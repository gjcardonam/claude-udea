"""
Módulo de browser: login en Moodle y scraping de grabaciones.
Aislado para que cambios en otras partes no lo afecten.
"""

import asyncio
import subprocess
import shutil
from pathlib import Path
from playwright.async_api import async_playwright

BROWSER_DATA_DIR = Path(__file__).parent / ".browser-data"
LOGIN_URL = "https://udearroba.udea.edu.co/internos/my/"


def force_clean():
    """Mata procesos de Chromium y borra .browser-data de forma robusta."""
    # Matar cualquier Chromium residual
    try:
        subprocess.run(
            ["pkill", "-f", "chromium"],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass

    # Borrar directorio, reintentar si falla
    for _ in range(3):
        if not BROWSER_DATA_DIR.exists():
            return
        try:
            shutil.rmtree(BROWSER_DATA_DIR)
            return
        except Exception:
            import time
            time.sleep(1)


async def _safe_goto(page, url):
    """Navega tolerando redirects SSO de Moodle."""
    try:
        await page.goto(url, wait_until="commit", timeout=60000)
    except Exception:
        await asyncio.sleep(3)
    try:
        await page.wait_for_selector("body", timeout=30000)
    except Exception:
        pass


async def _wait_for_login(page):
    """Espera a que el usuario inicie sesión manualmente."""
    print("\n  Inicia sesión en Moodle en el navegador que se abrió.")
    print("  El script continuará automáticamente al detectar el login.\n")

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
    """Extrae links de grabaciones de una página de Moodle."""
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


async def do_login():
    """Abre browser visible para login. Cierra al detectar sesión."""
    force_clean()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(BROWSER_DATA_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="es-CO",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        await _safe_goto(page, LOGIN_URL)
        needs_login = "login" in page.url.lower() or "sso" in page.url.lower()

        if needs_login:
            await _wait_for_login(page)
        else:
            try:
                await page.wait_for_selector(
                    ".course-listitem, .coursebox, .card-deck, [data-region='course-content']",
                    timeout=5000,
                )
            except Exception:
                await _wait_for_login(page)

        await context.close()


async def scrape_all(courses: dict, progress_callback=None) -> dict:
    """Scraping headless. Retorna {slug: [links]}. Usa cookies del login previo."""
    results = {}

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(BROWSER_DATA_DIR),
            headless=True,
            viewport={"width": 1280, "height": 800},
            locale="es-CO",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        for slug, course_info in courses.items():
            links = await _scrape_course(page, course_info)
            results[slug] = links
            if progress_callback:
                progress_callback(slug, course_info["name"], len(links))

        await context.close()

    # Limpiar browser data al terminar
    force_clean()

    return results
