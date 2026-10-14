"""
CLI principal: claude_udea
"""

import json
import subprocess
import sys
import os
import re
import threading
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import requests


# Fix encoding for Windows console
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


import platform

def _default_work_dir() -> Path:
    """Retorna el directorio de trabajo según el OS."""
    if platform.system() == "Windows":
        return Path("C:/claude-udea")
    return Path.home() / "claude-udea"

WORK_DIR = _default_work_dir()


def _get_work_dir() -> Path:
    """Directorio de trabajo fijo."""
    WORK_DIR.mkdir(exist_ok=True)

    # Si no existe config.json, correr setup interactivo
    if not (WORK_DIR / "config.json").exists():
        from claude_udea.setup import run_setup
        if not run_setup(WORK_DIR):
            sys.exit(0)

    _ensure_templates(WORK_DIR)
    return WORK_DIR


def _ensure_templates(work_dir: Path):
    """Copia instrucciones, rules y skills para el asistente configurado."""
    import shutil
    templates_dir = Path(__file__).parent / "templates"
    if not templates_dir.exists():
        return

    # Generar MD de instrucciones (CLAUDE.md y/o GEMINI.md)
    _generate_assistant_md(work_dir)

    # .claude/rules.md y skills/ (también .gemini/ para Gemini)
    src_claude_dir = templates_dir / ".claude"
    if not src_claude_dir.exists():
        return

    for dest_name in (".claude", ".gemini"):
        dest_dir = work_dir / dest_name
        dest_dir.mkdir(exist_ok=True)

        src_rules = src_claude_dir / "rules.md"
        dest_rules = dest_dir / "rules.md"
        if src_rules.exists() and not dest_rules.exists():
            shutil.copy2(src_rules, dest_rules)

        src_skills = src_claude_dir / "skills"
        dest_skills = dest_dir / "skills"
        if src_skills.exists():
            dest_skills.mkdir(exist_ok=True)
            for skill_file in src_skills.glob("*.md"):
                dest_skill = dest_skills / skill_file.name
                if not dest_skill.exists():
                    shutil.copy2(skill_file, dest_skill)


def _build_assistant_md(courses: dict) -> str:
    """Genera el contenido de instrucciones para el asistente (agnóstico del LLM)."""
    course_lines = "\n".join(
        f"- **{info['name']}** -> `downloads/transcripts/{slug}/`"
        for slug, info in courses.items()
    )

    return f"""# Asistente Academico UdeA

Eres un asistente academico especializado para un estudiante de la Universidad de Antioquia. Tu unica fuente de verdad son las transcripciones de clase en formato WebVTT ubicadas en `downloads/transcripts/`.

## Asignaturas

{course_lines}

## Fechas y metadata

Cada archivo VTT tiene la fecha de la clase de tres formas:
1. **En el nombre del archivo**: `Clase #N - YYYY-MM-DD` (ej: `Clase #1 - 2026-03-09.transcript.vtt`)
2. **Dentro del archivo**: bloque `NOTE` al inicio con fecha, asignatura, tema y duracion
3. **En el indice**: `downloads/transcripts/index.json` tiene un listado completo ordenado por fecha

Cuando el estudiante pregunte "cuando se dijo X" o "que se vio el dia Y", usa estas fechas para dar respuestas precisas. Lee `index.json` primero para ubicar las grabaciones por fecha sin tener que abrir cada archivo.

## Funciones principales

### 1. Ensenar
Ensenar TODO lo visto en clase de forma organizada, profesional, al grano. No omitir ningun tema. No inventar contenido que no este en las transcripciones. Cada tema debe tener referencia a la grabacion y minuto donde se trato.

### 2. Informar compromisos
Encontrar TODOS los pendientes: parciales, quices, tareas, talleres, trabajos, entregas, exposiciones, o cualquier actividad mencionada en clase. Presentarlos visualmente de forma clara con fechas y estado.

### 3. Planear y organizar
Ayudar al estudiante a planificar su tiempo: crear horarios de estudio, priorizar tareas, distribuir carga academica, y asegurar que cumpla con todo.

## Reglas de referencia

Siempre que menciones un tema o un pendiente, incluye:
- Nombre del archivo VTT (grabacion)
- Fecha de la clase
- Timestamp (minuto aproximado)
- Asignatura

Formato: `[Asignatura | 2026-03-09 | archivo.vtt | ~min 23]`

## Como leer las transcripciones

Los archivos `.vtt` tienen este formato:
```
WEBVTT

NOTE
Fecha de clase: 2026-03-09
Asignatura: Calidad de Software
Tema: CALIDAD DE SOFTWARE (2026-1)
Duracion: 81 min

1
00:12:34.000 --> 00:12:38.000
texto que dijo el profesor
```

El timestamp `00:12:34` = minuto 12. Usa eso para dar referencias.

## Comportamiento

- Responde en espanol
- Se directo y conciso a menos que te pidan profundizar
- No des ejemplos a menos que te los pidan (usa /ejemplos)
- Si el estudiante se desvia del tema academico, redirige amablemente
- Nunca inventes informacion que no este en las transcripciones
- Si no encuentras algo en las transcripciones, dilo honestamente
"""


def _generate_assistant_md(work_dir: Path):
    """Genera CLAUDE.md y GEMINI.md segun las asignaturas configuradas."""
    config_path = work_dir / "config.json"
    if not config_path.exists():
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    content = _build_assistant_md(config.get("courses", {}))

    for filename in ("CLAUDE.md", "GEMINI.md"):
        with open(work_dir / filename, "w", encoding="utf-8") as f:
            f.write(content)



# ─── Helpers ─────────────────────────────────────────────────

