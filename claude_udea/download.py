"""
Módulo de descarga: descarga grabaciones con yt-dlp.
Aislado para que cambios en otras partes no lo afecten.
"""

import json
import hashlib
import re
import subprocess
import sys
import shutil
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path


def get_archive_path(download_dir: Path) -> Path:
    return download_dir / ".download-archive.txt"


def is_downloaded(archive_path: Path, rec_id: str) -> bool:
    if not archive_path.exists():
        return False
    content = archive_path.read_text(encoding="utf-8")
    return rec_id in content


def download_one(url, output_dir, archive_path, skip_video=False, dry_run=False, skip_subs=False,
                 subs_only=False):
    """Descarga una grabación. Retorna 'ok', 'processing' o 'error'.

    `subs_only` re-descarga solo los subtítulos de Zoom aunque el rec_id ya esté
    en el archive (p. ej. tras respaldar subtítulos mal asignados).
    """
    if subs_only:
        skip_video, skip_subs = True, False
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(title)s [%(id)s].%(ext)s")

    rec_id = _extract_rec_id_from_url(url)
    before = {
        path.resolve() for path in output_dir.rglob("*")
        if path.is_file()
    } if output_dir.exists() else set()

    # Si los subtítulos ya existen, reparar un video faltante no debe re-descargarlos.
    write_subs = skip_video or not skip_subs

    cmd = [
        sys.executable, "-m", "yt_dlp",
        url,
        "-o", output_template,
        "--no-overwrites",
        "--retries", "3",
        "--fragment-retries", "3",
        "--no-warnings",
    ]
    if write_subs:
        cmd.extend([
            "--write-subs", "--all-subs",
            "--sub-format", "vtt/srt/best",
            "--convert-subs", "vtt",
        ])

    # A stale archive entry must not suppress repair of a missing video (or subs).
    if skip_video and not subs_only:
        cmd.extend(["--download-archive", str(archive_path)])
    else:
        cmd.extend(["--no-download-archive"])

    if skip_video:
        cmd.append("--skip-download")
    else:
        cmd.extend(["--concurrent-fragments", "4"])

    if dry_run:
        cmd.append("--simulate")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600,
        )
        if result.returncode == 0:
            if dry_run:
                return "ok"
            if skip_video:
                return "ok" if any(
                    path.is_file() and path.suffix.lower() in {".vtt", ".srt"}
                    and path.resolve() not in before
                    for path in output_dir.rglob("*")
                ) else "error"
            produced = [
                path for path in output_dir.rglob("*")
                if path.is_file() and path.resolve() not in before
                and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
                and path.stat().st_size > 0
            ]
            # --no-download-archive avoids stale skips; record successful repairs
            # only after the requested video is verified on disk.
            if produced:
                if rec_id and not is_downloaded(archive_path, rec_id):
                    with open(archive_path, "a", encoding="utf-8") as archive:
                        archive.write(f"zoom {rec_id}\n")
                return "ok"
            return "error"
        # Zoom aún procesando o página no disponible
        stderr = result.stderr or ""
        if "Unable to extract" in stderr or "is not a valid URL" in stderr:
            return "processing"
        return "error"
    except subprocess.TimeoutExpired:
        return "error"
    except Exception:
        return "error"


def _extract_rec_id_from_url(url: str) -> str:
    """Extrae el recording ID de una URL de Zoom: /rec/share/REC_ID o /rec/play/REC_ID."""
    match = re.search(r"/rec/(?:share|play)/([^?\s]+)", url)
    return match.group(1) if match else ""


def _extract_rec_id_from_filename(filename: str) -> str:
    """Extrae el recording ID de un nombre de archivo yt-dlp: 'Titulo [REC_ID].ext'."""
    match = re.search(r"\[([^\]]+)\]", filename)
    return match.group(1) if match else ""


def _recording_alias_ids(rec_id: str, rec_info: dict) -> list[str]:
    """IDs con los que puede aparecer un archivo de esta grabación.

    La clave del registro puede diferir del token de la URL porque los tokens de
    Zoom rotan entre ejecuciones; se aceptan la clave y el token de la URL.
    """
    ids = [rec_id]
    for key in ("url", "share_url"):
        token = _extract_rec_id_from_url(rec_info.get(key) or "")
        if token and token not in ids:
            ids.append(token)
    return ids


