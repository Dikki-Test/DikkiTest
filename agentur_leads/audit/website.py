"""Website-Check: Gibt es eine Website – und wie gut/zeitgemäß ist sie?"""

from __future__ import annotations

import datetime as dt
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..http import PoliteSession
from ..models import WebsiteAudit

SOCIAL_PATTERNS = {
    "instagram": re.compile(r"instagram\.com/(?!p/|reel/|explore/|accounts/)([A-Za-z0-9_.]{2,30})/?", re.I),
    "facebook": re.compile(r"facebook\.com/(?!sharer|share\.php|dialog)([A-Za-z0-9_.\-]+)/?", re.I),
    "linkedin": re.compile(r"linkedin\.com/(company|in)/([A-Za-z0-9_\-]+)", re.I),
    "youtube": re.compile(r"youtube\.com/(@[A-Za-z0-9_.\-]+|channel/[A-Za-z0-9_\-]+|c/[A-Za-z0-9_\-]+)", re.I),
    "tiktok": re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)", re.I),
}

BAUKASTEN_MARKER = {
    "Jimdo": ["jimdo", "jimdosite"],
    "Wix": ["wix.com", "wixstatic", "_wixcss"],
    "IONOS MyWebsite": ["mywebsite-editor", "ionos-mywebsite", "homepagebaukasten"],
    "Squarespace": ["squarespace"],
    "Webflow": ["webflow"],
    "WordPress": ["wp-content", "wp-includes"],
    "TYPO3": ["typo3"],
    "Joomla": ["/media/jui/", "joomla"],
    "Strato Homepage-Baukasten": ["strato-editor", "sitebuilder"],
    "Shopify": ["cdn.shopify"],
}

# Häufige "Instagram-Handles", die keine echten Profile sind
IG_BLACKLIST = {"instagram", "sharer", "about", "developer", "legal", "explore", "p", "reel", "stories"}


def _detect_baukasten(html_lower: str, generator: str) -> str:
    generator = generator.lower()
    for name, markers in BAUKASTEN_MARKER.items():
        if name.lower().split()[0] in generator or any(m in html_lower for m in markers):
            return name
    return ""


def _veraltete_technik(soup: BeautifulSoup, html_lower: str) -> list[str]:
    hinweise = []
    if soup.find(["frameset", "frame"]):
        hinweise.append("Frames")
    if "shockwave-flash" in html_lower or ".swf" in html_lower:
        hinweise.append("Flash")
    if re.search(r"jquery[-.]?1\.[0-9]", html_lower):
        hinweise.append("jQuery 1.x")
    if soup.find("font") or soup.find("center") or soup.find("marquee"):
        hinweise.append("HTML-3/4-Tags (font/center/marquee)")
    layout_tables = [t for t in soup.find_all("table") if t.get("width") or t.get("bgcolor")]
    if len(layout_tables) >= 2:
        hinweise.append("Tabellen-Layout")
    if "besucherzähler" in html_lower or "counter.php" in html_lower:
        hinweise.append("Besucherzähler")
    return hinweise


def _copyright_jahr(text: str) -> int | None:
    jahre = [int(j) for j in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", text, re.I)]
    return max(jahre) if jahre else None


def extract_social_links(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    links: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        for name, pat in SOCIAL_PATTERNS.items():
            if name in links:
                continue
            m = pat.search(href)
            if not m:
                continue
            if name == "instagram":
                handle = m.group(1).rstrip(".")
                if handle.lower() in IG_BLACKLIST:
                    continue
                links[name] = handle
            else:
                links[name] = href
    return links


def analyse_html(html: str, url: str, audit: WebsiteAudit) -> BeautifulSoup:
    """Füllt die inhaltlichen Felder des Audits aus dem HTML. Gibt die Soup zurück."""
    soup = BeautifulSoup(html, "html.parser")
    lower = html.lower()
    text = soup.get_text(" ", strip=True)

    audit.mobil_viewport = bool(soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}))
    audit.title = (soup.title.string or "").strip()[:150] if soup.title else ""
    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    audit.meta_description = bool(md and md.get("content", "").strip())

    link_texts = " ".join(
        (a.get_text(" ", strip=True) + " " + a.get("href", "")).lower() for a in soup.find_all("a")
    )
    audit.impressum = "impressum" in link_texts or "imprint" in link_texts
    audit.datenschutz = "datenschutz" in link_texts or "privacy" in link_texts
    audit.telefon_klickbar = bool(soup.find("a", href=re.compile(r"^tel:", re.I)))
    audit.kontaktformular = any(
        f.find(["textarea"]) or f.find("input", attrs={"type": "email"}) for f in soup.find_all("form")
    ) or "contact-form" in lower or "wpcf7" in lower
    audit.copyright_jahr = _copyright_jahr(text)
    gen = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
    audit.baukasten = _detect_baukasten(lower, gen.get("content", "") if gen else "")
    audit.veraltete_technik = _veraltete_technik(soup, lower)
    audit.social_links = extract_social_links(soup, url)
    return soup


