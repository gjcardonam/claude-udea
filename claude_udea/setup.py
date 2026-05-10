"""
Setup interactivo: configura claude_udea pidiendo los links de grabaciones (Moodle o Ingenia).
Se ejecuta automáticamente la primera vez.
"""

import json
import re
import unicodedata
from pathlib import Path

from claude_udea.auth import recording_canonical_key


def _normalize_url_loose(url: str) -> str:
    return url.strip().rstrip("/").lower()


def urls_alike(a: str, b: str) -> bool:
    """Misma fuente de grabaciones (clave canónica o URL equivalente)."""
    if not a or not b:
        return False
    ka, kb = recording_canonical_key(a), recording_canonical_key(b)
    if ka and kb and ka == kb:
        return True
    return _normalize_url_loose(a) == _normalize_url_loose(b)


def _source_choices(style):
    import questionary
    from questionary import Choice

    return questionary.select(
        "¿De dónde son las grabaciones de esta asignatura?",
        choices=[
            Choice(
                title=[
                    ("fg:ansicyan bold", "Moodle (UdeArroba / Ude@)"),
                    ("", "  — login con usuario institucional"),
                ],
                value="moodle",
            ),
            Choice(
                title=[
                    ("fg:ansigreen bold", "Ingenia (Virtual Ingeniería)"),
                    ("", "  — acceso público a la reunión Zoom"),
                ],
                value="ingenia",
            ),
        ],
        style=style,
        instruction="(↑↓ elegir, Enter)",
    )


def normalize_for_source(raw: str, source: str) -> tuple[str | None, str | None]:
    """
    Devuelve (url_normalizada, mensaje_error).
    source: 'moodle' | 'ingenia'
    """
    s = raw.strip()
    if not s:
        return None, "Vacío."

    if source == "ingenia":
        if re.fullmatch(r"\d{8,14}", s):
            s = f"https://ingenia.udea.edu.co/zoom/meeting/{s}"
        s_low = s.lower()
        if "ingenia.udea.edu.co" not in s_low or "/zoom/meeting/" not in s_low:
            return (
                None,
                "Para Ingenia usá la URL https://ingenia.udea.edu.co/zoom/meeting/<ID> "
                "o solo el número de reunión (sin espacios).",
            )
        return s, None

    # Moodle: siempre URL completa de la actividad Zoom en UdeArroba
    if re.fullmatch(r"\d{8,14}", s):
        return (
            None,
            "Para Moodle (Ude@) hace falta la URL completa de la página de grabaciones "
            "en UdeArroba (mod/zoom/view.php o mod/recordingszoom/recordinglist.php), "
            "no solo números.",
        )

    if not s.startswith("http"):
        s = "https://" + s.lstrip("/")

    s_low = s.lower()
    if "zoom.us" in s_low and "udearroba" in s_low:
        return (
            None,
            "Ese es el enlace de **reproducir una clase** en Zoom (rec/play/...). "
            "Para Ude@ necesitás la URL de **Moodle** con la tabla de grabaciones: "
            "debe ser udearroba.udea.edu.co con mod/zoom/view.php?id=... "
            "o mod/recordingszoom/recordinglist.php?id=...",
        )
    if "udearroba" not in s_low:
        return (
            None,
            "La URL debe ser de UdeArroba (udearroba.udea.edu.co), no de Ingenia.",
        )
    has_view = "mod/zoom/view" in s_low
    has_rec_list = "mod/recordingszoom/" in s_low and "recordinglist.php" in s_low
    if not has_view and not has_rec_list:
        return (
            None,
            "Pegá la URL de la **lista de grabaciones** en UdeArroba: "
            "mod/zoom/view.php?id=... o mod/recordingszoom/recordinglist.php?id=...",
        )
    if not re.search(r"[?&]id=\d+", s):
        return None, "Falta el id de la actividad (?id=...) en la URL."

    return s, None


