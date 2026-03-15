"""
Módulo de descarga: descarga grabaciones con yt-dlp.
Aislado para que cambios en otras partes no lo afecten.
"""

import subprocess
import sys
import shutil
from pathlib import Path


def get_archive_path(download_dir: Path) -> Path:
    return download_dir / ".download-archive.txt"


def is_downloaded(archive_path: Path, rec_id: str) -> bool:
    if not archive_path.exists():
        return False
    content = archive_path.read_text(encoding="utf-8")
    return rec_id in content


def download_one(url, output_dir, archive_path, skip_video=False, dry_run=False):
    """Descarga una grabación. Retorna True si OK."""
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
        return result.returncode == 0
    except Exception:
        return False


def copy_transcripts(download_dir: Path) -> int:
    """Copia VTTs a carpeta centralizada. Retorna cantidad copiada."""
    transcripts_dir = download_dir / "transcripts"
    count = 0

    for course_dir in download_dir.iterdir():
        if not course_dir.is_dir() or course_dir.name in ("transcripts", ".browser-data"):
            continue
        course_transcripts = transcripts_dir / course_dir.name

        # VTTs en subdirectorios
        for rec_dir in course_dir.iterdir():
            if not rec_dir.is_dir():
                continue
            for vtt_file in rec_dir.glob("*.vtt"):
                course_transcripts.mkdir(parents=True, exist_ok=True)
                dest = course_transcripts / vtt_file.name
                if not dest.exists():
                    shutil.copy2(vtt_file, dest)
                    count += 1

        # VTTs sueltos en carpeta del curso
        for vtt_file in course_dir.glob("*.vtt"):
            course_transcripts.mkdir(parents=True, exist_ok=True)
            dest = course_transcripts / vtt_file.name
            if not dest.exists():
                shutil.copy2(vtt_file, dest)
                count += 1

    return count


def count_transcripts(download_dir: Path, slug: str) -> int:
    """Cuenta VTTs de una asignatura en transcripts/."""
    course_transcripts = download_dir / "transcripts" / slug
    if not course_transcripts.exists():
        return 0
    return len(list(course_transcripts.glob("*.vtt")))
