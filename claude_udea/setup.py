"""
Setup interactivo: configura claude_udea pidiendo los links de Moodle.
Se ejecuta automáticamente la primera vez.
"""

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def slugify(name: str) -> str:
    """Convierte un nombre a slug: 'Ingeniería Web' -> 'ingenieria-web'"""
    # Quitar acentos
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ASCII", "ignore").decode("ASCII")
    # Lowercase, reemplazar espacios y caracteres raros por guiones
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_str.lower()).strip("-")
    return slug


def _canonical_url(url: str) -> tuple[str, str, str] | None:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.hostname:
        return None
    query_id = parse_qs(parsed.query).get("id", [""])[0]
    return parsed.hostname.lower(), parsed.path.rstrip("/").lower(), query_id


def urls_alike(first: str, second: str) -> bool:
    """Compara URLs de actividades ignorando esquema, slash final y tracking."""
    first_key = _canonical_url(first)
    second_key = _canonical_url(second)
    if first_key is not None and second_key is not None:
        return first_key == second_key
    return first.strip().rstrip("/").lower() == second.strip().rstrip("/").lower()


def normalize_for_source(raw: str, source: str) -> tuple[str | None, str | None]:
    """Valida y normaliza la URL de grabaciones para la plataforma elegida."""
    value = raw.strip()
    if not value:
        return None, "La URL no puede estar vacía."

    if source == "ingenia":
        if re.fullmatch(r"\d{8,14}", value):
            value = f"https://ingenia.udea.edu.co/zoom/meeting/{value}"
        elif not value.lower().startswith(("http://", "https://")):
            value = f"https://{value.lstrip('/')}"
        parsed = urlparse(value)
        if (parsed.hostname != "ingenia.udea.edu.co"
                or not re.fullmatch(r"/zoom/meeting/\d+/?", parsed.path, re.IGNORECASE)):
            return None, (
                "Para Ingenia usa la URL https://ingenia.udea.edu.co/zoom/meeting/<ID> "
                "o pega solo el número de reunión."
            )
        return value.rstrip("/"), None

    if source != "moodle":
        return None, "Plataforma no reconocida."

    if not value.lower().startswith(("http://", "https://")):
        value = f"https://{value.lstrip('/')}"
    parsed = urlparse(value)
    query_id = parse_qs(parsed.query).get("id", [""])[0]
    if parsed.hostname != "udearroba.udea.edu.co":
        return None, "La URL de Moodle debe pertenecer a udearroba.udea.edu.co."
    if not parsed.path.lower().endswith("/mod/zoom/view.php") or not query_id.isdigit():
        return None, (
            "Pega la URL de la actividad Zoom en Moodle (mod/zoom/view.php?id=...), "
            "no el enlace directo al reproductor."
        )
    return value, None


def _source_choices(style):
    import questionary

    return questionary.select(
        "¿Dónde están las grabaciones de esta asignatura?",
        choices=[
            questionary.Choice("Moodle (UdeArroba)", value="moodle"),
            questionary.Choice("Ingenia (Virtual Ingeniería)", value="ingenia"),
        ],
        style=style,
        instruction="(↑↓ elegir, Enter)",
    )


def _duplicate_course(courses: dict, url: str) -> tuple[str, str] | None:
    for slug, info in courses.items():
        previous_url = info.get("moodle_url", "")
        if previous_url and urls_alike(previous_url, url):
            return slug, info.get("name", slug)
    return None


