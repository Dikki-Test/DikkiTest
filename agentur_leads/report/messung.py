"""HTTP-Messungen: Adressvarianten, Vorschaltseite, Crawl, Server/CMS, robots.txt/llms.txt, Datenschutz.

Alles läuft über PoliteSession (robots.txt, 1 Anfrage/Sekunde pro Host). Jede Funktion liefert
JSON-fähige dicts, damit die Messung als fakten.json gespeichert und später erneut bewertet werden kann.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections import deque
from dataclasses import asdict, dataclass, field
from urllib import robotparser
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..audit.website import analyse_html
from ..http import PoliteSession
from ..models import WebsiteAudit
from .modelle import registrierte_domain

log = logging.getLogger(__name__)

KI_BOTS = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "Claude-SearchBot", "PerplexityBot", "Google-Extended"]
# Sicherheitsupdates laut php.net/supported-versions (Ende des Security-Supports)
PHP_EOL = {
    "5": "2018-12-31", "7.0": "2019-01-10", "7.1": "2019-12-01", "7.2": "2020-11-30", "7.3": "2021-12-06",
    "7.4": "2022-11-28", "8.0": "2023-11-26", "8.1": "2025-12-31", "8.2": "2026-12-31", "8.3": "2027-12-31",
    "8.4": "2028-12-31", "8.5": "2029-12-31",
}
SICHERHEITS_HEADER = {
    "hsts": "strict-transport-security",
    "csp": "content-security-policy",
    "frame": "x-frame-options",
    "nosniff": "x-content-type-options",
    "referrer": "referrer-policy",
    "permissions": "permissions-policy",
}
DATEI_ENDUNG = re.compile(r"\.(jpe?g|png|gif|webp|svg|ico|pdf|zip|rar|mp4|mov|mp3|docx?|xlsx?|pptx?)$", re.I)
SHORTCODE = re.compile(
    r"\[(?:contact[-_ ]?form[^\]]{0,40}|wpforms[^\]]{0,40}|gravityforms?[^\]]{0,40}|ninja_forms?[^\]]{0,40}"
    r"|caldera_form[^\]]{0,40}|formidable[^\]]{0,40}|cf7[^\]]{0,40})\]", re.I)
ZEITSPANNE = re.compile(r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:uhr\s*)?[-–]\s*\d{1,2}(?:[:.]\d{2})?\s*uhr\b|\b\d{1,2}[:.]\d{2}\s*[-–]\s*\d{1,2}[:.]\d{2}\b", re.I)
OEFFNUNGSZEITEN = re.compile(r"öffnungszeit|bürozeit|sprechzeit|geschäftszeit|opening hours", re.I)
UPLOAD_JAHR = re.compile(r"/uploads/((?:19|20)\d{2})/")

# Branchen-Kernfunktionen: Muster über Linktexte, Links, Skripte und iFrames
FUNKTIONEN = {
    "speisekarte": re.compile(r"speise|speisen|menü|menu|\bkarte\b|gerichte|mittagstisch|getränkekarte", re.I),
    "reservierung": re.compile(r"reservier|tisch\s*buchen|opentable|quandoo|resmio|thefork|bookatable|formitable"
                               r"|gastronovi|aleno|tablein|zenchef", re.I),
    "bestellung": re.compile(r"lieferando|wolt\.com|ubereats|online[- ]?bestell|jetzt bestellen", re.I),
    "termin": re.compile(r"doctolib|jameda|samedi|terminland|dr-flex|etermin|online[- ]?termin|termin\s*(?:online\s*)?buchen"
                         r"|terminvereinbarung", re.I),
    "buchung": re.compile(r"treatwell|shore\.com|planity|salonkee|studiobookings|eversports|fresha|timify|etermin"
                          r"|calendly|online\s*buchen|jetzt buchen|termin\s*buchen", re.I),
    "leistungen": re.compile(r"leistung|service|angebot|behandlung|therapie|sortiment|unsere arbeit|was wir", re.I),
    "objekte": re.compile(r"objekt|immobilienangebot|\bangebote\b|kaufen|mieten|exposé|expose|onoffice|flowfact"
                          r"|propstack|immowelt|immobilienscout|immonet", re.I),
    "bewertung": re.compile(r"bewertung|wertermittlung|immobilie verkaufen|was ist meine", re.I),
}


@dataclass
class Seite:
    url: str
    status: int | None = None
    titel: str = ""
    meta_beschreibung: bool = False
    h1: int = 0
    woerter: int = 0
    bilder: int = 0
    bilder_ohne_alt: int = 0
    formular: bool = False
    shortcode_reste: list[str] = field(default_factory=list)
    iframes: list[str] = field(default_factory=list)
    pdfs: list[list[str]] = field(default_factory=list)  # [Linktext, URL]
    upload_jahre: list[int] = field(default_factory=list)  # aus Bild-URLs (…/uploads/2015/…)
    datei_jahre: list[int] = field(default_factory=list)  # aus verlinkten Dateien (PDFs usw.)
    jsonld_typen: list[str] = field(default_factory=list)
    oeffnungszeiten: bool = False
    tel_links: int = 0
    query_url: bool = False
    fehler: str = ""


def _jsonld_typen(soup: BeautifulSoup) -> list[str]:
    typen: list[str] = []

    def sammle(obj) -> None:
        if isinstance(obj, dict):
            t = obj.get("@type")
            for x in t if isinstance(t, list) else [t]:
                if isinstance(x, str) and x not in typen:
                    typen.append(x)
            for v in obj.values():
                sammle(v)
        elif isinstance(obj, list):
            for v in obj:
                sammle(v)

    for s in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            sammle(json.loads(s.string or s.get_text() or "{}"))
        except (ValueError, TypeError):
            continue
    return typen


def analysiere_seite(html: str, url: str, status: int | None = 200) -> tuple[Seite, BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    s = Seite(url=url, status=status)
    s.titel = (soup.title.get_text(strip=True) if soup.title else "")[:200]
    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    s.meta_beschreibung = bool(md and md.get("content", "").strip())
    s.h1 = len(soup.find_all("h1"))
    imgs = soup.find_all("img")
    s.bilder = len(imgs)
    s.bilder_ohne_alt = sum(1 for i in imgs if i.get("alt") is None)
    s.formular = any(f.find("textarea") or f.find("input", attrs={"type": "email"}) for f in soup.find_all("form"))
    s.iframes = [f.get("src", "") for f in soup.find_all("iframe") if f.get("src")]
    s.jsonld_typen = _jsonld_typen(soup)
    s.tel_links = len(soup.find_all("a", href=re.compile(r"^tel:", re.I)))
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if urlparse(href).path.lower().endswith(".pdf"):
            s.pdfs.append([a.get_text(" ", strip=True)[:80], href])
    bildquellen = " ".join(i.get("src", "") + " " + i.get("srcset", "") for i in imgs)
    s.upload_jahre = sorted({int(j) for j in UPLOAD_JAHR.findall(bildquellen)})
    s.datei_jahre = sorted({int(j) for j in UPLOAD_JAHR.findall(" ".join(x[1] for x in s.pdfs))})
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    s.woerter = len(text.split())
    s.shortcode_reste = sorted(set(m.group(0) for m in SHORTCODE.finditer(text)))[:5]
    s.oeffnungszeiten = bool(OEFFNUNGSZEITEN.search(text) or ZEITSPANNE.search(text))
    s.query_url = bool(re.search(r"[?&](page_id|p|id|cat|option|itemid)=", url, re.I))
    return s, soup


def meta_refresh(soup: BeautifulSoup, url: str) -> tuple[float, str] | None:
    """(Verzögerung in s, Ziel-URL) einer <meta http-equiv="refresh">-Weiterleitung, sonst None."""
    m = soup.find("meta", attrs={"http-equiv": re.compile("^refresh$", re.I)})
    if not m:
        return None
    inhalt = m.get("content", "")
    treffer = re.match(r"\s*(\d+(?:\.\d+)?)\s*[;,]?\s*(?:url\s*=\s*)?['\"]?([^'\"]*)", inhalt, re.I)
    if not treffer or not treffer.group(2).strip():
        return None
    return float(treffer.group(1)), urljoin(url, treffer.group(2).strip())


def _abrufen(http: PoliteSession, url: str) -> requests.Response | str:
    try:
        return http.get(url)
    except PermissionError:
        return "robots.txt verbietet Abruf"
    except requests.exceptions.SSLError:
        return "SSL-Zertifikat ungültig"
    except requests.RequestException as e:
        return type(e).__name__


def startseite(http: PoliteSession, url: str) -> dict:
    """Lädt die Start-URL, folgt einer Vorschaltseite (Meta-Refresh) und analysiert die eigentliche Startseite."""
    ergebnis: dict = {"start_url": url, "vorschaltseite": None, "erreichbar": False, "fehler": ""}
    r = _abrufen(http, url)
    if isinstance(r, str) or r.status_code >= 400 or "html" not in r.headers.get("Content-Type", "html"):
        ergebnis["fehler"] = r if isinstance(r, str) else f"HTTP {r.status_code}"
        return ergebnis
    soup = BeautifulSoup(r.text, "html.parser")
    ziel = meta_refresh(soup, r.url)
    if ziel and urldefrag(ziel[1])[0].rstrip("/") != urldefrag(r.url)[0].rstrip("/"):
        ergebnis["vorschaltseite"] = {
            "url": r.url, "verzoegerung_s": ziel[0], "ziel": ziel[1],
            "viewport": bool(soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)})),
            "zuletzt_geaendert": r.headers.get("Last-Modified", ""),
        }
        r2 = _abrufen(http, ziel[1])
        if not isinstance(r2, str) and r2.status_code < 400:
            r = r2
    audit = WebsiteAudit(url=url, erreichbar=True, status_code=r.status_code, final_url=r.url,
                         https=urlparse(r.url).scheme == "https")
    analyse_html(r.text, r.url, audit)
    ergebnis.update(erreichbar=True, website_url=r.url, startseite=asdict(audit),
                    header={k.lower(): v for k, v in r.headers.items()}, html=r.text)
    return ergebnis


def _interne_links(soup: BeautifulSoup, basis: str, host: str) -> list[str]:
    """Interne Links, Navigation/Kopf/Fuß zuerst."""
    def aus(knoten) -> list[str]:
        out = []
        for a in knoten.find_all("a", href=True):
            href = urldefrag(urljoin(basis, a["href"]))[0]
            p = urlparse(href)
            if p.scheme not in ("http", "https") or (p.hostname or "").removeprefix("www.") != host.removeprefix("www."):
                continue
            if DATEI_ENDUNG.search(p.path) or re.search(r"wp-admin|wp-login|/feed|replytocom|attachment_id|\?s=", href, re.I):
                continue
            out.append(href)
        return out

    vorne = [x for knoten in soup.find_all(["nav", "header", "footer"]) for x in aus(knoten)]
    reihenfolge = vorne + aus(soup)
    return list(dict.fromkeys(reihenfolge))


def crawl(http: PoliteSession, start_url: str, start_html: str, max_seiten: int = 15) -> list[dict]:
    host = urlparse(start_url).hostname or ""
    seite, soup = analysiere_seite(start_html, start_url)
    seiten = [seite]
    gesehen = {start_url.rstrip("/")}
    warteschlange = deque(_interne_links(soup, start_url, host))
    while warteschlange and len(seiten) < max_seiten:
        url = warteschlange.popleft()
        if url.rstrip("/") in gesehen:
            continue
        gesehen.add(url.rstrip("/"))
        r = _abrufen(http, url)
        if isinstance(r, str):
            seiten.append(Seite(url=url, fehler=r))
            continue
        if "html" not in r.headers.get("Content-Type", "html"):
            continue
        s, sp = analysiere_seite(r.text, r.url, r.status_code)
        seiten.append(s)
        if r.status_code < 400:
            warteschlange.extend(x for x in _interne_links(sp, r.url, host) if x.rstrip("/") not in gesehen)
    return [asdict(s) for s in seiten]


def varianten(http: PoliteSession, website_url: str) -> dict:
    """Prüft http/https und www/ohne www: Wird auf eine einzige verschlüsselte Adresse umgeleitet?"""
    host = urlparse(website_url).hostname or ""
    domain = registrierte_domain(website_url)
    hosts = list(dict.fromkeys([host, domain, "www." + domain]))
    ergebnisse = {}
    for h in hosts:
        for schema in ("http", "https"):
            url = f"{schema}://{h}/"
            r = _abrufen(http, url)
            ergebnisse[url] = {"fehler": r} if isinstance(r, str) else {"status": r.status_code, "ziel": r.url}
    ziele = {urldefrag(v["ziel"])[0].rstrip("/") for v in ergebnisse.values() if v.get("status", 999) < 400}
    http_haupt = ergebnisse.get(f"http://{host}/", {})
    https_ok = ergebnisse.get(f"https://{host}/", {}).get("status", 999) < 400
    return {
        "abrufe": ergebnisse,
        "erreichbare_varianten": sum(1 for v in ergebnisse.values() if v.get("status", 999) < 400),
        "ziele": sorted(ziele),
        "eindeutig": len(ziele) <= 1,
        "https_verfuegbar": https_ok,
        # erzwungen: http:// leitet auf https:// um (oder ist gar nicht erreichbar)
        "https_erzwungen": https_ok and (str(http_haupt.get("ziel", "")).startswith("https://") or "status" not in http_haupt),
    }


def server_und_cms(header: dict, html: str, http: PoliteSession, heute: dt.date | None = None) -> dict:
    heute = heute or dt.date.today()
    info: dict = {"server": header.get("server", ""), "x_powered_by": header.get("x-powered-by", "")}
    m = re.search(r"PHP/(\d+)\.(\d+)", info["x_powered_by"], re.I)
    if m:
        version = f"{m.group(1)}.{m.group(2)}"
        eol = PHP_EOL.get(version) or (PHP_EOL["5"] if int(m.group(1)) < 7 else None)
        info["php"] = version
        info["php_eol"] = eol
        info["php_veraltet"] = bool(eol and dt.date.fromisoformat(eol) < heute)
    soup = BeautifulSoup(html, "html.parser")
    gen = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
    gen_text = gen.get("content", "") if gen else ""
    wp = re.search(r"WordPress\s+(\d+(?:\.\d+)+)", gen_text, re.I)
    if wp or "wp-content" in html:
        info["cms"] = "WordPress"
        info["cms_version"] = wp.group(1) if wp else ""
        aktuell = wordpress_aktuell(http)
        info["cms_aktuell"] = aktuell
        if wp and aktuell:
            info["cms_ist_aktuell"] = _version_tupel(wp.group(1))[:2] >= _version_tupel(aktuell)[:2]
    elif gen_text:
        info["cms"] = gen_text[:60]
    info["admin_link"] = bool(soup.find("a", href=re.compile(r"wp-admin|wp-login\.php|/administrator/|/typo3/?$", re.I)))
    info["sicherheits_header"] = {k: h in header for k, h in SICHERHEITS_HEADER.items()}
    if not info["sicherheits_header"]["frame"]:
        info["sicherheits_header"]["frame"] = "frame-ancestors" in header.get("content-security-policy", "")
    return info


_WP_AKTUELL: dict[str, str] = {}


def wordpress_aktuell(http: PoliteSession) -> str:
    if "v" not in _WP_AKTUELL:
        try:
            d = http.api_get("https://api.wordpress.org/core/version-check/1.7/").json()
            _WP_AKTUELL["v"] = d["offers"][0]["current"]
        except Exception:
            _WP_AKTUELL["v"] = ""
    return _WP_AKTUELL["v"]


def _version_tupel(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def robots_und_ki(http: PoliteSession, website_url: str) -> dict:
    p = urlparse(website_url)
    basis = f"{p.scheme}://{p.netloc}"
    info: dict = {"robots_status": None, "ki_bots": {}, "sitemap": "", "llms_txt": False, "ua_test": {}}
    r = _abrufen(http, basis + "/robots.txt")
    text = ""
    if not isinstance(r, str):
        info["robots_status"] = r.status_code
        if r.status_code < 400 and "html" not in r.headers.get("Content-Type", "").lower():
            text = r.text
    rp = robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    info["ki_bots"] = {bot: rp.can_fetch(bot, website_url) for bot in KI_BOTS}
    sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text)
    for kandidat in sitemaps + [basis + x for x in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/?sitemap=index")]:
        rs = _abrufen(http, kandidat)
        if not isinstance(rs, str) and rs.status_code < 400 and "xml" in rs.headers.get("Content-Type", ""):
            info["sitemap"] = rs.url
            break
    rl = _abrufen(http, basis + "/llms.txt")
    info["llms_txt"] = (not isinstance(rl, str) and rl.status_code == 200
                        and "html" not in rl.headers.get("Content-Type", "").lower() and len(rl.text.strip()) > 20)
    # Blockiert der Server KI-Crawler schon am User-Agent (z.B. Bot-Schutz)? Je ein Abruf.
    for bot, ua in (("GPTBot", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)"),
                    ("ClaudeBot", "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)")):
        try:
            rb = http.session.get(website_url, headers={"User-Agent": ua}, timeout=http.timeout_s)
            info["ua_test"][bot] = rb.status_code
        except requests.RequestException as e:
            info["ua_test"][bot] = type(e).__name__
    return info


def funktionen(seiten: list[dict], html_start: str) -> dict:
    """Erkennt Branchen-Kernfunktionen (Speisekarte, Reservierung, Termin …) aus Links, Texten und Einbettungen."""
    soup = BeautifulSoup(html_start, "html.parser")
    linktexte = " ".join(f"{a.get_text(' ', strip=True)} {a.get('href', '')}" for a in soup.find_all("a", href=True))
    einbettungen = " ".join([s.get("src", "") for s in soup.find_all(["script", "iframe"])])
    alles = " ".join([linktexte, einbettungen] + [" ".join(s.get("iframes", [])) for s in seiten]
                     + [" ".join(x[0] + " " + x[1] for x in s.get("pdfs", [])) for s in seiten]
                     + [s.get("url", "") + " " + s.get("titel", "") for s in seiten])
    f = {k: bool(muster.search(alles)) for k, muster in FUNKTIONEN.items()}
    # Speisekarte: als eigene Seite (HTML) oder nur als PDF?
    pdf_karte = [x for s in seiten for x in s.get("pdfs", []) if FUNKTIONEN["speisekarte"].search(" ".join(x))]
    html_karte = [s["url"] for s in seiten if FUNKTIONEN["speisekarte"].search(s.get("url", "") + " " + s.get("titel", ""))
                  and not s.get("fehler")]
    f["speisekarte_art"] = "html" if html_karte else "pdf" if pdf_karte else ""
    f["speisekarte_pdf"] = pdf_karte[0][1] if pdf_karte else ""
    return f


def datenschutz(http: PoliteSession, html_start: str, basis_url: str, seiten: list[dict]) -> dict:
    soup = BeautifulSoup(html_start, "html.parser")
    link = next((urljoin(basis_url, a["href"]) for a in soup.find_all("a", href=True)
                 if re.search(r"datenschutz|privacy", a.get_text(" ", strip=True) + " " + a["href"], re.I)), "")
    info: dict = {"url": link, "dsgvo": None, "erwaehnt": [], "im_impressum": False}
    if not link:  # manchmal steht der Datenschutz nur als Abschnitt im Impressum
        link = next((urljoin(basis_url, a["href"]) for a in soup.find_all("a", href=True)
                     if re.search(r"impressum|imprint", a.get_text(" ", strip=True) + " " + a["href"], re.I)), "")
        info["im_impressum"] = bool(link)
    if not link:
        return info
    r = _abrufen(http, link)
    if isinstance(r, str) or r.status_code >= 400:
        return info
    text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
    if info["im_impressum"]:
        if not re.search(r"datenschutz", text, re.I):
            return {**info, "im_impressum": False}
        info["url"] = link
    info["dsgvo"] = bool(re.search(r"DSGVO|DS-GVO|Datenschutz-Grundverordnung|Art\.\s?(6|13)\b|GDPR", text))
    info["erwaehnt"] = [d for d in ("Google Analytics", "Google Maps", "YouTube", "Facebook", "Instagram", "Google Fonts",
                                    "Google Tag Manager", "Vimeo") if d.lower() in text.lower()]
    info["woerter"] = len(text.split())
    return info


def observatory(host: str, timeout: float = 90) -> dict:
    """Mozilla HTTP Observatory (API v2): Note und Punktzahl der Sicherheits-Header."""
    try:
        r = requests.post("https://observatory-api.mdn.mozilla.net/api/v2/scan", params={"host": host}, timeout=timeout)
        d = r.json()
        if d.get("error"):
            return {"fehler": str(d["error"])[:120]}
        return {k: d.get(k) for k in ("grade", "score", "tests_failed", "tests_passed", "tests_quantity", "details_url")}
    except (requests.RequestException, ValueError) as e:
        return {"fehler": type(e).__name__}
