"""PDF-Ausgabe: der Bericht als gestaltetes A4-Dokument (HTML → PDF mit Chromium über Playwright).

Bilder und Schriften werden eingebettet, das PDF braucht also kein Netz. Emojis gibt es in Standard-
Schriften nicht zuverlässig; Ergebnisse erscheinen deshalb als farbige Marken („erfüllt“, „offen“).
"""

from __future__ import annotations

import base64
import html
import io
import logging
import os
import re
from pathlib import Path

from .diagramme import FONTS
from .inhalt import Bild, Block, H, Hinweis, Liste, P, Spalten, Tabelle, Trenner, rich_text

log = logging.getLogger(__name__)
MAX_BYTES = 4_800_000  # Notion-Workspaces im Free-Plan erlauben 5 MB je Datei

FARBEN = {  # Hintergrund, Akzent
    "gray": ("#F3F4F6", "#9CA3AF"), "blue": ("#EEF2FF", "#4F46E5"), "green": ("#ECFDF5", "#16A34A"),
    "yellow": ("#FFFBEB", "#D97706"), "red": ("#FEF2F2", "#DC2626"), "purple": ("#F5F3FF", "#7C3AED"),
    "orange": ("#FFF7ED", "#EA580C"),
}
_EMOJI = re.compile("[\U0001F000-\U0001FAFF✅❌✔✖✉️]")  # ★, →, ✓ bleiben
_MARKE = {"✅": "ok", "❌": "offen", "–": "neutral"}
_DOMAIN = re.compile(r"(?<![\w@])((?:https?://)?(?:[\w-]+\.)+(?:de|com|net|org|eu|info|at|ch)(?:/[\w./?=&%-]*)?)(?![\w])")
# feste Spaltenbreiten, damit die Tabellen aller Abschnitte gleich aussehen
SPALTEN_BREITE = {
    ("Prüfpunkt", "Ergebnis", "Befund"): (38, 13, 49),
    ("Nr.", "Maßnahme", "Aufwand", "Wirkung", "Paket"): (5, 52, 10, 10, 23),
}
BILD_KLASSE = {"handy": "handy", "desktop": "desktop", "seitengewicht": "schmal", "massnahmen": "mittel",
               "lighthouse": "mittel", "ki_": "mittel", "vergleich": "mittel"}


def _schriften() -> str:
    def face(familie: str, pfad: Path, gewicht: int) -> str:
        daten = base64.b64encode(pfad.read_bytes()).decode()
        return (f"@font-face{{font-family:'{familie}';font-weight:{gewicht};"
                f"src:url(data:font/ttf;base64,{daten}) format('truetype');}}")

    css = [face("Inter", FONTS / "Inter-400.ttf", 400), face("Inter", FONTS / "Inter-700.ttf", 700)]
    try:  # Ersatzschrift für ★, → usw.; kommt mit matplotlib mit
        import matplotlib
        dejavu = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        css += [face("DejaVu Sans", dejavu / "DejaVuSans.ttf", 400), face("DejaVu Sans", dejavu / "DejaVuSans-Bold.ttf", 700)]
    except (ImportError, OSError):
        pass
    return "\n".join(css)


