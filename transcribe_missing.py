#!/usr/bin/env python3
"""
Genera transcripciones locales (faster-whisper) para grabaciones que no
tienen transcript de Zoom (.transcript.vtt) ni subtítulos (.cc.vtt).

Flujo por grabación:
  1. Descarga el video de Zoom con yt-dlp (formato 'view', el más liviano).
  2. Extrae audio 16 kHz mono con ffmpeg y borra el video.
  3. Transcribe con faster-whisper (small, int8, VAD) y escribe
     'TITULO [REC_ID].transcript.vtt' en downloads/<asignatura>/.
  4. Borra el audio y regenera downloads/transcripts/ + index.json
     con copy_transcripts() (el mismo paso del proceso normal).

Es idempotente: las grabaciones que ya tienen transcript se saltan,
así que se puede relanzar tras una interrupción o tras nuevas descargas.

Uso:
  .venv/bin/python transcribe_missing.py [--work-dir /home/gabo/claude-udea] [--check]
"""

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

from claude_udea.download import copy_transcripts  # noqa: E402

MODEL_SIZE = "small"          # mejor balance calidad/velocidad en Pi 5 (~1x tiempo real)
COMPUTE_TYPE = "int8"
CPU_THREADS = 4
LANGUAGE = "es"
# Transcribir por bloques: acota la RAM (audios de 4h enteros mataban el proceso
# en la Pi) y permite reanudar desde el último bloque completado tras un crash.
CHUNK_SECONDS = 1200


def log(msg):
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def has_transcript(course_dir: Path, rec_id: str) -> bool:
    for vtt in course_dir.glob("*.vtt"):
        if rec_id in vtt.name and (".transcript." in vtt.name or ".cc." in vtt.name):
            return True
    return False


def find_missing(work_dir: Path):
    recordings_path = work_dir / "recordings.json"
    with open(recordings_path, encoding="utf-8") as f:
        recordings = json.load(f)

    download_dir = work_dir / "downloads"
    missing = []
    for slug, course in recordings.items():
        course_dir = download_dir / slug
        for rec_id, info in course.get("recordings", {}).items():
            if not has_transcript(course_dir, rec_id):
                missing.append({
                    "slug": slug,
                    "rec_id": rec_id,
                    "url": info["url"],
                    "title": info.get("title", slug),
                    "duration": info.get("duration_minutes", 0),
                })
    # Cortas primero: resultados útiles cuanto antes
    missing.sort(key=lambda r: r["duration"])
    return recordings, missing


def download_video(rec, cache_dir: Path) -> Path | None:
    ytdlp = TOOL_DIR / ".venv" / "bin" / "yt-dlp"
    out_tpl = str(cache_dir / "%(title)s [%(id)s].%(ext)s")
    for fmt in (["-f", "view"], []):  # 'view' es el stream más liviano; sin -f como fallback
        cmd = [str(ytdlp), "--no-update", "-o", out_tpl, "--no-overwrites",
               "--retries", "3", "--fragment-retries", "3", *fmt, rec["url"]]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        matches = [p for p in cache_dir.glob("*.mp4") if rec["rec_id"] in p.name]
        if result.returncode == 0 and matches:
            return matches[0]
    return None


def extract_audio(video: Path) -> Path | None:
    wav = video.with_suffix(".wav")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
           "-vn", "-ac", "1", "-ar", "16000", str(wav)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    video.unlink(missing_ok=True)
    return wav if result.returncode == 0 and wav.exists() else None


def wav_duration(wav: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(wav)],
        capture_output=True, text=True, timeout=60)
    return float(result.stdout.strip())