def load_config(work_dir: Path):
    with open(work_dir / "config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    # Resolver paths relativos al work_dir
    for key in ("download_dir", "manifest_file", "recordings_file"):
        if key in config:
            p = Path(config[key])
            if not p.is_absolute():
                config[key] = str(work_dir / p)
    return config


def load_recordings(path: Path) -> dict:
    if path.exists():
        # No se deduplica por fecha: dos clases (p. ej. Fábrica Escuela y una clase
        # normal) pueden empezar a la misma hora y ambas son grabaciones distintas.
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_recordings(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def extract_recording_id(url: str) -> str:
    match = re.search(r"/rec/(?:share|play)/([^?\s]+)", url)
    return match.group(1) if match else url


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:100] if name else "sin-titulo"


class Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, msg):
        self.msg = msg
        self._stop = threading.Event()
        self._thread = None

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            print(f"\r  {frame} {self.msg}", end="", flush=True)
            i += 1
            time.sleep(0.1)

    def __enter__(self):
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()
        print(f"\r  ✔ {self.msg}  ")


# ─── Scraping + Descarga (pipeline paralelo) ──────────────

def _merge_scraped(existing, config, slug, links):
    """Merge resultados de scraping en existing. Retorna lista de nuevos pendientes."""
    course_info = config["courses"][slug]
    if slug not in existing:
        existing[slug] = {
            "name": course_info["name"],
            "recordings": {},
            "last_scraped": None,
        }

    course_data = existing[slug]
    from claude_udea.download import backfill_recording_metadata
    backfill_recording_metadata(
        Path(config["download_dir"]) / slug, course_data, links
    )

    # Colapsar duplicados ya persistidos: misma sesión (meeting_id + start_date)
    # descubierta antes con otra URL/share.
    _collapse_duplicate_sessions(course_data)

    session_index = {}
    for rec_id, rec_info in course_data["recordings"].items():
        session_key = str(rec_info.get("start_date", "") or "")
        if session_key:
            session_index[session_key] = rec_id

    new_pending = []
    seen_ids = set()
    seen_sessions = set()
    for link in links:
        link_rec_id = extract_recording_id(link["url"])
        if link_rec_id in seen_ids:
            continue
        seen_ids.add(link_rec_id)
        start_date = str(link.get("start_date", "") or "")
        # La fecha identifica la sesión dentro del curso (los tokens rotan).
        session_key = start_date
        has_session = bool(session_key)
        if has_session:
            if session_key in seen_sessions:
                continue
            seen_sessions.add(session_key)

        rec_id = link_rec_id
        if has_session:
            existing_rec_id = session_index.get(session_key)
            if existing_rec_id and existing_rec_id != link_rec_id:
                # La misma sesión descubierta con otra URL: actualizar el registro existente.
                rec_id = existing_rec_id
                seen_ids.add(rec_id)

        if rec_id in course_data["recordings"]:
            rec_info = course_data["recordings"][rec_id]
            rec_info["url"] = link["full_url"]
            rec_info["share_url"] = link["url"]
            # No sobrescribir la identidad de una sesión conocida: un token rotado
            # puede reapuntar a otra fecha y provocar colisiones que pierden clases.
            if not rec_info.get("title"):
                rec_info["title"] = link.get("topic") or link["text"] or ""
            if not rec_info.get("meeting_id"):
                rec_info["meeting_id"] = link.get("meeting_id") or ""
            if not rec_info.get("start_date"):
                rec_info["start_date"] = start_date or ""
            duration = link.get("duration_minutes")
            if duration or not rec_info.get("duration_minutes"):
                rec_info["duration_minutes"] = duration or 0
            rec_info["video_downloaded"] = _has_video_artifact(
                Path(config["download_dir"]) / slug, rec_info, rec_id,
                _fabrica_ids_for(config, slug),
            )
            rec_info["downloaded"] = rec_info["video_downloaded"]
            if link.get("_existing_files"):
                rec_info["organized_files"] = sorted(
                    set(rec_info.get("organized_files", []))
                    | set(link["_existing_files"])
                )
                rec_info["video_downloaded"] = _has_video_artifact(
                    Path(config["download_dir"]) / slug, rec_info, rec_id,
                    _fabrica_ids_for(config, slug),
                )
                rec_info["downloaded"] = rec_info["video_downloaded"]
            continue
        title = link.get("topic") or link["text"]

        rec_info = {
            "url": link["full_url"],
            "share_url": link["url"],
            "title": title,
            "meeting_id": link.get("meeting_id", ""),
            "start_date": start_date,
            "duration_minutes": link.get("duration_minutes", 0),
            "scraped_at": datetime.now().isoformat(),
            "downloaded": False,
        }
        if link.get("_existing_files"):
            rec_info["organized_files"] = link["_existing_files"]
        course_data["recordings"][rec_id] = rec_info
        if has_session:
            session_index[session_key] = rec_id
        url = rec_info.get("url") or rec_info.get("share_url", "")
        if url and not rec_info["downloaded"]:
            new_pending.append((slug, rec_id, rec_info, url))

    course_data["last_scraped"] = datetime.now().isoformat()
    return new_pending