def _parse_recording_datetime(value):
    """Interpreta fechas ISO y formatos habituales de Moodle en español."""
    if not value:
        return None

    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass

    normalized = unicodedata.normalize("NFKD", text)
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    months = {
        "enero": "01", "ene": "01", "febrero": "02", "feb": "02",
        "marzo": "03", "mar": "03", "abril": "04", "abr": "04",
        "mayo": "05", "may": "05", "junio": "06", "jun": "06",
        "julio": "07", "jul": "07", "agosto": "08", "ago": "08",
        "septiembre": "09", "setiembre": "09", "sep": "09",
        "octubre": "10", "oct": "10", "noviembre": "11", "nov": "11",
        "diciembre": "12", "dic": "12",
    }
    for month, number in sorted(months.items(), key=lambda item: -len(item[0])):
        normalized = re.sub(rf"\b{month}\b", number, normalized)
    normalized = re.sub(r"^[a-z]+,\s*", "", normalized)
    normalized = re.sub(r"\bde\b", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    formats = (
        "%d %m %Y, %H:%M", "%d %m %Y %H:%M", "%d/%m/%Y, %H:%M",
        "%d/%m/%Y %H:%M", "%d %m %Y, %I:%M %p", "%d %m %Y %I:%M %p",
        "%d/%m/%Y, %I:%M %p", "%d/%m/%Y %I:%M %p", "%d %m %Y",
        "%d/%m/%Y", "%m %d, %Y, %I:%M %p", "%m %d, %Y",
    )
    for date_format in formats:
        try:
            return datetime.strptime(normalized, date_format)
        except ValueError:
            continue
    return None


def _recording_sort_key(item):
    rec_id, rec_info = item
    recording_date = _parse_recording_datetime(rec_info.get("start_date", ""))
    if recording_date is not None and recording_date.tzinfo is not None:
        recording_date = recording_date.astimezone(timezone.utc).replace(tzinfo=None)
    return (recording_date is None, recording_date or datetime.max, rec_id)


def _datetime_key(value):
    parsed = _parse_recording_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _filename_suffix(filename: str, rec_id: str) -> str:
    """Conserva la extensión y variantes de subtítulo después del ID."""
    if rec_id:
        marker = re.search(
            r"\[[^\]]*" + re.escape(rec_id) + r"[^\]]*\]",
            filename,
        )
        if marker:
            return filename[marker.end():]
    id_suffix = re.search(
        r"\[[^\]]+\](\.(?:whisper\.)?(?:transcript|chapter|cc)\.vtt|\.[^.]+)$",
        filename,
        re.IGNORECASE,
    )
    if id_suffix:
        return id_suffix.group(1)
    match = re.match(
        r"^(?:Fabrica Escuela - )?Clase #\d+ - (?:\d{4}-\d{2}-\d{2}|sin-fecha)(.*)$",
        filename,
        re.IGNORECASE,
    )
    if not match:
        return Path(filename).suffix

    # Las marcas de parte (' - Parte N', ' (N)') no son parte del sufijo: si se
    # conservaran, cada renombrado volvería a anexar 'Parte' ('Parte 1 - Parte 1').
    suffix = _PART_PREFIX_RE.sub("", match.group(1))
    legacy_type = re.match(r"\s*-\s*(video|chapter|transcript|cc)(.*)$", suffix, re.IGNORECASE)
    if legacy_type:
        kind, extension = legacy_type.groups()
        return f".{kind.lower()}{extension}" if kind.lower() != "video" else extension
    return suffix or Path(filename).suffix


_PART_MARKER = r"(?:\s-\sParte\s\d+|\s\(\d+\))"
_PART_PREFIX_RE = re.compile(rf"^{_PART_MARKER}+", re.IGNORECASE)
_PART_TAIL_RE = re.compile(rf"{_PART_MARKER}+$", re.IGNORECASE)
_VARIANT_SUFFIX_RE = re.compile(
    r"(\.whisper\.transcript\.vtt|\.transcript\.vtt|\.cc\.vtt|\.chapter\.vtt|\.[A-Za-z0-9]+)$",
    re.IGNORECASE,
)
_CANONICAL_RE = re.compile(
    r"^(?P<fabrica>Fabrica Escuela - )?Clase #(?P<number>\d+) - (?P<date>\d{4}-\d{2}-\d{2}|sin-fecha)$",
    re.IGNORECASE,
)


def _split_variant(name: str) -> tuple[str, str]:
    """Separa 'Clase #1 - 2026-09-01 - Parte 2.cc.vtt' en (stem, '.cc.vtt')."""
    match = _VARIANT_SUFFIX_RE.search(name)
    if not match:
        return name, ""
    return name[:match.start()], match.group(1)


def _split_part(name: str) -> tuple[str, tuple[int, ...], str]:
    """Devuelve (base, partes, sufijo) quitando TODAS las marcas de parte repetidas.

    'Clase #15 - 2026-09-29 - Parte 1 - Parte 2.mp4' -> ('Clase #15 - 2026-09-29', (1, 2), '.mp4').
    Las marcas anidadas son colisiones viejas; la tupla sirve para ordenarlas.
    """
    stem, suffix = _split_variant(name)
    match = _PART_TAIL_RE.search(stem)
    if not match:
        return stem, (), suffix
    numbers = tuple(int(value) for value in re.findall(r"(\d+)", match.group(0)))
    return stem[:match.start()], numbers, suffix


def _parse_canonical(name: str):
    """Interpreta un nombre canónico. Retorna dict o None si no es canónico."""
    base, parts, suffix = _split_part(name)
    match = _CANONICAL_RE.match(base)
    if not match:
        return None
    return {
        "base": base,
        "parts": parts,
        "suffix": suffix,
        "category": "fabrica_escuela" if match.group("fabrica") else "course",
        "number": int(match.group("number")),
        "date": match.group("date"),
    }


def _part_label(part) -> str:
    return f" - Parte {part}" if part else ""


def _slot_name(meta: dict, part, suffix: str) -> str:
    """Generador único de nombres: base canónica + ' - Parte N' opcional + sufijo."""
    return f"{recording_filename(meta)}{_part_label(part)}{suffix}"


def _next_part_number(folder: Path, meta: dict, suffix: str, reserved=()) -> int:
    """Siguiente slot de video disponible, siempre desde la base canónica limpia."""
    base = recording_filename(meta)
    reserved_names = {str(path).lower() for path in reserved}
    existing_parts = []
    pattern = re.compile(rf"^{re.escape(base)} - Parte (\d+){re.escape(suffix)}$", re.I)
    if folder.is_dir():
        for path in folder.iterdir():
            match = pattern.match(path.name)
            if match:
                existing_parts.append(int(match.group(1)))
    number = max(existing_parts, default=0) + 1
    while str((folder / _slot_name(meta, number, suffix)).resolve()).lower() in reserved_names:
        number += 1
    return number


def _name_conflicts_with(name: str, meta: dict) -> bool:
    """True si el nombre lleva fecha o categoría canónica distinta a la del registro.

    La fecha es el ancla: el número de clase cambia al renumerar, la fecha no.
    """
    parsed = _parse_canonical(re.sub(r"\s*\[[^\]]+\]", "", name).strip())
    if not parsed or parsed["date"] == "sin-fecha":
        return False
    expected_date = _parse_date_prefix(meta.get("start_date", ""))
    if expected_date != "sin-fecha" and parsed["date"] != expected_date:
        return True
    return parsed["category"] != meta.get("class_category", "course")


def _class_number_from_filename(filename: str):
    match = re.match(
        r"^(?:Fabrica Escuela - )?Clase #(\d+) - ",
        filename,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def _class_key_from_filename(filename: str):
    """(categoría, número, fecha|'') de un nombre 'Clase #N - YYYY-MM-DD...' o None."""
    match = re.match(
        r"^(Fabrica Escuela - )?Clase #(\d+) - (\d{4}-\d{2}-\d{2})?",
        filename,
        re.IGNORECASE,
    )
    if not match:
        return None
    category = "fabrica_escuela" if match.group(1) else "course"
    return category, int(match.group(2)), match.group(3) or ""


def _class_category(title: str) -> str:
    normalized_title = unicodedata.normalize("NFKD", title)
    normalized_title = normalized_title.encode("ascii", "ignore").decode("ascii").lower()
    return (
        "fabrica_escuela"
        if "fabrica de escuela" in normalized_title or "fabrica escuela" in normalized_title
        else "course"
    )


def _class_category_from_filename(filename: str) -> str:
    return "fabrica_escuela" if filename.lower().startswith("fabrica escuela - ") else "course"


def _class_filename(meta: dict, date_str: str) -> str:
    category = "Fabrica Escuela - " if meta.get("class_category") == "fabrica_escuela" else ""
    return f"{category}Clase #{meta['class_number']} - {date_str}"


def recording_filename(meta: dict, suffix: str = "") -> str:
    return f"{_class_filename(meta, _parse_date_prefix(meta.get('start_date', '')))}{suffix}"


_INCOMPLETE_RE = re.compile(r"\.(?:part|tmp|ytdl)$", re.IGNORECASE)
_LOOSE_CLASS_RE = re.compile(
    r"^(?:Fabrica Escuela - )?Clase #(\d+) - (\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_ID_MARKER_RE = re.compile(r"\[[^\]]+\]")


def _recording_category(filename: str, suffix: str, source: Path | None = None) -> str:
    lowered = (filename + suffix).lower()
    if _INCOMPLETE_RE.search(lowered):
        # Descargas interrumpidas o copias temporales: no son videos ni transcripciones
        return "incompletos"
    if lowered.endswith(".vtt"):
        is_whisper = ".whisper.transcript." in lowered
        if not is_whisper and source and source.is_file():
            try:
                is_whisper = "generada localmente con faster-whisper" in source.read_text(
                    encoding="utf-8", errors="replace"
                )[:500]
            except OSError:
                pass
        return "transcripts/whisper" if is_whisper else "transcripts/zoom"
    if Path(lowered).suffix in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}:
        return "videos"
    return ""


def _class_category_for(rec_info: dict, fabrica_meeting_ids: set | None = None) -> str:
    """Clasifica una grabación: el meeting_id es la señal primaria; el título es fallback.

    El título del meeting de Zoom no es confiable (la sala puede renombrarse a mitad
    de semestre y ambas salas registran la misma sesión), así que cuando el curso
    configura `fabrica_meeting_ids`, el meeting_id decide la categoría.
    """
    meeting_id = str(rec_info.get("meeting_id", "") or "")
    if meeting_id and fabrica_meeting_ids:
        return "fabrica_escuela" if meeting_id in fabrica_meeting_ids else "course"
    return _class_category(rec_info.get("title", ""))


def _course_fabrica_ids(course_options: dict | None, slug: str) -> set:
    options = (course_options or {}).get(slug) or {}
    return {str(value) for value in options.get("fabrica_meeting_ids", []) or []}


def _build_rec_id_map(recordings: dict, course_options: dict | None = None) -> dict:
    """Mapa de rec_id -> {slug, course_name, start_date, duration, title}."""
    id_map = {}
    for slug, course in recordings.items():
        fabrica_meeting_ids = _course_fabrica_ids(course_options, slug)
        ordered_recordings = sorted(
            course.get("recordings", {}).items(), key=_recording_sort_key
        )
        class_numbers = {}
        class_by_datetime = {}
        for rec_id, rec_info in ordered_recordings:
            category = _class_category_for(rec_info, fabrica_meeting_ids)
            date_key = _datetime_key(rec_info.get("start_date", ""))
            category_date_key = (category, date_key)
            if date_key is not None and category_date_key in class_by_datetime:
                recording_class = class_by_datetime[category_date_key]
            else:
                class_numbers[category] = class_numbers.get(category, 0) + 1
                recording_class = class_numbers[category]
                if date_key is not None:
                    class_by_datetime[category_date_key] = recording_class
            id_map[rec_id] = {
                "slug": slug,
                "course_name": course.get("name", slug),
                "start_date": rec_info.get("start_date", ""),
                "duration_minutes": rec_info.get("duration_minutes", 0),
                "title": rec_info.get("title", ""),
                "class_category": category,
                "class_number": recording_class,
            }
    return id_map


def _parse_date_prefix(start_date: str) -> str:
    """Convierte la fecha de Moodle a YYYY-MM-DD para nombres de archivo."""
    parsed = _parse_recording_datetime(start_date)
    return parsed.strftime("%Y-%m-%d") if parsed else "sin-fecha"


def _inject_vtt_metadata(vtt_content: str, course_name: str, date_str: str,
                         duration_minutes: int, title: str) -> str:
    """Inyecta un bloque NOTE con metadata después del header WEBVTT."""
    note_block = (
        f"\nNOTE\n"
        f"Fecha de clase: {date_str}\n"
        f"Asignatura: {course_name}\n"
        f"Tema: {title}\n"
        f"Duración: {duration_minutes} min\n"
    )
    if vtt_content.startswith("WEBVTT"):
        first_newline = vtt_content.index("\n")
        return vtt_content[:first_newline] + "\n" + note_block + vtt_content[first_newline:]
    return note_block + "\n" + vtt_content


def copy_transcripts(download_dir: Path, recordings: dict = None, course_options: dict | None = None,
                     course_slugs: list[str] | None = None) -> int:
    """
    Copia VTTs a carpeta centralizada con fecha en el nombre,
    metadata inyectada en el VTT y genera index.json.
    Retorna cantidad procesada.
    """
    transcripts_dir = download_dir / "transcripts"

    # Si no hay recordings, cargar desde disco
    if recordings is None:
        rec_path = download_dir.parent / "recordings.json"
        if rec_path.exists():
            with open(rec_path, "r", encoding="utf-8") as f:
                recordings = json.load(f)
        else:
            recordings = {}

    id_map = _build_rec_id_map(recordings, course_options)
    count = 0
    index = {}
    selected = set(course_slugs) if course_slugs is not None else None
    index_path = transcripts_dir / "index.json"
    if selected is not None and index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for slug in selected:
            index.pop(slug, None)

    # Limpiar carpeta de transcripts para regenerar con nuevos nombres
    if transcripts_dir.exists():
        for child in transcripts_dir.iterdir():
            if selected is not None and child.name not in selected:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            elif child.name != ".gitkeep":
                child.unlink()

    def process_vtt(vtt_file: Path, course_slug: str):
        nonlocal count
        rec_id = _extract_rec_id_from_filename(vtt_file.name)
        meta = id_map.get(rec_id, {})
        if not rec_id:
            class_number = _class_number_from_filename(vtt_file.name)
            if class_number:
                category = _class_category_from_filename(vtt_file.name)
                candidates = [
                    candidate for rec_id_key, candidate in id_map.items()
                    if candidate["slug"] == course_slug
                    and candidate["class_category"] == category
                    and candidate["class_number"] == class_number
                    and not _name_conflicts_with(vtt_file.name, candidate)
                ]
                meta = candidates[0] if len(candidates) == 1 else {}
        if rec_id and not meta:
            return

        date_str = _parse_date_prefix(meta.get("start_date", ""))
        course_name = meta.get("course_name", course_slug)
        duration = meta.get("duration_minutes", 0)
        title = meta.get("title", "")

        part = None
        if meta:
            suffix = _filename_suffix(vtt_file.name, rec_id)
            if not rec_id:
                parts = _split_part(vtt_file.name)[1]
                part = parts[-1] if parts else None
            new_name = _slot_name(meta, part, suffix)
        else:
            new_name = f"{date_str}_{vtt_file.name}"
        course_transcripts = transcripts_dir / course_slug
        course_transcripts.mkdir(parents=True, exist_ok=True)
        dest = course_transcripts / new_name
        if dest.exists():
            # Las carpetas de curso ya tienen nombres únicos por slot; una colisión
            # aquí es un duplicado, no una transcripción nueva: no se copia dos veces.
            print(f"  ⚠ Transcripción duplicada en el índice central, se omite: {vtt_file}")
            return

        vtt_content = vtt_file.read_text(encoding="utf-8", errors="replace")
        enriched = _inject_vtt_metadata(vtt_content, course_name, date_str, duration, title)
        dest.write_text(enriched, encoding="utf-8")
        count += 1

        vtt_type = "cc" if ".cc." in vtt_file.name.lower() else (
            "transcript" if ".transcript." in vtt_file.name.lower() else "chapter"
        )

        if course_slug not in index:
            index[course_slug] = {"course_name": course_name, "files": []}
        index[course_slug]["files"].append({
            "file": new_name,
            "date": date_str,
            "class_number": meta.get("class_number"),
            "part": part,
            "topic": title,
            "duration_minutes": duration,
            "type": vtt_type,
            "source": "faster-whisper" if ".whisper.transcript." in vtt_file.name.lower() else "zoom",
        })

    for course_dir in download_dir.iterdir():
        if not course_dir.is_dir() or course_dir.name in ("transcripts", ".browser-data"):
            continue
        if selected is not None and course_dir.name not in selected:
            continue
        slug = course_dir.name
        for vtt_file in course_dir.rglob("*.vtt"):
            rel_parts = vtt_file.relative_to(course_dir).parts
            if any(part in {".claude-udea-backup", "sin-clasificar", "incompletos"} for part in rel_parts):
                continue
            process_vtt(vtt_file, slug)

    # Sort same-day entries by class and part instead of lexical filename order.
    for slug in index:
        if selected is not None and slug not in selected:
            continue
        index[slug]["files"].sort(key=lambda x: (
            x["date"],
            0 if x.get("class_number") is not None else 1,
            x.get("class_number") if x.get("class_number") is not None else 0,
            x.get("part") or 0,
            x["file"].casefold(),
        ))

    # Escribir index.json
    if index or selected is not None:
        index_path = transcripts_dir / "index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    return count


def _restore_stale_organization_temps(download_dir: Path) -> None:
    for temporary in download_dir.rglob(".*.tmp"):
        if not temporary.is_file() or not temporary.name.startswith("."):
            continue
        name_parts = temporary.name[1:-4].rsplit(".", 1)
        if len(name_parts) != 2:
            continue
        intended_name, temp_id = name_parts
        try:
            uuid.UUID(hex=temp_id)
        except ValueError:
            continue
        destination = temporary.with_name(intended_name)
        if not destination.exists():
            temporary.replace(destination)
        elif temporary.read_bytes() == destination.read_bytes():
            temporary.unlink()

    for temporary in download_dir.rglob("*.whisper.transcript.vtt.tmp"):
        destination = temporary.with_name(temporary.name[:-4])
        try:
            content = temporary.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not content.startswith("WEBVTT") or (
            "generada localmente con faster-whisper" not in content[:500]
        ):
            continue
        if not destination.exists():
            temporary.replace(destination)
        elif temporary.read_bytes() == destination.read_bytes():
            temporary.unlink()


def rename_downloads(download_dir: Path, recordings: dict, course_options: dict | None = None) -> int:
    """Renombra descargas por clase y guarda sus rutas para futuras renumeraciones."""
    for slug in recordings:
        course_dir = download_dir / slug
        if course_dir.is_dir():
            _restore_stale_organization_temps(course_dir)
    if not recordings:
        _restore_stale_organization_temps(download_dir)
    id_map = _build_rec_id_map(recordings, course_options)
    renamed_count = 0

    for slug, course in recordings.items():
        course_dir = download_dir / slug
        if not course_dir.is_dir():
            continue
        for category_dir in (
            "videos",
            "transcripts/zoom",
            "transcripts/whisper",
        ):
            (course_dir / category_dir).mkdir(parents=True, exist_ok=True)

        resolved_plans, record_files = _plan_course_renames(
            course_dir, slug, course, id_map,
        )

        staged_plans = []
        for source, destination, rec_id, rec_info, organized_files in resolved_plans:
            if source == destination:
                organized_files.append(destination.relative_to(course_dir).as_posix())
                continue
            # Verificar que el archivo fuente existe
            if not source.exists():
                print(f"  ⚠ Archivo no encontrado, se omite: {source}")
                continue
            # Crear directorio destino primero
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Usar nombre temporal en el directorio destino
            temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
            try:
                source.rename(temporary)
                staged_plans.append(
                    (temporary, destination, rec_id, rec_info, organized_files)
                )
            except OSError as e:
                print(f"  ⚠ Error moviendo {source.name}: {e}")
                continue

        for temporary, destination, rec_id, rec_info, organized_files in staged_plans:
            try:
                if destination.exists():
                    raise FileExistsError(f"El destino apareció durante la organización: {destination}")
                temporary.rename(destination)
                renamed_count += 1
                organized_files.append(destination.relative_to(course_dir).as_posix())
            except OSError as e:
                print(f"  ⚠ Error renombrando {temporary.name}: {e}")

        for rec_id, (rec_info, organized_files) in record_files.items():
            rec_info["organized_files"] = sorted(set(organized_files))

        _sweep_unclassified(course_dir)

    return renamed_count


_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
_CATEGORY_DIRS = ("videos", "transcripts/zoom", "transcripts/whisper")
_ZOOM_SUB_SUFFIXES = (".cc.vtt", ".transcript.vtt")


def _is_backup_path(course_dir: Path, path: Path) -> bool:
    try:
        return ".claude-udea-backup" in path.relative_to(course_dir).parts
    except ValueError:
        return ".claude-udea-backup" in path.parts


def _is_zoom_sub(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith(_ZOOM_SUB_SUFFIXES) and ".whisper.transcript." not in lowered


class _ContentIndex:
    """Índice de contenido por curso: compara por tamaño y solo hashea si coincide."""

    def __init__(self):
        self._by_size: dict[int, list[Path]] = {}
        self._digests: dict[Path, tuple] = {}

    def digest(self, path: Path) -> str:
        try:
            stat = path.stat()
        except OSError:
            return ""
        cached = self._digests.get(path)
        if cached and cached[:2] == (stat.st_size, stat.st_mtime_ns):
            return cached[2]
        value = _file_sha256(path)
        self._digests[path] = (stat.st_size, stat.st_mtime_ns, value)
        return value

    def add(self, path: Path) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            return
        bucket = self._by_size.setdefault(size, [])
        if path not in bucket:
            bucket.append(path)

    def discard(self, path: Path) -> None:
        for bucket in self._by_size.values():
            if path in bucket:
                bucket.remove(path)

    def find_identical(self, source: Path) -> Path | None:
        try:
            size = source.stat().st_size
        except OSError:
            return None
        candidates = [path for path in self._by_size.get(size, []) if path != source]
        if not candidates:
            return None
        source_digest = self.digest(source)
        for candidate in candidates:
            if candidate.exists() and self.digest(candidate) == source_digest:
                return candidate
        return None


def _raw_key(source: Path, suffix: str):
    """Clave que agrupa video y subtítulos de una misma descarga ('Titulo [id]')."""
    name = source.name
    if suffix and name.lower().endswith(suffix.lower()):
        name = name[:-len(suffix)]
    return source.parent, name.lower()


def _plan_course_renames(course_dir: Path, slug: str, course: dict, id_map: dict):
    """Decide destino de cada archivo de un curso.

    Reglas:
    - La fecha (y categoría) del nombre canónico es el ancla: una ruta de
      `organized_files` con fecha de otra clase no se reclama ni se renombra.
    - 'Parte N' se genera siempre desde la base canónica limpia y solo para
      videos de contenido distinto; los subtítulos siguen el slot de su video.
    - Contenido de video/subtítulo Zoom idéntico a otro ya organizado va a respaldo.
    """
    all_files = [
        path for path in course_dir.rglob("*")
        if path.is_file() and not _is_backup_path(course_dir, path)
    ]
    canonical_files: dict[str, list[Path]] = {}
    taken_stems: set[str] = set()
    for category in _CATEGORY_DIRS:
        folder = course_dir / category
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if not path.is_file():
                continue
            base, parts, suffix = _split_part(path.name)
            taken_stems.add(path.name[:len(path.name) - len(suffix)].lower())
            canonical_files.setdefault(base.lower(), []).append(path)

    loose_sources = _loose_sources_by_recording(course_dir, slug, id_map)
    record_files: dict = {}
    claims = []
    claimed: set[Path] = set()
    for rec_id, rec_info in course.get("recordings", {}).items():
        meta = id_map.get(rec_id)
        if not meta:
            continue
        base = recording_filename(meta)
        organized: list[Path] = []
        sources: dict[Path, tuple] = {}
        for relative_name in rec_info.get("organized_files", []):
            source = course_dir / relative_name
            if not source.is_file() or _is_backup_path(course_dir, source):
                continue
            if _name_conflicts_with(source.name, meta):
                # Ruta obsoleta que apunta a otra fecha/categoría: no se reclama.
                continue
            if _ID_MARKER_RE.search(source.name):
                sources[source] = (_filename_suffix(source.name, rec_id), None)
                continue
            source_base, parts, _ = _split_part(source.name)
            if source_base == base:
                organized.append(source)
            else:
                # Numeración obsoleta / 'sin-fecha' / formato legado: re-normalizar.
                sources[source] = (_filename_suffix(source.name, ""), parts[-1] if parts else None)

        for path in canonical_files.get(base.lower(), []):
            if path not in organized and path not in claimed and _split_part(path.name)[0] == base:
                organized.append(path)

        for source, value in loose_sources.get(rec_id, {}).items():
            sources.setdefault(source, value)

        alias_ids = _recording_alias_ids(rec_id, rec_info)
        for source in all_files:
            if source in sources or source in organized:
                continue
            if _name_conflicts_with(source.name, meta):
                continue
            if any(f"[{alias}" in source.name for alias in alias_ids):
                sources[source] = (_filename_suffix(source.name, rec_id), None)

        organized = [path for path in organized if path not in claimed]
        sources = {path: value for path, value in sources.items() if path not in claimed}
        if not sources and not organized:
            if rec_info.get("organized_files"):
                rec_info["organized_files"] = []
            continue
        claimed.update(organized)
        claimed.update(sources)
        organized_files = [path.relative_to(course_dir).as_posix() for path in organized]
        record_files[rec_id] = (rec_info, organized_files)
        for source, (suffix, part) in sources.items():
            claims.append((source, suffix, part, rec_id))

    source_paths = {claim[0] for claim in claims}
    video_index = _ContentIndex()
    subs_index = _ContentIndex()
    for path in (course_dir / "videos").glob("*") if (course_dir / "videos").is_dir() else []:
        if path.is_file() and path not in source_paths:
            video_index.add(path)
    zoom_dir = course_dir / "transcripts" / "zoom"
    for path in zoom_dir.glob("*") if zoom_dir.is_dir() else []:
        if path.is_file() and path not in source_paths and _is_zoom_sub(path.name):
            subs_index.add(path)

    def category_of(claim):
        source, suffix = claim[0], claim[1]
        return _recording_category(source.name, suffix, source)

    # Videos primero: fijan el slot (parte) que heredan sus subtítulos.
    claims.sort(key=lambda claim: 0 if category_of(claim) == "videos" else 1)

    reserved: set[Path] = set()
    sibling_parts: dict = {}
    rejected_siblings = set()
    indexed_destinations = {}
    plans = []

    def occupied(destination: Path) -> bool:
        return destination in reserved or (
            destination.exists() and destination not in source_paths
        )

    for source, suffix, part, rec_id in claims:
        if not source.exists():
            continue
        rec_info, organized_files = record_files[rec_id]
        meta = id_map[rec_id]
        base = recording_filename(meta)
        category = _recording_category(source.name, suffix, source)
        target_dir = course_dir / category if category else source.parent
        key = _raw_key(source, suffix)
        if category != "videos" and key in rejected_siblings:
            _backup_duplicate(course_dir, source, rec_id, "", "misassigned-transcripts")
            continue

        if category in ("incompletos", ""):
            destination = target_dir / (source.name if category else _slot_name(meta, part, suffix))
            if destination != source and occupied(destination):
                destination = target_dir / f"{Path(destination.name).stem} ({uuid.uuid4().hex[:8]}){destination.suffix}"
        else:
            if category != "videos" and key in sibling_parts:
                part = sibling_parts[key]
            destination = target_dir / _slot_name(meta, part, suffix)

        if destination == source:
            reserved.add(destination)
            organized_files.append(destination.relative_to(course_dir).as_posix())
            continue

        if category == "videos":
            duplicate = video_index.find_identical(source)
            if duplicate is not None:
                keeper = indexed_destinations.get(duplicate, duplicate)
                keeper_base, keeper_parts, _ = _split_part(keeper.name)
                _backup_duplicate(course_dir, source, rec_id, video_index.digest(duplicate))
                if keeper_base == base:
                    sibling_parts[key] = keeper_parts[-1] if keeper_parts else None
                    organized_files.append(keeper.relative_to(course_dir).as_posix())
                else:
                    rejected_siblings.add(key)
                    _flag_suspect_url(rec_info, source, duplicate)
                continue
            if occupied(destination):
                number = _next_part_number(
                    target_dir, meta, suffix,
                    reserved=(path for path in reserved if path.parent == target_dir),
                )
                destination, part = target_dir / _slot_name(meta, number, suffix), number
                while occupied(destination) or destination.name[:len(destination.name) - len(suffix)].lower() in taken_stems:
                    number += 1
                    destination, part = target_dir / _slot_name(meta, number, suffix), number
            sibling_parts[key] = part
            indexed_destinations[source] = destination
            video_index.add(source)
        elif category in ("transcripts/zoom", "transcripts/whisper"):
            if occupied(destination):
                if destination.exists() and destination not in reserved:
                    same, digest = _files_identical(source, destination)
                    if same:
                        _backup_duplicate(course_dir, source, rec_id, digest, "identical-transcripts")
                        organized_files.append(destination.relative_to(course_dir).as_posix())
                        continue
                # Un subtítulo nunca crea una 'Parte' propia: se respalda y se conserva el existente.
                _backup_duplicate(course_dir, source, rec_id, "", "misassigned-transcripts")
                continue
            if category == "transcripts/zoom" and _is_zoom_sub(source.name):
                duplicate = subs_index.find_identical(source)
                if duplicate is not None and _split_part(indexed_destinations.get(duplicate, duplicate).name)[0] != base:
                    _backup_duplicate(
                        course_dir, source, rec_id, subs_index.digest(duplicate),
                        "suspicious-transcripts",
                    )
                    _flag_suspect_url(rec_info, source, duplicate)
                    continue
                subs_index.add(source)
                indexed_destinations[source] = destination

        reserved.add(destination)
        taken_stems.add(destination.name[:len(destination.name) - len(suffix)].lower())
        plans.append((source, destination, rec_id, rec_info, organized_files))

    return plans, record_files


def _flag_suspect_url(rec_info: dict, source: Path, duplicate: Path) -> None:
    """Marca la URL actual como sospechosa: devolvió contenido de otra clase."""
    url = rec_info.get("url") or rec_info.get("share_url") or ""
    rec_info["suspect_url"] = url
    print(
        f"  ⚠ URL sospechosa: '{source.name}' es idéntico a '{duplicate.name}' "
        "(otra clase); se movió a respaldo y no se re-descargará con esta URL."
    )


def _loose_sources_by_recording(course_dir: Path, slug: str, id_map: dict) -> dict:
    """Asocia archivos de la raíz del curso sin ID (p. ej. 'Fabrica Escuela - Clase #3 - 2026-08-26.mp4')
    con su grabación por categoría, número de clase y fecha. Retorna {ruta: (sufijo, parte)}."""
    index = {}
    for rec_id, meta in id_map.items():
        if meta["slug"] != slug:
            continue
        date_str = _parse_date_prefix(meta.get("start_date", ""))
        index[(meta["class_category"], meta["class_number"], date_str)] = rec_id

    loose = {}
    for entry in course_dir.iterdir():
        if not entry.is_file() or _ID_MARKER_RE.search(entry.name):
            continue
        match = _LOOSE_CLASS_RE.match(entry.name)
        if not match:
            continue
        key = (_class_category_from_filename(entry.name), int(match.group(1)), match.group(2))
        rec_id = index.get(key)
        if rec_id:
            parts = _split_part(entry.name)[1]
            loose.setdefault(rec_id, {})[entry] = (
                _filename_suffix(entry.name, ""), parts[-1] if parts else None,
            )
    return loose


_SWEEP_SUFFIXES = {
    ".mp4", ".mkv", ".webm", ".mov", ".m4v", ".wav", ".vtt", ".srt",
    ".txt", ".json", ".csv", ".part", ".tmp", ".ytdl",
}


def _sweep_unclassified(course_dir: Path) -> None:
    """Mueve archivos sueltos de la raíz a su carpeta según tipo, o a sin-clasificar."""
    for entry in course_dir.iterdir():
        if not entry.is_file() or entry.suffix.lower() not in _SWEEP_SUFFIXES:
            continue
        lowered = entry.name.lower()
        if _INCOMPLETE_RE.search(entry.name):
            category = "incompletos"
        elif lowered.endswith(".vtt"):
            is_whisper = ".whisper.transcript." in lowered
            if not is_whisper:
                try:
                    is_whisper = "generada localmente con faster-whisper" in entry.read_text(
                        encoding="utf-8", errors="replace"
                    )[:500]
                except OSError:
                    pass
            category = "transcripts/whisper" if is_whisper else "transcripts/zoom"
        else:
            category = "sin-clasificar"
        target_dir = course_dir / category
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / entry.name
        if destination.exists():
            # No dejar nada suelto en la raíz: si es idéntico se descarta el duplicado;
            # si difiere se conserva con un sufijo único.
            if _files_identical(entry, destination)[0]:
                entry.unlink()
                continue
            destination = target_dir / f"{entry.stem} ({uuid.uuid4().hex[:8]}){entry.suffix}"
        entry.rename(destination)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _files_identical(left: Path, right: Path) -> tuple[bool, str]:
    try:
        if left.stat().st_size != right.stat().st_size:
            return False, ""
        left_hash = _file_sha256(left)
        right_hash = _file_sha256(right)
        return left_hash == right_hash, left_hash if left_hash == right_hash else ""
    except OSError:
        return False, ""


def _backup_duplicate(
    course_dir: Path, source: Path, rec_id: str, digest: str, reason: str = "identical-videos",
) -> Path:
    """Mueve `source` a `.claude-udea-backup/<reason>/` (nunca borra contenido único)."""
    backup_dir = course_dir / ".claude-udea-backup" / reason
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / source.name
    stem, suffix = _split_variant(source.name)
    number = 1
    while destination.exists():
        if _files_identical(source, destination)[0]:
            source.unlink()
            return destination
        destination = backup_dir / f"{stem} ({number}){suffix}"
        number += 1
    manifest_path = backup_dir / "manifest.jsonl"
    entry = {
        "source": source.relative_to(course_dir).as_posix(),
        "backup": destination.relative_to(course_dir).as_posix(),
        "recording_id": rec_id,
        "sha256": digest,
        "reason": reason,
    }
    with manifest_path.open("a", encoding="utf-8") as manifest:
        manifest.write(json.dumps(entry, ensure_ascii=False) + "\n")
    source.replace(destination)
    return destination


def backfill_recording_metadata(course_dir: Path, course: dict, links: list[dict]) -> int:
    """Asocia archivos antiguos con metadata por creation_time exacto del MP4."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not course_dir.is_dir():
        return 0

    videos_by_datetime = {}
    for video in course_dir.rglob("*.mp4"):
        try:
            result = subprocess.run(
                [
                    ffprobe, "-v", "error", "-show_entries",
                    "format_tags=creation_time", "-of", "json", str(video),
                ],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=15,
            )
            if result.returncode != 0:
                continue
            tags = json.loads(result.stdout).get("format", {}).get("tags", {})
            date_key = _datetime_key(tags.get("creation_time", ""))
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            continue
        if date_key is not None:
            videos_by_datetime.setdefault(date_key, []).append(video)

    if not videos_by_datetime:
        return 0

    owners = {}
    records_by_datetime = {}
    for rec_info in course.get("recordings", {}).values():
        date_key = _datetime_key(rec_info.get("start_date", ""))
        if date_key is not None:
            records_by_datetime.setdefault(date_key, []).append(rec_info)
        for relative_name in rec_info.get("organized_files", []):
            key = str(relative_name).replace("\\", "/").casefold()
            owners.setdefault(key, []).append(rec_info)

    link_dates = {
        _datetime_key(link.get("start_date", ""))
        for link in links
        if _datetime_key(link.get("start_date", "")) is not None
    }
    metadata_links = list(links)
    for date_key, rec_infos in records_by_datetime.items():
        if date_key in link_dates:
            continue
        rec_info = rec_infos[0]
        metadata_links.append({
            "start_date": rec_info.get("start_date", ""),
            "title": rec_info.get("title", ""),
            "duration_minutes": rec_info.get("duration_minutes", 0),
        })

    backfilled = 0
    for link in metadata_links:
        date_key = _datetime_key(link.get("start_date", ""))
        matching_videos = videos_by_datetime.get(date_key, [])
        if not matching_videos:
            continue

        assets = set(matching_videos)
        class_keys = set()
        undated_keys = set()
        recording_ids = set()
        for video in matching_videos:
            key = _class_key_from_filename(video.name)
            if key is not None:
                class_keys.add(key)
                undated_keys.add(key[:2])
            rec_id = _extract_rec_id_from_filename(video.name)
            if rec_id:
                recording_ids.add(rec_id)

        for asset in course_dir.rglob("*"):
            if not asset.is_file() or _is_backup_path(course_dir, asset):
                continue
            rec_id = _extract_rec_id_from_filename(asset.name)
            key = _class_key_from_filename(asset.name)
            # El número de clase solo no basta: debe coincidir categoría y fecha
            # (si el nombre la trae); si no, se arrastran archivos de otras clases.
            matches_class = key is not None and (
                key in class_keys if key[2] else key[:2] in undated_keys
            )
            if matches_class or (rec_id and rec_id in recording_ids):
                assets.add(asset)

        asset_names = sorted(
            asset.relative_to(course_dir).as_posix() for asset in assets
        )
        matching_records = {
            id(rec_info): rec_info
            for rec_info in records_by_datetime.get(date_key, [])
        }
        unowned_assets = []
        for relative_name in asset_names:
            asset_owners = owners.get(relative_name.casefold(), [])
            if asset_owners:
                for rec_info in asset_owners:
                    matching_records[id(rec_info)] = rec_info
            else:
                unowned_assets.append(relative_name)

        if matching_records:
            for index, rec_info in enumerate(matching_records.values()):
                rec_info["start_date"] = link["start_date"]
                rec_info["title"] = link.get("title") or rec_info.get("title", "")
                rec_info["duration_minutes"] = link.get(
                    "duration_minutes", rec_info.get("duration_minutes", 0)
                )
                existing_files = set(rec_info.get("organized_files", []))
                if index == 0:
                    existing_files.update(unowned_assets)
                rec_info["organized_files"] = sorted(existing_files)
                if any(Path(name).suffix.lower() == ".mp4" for name in rec_info["organized_files"]):
                    rec_info["downloaded"] = True
                backfilled += 1
        else:
            link["_existing_files"] = asset_names
            link["_already_downloaded"] = True
            backfilled += 1

    return backfilled


# ─── Reparación de nombres y duplicados ya presentes en disco ──────────────

_EMPTY_VIDEO_BYTES = 1024 * 1024
_EMPTY_VIDEO_SECONDS = 60
_EMPTY_VTT_BYTES = 100
_OWNER_TOLERANCE_SECONDS = 600
_REBASE_PART_OFFSET = 1_000_000


def _probe_video(path: Path) -> tuple:
    """(duración en segundos | None, creation_time naive-UTC | None) vía ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None, None
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_entries",
                "format=duration:format_tags=creation_time", "-of", "json", str(path),
            ],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
        if result.returncode != 0:
            return None, None
        info = json.loads(result.stdout).get("format", {})
        raw_duration = info.get("duration")
        duration = float(raw_duration) if raw_duration not in (None, "", "N/A") else None
        created = _datetime_key((info.get("tags") or {}).get("creation_time", ""))
        return duration, created
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None, None


def _ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


class _RepairAsset:
    __slots__ = ("origin", "category", "base", "parts", "suffix", "size", "removed", "rec_id")

    def __init__(self, origin: Path, category: str, base: str, parts: tuple, suffix: str,
                 size: int, rec_id: str | None):
        self.origin = origin
        self.category = category
        self.base = base
        self.parts = parts
        self.suffix = suffix
        self.size = size
        self.removed = None
        self.rec_id = rec_id

    @property
    def slot(self):
        return self.base, self.parts

    @property
    def is_video(self) -> bool:
        return self.category == "videos"

    def final_name(self) -> str:
        return f"{self.base}{''.join(_part_label(part) for part in self.parts)}{self.suffix}"


def repair_course(course_dir: Path, course: dict, id_map: dict, dry_run: bool = False) -> dict:
    """Repara un curso ya organizado: 'Parte' repetidas, duplicados entre clases,
    subtítulos huérfanos/mal asignados y grabaciones vacías.

    Nunca borra: todo lo descartado va a `.claude-udea-backup/<motivo>/` con
    manifest. Con `dry_run` solo devuelve el plan. Retorna un reporte con
    `actions`, `warnings` y `flags` (marcas por grabación).
    """
    report = {"actions": [], "warnings": [], "flags": {}}
    if not course_dir.is_dir():
        return report

    recordings = course.get("recordings", {})
    metas = {rec_id: id_map[rec_id] for rec_id in recordings if rec_id in id_map}
    base_of = {rec_id: recording_filename(meta) for rec_id, meta in metas.items()}
    rec_by_base: dict[str, list[str]] = {}
    by_category_date: dict[tuple, list[str]] = {}
    for rec_id, meta in metas.items():
        rec_by_base.setdefault(base_of[rec_id], []).append(rec_id)
        key = (meta["class_category"], _parse_date_prefix(meta.get("start_date", "")))
        by_category_date.setdefault(key, []).append(rec_id)
    start_keys = {rec_id: _datetime_key(meta.get("start_date", "")) for rec_id, meta in metas.items()}

    def warn(message: str) -> None:
        report["warnings"].append(message)

    # 1. Modelo en memoria de videos/ y transcripts/{zoom,whisper}.
    assets: list[_RepairAsset] = []
    pending_rebase = []
    for category in _CATEGORY_DIRS:
        folder = course_dir / category
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            parsed = _parse_canonical(path.name)
            if not parsed or parsed["date"] == "sin-fecha":
                continue
            asset = _RepairAsset(
                path, category, parsed["base"], parsed["parts"], parsed["suffix"],
                path.stat().st_size, None,
            )
            if parsed["base"] in rec_by_base:
                asset.rec_id = rec_by_base[parsed["base"]][0]
                assets.append(asset)
                continue
            # Ancla por fecha: misma categoría+fecha y número obsoleto -> se re-basa.
            candidates = by_category_date.get((parsed["category"], parsed["date"]), [])
            if len(candidates) == 1:
                pending_rebase.append((asset, candidates[0]))
            else:
                warn(f"Sin grabación inequívoca para '{category}/{path.name}'; no se toca.")

    occupied_names = {
        (asset.category, asset.final_name().lower()) for asset in assets
    }
    rebase_slots = {}
    for index, (asset, rec_id) in enumerate(pending_rebase, start=1):
        original_slot = asset.slot
        asset.base = base_of[rec_id]
        asset.rec_id = rec_id
        if original_slot not in rebase_slots:
            siblings = [item for item, rid in pending_rebase if rid == rec_id and item.origin.name.startswith(original_slot[0]) and _split_part(item.origin.name)[1] == original_slot[1]]
            collision = any(
                (item.category, f"{asset.base}{''.join(_part_label(p) for p in original_slot[1])}{item.suffix}".lower()) in occupied_names
                for item in siblings
            )
            rebase_slots[original_slot] = (
                (_REBASE_PART_OFFSET + index,) + original_slot[1] if collision else original_slot[1]
            )
        asset.parts = rebase_slots[original_slot]
        occupied_names.add((asset.category, asset.final_name().lower()))
        assets.append(asset)

    # Preserve distinct legacy spellings that parse into the same slot, including
    # '(1)' versus 'Parte 1'. Allocate once per raw stem for every variant.
    occupied_assets = set()
    legacy_slots = {}
    for index, asset in enumerate(assets, start=1):
        stem = _split_variant(asset.origin.name)[0]
        key = (asset.base, stem)
        if key in legacy_slots:
            asset.parts = legacy_slots[key]
        elif (asset.category, asset.base, asset.parts, asset.suffix.lower()) in occupied_assets:
            asset.parts = (_REBASE_PART_OFFSET * 2 + index,) + asset.parts
        legacy_slots[key] = asset.parts
        occupied_assets.add((asset.category, asset.base, asset.parts, asset.suffix.lower()))

    zoom_subs_before = {
        asset.rec_id for asset in assets
        if asset.category == "transcripts/zoom" and _is_zoom_sub(asset.suffix)
    }
    reassigned_targets = set()

    def live(predicate=lambda asset: True):
        return [asset for asset in assets if asset.removed is None and predicate(asset)]

    def slot_assets(slot):
        return live(lambda asset: asset.slot == slot)

    def remove_slot(slot, video_reason: str, transcript_reason: str) -> None:
        for asset in slot_assets(slot):
            asset.removed = video_reason if asset.is_video else transcript_reason

    def move_slot(slot, new_base: str, rec_id: str) -> None:
        reassigned_targets.add(rec_id)
        for asset in slot_assets(slot):
            # Historical part labels do not prove that a VTT came from this video.
            # Re-fetch Zoom subs and regenerate Whisper rather than relabel content.
            if not asset.is_video:
                asset.removed = "misassigned-transcripts"
                continue
            asset.base = new_base
            asset.parts = ()
            asset.rec_id = rec_id

    def renumber() -> None:
        bases = {asset.base for asset in live()}
        for base in bases:
            keys = sorted({asset.parts for asset in live(lambda item: item.base == base)})
            mapping = {}
            if () in keys:
                mapping[()] = ()
                rest = [key for key in keys if key != ()]
            else:
                mapping[keys[0]] = ()
                rest = keys[1:]
            for number, key in enumerate(rest, start=1):
                mapping[key] = (number,)
            for asset in live(lambda item: item.base == base):
                asset.parts = mapping[asset.parts]

    # Validate original slots before normalization can promote a lone orphan.
    original_video_slots = {asset.slot for asset in live(lambda item: item.is_video)}
    for asset in live(lambda item: not item.is_video and item.parts):
        if asset.slot not in original_video_slots:
            asset.removed = "orphan-transcripts"

    # 2. Normalizar 'Parte X - Parte Y' / ' (N)' a una numeración 1..n por clase.
    renumber()

    probes: dict[Path, tuple] = {}
    has_ffprobe = _ffprobe_available()
    if not has_ffprobe:
        warn("ffprobe no disponible: no se reasignan videos entre clases ni se verifica duración.")

    def probe(asset: _RepairAsset) -> tuple:
        if asset.origin not in probes:
            probes[asset.origin] = _probe_video(asset.origin) if has_ffprobe else (None, None)
        return probes[asset.origin]

    def owners_for(created) -> list[str]:
        if created is None:
            return []
        return [
            rec_id for rec_id, start in start_keys.items()
            if start is not None and abs((start - created).total_seconds()) <= _OWNER_TOLERANCE_SECONDS
        ]

    # 3. Grabaciones vacías ('0 min').
    empty_recs = set()
    for asset in live(lambda item: item.is_video):
        duration = probe(asset)[0] if has_ffprobe else None
        # A short but valid clip is not an empty recording. Without probe data,
        # only classify tiny media when the recording has no positive duration.
        empty = duration == 0 or (
            duration is None and not has_ffprobe
            and asset.size < _EMPTY_VIDEO_BYTES
            and not recordings.get(asset.rec_id, {}).get("duration_minutes")
        )
        if not empty:
            if asset.size < _EMPTY_VIDEO_BYTES or (duration is not None and duration < _EMPTY_VIDEO_SECONDS):
                warn(f"Video corto o pequeño '{asset.final_name()}' conservado: no está confirmado como vacío.")
            continue
        for sibling in slot_assets(asset.slot):
            if sibling.is_video or sibling.size < _EMPTY_VTT_BYTES:
                sibling.removed = "empty-videos"
        empty_recs.add(asset.rec_id)

    # 4. Videos idénticos: un contenido pertenece a una sola grabación por curso.
    content = _ContentIndex()
    groups: dict[tuple, list[_RepairAsset]] = {}
    sizes: dict[int, list[_RepairAsset]] = {}
    for asset in live(lambda item: item.is_video):
        sizes.setdefault(asset.size, []).append(asset)
    for size, same_size in sizes.items():
        if len(same_size) < 2:
            continue
        for asset in same_size:
            groups.setdefault((size, content.digest(asset.origin)), []).append(asset)
    grouped = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        grouped.update(id(asset) for asset in group)
        group.sort(key=lambda item: (item.base, item.parts))
        owners = owners_for(probe(group[0])[1])
        if len(owners) == 1:
            owner = owners[0]
            owner_base = base_of[owner]
            keepers = [asset for asset in group if asset.base == owner_base]
            keeper = keepers[0] if keepers else None
            if keeper is None:
                candidate = group[0]
                if not slot_assets((owner_base, ())):
                    report["actions"].append(
                        ("reassign", candidate.final_name(), owner_base, "creation_time")
                    )
                    move_slot(candidate.slot, owner_base, owner)
                    keeper = candidate
                else:
                    remove_slot(candidate.slot, "misassigned-videos", "misassigned-transcripts")
            for asset in group:
                if asset is keeper or asset.removed:
                    continue
                if asset.base == owner_base:
                    asset.removed = "identical-videos"
                else:
                    remove_slot(asset.slot, "misassigned-videos", "misassigned-transcripts")
        else:
            by_base: dict[str, list[_RepairAsset]] = {}
            for asset in group:
                by_base.setdefault(asset.base, []).append(asset)
            for same_base in by_base.values():
                for asset in same_base[1:]:
                    asset.removed = "identical-videos"
            if len(by_base) > 1:
                warn(
                    "Videos idénticos en varias clases sin dueño verificable (ffprobe/creation_time): "
                    + ", ".join(items[0].final_name() for items in by_base.values())
                )

    # 5. Videos únicos cuyo creation_time corresponde a otra grabación.
    if has_ffprobe:
        for asset in live(lambda item: item.is_video and id(item) not in grouped):
            created = probe(asset)[1]
            if created is None:
                continue
            owners = owners_for(created)
            if asset.rec_id in owners:
                continue
            others = [rec_id for rec_id in owners if base_of[rec_id] != asset.base]
            if len(others) != 1:
                if not owners:
                    warn(f"creation_time de '{asset.final_name()}' no coincide con ninguna grabación.")
                continue
            target_base = base_of[others[0]]
            if not slot_assets((target_base, ())):
                report["actions"].append(("reassign", asset.final_name(), target_base, "creation_time"))
                move_slot(asset.slot, target_base, others[0])
            else:
                warn(f"Video distinto '{asset.final_name()}' pertenece a '{target_base}', pero el destino está ocupado; se conserva para revisión.")

    # 6. Subtítulos con 'Parte N' sin su video 'Parte N' son huérfanos.
    video_slots = {asset.slot for asset in live(lambda item: item.is_video)}
    for asset in live(lambda item: not item.is_video and item.parts and item.slot not in video_slots):
        asset.removed = "orphan-transcripts"

    # 7. Subtítulos Zoom (.cc/.transcript) idénticos en varias clases. Los
    # .chapter.vtt son genéricos y no se comparan entre clases.
    sub_sizes: dict[int, list[_RepairAsset]] = {}
    for asset in live(lambda item: item.category == "transcripts/zoom" and _is_zoom_sub(item.suffix)):
        sub_sizes.setdefault(asset.size, []).append(asset)
    for size, same_size in sub_sizes.items():
        if len(same_size) < 2:
            continue
        sub_groups: dict[str, list[_RepairAsset]] = {}
        for asset in same_size:
            sub_groups.setdefault(content.digest(asset.origin), []).append(asset)
        for group in sub_groups.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda item: (item.parts, item.base))
            if len({asset.base for asset in group}) == 1:
                for asset in group[1:]:
                    asset.removed = "identical-transcripts"
                continue
            primaries = [asset for asset in group if asset.parts == ()]
            keeper = primaries[0] if len(primaries) == 1 else None
            for asset in group:
                if asset is not keeper:
                    asset.removed = "misassigned-transcripts"

    # 8. Whisper idéntico entre clases delata un video mal asignado: solo se reporta.
    whisper_groups: dict[tuple, list[_RepairAsset]] = {}
    whisper_sizes: dict[int, list[_RepairAsset]] = {}
    for asset in live(lambda item: item.category == "transcripts/whisper"):
        whisper_sizes.setdefault(asset.size, []).append(asset)
    for size, same_size in whisper_sizes.items():
        if len(same_size) < 2:
            continue
        for asset in same_size:
            whisper_groups.setdefault((size, content.digest(asset.origin)), []).append(asset)
    for group in whisper_groups.values():
        if len({asset.base for asset in group}) > 1:
            warn(
                "Transcripciones whisper idénticas en varias clases (posible video mal asignado): "
                + ", ".join(asset.final_name() for asset in group)
            )

    # 9. Numeración final 1..n sin huecos (video y subtítulos del slot juntos).
    renumber()

    # 10. Marcas por grabación.
    zoom_subs_after = {
        asset.rec_id for asset in live(
            lambda item: item.category == "transcripts/zoom" and _is_zoom_sub(item.suffix)
        )
    }
    videos_after = {asset.rec_id for asset in live(lambda item: item.is_video)}
    for rec_id in metas:
        if rec_id in zoom_subs_before | reassigned_targets and rec_id not in zoom_subs_after and rec_id not in empty_recs:
            report["flags"].setdefault(rec_id, {})["zoom_subs_missing"] = True
        elif rec_id in zoom_subs_after:
            report["flags"].setdefault(rec_id, {})["zoom_subs_missing"] = False
    for rec_id in empty_recs - videos_after:
        if rec_id:
            report["flags"].setdefault(rec_id, {})["empty_recording"] = True
    for rec_id in videos_after:
        report["flags"].setdefault(rec_id, {})["empty_recording"] = False

    moves = []
    for asset in assets:
        origin_rel = asset.origin.relative_to(course_dir).as_posix()
        if asset.removed:
            report["actions"].append(("backup", origin_rel, asset.removed, asset.rec_id or ""))
            continue
        destination = course_dir / asset.category / asset.final_name()
        if destination != asset.origin or destination.name != asset.origin.name:
            report["actions"].append(
                ("rename", origin_rel, destination.relative_to(course_dir).as_posix(), "")
            )
            moves.append((asset, destination))

    if dry_run:
        return report

    _apply_repair(course_dir, assets, moves, recordings, report)
    return report


