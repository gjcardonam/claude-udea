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
1. **En el nombre del archivo**: prefijo `YYYY-MM-DD_` (ej: `2026-03-09_CALIDAD...vtt`)
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
    known_dates = {
        rec["start_date"]
        for rec in course_data["recordings"].values()
        if rec.get("start_date")
    }

    new_pending = []
    for link in links:
        rec_id = extract_recording_id(link["url"])
        start_date = link.get("start_date", "")

        if rec_id in course_data["recordings"]:
            course_data["recordings"][rec_id]["url"] = link["full_url"]
            course_data["recordings"][rec_id]["share_url"] = link["url"]
            continue
        if start_date and start_date in known_dates:
            continue

        rec_info = {
            "url": link["full_url"],
            "share_url": link["url"],
            "title": link.get("topic") or link["text"],
            "meeting_id": link.get("meeting_id", ""),
            "start_date": start_date,
            "duration_minutes": link.get("duration_minutes", 0),
            "scraped_at": datetime.now().isoformat(),
            "downloaded": False,
        }
        course_data["recordings"][rec_id] = rec_info
        known_dates.add(start_date)
        url = rec_info.get("url") or rec_info.get("share_url", "")
        if url:
            new_pending.append((slug, rec_id, rec_info, url))

    course_data["last_scraped"] = datetime.now().isoformat()
    return new_pending


def fase_scraping_y_descarga(work_dir, config, recordings_path, target_courses, skip_video, dry_run, skip_scrape=False):
    """
    Pipeline paralelo: login → scrape todas las materias en paralelo →
    a medida que cada scrape termina, lanza descargas inmediatamente.
    Todo con un solo ThreadPoolExecutor.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from claude_udea.auth import login, _scrape_one
    from claude_udea.download import get_archive_path, is_downloaded, download_one
    from tqdm import tqdm

    existing = load_recordings(recordings_path)
    download_dir = Path(config["download_dir"])
    archive_path = get_archive_path(download_dir)

    courses_to_scrape = {slug: config["courses"][slug] for slug in target_courses}

    # Login solo si vamos a scrapear
    session = None
    if not skip_scrape:
        session = login(work_dir)

    # Contar ya descargadas
    already = 0
    for slug in target_courses:
        if slug not in existing:
            continue
        for rec_id, rec_info in existing[slug].get("recordings", {}).items():
            if rec_info.get("downloaded") or is_downloaded(archive_path, rec_id):
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

                # Merge y obtener pendientes nuevos
                new_pending = _merge_scraped(existing, config, slug, links)

                # Filtrar los que ya están descargados
                pending = []
                for item in new_pending:
                    _, rec_id, _, _ = item
                    if not is_downloaded(archive_path, rec_id):
                        pending.append(item)
                    else:
                        already += 1

                # También agregar pendientes de ejecuciones previas
                if slug in existing:
                    for rec_id, rec_info in existing[slug].get("recordings", {}).items():
                        if rec_info.get("downloaded") or is_downloaded(archive_path, rec_id):
                            continue
                        url = rec_info.get("url") or rec_info.get("share_url", "")
                        if url and not any(p[1] == rec_id for p in pending):
                            pending.append((slug, rec_id, rec_info, url))

                total_new += len(new_pending)
                print(f"  ✔ {course_name}: {len(links)} grabaciones, {len(pending)} pendientes")

                # Lanzar descargas en paralelo
                for item in pending:
                    slug_d, rec_id, rec_info, url = item
                    course_dir = download_dir / slug_d
                    df = pool.submit(download_one, url, course_dir, archive_path, skip_video, dry_run)
                    download_futures.append((slug_d, rec_id, rec_info, df))
        else:
            # Sin scraping: solo descargar pendientes existentes
            for slug in target_courses:
                if slug not in existing:
                    continue
                for rec_id, rec_info in existing[slug].get("recordings", {}).items():
                    if rec_info.get("downloaded") or is_downloaded(archive_path, rec_id):
                        already += 1
                        continue
                    url = rec_info.get("url") or rec_info.get("share_url", "")
                    if url:
                        course_dir = download_dir / slug
                        df = pool.submit(download_one, url, course_dir, archive_path, skip_video, dry_run)
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
                    rec_info["downloaded"] = True
                    rec_info["downloaded_at"] = datetime.now().isoformat()
                    total_ok += 1
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
        "Presentate brevemente y mostrame que comandos tengo disponibles."
    )

    work_dir = download_dir.parent
    assistant = _get_assistant(config)

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
        _generate_assistant_md(work_dir)
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

    # Organizar transcripciones + Claude Code
    if not dry_run:
        fase_final(config, recordings, target_courses)
