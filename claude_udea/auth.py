"""
Autenticación en Moodle UdeA sin navegador.
Login directo por HTTP con requests.
"""

import getpass
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SESSION_FILE = ".moodle-session.json"
LOGIN_URL = "https://udearroba.udea.edu.co/internos/login/index.php"
DASHBOARD_URL = "https://udearroba.udea.edu.co/internos/my/"


def _session_path(work_dir: Path) -> Path:
    return work_dir / SESSION_FILE


def save_session(session: requests.Session, work_dir: Path):
    """Guarda cookies de la sesión a disco."""
    data = []
    for cookie in session.cookies:
        data.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
        })
    with open(_session_path(work_dir), "w", encoding="utf-8") as f:
        json.dump(data, f)


def load_session(work_dir: Path) -> requests.Session | None:
    """Carga sesión guardada y verifica que siga activa."""
    path = _session_path(work_dir)
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
    except Exception:
        return None

    session = requests.Session()
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])

    # Verificar que la sesión siga activa
    try:
        r = session.get(DASHBOARD_URL, allow_redirects=False, timeout=15)
        # Si redirige al login, la sesión expiró
        if r.status_code in (301, 302, 303) and "login" in r.headers.get("Location", ""):
            return None
        if r.status_code == 200 and "login" not in r.url:
            return session
    except Exception:
        pass

    return None


def login(work_dir: Path, username: str = None, password: str = None) -> requests.Session:
    """
    Intenta restaurar sesión guardada. Si no sirve, pide credenciales
    y hace login por HTTP POST.
    """
    # Intentar sesión guardada
    session = load_session(work_dir)
    if session:
        print("  ✔ Sesión activa (login no necesario)\n")
        return session

    # Pedir credenciales si no se pasaron
    if not username:
        print()
        username = input("  Usuario Moodle UdeA: ").strip()
    if not password:
        password = getpass.getpass("  Contraseña: ")

    session = requests.Session()

    # Obtener logintoken del formulario
    r = session.get(LOGIN_URL, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    token_input = soup.find("input", {"name": "logintoken"})
    logintoken = token_input["value"] if token_input else ""

    # POST login
    r = session.post(LOGIN_URL, data={
        "anchor": "",
        "logintoken": logintoken,
        "username": username,
        "password": password,
    }, allow_redirects=True, timeout=15)

    # Verificar login exitoso
    if "login" in r.url.lower() and "errorcode" not in r.url:
        # Revisar si hay mensaje de error en la página
        soup = BeautifulSoup(r.text, "html.parser")
        error = soup.find("div", {"class": "alert-danger"}) or soup.find("div", {"id": "loginerrormessage"})
        if error:
            raise ValueError(f"Login fallido: {error.get_text(strip=True)}")
        if "login/index.php" in r.url:
            raise ValueError("Login fallido: credenciales incorrectas")

    # Verificar acceso al dashboard
    r = session.get(DASHBOARD_URL, timeout=15)
    if "login" in r.url.lower():
        raise ValueError("Login fallido: no se pudo acceder al dashboard")

    save_session(session, work_dir)
    print("  ✔ Login exitoso, sesión guardada\n")
    return session


def _scrape_one(session: requests.Session, slug: str, course_info: dict) -> tuple[str, list[dict]]:
    """Scrapea una materia. Diseñado para correr en un thread."""
    url = course_info["moodle_url"]
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"  ⚠ Error accediendo a {course_info['name']}: {e}")
        return slug, []

    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", class_="generaltable")
    if not table:
        return slug, []

    tbody = table.find("tbody")
    if not tbody:
        return slug, []

    links = []
    seen = set()

    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        hidden_input = row.find("input", {"name": "zoomplayredirect"})
        if not hidden_input:
            continue

        href = hidden_input.get("value", "")
        if not href:
            continue

        match = re.search(r"/rec/(?:share|play)/([^?\s]+)", href)
        rec_id = match.group(1) if match else href
        if rec_id in seen:
            continue
        seen.add(rec_id)

        meeting_id = cells[0].get_text(strip=True)
        topic = cells[1].get_text(strip=True)
        start_date = cells[2].get_text(strip=True)
        duration = cells[3].get_text(strip=True)

        links.append({
            "url": href.split("?")[0],
            "full_url": href,
            "text": topic or meeting_id,
            "id": rec_id,
            "meeting_id": meeting_id,
            "topic": topic,
            "start_date": start_date,
            "duration_minutes": int(duration) if duration.isdigit() else 0,
        })

    return slug, links


def scrape_recordings(session: requests.Session, courses: dict) -> dict:
    """
    Scrapea todas las materias en paralelo con ThreadPoolExecutor.
    Retorna {slug: [links]}.
    """
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(courses)) as pool:
        futures = {
            pool.submit(_scrape_one, session, slug, info): slug
            for slug, info in courses.items()
        }
        results = {}
        for future in futures:
            slug, links = future.result()
            results[slug] = links

    return results
