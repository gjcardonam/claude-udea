"""
Autenticación en Moodle UdeA sin navegador.
Login directo por HTTP con requests.
Guarda credenciales para re-login automático cuando la sesión expire.
"""

import getpass
import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

SESSION_FILE = ".moodle-session.json"
CREDENTIALS_FILE = ".moodle-credentials.json"
KEYRING_SERVICE = "claude-udea"
SESSION_ACCOUNT = "moodle-session"
CREDENTIALS_ACCOUNT = "moodle-credentials"
LOGIN_URL = "https://udearroba.udea.edu.co/internos/login/index.php"
DASHBOARD_URL = "https://udearroba.udea.edu.co/internos/my/"

# Filtro por rango de fechas de recordinglist.php: la página limita a 30 días.
# El scraping recorre todo el semestre en ventanas de este tamaño.
_MOODLE_DATE_WINDOW_START = "2026-08-01"
_MOODLE_DATE_WINDOW_DAYS = 30


def _session_path(work_dir: Path) -> Path:
    return work_dir / SESSION_FILE


def _credentials_path(work_dir: Path) -> Path:
    return work_dir / CREDENTIALS_FILE


def _keyring_backend():
    try:
        import keyring
        backend = keyring.get_keyring()
    except Exception as error:
        raise RuntimeError(
            "No se pudo acceder al almacén seguro del sistema. "
            "Las credenciales no se guardarán en archivos sin cifrar."
        ) from error
    if getattr(backend, "priority", 0) <= 0:
        raise RuntimeError(
            "No hay un almacén de credenciales seguro disponible. "
            "Las credenciales no se guardarán en archivos sin cifrar."
        )
    return keyring


def _get_secret(account: str) -> str | None:
    return _keyring_backend().get_password(KEYRING_SERVICE, account)


def _set_secret(account: str, value: str):
    keyring = _keyring_backend()
    keyring.set_password(KEYRING_SERVICE, account, value)
    if keyring.get_password(KEYRING_SERVICE, account) != value:
        raise RuntimeError("El almacén seguro no confirmó la escritura del secreto.")


def save_session(session: requests.Session, work_dir: Path):
    """Guarda cookies en el almacén seguro del sistema operativo."""
    data = []
    for cookie in session.cookies:
        data.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
        })
    _set_secret(SESSION_ACCOUNT, json.dumps(data))
    _session_path(work_dir).unlink(missing_ok=True)


def _save_credentials(work_dir: Path, username: str, password: str):
    """Guarda credenciales cifradas por el almacén del sistema operativo."""
    _set_secret(
        CREDENTIALS_ACCOUNT,
        json.dumps({"username": username, "password": password}),
    )
    _credentials_path(work_dir).unlink(missing_ok=True)


def _load_credentials(work_dir: Path) -> tuple[str, str] | None:
    """Carga credenciales guardadas."""
    try:
        stored = _get_secret(CREDENTIALS_ACCOUNT)
        path = _credentials_path(work_dir)
        if stored is not None:
            data = json.loads(stored)
        elif path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            return None
        return data.get("username", ""), data.get("password", "")
    except (OSError, ValueError, TypeError):
        return None


def migrate_saved_secrets(work_dir: Path) -> list[str]:
    """Migra archivos JSON legados al almacén seguro y los elimina tras verificarlos."""
    migrated = []
    legacy_secrets = (
        (_session_path(work_dir), SESSION_ACCOUNT),
        (_credentials_path(work_dir), CREDENTIALS_ACCOUNT),
    )
    for path, account in legacy_secrets:
        if not path.exists():
            continue
        legacy_value = path.read_text(encoding="utf-8")
        stored = _get_secret(account)
        if stored is None:
            _set_secret(account, legacy_value)
            stored = _get_secret(account)
        if stored != legacy_value:
            raise RuntimeError(
                f"No se pudo verificar la migración segura de {path.name}; "
                "el archivo original se conservó."
            )
        path.unlink()
        migrated.append(path.name)
    return migrated


def load_session(work_dir: Path) -> requests.Session | None:
    """Carga sesión guardada y verifica que siga activa."""
    path = _session_path(work_dir)
    stored = _get_secret(SESSION_ACCOUNT)
    if stored is None and not path.exists():
        return None

    try:
        if stored is not None:
            cookies = json.loads(stored)
        elif path.exists():
            with open(path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
        else:
            return None
    except (OSError, ValueError, TypeError):
        return None

    session = requests.Session()
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])

    # Verificar que la sesión siga activa (seguir redirects para manejar SSO)
    try:
        r = session.get(DASHBOARD_URL, allow_redirects=True, timeout=15)
        if "login" in r.url.lower():
            return None
        if r.status_code == 200:
            return session
    except Exception:
        pass

    return None


def _do_login_request(username: str, password: str) -> requests.Session:
    """Hace login HTTP POST y retorna la sesión autenticada."""
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

    return session


