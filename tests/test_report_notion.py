from types import SimpleNamespace as NS

import pytest

from agentur_leads.report.ki_suche import auswerten_antwort, fragen, genannt, ki_stichprobe
from agentur_leads.report.lauf import vergleichsgruppe
from agentur_leads.report.modelle import ReportLead
from agentur_leads.report.notion import Notion
from agentur_leads.report.quelle import bewertung_aus_text, lead_aus_notion, notion_filter, ort_aus_adresse


def rt(text):
    return [{"plain_text": text}]


NOTION_SEITE = {
    "id": "3ea8eea0-e22a-8116-9f3e-dde94402f2c4",
    "url": "https://www.notion.so/Viet-Haus-3ea8eea0e22a81169f3edde94402f2c4",
    "properties": {
        "Name": {"type": "title", "title": rt("Viet Haus")},
        "Website": {"type": "url", "url": "http://viethaus-restaurant.de/"},
        "Branche": {"type": "select", "select": {"name": "Gastronomie"}},
        "Fachrichtung": {"type": "rich_text", "rich_text": rt("Restaurant")},
        "Gewerk": {"type": "select", "select": None},
        "Adresse": {"type": "rich_text", "rich_text": rt("Rathausplatz 5, Aachen")},
        "KI-Einschätzung": {"type": "rich_text", "rich_text": rt("Google 4,7 ★ (341 Bewertungen). Website 1/10 …")},
        "Notiz": {"type": "rich_text", "rich_text": rt("Nachtlauf 29.09.2026 | Quelle: OpenStreetMap | Küche: asian")},
        "Instagram vorhanden": {"type": "select", "select": {"name": "nein"}},
        "Instagram-Handle": {"type": "rich_text", "rich_text": []},
        "Qualität": {"type": "select", "select": {"name": "✅ OK"}},
        "Report-Datum": {"type": "date", "date": None},
    },
}


def test_lead_aus_notion():
    lead = lead_aus_notion(NOTION_SEITE)
    assert (lead.name, lead.branche, lead.kategorie, lead.ort, lead.kueche) == \
           ("Viet Haus", "Gastronomie", "Restaurant", "Aachen", "asian")
    assert (lead.google_rating, lead.google_bewertungen) == (4.7, 341)
    assert lead.instagram_vorhanden is False and lead.notion_page_id.startswith("3ea8")
    geschlossen = {**NOTION_SEITE, "properties": {**NOTION_SEITE["properties"],
                                                  "Qualität": {"type": "select", "select": {"name": "❌ Geschlossen"}}}}
    assert notion_filter(NOTION_SEITE) and not notion_filter(geschlossen)


def test_hilfsfunktionen_quelle():
    assert ort_aus_adresse("Kamper Str. 19, 52064 Aachen") == "Aachen"
    assert bewertung_aus_text("Google 4.5 ★ (1.026 Bewertungen)") == (4.5, 1026)
    assert bewertung_aus_text("keine Angabe") == (None, None)


class FakeAntwort:
    def __init__(self, status=200, daten=None, headers=None):
        self.status_code, self._daten, self.headers, self.text = status, daten or {}, headers or {}, ""

    def json(self):
        return self._daten


class FakeNotionSession:
    def __init__(self, antworten):
        self.headers, self.aufrufe, self.antworten = {}, [], list(antworten)

    def request(self, methode, url, **kw):
        self.aufrufe.append((methode, url.removeprefix("https://api.notion.com/v1"), kw))
        return self.antworten.pop(0)


def test_notion_leads_paginiert():
    s = FakeNotionSession([FakeAntwort(daten={"results": [1, 2], "has_more": True, "next_cursor": "c1"}),
                           FakeAntwort(daten={"results": [3], "has_more": False})])
    assert Notion("t", session=s, pause_s=0).leads("ds1") == [1, 2, 3]
    assert s.aufrufe[1][2]["json"]["start_cursor"] == "c1"
    assert s.aufrufe[0][2]["json"]["filter"] == {"property": "Website", "url": {"is_not_empty": True}}
    assert s.headers["Notion-Version"] == "2026-03-11"


def test_notion_seite_in_stapeln_und_upload(tmp_path):
    bild = tmp_path / "a.png"
    bild.write_bytes(b"\x89PNG....")
    s = FakeNotionSession([FakeAntwort(daten={"id": "fu1"}), FakeAntwort(daten={"status": "uploaded"}),
                           FakeAntwort(daten={"id": "p1", "url": "https://notion.so/p1"}), FakeAntwort(), FakeAntwort(429, headers={"Retry-After": "0"}),
                           FakeAntwort()])
    n = Notion("t", session=s, pause_s=0)
    assert n.hochladen(bild) == "fu1"
    assert "files" in s.aufrufe[1][2] and s.aufrufe[1][1] == "/file_uploads/fu1/send"
    absatz = {"type": "paragraph", "paragraph": {"rich_text": []}}
    seite = n.seite_anlegen("lead1", "Website-Check", "📊", [absatz] * 200)
    assert seite["id"] == "p1"
    methoden = [(m, u) for m, u, _ in s.aufrufe[2:]]
    assert methoden[0] == ("POST", "/pages") and methoden[1:] == [("PATCH", "/blocks/p1/children")] * 3  # inkl. Wiederholung nach 429
    assert s.aufrufe[2][2]["json"]["parent"] == {"page_id": "lead1"}


