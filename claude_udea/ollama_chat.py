"""Chat académico local sobre las transcripciones usando la API de Ollama."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


_PENDING_RE = re.compile(
    r"parcial|quiz|quices|examen|evaluaci[oó]n|tarea|taller|entrega|"
    r"proyecto|fecha l[ií]mite|deadline|para el \d|calificaci[oó]n|nota",
    re.IGNORECASE,
)
_MAX_VTT_CHARS = 100_000


def parse_ollama_model_flag(args: list[str]) -> tuple[list[str], str | None]:
    """Extrae --ollama-model VALOR sin confundirlo con un curso."""
    filtered: list[str] = []
    model = None
    index = 0
    while index < len(args):
        value = args[index]
        if value.startswith("--ollama-model="):
            model = value.split("=", 1)[1].strip() or None
        elif value == "--ollama-model":
            index += 1
            if index < len(args):
                model = args[index].strip() or None
        else:
            filtered.append(value)
        index += 1
    return filtered, model


def _base_url() -> str:
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _json_get(url: str, timeout: int = 5) -> dict:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def list_models(base_url: str | None = None) -> list[str]:
    try:
        payload = _json_get(f"{base_url or _base_url()}/api/tags")
        return [model["name"] for model in payload.get("models", [])]
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError):
        return []


def _read_context_file(path: Path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _system_prompt(work_dir: Path, transcripts_dir: Path, summary: str) -> str:
    instructions = _read_context_file(work_dir / "CLAUDE.md", 24_000)
    if not instructions:
        instructions = _read_context_file(work_dir / "GEMINI.md", 24_000)
    rules = _read_context_file(work_dir / ".claude" / "rules.md", 12_000)
    index = _read_context_file(transcripts_dir / "index.json", 48_000)
    skills_dir = work_dir / ".claude" / "skills"
    skills = []
    budget = 8_000
    if skills_dir.is_dir():
        for path in sorted(skills_dir.glob("*.md")):
            content = _read_context_file(path, budget)
            if content:
                skills.append(f"### /{path.stem}\n{content}")
                budget -= len(content)
            if budget <= 0:
                break

    sections = [instructions or "Responde en español y usa solo la información disponible."]
    if rules:
        sections.append("Reglas adicionales:\n" + rules)
    if index:
        sections.append("Índice de transcripciones:\n" + index)
    if skills:
        sections.append("Comandos académicos:\n" + "\n\n".join(skills))
    if summary:
        sections.append("Descargas disponibles en esta ejecución:\n" + summary)
    sections.append(
        f"Las transcripciones están en {transcripts_dir.resolve()}. "
        "Cita archivo, asignatura, fecha y timestamp cuando respondas sobre una clase. "
        "El usuario puede cargar un VTT con /leer ruta.vtt."
    )
    return "\n\n".join(sections)


def _transcript_files(transcripts_dir: Path) -> list[Path]:
    return sorted(transcripts_dir.rglob("*.vtt")) if transcripts_dir.is_dir() else []


def _show_inventory(transcripts_dir: Path) -> None:
    if not transcripts_dir.is_dir():
        print("  Aún no existe la carpeta de transcripciones.\n")
        return
    courses = sorted(path for path in transcripts_dir.iterdir() if path.is_dir())
    if not courses:
        print("  No hay transcripciones organizadas todavía.\n")
        return
    for course in courses:
        files = sorted(course.glob("*.vtt"))
        print(f"  {course.name}/ ({len(files)} VTT)")
        for path in files[:6]:
            print(f"    {path.name}")
        if len(files) > 6:
            print(f"    y {len(files) - 6} más")
    print()


def _resolve_vtt(transcripts_dir: Path, relative_path: str) -> str | None:
    root = transcripts_dir.resolve()
    target = (root / relative_path.strip().replace("\\", "/")).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if target.suffix.lower() != ".vtt" or not target.is_file():
        return None
    return _read_context_file(target, _MAX_VTT_CHARS)


def _search_transcripts(transcripts_dir: Path, query: str, pending: bool = False) -> list[str]:
    results = []
    if len(query.strip()) < 2 and not pending:
        return results
    needle = query.casefold()
    for path in _transcript_files(transcripts_dir):
        matches = []
        try:
            with path.open(encoding="utf-8", errors="replace") as transcript:
                for line_number, line in enumerate(transcript, start=1):
                    if (_PENDING_RE.search(line) if pending else needle in line.casefold()):
                        text = line.strip()
                        if text:
                            matches.append(f"  L{line_number}: {text[:220]}")
                    if len(matches) == 4:
                        break
        except OSError:
            continue
        if matches:
            relative = path.relative_to(transcripts_dir).as_posix()
            results.append(f"{relative}\n" + "\n".join(matches))
        if len(results) == 30:
            break
    return results


def _chat(base_url: str, model: str, messages: list[dict]) -> str:
    body = json.dumps({"model": model, "messages": messages, "stream": True}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chunks = []
    with urllib.request.urlopen(request, timeout=900) as response:
        for raw_line in response:
            try:
                payload = json.loads(raw_line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            content = (payload.get("message") or {}).get("content", "")
            if content:
                print(content, end="", flush=True)
                chunks.append(content)
    print()
    return "".join(chunks)


def run_session(
    work_dir: Path,
    transcripts_dir: Path,
    model: str | None = None,
    session_summary: str | None = None,
) -> None:
    base_url = _base_url()
    models = list_models(base_url)
    if not models:
        print(f"  Ollama no responde en {base_url} o no tiene modelos instalados.")
        print("  Inicia Ollama y descarga un modelo, por ejemplo: ollama pull llama3.2\n")
        return

    preferred = model or os.environ.get("CLAUDE_UDEA_OLLAMA_MODEL", "llama3.2")
    selected = next((name for name in models if name == preferred), None)
    if selected is None:
        selected = next((name for name in models if name.startswith(preferred + ":")), None)
    if selected is None:
        selected = models[0]
        print(f"  Modelo '{preferred}' no encontrado; usaré '{selected}'.\n")

    messages = [{
        "role": "system",
        "content": _system_prompt(work_dir, transcripts_dir, session_summary or ""),
    }]
    pending_vtt = None
    _show_inventory(transcripts_dir)
    print(f"  Chat Ollama ({selected}). Comandos: /help /listado /leer /buscar /pendientes /ensenar /salir\n")

    while True:
        try:
            line = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Chat finalizado.\n")
            return
        if not line:
            continue
        lowered = line.lower()
        if lowered in {"/salir", "/exit", "/quit", "salir"}:
            print("  Chat finalizado.\n")
            return
        if lowered in {"/help", "/ayuda", "/?"}:
            print("  /listado  lista VTTs\n  /leer ruta.vtt  carga un VTT al siguiente mensaje\n"
                  "  /buscar texto  busca líneas coincidentes\n  /pendientes  busca posibles evaluaciones y tareas\n"
                  "  /ensenar tema  pide una explicación basada en las clases\n  /salir\n")
            continue
        if lowered in {"/listado", "/lista", "/ls"}:
            _show_inventory(transcripts_dir)
            continue
        if lowered.startswith("/leer "):
            relative_path = line[len("/leer "):].strip()
            pending_vtt = _resolve_vtt(transcripts_dir, relative_path)
            if pending_vtt is None:
                print("  No encontré ese VTT dentro de transcripts/.\n")
            else:
                print(f"  VTT cargado para el próximo mensaje: {relative_path}\n")
            continue
        if lowered.startswith("/buscar "):
            query = line.split(None, 1)[1]
            matches = _search_transcripts(transcripts_dir, query)
            print("\n".join(matches) if matches else "  No encontré coincidencias.")
            print()
            continue
        if lowered in {"/pendientes", "/pendiente"}:
            matches = _search_transcripts(transcripts_dir, "", pending=True)
            print("\n".join(matches) if matches else "  No encontré menciones probables de pendientes.")
            print()
            continue

        user_message = line
        if lowered.startswith("/ensenar"):
            topic = line[len("/ensenar"):].strip()
            if not topic:
                print("  Uso: /ensenar <tema o asignatura>\n")
                continue
            user_message = f"Enséñame, con referencias a las transcripciones, lo visto en clase sobre: {topic}."
        if pending_vtt:
            user_message = f"VTT adjunto:\n{pending_vtt}\n\nPregunta:\n{user_message}"
            pending_vtt = None
        messages.append({"role": "user", "content": user_message})
        print("IA: ", end="", flush=True)
        try:
            answer = _chat(base_url, selected, messages)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
            print(f"\n  Error de Ollama: {error}\n")
            messages.pop()
            continue
        messages.append({"role": "assistant", "content": answer or "(sin respuesta)"})
        if len(messages) > 21:
            messages = [messages[0], *messages[-20:]]