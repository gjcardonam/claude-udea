"""Validación e instalación de dependencias."""

import subprocess
import sys
import shutil


DEPS = {
    "yt_dlp": {"pip": "yt-dlp", "desc": "Descarga de videos/transcripciones de Zoom"},
    "playwright": {"pip": "playwright", "desc": "Navegador automatizado para Moodle", "post": "playwright-chromium"},
    "questionary": {"pip": "questionary", "desc": "Menús interactivos en terminal"},
    "tqdm": {"pip": "tqdm", "desc": "Barras de progreso"},
}


def _try_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _check_chromium() -> bool:
    """Verifica si Playwright tiene Chromium instalado."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


def _check_claude_cli() -> bool:
    return shutil.which("claude") is not None


def _check_npm() -> bool:
    return shutil.which("npm") is not None


def _check_node() -> bool:
    return shutil.which("node") is not None


def _pip_install(package: str):
    subprocess.run(
        [sys.executable, "-m", "pip", "install", package, "--quiet"],
        check=True,
    )


def _install_chromium():
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )


def _install_claude_code():
    """Instala Claude Code CLI vía npm."""
    subprocess.run(
        ["npm", "install", "-g", "@anthropic-ai/claude-code"],
        check=True,
    )


def check_and_install(auto=False):
    """
    Verifica dependencias. Si falta algo, pregunta si instalar.
    Retorna True si todo está listo.
    """
    missing = []

    for module, info in DEPS.items():
        if not _try_import(module):
            missing.append(info)

    chromium_ok = True
    if _try_import("playwright"):
        chromium_ok = _check_chromium()

    claude_ok = _check_claude_cli()

    if not missing and chromium_ok and claude_ok:
        return True

    # Mostrar qué falta
    print("\n  Dependencias faltantes:\n")

    for info in missing:
        print(f"    - {info['pip']}: {info['desc']}")

    if not chromium_ok:
        print("    - chromium: Navegador para acceder a Moodle")

    node_ok = _check_node()
    npm_ok = _check_npm()

    if not claude_ok:
        if npm_ok:
            print("    - claude: CLI de Claude Code (se instalará con npm)")
        elif not node_ok:
            print("    - Node.js: Requerido para instalar Claude Code")
            print("      → Instalá Node.js desde https://nodejs.org/ y volvé a ejecutar")
        else:
            print("    - npm: No encontrado (debería venir con Node.js)")

    print()

    # Si falta Node.js y Claude Code, no podemos continuar
    if not claude_ok and not node_ok:
        print("  ⚠ Claude Code es necesario y requiere Node.js para instalarse.")
        print("    1. Instalá Node.js desde https://nodejs.org/ (LTS recomendado)")
        print("    2. Cerrá y reabrí la terminal")
        print("    3. Ejecutá claude_udea de nuevo\n")
        return False

    # Preguntar
    if not auto:
        try:
            import questionary
            do_install = questionary.confirm(
                "¿Deseas instalar lo que falta automáticamente?",
                default=True,
            ).ask()
        except ImportError:
            resp = input("  ¿Instalar automáticamente? [S/n]: ").strip().lower()
            do_install = resp in ("", "s", "si", "sí", "y", "yes")
    else:
        do_install = True

    if not do_install:
        print("\n  Instalá las dependencias manualmente y volvé a ejecutar.\n")
        return False

    print()

    # Instalar paquetes pip
    for info in missing:
        pkg = info["pip"]
        print(f"  Instalando {pkg}...")
        try:
            _pip_install(pkg)
            print(f"  ✔ {pkg}")
        except Exception as e:
            print(f"  ✖ Error instalando {pkg}: {e}")
            return False

        # Post-install (chromium para playwright)
        if info.get("post") == "playwright-chromium":
            print("  Instalando Chromium...")
            try:
                _install_chromium()
                print("  ✔ Chromium")
                chromium_ok = True
            except Exception as e:
                print(f"  ✖ Error instalando Chromium: {e}")
                return False

    # Instalar Chromium si playwright ya estaba pero chromium no
    if not chromium_ok and "playwright" not in [i["pip"] for i in missing]:
        print("  Instalando Chromium...")
        try:
            _install_chromium()
            print("  ✔ Chromium")
        except Exception as e:
            print(f"  ✖ Error instalando Chromium: {e}")
            return False

    # Instalar Claude Code si falta
    if not claude_ok and npm_ok:
        print("  Instalando Claude Code CLI...")
        try:
            _install_claude_code()
            print("  ✔ Claude Code")
        except Exception as e:
            print(f"  ✖ Error instalando Claude Code: {e}")
            print("    Intentá manualmente: npm install -g @anthropic-ai/claude-code\n")
            return False

    print()
    return True
