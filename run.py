"""
UdeA Zoom Recording Pipeline
python run.py                         # Flujo completo
python run.py --skip-scrape           # Saltar scraping
python run.py --skip-video            # Solo transcripciones sin preguntar
python run.py --all                   # Video + transcripciones sin preguntar
python run.py --status                # Ver estado
python run.py --dry-run               # Simular
python run.py calidad-de-software     # Solo una asignatura
"""

import json
import subprocess
import sys
import os
import re
import asyncio
import threading
import time
from pathlib import Path
from datetime import datetime
import questionary
from questionary import Style
from tqdm import tqdm

from browser import do_login, scrape_all, force_clean
from download import (
    get_archive_path, is_downloaded, download_one,
    copy_transcripts, count_transcripts,
)

# Fix encoding for Windows console
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"


# ─── Helpers ─────────────────────────────────────────────────

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_recordings(path: Path) -> dict:
    if path.exists():
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
    """Spinner minimalista con mensaje."""
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


# ─── Fase 1: Scraping ───────────────────────────────────────

def fase_scraping(config, recordings_path, target_courses):
    existing = load_recordings(recordings_path)

    # Login visible (browser se cierra solo)
    asyncio.run(do_login())

    # Scraping headless con spinner
    courses_to_scrape = {
        slug: config["courses"][slug]
        for slug in target_courses
    }

    with Spinner("Buscando grabaciones en Moodle..."):
        scraped = asyncio.run(scrape_all(courses_to_scrape))

    # Merge resultados
    total_new = 0
    for slug, links in scraped.items():
        course_info = config["courses"][slug]
        if slug not in existing:
            existing[slug] = {
                "name": course_info["name"],
                "recordings": {},
                "last_scraped": None,
            }

        course_data = existing[slug]
        for link in links:
            rec_id = extract_recording_id(link["url"])
            if rec_id not in course_data["recordings"]:
                course_data["recordings"][rec_id] = {
                    "url": link["full_url"],
                    "share_url": link["url"],
                    "title": link.get("topic") or link["text"],
                    "meeting_id": link.get("meeting_id", ""),
                    "start_date": link.get("start_date", ""),
                    "duration_minutes": link.get("duration_minutes", 0),
                    "scraped_at": datetime.now().isoformat(),
                    "downloaded": False,
                }
                total_new += 1
        course_data["last_scraped"] = datetime.now().isoformat()

    save_recordings(recordings_path, existing)

    total_recs = sum(len(c.get("recordings", {})) for c in existing.values())
    if total_new:
        print(f"  ✔ {total_recs} grabaciones encontradas ({total_new} nuevas)\n")
    else:
        print(f"  ✔ {total_recs} grabaciones encontradas, todo al día\n")
    return existing


# ─── Fase 2: Descarga ───────────────────────────────────────

def fase_descarga(config, recordings, target_courses, skip_video, dry_run):
    download_dir = Path(config["download_dir"])
    archive_path = get_archive_path(download_dir)

    # Planificar: separar pendientes de ya descargadas
    pending = []
    already = 0
    for slug in target_courses:
        if slug not in recordings:
            continue
        course = recordings[slug]
        for rec_id, rec_info in course.get("recordings", {}).items():
            if is_downloaded(archive_path, rec_id):
                already += 1
            else:
                url = rec_info.get("url") or rec_info.get("share_url", "")
                if url:
                    pending.append((slug, rec_id, rec_info, url))

    total = already + len(pending)

    if not pending:
        print(f"  ✔ {total} grabaciones ya descargadas, nada nuevo\n")
        return 0

    print(f"  {already} ya descargadas, {len(pending)} pendientes\n")

    # Descargar solo las pendientes con una sola barra
    mode = "Descargando transcripciones" if skip_video else "Descargando video + transcripciones"
    pbar = tqdm(
        pending, desc=f"  {mode}", unit="grab",
        bar_format="  {desc}  {bar}  {n_fmt}/{total_fmt}",
        ncols=70,
    )

    total_failed = 0
    for slug, rec_id, rec_info, url in pbar:
        course_dir = download_dir / slug
        ok = download_one(url, course_dir, archive_path, skip_video, dry_run)

        if ok:
            rec_info["downloaded"] = True
            rec_info["downloaded_at"] = datetime.now().isoformat()
        else:
            total_failed += 1

    pbar.close()

    if not dry_run:
        recordings_path = Path(config["recordings_file"])
        save_recordings(recordings_path, recordings)

    ok_count = len(pending) - total_failed
    if total_failed:
        print(f"\n  ✔ {ok_count} descargadas, {total_failed} fallidas\n")
    else:
        print(f"\n  ✔ Listo\n")

    return total_failed


