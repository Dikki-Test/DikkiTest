import datetime as dt
from dataclasses import asdict
from pathlib import Path

import pytest

from agentur_leads.report import inhalt, pruefung
from agentur_leads.report.modelle import ReportLead
from agentur_leads.report.notion import MAX_GESAMT, MAX_OBEN, stapel

HEUTE = dt.date(2026, 9, 30)


def seite(url, **kw):
    basis = {"url": url, "status": 200, "titel": "Lotus Garten", "meta_beschreibung": False, "h1": 2, "woerter": 130,
             "bilder": 17, "bilder_ohne_alt": 16, "formular": False, "shortcode_reste": [], "iframes": [], "pdfs": [],
             "upload_jahre": [2015], "datei_jahre": [], "jsonld_typen": [], "oeffnungszeiten": True, "tel_links": 0,
             "query_url": True}
    return {**basis, **kw}


def fakten_restaurant(**ueberschreiben) -> dict:
    lead = ReportLead("Lotus Garten", "http://lotus-garten.de/", branche="Gastronomie", kategorie="Restaurant",
                      ort="Aachen", adresse="Markt 1, 52062 Aachen", google_rating=4.7, google_bewertungen=341,
                      instagram_vorhanden=False)
    f = {
        "lead": asdict(lead), "datum": HEUTE.isoformat(), "erreichbar": True, "website_url": "http://neu.lotus-garten.de/",
        "vorschaltseite": {"url": "http://lotus-garten.de/", "verzoegerung_s": 3.0, "ziel": "http://neu.lotus-garten.de",
                           "viewport": False},
        "startseite": {"mobil_viewport": True, "impressum": True, "telefon_klickbar": False, "copyright_jahr": 2016,
                       "title": "Lotus Garten | Vietnamesische Küche", "social_links": {"facebook": "https://facebook.com/lotus"}},
        "seiten": [seite("http://neu.lotus-garten.de/", h1=1, query_url=False),
                   seite("http://neu.lotus-garten.de/?page_id=30", shortcode_reste=["[contact_form]"]),
                   seite("http://neu.lotus-garten.de/?page_id=22", pdfs=[["Speisekarte.pdf", "https://x/speisekarte.pdf"]],
                         datei_jahre=[2023])],
        "varianten": {"eindeutig": False, "erreichbare_varianten": 6, "https_verfuegbar": True, "https_erzwungen": False},
        "server": {"php": "8.0", "php_eol": "2023-11-26", "php_veraltet": True, "cms": "WordPress", "cms_version": "7.1.2",
                   "cms_aktuell": "7.1.2", "cms_ist_aktuell": True, "admin_link": True,
                   "sicherheits_header": {"hsts": False, "csp": False, "frame": False, "nosniff": False, "referrer": False,
                                          "permissions": False}},
        "robots": {"robots_status": 404, "ki_bots": {"GPTBot": True, "ClaudeBot": True}, "sitemap": "http://x/?sitemap=index",
                   "llms_txt": False, "ua_test": {"GPTBot": 200}},
        "funktionen": {"speisekarte_art": "pdf", "reservierung": False, "bestellung": False, "leistungen": True},
        "datenschutz": {"url": "http://neu.lotus-garten.de/?page_id=32", "dsgvo": False, "im_impressum": True},
        "observatory": {"grade": "F", "score": 5},
        "browser": {"seiten": {"start_mobil": {}}, "fehler": "", "dienste_ohne_einwilligung": ["YouTube", "Google Maps"],
                    "cookies_dritt": [".youtube.com:YSC"], "unverschluesselt": ["http://x/1.jpg"] * 16,
                    "handy_ueberbreite": False, "screenshots": {}},
        "lighthouse": {"mobil": {"scores": {"performance": 44, "accessibility": 84, "best-practices": 72, "seo": 73},
                                 "lcp": 5.1, "fcp": 3.3, "cls": 0.38, "gewicht_kb": {"total": 3752, "image": 3675},
                                 "gewicht_ok": False, "fehlgeschlagen": {"accessibility": ["Bildelemente haben kein alt"]},
                                 "laeufe": [44, 54, 43], "version": "12.8.2", "quelle": "lokal gemessen"},
                       "desktop": {"scores": {"performance": 70}, "lcp": 1.8}},
        "ki_suche": None,
    }
    f.update(ueberschreiben)
    return f


def punkt(bereiche, text):
    return next(p for b in bereiche for p in b.punkte if p.text.startswith(text))