CSS = """
@page { size: A4; margin: 15mm 15mm 17mm 15mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: 'Inter', 'DejaVu Sans', sans-serif; color: #111827; font-size: 9.6pt; line-height: 1.45; margin: 0; }
h1 { font-size: 21pt; line-height: 1.15; margin: 0 0 1.5mm; letter-spacing: -0.01em; }
.oberzeile { font-size: 8pt; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #4F46E5; margin-bottom: 1.5mm; }
.nowrap { white-space: nowrap; }
h1 + p { color: #6B7280; font-size: 8.8pt; padding-bottom: 3.5mm; margin-bottom: 5mm; border-bottom: 2.5px solid #4F46E5; }
h2 { font-size: 14pt; margin: 7mm 0 3mm; padding-bottom: 1.5mm; border-bottom: 1.5px solid #E5E7EB; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 0 0 2mm; break-after: avoid; }
h2.neue-seite { break-before: page; margin-top: 0; }
p { margin: 0 0 2.5mm; }
ul, ol { margin: 0 0 3mm; padding-left: 5mm; }
li { margin-bottom: 1.3mm; }
strong { font-weight: 700; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 0.9em; background: #F3F4F6; padding: 0 0.8mm; border-radius: 1mm; }
figure { margin: 3mm 0 4.5mm; text-align: center; break-inside: avoid; }
figure img { max-width: 100%; max-height: 205mm; }
figure.handy img { max-height: 118mm; }
figure.desktop img { max-height: 108mm; }
figure.schmal img { max-width: 66%; }
figure.mittel img { max-width: 88%; }
figcaption { font-size: 8.3pt; color: #6B7280; margin-top: 1.5mm; }
.spalten { display: grid; gap: 5mm; align-items: start; margin: 1mm 0 4mm; break-inside: avoid; }
.spalten figure { margin: 0; }
.callout { border-radius: 2.5mm; padding: 3.2mm 4mm; border-left: 1.3mm solid; margin: 0 0 3mm; break-inside: avoid; }
.callout div + div { margin-top: 1mm; }
.callout .titel { font-weight: 700; margin-bottom: 1.5mm; }
table { width: 100%; border-collapse: collapse; font-size: 8.6pt; margin: 2mm 0 4mm; }
table.fest { table-layout: fixed; }
thead { display: table-header-group; }
th { text-align: left; font-weight: 700; color: #6B7280; border-bottom: 1.5px solid #D1D5DB; padding: 1.6mm 2mm; }
td { border-bottom: 1px solid #E5E7EB; padding: 1.6mm 2mm; vertical-align: top; }
tr { break-inside: avoid; }
.marke { display: inline-block; border-radius: 99px; padding: 0.2mm 2.2mm; font-weight: 700; font-size: 7.8pt; white-space: nowrap; }
.marke.ok { background: #DCFCE7; color: #166534; }
.marke.offen { background: #FEE2E2; color: #991B1B; }
.marke.neutral { background: #F3F4F6; color: #4B5563; }
.farbe-green { color: #15803D; } .farbe-red { color: #B91C1C; } .farbe-yellow { color: #B45309; }
hr { border: 0; border-top: 1px solid #E5E7EB; margin: 5mm 0; }
.methodik { font-size: 8.4pt; color: #4B5563; }
"""


def _text(t: str) -> str:
    """Escaped; Domains bleiben beim Zeilenumbruch zusammen."""
    teile, pos = [], 0
    for m in _DOMAIN.finditer(t):
        teile += [html.escape(t[pos:m.start()]), f'<span class="nowrap">{html.escape(m.group(1))}</span>']
        pos = m.end()
    return "".join(teile) + html.escape(t[pos:])


def _inline(text: str) -> str:
    teile = []
    for stueck in rich_text(_EMOJI.sub("", text).strip() if _EMOJI.search(text) else text):
        t = _text(stueck["text"]["content"])
        a = stueck.get("annotations", {})
        if a.get("code"):
            t = f"<code>{t}</code>"
        if a.get("bold"):
            t = f"<strong>{t}</strong>"
        if a.get("italic"):
            t = f"<em>{t}</em>"
        teile.append(t)
    return "".join(teile)


def _zelle(text: str, farbe: str) -> str:
    for zeichen, klasse in _MARKE.items():
        if text.startswith(zeichen + " "):
            symbol = {"ok": "✓ ", "offen": "✗ ", "neutral": ""}[klasse]
            return f'<span class="marke {klasse}">{symbol}{html.escape(text[len(zeichen) + 1:])}</span>'
    inhalt = _inline(text)
    return f'<span class="farbe-{farbe}">{inhalt}</span>' if farbe else inhalt


def _bild_daten(pfad: Path, max_breite: int = 1500) -> str:
    """Data-URI; Fotos/Screenshots werden verkleinert und als JPEG eingebettet, Diagramme bleiben PNG."""
    if pfad.suffix.lower() in (".jpg", ".jpeg"):
        try:
            from PIL import Image
            im = Image.open(pfad).convert("RGB")
            if im.width > max_breite:
                im = im.resize((max_breite, round(im.height * max_breite / im.width)), Image.LANCZOS)
            puffer = io.BytesIO()
            im.save(puffer, "JPEG", quality=80, optimize=True)
            return "data:image/jpeg;base64," + base64.b64encode(puffer.getvalue()).decode()
        except (ImportError, OSError):
            pass
    typ = "image/png" if pfad.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{typ};base64," + base64.b64encode(pfad.read_bytes()).decode()


def _klasse_fuer(pfad: Path) -> str:
    return next((klasse for teil, klasse in BILD_KLASSE.items() if teil in pfad.stem), "")


