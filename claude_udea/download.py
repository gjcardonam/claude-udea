"""
Módulo de descarga: descarga grabaciones con yt-dlp.
Aislado para que cambios en otras partes no lo afecten.
"""

import json
import re
import subprocess
import sys
import shutil
from datetime import datetime
from pathlib import Path


def get_archive_path(download_dir: Path) -> Path:
    return download_dir / ".download-archive.txt"


def is_downloaded(archive_path: Path, rec_id: str) -> bool:
    if not archive_path.exists():
        return False
    content = archive_path.read_text(encoding="utf-8")
    return rec_id in content


def download_one(url, output_dir, archive_path, skip_video=False, dry_run=False):
    """Descarga una grabación. Retorna 'ok', 'processing' o 'error'."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(title)s [%(id)s].%(ext)s")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        url,
        "-o", output_template,
        "--write-subs", "--all-subs",
        "--sub-format", "vtt/srt/best",
        "--convert-subs", "vtt",
        "--no-overwrites",
        "--retries", "3",
        "--fragment-retries", "3",
        "--no-warnings",
        "--download-archive", str(archive_path),
    ]

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
            # yt-dlp con --skip-download no escribe al archive, hacerlo manualmente
            if skip_video and not dry_run:
                rec_id = _extract_rec_id_from_url(url)
                if rec_id and not is_downloaded(archive_path, rec_id):
                    with open(archive_path, "a", encoding="utf-8") as f:
                        f.write(f"zoomus {rec_id}\n")
            return "ok"
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


def _build_rec_id_map(recordings: dict) -> dict:
    """Mapa de rec_id -> {slug, course_name, start_date, duration, title}."""
    id_map = {}
    for slug, course in recordings.items():
        for rec_id, rec_info in course.get("recordings", {}).items():
            id_map[rec_id] = {
                "slug": slug,
                "course_name": course.get("name", slug),
                "start_date": rec_info.get("start_date", ""),
                "duration_minutes": rec_info.get("duration_minutes", 0),
                "title": rec_info.get("title", ""),
            }
    return id_map


def _parse_date_prefix(start_date: str) -> str:
    """Convierte '2026-03-09T11:00:58Z' a '2026-03-09'."""
    if not start_date:
        return "sin-fecha"
    try:
        dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "sin-fecha"


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


def copy_transcripts(download_dir: Path, recordings: dict = None) -> int:
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

    id_map = _build_rec_id_map(recordings)
    count = 0
    index = {}

    # Limpiar carpeta de transcripts para regenerar con nuevos nombres
    if transcripts_dir.exists():
        for child in transcripts_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.name != ".gitkeep":
                child.unlink()

    def process_vtt(vtt_file: Path, course_slug: str):
        nonlocal count
        rec_id = _extract_rec_id_from_filename(vtt_file.name)
        meta = id_map.get(rec_id, {})
        date_str = _parse_date_prefix(meta.get("start_date", ""))
        course_name = meta.get("course_name", course_slug)
        duration = meta.get("duration_minutes", 0)
        title = meta.get("title", "")

        new_name = f"{date_str}_{vtt_file.name}"
        course_transcripts = transcripts_dir / course_slug
        course_transcripts.mkdir(parents=True, exist_ok=True)
        dest = course_transcripts / new_name

        vtt_content = vtt_file.read_text(encoding="utf-8", errors="replace")
        enriched = _inject_vtt_metadata(vtt_content, course_name, date_str, duration, title)
        dest.write_text(enriched, encoding="utf-8")
        count += 1

        vtt_type = "transcript" if ".transcript." in vtt_file.name else "chapter"

        if course_slug not in index:
            index[course_slug] = {"course_name": course_name, "files": []}
        index[course_slug]["files"].append({
            "file": new_name,
            "date": date_str,
            "topic": title,
            "duration_minutes": duration,
            "type": vtt_type,
        })

    for course_dir in download_dir.iterdir():
        if not course_dir.is_dir() or course_dir.name in ("transcripts", ".browser-data"):
            continue
        slug = course_dir.name

        for rec_dir in course_dir.iterdir():
            if not rec_dir.is_dir():
                continue
            for vtt_file in rec_dir.glob("*.vtt"):
                process_vtt(vtt_file, slug)

        for vtt_file in course_dir.glob("*.vtt"):
            process_vtt(vtt_file, slug)

    # Ordenar por fecha
    for slug in index:
        index[slug]["files"].sort(key=lambda x: x["date"])

    # Escribir index.json
    if index:
        index_path = transcripts_dir / "index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    return count


def count_transcripts(download_dir: Path, slug: str) -> int:
    """Cuenta VTTs de una asignatura en transcripts/."""
    course_transcripts = download_dir / "transcripts" / slug
    if not course_transcripts.exists():
        return 0
    return len(list(course_transcripts.glob("*.vtt")))
