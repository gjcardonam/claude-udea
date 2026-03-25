"""
CLI principal: claude_udea
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
    """Copia CLAUDE.md, rules y skills si no existen."""
    import shutil
    templates_dir = Path(__file__).parent / "templates"
    if not templates_dir.exists():
        return

    # CLAUDE.md — regenerar siempre con las asignaturas actuales
    _generate_claude_md(work_dir)

    # .claude/rules.md y skills/
    src_claude_dir = templates_dir / ".claude"
    dest_claude_dir = work_dir / ".claude"
    if src_claude_dir.exists():
        dest_claude_dir.mkdir(exist_ok=True)
        src_rules = src_claude_dir / "rules.md"
        dest_rules = dest_claude_dir / "rules.md"
        if src_rules.exists() and not dest_rules.exists():
            shutil.copy2(src_rules, dest_rules)
        src_skills = src_claude_dir / "skills"
        dest_skills = dest_claude_dir / "skills"
        if src_skills.exists():
            dest_skills.mkdir(exist_ok=True)
            for skill_file in src_skills.glob("*.md"):
                dest_skill = dest_skills / skill_file.name
                if not dest_skill.exists():
                    shutil.copy2(skill_file, dest_skill)


def _generate_claude_md(work_dir: Path):
    """Genera CLAUDE.md dinámicamente según las asignaturas configuradas."""
    config_path = work_dir / "config.json"
    if not config_path.exists():
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    courses = config.get("courses", {})
    course_lines = "\n".join(
        f"- **{info['name']}** → `downloads/transcripts/{slug}/`"
        for slug, info in courses.items()
    )

    content = f"""# Asistente Académico UdeA

Eres un asistente académico especializado para un estudiante de la Universidad de Antioquia. Tu única fuente de verdad son las transcripciones de clase en formato WebVTT ubicadas en `downloads/transcripts/`.

## Asignaturas

{course_lines}

## Fechas y metadata

Cada archivo VTT tiene la fecha de la clase de tres formas:
1. **En el nombre del archivo**: prefijo `YYYY-MM-DD_` (ej: `2026-03-09_CALIDAD...vtt`)
2. **Dentro del archivo**: bloque `NOTE` al inicio con fecha, asignatura, tema y duración
3. **En el índice**: `downloads/transcripts/index.json` tiene un listado completo ordenado por fecha

Cuando el estudiante pregunte "cuándo se dijo X" o "qué se vio el día Y", usa estas fechas para dar respuestas precisas. Lee `index.json` primero para ubicar las grabaciones por fecha sin tener que abrir cada archivo.

## Funciones principales

### 1. Enseñar
Enseñar TODO lo visto en clase de forma organizada, profesional, al grano. No omitir ningún tema. No inventar contenido que no esté en las transcripciones. Cada tema debe tener referencia a la grabación y minuto donde se trató.

### 2. Informar compromisos
Encontrar TODOS los pendientes: parciales, quices, tareas, talleres, trabajos, entregas, exposiciones, o cualquier actividad mencionada en clase. Presentarlos visualmente de forma clara con fechas y estado.

### 3. Planear y organizar
Ayudar al estudiante a planificar su tiempo: crear horarios de estudio, priorizar tareas, distribuir carga académica, y asegurar que cumpla con todo.

## Reglas de referencia

Siempre que menciones un tema o un pendiente, incluye:
- Nombre del archivo VTT (grabación)
- Fecha de la clase
- Timestamp (minuto aproximado)
- Asignatura

Formato: `[Asignatura | 2026-03-09 | archivo.vtt | ~min 23]`

## Cómo leer las transcripciones

Los archivos `.vtt` tienen este formato:
```
WEBVTT

NOTE
Fecha de clase: 2026-03-09
Asignatura: Calidad de Software
Tema: CALIDAD DE SOFTWARE (2026-1)
Duración: 81 min

1
00:12:34.000 --> 00:12:38.000
texto que dijo el profesor
```

El timestamp `00:12:34` = minuto 12. Usa eso para dar referencias.

## Comportamiento