def test_bewertung_restaurant_mit_vorschaltseite():
    bereiche = pruefung.bewerte(fakten_restaurant(), HEUTE)
    namen = [b.name for b in bereiche]
    assert namen[1] == "Gäste-Erlebnis"
    assert bereiche[0].score == 44  # Lighthouse-Leistungswert
    assert punkt(bereiche, "Startadresse führt direkt").ok is False
    assert punkt(bereiche, "Speisekarte als eigene Seite").befund == "nur als PDF"
    assert punkt(bereiche, "Kontaktformular funktioniert").ok is False
    assert punkt(bereiche, "Alle Inhalte verschlüsselt").ok is False
    assert "nur als Abschnitt im Impressum" in punkt(bereiche, "Datenschutzerklärung").befund
    assert "YouTube" in punkt(bereiche, "Externe Dienste").befund
    assert punkt(bereiche, "PHP-Version").ok is False and "26.11.2023" in punkt(bereiche, "PHP-Version").befund
    assert punkt(bereiche, "WordPress aktuell").ok is True
    assert punkt(bereiche, "Aktuelle Fotos").ok is False  # 2015, das PDF von 2023 zählt nicht als Foto
    assert punkt(bereiche, "Instagram-Profil").ok is False
    assert punkt(bereiche, "KI-Stichprobe").ok is None  # ohne API-Schlüssel nicht geprüft
    gesamt = pruefung.gesamtnote(bereiche)
    assert 15 <= gesamt <= 45


def test_massnahmen_hebel_und_zusammenfassung():
    bereiche = pruefung.bewerte(fakten_restaurant(), HEUTE)
    gesamt = pruefung.gesamtnote(bereiche)
    ms = pruefung.massnahmen(bereiche, "Gastronomie", gesamt)
    keys = [m.key for m in ms]
    assert {"direkt", "kernfunktion", "https", "datenschutz", "relaunch"} <= set(keys)
    assert [m.nr for m in ms] == list(range(1, len(ms) + 1))
    assert [m.paket for m in ms] == sorted(m.paket for m in ms)  # nach Paketen sortiert nummeriert
    assert "Speisekarte als eigene Seite" in next(m.text for m in ms if m.key == "kernfunktion")
    kurz = pruefung.befunde_kurz(bereiche)
    assert kurz[0].startswith("Wer lotus-garten.de aufruft")
    assert len({pruefung.hebel(bereiche, ms)[i].key for i in range(3)}) == 3
    assert any("Bewertungen" in s for s in pruefung.staerken(bereiche))


def test_gute_website_ohne_lighthouse():
    f = fakten_restaurant(vorschaltseite=None, lighthouse={}, browser={"fehler": "Playwright nicht installiert"},
                          varianten={"eindeutig": True, "erreichbare_varianten": 4, "https_verfuegbar": True, "https_erzwungen": True})
    bereiche = pruefung.bewerte(f, HEUTE)
    assert bereiche[0].score is None and punkt(bereiche, "Ladezeit gemessen").ok is None
    assert punkt(bereiche, "Startadresse führt direkt").ok is True
    assert punkt(bereiche, "Verschlüsselung (HTTPS) erzwungen").ok is True
    assert not any(p.text.startswith("Externe Dienste") for b in bereiche for p in b.punkte)  # ohne Browser und Einbettungen


def test_bericht_als_markdown_und_notion_bloecke(tmp_path):
    f = fakten_restaurant()
    bereiche = pruefung.bewerte(f, HEUTE)
    gesamt = pruefung.gesamtnote(bereiche)
    ms = pruefung.massnahmen(bereiche, "Gastronomie", gesamt)
    bilder = {k: tmp_path / f"{k}.png" for k in ("gesamtnote", "bereiche", "wartezeit", "massnahmen")}
    bl = inhalt.baue_bericht(f, bereiche, gesamt, ms, bilder, "GG Studios", HEUTE)

    md = inhalt.als_markdown(bl, lambda p: f"file-upload://{p.stem}")
    assert "## 2. Ladezeit & Technik · 44/100" in md
    assert '<image src="file-upload://gesamtnote">' in md and "<columns>" in md
    assert "\\[contact_form\\]" in md  # Sonderzeichen escaped
    assert "`lotus-garten.de`" in md  # Domains als Code, damit Notion sie nicht verlinkt
    assert '## Methodik & Quellen {toggle="true"}' in md

    ids = {}
    bloecke = inhalt.als_notion_bloecke(bl, lambda p: ids.setdefault(p, f"id-{p.stem}"))
    assert set(ids.values()) == {f"id-{k}" for k in bilder}

    def tiefe(b, d=0):
        kinder = b[b["type"]].get("children", [])
        return max([d] + [tiefe(k, d + 1) for k in kinder])

    def rich_texts(b):
        inhalt_ = b[b["type"]]
        rt = list(inhalt_.get("rich_text", [])) + [c for zelle in inhalt_.get("cells", []) for c in zelle]
        return rt + [x for k in inhalt_.get("children", []) for x in rich_texts(k)]

    assert max(tiefe(b) for b in bloecke) <= 2  # Notion-API: max. zwei Ebenen je Anfrage
    assert all(len(t["text"]["content"]) <= 2000 for b in bloecke for t in rich_texts(b))
    tabellen = [b for b in bloecke if b["type"] == "table"]
    assert tabellen and all(len(r["table_row"]["cells"]) == t["table"]["table_width"]
                            for t in tabellen for r in t["table"]["children"])