def _duplicate_info(courses: dict, url: str) -> tuple[str, str] | None:
    """Si url ya está en courses, devuelve (slug, name)."""
    for slug, info in courses.items():
        prev = (info.get("moodle_url") or "").strip()
        if prev and urls_alike(prev, url):
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
    print("  Por cada asignatura elegís si las grabaciones están en")
    print("  Moodle (UdeArroba) o en Ingenia (Virtual Ingeniería).")
    print("  Así se evita confundir un ID de una plataforma con la otra.")
    print(
        "  En Moodle: usá la URL de la **lista en UdeArroba** "
        "(view.php o recordingszoom/recordinglist.php), no el link de Zoom rec/play.\n"
    )

    courses = {}

    while True:
        source = _source_choices(style).ask()
        if source is None:
            if not courses:
                print("\n  Cancelado. Ejecutá claude_udea de nuevo cuando quieras configurar.\n")
                return False
            break

        if source == "moodle":
            print(
                "  » Con la tabla «Lista de grabaciones» abierta, copiá la URL de la barra "
                "(…/mod/zoom/view.php?id=… o …/mod/recordingszoom/recordinglist.php?id=…).\n"
                "  » No pegues el enlace al reproductor (udearroba.zoom.us/rec/play/...).\n"
            )
            hint = "URL de la lista de grabaciones en UdeArroba (barra del navegador):"
            instr = "(view.php o recordinglist.php)"
        else:
            hint = "URL de Ingenia o solo el ID numérico de la reunión:"
            instr = ""
        url_raw = questionary.text(hint, instruction=instr, style=style).ask()

        if url_raw is None:
            if not courses:
                print("\n  Cancelado.\n")
                return False
            break

        url, err = normalize_for_source(url_raw, source)
        if err or not url:
            print(f"  ⚠ {err}\n")
            continue

        dup = _duplicate_info(courses, url)
        if dup:
            print(
                f"  ⚠ Ese listado ya está cargado como «{dup[1]}» (slug: {dup[0]}). "
                "No se duplica.\n"
            )
            continue

        name = questionary.text(
            "Nombre de la asignatura:",
            instruction="(ej: Lab integrado de física)",
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
            "source": source,
        }

        print(f"  ✔ {name} agregada\n")

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

    print("\n  Asignaturas configuradas:\n")
    for slug, info in courses.items():
        print(f"  ✔ {info['name']}")
    print()

    ok = questionary.confirm(
        "¿Todo correcto?",
        default=True,
        style=style,
    ).ask()

    if not ok:
        print("  Cancelado. Ejecutá claude_udea de nuevo.\n")
        return False

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

    courses = config.get("courses", {})

    source = _source_choices(style).ask()
    if source is None:
        return False

    if source == "moodle":
        print(
            "  Con la lista abierta en UdeArroba, copiá la URL (view.php o recordinglist.php); "
            "no uses udearroba.zoom.us/rec/play/...\n"
        )
    hint = (
        "URL de la lista de grabaciones en UdeArroba:"
        if source == "moodle"
        else "URL de Ingenia o solo el ID numérico:"
    )
    url_raw = questionary.text(
        hint,
        instruction="(Moodle: view.php o recordinglist.php)" if source == "moodle" else "",
        style=style,
    ).ask()

    if not url_raw or not url_raw.strip():
        return False

    url, err = normalize_for_source(url_raw, source)
    if err or not url:
        print(f"  ⚠ {err}\n")
        return False

    dup = _duplicate_info(courses, url)
    if dup:
        print(
            f"  ⚠ Ese listado ya está en «{dup[1]}» ({dup[0]}). "
            "No se agrega de nuevo.\n"
        )
        return False

    name = questionary.text(
        "Nombre de la asignatura:",
        style=style,
    ).ask()

    if not name or not name.strip():
        return False

    slug = slugify(name.strip())

    if slug in courses:
        print(f"  ⚠ Ya existe una asignatura con el mismo nombre corto («{slug}»).\n")
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


def slugify(name: str) -> str:
    """Convierte un nombre a slug: 'Ingeniería Web' -> 'ingenieria-web'"""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ASCII", "ignore").decode("ASCII")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_str.lower()).strip("-")
    return slug
