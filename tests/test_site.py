#!/usr/bin/env python3
"""Static checks for the Naldo's GitHub Pages site.

Confirms the approved business details, real JPEG gallery files, relative
paths that work under /-naldos-visible/, and photos that render without
JavaScript.
"""

from __future__ import annotations

import http.server
import os
import re
import socket
import tempfile
import threading
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
BASE_PATH = "/-naldos-visible"

PHONE_DISPLAY = "079 695 1572"
PHONE_TEL = "tel:+27796951572"
WHATSAPP_URL = "https://wa.me/27796951572"
WHATSAPP_LABEL = f"WhatsApp {PHONE_DISPLAY}"
EMAIL = "arnaldohuman@gmail.com"
MAILTO = f"mailto:{EMAIL}"
EMAIL_LABEL = f"Email {EMAIL}"
MANAGER = "Rhenvin Human"
ADDRESS_LINES = ("12 Rewlatch Road", "Rewlatch 2197", "Johannesburg")
BUSINESS = "Naldo's Roller Shutter Doors, Automotive & Steel Works"

SERVICES = (
    "Roller Shutter Doors",
    "Steel Gates & Custom Work",
    "Solar Panel Installations",
    "Steel Fabrication & Welding",
    "Gates & Burglar Bars",
    "Automotive Repairs",
    "Garage Doors",
    "Custom Steel Structures",
)

GALLERY_COUNT = 25

FILTERS = ("all", "shutters", "steel", "gates", "railings", "solar")

SOLAR_FULL = (
    "images/solar-home-installation.jpg",
    "images/solar-panels-roof-mounting.jpg",
    "images/solar-inverter-battery-finished.jpg",
    "images/solar-inverter-battery-wip.jpg",
)
GATE_MOTOR_FULL = "images/gate-motor-installation.jpg"

FORBIDDEN_MARKERS = (
    "testimonial",
    "accreditation",
    "accredited",
    "<form",
    "data:image",
)


class Node:
    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag = tag
        self.attrs = attrs
        self.children: list[Node | str] = []

    def text(self) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            else:
                parts.append(child.text())
        return "".join(parts)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def find_all(self, tag: str) -> list[Node]:
        return [node for node in self.walk() if node.tag == tag]


