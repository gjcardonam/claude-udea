"""Validacion e instalacion de dependencias."""

import json
import platform
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
    "ollama": {
        "bin": "ollama",
        "npm": None,
        "desc": "Ollama — modelos locales en tu maquina (gratis)",
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


def _ollama_on_path() -> bool:
    return shutil.which("ollama") is not None


def _install_ollama() -> bool:
    """Intenta instalar el CLI de Ollama según el sistema operativo."""
    system = platform.system()
    print("  Instalando Ollama (puede pedir contraseña de administrador)...")
    try:
        if system == "Linux":
            subprocess.run(
                "curl -fsSL https://ollama.com/install.sh | sh",
                shell=True,
                check=True,
            )
        elif system == "Darwin":
            if shutil.which("brew"):
                subprocess.run(["brew", "install", "ollama"], check=True)
            else:
                subprocess.run(
                    "curl -fsSL https://ollama.com/install.sh | sh",
                    shell=True,
                    check=True,
                )
        elif system == "Windows":
            if shutil.which("winget"):
                subprocess.run(
                    [
                        "winget",
                        "install",
                        "-e",
                        "--id",
                        "Ollama.Ollama",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ],
                    check=True,
                )
            else:
                print(
                    "  ! No se encontro winget. Instala Ollama desde https://ollama.com/download"
                )
                return False
        else:
            print("  ! Instala Ollama manualmente desde https://ollama.com/download")
            return False
    except subprocess.CalledProcessError as e:
        print(f"  Error en la instalacion de Ollama: {e}")
        print("  Proba manualmente: https://ollama.com/download")
        return False
    except OSError as e:
        print(f"  Error ejecutando el instalador de Ollama: {e}")
        return False

    if _ollama_on_path():
        print("  OK ollama")
        return True
    print(
        "  Ollama pudo instalarse pero no esta en el PATH. "
        "Cerrá y abrí la terminal, o agrega Ollama al PATH."
    )
    return False


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
                questionary.Choice(
                    title=[
                        ("fg:ansiyellow bold", "Ollama"),
                        ("", "  — modelos locales, gratis (CLI ollama)"),
                    ],
                    value="ollama",
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
        print("  2. Claude Code — mejor calidad, requiere plan de pago ($20/mes)")
        print("  3. Ollama — modelos locales, gratis\n")
        resp = input("  Opcion [1]: ").strip()
        if resp == "2":
            return "claude"
        if resp == "3":
            return "ollama"
        return "gemini"


def check_and_install(auto=False, require_assistant=True, ollama_cli: bool = False):
    """
    Verifica dependencias. Si falta algo, pregunta si instalar.
    Retorna True si todo esta listo.

    Si require_assistant es False, normalmente solo valida dependencias Python.
    Si además ollama_cli es True (p. ej. flag --ollama), también exige el
    ejecutable ollama e intenta instalarlo.
    """
    missing = []

    for module, info in DEPS.items():
        if not _try_import(module):
            missing.append(info)

    needs_ollama_bin = ollama_cli and not _ollama_on_path()

    if not require_assistant:
        if not missing and not needs_ollama_bin:
            return True
        assistant = None
        assistant_info = None
        assistant_ok = True
    else:
        # Determinar asistente
        assistant = _load_assistant_choice()
        if not assistant or assistant not in ASSISTANTS:
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

    if needs_ollama_bin and not require_assistant:
        print("    - ollama: CLI de Ollama (chat local, modelos LLM)")
        print("      -> Se intentara instalar; si falla: https://ollama.com/download")

    if require_assistant and not assistant_ok:
        bin_name = assistant_info["bin"]
        if assistant == "ollama":
            print(f"    - {bin_name}: {assistant_info['desc']}")
            print("      -> Se intentara instalar; si falla: https://ollama.com/download")
        elif npm_ok:
            print(f"    - {bin_name}: {assistant_info['desc']}")
        elif not node_ok:
            print(f"    - {bin_name}: {assistant_info['desc']}")
            print("      -> Instala Node.js desde https://nodejs.org/ y volve a ejecutar")
        else:
            print(f"    - {bin_name}: npm no encontrado")

    print()

    # Claude/Gemini se instalan con npm; hace falta Node.
    if (
        require_assistant
        and not assistant_ok
        and assistant in ("claude", "gemini")
        and not node_ok
    ):
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

    # Ollama (elegido como asistente o por flag --ollama)
    if needs_ollama_bin and not require_assistant:
        if not _install_ollama():
            return False

    if require_assistant and not assistant_ok:
        if assistant == "ollama":
            if not _install_ollama():
                return False
        elif npm_ok and assistant_info.get("npm"):
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