def login(work_dir: Path, username: str = None, password: str = None) -> requests.Session:
    """
    Intenta restaurar sesión guardada. Si expiró, re-login automático
    con credenciales guardadas. Solo pide credenciales la primera vez.
    """
    # 1. Intentar sesión guardada
    session = load_session(work_dir)
    if session:
        print("  ✔ Sesión activa\n")
        return session

    # 2. Intentar re-login con credenciales guardadas
    if not username and not password:
        saved = _load_credentials(work_dir)
        if saved:
            saved_user, saved_pass = saved
            if saved_user and saved_pass:
                try:
                    session = _do_login_request(saved_user, saved_pass)
                    save_session(session, work_dir)
                    print("  ✔ Re-login automático exitoso\n")
                    return session
                except ValueError:
                    # Credenciales guardadas ya no sirven, pedir nuevas
                    print("  ⚠ Credenciales guardadas inválidas, pidiendo nuevas...\n")

    # 3. Pedir credenciales manualmente
    if not username:
        print()
        username = input("  Usuario Moodle UdeA: ").strip()
    if not password:
        password = getpass.getpass("  Contraseña: ")

    session = _do_login_request(username, password)
    save_session(session, work_dir)
    _save_credentials(work_dir, username, password)
    print("  ✔ Login exitoso, credenciales guardadas\n")
    return session


def _ingenia_recordings_from_html(html: str) -> list[dict]:
    """Lee el arreglo completo de grabaciones serializado por Next.js."""
    soup = BeautifulSoup(html, "html.parser")
    decoder = json.JSONDecoder()

    for script in soup.find_all("script"):
        script_text = script.string or script.get_text()
        match = re.search(r"self\.__next_f\.push\((.*)\);?\s*$", script_text, re.DOTALL)
        if not match:
            continue

        try:
            push_data = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(push_data, list) or len(push_data) < 2:
            continue

        payload = push_data[1]
        if not isinstance(payload, str):
            continue
        marker = re.search(r'"recordings"\s*:\s*\[', payload)
        if not marker:
            continue

        array_start = payload.find("[", marker.start())
        try:
            recordings, _ = decoder.raw_decode(payload, array_start)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(recordings, list) and recordings:
            return recordings

    return []


def _scrape_ingenia(session: requests.Session, slug: str,
                    course_info: dict) -> tuple[str, list[dict]]:
    """Extrae todas las grabaciones de una página de Virtual Ingeniería."""
    last_error = None
    recordings = []
    for attempt in range(3):
        try:
            response = session.get(
                course_info["moodle_url"],
                headers={"Cache-Control": "no-cache"},
                timeout=30,
            )
            response.raise_for_status()
            if "login" in urlparse(response.url).path.lower():
                raise PermissionError("Ingenia redirigió a una página de acceso.")
            recordings = _ingenia_recordings_from_html(response.text)
            if recordings:
                break
            last_error = "la respuesta no contenía el bloque de grabaciones de Next.js"
        except Exception as error:
            last_error = str(error)
        if attempt < 2:
            time.sleep(0.5 * (attempt + 1))

    if not recordings:
        print(
            f"  ⚠ No se encontró metadata de grabaciones en {course_info['name']} "
            f"(Ingenia) después de 3 intentos: {last_error}"
        )
        return slug, []

    links = []
    seen = set()
    for recording in recordings:
        video_url = recording.get("videoUrl", "")
        if not video_url:
            continue

        match = re.search(r"/rec/(?:share|play)/([^?\s]+)", video_url)
        rec_id = match.group(1) if match else video_url
        if rec_id in seen:
            continue
        seen.add(rec_id)

        start_date = recording.get("startTime", "")
        if isinstance(start_date, str) and start_date.startswith("$D"):
            start_date = start_date[2:]

        title = recording.get("topic") or course_info["name"]
        links.append({
            "url": video_url.split("?")[0],
            "full_url": video_url,
            "text": title,
            "id": rec_id,
            "meeting_id": recording.get("id", ""),
            "topic": title,
            "start_date": start_date,
            "duration_minutes": int(recording.get("duration") or 0),
        })

    return slug, links


