"""
Autenticación en Moodle UdeA sin navegador.
Login directo por HTTP con requests.
"""

import getpass
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SESSION_FILE = ".moodle-session.json"
LOGIN_URL = "https://udearroba.udea.edu.co/internos/login/index.php"
DASHBOARD_URL = "https://udearroba.udea.edu.co/internos/my/"
INGENIA_MEETING_RE = re.compile(
    r"https?://ingenia\.udea\.edu\.co/zoom/meeting/(\d+)/?",
    re.IGNORECASE,
)
SPANISH_MONTHS = {
    "enero": "01",
    "febrero": "02",
    "marzo": "03",
    "abril": "04",
    "mayo": "05",
    "junio": "06",
    "julio": "07",
    "agosto": "08",
    "septiembre": "09",
    "setiembre": "09",
    "octubre": "10",
    "noviembre": "11",
    "diciembre": "12",
}


def is_ingenia_url(url: str) -> bool:
    """Retorna True para paginas de reunion de Ingenia / Virtual Ingenieria."""
    return bool(url and INGENIA_MEETING_RE.search(url.strip()))


def recording_canonical_key(url: str) -> str | None:
    """
    Identificador estable del mismo listado de grabaciones (evitar duplicados en config).

    - Ingenia: ``ingenia:<id_reunion>``
    - Moodle lista Ude@ (recordingszoom): ``moodle_recordingszoom:<id>``
    - Moodle actividad Zoom: ``moodle_zoom:<id>`` (mod/zoom/view.php?id=)
    """
    if not url or not str(url).strip():
        return None
    url = str(url).strip()
    m = INGENIA_MEETING_RE.search(url)
    if m:
        return f"ingenia:{m.group(1)}"
    low = url.lower()
    if "udearroba" not in low:
        return None
    if "mod/recordingszoom/" in low and "recordinglist.php" in low:
        m_id = re.search(r"[?&]id=(\d+)", url)
        if m_id:
            return f"moodle_recordingszoom:{m_id.group(1)}"
        return None
    if "mod/zoom/view" not in low:
        return None
    m_id = re.search(r"[?&]id=(\d+)", url)
    if m_id:
        return f"moodle_zoom:{m_id.group(1)}"
    return None


def _ingenia_meeting_id(url: str) -> str:
    match = INGENIA_MEETING_RE.search(url.strip())
    return match.group(1) if match else ""


def _parse_ingenia_date(text: str) -> str:
    """Convierte fechas tipo '17 de febrero de 2026' a '2026-02-17'."""
    match = re.search(
        r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})",
        text.lower(),
        re.IGNORECASE,
    )
    if not match:
        return ""
    day, month_name, year = match.groups()
    month = SPANISH_MONTHS.get(
        month_name.translate(str.maketrans("áéíóú", "aeiou"))
    )
    if not month:
        return ""
    return f"{year}-{month}-{int(day):02d}"


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


def _extract_zoom_rec_id(url: str) -> str:
    match = re.search(r"/rec/(?:share|play)/([^?\s#]+)", url)
    return match.group(1) if match else url


_NEXT_PAGE_TEXT = re.compile(
    r"(siguiente|próximo|proximo|next|older|más\b|mas\b|›|»)",
    re.IGNORECASE,
)


def _ingenia_next_page_url(soup: BeautifulSoup, current_url: str) -> str:
    """Localiza enlace a la página siguiente de la lista de grabaciones Ingenia."""
    first = soup.find("a", string=re.compile(r"Siguiente", re.IGNORECASE), href=True)
    if first and first.get("href"):
        return urljoin(current_url, first["href"])

    for a in soup.find_all("a", href=True):
        if "udea.zoom.us" in a["href"]:
            continue
        t = a.get_text(" ", strip=True)
        if not t or len(t) > 48:
            continue
        if _NEXT_PAGE_TEXT.search(t):
            href = a["href"].strip()
            if href in ("#", "") or href.lower().startswith("javascript"):
                continue
            full = urljoin(current_url, href)
            if full.rstrip("/") != current_url.rstrip("/"):
                return full

    link_rel = soup.find("link", href=True, attrs={"rel": re.compile(r"next", re.I)})
    if link_rel and link_rel.get("href"):
        return urljoin(current_url, link_rel["href"])

    return ""


