"""
Módulo de browser: login en Moodle y scraping de grabaciones.
Aislado para que cambios en otras partes no lo afecten.
"""

import asyncio
import platform
import subprocess
import shutil
import signal
import time
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

LOGIN_URL = "https://udearroba.udea.edu.co/internos/my/"

# User agent real de Chrome estable (no el de Playwright/Chromium)
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

stealth = Stealth(
    navigator_webdriver=True,
    webgl_vendor=True,
    chrome_app=True,
    chrome_csi=True,
    chrome_load_times=True,
    chrome_runtime=True,
    iframe_content_window=True,
    media_codecs=True,
    navigator_hardware_concurrency=True,
    navigator_languages=True,
    navigator_permissions=True,
    navigator_platform=True,
    navigator_plugins=True,
    navigator_user_agent=True,
    navigator_vendor=True,
    hairline=True,
    error_prototype=True,
    sec_ch_ua=True,
    navigator_languages_override=("es-CO", "es"),
    navigator_platform_override="Win32",
    navigator_user_agent_override=CHROME_UA,
)

# Args para que Chromium parezca un browser real
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
    "--disable-component-update",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-dev-shm-usage",
    "--lang=es-CO",
    "--window-size=1366,768",
]


def _browser_data_dir(work_dir: Path) -> Path:
    return work_dir / ".browser-data"


def _kill_chromium():
    """Mata procesos de Chromium de forma cross-platform."""
    if platform.system() == "Windows":
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "chromium.exe"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
    else:
        # macOS / Linux: pkill chromium
        try:
            subprocess.run(
                ["pkill", "-f", "chromium"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass


def _is_browser_locked(work_dir: Path) -> bool:
    """Detecta si el perfil quedó trabado por un crash previo."""
    lock_file = _browser_data_dir(work_dir) / "SingletonLock"
    cookie_lock = _browser_data_dir(work_dir) / "SingletonCookie"
    return lock_file.exists() or cookie_lock.exists()


def force_clean(work_dir: Path):
    """Solo limpia si hay un lock de crash. Preserva cookies y sesión."""
    bdir = _browser_data_dir(work_dir)

    if not bdir.exists():
        return

    if not _is_browser_locked(work_dir):
        return

    # Hay un lock — matar procesos y limpiar locks
    _kill_chromium()
    time.sleep(1)

    for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        lock_path = bdir / lock
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    # Si sigue trabado, borrar todo como último recurso
    if _is_browser_locked(work_dir):
        for _ in range(3):
            try:
                shutil.rmtree(bdir)
                return
            except Exception:
                time.sleep(1)

        if platform.system() == "Windows":
            try:
                subprocess.run(
                    ["cmd", "/c", "rmdir", "/s", "/q", str(bdir)],
                    capture_output=True, timeout=10,
                )
            except Exception:
                pass


async def _safe_goto(page, url):
    try:
        await page.goto(url, wait_until="commit", timeout=60000)
    except Exception:
        await asyncio.sleep(3)
    try:
        await page.wait_for_selector("body", timeout=30000)
    except Exception:
        pass


async def _wait_for_login(page):
    print("\n  Inicia sesión en Moodle en el navegador que se abrió.")
    print("  Continuará automáticamente al detectar el login.\n")

    while True:
        try:
            if "/my/" in page.url:
                await page.wait_for_selector(
                    ".course-listitem, .coursebox, .card-deck, [data-region='course-content']",
                    timeout=2000,
                )
                return
        except Exception:
            pass
        await asyncio.sleep(1)


async def _scrape_course(page, course_info: dict) -> list[dict]:
    await _safe_goto(page, course_info["moodle_url"])
    await asyncio.sleep(3)

    return await page.evaluate("""() => {
        const rows = document.querySelectorAll('table.generaltable tbody tr');
        const results = [];
        const seen = new Set();
        for (const row of rows) {
            const cells = row.querySelectorAll('td');
            if (cells.length < 4) continue;
            const hiddenInput = row.querySelector('input[name="zoomplayredirect"]');
            if (!hiddenInput) continue;
            const href = hiddenInput.value;
            if (!href) continue;
            const match = href.match(/\\/rec\\/(?:share|play)\\/([^?\\s]+)/);
            const id = match ? match[1] : href;
            if (seen.has(id)) continue;
            seen.add(id);
            const meetingId = cells[0]?.textContent.trim() || '';
            const topic = cells[1]?.textContent.trim() || '';
            const startDate = cells[2]?.textContent.trim() || '';
            const duration = cells[3]?.textContent.trim() || '';
            results.push({
                url: href.split('?')[0], full_url: href,
                text: topic || meetingId, id: id,
                meeting_id: meetingId, topic: topic,
                start_date: startDate, duration_minutes: parseInt(duration) || 0
            });
        }
        return results;
    }""")


async def do_login(work_dir: Path):
    """No-op: login ahora se hace dentro de login_and_scrape."""
    pass


async def scrape_all(work_dir: Path, courses: dict) -> dict:
    """No-op: scraping ahora se hace dentro de login_and_scrape."""
    return {}


def _launch_args(headless: bool) -> dict:
    """Parámetros comunes para launch_persistent_context."""
    return dict(
        headless=headless,
        viewport={"width": 1366, "height": 768},
        screen={"width": 1920, "height": 1080},
        locale="es-CO",
        timezone_id="America/Bogota",
        user_agent=CHROME_UA,
        color_scheme="light",
        args=STEALTH_ARGS,
        ignore_default_args=["--enable-automation"],
    )


_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    if (!window.chrome) {
        window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
    }
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
                {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                {name: 'Native Client', filename: 'internal-nacl-plugin'},
            ];
            plugins.length = 3;
            return plugins;
        }
    });
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (params) =>
        params.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : originalQuery(params);