def _collapse_duplicate_sessions(course_data: dict) -> None:
    """Colapsa grabaciones duplicadas: mismo meeting_id + start_date con distinto rec_id.

    La misma sesión de Zoom puede descubrirse con URLs share/play distintas y generar
    registros repetidos que luego producen 'Parte N' espurios. Se conserva el registro
    con mejor metadata (descargado > más organized_files > duración) y se fusionan
    banderas y referencias de archivos.
    """
    recordings = course_data.get("recordings", {})
    by_session = {}
    for rec_id, rec_info in recordings.items():
        start_date = str(rec_info.get("start_date", "") or "")
        if not start_date:
            continue
        # Dentro de un mismo curso, el start_date exacto identifica la sesión: los
        # tokens de Zoom rotan y el meeting_id puede ser inconsistente (Ingenia).
        by_session.setdefault(start_date, []).append(rec_id)

    for key, rec_ids in by_session.items():
        if len(rec_ids) < 2:
            continue

        def rank(rid):
            rec = recordings[rid]
            return (
                1 if rec.get("downloaded") else 0,
                len(rec.get("organized_files", [])),
                rec.get("duration_minutes", 0) or 0,
            )

        ordered = sorted(rec_ids, key=rank, reverse=True)
        keeper_id = ordered[0]
        keeper = recordings[keeper_id]
        for other_id in ordered[1:]:
            other = recordings[other_id]
            keeper["organized_files"] = sorted(
                set(keeper.get("organized_files", []))
                | set(other.get("organized_files", []))
            )
            keeper["downloaded"] = bool(
                keeper.get("downloaded") or other.get("downloaded")
            )
            keeper["video_downloaded"] = bool(
                keeper.get("video_downloaded") or other.get("video_downloaded")
            )
            if other.get("duration_minutes") and not keeper.get("duration_minutes"):
                keeper["duration_minutes"] = other["duration_minutes"]
            if not keeper.get("url") and other.get("url"):
                keeper["url"] = other["url"]
                keeper["share_url"] = other.get("share_url", other.get("url", ""))
            del recordings[other_id]


def _fabrica_ids_for(config: dict, slug: str) -> set:
    """Meeting IDs configurados como Fábrica Escuela para un curso."""
    course = config.get("courses", {}).get(slug, {}) or {}
    return {str(value) for value in course.get("fabrica_meeting_ids", []) or []}


def _category_prefix_for(rec_info: dict, fabrica_meeting_ids: set | None) -> str:
    from claude_udea.download import _class_category_for
    category = _class_category_for(rec_info, fabrica_meeting_ids)
    return "fabrica escuela - clase #" if category == "fabrica_escuela" else "clase #"


def _usable_media_file(path: Path) -> bool:
    """True si es un archivo real con contenido y NO vive en el respaldo de duplicados.

    Las copias en `.claude-udea-backup/` no cuentan como video/subtítulo disponible:
    si el usuario borra sus videos, deben re-descargarse aunque el respaldo exista.
    """
    try:
        return (
            path.is_file()
            and path.stat().st_size > 0
            and ".claude-udea-backup" not in path.parts
        )
    except OSError:
        return False


def _guard_meta(rec_info: dict, fabrica_meeting_ids: set | None) -> dict:
    from claude_udea.download import _class_category_for
    return {
        "start_date": rec_info.get("start_date", ""),
        "class_category": _class_category_for(rec_info, fabrica_meeting_ids),
    }


def _owned_organized_files(rec_info: dict, fabrica_meeting_ids: set | None) -> list[str]:
    """organized_files sin rutas obsoletas que apuntan a otra fecha/categoría."""
    from claude_udea.download import _name_conflicts_with
    meta = _guard_meta(rec_info, fabrica_meeting_ids)
    return [
        relative_name for relative_name in rec_info.get("organized_files", [])
        if not _name_conflicts_with(Path(relative_name).name, meta)
    ]


def _skip_reason(rec_info: dict) -> str:
    """Motivo para no (re)descargar una grabación, o '' si debe intentarse."""
    if rec_info.get("empty_recording"):
        return "grabación vacía"
    url = rec_info.get("url") or rec_info.get("share_url", "")
    if rec_info.get("suspect_url") and rec_info["suspect_url"] == url:
        return "URL sospechosa (devolvió contenido de otra clase)"
    return ""


def _has_video_artifact(course_dir: Path, rec_info: dict, rec_id: str, fabrica_meeting_ids: set | None = None) -> bool:
    """True only when a complete video file for this recording exists on disk."""
    from claude_udea.download import _recording_alias_ids

    video_extensions = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
    alias_ids = _recording_alias_ids(rec_id, rec_info)
    candidates = []
    for relative_name in _owned_organized_files(rec_info, fabrica_meeting_ids):
        path = course_dir / relative_name
        if path.suffix.lower() in video_extensions:
            candidates.append(path)
    candidates.extend(
        path for path in course_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in video_extensions
        and any(f"[{alias}" in path.name for alias in alias_ids)
    )
    if any(_usable_media_file(path) for path in candidates):
        return True

    # organized_files may be stale (files renamed by organizer).
    # Fallback: match clean video names by category prefix and date.
    start_date = rec_info.get("start_date", "")
    date_prefix = start_date[:10] if start_date else ""
    if not date_prefix or not date_prefix[0].isdigit():
        return False
    category_prefix = _category_prefix_for(rec_info, fabrica_meeting_ids)
    date_marker = f" - {date_prefix}"

    for path in course_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in video_extensions:
            continue
        name = path.name.casefold()
        if name.startswith(category_prefix) and date_marker in name and _usable_media_file(path):
            return True

    return False


def _recording_video_missing(course_dir: Path, rec_info: dict, rec_id: str, fabrica_meeting_ids: set | None = None) -> bool:
    """Return false when a canonical, previously organized video is present."""
    return not _has_video_artifact(course_dir, rec_info, rec_id, fabrica_meeting_ids)


def _recording_subs_present(course_dir: Path, rec_info: dict, fabrica_meeting_ids: set | None = None) -> bool:
    """True si ya existen subtítulos de Zoom (.cc/.transcript, no whisper) para esta grabación."""
    from claude_udea.download import _is_zoom_sub, _parse_date_prefix

    for relative_name in _owned_organized_files(rec_info, fabrica_meeting_ids):
        if _is_zoom_sub(relative_name) and _usable_media_file(course_dir / relative_name):
            return True

    date_prefix = _parse_date_prefix(rec_info.get("start_date", ""))
    if date_prefix == "sin-fecha":
        return False
    category_prefix = _category_prefix_for(rec_info, fabrica_meeting_ids)
    date_marker = f" - {date_prefix}"
    for path in course_dir.rglob("*.vtt"):
        name = path.name.casefold()
        if (
            _is_zoom_sub(name) and name.startswith(category_prefix)
            and date_marker in name and _usable_media_file(path)
        ):
            return True
    return False


