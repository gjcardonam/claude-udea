"""Autenticación y sincronización de cursos del campus Ingenia."""

from __future__ import annotations

import getpass
import json
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from claude_udea.auth import _get_secret, _set_secret
from claude_udea.materials import scrape_course_materials


SERVICE_ACCOUNT = "ingenia-campus-credentials"
SERVICE_SESSION = "ingenia-campus-session"
BASE_URL = "https://ingenia.udea.edu.co/campus"
LOGIN_URL = f"{BASE_URL}/login/index.php"
MY_URL = f"{BASE_URL}/my/"


def _session_from_secret() -> requests.Session | None:
    raw = _get_secret(SERVICE_SESSION)
    if raw is None:
        return None
    try:
        cookies = json.loads(raw)
    except (TypeError, ValueError):
        return None
    session = requests.Session()
    for cookie in cookies:
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain", "ingenia.udea.edu.co"),
            path=cookie.get("path", "/"),
        )
    return session


def _save_session(session: requests.Session):
    cookies = [
        {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
        }
        for cookie in session.cookies
    ]
    _set_secret(SERVICE_SESSION, json.dumps(cookies))


def _session_is_authenticated(session: requests.Session) -> bool:
    try:
        response = session.get(MY_URL, timeout=20)
    except requests.RequestException:
        return False
    return "/login/" not in urlparse(response.url).path.lower()


def _login_request(username: str, password: str) -> requests.Session:
    session = requests.Session()
    response = session.get(LOGIN_URL, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    form = soup.find("form")
    token = soup.find("input", {"name": "logintoken"})
    if not form or not token:
        raise RuntimeError("Ingenia no mostró el formulario de acceso esperado.")

    login_url = response.url
    result = session.post(
        login_url,
        data={
            "anchor": "",
            "logintoken": token.get("value", ""),
            "username": username,
            "password": password,
        },
        allow_redirects=True,
        timeout=30,
    )
    result.raise_for_status()
    final_path = urlparse(result.url).path.lower()
    if "/login/" in final_path:
        result_soup = BeautifulSoup(result.text, "html.parser")
        error = result_soup.select_one(".loginerrors, .alert-danger, #loginerrormessage")
        message = error.get_text(" ", strip=True) if error else "usuario o contraseña inválidos"
        raise ValueError(f"No fue posible iniciar sesión en Ingenia: {message}")
    if not _session_is_authenticated(session):
        raise ValueError("Ingenia no confirmó la sesión autenticada.")
    return session


def login() -> requests.Session:
    """Usa cookies protegidas o pide credenciales en la terminal y las recuerda."""
    session = _session_from_secret()
    if session and _session_is_authenticated(session):
        print("  ✔ Sesión de Ingenia activa\n")
        return session

    stored_credentials = _get_secret(SERVICE_ACCOUNT)
    if stored_credentials:
        try:
            credentials = json.loads(stored_credentials)
            session = _login_request(credentials["username"], credentials["password"])
            _save_session(session)
            print("  ✔ Re-login automático en Ingenia exitoso\n")
            return session
        except (ValueError, KeyError, json.JSONDecodeError):
            print("  ⚠ Las credenciales de Ingenia guardadas ya no son válidas.\n")

    print("  Inicio de sesión de Ingenia Campus (las credenciales no se mostrarán).")
    username = input("  Usuario Ingenia: ").strip()
    password = getpass.getpass("  Contraseña Ingenia: ")
    session = _login_request(username, password)
    _set_secret(
        SERVICE_ACCOUNT,
        json.dumps({"username": username, "password": password}),
    )
    _save_session(session)
    print("  ✔ Sesión de Ingenia guardada en el almacén seguro de Windows.\n")
    return session


def sync_course_materials(course_url: str, work_dir: Path) -> dict:
    parsed = urlparse(course_url)
    if parsed.hostname != "ingenia.udea.edu.co" or not parsed.path.startswith("/campus/course/view.php"):
        raise ValueError("Usa una URL de curso Ingenia /campus/course/view.php?id=...")
    session = login()
    from urllib.parse import parse_qs

    course_id = parse_qs(parsed.query).get("id", [""])[0]
    if not course_id.isdigit():
        raise ValueError("La URL del curso Ingenia debe incluir un id numérico.")
    slug = f"ingenia-{course_id}"
    course_info = {
        "name": f"Ingenia {slug.removeprefix('ingenia-')}",
        "course_url": course_url,
    }
    destination = work_dir / "course-materials" / slug
    return scrape_course_materials(session, course_info, destination)