def _append_params(url: str, params: dict) -> str:
    """Agrega parámetros de query a una URL conservando los existentes."""
    if not params:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _detect_date_range_fields(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Detecta los campos de rango de fechas del formulario de recordinglist.php."""
    form = soup.find("form")
    if not form:
        return None, None
    from_field = None
    to_field = None
    for element in form.find_all(["input", "select"]):
        name = element.get("name", "")
        lowered = name.lower()
        if from_field is None and any(
            token in lowered for token in ("from", "start", "fecha_inicio", "fecha_desde", "desde")
        ):
            from_field = name
        elif to_field is None and any(
            token in lowered for token in ("to", "end", "fecha_fin", "fecha_hasta", "hasta")
        ):
            to_field = name
    return from_field, to_field


def _date_windows() -> list[tuple[str, str]]:
    """Ventanas de hasta _MOODLE_DATE_WINDOW_DAYS desde el inicio del semestre hasta hoy."""
    start = date.fromisoformat(_MOODLE_DATE_WINDOW_START)
    end = date.today()
    windows = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=_MOODLE_DATE_WINDOW_DAYS - 1), end)
        windows.append((cursor.isoformat(), window_end.isoformat()))
        cursor = window_end + timedelta(days=1)
    return windows


def _collect_recording_links(soup: BeautifulSoup, links: list[dict], seen: set, course_info: dict) -> None:
    """Extrae las grabaciones de una página y las agrega a links (deduplicando por ID)."""
    for table in soup.find_all("table", class_="generaltable"):
        tbody = table.find("tbody")
        if not tbody:
            continue
        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            meeting_id = cells[0].get_text(strip=True)
            topic = cells[1].get_text(strip=True)
            start_date = cells[2].get_text(strip=True)
            duration = cells[3].get_text(strip=True)
            hidden_input = row.find("input", {"name": "zoomplayredirect"})
            if not hidden_input:
                print(f"  ⚠ {course_info['name']}: grabación del {start_date} sin URL (procesándose en Zoom)")
                continue
            href = hidden_input.get("value", "")
            if not href:
                print(f"  ⚠ {course_info['name']}: grabación del {start_date} con URL vacía")
                continue
            match = re.search(r"/rec/(?:share|play)/([^?\s]+)", href)
            rec_id = match.group(1) if match else href
            if rec_id in seen:
                continue
            seen.add(rec_id)
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


def _moodle_recording_pages(session: requests.Session, initial_url: str) -> list[BeautifulSoup]:
    """Recolecta las páginas de grabaciones de Moodle.

    Detecta el filtro por rango de fechas de recordinglist.php y, si existe,
    recorre todo el semestre en ventanas de 30 días; dentro de cada ventana
    sigue la paginación de la misma actividad.
    """
    base = urlparse(initial_url)
    activity_id = re.search(r"[?&]id=(\d+)", initial_url)

    def fetch(url: str) -> BeautifulSoup:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        if "login" in response.url.lower():
            raise PermissionError("Sesión expirada al recorrer las páginas de grabaciones Moodle.")
        return BeautifulSoup(response.text, "html.parser")

    first_soup = fetch(initial_url)
    from_field, to_field = _detect_date_range_fields(first_soup)

    queries: list[dict | None] = [None]
    if from_field and to_field:
        queries = [
            {from_field: window_start, to_field: window_end}
            for window_start, window_end in _date_windows()
        ]

    pages: list[BeautifulSoup] = []
    for params in queries:
        start_url = _append_params(initial_url, params or {})
        pending = [start_url]
        visited = set()
        while pending:
            url = pending.pop(0)
            if url in visited:
                continue
            visited.add(url)
            if url == initial_url and params is None:
                soup = first_soup
            else:
                soup = fetch(url)
            pages.append(soup)
            for anchor in soup.select("a[href]"):
                href = urljoin(url, anchor.get("href", ""))
                if params:
                    href = _append_params(href, params)
                parsed = urlparse(href)
                href_id = re.search(r"[?&]id=(\d+)", href)
                if (
                    parsed.scheme not in ("http", "https")
                    or parsed.hostname != base.hostname
                    or parsed.path != base.path
                    or (activity_id and (not href_id or href_id.group(1) != activity_id.group(1)))
                    or href in visited
                ):
                    continue
                label = " ".join((anchor.get_text(" ", strip=True), anchor.get("aria-label", ""), anchor.get("title", ""))).casefold()
                classes = " ".join(anchor.get("class", [])).casefold()
                parent_classes = " ".join(anchor.parent.get("class", [])).casefold() if anchor.parent else ""
                is_pager = (
                    "pagination" in parent_classes
                    or "pagination" in classes
                    or label in {"siguiente", "next", "»", "›", "→"}
                    or "siguiente" in label
                    or "next" == label
                )
                if is_pager:
                    pending.append(href)

    return pages


def _scrape_one(session: requests.Session, slug: str, course_info: dict) -> tuple[str, list[dict]]:
    """Scrapea una materia. Diseñado para correr en un thread."""
    url = course_info["moodle_url"]
    if urlparse(url).hostname == "ingenia.udea.edu.co":
        return _scrape_ingenia(session, slug, course_info)

    links = []
    seen = set()
    try:
        page_soups = _moodle_recording_pages(session, url)
        for soup in page_soups:
            _collect_recording_links(soup, links, seen, course_info)
    except Exception as error:
        print(f"  ⚠ {course_info['name']}: scrape incompleto; no se procesarán páginas parciales: {error}")
        return slug, []

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