"""


async def _setup_page(context):
    """Prepara una página con stealth y parches anti-detección."""
    page = context.pages[0] if context.pages else await context.new_page()
    await stealth.apply_stealth_async(page)
    await page.add_init_script(_INIT_SCRIPT)
    return page


async def _ensure_login(work_dir: Path, playwright_instance):
    """Abre browser visible solo si es necesario hacer login. Cierra al terminar."""
    bdir = _browser_data_dir(work_dir)

    # Primero intentar headless para ver si la sesión persiste
    try:
        context = await playwright_instance.chromium.launch_persistent_context(
            str(bdir), **_launch_args(headless=True),
        )
        page = await _setup_page(context)
        await page.goto(LOGIN_URL, wait_until="commit", timeout=30000)
        await asyncio.sleep(2)

        is_logged_in = "/my/" in page.url
        if is_logged_in:
            try:
                await page.wait_for_selector(
                    ".course-listitem, .coursebox, .card-deck, [data-region='course-content']",
                    timeout=5000,
                )
            except Exception:
                is_logged_in = False

        await context.close()

        if is_logged_in:
            print("  ✔ Sesión activa (login no necesario)\n")
            return
    except Exception:
        # Si falla headless, seguir con visible
        try:
            await context.close()
        except Exception:
            pass

    # Sesión expirada — abrir visible para login manual
    context = await playwright_instance.chromium.launch_persistent_context(
        str(bdir), **_launch_args(headless=False),
    )
    page = await _setup_page(context)
    await _safe_goto(page, LOGIN_URL)
    await _wait_for_login(page)
    print("  ✔ Sesión guardada\n")
    await context.close()


async def login_and_scrape(work_dir: Path, courses: dict) -> dict:
    """Login (visible si es necesario) + scraping headless. Retorna {slug: [links]}."""
    force_clean(work_dir)
    bdir = _browser_data_dir(work_dir)
    results = {}

    async with async_playwright() as p:
        # Paso 1: asegurar login (abre ventana solo si la sesión expiró)
        await _ensure_login(work_dir, p)

        # Paso 2: scrapear en headless — invisible
        print("  Scrapeando en segundo plano...\n")
        context = await p.chromium.launch_persistent_context(
            str(bdir), **_launch_args(headless=True),
        )
        page = await _setup_page(context)

        for slug, course_info in courses.items():
            links = await _scrape_course(page, course_info)
            results[slug] = links

        await context.close()

    return results