def transcribe(model, wav: Path, dest_vtt: Path, parts_dir: Path):
    """Transcribe por bloques de CHUNK_SECONDS con resultados parciales en
    parts_dir; si un bloque ya tiene su .json, se salta (reanudación)."""
    total = wav_duration(wav)
    n_chunks = max(1, math.ceil(total / CHUNK_SECONDS))
    parts_dir.mkdir(parents=True, exist_ok=True)

    for i in range(n_chunks):
        part_json = parts_dir / f"part{i:03d}.json"
        if part_json.exists():
            continue
        offset = i * CHUNK_SECONDS
        chunk_wav = parts_dir / "chunk.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(offset),
             "-t", str(CHUNK_SECONDS), "-i", str(wav), "-c", "copy", str(chunk_wav)],
            capture_output=True, timeout=600, check=True)
        segments, _info = model.transcribe(
            str(chunk_wav),
            language=LANGUAGE,
            vad_filter=True,
            beam_size=1,
            condition_on_previous_text=False,  # evita bucles de repetición
        )
        data = [{"start": s.start + offset, "end": s.end + offset,
                 "text": s.text.strip()} for s in segments if s.text.strip()]
        chunk_wav.unlink(missing_ok=True)
        tmp = part_json.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.rename(part_json)  # atómico: nunca queda un parcial corrupto
        log(f"    bloque {i + 1}/{n_chunks} listo ({len(data)} segmentos)")

    cues = []
    for part_json in sorted(parts_dir.glob("part*.json")):
        cues.extend(json.loads(part_json.read_text(encoding="utf-8")))

    with open(dest_vtt, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\nNOTE\nTranscripción generada localmente con "
                f"faster-whisper ({MODEL_SIZE}, {COMPUTE_TYPE})\n\n")
        for i, seg in enumerate(cues, 1):
            f.write(f"{i}\n{fmt_ts(seg['start'])} --> {fmt_ts(seg['end'])}\n"
                    f"{seg['text']}\n\n")
    shutil.rmtree(parts_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", default="/home/gabo/claude-udea")
    parser.add_argument("--check", action="store_true",
                        help="solo listar grabaciones sin transcript, no procesar")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    recordings, missing = find_missing(work_dir)

    if not missing:
        log("Todas las grabaciones tienen transcripción. Nada que hacer.")
        return

    log(f"{len(missing)} grabaciones sin transcripción:")
    for rec in missing:
        log(f"  - [{rec['slug']}] {rec['title']} ({rec['duration']} min)")

    if args.check:
        return

    cache_dir = work_dir / ".media-cache"
    cache_dir.mkdir(exist_ok=True)

    from faster_whisper import WhisperModel
    log(f"Cargando modelo {MODEL_SIZE} ({COMPUTE_TYPE})...")
    model = WhisperModel(MODEL_SIZE, device="cpu",
                         compute_type=COMPUTE_TYPE, cpu_threads=CPU_THREADS)

    ok, failed = 0, 0
    for rec in missing:
        label = f"[{rec['slug']}] {rec['title']} ({rec['duration']} min)"

        # Reanudación: si el wav ya está en cache (corrida anterior), no
        # volver a descargar ni extraer.
        existing = [p for p in cache_dir.glob("*.wav") if rec["rec_id"] in p.name]
        if existing:
            wav = existing[0]
            log(f"Reutilizando audio en cache: {wav.name}")
        else:
            log(f"Descargando video: {label}")
            video = download_video(rec, cache_dir)
            if not video:
                log(f"  ERROR descargando {label}, se omite")
                failed += 1
                continue
            log(f"  Extrayendo audio de {video.name}")
            wav = extract_audio(video)
            if not wav:
                log(f"  ERROR extrayendo audio de {label}, se omite")
                failed += 1
                continue

        dest = work_dir / "downloads" / rec["slug"] / f"{wav.stem}.transcript.vtt"
        parts_dir = cache_dir / f"parts-{rec['rec_id'].split('.')[0][:16]}"
        log(f"  Transcribiendo (esto puede tardar ~{rec['duration']} min)...")
        try:
            transcribe(model, wav, dest, parts_dir)
        except Exception as e:
            log(f"  ERROR transcribiendo {label}: {e} (el wav y los bloques "
                "quedan en cache para reanudar)")
            failed += 1
            continue
        wav.unlink(missing_ok=True)  # solo tras escribir el VTT completo

        log(f"  OK -> {dest.name}")
        ok += 1
        # Integrar al proceso normal tras cada grabación (progreso incremental)
        copy_transcripts(work_dir / "downloads", recordings)
        log("  index.json y transcripts/ regenerados")

    log(f"Terminado: {ok} transcritas, {failed} fallidas.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