def _scrape_ingenia_course(page_url: str) -> list[dict]:
    """
    Scrapea una pagina publica de Ingenia. Mantiene la misma forma de salida
    que Moodle para no tocar el pipeline de descargas.
    """
    session = requests.Session()
    meeting_id = _ingenia_meeting_id(page_url)
    links = []
    seen = set()
    next_url = page_url

    while next_url:
        try:
            r = session.get(next_url, timeout=30)
            r.raise_for_status()
        except Exception:
            break

        soup = BeautifulSoup(r.text, "html.parser")
        title_node = soup.select_one("main h2") or soup.find(["h1", "h2"])
        topic = title_node.get_text(" ", strip=True) if title_node else ""

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if "udea.zoom.us/rec/" not in href:
                continue
            if not re.search(r"/rec/(?:share|play)/", href):
                continue

            full_url = urljoin(next_url, href)
            rec_id = _extract_zoom_rec_id(full_url)
            if rec_id in seen:
                continue
            seen.add(rec_id)

            container = anchor.find_parent(
                lambda tag: tag.name in {"article", "section", "div", "li"}
                and "min" in tag.get_text(" ", strip=True).lower()
            ) or anchor.parent
            text = container.get_text(" ", strip=True) if container else anchor.get_text(" ", strip=True)
            date = _parse_ingenia_date(text)
            duration_match = re.search(r"(\d+)\s*min", text, re.IGNORECASE)

            links.append({
                "url": full_url.split("?")[0],
                "full_url": full_url,
                "text": date or topic or rec_id[:20],
                "id": rec_id,
                "meeting_id": meeting_id,
                "topic": topic,
                "start_date": date,
                "duration_minutes": int(duration_match.group(1)) if duration_match else 0,
            })

        nxt = _ingenia_next_page_url(soup, next_url)
        if not nxt or nxt.rstrip("/") == next_url.rstrip("/"):
            break
        next_url = nxt

    return links


def _scrape_moodle_table_zoom_inputs(soup: BeautifulSoup) -> list[dict]:
    """Tabla Moodle clásica: inputs zoomplayredirect por fila."""
    table = soup.find("table", class_="generaltable")
    if not table:
        return []
    tbody = table.find("tbody")
    if not tbody:
        return []

    links: list[dict] = []
    seen: set[str] = set()

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

        rec_id = _extract_zoom_rec_id(href)
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

    return links


def _scrape_moodle_zoom_anchor_rows(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """
    Fallback para mod/recordingszoom/ y otras vistas: enlaces a zoom.us/rec/ en filas de tabla.
    """
    links: list[dict] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "zoom.us/rec/" not in href.lower():
            continue
        if not re.search(r"/rec/(?:share|play)/", href):
            continue

        full_url = urljoin(page_url, href)
        rec_id = _extract_zoom_rec_id(full_url)
        if rec_id in seen:
            continue
        seen.add(rec_id)

        row = anchor.find_parent("tr")
        meeting_id = topic = start_date = ""
        duration = "0"
        if row:
            cells = row.find_all("td")
            if len(cells) >= 4:
                meeting_id = cells[0].get_text(strip=True)
                topic = cells[1].get_text(strip=True)
                start_date = cells[2].get_text(strip=True)
                duration = cells[3].get_text(strip=True)
            elif cells:
                topic = " ".join(c.get_text(" ", strip=True) for c in cells)

        links.append({
            "url": full_url.split("?")[0],
            "full_url": full_url,
            "text": topic or meeting_id or rec_id[:20],
            "id": rec_id,
            "meeting_id": meeting_id,
            "topic": topic,
            "start_date": start_date,
            "duration_minutes": int(duration) if str(duration).isdigit() else 0,
        })

    return links


def _scrape_one(session: requests.Session | None, slug: str, course_info: dict) -> tuple[str, list[dict]]:
    """Scrapea una materia. Diseñado para correr en un thread."""
    url = course_info["moodle_url"]
    if is_ingenia_url(url):
        return slug, _scrape_ingenia_course(url)

    if session is None:
        print(f"  ⚠ {course_info['name']} requiere sesion de Moodle.")
        return slug, []

    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"  ⚠ Error accediendo a {course_info['name']}: {e}")
        return slug, []

    soup = BeautifulSoup(r.text, "html.parser")

    links = _scrape_moodle_table_zoom_inputs(soup)
    if not links:
        links = _scrape_moodle_zoom_anchor_rows(soup, r.url)

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