# ─── Fase 3: Validación + Claude Code ───────────────────────

def fase_final(config, recordings, target_courses):
    download_dir = Path(config["download_dir"])

    with Spinner("Organizando transcripciones..."):
        copy_transcripts(download_dir)

    # Reporte compacto
    total_vtts = 0
    for slug in target_courses:
        if slug not in recordings:
            continue
        n = count_transcripts(download_dir, slug)
        total_vtts += n

    print(f"  ✔ {total_vtts} transcripciones listas\n")

    if total_vtts == 0:
        return

    # Prompt para Claude Code
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
        "Tengo transcripciones de clases universitarias (UdeA, semestre 2026-1) "
        "en formato WebVTT con timestamps. Están organizadas así:\n\n"
        + "\n".join(summary_lines) + "\n\n"
        f"Directorio base: {transcripts_dir.resolve()}\n\n"
        "Puedes leer cualquier archivo .vtt para responder preguntas sobre el contenido "
        "de las clases. Las transcripciones son automáticas de Zoom, así que pueden "
        "tener errores de transcripción. ¿En qué te puedo ayudar?"
    )

    try:
        subprocess.run(["claude", prompt], cwd=str(transcripts_dir.resolve()))
    except FileNotFoundError:
        print("  'claude' no está en el PATH.")
        print(f"  Abrilo manualmente en: {transcripts_dir.resolve()}")


# ─── Main ────────────────────────────────────────────────────

def main():
    force_clean()

    config = load_config()
    recordings_path = Path(config["recordings_file"])
    download_dir = Path(config["download_dir"])
    archive_path = get_archive_path(download_dir)

    # Flags
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    status_only = "--status" in args
    skip_scrape = "--skip-scrape" in args
    skip_video_flag = "--skip-video" in args
    download_all_flag = "--all" in args

    course_args = [a for a in args if not a.startswith("--")]
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
            print("  No hay datos aún. Ejecutá python run.py primero.\n")
            return
        for slug, course in recordings.items():
            recs = course.get("recordings", {})
            ct = len(recs)
            cd = sum(1 for rid in recs if is_downloaded(archive_path, rid))
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
                questionary.Choice("Solo transcripciones  (rápido)", value="transcripts"),
                questionary.Choice("Video + transcripciones  (varios GB)", value="all"),
            ],
            style=Style([("highlighted", "bold"), ("pointer", "bold")]),
            instruction="(↑↓ mover, Enter seleccionar)",
        ).ask()
        if choice is None:
            sys.exit(0)
        skip_video = (choice == "transcripts")

    print()

    # Fase 1: Scraping
    if skip_scrape:
        recordings = load_recordings(recordings_path)
        if not recordings:
            print("  No hay datos previos. Ejecutá sin --skip-scrape.\n")
            sys.exit(1)
    else:
        recordings = fase_scraping(config, recordings_path, target_courses)

    # Fase 2: Descarga
    failed = fase_descarga(config, recordings, target_courses, skip_video, dry_run)

    # Fase 3: Organizar + Claude Code
    if not dry_run and failed == 0:
        fase_final(config, recordings, target_courses)


if __name__ == "__main__":
    main()
