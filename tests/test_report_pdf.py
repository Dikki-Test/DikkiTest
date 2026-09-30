import pytest

from agentur_leads.report import inhalt, pdf, pruefung
from agentur_leads.report.lauf import Bericht, lead_eigenschaften, veroeffentlichen
from agentur_leads.report.modelle import ReportLead
from agentur_leads.report.notion import lead_felder

from .test_report_bewertung import HEUTE, fakten_restaurant

ANGEBOT = {"1": {"dauer": "1 Woche", "preis": "ab 390 €"}, "2": {"dauer": "6 Wochen", "preis": "ab 2.900 €"},
           "3": {"dauer": "monatlich kündbar", "preis": "ab 290 € pro Monat"}}


def bloecke(ausgabe: str, **kw) -> list:
    f = fakten_restaurant()
    bereiche = pruefung.bewerte(f, HEUTE)
    gesamt = pruefung.gesamtnote(bereiche)
    ms = pruefung.massnahmen(bereiche, "Gastronomie", gesamt)
    return inhalt.baue_bericht(f, bereiche, gesamt, ms, {}, "GG Studios", HEUTE, ausgabe=ausgabe, **kw)


def test_pdf_fassung_ohne_interne_notiz_und_platzhalter():
    notion_md = inhalt.als_markdown(bloecke("notion"), lambda p: p.name)
    assert "(eintragen)" in notion_md and "Intern, vor dem Versand löschen" in notion_md
    h = pdf.als_html(bloecke("pdf"), oberzeile="GG Studios · Website-Check")
    assert "(eintragen)" not in h and "Intern" not in h and "persönlichen" not in h
    assert "in einem kurzen Gespräch" in h
    assert "<h1>Online-Check für Lotus Garten</h1>" in h and "GG Studios · Website-Check" in h
    assert '<span class="marke offen">✗ offen</span>' in h and h.count('class="neue-seite"') == 2
    assert '<table class="fest"><colgroup>' in h  # gleiche Spaltenbreiten in allen Prüftabellen
    assert '<span class="nowrap">lotus-garten.de</span>' in h
    assert not pdf._EMOJI.search(h)  # Emojis fehlen in Standardschriften


def test_angebot_und_kontakt():
    md = inhalt.als_markdown(bloecke("notion", angebot=ANGEBOT, kontakt="Max Muster · 0241 123"), lambda p: p.name)
    assert "Preis: ab 390 €" in md and "Dauer: 6 Wochen" in md
    assert "(eintragen)" not in md and "Intern" not in md and "Max Muster · 0241 123" in md
    h = pdf.als_html(bloecke("pdf", angebot=ANGEBOT))
    assert "Preis: ab 2.900 €" in h and "in einem kurzen Gespräch" not in h


def test_pdf_wird_erzeugt(tmp_path):
    pytest.importorskip("playwright.sync_api")
    try:
        pfad = pdf.erzeuge_pdf(bloecke("pdf"), tmp_path / "bericht.pdf", fusszeile="Online-Check Lotus Garten")
    except Exception as e:  # kein Chromium in dieser Umgebung
        pytest.skip(f"Chromium nicht verfügbar: {e}")
    daten = pfad.read_bytes()
    assert daten.startswith(b"%PDF") and 20_000 < len(daten) < pdf.MAX_BYTES


class FakeNotion:
    def __init__(self):
        self.aufrufe = []

    def hochladen(self, pfad, name=""):
        self.aufrufe.append(("hochladen", name or pfad.name))
        return "fu-pdf"

    def seite_anlegen(self, eltern_id, titel, icon, bloecke):
        self.aufrufe.append(("seite", eltern_id))
        return {"id": "s1", "url": "https://www.notion.so/s1"}


def test_veroeffentlichen_haengt_pdf_an_den_lead(tmp_path):
    lead = ReportLead("Lotus Garten", "http://lotus-garten.de/", notion_page_id="lead1")
    b = Bericht(lead=lead, ordner=tmp_path, fakten={"datum": "2026-09-30"}, gesamt=34, bloecke=[inhalt.P("x")],
                pdf=tmp_path / "bericht.pdf")
    b.pdf.write_bytes(b"%PDF-1.7")

    n = FakeNotion()
    erg = veroeffentlichen(b, n, "lead1")
    name = "Website-Check Lotus Garten 2026-09-30.pdf"
    assert erg == {"pdf_id": "fu-pdf", "url": ""} and n.aufrufe == [("hochladen", name)]  # keine Unterseite
    werte = lead_eigenschaften(b, erg["pdf_id"])
    assert werte["Report-PDF"] == {"files": [{"type": "file_upload", "file_upload": {"id": "fu-pdf"}, "name": name}]}
    assert werte["Report-Score"] == {"number": 34} and werte["Report-Datum"] == {"date": {"start": "2026-09-30"}}
    assert "Report" not in werte

    trocken = FakeNotion()
    assert veroeffentlichen(b, trocken, "lead1", trockenlauf=True) == {"pdf_id": "", "url": ""} and not trocken.aufrufe

    mit_seite = FakeNotion()
    assert veroeffentlichen(b, mit_seite, "lead1", mit_seite=True)["url"] == "https://www.notion.so/s1"
    assert ("seite", "lead1") in mit_seite.aufrufe
    assert "Report-PDF" in lead_felder() and "Report" not in lead_felder() and "Report" in lead_felder(mit_seite=True)
