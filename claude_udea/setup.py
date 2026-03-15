"""
Setup interactivo: configura claude_udea pidiendo los links de Moodle.
Se ejecuta automáticamente la primera vez.
"""

import json
import re
import unicodedata
from pathlib import Path


def slugify(name: str) -> str:
    """Convierte un nombre a slug: 'Ingeniería Web' -> 'ingenieria-web'"""
    # Quitar acentos
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ASCII", "ignore").decode("ASCII")
    # Lowercase, reemplazar espacios y caracteres raros por guiones
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_str.lower()).strip("-")
    return slug


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
    print("  Vamos a configurar tus asignaturas.")
    print("  Necesitás el link de la lista de grabaciones de cada materia en Moodle.")
    print("  (Es la página donde ves los botones 'Ver grabación')\n")

    courses = {}

    while True:
        # Pedir URL
        url = questionary.text(
            "Link de grabaciones de Moodle:",
            instruction="(pega la URL completa)",
            style=style,
        ).ask()

        if url is None:
            if not courses:
                print("\n  Cancelado. Ejecutá claude_udea de nuevo cuando quieras configurar.\n")
                return False
            break

        url = url.strip()
        if not url:
            break

        # Validar que sea una URL de Moodle
        if "udearroba" not in url and "moodle" not in url:
            print("  ⚠ No parece ser una URL de Moodle. Intentá de nuevo.\n")
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

        courses[slug] = {
            "name": name,
            "moodle_url": url,
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

    url = questionary.text(
        "Link de grabaciones de Moodle:",
        style=style,
    ).ask()

    if not url or not url.strip():
        return False

    name = questionary.text(
        "Nombre de la asignatura:",
        style=style,
    ).ask()

    if not name or not name.strip():
        return False

    slug = slugify(name.strip())
    config["courses"][slug] = {
        "name": name.strip(),
        "moodle_url": url.strip(),
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"  ✔ {name.strip()} agregada\n")
    return True