def test_ki_antwort_auswerten():
    lead = ReportLead("Viet Haus", "https://neu.viethaus-restaurant.de/", branche="Gastronomie", ort="Aachen")
    content = [
        NS(type="server_tool_use"),
        NS(type="web_search_tool_result", content=[NS(url="https://www.tripadvisor.com/x"),
                                                   NS(url="https://viethaus-restaurant.de/")]),
        NS(type="web_search_tool_result", content=NS(type="web_search_tool_result_error", error_code="max_uses_exceeded")),
        NS(type="text", text="Das **VietHaus** in Richterich ist beliebt.", citations=[NS(url="https://yelp.com/biz/1")]),
        NS(type="text", text="\nEMPFEHLUNGEN: Good Morning Vietnam; Viet Haus; Minh Châu", citations=None),
    ]
    r = auswerten_antwort(content, lead)
    assert r["genannt"] and r["eigene_quelle"] and r["suchen"] == 1
    assert r["quellen"] == ["tripadvisor.com", "viethaus-restaurant.de", "yelp.com"]
    assert r["empfehlungen"] == ["Good Morning Vietnam", "Viet Haus", "Minh Châu"]
    assert "EMPFEHLUNGEN" not in r["antwort"]
    assert not genannt(lead, "Good Morning Vietnam und Minh Châu")


def test_ki_stichprobe_setzt_pausierte_antwort_fort(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    rollen, antworten = [], [
        NS(stop_reason="pause_turn", content=[NS(type="server_tool_use"), NS(type="web_search_tool_result",
                                                                             content=[NS(url="https://www.tripadvisor.de/x")])]),
        NS(stop_reason="end_turn", content=[NS(type="text", text="Viet Haus ist beliebt.\nEMPFEHLUNGEN: Viet Haus", citations=None)]),
    ] * 3  # drei Fragen, jede einmal pausiert

    class FakeClient:
        def __init__(self, *a, **kw):
            self.beta = NS(messages=NS(create=lambda **kw: rollen.append([m["role"] for m in kw["messages"]]) or antworten.pop(0)))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("KI_SUCHE_MODELL", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    lead = ReportLead("Viet Haus", "https://viethaus-restaurant.de/", branche="Gastronomie", kategorie="Restaurant",
                      kueche="vietnamese", ort="Aachen")
    r = ki_stichprobe(lead)
    assert r["modell"] == "claude-opus-5-5" and r["gesamt"] == 3 and r["allgemein_genannt"] == 2
    assert rollen[:2] == [["user"], ["user", "assistant"]]  # pausierter Teil wird angehängt
    assert r["fragen"][0]["quellen"] == ["tripadvisor.de"] and r["suchen"] == 3  # Suche aus dem pausierten Teil zählt mit


def test_ki_fragen_grammatik():
    viet = ReportLead("Viet Haus", "http://x.de", branche="Gastronomie", kategorie="Restaurant", kueche="vietnamese", ort="Aachen")
    praxis = ReportLead("Praxis Dr. Meier", "http://y.de", branche="Gesundheit", kategorie="Zahnarzt", ort="Aachen")
    dach = ReportLead("Sauer Bedachungen", "http://z.de", branche="Handwerk", kategorie="Dachdecker", ort="Aachen")
    assert fragen(viet)[0]["frage"] == "Ich suche ein vietnamesisches Restaurant in Aachen. Wen kannst du empfehlen?"
    assert fragen(viet)[1]["frage"] == "Wer ist das beste vietnamesische Restaurant in Aachen?"
    assert fragen(praxis)[1]["frage"] == "Wer ist die beste Zahnarzt-Praxis in Aachen?"
    assert fragen(dach)[0]["frage"].startswith("Ich suche einen Dachdecker")


def test_vergleichsgruppe():
    a = ReportLead("A", "http://a.de", branche="Gastronomie", kategorie="Restaurant", ort="Aachen", google_rating=4.9, google_bewertungen=415)
    b = ReportLead("B", "http://b.de", branche="Gastronomie", kategorie="Restaurant", ort="Aachen", google_rating=4.5, google_bewertungen=530)
    c = ReportLead("C", "http://c.de", branche="Handwerk", ort="Aachen", google_rating=4.0, google_bewertungen=20)
    ich = ReportLead("Ich", "http://i.de", branche="Gastronomie", kategorie="Restaurant", ort="Aachen", google_rating=4.7, google_bewertungen=341)
    gruppe = vergleichsgruppe(ich, [a, b, c, ich])
    assert [z["name"] for z in gruppe] == ["B", "A", "Ich"]