def _apply_repair(course_dir: Path, assets, moves, recordings: dict, report: dict) -> None:
    mapping: dict[str, str | None] = {}

    # Validate all final paths before moving anything. Legacy '(N)' and 'Parte N'
    # can parse to the same slot; never overwrite distinct content on POSIX.
    final_paths = {}
    for asset in assets:
        if asset.removed:
            continue
        destination = course_dir / asset.category / asset.final_name()
        key = str(destination).casefold()
        if key in final_paths:
            report["warnings"].append(f"Colisión ambigua de destino: {destination.name}; no se aplica la reparación del curso.")
            return
        final_paths[key] = asset

    moving_origins = {asset.origin for asset, _ in moves}
    removed_origins = {asset.origin for asset in assets if asset.removed}
    for _, destination in moves:
        if destination.exists() and destination not in moving_origins | removed_origins:
            report["warnings"].append(f"Destino ajeno ocupado: {destination.name}; no se aplica la reparación del curso.")
            return

    for asset in assets:
        if not asset.removed or not asset.origin.exists():
            continue
        origin_rel = asset.origin.relative_to(course_dir).as_posix()
        try:
            _backup_duplicate(course_dir, asset.origin, asset.rec_id or "", "", asset.removed)
            mapping[origin_rel.casefold()] = None
        except OSError as error:
            report["flags"] = {}
            report["warnings"].append(f"No se pudo respaldar {origin_rel}: {error}")

    staged = []
    failures = False
    for asset, destination in moves:
        if destination.exists() and destination not in moving_origins:
            report["warnings"].append(
                f"Destino ocupado por un archivo ajeno, se omite: {destination.name}"
            )
            failures = True
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            asset.origin.rename(temporary)
            staged.append((asset, temporary, destination))
        except OSError as error:
            failures = True
            report["warnings"].append(f"No se pudo mover {asset.origin.name}: {error}")
    if failures:
        for asset, temporary, _ in staged:
            if not asset.origin.exists():
                temporary.rename(asset.origin)
        staged = []
    for asset, temporary, destination in staged:
        try:
            if destination.exists():
                raise FileExistsError(f"Destino ocupado durante reparación: {destination}")
            temporary.rename(destination)
            mapping[asset.origin.relative_to(course_dir).as_posix().casefold()] = (
                destination.relative_to(course_dir).as_posix()
            )
        except OSError as error:
            failures = True
            if not asset.origin.exists():
                temporary.rename(asset.origin)
            report["warnings"].append(f"No se pudo renombrar {asset.origin.name}: {error}")

    processed_origins = {
        asset.origin.relative_to(course_dir).as_posix().casefold(): asset
        for asset in assets
    }
    for rec_id, rec_info in recordings.items():
        updated = []
        for relative_name in rec_info.get("organized_files", []):
            key = str(relative_name).replace("\\", "/").casefold()
            if key in processed_origins:
                asset = processed_origins[key]
                if key in mapping or (not asset.removed and asset.rec_id == rec_id):
                    # Successfully moved assets are re-associated below.
                    if key not in mapping:
                        updated.append(relative_name)
                    continue
            if key in mapping:
                if mapping[key]:
                    updated.append(mapping[key])
            elif (course_dir / relative_name).is_file():
                updated.append(relative_name)
        if updated != rec_info.get("organized_files", updated):
            rec_info["organized_files"] = sorted(set(updated))
        for flag, value in report["flags"].get(rec_id, {}).items():
            if failures:
                continue
            if value:
                rec_info[flag] = value
            else:
                rec_info.pop(flag, None)

    for asset in assets:
        origin_rel = asset.origin.relative_to(course_dir).as_posix()
        key = origin_rel.casefold()
        final_rel = mapping.get(key, origin_rel)
        if asset.removed or not final_rel or asset.rec_id not in recordings:
            continue
        if not (course_dir / final_rel).is_file():
            continue
        owner = recordings[asset.rec_id]
        owner["organized_files"] = sorted(set(owner.get("organized_files", [])) | {final_rel})

    if mapping:
        manifest = course_dir / ".claude-udea-backup" / "repair-manifest.jsonl"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("a", encoding="utf-8") as stream:
            for source, destination in mapping.items():
                stream.write(json.dumps({"source": source, "destination": destination}, ensure_ascii=False) + "\n")


def count_transcripts(download_dir: Path, slug: str) -> int:
    """Cuenta VTTs de una asignatura en transcripts/."""
    course_transcripts = download_dir / "transcripts" / slug
    if not course_transcripts.exists():
        return 0
    return len(list(course_transcripts.glob("*.vtt")))