class TreeParser(HTMLParser):
    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("document", {})
        self.stack = [self.root]
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.skip_depth:
            if tag in ("script", "style"):
                self.skip_depth += 1
            return
        node = Node(tag, {k.lower(): (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)
        if tag in ("script", "style"):
            self.skip_depth = 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style") and self.skip_depth:
            self.skip_depth -= 1
            if self.skip_depth == 0 and self.stack and self.stack[-1].tag == tag:
                self.stack.pop()
            return
        if self.skip_depth:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.skip_depth:
            return
        if data:
            self.stack[-1].children.append(data)


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def visible_text(root: Node) -> str:
    return re.sub(r"\s+", " ", root.text()).strip()


def contrast_ratio(foreground: str, background: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def luminance(hex_color: str) -> float:
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    hi, lo = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    check(data[:2] == b"\xff\xd8", f"{path.name} is not a JPEG")
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            check(width > 0 and height > 0, f"{path.name} has no pixel size")
            return width, height
        if marker == 0xD9 or marker == 0xDA:
            break
        if index + 4 > len(data):
            break
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        if length < 2:
            break
        index += 2 + length
    fail(f"{path.name} has no JPEG frame header")


def assert_relative_asset(url: str, kind: str) -> None:
    check(bool(url), f"empty {kind}")
    lowered = url.lower()
    check(not lowered.startswith("data:"), f"{kind} uses a data URI: {url[:40]}")
    check(not lowered.startswith(("http://", "https://", "//")), f"{kind} is absolute: {url}")
    check(not url.startswith("/"), f"{kind} is root-absolute and ignores {BASE_PATH}: {url}")
    check(not url.startswith(("./../", "../")), f"{kind} escapes the site directory: {url}")
    check("\\" not in url, f"{kind} uses a backslash: {url}")


def serve_under_base_path() -> None:
    parent = Path(tempfile.mkdtemp(prefix="naldos-pages-"))
    link = parent / "-naldos-visible"
    link.symlink_to(ROOT, target_is_directory=True)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(parent), **kwargs)

        def log_message(self, fmt: str, *args) -> None:
            return

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}{BASE_PATH}"
        for path in ("/", "/index.html"):
            with urllib.request.urlopen(base + path, timeout=5) as response:
                body = response.read().decode("utf-8")
                check(response.status == 200, f"{path} status {response.status}")
                check(BUSINESS in body or "Naldo&#39;s" in body or "Naldo's" in body, f"{path} missing business name")
        html = INDEX.read_text(encoding="utf-8")
        assets = sorted(set(re.findall(r'(?:src|data-full)="(images/[^"]+)"', html)))
        check(len(assets) >= GALLERY_COUNT + 1, "not enough image references to request")
        for asset in assets:
            url = f"{base}/{asset}"
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    payload = response.read()
                    check(response.status == 200, f"{asset} status {response.status}")
                    check(response.headers.get_content_type() in ("image/jpeg", "image/jpg"), f"{asset} content-type")
                    check(payload[:2] == b"\xff\xd8", f"{asset} body is not JPEG")
            except urllib.error.HTTPError as error:
                fail(f"{url} returned HTTP {error.code}")
        # A root-absolute image path would miss the project prefix. Confirm that mistake 404s.
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/images/hero-embed.jpg", timeout=5)
            fail("root-absolute /images/ was served; base-path check is invalid")
        except urllib.error.HTTPError as error:
            check(error.code == 404, f"unexpected status for root-absolute image: {error.code}")
    finally:
        server.shutdown()
        server.server_close()


def check_pages_workflow() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    for required in (
        "actions/checkout@v4",
        "actions/configure-pages@v5",
        "actions/upload-pages-artifact@v3",
        "actions/deploy-pages@v5",
        "pages: write",
        "id-token: write",
        'branches: ["main"]',
        "path: _site",
        "github-pages",
    ):
        check(required in workflow, f"pages workflow missing {required}")
    lowered = workflow.lower()
    check("cname" not in lowered, "pages workflow mentions a custom domain")
    check("secrets." not in lowered, "pages workflow reads secrets")
    check("pull_request" not in lowered, "pages deploy must not run on pull requests")
    check((ROOT / ".nojekyll").is_file(), ".nojekyll is missing")
    checks = (ROOT / ".github" / "workflows" / "site-checks.yml").read_text(encoding="utf-8")
    check("python3 tests/test_site.py" in checks, "site checks workflow does not run the test")


def check_whatsapp(doc: Node, raw: str) -> None:
    """Allow only the published WhatsApp contact, in the same places as the phone."""
    links = [
        node
        for node in doc.find_all("a")
        if "wa.me" in node.attrs.get("href", "").lower() or "whatsapp" in node.attrs.get("href", "").lower()
    ]
    check(links, "WhatsApp contact link is missing")
    for node in links:
        href = node.attrs.get("href", "")
        check(href == WHATSAPP_URL, f"only {WHATSAPP_URL} is allowed, found {href}")
        check(node.attrs.get("target") == "_blank", "WhatsApp link must open in a new tab")
        check("noopener" in node.attrs.get("rel", "").split(), 'WhatsApp link must include rel="noopener"')
        visible = re.sub(r"\s+", " ", node.text()).strip()
        check(visible == WHATSAPP_LABEL, f"WhatsApp label should be {WHATSAPP_LABEL!r}, found {visible!r}")
        check(
            node.attrs.get("aria-label", "").strip() == WHATSAPP_LABEL,
            "WhatsApp link needs an accessible label with the phone number",
        )
        check("btn" in node.attrs.get("class", "").split(), "WhatsApp link should use the existing button style")
        icons = node.find_all("svg")
        check(len(icons) == 1, "WhatsApp link needs one icon")
        check(icons[0].attrs.get("aria-hidden") == "true", "WhatsApp icon should be hidden from assistive tech")

    for found in re.findall(r"https?://[^\s\"'<>]+", raw, flags=re.I):
        lowered = found.lower()
        if "wa.me" in lowered or "whatsapp" in lowered:
            check(found == WHATSAPP_URL, f"unexpected WhatsApp URL: {found}")
    check(raw.count(WHATSAPP_URL) == len(links), "WhatsApp URL appears outside the allowed links")
    check("api.whatsapp.com" not in raw.lower(), "unexpected WhatsApp API link")
    check("web.whatsapp.com" not in raw.lower(), "unexpected WhatsApp Web link")

    def region(start: str, end: str) -> str:
        begin = raw.find(start)
        finish = raw.find(end, begin + len(start)) if begin != -1 else -1
        check(begin != -1 and finish != -1, f"could not find {start} … {end}")
        return raw[begin:finish]

    check(WHATSAPP_URL in region("<header", "<section"), "WhatsApp link missing from the header call contact")
    check(WHATSAPP_URL in region('class="hero"', 'id="main"'), "WhatsApp link missing from the hero call-to-action")
    check(WHATSAPP_URL in region('id="contact"', "<footer"), "WhatsApp link missing from the contact section")


def check_email(doc: Node, raw: str) -> None:
    """Allow only Rhenvin Human's published email address."""
    links = [
        node
        for node in doc.find_all("a")
        if node.attrs.get("href", "").lower().startswith("mailto:")
    ]
    check(links, "email contact link is missing")
    for node in links:
        href = node.attrs.get("href", "")
        check(href == MAILTO, f"only {MAILTO} is allowed, found {href}")
        check(
            node.attrs.get("aria-label", "").strip() == EMAIL_LABEL,
            "email link needs an accessible label with the address",
        )
        visible = re.sub(r"\s+", " ", node.text()).strip()
        check(
            visible in {EMAIL, "Email", EMAIL_LABEL},
            f"unexpected email link text: {visible!r}",
        )
        classes = set(node.attrs.get("class", "").split())
        check(classes & {"btn", "tel"}, "email link should use the existing button or contact link style")
        icons = node.find_all("svg")
        check(len(icons) == 1, "email link needs one envelope icon")
        check(icons[0].attrs.get("aria-hidden") == "true", "email icon should be hidden from assistive tech")

    addresses = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", raw)
    check(addresses, "email address missing from the page")
    check(all(found == EMAIL for found in addresses), f"unexpected email address: {addresses}")
    mailtos = re.findall(r"mailto:[^\s\"'<>]+", raw, flags=re.I)
    check(mailtos and all(found == MAILTO for found in mailtos), f"unexpected mailto link: {mailtos}")
    check(raw.count(MAILTO) == len(links), "mailto appears outside the allowed links")

    def region(start: str, end: str) -> str:
        begin = raw.find(start)
        finish = raw.find(end, begin + len(start)) if begin != -1 else -1
        check(begin != -1 and finish != -1, f"could not find {start} … {end}")
        return raw[begin:finish]

    check(MAILTO in region("<header", "<section"), "email link missing from the header")
    check(MAILTO in region('class="hero"', 'id="main"'), "email link missing from the hero")
    contact = region('id="contact"', "<footer")
    check(MAILTO in contact, "email link missing from the contact section")
    check(EMAIL in contact, "email address missing from the contact section")


def main() -> None:
    check(INDEX.is_file(), "index.html is missing")
    raw = INDEX.read_text(encoding="utf-8")
    check(len(raw) < 120_000, "index.html looks like an embedded-image file")
    check("<base" not in raw.lower(), "a <base> tag would pin the wrong host or path")

    lowered_raw = raw.lower()
    for marker in FORBIDDEN_MARKERS:
        check(marker not in lowered_raw, f"forbidden marker present: {marker}")

    parser = TreeParser()
    parser.feed(raw)
    doc = parser.root
    html_nodes = doc.find_all("html")
    check(len(html_nodes) == 1, "missing html element")
    check(html_nodes[0].attrs.get("lang", "").lower().startswith("en"), "html lang is missing")

    viewport = [
        node
        for node in doc.find_all("meta")
        if node.attrs.get("name", "").lower() == "viewport"
    ]
    check(viewport, "viewport meta is missing")
    content = viewport[0].attrs.get("content", "")
    check("width=device-width" in content and "initial-scale=1" in content, f"viewport is {content!r}")

    titles = doc.find_all("title")
    check(len(titles) == 1 and BUSINESS in titles[0].text(), "title does not match the business name")

    h1 = doc.find_all("h1")
    check(len(h1) == 1, f"expected one h1, found {len(h1)}")
    headings = [node for node in doc.walk() if re.fullmatch(r"h[1-6]", node.tag)]
    levels = [int(node.tag[1]) for node in headings]
    for previous, current in zip(levels, levels[1:]):
        check(current <= previous + 1, f"heading level jumps from h{previous} to h{current}")

    text = visible_text(doc)
    check(MANAGER in text, "manager name missing")
    check(text.count(PHONE_DISPLAY) >= 2, "phone number is not shown in the page")
    for line in ADDRESS_LINES:
        check(line in text, f"address line missing: {line}")
    for service in SERVICES:
        check(service in text, f"service missing: {service}")
    check("Email will be added once confirmed." not in text, "email is still described as unconfirmed")
    check(
        "Call or email to confirm whether we can assist with your job and location." in text,
        "contact note was not updated for email",
    )
    check(EMAIL in text, "email address is not shown")
    check("Solar" in text, "solar service text missing")

    tel_links = [
        node.attrs.get("href", "")
        for node in doc.find_all("a")
        if node.attrs.get("href", "").startswith("tel:")
    ]
    check(tel_links, "no telephone links")
    check(all(href == PHONE_TEL for href in tel_links), f"unexpected tel links: {tel_links}")
    check_whatsapp(doc, raw)
    check_email(doc, raw)

    main = doc.find_all("main")
    check(len(main) == 1 and main[0].attrs.get("id") == "main", "main landmark missing")
    skip = [node for node in doc.find_all("a") if node.attrs.get("href") == "#main"]
    check(skip, "skip link missing")
    check(doc.find_all("header") and doc.find_all("footer") and doc.find_all("nav"), "landmarks missing")

    images = doc.find_all("img")
    check(images, "no images")
    gallery_sources: list[str] = []
    for image in images:
        src = image.attrs.get("src", "")
        # The lightbox image starts without a src and is display:none until a photo is opened.
        if src == "":
            check(image.attrs.get("alt") == "", "placeholder image needs an empty alt")
            continue
        assert_relative_asset(src, "img src")
        check("alt" in image.attrs, f"img missing alt: {src}")
        path = ROOT / src
        check(path.is_file(), f"missing image file {src}")
        jpeg_size(path)
        if "thumb" in src or src.endswith("hero-embed.jpg") or src.endswith("hero.jpg"):
            continue
        gallery_sources.append(src)
    # Gallery photos are the thumbnails inside project cards. Full files are linked for the lightbox.
    cards = [node for node in doc.find_all("figure") if "project-card" in node.attrs.get("class", "")]
    check(len(cards) == GALLERY_COUNT, f"expected {GALLERY_COUNT} gallery cards, found {len(cards)}")
    indexes = [int(card.attrs.get("data-index", "-1")) for card in cards]
    check(indexes == list(range(GALLERY_COUNT)), f"data-index is not sequential: {indexes}")
    filter_buttons = [node for node in doc.find_all("button") if node.attrs.get("data-filter")]
    filter_values = [node.attrs["data-filter"] for node in filter_buttons]
    check(filter_values == list(FILTERS), f"filter buttons are {filter_values}")
    solar_filter = filter_buttons[-1]
    check(solar_filter.text().strip() == "Solar installations", "solar filter label changed")
    full_sources: list[str] = []
    for card in cards:
        images_in_card = card.find_all("img")
        check(len(images_in_card) == 1, "each gallery card needs one visible image")
        alt = images_in_card[0].attrs.get("alt", "").strip()
        check(alt, "gallery image alt is empty")
        category = card.attrs.get("data-category", "")
        check(category in FILTERS, f"gallery category has no filter: {category}")
        thumb = images_in_card[0].attrs["src"]
        check(thumb.startswith("images/") and thumb.endswith("-thumb.jpg"), f"gallery thumb path {thumb}")
        buttons = [node for node in card.find_all("button") if "open" in node.attrs.get("class", "")]
        check(len(buttons) == 1, "gallery card missing open button")
        label = buttons[0].attrs.get("aria-label", "").strip()
        check(label.lower().startswith("open photo:"), f"open button label missing: {label}")
        full = buttons[0].attrs.get("data-full", "")
        assert_relative_asset(full, "data-full")
        check((ROOT / full).is_file(), f"missing full image {full}")
        jpeg_size(ROOT / full)
        if category == "solar":
            check("solar" in full.lower() and "solar" in thumb.lower(), f"solar card path {full}")
        else:
            check("solar" not in alt.lower(), f"gallery alt invents a solar photo: {alt}")
            check("solar" not in full.lower() and "solar" not in thumb.lower(), "solar image on a non-solar card")
        full_sources.append(full)
    check(len(set(full_sources)) == GALLERY_COUNT, "gallery full images are not unique")
    for solar_full in SOLAR_FULL:
        check(solar_full in full_sources, f"missing solar gallery photo {solar_full}")
    check(GATE_MOTOR_FULL in full_sources, "missing gate motor gallery photo")
    gate_cards = [
        card
        for card in cards
        if any(node.attrs.get("data-full") == GATE_MOTOR_FULL for node in card.find_all("button"))
    ]
    check(len(gate_cards) == 1 and gate_cards[0].attrs.get("data-category") == "gates", "gate motor card category")

    hero = [image for image in images if image.attrs.get("src") == "images/hero-embed.jpg"]
    check(len(hero) == 1, "hero image missing")
    check(hero[0].attrs.get("alt") == "", "decorative hero image should have an empty alt")

    style = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", raw, flags=re.I | re.S))
    check(style.strip(), "page has no stylesheet")
    check(".reveal" in style and "opacity:1" in style.replace(" ", ""), "reveal class hides content until JS")
    check("opacity:1!important" in style.replace(" ", ""), "no-JS visibility rule missing")
    check(".project-card.is-hidden{display:none" in style.replace(" ", ""), "filter hide rule missing")
    check("img{max-width:100%" in style.replace(" ", ""), "images are not fluid")
    # Default cards are not display:none. Only the filtered state is.
    check(not re.search(r"\.project-card\s*\{[^}]*display\s*:\s*none", style), "gallery cards are hidden by default")

    colors = dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", style))
    pairs = (
        ("silver-2", "charcoal", 4.5),
        ("muted", "charcoal", 4.5),
        ("muted", "card", 4.5),
        ("red-text", "charcoal", 4.5),
        ("red-text", "card", 4.5),
    )
    for foreground, background, minimum in pairs:
        ratio = contrast_ratio(colors[foreground], colors[background])
        check(ratio >= minimum, f"{foreground} on {background} contrast {ratio:.2f} < {minimum}")

    for node in doc.walk():
        check(node.attrs.get("tabindex", "0") in ("0", "-1", ""), f"positive tabindex on {node.tag}")

    check_pages_workflow()
    serve_under_base_path()
    print("OK: site files, contacts, gallery JPEGs, base path, and Pages workflow checks passed")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
