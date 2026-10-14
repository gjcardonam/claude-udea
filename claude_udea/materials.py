"""Descarga material docente visible en las páginas de cursos Moodle."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


_MODULE_TYPES = {"resource", "folder", "page", "url", "assign"}


def _safe_component(value: str, fallback: str = "material") -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    value = re.sub(r"\s+", " ", value)
    return (value[:120] or fallback).strip(" .") or fallback


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "general"


def _same_host(url: str, host: str) -> bool:
    return urlparse(url).hostname == host


def discover_course_url(session: requests.Session, course_info: dict) -> str:
    """Resuelve la página de curso a partir de la URL Moodle ya configurada."""
    direct_url = course_info.get("course_url")
    if direct_url:
        return direct_url

    activity_url = course_info.get("moodle_url", "")
    host = urlparse(activity_url).hostname
    if host != "udearroba.udea.edu.co":
        raise ValueError("El curso no pertenece a Moodle UdeArroba.")

    response = session.get(activity_url, timeout=30)
    response.raise_for_status()
    if "login" in urlparse(response.url).path.lower():
        raise PermissionError("La sesión de Moodle expiró al abrir la actividad configurada.")

    soup = BeautifulSoup(response.text, "html.parser")
    course_links = []
    for anchor in soup.select('a[href*="/course/view.php"]'):
        href = urljoin(response.url, anchor.get("href", ""))
        parsed = urlparse(href)
        course_id = parse_qs(parsed.query).get("id", [""])[0]
        if parsed.hostname == host and course_id.isdigit():
            course_links.append(href)

    if not course_links:
        raise ValueError(
            f"No encontré el enlace al curso desde {course_info.get('name', 'Moodle')}."
        )
    return course_links[0]


def _section_name(anchor) -> str:
    section = anchor.find_parent(
        class_=re.compile(r"(?:course-section|section main|course-section-item)")
    )
    if section:
        heading = section.select_one(".sectionname, .section-title, h3")
        if heading:
            text = heading.get_text(" ", strip=True)
            if text:
                return text
    return "General"


def _is_safe_pluginfile(url: str, module: str | None = None) -> bool:
    path = urlparse(url).path.lower()
    if "pluginfile.php" not in path or "assignsubmission" in path or "submission_files" in path:
        return False
    if module == "assign":
        return "/mod_assign/introattachment/" in path
    if module == "resource":
        return "/mod_resource/content/" in path
    if module == "folder":
        return "/mod_folder/content/" in path
    if module == "page":
        return "/mod_page/content/" in path
    return any(
        marker in path
        for marker in (
            "/block_html/content/",
            "/mod_label/intro/",
            "/mod_resource/content/",
            "/mod_folder/content/",
            "/mod_page/content/",
            "/mod_assign/introattachment/",
        )
    )


def _course_entries(soup: BeautifulSoup, base_url: str, host: str) -> list[dict]:
    entries = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, anchor["href"])
        parsed = urlparse(url)
        if parsed.hostname != host:
            continue

        path = parsed.path.lower()
        label = anchor.get_text(" ", strip=True) or unquote(path.rsplit("/", 1)[-1])
        section = _section_name(anchor)
        if _is_safe_pluginfile(url):
            kind = "file"
        else:
            match = re.search(r"/mod/([a-z0-9_]+)/view\.php", path)
            if not match or match.group(1) not in _MODULE_TYPES:
                continue
            kind = match.group(1)
        key = (kind, url)
        if key in seen:
            continue
        seen.add(key)
        entries.append({"kind": kind, "name": label, "section": section, "url": url})
    return entries


def _course_section_urls(
    soup: BeautifulSoup,
    base_url: str,
    host: str,
    course_id: str,
) -> list[str]:
    section_urls = []
    seen = set()
    for anchor in soup.select('a[href*="/course/view.php"]'):
        url = urljoin(base_url, anchor.get("href", ""))
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.hostname != host or query.get("id", [""])[0] != course_id:
            continue
        if not query.get("section", [""])[0].isdigit() or url in seen:
            continue
        seen.add(url)
        section_urls.append(url)
    return section_urls


def _module_files(soup: BeautifulSoup, base_url: str, host: str, kind: str) -> list[dict]:
    files = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, anchor["href"])
        if urlparse(url).hostname != host or not _is_safe_pluginfile(url, kind):
            continue
        if url in seen:
            continue
        seen.add(url)
        name = anchor.get_text(" ", strip=True) or unquote(urlparse(url).path.rsplit("/", 1)[-1])
        files.append({"kind": "file", "name": name, "url": url})
    return files


def _page_text(soup: BeautifulSoup) -> str:
    main = soup.select_one("#region-main") or soup
    candidates = main.select(".no-overflow, .box.generalbox, .activity-description")
    if not candidates:
        return ""
    content = max(candidates, key=lambda element: len(element.get_text(" ", strip=True)))
    for element in content.select("script, style, form, nav"):
        element.decompose()
    return content.get_text("\n", strip=True)


def _external_url(soup: BeautifulSoup, base_url: str, host: str) -> str | None:
    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, anchor["href"])
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname and parsed.hostname != host:
            return url
    return None


def _filename_from_response(response: requests.Response, source_url: str) -> str:
    disposition = response.headers.get("Content-Disposition", "")
    message = Message()
    message["content-disposition"] = disposition
    filename = message.get_filename()
    if not filename:
        filename = unquote(urlparse(response.url or source_url).path.rsplit("/", 1)[-1])
    return _safe_component(filename, "download")


def _write_response(
    response: requests.Response,
    entry: dict,
    output_root: Path,
    existing: dict | None,
) -> dict:
    if response.status_code == 304 and existing:
        response.close()
        updated = dict(existing)
        updated["last_seen"] = datetime.now(timezone.utc).isoformat()
        return updated
    response.raise_for_status()
    if "login" in urlparse(response.url).path.lower():
        raise PermissionError("Moodle devolvió la página de inicio de sesión en vez del archivo.")
    if "text/html" in response.headers.get("Content-Type", "").lower():
        response.close()
        raise ValueError("El enlace de archivo devolvió HTML en vez de un documento.")

    filename = _filename_from_response(response, entry["url"])
    section = _safe_component(_slug(entry.get("section", "General")))
    directory = output_root / "files" / section
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / filename
    url_hash = hashlib.sha256(entry["url"].encode("utf-8")).hexdigest()[:10]
    if destination.exists() and (not existing or existing.get("url") != entry["url"]):
        destination = directory / f"{destination.stem}-{url_hash}{destination.suffix}"

    temporary = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        response.close()

    return {
        "kind": "file",
        "name": entry.get("name") or filename,
        "filename": filename,
        "section": entry.get("section", "General"),
        "url": entry["url"],
        "path": destination.relative_to(output_root).as_posix(),
        "content_type": response.headers.get("Content-Type", ""),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }


def _fetch_file(session, entry, output_root, existing, host):
    headers = {}
    if existing:
        if existing.get("etag"):
            headers["If-None-Match"] = existing["etag"]
        if existing.get("last_modified"):
            headers["If-Modified-Since"] = existing["last_modified"]
    response = session.get(entry["url"], headers=headers, timeout=(15, 120), stream=True)
    if urlparse(response.url).hostname != host:
        response.close()
        raise ValueError("Moodle redirigió el archivo a un dominio externo.")
    return _write_response(response, entry, output_root, existing)


def scrape_course_materials(
    session: requests.Session,
    course_info: dict,
    destination: Path,
) -> dict:
    """Sincroniza documentos y recursos visibles del curso en un directorio separado."""
    course_url = discover_course_url(session, course_info)
    host = urlparse(course_url).hostname
    course_response = session.get(course_url, timeout=30)
    course_response.raise_for_status()
    if "login" in urlparse(course_response.url).path.lower():
        raise PermissionError("La sesión de Moodle expiró al abrir el curso.")
    if "/enrol/" in urlparse(course_response.url).path.lower():
        raise PermissionError(
            "La plataforma muestra matrícula o compra del curso en vez del aula. "
            "La cuenta debe tener acceso activo al curso."
        )

    course_id = parse_qs(urlparse(course_url).query).get("id", [""])[0]
    pending_pages = [course_response.url]
    visited_pages = set()
    course_entries = []
    entry_urls = set()
    failures = []
    while pending_pages and len(visited_pages) < 250:
        current_url = pending_pages.pop(0)
        if current_url in visited_pages:
            continue
        visited_pages.add(current_url)
        if current_url == course_response.url:
            page_response = course_response
        else:
            try:
                page_response = session.get(current_url, timeout=30)
                page_response.raise_for_status()
            except requests.RequestException as error:
                failures.append({"url": current_url, "name": "sección", "error": str(error)})
                continue
        if "login" in urlparse(page_response.url).path.lower():
            failures.append({"url": current_url, "name": "sección", "error": "Sesión de Moodle expirada."})
            continue
        section_soup = BeautifulSoup(page_response.text, "html.parser")
        for entry in _course_entries(section_soup, page_response.url, host):
            if entry["url"] not in entry_urls:
                entry_urls.add(entry["url"])
                course_entries.append(entry)
        for section_url in _course_section_urls(
            section_soup, page_response.url, host, course_id
        ):
            if section_url not in visited_pages and section_url not in pending_pages:
                pending_pages.append(section_url)
    if pending_pages:
        failures.append({
            "url": course_url,
            "name": "secciones",
            "error": "Se alcanzó el límite de 250 páginas de sección.",
        })
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.json"
    previous_items = {}
    if manifest_path.exists():
        try:
            old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            previous_items = {item["url"]: item for item in old_manifest.get("items", [])}
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            previous_items = {}

    discovered = {}
    page_count = 0
    external_links = 0

    def add_file(file_entry):
        old_item = previous_items.get(file_entry["url"])
        try:
            discovered[file_entry["url"]] = _fetch_file(
                session, file_entry, destination, old_item, host
            )
        except (OSError, requests.RequestException, ValueError, PermissionError) as error:
            failures.append({"url": file_entry["url"], "name": file_entry.get("name", ""), "error": str(error)})

    for entry in course_entries:
        if entry["kind"] == "file":
            add_file(entry)
            continue

        try:
            response = session.get(
                entry["url"],
                timeout=(15, 120),
                stream=True,
                allow_redirects=entry["kind"] != "url",
            )
        except requests.RequestException as error:
            failures.append({"url": entry["url"], "name": entry["name"], "error": str(error)})
            continue
        if entry["kind"] == "url" and response.is_redirect:
            target_url = urljoin(response.url, response.headers.get("Location", ""))
            target = urlparse(target_url)
            response.close()
            if target.scheme in {"http", "https"} and target.hostname != host:
                discovered[entry["url"]] = {
                    "kind": "external_link",
                    "name": entry["name"],
                    "section": entry["section"],
                    "url": entry["url"],
                    "target_url": target_url,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                }
                external_links += 1
                continue
            if target.hostname == host:
                response = session.get(target_url, timeout=(15, 120), stream=True)
        if urlparse(response.url).hostname != host:
            response.close()
            failures.append({"url": entry["url"], "name": entry["name"], "error": "Moodle redirigió a un dominio externo."})
            continue
        try:
            response.raise_for_status()
        except requests.RequestException as error:
            response.close()
            failures.append({"url": entry["url"], "name": entry["name"], "error": str(error)})
            continue
        if "login" in urlparse(response.url).path.lower():
            response.close()
            failures.append({"url": entry["url"], "name": entry["name"], "error": "Sesión de Moodle expirada."})
            continue

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type:
            old_item = previous_items.get(entry["url"])
            try:
                discovered[entry["url"]] = _write_response(
                    response,
                    entry,
                    destination,
                    old_item,
                )
            except (OSError, requests.RequestException, ValueError, PermissionError) as error:
                failures.append({"url": entry["url"], "name": entry["name"], "error": str(error)})
            continue

        page = BeautifulSoup(response.content, "html.parser")
        page_url = response.url
        response.close()

        if entry["kind"] in {"resource", "folder", "page", "assign"}:
            for file_entry in _module_files(page, page_url, host, entry["kind"]):
                file_entry.update({"section": entry["section"], "name": file_entry.get("name") or entry["name"]})
                add_file(file_entry)

        if entry["kind"] == "page":
            text = _page_text(page)
            if text:
                title = _safe_component(entry["name"], "pagina")
                text_path = destination / "pages" / _safe_component(_slug(entry["section"])) / f"{title}.txt"
                text_path.parent.mkdir(parents=True, exist_ok=True)
                text_path.write_text(text + "\n", encoding="utf-8")
                discovered[entry["url"]] = {
                    "kind": "page",
                    "name": entry["name"],
                    "section": entry["section"],
                    "url": entry["url"],
                    "path": text_path.relative_to(destination).as_posix(),
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                }
                page_count += 1

        if entry["kind"] == "url":
            external = _external_url(page, page_url, host)
            if external:
                discovered[entry["url"]] = {
                    "kind": "external_link",
                    "name": entry["name"],
                    "section": entry["section"],
                    "url": entry["url"],
                    "target_url": external,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                }
                external_links += 1

    for source_url, item in previous_items.items():
        discovered.setdefault(source_url, item)

    manifest = {
        "course": course_info.get("name", ""),
        "course_id": course_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": sum(item.get("kind") == "file" for item in discovered.values()),
        "page_count": page_count,
        "external_link_count": external_links,
        "failures": failures,
        "items": list(discovered.values()),
    }
    temporary_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary_manifest.replace(manifest_path)
    return manifest