def _needs_subs_redownload(rec_info: dict) -> bool:
    url = rec_info.get("url") or rec_info.get("share_url", "")
    return bool(url and rec_info.get("zoom_subs_missing") and not _skip_reason(rec_info))


def fase_scraping_y_descarga(work_dir, config, recordings_path, target_courses, skip_video, dry_run, skip_scrape=False):
    """
    Pipeline paralelo: login → scrape todas las materias en paralelo →
    a medida que cada scrape termina, lanza descargas inmediatamente.
    Todo con un solo ThreadPoolExecutor.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from claude_udea.auth import login, _scrape_one
    from claude_udea.download import get_archive_path, download_one
    from tqdm import tqdm

    existing = load_recordings(recordings_path)
    download_dir = Path(config["download_dir"])
    archive_path = get_archive_path(download_dir)

    courses_to_scrape = {slug: config["courses"][slug] for slug in target_courses}

    # Login solo si vamos a scrapear
    session = None
    if not skip_scrape:
        has_moodle_courses = any(
            urlparse(info.get("moodle_url", "")).hostname != "ingenia.udea.edu.co"
            for info in courses_to_scrape.values()
        )
        session = login(work_dir) if has_moodle_courses else requests.Session()

    # El archive no demuestra que el video siga en disco; se valida por artefacto.
    already = 0
    for slug in target_courses:
        if slug not in existing:
            continue
        fabrica_ids = _fabrica_ids_for(config, slug)
        for rec_id, rec_info in existing[slug].get("recordings", {}).items():
            video_present = not _recording_video_missing(download_dir / slug, rec_info, rec_id, fabrica_ids)
            if not skip_video and video_present:
                already += 1

    total_new = 0
    total_ok = 0
    total_failed = 0
    total_processing = 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        download_futures = []

        if not skip_scrape:
            print("  Scrapeando y descargando en paralelo...\n")

            # Lanzar scraping de todas las materias en paralelo
            scrape_futures = {
                pool.submit(_scrape_one, session, slug, info): slug
                for slug, info in courses_to_scrape.items()
            }

            # A medida que cada scrape termina, lanzar descargas
            for future in as_completed(scrape_futures):
                slug, links = future.result()
                course_name = config["courses"][slug]["name"]

                is_ingenia = urlparse(
                    config["courses"][slug].get("moodle_url", "")
                ).hostname == "ingenia.udea.edu.co"
                if is_ingenia and not links:
                    previous_count = len(
                        existing.get(slug, {}).get("recordings", {})
                    )
                    print(
                        f"  ⚠ {course_name}: respuesta vacía de Ingenia; "
                        f"se conserva el estado previo ({previous_count} grabaciones)"
                    )
                    new_pending = []
                else:
                    # Merge y obtener pendientes nuevos
                    new_pending = _merge_scraped(existing, config, slug, links)

                # Filtrar los que ya están descargados
                fabrica_ids = _fabrica_ids_for(config, slug)
                pending = []
                for item in new_pending:
                    _, rec_id, _, _ = item
                    rec_info = item[2]
                    if _skip_reason(rec_info):
                        continue
                    if skip_video or _recording_video_missing(download_dir / slug, rec_info, rec_id, fabrica_ids):
                        pending.append(item)
                    else:
                        already += 1

                # También agregar pendientes de ejecuciones previas
                if slug in existing:
                    for rec_id, rec_info in existing[slug].get("recordings", {}).items():
                        if _skip_reason(rec_info):
                            continue
                        video_present = not _recording_video_missing(download_dir / slug, rec_info, rec_id, fabrica_ids)
                        url = rec_info.get("url") or rec_info.get("share_url", "")
                        if not skip_video and video_present:
                            continue
                        if url and not any(p[1] == rec_id for p in pending):
                            pending.append((slug, rec_id, rec_info, url))

                total_new += len(new_pending)
                if not (is_ingenia and not links):
                    print(f"  ✔ {course_name}: {len(links)} grabaciones, {len(pending)} pendientes")

                # Lanzar descargas en paralelo
                for item in pending:
                    slug_d, rec_id, rec_info, url = item
                    course_dir = download_dir / slug_d
                    skip_subs = (not skip_video) and _recording_subs_present(
                        course_dir, rec_info, _fabrica_ids_for(config, slug_d)
                    )
                    df = pool.submit(download_one, url, course_dir, archive_path, skip_video, dry_run, skip_subs)
                    download_futures.append((slug_d, rec_id, rec_info, df))
        else:
            # Sin scraping: solo descargar pendientes existentes
            for slug in target_courses:
                if slug not in existing:
                    continue
                fabrica_ids = _fabrica_ids_for(config, slug)
                for rec_id, rec_info in existing[slug].get("recordings", {}).items():
                    if _skip_reason(rec_info):
                        continue
                    video_present = not _recording_video_missing(download_dir / slug, rec_info, rec_id, fabrica_ids)
                    url = rec_info.get("url") or rec_info.get("share_url", "")
                    course_dir = download_dir / slug
                    if not skip_video and video_present:
                        already += 1
                        continue
                    if url:
                        skip_subs = (not skip_video) and _recording_subs_present(course_dir, rec_info, fabrica_ids)
                        df = pool.submit(download_one, url, course_dir, archive_path, skip_video, dry_run, skip_subs)
                        download_futures.append((slug, rec_id, rec_info, df))

        # Esperar descargas con barra de progreso
        if download_futures:
            print()
            mode = "Descargando transcripciones" if skip_video else "Descargando video + transcripciones"
            pbar = tqdm(
                total=len(download_futures), desc=f"  {mode}", unit="grab",
                bar_format="  {desc}  {bar}  {n_fmt}/{total_fmt}",
                ncols=70,
            )
            for slug_d, rec_id, rec_info, df in download_futures:
                status = df.result()
                if status == "ok":
                    if not skip_video:
                        rec_info["video_downloaded"] = _has_video_artifact(
                            Path(config["download_dir"]) / slug_d, rec_info, rec_id,
                            _fabrica_ids_for(config, slug_d),
                        )
                        rec_info["downloaded"] = rec_info["video_downloaded"]
                        if rec_info["video_downloaded"]:
                            rec_info["downloaded_at"] = datetime.now().isoformat()
                    if skip_video or rec_info.get("video_downloaded"):
                        total_ok += 1
                    else:
                        total_failed += 1
                        rec_info["download_error"] = "yt-dlp terminó sin producir un archivo de video"
                elif status == "processing":
                    total_processing += 1
                else:
                    total_failed += 1
                pbar.update(1)
            pbar.close()

    # Guardar estado
    save_recordings(recordings_path, existing)

    # Resumen
    total_recs = sum(len(c.get("recordings", {})) for c in existing.values())
    print(f"\n  ✔ {total_recs} grabaciones totales ({total_new} nuevas)")

    if download_futures:
        parts = []
        if total_ok:
            parts.append(f"{total_ok} descargadas")
        if already:
            parts.append(f"{already} ya estaban")
        if total_processing:
            parts.append(f"{total_processing} procesándose en Zoom")
        if total_failed:
            parts.append(f"{total_failed} fallidas")
        if parts:
            print(f"  ✔ {', '.join(parts)}")
    elif already:
        print(f"  ✔ {already} ya descargadas, nada nuevo")

    print()
    return existing, total_failed


# ─── Fase 3: Validación + Asistente AI ────────────────────

def _get_assistant(config) -> str:
    """Retorna 'claude' o 'gemini' segun la config."""
    return config.get("assistant", "claude")


def _run_repair(config, recordings, target_courses, dry_run=False, verbose=False) -> dict:
    """Ejecuta repair_course en los cursos seleccionados y devuelve totales."""
    from claude_udea.download import _build_rec_id_map, repair_course

    download_dir = Path(config["download_dir"])
    all_id_map = _build_rec_id_map(recordings, config.get("courses", {}))
    totals = {"backup": 0, "rename": 0, "reassign": 0, "warnings": 0, "subs": 0, "empty": 0}
    for slug in target_courses:
        if slug not in recordings:
            continue
        id_map = {
            rec_id: meta for rec_id, meta in all_id_map.items()
            if meta.get("slug") == slug
        }
        report = repair_course(download_dir / slug, recordings[slug], id_map, dry_run=dry_run)
        for kind, *_ in report["actions"]:
            totals[kind] = totals.get(kind, 0) + 1
        totals["warnings"] += len(report["warnings"])
        totals["empty"] += sum(1 for flags in report["flags"].values() if flags.get("empty_recording"))
        totals["subs"] += sum(1 for flags in report["flags"].values() if flags.get("zoom_subs_missing"))
        if not verbose or not (report["actions"] or report["warnings"]):
            continue
        print(f"\n  [{slug}]")
        for kind, first, second, extra in report["actions"]:
            if kind == "backup":
                print(f"    respaldo ({second}): {first}")
            elif kind == "rename":
                print(f"    renombrar: {first}\n            -> {second}")
            else:
                print(f"    reasignar ({extra}): {first} -> {second}")
        for warning in report["warnings"]:
            print(f"    ⚠ {warning}")
        for rec_id, flags in report["flags"].items():
            names = ", ".join(sorted(flag for flag, value in flags.items() if value))
            if not names:
                continue
            print(f"    marca {names}: {id_map.get(rec_id, {}).get('class_number', '?')} ({rec_id[:12]}…)")
    return totals


def _print_repair_totals(totals: dict, dry_run: bool) -> None:
    prefix = "Plan de reparación" if dry_run else "Reparación"
    print(
        f"  ✔ {prefix}: {totals['backup']} a respaldo, {totals['rename']} renombrados, "
        f"{totals['reassign']} reasignados, {totals['subs']} clases sin subtítulos Zoom "
        f"(se re-descargan), {totals['empty']} grabaciones vacías, "
        f"{totals['warnings']} advertencias"
    )


def _redownload_missing_subs(config, recordings, target_courses) -> int:
    """Re-descarga solo subtítulos de las grabaciones marcadas `zoom_subs_missing`."""
    from claude_udea.download import download_one, get_archive_path

    download_dir = Path(config["download_dir"])
    archive_path = get_archive_path(download_dir)
    recovered = 0
    for slug in target_courses:
        for rec_id, rec_info in recordings.get(slug, {}).get("recordings", {}).items():
            if not _needs_subs_redownload(rec_info):
                continue
            url = rec_info.get("url") or rec_info.get("share_url", "")
            status = download_one(url, download_dir / slug, archive_path, True, False, False, True)
            if status == "ok":
                recovered += 1
    return recovered


def repair_videos_command(config, target_courses, dry_run=False) -> None:
    """`claude_udea --repair-videos [--dry-run] [curso...]`."""
    from claude_udea.download import copy_transcripts, rename_downloads

    recordings_path = Path(config["recordings_file"])
    recordings = load_recordings(recordings_path)
    if not recordings:
        print("  No hay datos previos (recordings.json vacío).\n")
        return
    if not dry_run:
        import shutil
        backup_path = recordings_path.with_name(
            f"{recordings_path.name}.antes-repair-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        )
        shutil.copy2(recordings_path, backup_path)
        print(f"  Respaldo de metadatos: {backup_path}")
    totals = _run_repair(config, recordings, target_courses, dry_run=dry_run, verbose=True)
    print()
    _print_repair_totals(totals, dry_run)
    if dry_run:
        print("  (--dry-run: no se movió ningún archivo)\n")
        return
    download_dir = Path(config["download_dir"])
    course_options = config.get("courses", {})
    selected = {slug: recordings[slug] for slug in target_courses if slug in recordings}
    rename_downloads(download_dir, selected, course_options)
    save_recordings(recordings_path, recordings)
    missing_subs = sum(
        1 for slug in target_courses
        for rec_info in recordings.get(slug, {}).get("recordings", {}).values()
        if rec_info.get("zoom_subs_missing") and not rec_info.get("empty_recording")
    )
    if missing_subs:
        print("  Re-descargando subtítulos de Zoom de las clases marcadas...")
        recovered = _redownload_missing_subs(config, recordings, target_courses)
        print(f"  ✔ Subtítulos recuperados en {recovered} clases")
        rename_downloads(download_dir, selected, course_options)
        for slug in target_courses:
            fabrica_ids = _fabrica_ids_for(config, slug)
            for rec_info in recordings.get(slug, {}).get("recordings", {}).values():
                if rec_info.get("zoom_subs_missing") and _recording_subs_present(
                    download_dir / slug, rec_info, fabrica_ids,
                ):
                    rec_info.pop("zoom_subs_missing", None)
    copy_transcripts(download_dir, recordings, course_options, course_slugs=target_courses)
    save_recordings(recordings_path, recordings)
    print()


def fase_final(config, recordings, target_courses, assistant_override=None, ollama_model=None):
    from claude_udea.download import copy_transcripts, count_transcripts, rename_downloads

    download_dir = Path(config["download_dir"])
    course_options = config.get("courses", {})

    repair_totals = _run_repair(config, recordings, target_courses, verbose=True)
    if any(repair_totals[key] for key in ("backup", "rename", "reassign")):
        _print_repair_totals(repair_totals, dry_run=False)

    with Spinner("Organizando transcripciones..."):
        selected = {slug: recordings[slug] for slug in target_courses if slug in recordings}
        rename_downloads(download_dir, selected, course_options)
        missing_subs = any(
            rec_info.get("zoom_subs_missing") and not rec_info.get("empty_recording")
            for slug in target_courses
            for rec_info in recordings.get(slug, {}).get("recordings", {}).values()
        )
        if missing_subs:
            print("  Re-descargando subtítulos Zoom de las grabaciones recuperables...")
            recovered = _redownload_missing_subs(config, recordings, target_courses)
            rename_downloads(download_dir, selected, course_options)
            for slug in target_courses:
                fabrica_ids = _fabrica_ids_for(config, slug)
                for rec_info in recordings.get(slug, {}).get("recordings", {}).values():
                    if rec_info.get("zoom_subs_missing") and _recording_subs_present(
                        download_dir / slug, rec_info, fabrica_ids,
                    ):
                        rec_info.pop("zoom_subs_missing", None)
            print(f"  ✔ Subtítulos recuperados en {recovered} clases")
        copy_transcripts(download_dir, recordings, course_options, course_slugs=target_courses)
        save_recordings(Path(config["recordings_file"]), recordings)

    total_vtts = 0
    for slug in target_courses:
        if slug not in recordings:
            continue
        n = count_transcripts(download_dir, slug)
        total_vtts += n

    print(f"  ✔ {total_vtts} archivos VTT listos (incluye subtítulos y capítulos)\n")

    if total_vtts == 0:
        return

    transcripts_dir = download_dir / "transcripts"
    summary_lines = []
    for slug in target_courses:
        if slug not in recordings:
            continue
        course = recordings[slug]
        course_dir = transcripts_dir / slug
        if not course_dir.exists():
            continue
        vtts = sorted(course_dir.glob("*.transcript.vtt"))
        if not vtts:
            vtts = sorted(course_dir.glob("*.vtt"))
        summary_lines.append(f"- {course['name']} ({len(vtts)} transcripciones): {course_dir}")

    prompt = (
        "Hola. Acabo de descargar las transcripciones de mis clases. "
        "Tengo esto disponible:\n\n"
        + "\n".join(summary_lines) + "\n\n"
        "Presentate brevemente y mostrame que comandos tengo disponibles."
    )

    work_dir = download_dir.parent
    assistant = assistant_override or _get_assistant(config)

    if assistant == "none":
        print("  Modo sin asistente: no se abre Claude Code, Gemini ni Ollama.")
        print(f"  Tus .vtt están en:\n    {transcripts_dir.resolve()}\n")
        return

    if assistant == "ollama":
        from claude_udea.ollama_chat import run_session
        run_session(
            work_dir,
            transcripts_dir,
            model=ollama_model,
            session_summary="\n".join(summary_lines),
        )
        return

    if assistant == "gemini":
        cmd = ["gemini"]
    else:
        cmd = ["claude", "--dangerously-skip-permissions", prompt]

    try:
        subprocess.run(cmd, cwd=str(work_dir.resolve()))
    except FileNotFoundError:
        print(f"  '{assistant}' no esta en el PATH.")
        if assistant == "gemini":
            print("  Instala con: npm install -g @google/gemini-cli")
        else:
            print("  Instala con: npm install -g @anthropic-ai/claude-code")
        print(f"  O abri manualmente en: {work_dir.resolve()}")


def _sync_moodle_materials(work_dir: Path, config: dict, target_courses: list[str]):
    from claude_udea.auth import login, migrate_saved_secrets
    from claude_udea.materials import scrape_course_materials

    moodle_courses = {
        slug: config["courses"][slug]
        for slug in target_courses
        if urlparse(config["courses"][slug].get("moodle_url", "")).hostname
        == "udearroba.udea.edu.co"
    }
    ingenia_courses = set(target_courses) - set(moodle_courses)
    if not moodle_courses:
        print("  No hay asignaturas Moodle en la selección para descargar materiales.\n")
        return

    if ingenia_courses:
        print(
            "  Ingenia: se omiten los materiales del curso; la configuración actual "
            "solo contiene enlaces públicos de reuniones Zoom."
        )

    session = login(work_dir)
    materials_root = Path(config["download_dir"]).parent / "course-materials"
    failures = 0
    for slug, course_info in moodle_courses.items():
        destination = materials_root / slug
        try:
            manifest = scrape_course_materials(session, course_info, destination)
        except Exception as error:
            failures += 1
            print(f"  ⚠ {course_info['name']}: no se pudo recorrer el curso: {error}")
            continue
        course_failures = len(manifest["failures"])
        failures += course_failures
        print(
            f"  ✔ {course_info['name']}: {manifest['file_count']} archivos, "
            f"{manifest['page_count']} páginas, "
            f"{manifest['external_link_count']} enlaces externos, "
            f"{course_failures} fallos"
        )
        print(f"    {destination}")

    migrated = migrate_saved_secrets(work_dir)
    if migrated:
        print("  ✔ Sesiones y credenciales migradas a Windows Credential Manager.")
        print("    Se eliminaron los JSON legados solo después de verificar el almacén seguro.")
    if failures:
        print(f"  ⚠ La sincronización terminó con {failures} elementos que requieren revisión.\n")
    else:
        print("  ✔ Materiales Moodle sincronizados.\n")


def _sync_ingenia_materials(work_dir: Path, course_url: str):
    from claude_udea.ingenia import sync_course_materials

    manifest = sync_course_materials(course_url, work_dir)
    print(
        f"  ✔ Ingenia: {manifest['file_count']} archivos, "
        f"{manifest['page_count']} páginas, "
        f"{manifest['external_link_count']} enlaces externos, "
        f"{len(manifest['failures'])} fallos"
    )
    print(f"    {work_dir / 'course-materials' / f"ingenia-{manifest['course_id']}"}")
    if manifest["failures"]:
        print("  ⚠ Algunos recursos no pudieron descargarse; revisa el manifest.json.\n")


# ─── Main ────────────────────────────────────────────────────

def _filter_course_args(args: list[str]) -> list[str]:
    value_flags = {
        "--whisper-model", "--whisper-compute-type", "--whisper-device",
        "--whisper-cpu-threads", "--whisper-beam-size", "--whisper-language",
        "--whisper-initial-prompt", "--whisper-chunk-seconds", "--class",
        "--keep-zoom-transcripts", "--discard-zoom-transcripts",
    }
    result = []
    index = 0
    while index < len(args):
        flag, separator, _value = args[index].partition("=")
        if flag in value_flags:
            index += 1 if separator else 2
            continue
        result.append(args[index])
        index += 1
    return result


def main():
    from claude_udea.ollama_chat import parse_ollama_model_flag
    args, ollama_model = parse_ollama_model_flag(sys.argv[1:])
    use_ollama = "--ollama" in args
    repair_only = "--repair-videos" in args
    no_assistant = "--no-assistant" in args or "--no-claude" in args or repair_only
    if use_ollama and no_assistant:
        print("  Usa --ollama o --no-assistant, no ambos.\n")
        sys.exit(2)
    if ollama_model and not use_ollama:
        print("  --ollama-model requiere --ollama.\n")
        sys.exit(2)

    sync_materials_only = "--sync-materials" in args
    sync_ingenia_only = "--sync-ingenia-materials" in args
    if sync_materials_only and sync_ingenia_only:
        print("  Usa --sync-materials o --sync-ingenia-materials, no ambos.\n")
        sys.exit(2)
    if sync_ingenia_only:
        from claude_udea.deps import check_and_install
        if not check_and_install(skip_assistant=True):
            sys.exit(1)
        work_dir = _get_work_dir()
        url_index = args.index("--sync-ingenia-materials") + 1
        if url_index >= len(args) or args[url_index].startswith("--"):
            print("  Uso: claude_udea --sync-ingenia-materials <URL-del-curso>\n")
            sys.exit(2)
        try:
            _sync_ingenia_materials(work_dir, args[url_index])
        except (PermissionError, RuntimeError, ValueError) as error:
            print(f"  ⚠ {error}\n")
            sys.exit(1)
        return
    if sync_materials_only:
        from claude_udea.deps import check_and_install
        if not check_and_install(skip_assistant=True):
            sys.exit(1)
        work_dir = _get_work_dir()
        config = load_config(work_dir)
        course_args = [
            arg for arg in args
            if not arg.startswith("--") and arg not in {"--sync-materials"}
        ]
        all_courses = list(config["courses"].keys())
        unknown_courses = [slug for slug in course_args if slug not in config["courses"]]
        if unknown_courses:
            print(f"  Asignaturas no encontradas: {', '.join(unknown_courses)}")
            print(f"  Disponibles: {', '.join(all_courses)}\n")
            sys.exit(2)
        _sync_moodle_materials(work_dir, config, course_args or all_courses)
        return

    # Validar dependencias
    from claude_udea.deps import check_and_install
    if not (repair_only and "--dry-run" in args) and not check_and_install(
        skip_assistant=use_ollama or no_assistant,
        require_whisper="--always-whisper" in args,
    ):
        sys.exit(1)

    work_dir = WORK_DIR if repair_only else _get_work_dir()

    config = load_config(work_dir)
    recordings_path = Path(config["recordings_file"])
    download_dir = Path(config["download_dir"])

    dry_run = "--dry-run" in args
    if repair_only:
        course_args = [
            arg for index, arg in enumerate(args)
            if not arg.startswith("--")
            and (index == 0 or args[index - 1] not in {"--whisper-model", "--whisper-compute-type", "--whisper-device", "--whisper-cpu-threads", "--whisper-beam-size", "--whisper-language", "--whisper-initial-prompt", "--whisper-chunk-seconds"})
        ]
        all_courses = list(config["courses"].keys())
        unknown = [slug for slug in course_args if slug not in config["courses"]]
        if unknown:
            print(f"  Asignaturas no encontradas: {', '.join(unknown)}")
            print(f"  Disponibles: {', '.join(all_courses)}\n")
            sys.exit(2)
        print("\n  UdeA Zoom → Transcripciones → AI\n")
        repair_videos_command(config, course_args or all_courses, dry_run=dry_run)
        return

    import questionary
    from questionary import Style

    from claude_udea.download import get_archive_path
    archive_path = get_archive_path(download_dir)

    # Flags
    status_only = "--status" in args
    skip_scrape = "--skip-scrape" in args or repair_only
    skip_video_flag = "--skip-video" in args
    download_all_flag = "--all" in args
    add_course_flag = "--add-course" in args
    skip_materials = "--skip-materials" in args or repair_only
    always_whisper = "--always-whisper" in args

    if add_course_flag:
        from claude_udea.setup import add_course
        add_course(work_dir)
        # Regenerar CLAUDE.md con la nueva asignatura
        _generate_assistant_md(work_dir)
        return

    course_args = [a for a in _filter_course_args(args) if not a.startswith("--")]
    all_courses = list(config["courses"].keys())

    for slug in course_args:
        if slug not in config["courses"]:
            print(f"\n  Asignatura '{slug}' no encontrada.")
            print(f"  Disponibles: {', '.join(all_courses)}")
            sys.exit(1)

    target_courses = course_args if course_args else all_courses

    # Banner
    print("\n  UdeA Zoom → Transcripciones → AI\n")

    # Status
    if status_only:
        recordings = load_recordings(recordings_path)
        if not recordings:
            print("  No hay datos aún.\n")
            return
        for slug, course in recordings.items():
            recs = course.get("recordings", {})
            ct = len(recs)
            cd = sum(
                1 for rid, rec_info in recs.items()
                if not _recording_video_missing(
                    Path(config["download_dir"]) / slug, rec_info, rid,
                    _fabrica_ids_for(config, slug),
                )
            )
            s = "✔" if cd == ct else "…"
            print(f"  {s} {course['name']}: {cd}/{ct}")
        print()
        return

    # Menú
    skip_video = skip_video_flag
    if not skip_video_flag and not download_all_flag and not dry_run:
        choice = questionary.select(
            "¿Qué deseas descargar?",
            choices=[
                questionary.Choice(
                    title=[("fg:ansicyan bold", "⚡ Solo transcripciones"), ("", "  (rápido)")],
                    value="transcripts",
                ),
                questionary.Choice(
                    title=[("fg:ansiyellow bold", "🎬 Video + transcripciones"), ("", "  (varios GB)")],
                    value="all",
                ),
            ],
            style=Style([("highlighted", "bold"), ("pointer", "bold")]),
            instruction="(↑↓ mover, Enter seleccionar)",
        ).ask()
        if choice is None:
            sys.exit(0)
        skip_video = (choice == "transcripts")

    print()

    # Scraping + Descarga (pipeline paralelo)
    if skip_scrape:
        recordings = load_recordings(recordings_path)
        if not recordings:
            print("  No hay datos previos. Ejecutá sin --skip-scrape.\n")
            sys.exit(1)
    recordings, failed = fase_scraping_y_descarga(
        work_dir, config, recordings_path, target_courses, skip_video, dry_run,
        skip_scrape=skip_scrape,
    )

    if always_whisper and not dry_run:
        try:
            from transcribe_missing import has_zoom_transcripts, settings_from_args, transcribe_all
            keep_zoom_transcripts = "--discard-zoom-transcripts" not in args
            if "--keep-zoom-transcripts" not in args and "--discard-zoom-transcripts" not in args:
                if has_zoom_transcripts(work_dir, target_courses):
                    keep_zoom_transcripts = questionary.confirm(
                        "Hay transcripciones de Zoom. ¿Conservarlas además de las de faster-whisper?",
                        default=True,
                    ).ask()
                    if keep_zoom_transcripts is None:
                        sys.exit(0)
            class_numbers = []
            for index, token in enumerate(args):
                if token == "--class" and index + 1 < len(args):
                    try:
                        class_numbers.append(int(args[index + 1]))
                    except ValueError:
                        pass
            whisper_ok, whisper_failed = transcribe_all(
                work_dir,
                target_courses,
                keep_zoom_transcripts=keep_zoom_transcripts,
                settings=settings_from_args(args),
                class_numbers=class_numbers or None,
            )
            failed += whisper_failed
            print(f"  faster-whisper: {whisper_ok} completadas, {whisper_failed} fallidas.\n")
            if whisper_ok:
                fase_final(
                    config,
                    recordings,
                    target_courses,
                    assistant_override="none",
                )
                if skip_materials:
                    print("  Materiales omitidos por --skip-materials.\n")
                return
        except (OSError, RuntimeError, ValueError) as error:
            print(f"  ⚠ No se pudo iniciar faster-whisper: {error}\n")
            failed += 1
        except ImportError as error:
            print(
                "  ⚠ No se pudo importar el módulo de transcripción. "
                "Reinstala claude-udea en el mismo entorno de Python del comando: "
                f"{error}\n"
            )
            failed += 1

    if not dry_run and not skip_materials:
        _sync_moodle_materials(work_dir, config, target_courses)

    # Organizar transcripciones + asistente elegido
    if not dry_run:
        assistant_override = "ollama" if use_ollama else "none" if no_assistant else None
        fase_final(
            config,
            recordings,
            target_courses,
            assistant_override=assistant_override,
            ollama_model=ollama_model,
        )