def run_setup(work_dir: Path):
    """Setup interactivo. Retorna True si se completó."""
    try:
        import questionary
        from questionary import Style
    except ImportError:
        print("  Instalá questionary primero: pip install questionary")
        return False

    style = Style([("highlighted", "bold"), ("pointer", "bold")])

    print("\n  ╔══════════════════════════════════════╗")
    print("  ║   Configuración inicial               ║")
    print("  ╚══════════════════════════════════════╝\n")
    print("  Vamos a configurar tus asignaturas de Moodle o Ingenia.\n")

    courses = {}

    while True:
        source = _source_choices(style).ask()
        if source is None:
            if not courses:
                print("\n  Cancelado. Ejecutá claude_udea de nuevo cuando quieras configurar.\n")
                return False
            break

        prompt = (
            "URL de grabaciones en Moodle:"
            if source == "moodle"
            else "URL de reunión de Ingenia o ID numérico:"
        )
        raw_url = questionary.text(prompt, style=style).ask()
        if raw_url is None:
            if not courses:
                return False
            break

        url, error = normalize_for_source(raw_url, source)
        if error or not url:
            print(f"  ⚠ {error}\n")
            continue

        duplicate = _duplicate_course(courses, url)
        if duplicate:
            print(f"  ⚠ Ese listado ya está registrado como «{duplicate[1]}».\n")
            continue

        # Pedir nombre de la asignatura
        name = questionary.text(
            "Nombre de la asignatura:",
            instruction="(ej: Calidad de Software)",
            style=style,
        ).ask()

        if name is None or not name.strip():
            print("  ⚠ Nombre requerido. Intentá de nuevo.\n")
            continue

        name = name.strip()
        slug = slugify(name)
        if not slug:
            print("  ⚠ El nombre debe contener letras o números.\n")
            continue
        if slug in courses:
            print(f"  ⚠ Ya existe una asignatura con el nombre corto «{slug}».\n")
            continue

        courses[slug] = {
            "name": name,
            "moodle_url": url,
            "source": source,
        }

        print(f"  ✔ {name} agregada\n")

        # Preguntar si quiere agregar otra
        another = questionary.confirm(
            "¿Agregar otra asignatura?",
            default=True,
            style=style,
        ).ask()

        if not another:
            break

    if not courses:
        print("\n  No se agregaron asignaturas.\n")
        return False

    # Mostrar resumen
    print(f"\n  Asignaturas configuradas:\n")
    for slug, info in courses.items():
        print(f"  ✔ {info['name']}")
    print()

    # Confirmar
    ok = questionary.confirm(
        "¿Todo correcto?",
        default=True,
        style=style,
    ).ask()

    if not ok:
        print("  Cancelado. Ejecutá claude_udea de nuevo.\n")
        return False

    # Guardar config.json
    config = {
        "download_dir": "./downloads",
        "recordings_file": "./recordings.json",
        "courses": courses,
    }

    config_path = work_dir / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n  ✔ Configuración guardada en {config_path}\n")
    return True


def add_course(work_dir: Path):
    """Agrega una asignatura a una configuración existente."""
    try:
        import questionary
        from questionary import Style
    except ImportError:
        return False

    style = Style([("highlighted", "bold"), ("pointer", "bold")])

    config_path = work_dir / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    courses = config.setdefault("courses", {})

    source = _source_choices(style).ask()
    if source is None:
        return False

    prompt = (
        "URL de grabaciones en Moodle:"
        if source == "moodle"
        else "URL de reunión de Ingenia o ID numérico:"
    )
    raw_url = questionary.text(prompt, style=style).ask()
    if not raw_url:
        return False

    url, error = normalize_for_source(raw_url, source)
    if error or not url:
        print(f"  ⚠ {error}\n")
        return False

    duplicate = _duplicate_course(courses, url)
    if duplicate:
        print(f"  ⚠ Ese listado ya está registrado como «{duplicate[1]}».\n")
        return False

    name = questionary.text(
        "Nombre de la asignatura:",
        style=style,
    ).ask()

    if not name or not name.strip():
        return False

    slug = slugify(name.strip())
    if not slug or slug in courses:
        print(f"  ⚠ Ya existe una asignatura con el nombre corto «{slug}».\n")
        return False
    courses[slug] = {
        "name": name.strip(),
        "moodle_url": url,
        "source": source,
    }
    config["courses"] = courses

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"  ✔ {name.strip()} agregada\n")
    return True
