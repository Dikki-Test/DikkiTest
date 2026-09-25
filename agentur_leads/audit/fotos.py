"""Technische Foto-Qualität (ohne KI): Auflösung, Helligkeit, Schärfe, Format.

Das ist bewusst eine Heuristik – sie findet die typischen Makler-Fehler
(Handyfotos im Hochformat, zu dunkle Innenräume, unscharf, zu klein).
Für eine inhaltliche Bewertung (Perspektive, Aufgeräumtheit, Staging-Potenzial)
gibt es optional `ki_bewertung.py`.
"""

from __future__ import annotations

import io
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from PIL import Image, ImageFilter, ImageOps, ImageStat

from ..models import FotoAnalyse

MIN_BREITE = 1200  # darunter wirken Fotos in Exposés/Portalen pixelig
DUNKEL = 85  # mittlere Helligkeit (0-255) darunter = zu dunkel
HELL = 205  # darüber = ausgebrannt
UNSCHARF = 120  # Varianz der Kantenkarte bei 800px Breite

SKIP_PATTERN = re.compile(
    r"logo|icon|sprite|favicon|avatar|badge|siegel|banner-?ad|team|mitarbeiter|portrait|"
    r"placeholder|loading|spinner|flag|\.svg|\.gif",
    re.I,
)


def _groesste_srcset(srcset: str) -> str:
    best, best_w = "", -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            try:
                w = int(bits[1][:-1])
            except ValueError:
                w = 0
        if w > best_w:
            best, best_w = bits[0], w
    return best


def bild_urls(soup: BeautifulSoup, base_url: str, limit: int = 40) -> list[str]:
    """Kandidaten für Objektfotos (Logos, Icons, Teamfotos werden übersprungen)."""
    urls: list[str] = []
    for img in soup.find_all("img"):
        src = ""
        if img.get("srcset") or img.get("data-srcset"):
            src = _groesste_srcset(img.get("srcset") or img.get("data-srcset"))
        src = src or img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
        if not src or src.startswith("data:"):
            continue
        alt = img.get("alt", "") + " " + " ".join(img.get("class", []))
        if SKIP_PATTERN.search(src) or SKIP_PATTERN.search(alt):
            continue
        w, h = img.get("width"), img.get("height")
        try:
            if w and h and (int(w) < 200 or int(h) < 150):
                continue
        except ValueError:
            pass
        full = urljoin(base_url, src)
        if full not in urls:
            urls.append(full)
        if len(urls) >= limit:
            break
    # Auch Galerie-Links auf Originalbilder (Lightbox) mitnehmen
    for a in soup.find_all("a", href=re.compile(r"\.(jpe?g|webp|png)(\?|$)", re.I)):
        full = urljoin(base_url, a["href"])
        if full not in urls and not SKIP_PATTERN.search(full):
            urls.append(full)
        if len(urls) >= limit:
            break
    return urls


def analysiere_bild(url: str, daten: bytes) -> FotoAnalyse | None:
    try:
        img = Image.open(io.BytesIO(daten))
        img = ImageOps.exif_transpose(img)
    except Exception:
        return None
    breite, hoehe = img.size
    if breite < 300 or hoehe < 200:  # Thumbnails/Icons nicht werten
        return None
    grau = img.convert("L")
    helligkeit = ImageStat.Stat(grau).mean[0]
    # Schärfe auf normierter Größe messen, sonst sind große Bilder im Vorteil
    norm = grau.resize((800, max(1, int(800 * hoehe / breite))))
    kanten = norm.filter(ImageFilter.FIND_EDGES)
    schaerfe = ImageStat.Stat(kanten).var[0]

    fa = FotoAnalyse(url=url, breite=breite, hoehe=hoehe, helligkeit=round(helligkeit, 1),
                     schaerfe=round(schaerfe, 1), hochformat=hoehe > breite)
    if breite < MIN_BREITE:
        fa.probleme.append("niedrige Auflösung")
    if helligkeit < DUNKEL:
        fa.probleme.append("zu dunkel")
    elif helligkeit > HELL:
        fa.probleme.append("überbelichtet")
    if schaerfe < UNSCHARF:
        fa.probleme.append("unscharf/verwaschen")
    if fa.hochformat:
        fa.probleme.append("Hochformat (Handyfoto?)")
    return fa


def foto_score(fotos: list[FotoAnalyse]) -> tuple[int | None, list[str]]:
    """Aggregiert Einzelanalysen zu 0-100 und den häufigsten Problemen."""
    if not fotos:
        return None, []
    zaehler: dict[str, int] = {}
    abzug = 0.0
    gewichte = {"niedrige Auflösung": 30, "zu dunkel": 25, "überbelichtet": 15,
                "unscharf/verwaschen": 25, "Hochformat (Handyfoto?)": 15}
    for f in fotos:
        for p in f.probleme:
            zaehler[p] = zaehler.get(p, 0) + 1
            abzug += gewichte.get(p, 10)
    score = max(0, round(100 - abzug / len(fotos)))
    probleme = [f"{p} ({n}/{len(fotos)} Fotos)" for p, n in sorted(zaehler.items(), key=lambda x: -x[1])
                if n / len(fotos) >= 0.25]
    return score, probleme
