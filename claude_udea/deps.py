"""Validacion e instalacion de dependencias."""

import json
import subprocess
import sys
import shutil
from pathlib import Path


DEPS = {
    "yt_dlp": {"pip": "yt-dlp", "desc": "Descarga de videos/transcripciones de Zoom"},
    "requests": {"pip": "requests", "desc": "HTTP client para login en Moodle"},
    "bs4": {"pip": "beautifulsoup4", "desc": "Parser HTML para scraping de grabaciones"},
    "questionary": {"pip": "questionary", "desc": "Menus interactivos en terminal"},
    "tqdm": {"pip": "tqdm", "desc": "Barras de progreso"},
}

ASSISTANTS = {
    "claude": {
        "bin": "claude",
        "npm": "@anthropic-ai/claude-code",
        "desc": "Claude Code (Anthropic) — requiere plan de pago ($20/mes)",
    },
    "gemini": {
        "bin": "gemini",
        "npm": "@google/gemini-cli",
        "desc": "Gemini CLI (Google) — gratis, 1000 req/dia con cuenta Google",
    },
}


def _try_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _check_npm() -> bool:
    return shutil.which("npm") is not None


def _check_node() -> bool:
    return shutil.which("node") is not None


def _pip_install(package: str):
    subprocess.run(
        [sys.executable, "-m", "pip", "install", package, "--quiet"],
        check=True,
    )


def _install_npm_package(package: str):
    subprocess.run(
        ["npm", "install", "-g", package],
        check=True,
    )


def _get_work_dir() -> Path:
    import platform
    if platform.system() == "Windows":
        return Path("C:/claude-udea")
    return Path.home() / "claude-udea"


def _load_assistant_choice() -> str | None:
    """Lee el asistente elegido del config.json."""
    config_path = _get_work_dir() / "config.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f).get("assistant")
    except Exception:
        return None


def _save_assistant_choice(assistant: str):
    """Guarda el asistente elegido en config.json."""
    config_path = _get_work_dir() / "config.json"
    if not config_path.exists():
        return
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        config["assistant"] = assistant
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _choose_assistant() -> str:
    """Pregunta al usuario que asistente quiere usar."""
    try:
        import questionary
        from questionary import Style
        style = Style([("highlighted", "bold"), ("pointer", "bold")])

        print("\n  Elige tu asistente de IA:\n")
        choice = questionary.select(
            "Asistente",
            choices=[
                questionary.Choice(
                    title=[
                        ("fg:ansigreen bold", "Gemini CLI"),
                        ("", "  — gratis, 1000 req/dia con cuenta Google"),
                    ],
                    value="gemini",
                ),
                questionary.Choice(
                    title=[
                        ("fg:ansicyan bold", "Claude Code"),
                        ("", "  — mejor calidad, requiere plan de pago ($20/mes)"),
                    ],
                    value="claude",
                ),
            ],
            style=style,
            instruction="",
        ).ask()

        if choice is None:
            return "gemini"
        return choice
    except ImportError:
        print("\n  Elige tu asistente de IA:\n")
        print("  1. Gemini CLI  — gratis, 1000 req/dia con cuenta Google")
        print("  2. Claude Code — mejor calidad, requiere plan de pago ($20/mes)\n")
        resp = input("  Opcion [1]: ").strip()
        return "claude" if resp == "2" else "gemini"


def check_and_install(auto=False):
    """
    Verifica dependencias. Si falta algo, pregunta si instalar.
    Retorna True si todo esta listo.
    """
    missing = []

    for module, info in DEPS.items():
        if not _try_import(module):
            missing.append(info)

    # Determinar asistente
    assistant = _load_assistant_choice()
    if not assistant:
        assistant = _choose_assistant()
        _save_assistant_choice(assistant)

    assistant_info = ASSISTANTS[assistant]
    assistant_ok = shutil.which(assistant_info["bin"]) is not None

    if not missing and assistant_ok:
        return True

    # Mostrar que falta
    print("\n  Dependencias faltantes:\n")

    for info in missing:
        print(f"    - {info['pip']}: {info['desc']}")

    node_ok = _check_node()
    npm_ok = _check_npm()

    if not assistant_ok:
        bin_name = assistant_info["bin"]
        if npm_ok:
            print(f"    - {bin_name}: {assistant_info['desc']}")
        elif not node_ok:
            print(f"    - {bin_name}: {assistant_info['desc']}")
            print("      -> Instala Node.js desde https://nodejs.org/ y volve a ejecutar")
        else:
            print(f"    - {bin_name}: npm no encontrado")

    print()

    # Si falta Node.js y el asistente, no podemos continuar
    if not assistant_ok and not node_ok:
        bin_name = assistant_info["bin"]
        print(f"  ! {bin_name} requiere Node.js para instalarse.")
        print("    1. Instala Node.js desde https://nodejs.org/ (LTS recomendado)")
        print("    2. Cerra y reabri la terminal")
        print("    3. Ejecuta claude_udea de nuevo\n")
        return False

    # Preguntar
    if not auto:
        try:
            import questionary
            do_install = questionary.confirm(
                "Deseas instalar lo que falta automaticamente?",
                default=True,
            ).ask()
        except ImportError:
            resp = input("  Instalar automaticamente? [S/n]: ").strip().lower()
            do_install = resp in ("", "s", "si", "y", "yes")
    else:
        do_install = True

    if not do_install:
        print("\n  Instala las dependencias manualmente y volve a ejecutar.\n")
        return False

    print()

    # Instalar paquetes pip
    for info in missing:
        pkg = info["pip"]
        print(f"  Instalando {pkg}...")
        try:
            _pip_install(pkg)
            print(f"  OK {pkg}")
        except Exception as e:
            print(f"  Error instalando {pkg}: {e}")
            return False

    # Instalar asistente si falta
    if not assistant_ok and npm_ok:
        npm_pkg = assistant_info["npm"]
        bin_name = assistant_info["bin"]
        print(f"  Instalando {bin_name}...")
        try:
            _install_npm_package(npm_pkg)
            print(f"  OK {bin_name}")
        except Exception as e:
            print(f"  Error instalando {bin_name}: {e}")
            print(f"    Intenta manualmente: npm install -g {npm_pkg}\n")
            return False

    print()
    return True