- Responde en español
- Sé directo y conciso a menos que te pidan profundizar
- No des ejemplos a menos que te los pidan (usa /ejemplos)
- Si el estudiante se desvía del tema académico, redirige amablemente
- Nunca inventes información que no esté en las transcripciones
- Si no encuentras algo en las transcripciones, dilo honestamente
"""

    with open(work_dir / "CLAUDE.md", "w", encoding="utf-8") as f:
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
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Deduplicar por start_date dentro de cada curso
        changed = False
        for slug, course in data.items():
            recs = course.get("recordings", {})
            seen_dates = {}
            to_remove = []
            for rec_id, rec_info in recs.items():
                sd = rec_info.get("start_date", "")
                if not sd:
                    continue
                if sd in seen_dates:
                    # Mantener el que ya fue descargado, o el primero
                    existing_id = seen_dates[sd]
                    if rec_info.get("downloaded") and not recs[existing_id].get("downloaded"):
                        to_remove.append(existing_id)
                        seen_dates[sd] = rec_id
                    else:
                        to_remove.append(rec_id)
                else:
                    seen_dates[sd] = rec_id
            for rid in to_remove:
                del recs[rid]
                changed = True
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        return data
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


# ─── Fase 1: Scraping ───────────────────────────────────────

def fase_scraping(work_dir, config, recordings_path, target_courses):
    from claude_udea.browser import login_and_scrape

    existing = load_recordings(recordings_path)

    courses_to_scrape = {slug: config["courses"][slug] for slug in target_courses}

    scraped = asyncio.run(login_and_scrape(work_dir, courses_to_scrape))

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
        # Índice de start_dates existentes para deduplicar
        known_dates = {
            rec["start_date"]
            for rec in course_data["recordings"].values()
            if rec.get("start_date")
        }
        for link in links:
            rec_id = extract_recording_id(link["url"])
            start_date = link.get("start_date", "")

            # Duplicado si ya existe por rec_id O por start_date
            if rec_id in course_data["recordings"]:
                # Actualizar URL por si cambió el share token
                course_data["recordings"][rec_id]["url"] = link["full_url"]
                course_data["recordings"][rec_id]["share_url"] = link["url"]
                continue
            if start_date and start_date in known_dates:
                continue

            course_data["recordings"][rec_id] = {
                "url": link["full_url"],
                "share_url": link["url"],
                "title": link.get("topic") or link["text"],
                "meeting_id": link.get("meeting_id", ""),
                "start_date": start_date,
                "duration_minutes": link.get("duration_minutes", 0),
                "scraped_at": datetime.now().isoformat(),
                "downloaded": False,
            }
            known_dates.add(start_date)
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
    from claude_udea.download import get_archive_path, is_downloaded, download_one
    from tqdm import tqdm

    download_dir = Path(config["download_dir"])
    archive_path = get_archive_path(download_dir)

    # Planificar
    pending = []
    already = 0
    for slug in target_courses:
        if slug not in recordings:
            continue
        course = recordings[slug]
        for rec_id, rec_info in course.get("recordings", {}).items():
            if rec_info.get("downloaded") or is_downloaded(archive_path, rec_id):
                already += 1
            else:
                url = rec_info.get("url") or rec_info.get("share_url", "")
                if url:
                    pending.append((slug, rec_id, rec_info, url))

    if not pending:
        print(f"  ✔ {already} grabaciones ya descargadas, nada nuevo\n")
        return 0

    print(f"  {already} ya descargadas, {len(pending)} pendientes\n")

    mode = "Descargando transcripciones" if skip_video else "Descargando video + transcripciones"
    pbar = tqdm(
        pending, desc=f"  {mode}", unit="grab",
        bar_format="  {desc}  {bar}  {n_fmt}/{total_fmt}",
        ncols=70,
    )

    total_failed = 0
    total_processing = 0
    for slug, rec_id, rec_info, url in pbar:
        course_dir = download_dir / slug
        status = download_one(url, course_dir, archive_path, skip_video, dry_run)
        if status == "ok":
            rec_info["downloaded"] = True
            rec_info["downloaded_at"] = datetime.now().isoformat()
        elif status == "processing":
            total_processing += 1
        else:
            total_failed += 1

    pbar.close()

    if not dry_run:
        recordings_path = Path(config["recordings_file"])
        save_recordings(recordings_path, recordings)

    ok_count = len(pending) - total_failed - total_processing
    parts = []
    if ok_count:
        parts.append(f"{ok_count} descargadas")
    if total_processing:
        parts.append(f"{total_processing} aún procesándose en Zoom")
    if total_failed:
        parts.append(f"{total_failed} fallidas")
    if parts:
        print(f"\n  ✔ {', '.join(parts)}\n")
    else:
        print(f"\n  ✔ Listo\n")

    return total_failed


# ─── Fase 3: Validación + Claude Code ───────────────────────

def fase_final(config, recordings, target_courses):
    from claude_udea.download import copy_transcripts, count_transcripts

    download_dir = Path(config["download_dir"])

    with Spinner("Organizando transcripciones..."):
        copy_transcripts(download_dir, recordings)

    total_vtts = 0
    for slug in target_courses:
        if slug not in recordings:
            continue
        n = count_transcripts(download_dir, slug)
        total_vtts += n

    print(f"  ✔ {total_vtts} transcripciones listas\n")

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
        "Presentate brevemente y mostrame qué comandos tengo disponibles."
    )

    # Abrir Claude Code desde C:\claude-udea donde está CLAUDE.md y las skills
    work_dir = download_dir.parent
    try:
        subprocess.run(["claude", "--dangerously-skip-permissions", prompt], cwd=str(work_dir.resolve()))
    except FileNotFoundError:
        print("  'claude' no está en el PATH.")
        print(f"  Abrilo manualmente en: {work_dir.resolve()}")


# ─── Main ────────────────────────────────────────────────────

def main():
    # Validar dependencias
    from claude_udea.deps import check_and_install
    if not check_and_install():
        sys.exit(1)

    import questionary
    from questionary import Style

    work_dir = _get_work_dir()

    config = load_config(work_dir)
    recordings_path = Path(config["recordings_file"])
    download_dir = Path(config["download_dir"])

    from claude_udea.download import get_archive_path, is_downloaded
    archive_path = get_archive_path(download_dir)

    # Flags
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    status_only = "--status" in args
    skip_scrape = "--skip-scrape" in args
    skip_video_flag = "--skip-video" in args
    download_all_flag = "--all" in args
    add_course_flag = "--add-course" in args

    if add_course_flag:
        from claude_udea.setup import add_course
        add_course(work_dir)
        # Regenerar CLAUDE.md con la nueva asignatura
        _generate_claude_md(work_dir)
        return

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
            print("  No hay datos aún.\n")
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

    # Fase 1
    if skip_scrape:
        recordings = load_recordings(recordings_path)
        if not recordings:
            print("  No hay datos previos. Ejecutá sin --skip-scrape.\n")
            sys.exit(1)
    else:
        recordings = fase_scraping(work_dir, config, recordings_path, target_courses)

    # Fase 2
    failed = fase_descarga(config, recordings, target_courses, skip_video, dry_run)

    # Fase 3
    if not dry_run:
        fase_final(config, recordings, target_courses)
