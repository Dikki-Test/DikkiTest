"""Orchestrierung: je Lead messen → bewerten → Diagramme → Bericht (PDF, Markdown, Notion-Blöcke) → optional veröffentlichen.

Veröffentlichen heißt: das PDF in der Spalte „Report-PDF“ des Leads anhängen, Report-Score und -Datum setzen;
mit mit_seite zusätzlich eine Notion-Unterseite mit dem Bericht anlegen.

Fortsetzbar: Messungen liegen je Lead in <out>/<slug>/fakten.json und werden wiederverwendet; bereits
veröffentlichte Berichte (veroeffentlicht.json bzw. Report-Datum in Notion) werden übersprungen.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from ..http import PoliteSession
from . import diagramme, inhalt, messung, pruefung
from .modelle import Bereich, Massnahme, ReportLead

log = logging.getLogger(__name__)
MAX_ALTER_TAGE = 14  # ältere Messungen werden neu erhoben, damit Berichte aktuell sind


@dataclass
class Optionen:
    out: Path = Path("output/berichte")
    agentur: str = "GG Studios"
    max_seiten: int = 15
    lighthouse_laeufe: int = 3
    lighthouse_schnell: bool = False  # erst 1 Messung, nur bei schwachen Werten lighthouse_laeufe
    browser: bool = True
    lighthouse: bool = True
    observatory: bool = True
    ki: bool = True
    neu_messen: bool = False
    datum: dt.date = field(default_factory=dt.date.today)
    pdf: bool = True
    mit_seite: bool = False  # zusätzlich eine Notion-Unterseite je Lead
    angebot: dict | None = None  # Dauer/Preis je Paket, siehe inhalt.baue_bericht
    kontakt: str = ""


@dataclass
class Bericht:
    lead: ReportLead
    ordner: Path
    fakten: dict = field(default_factory=dict)
    bereiche: list[Bereich] = field(default_factory=list)
    gesamt: int = 0
    massnahmen: list[Massnahme] = field(default_factory=list)
    bloecke: list = field(default_factory=list)
    fehler: str = ""
    notion_url: str = ""
    pdf: Path | None = None


def messen(lead: ReportLead, http: PoliteSession, ordner: Path, opt: Optionen) -> dict:
    """Alle Messungen für einen Lead; Ergebnis wird als fakten.json gespeichert."""
    f: dict = {"lead": asdict(lead), "datum": opt.datum.isoformat(), "fehler": []}
    start = messung.startseite(http, lead.website)
    html = start.pop("html", "")
    f.update(start)
    if not start.get("erreichbar"):
        return f
    web = start["website_url"]
    for name, schritt in [
        ("seiten", lambda: messung.crawl(http, web, html, opt.max_seiten)),
        ("varianten", lambda: messung.varianten(http, web)),
        ("server", lambda: messung.server_und_cms(start.get("header", {}), html, http, opt.datum)),
        ("robots", lambda: messung.robots_und_ki(http, web)),
    ]:
        try:
            f[name] = schritt()
        except Exception as e:  # eine fehlgeschlagene Messung darf den Bericht nicht verhindern
            log.warning("%s: Messung %s fehlgeschlagen: %s", lead.name, name, e)
            f["fehler"].append(f"{name}: {type(e).__name__}")
    # Moderne Browser wechseln selbst auf HTTPS, wenn es geht – dort messen wir auch
    mess_url = web.replace("http://", "https://", 1) if (f.get("varianten") or {}).get("https_verfuegbar") else web
    f["mess_url"] = mess_url
    f["funktionen"] = messung.funktionen(f.get("seiten", []), html)
    f["datenschutz"] = messung.datenschutz(http, html, web, f.get("seiten", []))
    if opt.observatory:
        from urllib.parse import urlparse
        f["observatory"] = messung.observatory(urlparse(web).hostname or "")
    if opt.browser:
        from .browser import browser_messung
        unterseiten = [s["url"] for s in f.get("seiten", [])[1:]
                       if any(d in " ".join(s.get("iframes", [])) for d in ("youtube", "google.com/maps", "vimeo"))]
        vs = (f.get("vorschaltseite") or {}).get("url", "")
        unterseiten = [u.replace("http://", "https://", 1) if mess_url.startswith("https") else u for u in unterseiten]
        f["browser"] = browser_messung(mess_url, ordner, unterseiten, vs)
    if opt.lighthouse:
        from .lighthouse import lighthouse
        f["lighthouse"] = lighthouse(mess_url, opt.lighthouse_laeufe, opt.lighthouse_schnell)
    if opt.ki:
        from .ki_suche import ki_stichprobe
        f["ki_suche"] = ki_stichprobe(lead)
    f.pop("header", None)
    return f


def bewerten_und_gestalten(b: Bericht, opt: Optionen, vergleich: list[dict] | None = None) -> None:
    f, o = b.fakten, b.ordner
    b.bereiche = pruefung.bewerte(f, opt.datum)
    b.gesamt = pruefung.gesamtnote(b.bereiche)
    b.massnahmen = pruefung.massnahmen(b.bereiche, b.lead.branche, b.gesamt)
    bilder: dict[str, Path] = {}
    bilder["gesamtnote"] = diagramme.gesamtnote(b.gesamt, o / "01_gesamtnote.png")
    bilder["bereiche"] = diagramme.bereiche([(x.name, x.score) for x in b.bereiche if x.score is not None], o / "02_bereiche.png")
    lh = f.get("lighthouse") or {}
    m, d = lh.get("mobil") or {}, lh.get("desktop") or {}
    if m.get("scores"):
        n = len(m.get("laeufe", []))
        titel = "Google Lighthouse – Handy" + (f" (Median aus {n} Messungen)" if n >= 3 else "")
        bilder["lighthouse"] = diagramme.lighthouse_ringe(m["scores"], d.get("scores", {}), titel, o / "04_lighthouse.png")
        if m.get("lcp") is not None:
            vs = f.get("vorschaltseite") or {}
            bilder["wartezeit"] = diagramme.wartezeit(vs.get("verzoegerung_s"), m["lcp"], d.get("lcp"), o / "03_wartezeit.png")
        if m.get("gewicht_kb", {}).get("total"):
            bilder["seitengewicht"] = diagramme.seitengewicht(m["gewicht_kb"], m.get("einsparung_bilder_kb", 0), o / "05_seitengewicht.png")
    screens = (f.get("browser") or {}).get("screenshots", {})
    if "screen_mobil" in screens:
        vs_pfad = Path(screens["screen_vorschalt_mobil"]) if "screen_vorschalt_mobil" in screens else None
        bilder["handy"] = diagramme.handy_collage(Path(screens["screen_mobil"]), o / "10_handy.jpg", vs_pfad,
                                                  (f.get("vorschaltseite") or {}).get("verzoegerung_s"))
    if "screen_desktop" in screens:
        bilder["desktop"] = diagramme.desktop_rahmen(Path(screens["screen_desktop"]), f.get("website_url", ""), o / "11_desktop.jpg")
    ki = f.get("ki_suche")
    if ki and ki.get("gesamt"):
        bilder["ki_nennungen"] = diagramme.ki_nennungen(ki, b.lead.name, o / "07_ki_nennungen.png")
        bilder["ki_quellen"] = diagramme.ki_quellen(ki, b.lead.domain, o / "06_ki_quellen.png")
    if vergleich and len(vergleich) >= 3:
        titel = f"Google-Bewertungen im Vergleich: {b.lead.kategorie or b.lead.branche} in {b.lead.ort}"
        bilder["vergleich"] = diagramme.vergleich(vergleich, b.lead.name, titel, o / "08_vergleich.png")
    if b.massnahmen:
        bilder["massnahmen"] = diagramme.massnahmen_matrix(b.massnahmen, o / "09_massnahmen.png")
    b.bloecke = inhalt.baue_bericht(f, b.bereiche, b.gesamt, b.massnahmen, bilder, opt.agentur, opt.datum,
                                    angebot=opt.angebot, kontakt=opt.kontakt)
    (o / "bericht.md").write_text(inhalt.als_markdown(b.bloecke, lambda p: p.name), encoding="utf-8")
    if opt.pdf:
        bl_pdf = inhalt.baue_bericht(f, b.bereiche, b.gesamt, b.massnahmen, bilder, opt.agentur, opt.datum,
                                     ausgabe="pdf", angebot=opt.angebot, kontakt=opt.kontakt)
        try:
            from . import pdf
            b.pdf = pdf.erzeuge_pdf(bl_pdf, o / "bericht.pdf", titel=f"Online-Check {b.lead.name}",
                                    fusszeile=f"Online-Check {b.lead.name} · {opt.agentur} · {opt.datum.strftime('%d.%m.%Y')}",
                                    oberzeile=f"{opt.agentur} · Website-Check")
        except Exception as e:  # z.B. Playwright/Chromium fehlt: der Bericht bleibt ohne PDF
            log.warning("PDF für %s nicht erstellt: %s", b.lead.name, e)


def erstelle_bericht(lead: ReportLead, http: PoliteSession, opt: Optionen, vergleich: list[dict] | None = None) -> Bericht:
    ordner = opt.out / lead.slug
    ordner.mkdir(parents=True, exist_ok=True)
    b = Bericht(lead=lead, ordner=ordner)
    pfad = ordner / "fakten.json"
    alt = json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() and not opt.neu_messen else {}
    if alt and (opt.datum - dt.date.fromisoformat(alt.get("datum", "1970-01-01"))).days <= MAX_ALTER_TAGE:
        b.fakten = alt  # fortgesetzter Lauf: frische Messung wiederverwenden
    else:
        b.fakten = messen(lead, http, ordner, opt)
        pfad.write_text(json.dumps(b.fakten, ensure_ascii=False, indent=1), encoding="utf-8")
    if not b.fakten.get("erreichbar"):
        b.fehler = f"Website nicht erreichbar ({b.fakten.get('fehler') or 'unbekannt'})"
        return b
    bewerten_und_gestalten(b, opt, vergleich)
    return b


def pdf_dateiname(b: Bericht) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', " ", b.lead.name).strip()
    return f"Website-Check {name} {b.fakten.get('datum', '')}".strip() + ".pdf"


def veroeffentlichen(b: Bericht, notion, eltern_id: str, trockenlauf: bool = False, mit_seite: bool = False) -> dict:
    """Lädt das PDF hoch und legt mit mit_seite die Berichtsseite unter eltern_id an.

    Gibt {"pdf_id": Upload-ID oder "", "url": Seiten-URL oder ""} zurück.
    """
    ergebnis = {"pdf_id": "", "url": ""}
    ids: dict[Path, str] = {}

    def upload(pfad: Path) -> str:
        if pfad not in ids:
            ids[pfad] = f"TROCKEN-{pfad.name}" if trockenlauf else notion.hochladen(pfad)
        return ids[pfad]

    if trockenlauf or mit_seite:
        bloecke = inhalt.als_notion_bloecke(b.bloecke, upload)
        (b.ordner / "notion_bloecke.json").write_text(json.dumps(bloecke, ensure_ascii=False, indent=1), encoding="utf-8")
    if trockenlauf:
        return ergebnis
    if b.pdf and b.pdf.exists():
        ergebnis["pdf_id"] = notion.hochladen(b.pdf, name=pdf_dateiname(b))
    if mit_seite and eltern_id:
        titel = f"Website-Check {b.lead.name} · {dt.date.fromisoformat(b.fakten['datum']).strftime('%d.%m.%Y')}"
        seite = notion.seite_anlegen(eltern_id, titel, "📊", bloecke)
        ergebnis["url"] = seite.get("url", "")
    (b.ordner / "veroeffentlicht.json").write_text(json.dumps(ergebnis), encoding="utf-8")
    return ergebnis


def lead_eigenschaften(b: Bericht, pdf_id: str = "", url: str = "") -> dict:
    """Werte für die Report-Spalten im Leads-Board (Notion-API-Format)."""
    werte: dict = {"Report-Score": {"number": b.gesamt}, "Report-Datum": {"date": {"start": b.fakten["datum"]}}}
    if pdf_id:
        werte["Report-PDF"] = {"files": [{"type": "file_upload", "file_upload": {"id": pdf_id}, "name": pdf_dateiname(b)}]}
    if url:
        werte["Report"] = {"url": url}
    return werte


def vergleichsgruppe(lead: ReportLead, alle: list[ReportLead], n: int = 5) -> list[dict]:
    """Bewertungen anderer Betriebe gleicher Branche und Stadt (aus den Lead-Daten) für den Vergleich."""
    if lead.google_rating is None or not lead.ort:
        return []
    andere = [x for x in alle if x is not lead and x.google_rating is not None and x.google_bewertungen
              and x.ort == lead.ort and x.branche == lead.branche and (x.kategorie == lead.kategorie or not lead.kategorie)]
    andere.sort(key=lambda x: -(x.google_bewertungen or 0))
    zeilen = [{"name": x.name, "rating": x.google_rating, "reviews": x.google_bewertungen} for x in andere[:n]]
    return zeilen + [{"name": lead.name, "rating": lead.google_rating, "reviews": lead.google_bewertungen or 0}]


def lauf(leads: list[ReportLead], http: PoliteSession, opt: Optionen, *, notion=None, eltern_id: str = "",
         veroeffentlichen_an: bool = False, trockenlauf: bool = False, parallel: int = 1,
         fortschritt: Callable[[int, int, Bericht], None] | None = None) -> list[Bericht]:
    opt.out.mkdir(parents=True, exist_ok=True)
    offen = [x for x in leads if opt.neu_messen or not (x.bericht_datum or (opt.out / x.slug / "veroeffentlicht.json").exists())]
    berichte: list[Bericht] = []

    def einer(lead: ReportLead) -> Bericht:
        try:
            return erstelle_bericht(lead, http, opt, vergleichsgruppe(lead, leads))
        except Exception as e:
            log.exception("Bericht für %s fehlgeschlagen", lead.name)
            return Bericht(lead=lead, ordner=opt.out / lead.slug, fehler=f"{type(e).__name__}: {e}")

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        futures = [pool.submit(einer, lead) for lead in offen]
        for i, fut in enumerate(as_completed(futures), 1):
            b = fut.result()
            ziel = b.lead.notion_page_id or (eltern_id if opt.mit_seite else "")
            soll = not b.fehler and (trockenlauf or (veroeffentlichen_an and notion is not None and ziel))
            if soll:
                try:
                    erg = veroeffentlichen(b, notion, b.lead.notion_page_id or eltern_id, trockenlauf, opt.mit_seite)
                    if not trockenlauf and b.lead.notion_page_id:
                        notion.seite_aktualisieren(b.lead.notion_page_id, lead_eigenschaften(b, erg["pdf_id"], erg["url"]))
                    b.notion_url = erg["url"] or (b.lead.notion_url if not trockenlauf else "")
                except Exception as e:
                    log.exception("Veröffentlichen für %s fehlgeschlagen", b.lead.name)
                    b.fehler = f"Notion: {e}"
            berichte.append(b)
            if fortschritt:
                fortschritt(i, len(offen), b)
    schreibe_uebersicht(berichte, opt.out / "uebersicht.csv")
    return berichte


def schreibe_uebersicht(berichte: list[Bericht], pfad: Path) -> None:
    bereiche = ["Ladezeit & Technik", "Erlebnis", "Sicherheit & Datenschutz", "Google-Sichtbarkeit (SEO)",
                "KI-Auffindbarkeit", "Social Media & Content"]
    neu = not pfad.exists()
    with pfad.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        if neu:
            w.writerow(["Datum", "Name", "Ort", "Branche", "Website", "Gesamtnote", *bereiche, "Größter Hebel",
                        "Ordner", "Notion", "Fehler"])
        for b in berichte:
            punkte = {("Erlebnis" if x.key == "erlebnis" else x.name): x.score for x in b.bereiche}
            top = pruefung.hebel(b.bereiche, b.massnahmen, 1) if b.bereiche else []
            w.writerow([b.fakten.get("datum", ""), b.lead.name, b.lead.ort, b.lead.branche, b.lead.website,
                        b.gesamt if b.bereiche else "", *[punkte.get(x, "") for x in bereiche],
                        top[0].text if top else "", str(b.ordner), b.notion_url, b.fehler])