def test_rich_text_formatierung():
    rt = inhalt.rich_text("**fett** und *kursiv* mit `code`", "red")
    assert [t["text"]["content"] for t in rt] == ["fett", " und ", "kursiv", " mit ", "code"]
    assert rt[0]["annotations"] == {"bold": True, "color": "red_background"}
    assert rt[4]["annotations"]["code"] is True
    assert len(inhalt.rich_text("x" * 4500)) == 3


def test_stapel_bleibt_unter_api_grenzen():
    absatz = {"type": "paragraph", "paragraph": {"rich_text": []}}
    tabelle = {"type": "table", "table": {"children": [{"type": "table_row", "table_row": {"cells": []}}] * 30}}
    teile = stapel([absatz] * 150 + [tabelle] * 20)
    assert all(len(t) <= MAX_OBEN for t in teile)
    zaehle = lambda b: 1 + len(b[b["type"]].get("children", []))  # noqa: E731
    assert all(sum(zaehle(b) for b in t) <= MAX_GESAMT for t in teile)
    assert sum(len(t) for t in teile) == 170


def test_diagramme_werden_erzeugt(tmp_path):
    pytest.importorskip("matplotlib")
    from agentur_leads.report import diagramme
    bereiche = pruefung.bewerte(fakten_restaurant(), HEUTE)
    ms = pruefung.massnahmen(bereiche, "Gastronomie", pruefung.gesamtnote(bereiche))
    for pfad in [diagramme.gesamtnote(26, tmp_path / "a.png"),
                 diagramme.bereiche([(b.name, b.score) for b in bereiche if b.score is not None], tmp_path / "b.png"),
                 diagramme.wartezeit(3.0, 5.1, 1.8, tmp_path / "c.png"),
                 diagramme.seitengewicht({"total": 3752, "image": 3675, "script": 49}, 3123, tmp_path / "d.png"),
                 diagramme.massnahmen_matrix(ms, tmp_path / "e.png"),
                 diagramme.vergleich([{"name": "A", "rating": 4.9, "reviews": 415}, {"name": "Lotus Garten", "rating": 4.7,
                                      "reviews": 341}, {"name": "B", "rating": 4.5, "reviews": 530}], "Lotus Garten", "T",
                                     tmp_path / "f.png")]:
        assert Path(pfad).stat().st_size > 5000


def test_ki_suchdienste_gesperrt_nur_bei_echter_sperre():
    def pruefe(robots):
        return punkt(pruefung.bewerte(fakten_restaurant(robots={"robots_status": 200, "sitemap": "", "llms_txt": False, **robots}),
                                      HEUTE), "KI-Suchdienste dürfen")

    gedrosselt = pruefe({"ki_bots": {"OAI-SearchBot": True, "GPTBot": True}, "ua_test": {"OAI-SearchBot": 429}})
    assert gedrosselt.ok is True  # 429 = nur gedrosselt, keine Sperre
    gesperrt = pruefe({"ki_bots": {"OAI-SearchBot": True, "GPTBot": True}, "ua_test": {"OAI-SearchBot": 403}})
    assert gesperrt.ok is False and gesperrt.befund == "gesperrt: OAI-SearchBot"
    # Wie beim Makler im Test: Suche erlaubt, nur Trainings-Crawler ausgesperrt – das ist kein Mangel
    training = pruefe({"ki_bots": {"OAI-SearchBot": True, "Claude-SearchBot": True, "GPTBot": False, "ClaudeBot": False},
                       "ua_test": {"GPTBot": 200}})
    assert training.ok is True and training.befund == "erlaubt; nur KI-Training gesperrt (ClaudeBot, GPTBot)"


def test_matrix_punkte_bleiben_im_quadranten():
    pytest.importorskip("matplotlib")
    from agentur_leads.report.diagramme import _freier_platz
    belegt: list[tuple[float, float]] = []
    for x, y in [(2.2, 3.3), (2.2, 3.3), (2.2, 3.3), (3.2, 4.7), (1.0, 2.8)]:
        nx, ny = _freier_platz(x, y, belegt)
        assert (nx < 3) == (x < 3) and (ny < 3) == (y < 3) and abs(nx - 3) >= 0.22 and abs(ny - 3) >= 0.3
        assert all(((nx - a) / 0.36) ** 2 + ((ny - b) / 0.5) ** 2 >= 1 for a, b in belegt)  # Kreise überlappen nicht
        belegt.append((nx, ny))
