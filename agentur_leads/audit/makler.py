"""Makler-spezifischer Check: Objektseiten, Fotoqualität, 360°-Rundgänge, (KI-)Staging."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..http import PoliteSession
from ..models import MaklerAudit
from . import fotos as fotomod

# Domains/Marker von 360°-/3D-Rundgang-Anbietern (in iframe/script/link/HTML)
RUNDGANG_ANBIETER = {
    "Matterport": ["matterport.com", "my.matterport"],
    "Ogulo": ["ogulo.com", "ogulo.de"],
    "immoviewer": ["immoviewer.com"],
    "FeelEstate": ["feelestate.de", "feel-estate"],
    "3DVista": ["3dvista"],
    "Kuula": ["kuula.co"],
    "Giraffe360": ["giraffe360"],
    "Nodalview": ["nodalview"],
    "Cupix": ["cupix.com"],
    "Momento360": ["momento360"],
    "Panoee": ["panoee"],
    "Theasys": ["theasys.io"],
    "Pano2VR": ["pano2vr"],
    "Immo-Rundgang (generisch)": ["virtual-tour", "virtualtour", "360-tour", "rundgang360"],
}
RUNDGANG_TEXT = re.compile(
    r"360\s?°|360-grad|3d-rundgang|virtuelle[rn]?\s+(rundgang|besichtigung|tour)|virtual\s+tour|online-besichtigung",
    re.I,
)
STAGING_TEXT = re.compile(
    r"(virtuelle[sn]?|digitale[sn]?|ki[- ]?)\s*(home[- ]?)?staging|virtual\s+staging|"
    r"ki[- ]gestützt\w*\s+(eingerichtet|möbliert|visualisiert)|beispielhaft\s+(eingerichtet|möbliert)|"
    r"(möblierung|einrichtung)\s+(ist\s+)?(digital|virtuell|visualisiert)|visualisierte?\s+einrichtung|home[- ]?staging",
    re.I,
)
DROHNE_TEXT = re.compile(r"drohne|luftaufnahme|luftbild|drone", re.I)
VIDEO_MARKER = re.compile(r"youtube\.com/embed|player\.vimeo|<video|objektvideo|immobilienvideo", re.I)
CRM_MARKER = {
    "onOffice": ["onoffice"],
    "FLOWFACT": ["flowfact"],
    "Propstack": ["propstack"],
    "justimmo": ["justimmo"],
    "immowelt-Widget": ["immowelt.de/expose", "immowelt.de/anbieter"],
    "ImmoScout24-Widget": ["immobilienscout24.de/anbieter", "immobilienscout24.de/expose", "is24"],
    "Estatesync/OpenImmo": ["openimmo", "estatesync"],
}
OBJEKT_LINK = re.compile(
    r"immobilien|objekte?|angebote?|expos[eé]|kaufen|mieten|wohnung|haus|referenz|verkauft|portfolio",
    re.I,
)
EXPOSE_LINK = re.compile(r"expos[eé]|objekt[-_/]?(nr|id)?[-_/]?\d+|/immobilie/|estate[-_]?id|obj(ekt)?id=", re.I)


def finde_objektseiten(soup: BeautifulSoup, base_url: str, max_seiten: int = 6) -> list[str]:
    host = urlparse(base_url).netloc
    uebersicht: list[str] = []
    exposes: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        if urlparse(href).netloc not in (host, "") and "onoffice" not in href and "flowfact" not in href:
            continue
        label = a.get_text(" ", strip=True) + " " + a["href"]
        if EXPOSE_LINK.search(label):
            if href not in exposes:
                exposes.append(href)
        elif OBJEKT_LINK.search(label) and href not in uebersicht and href.rstrip("/") != base_url.rstrip("/"):
            uebersicht.append(href)
    # Exposés sind am wertvollsten (dort sind die Fotos), dann Übersichten
    return (exposes[: max_seiten // 2 + 1] + uebersicht)[:max_seiten]


def scanne_html(html: str, audit: MaklerAudit) -> None:
    lower = html.lower()
    for anbieter, marker in RUNDGANG_ANBIETER.items():
        if any(m in lower for m in marker) and anbieter not in audit.rundgang_anbieter:
            audit.rundgang_anbieter.append(anbieter)
    if audit.rundgang_anbieter or RUNDGANG_TEXT.search(html):
        audit.rundgang_360 = True
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    for m in STAGING_TEXT.finditer(text):
        treffer = m.group(0).strip()
        if treffer.lower() not in (h.lower() for h in audit.staging_hinweise):
            audit.staging_hinweise.append(treffer)
    audit.staging = bool(audit.staging_hinweise)
    audit.drohne = audit.drohne or bool(DROHNE_TEXT.search(text))
    audit.video = audit.video or bool(VIDEO_MARKER.search(html))
    for crm, marker in CRM_MARKER.items():
        if any(m in lower for m in marker) and crm not in audit.crm_portal:
            audit.crm_portal.append(crm)


def audit_makler(http: PoliteSession, start_url: str, start_soup: BeautifulSoup | None,
                 max_seiten: int = 6, max_fotos: int = 12) -> MaklerAudit:
    audit = MaklerAudit()
    if start_soup is None:
        return audit
    scanne_html(str(start_soup), audit)
    audit.objektseiten = finde_objektseiten(start_soup, start_url, max_seiten)

    kandidaten: list[str] = fotomod.bild_urls(start_soup, start_url)
    expose_treffer = 0
    warteschlange = list(audit.objektseiten)
    besucht: set[str] = set()
    while warteschlange and len(besucht) < max_seiten:
        url = warteschlange.pop(0)
        if url in besucht:
            continue
        besucht.add(url)
        try:
            resp = http.get(url)
        except (requests.RequestException, PermissionError):
            continue
        if resp.status_code >= 400 or "html" not in resp.headers.get("Content-Type", "html"):
            continue
        scanne_html(resp.text, audit)
        soup = BeautifulSoup(resp.text, "html.parser")
        if EXPOSE_LINK.search(url):
            expose_treffer += 1
        else:
            # Übersichtsseite: verlinkte Exposés vorne einreihen (dort sind Fotos & Rundgänge)
            exposes = [u for u in finde_objektseiten(soup, resp.url or url, max_seiten)
                       if EXPOSE_LINK.search(u) and u not in besucht]
            warteschlange = exposes[:2] + warteschlange
            audit.objektseiten += [u for u in exposes[:2] if u not in audit.objektseiten]
        # Anzahl Objekte grob schätzen: Exposé-Links auf Übersichtsseiten
        expose_links = {a["href"] for a in soup.find_all("a", href=True) if EXPOSE_LINK.search(a["href"])}
        audit.anzahl_objekte_geschaetzt = max(audit.anzahl_objekte_geschaetzt, len(expose_links))
        neue = [u for u in fotomod.bild_urls(soup, resp.url) if u not in kandidaten]
        # Fotos von Exposé-Seiten zuerst prüfen – das sind die echten Objektfotos
        kandidaten = neue + kandidaten if EXPOSE_LINK.search(url) else kandidaten + neue
    audit.anzahl_objekte_geschaetzt = max(audit.anzahl_objekte_geschaetzt, expose_treffer)

    for url in kandidaten:
        if len(audit.fotos) >= max_fotos:
            break
        try:
            resp = http.get(url)
        except (requests.RequestException, PermissionError):
            continue
        if resp.status_code >= 400 or not resp.headers.get("Content-Type", "image").startswith("image"):
            continue
        fa = fotomod.analysiere_bild(url, resp.content)
        if fa:
            audit.fotos.append(fa)
    audit.fotos_geprueft = len(audit.fotos)
    audit.foto_score, audit.foto_probleme = fotomod.foto_score(audit.fotos)
    return audit
