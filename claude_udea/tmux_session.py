"""
Sesion persistente con tmux.

Corre el asistente (Claude Code / Gemini) dentro de una sesion de tmux para que
siga vivo aunque se cierre la terminal. El usuario se desconecta con Ctrl+b d y
vuelve con `claude_udea --attach`.
"""

import os
import shlex
import shutil
import subprocess
import sys


DEFAULT_SESSION = os.environ.get("CLAUDE_UDEA_SESSION", "claude_udea")


def session_name() -> str:
    return DEFAULT_SESSION


def tmux_available() -> bool:
    return shutil.which("tmux") is not None


def inside_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


def _tmux(*args, **kwargs):
    return subprocess.run(["tmux", *args], **kwargs)


def session_exists(name: str = None) -> bool:
    """True si ya hay una sesion del asistente corriendo."""
    if not tmux_available():
        return False
    name = name or session_name()
    # El prefijo '=' fuerza match exacto (si no, tmux hace match por prefijo)
    result = _tmux("has-session", "-t", f"={name}", capture_output=True)
    return result.returncode == 0


def kill_session(name: str = None) -> bool:
    """Mata la sesion. Retorna True si existia."""
    name = name or session_name()
    if not session_exists(name):
        return False
    _tmux("kill-session", "-t", f"={name}", capture_output=True)
    return True


def attach(name: str = None):
    """Se conecta a la sesion (o cambia de cliente si ya estamos en tmux)."""
    name = name or session_name()
    if inside_tmux():
        _tmux("switch-client", "-t", f"={name}")
    else:
        _tmux("attach-session", "-t", f"={name}")


def _wrap_command(cmd: list) -> str:
    """
    Envuelve el comando en un shell para que el panel no desaparezca si el
    asistente falla o termina: deja el error visible y espera un Enter.
    """
    inner = " ".join(shlex.quote(part) for part in cmd)
    return (
        f"{inner}; code=$?; echo; "
        f'echo "  [claude_udea] el asistente termino (codigo $code)."; '
        f'echo "  Presiona Enter para cerrar esta sesion."; read -r _'
    )


def start_session(cmd: list, cwd: str, name: str = None) -> bool:
    """
    Crea la sesion de tmux (desconectada) corriendo `cmd` en `cwd`.
    Retorna True si quedo creada.
    """
    name = name or session_name()

    # Resolver el binario a ruta absoluta: el servidor de tmux puede tener otro PATH
    resolved = list(cmd)
    binary = shutil.which(resolved[0])
    if binary:
        resolved[0] = binary

    script = _wrap_command(resolved)

    result = _tmux(
        "new-session", "-d",
        "-s", name,
        "-c", cwd,
        "-e", f"PATH={os.environ.get('PATH', '')}",
        "bash", "-lc", script,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or "").strip()
        print(f"  No se pudo crear la sesion de tmux: {err}")
        return False

    # set-option no acepta el prefijo '=' de match exacto
    _tmux(
        "set-option", "-t", name, "status-right",
        " claude_udea  |  Ctrl+b d = salir sin cerrar ",
        capture_output=True,
    )
    return True


def run_in_tmux(cmd: list, cwd: str, name: str = None) -> bool:
    """
    Deja el asistente corriendo en tmux y se conecta.
    Retorna False si tmux no esta disponible (el llamador hace fallback).
    """
    name = name or session_name()

    if not tmux_available():
        return False

    if session_exists(name):
        print(f"  Ya hay una sesion '{name}' corriendo. Me conecto a ella.\n")
    else:
        if not start_session(cmd, cwd, name):
            return False
        print(f"  Asistente corriendo en la sesion de tmux '{name}'.")
        print("  Ctrl+b luego d  ->  salir sin cerrarlo (podes cerrar la terminal)")
        print(f"  claude_udea --attach  ->  volver a conectarte")
        print(f"  claude_udea --stop    ->  cerrarlo\n")

    if not sys.stdout.isatty():
        print("  (sin terminal interactiva: la sesion queda corriendo en segundo plano)\n")
        return True

    attach(name)

    if session_exists(name):
        print(f"\n  El asistente sigue corriendo en tmux ('{name}').")
        print("  Volve con: claude_udea --attach\n")
    return True