def score(audit: WebsiteAudit, heute: dt.date | None = None) -> None:
    """Bewertet die Website 0-100 und sammelt verkaufsrelevante Mängel."""
    heute = heute or dt.date.today()
    if not audit.erreichbar:
        audit.score = 0
        audit.maengel = ["Website nicht erreichbar" + (f" ({audit.fehler})" if audit.fehler else "")]
        return
    s = 100
    m: list[str] = []
    if not audit.https:
        s -= 20
        m.append("Kein HTTPS (Browser zeigt 'Nicht sicher')")
    if not audit.mobil_viewport:
        s -= 25
        m.append("Nicht für Smartphones optimiert (kein Viewport)")
    if audit.ladezeit_s is not None and audit.ladezeit_s > 3:
        s -= 10
        m.append(f"Langsam ({audit.ladezeit_s:.1f}s Antwortzeit)")
    if not audit.meta_description:
        s -= 5
        m.append("Keine Meta-Description (schwach bei Google)")
    if not audit.impressum:
        s -= 10
        m.append("Kein Impressum verlinkt (Abmahnrisiko)")
    if not audit.datenschutz:
        s -= 5
        m.append("Keine Datenschutzerklärung verlinkt")
    if not audit.telefon_klickbar:
        s -= 5
        m.append("Telefonnummer nicht klickbar")
    if not audit.kontaktformular:
        s -= 5
        m.append("Kein Kontakt-/Anfrageformular")
    if audit.copyright_jahr and audit.copyright_jahr <= heute.year - 3:
        s -= 10
        m.append(f"Wirkt veraltet (© {audit.copyright_jahr})")
    if audit.veraltete_technik:
        s -= 10 * min(len(audit.veraltete_technik), 2)
        m.append("Veraltete Technik: " + ", ".join(audit.veraltete_technik))
    if audit.baukasten in {"Jimdo", "IONOS MyWebsite", "Strato Homepage-Baukasten"}:
        s -= 5
        m.append(f"Einfacher Baukasten ({audit.baukasten})")
    audit.score = max(0, min(100, s))
    audit.maengel = m


def audit_website(http: PoliteSession, url: str) -> tuple[WebsiteAudit, BeautifulSoup | None]:
    audit = WebsiteAudit(url=url)
    if not url:
        return audit, None
    soup = None
    try:
        t0 = time.monotonic()
        resp = http.get(url)
        audit.ladezeit_s = round(time.monotonic() - t0, 2)
        audit.status_code = resp.status_code
        audit.final_url = resp.url
        audit.https = urlparse(resp.url).scheme == "https"
        audit.erreichbar = resp.status_code < 400 and "html" in resp.headers.get("Content-Type", "html")
        if audit.erreichbar:
            soup = analyse_html(resp.text, resp.url, audit)
        else:
            audit.fehler = f"HTTP {resp.status_code}"
    except PermissionError as e:
        audit.fehler = str(e)
    except requests.exceptions.SSLError:
        audit.fehler = "SSL-Zertifikat ungültig"
    except requests.RequestException as e:
        audit.fehler = type(e).__name__
    score(audit)
    return audit, soup