def _bloecke(bloecke: list[Block], max_breite: int) -> str:
    out: list[str] = []
    for b in bloecke:
        if isinstance(b, H):
            ebene = min(max(b.ebene, 1), 3)
            klasse = ' class="neue-seite"' if b.neue_seite else ""
            out.append(f"<h{ebene}{klasse}>{_inline(b.text)}</h{ebene}>")
            if b.toggle:
                out.append(f'<div class="methodik">{_bloecke(b.toggle, max_breite)}</div>')
        elif isinstance(b, P):
            out.append(f"<p>{_inline(b.text)}</p>")
        elif isinstance(b, Liste):
            tag = "ol" if b.nummeriert else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(x)}</li>" for x in b.punkte) + f"</{tag}>")
        elif isinstance(b, Hinweis):
            if b.intern:
                continue
            hg, akzent = FARBEN.get(b.farbe, FARBEN["gray"])
            zeilen = [f'<div class="titel">{_inline(z)}</div>' if i == 0 and b.titel else f"<div>{_inline(z)}</div>"
                      for i, z in enumerate(b.zeilen)]
            out.append(f'<div class="callout" style="background:{hg};border-color:{akzent}">{"".join(zeilen)}</div>')
        elif isinstance(b, Tabelle):
            breiten = SPALTEN_BREITE.get(tuple(b.kopf))
            spalten = "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in breiten) + "</colgroup>" if breiten else ""
            kopf = "".join(f"<th>{_inline(k)}</th>" for k in b.kopf)
            zeilen = "".join("<tr>" + "".join(f"<td>{_zelle(t, farbe)}</td>" for t, farbe in z) + "</tr>" for z in b.zeilen)
            klasse = ' class="fest"' if breiten else ""
            out.append(f"<table{klasse}>{spalten}<thead><tr>{kopf}</tr></thead><tbody>{zeilen}</tbody></table>")
        elif isinstance(b, Bild):
            if not b.pfad.exists():
                continue
            klasse = f' class="{_klasse_fuer(b.pfad)}"' if _klasse_fuer(b.pfad) else ""
            unterschrift = f"<figcaption>{_inline(b.unterschrift)}</figcaption>" if b.unterschrift else ""
            out.append(f'<figure{klasse}><img src="{_bild_daten(b.pfad, max_breite)}">{unterschrift}</figure>')
        elif isinstance(b, Spalten):
            anteile = b.anteile or [1] * len(b.spalten)
            raster = " ".join(f"{a}fr" for a in anteile)
            inhalt = "".join(f"<div>{_bloecke(spalte, max_breite)}</div>" for spalte in b.spalten)
            out.append(f'<div class="spalten" style="grid-template-columns:{raster}">{inhalt}</div>')
        elif isinstance(b, Trenner):
            out.append("<hr>")
    return "\n".join(out)


def als_html(bloecke: list[Block], titel: str = "Online-Check", max_breite: int = 1500, oberzeile: str = "") -> str:
    kopf = f'<div class="oberzeile">{html.escape(oberzeile)}</div>' if oberzeile else ""
    return (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><title>{html.escape(titel)}</title>'
            f"<style>{_schriften()}\n{CSS}</style></head><body>{kopf}{_bloecke(bloecke, max_breite)}</body></html>")


def erzeuge_pdf(bloecke: list[Block], pfad: Path, titel: str = "Online-Check", fusszeile: str = "",
                oberzeile: str = "") -> Path:
    """Schreibt das PDF; wird es für Notion zu groß, werden die Fotos stärker verkleinert."""
    from playwright.sync_api import sync_playwright

    fuss = ('<div style="font-family:Helvetica,Arial,sans-serif;font-size:7px;color:#9CA3AF;width:100%;'
            'padding:0 15mm;display:flex;justify-content:space-between">'
            f'<span>{html.escape(fusszeile)}</span>'
            '<span>Seite <span class="pageNumber"></span> von <span class="totalPages"></span></span></div>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None)
        try:
            seite = browser.new_page()
            for max_breite in (1500, 1100, 800):
                seite.set_content(als_html(bloecke, titel, max_breite, oberzeile), wait_until="load")
                seite.pdf(path=str(pfad), format="A4", print_background=True, display_header_footer=True,
                          header_template="<div></div>", footer_template=fuss,
                          margin={"top": "15mm", "bottom": "17mm", "left": "15mm", "right": "15mm"})
                if pfad.stat().st_size <= MAX_BYTES:
                    break
                log.info("PDF %s ist %d KB groß – Fotos werden stärker verkleinert", pfad.name, pfad.stat().st_size // 1024)
        finally:
            browser.close()
    return pfad
