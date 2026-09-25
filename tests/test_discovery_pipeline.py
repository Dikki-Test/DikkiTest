import csv
import json

from agentur_leads import export
from agentur_leads.discovery import dedupe, osm
from agentur_leads.discovery.google_places import place_to_lead
from agentur_leads.models import HANDWERK, MAKLER, Lead
from agentur_leads.pipeline import audit_alle, lade_ergebnisse

from .conftest import FakeResponse, fixture


def test_osm_element_zu_lead():
    el = {"type": "node", "id": 1, "tags": {"name": "Tischlerei Brandt", "craft": "joiner",
                                            "addr:city": "Münster", "addr:postcode": "48149",
                                            "addr:street": "Hauptstr.", "addr:housenumber": "3",
                                            "website": "tischlerei-brandt.de",
                                            "contact:instagram": "https://instagram.com/brandt_holz"}}
    lead = osm.element_to_lead(el)
    assert lead.segment == HANDWERK and lead.gewerk == "Tischler/Schreiner"
    assert lead.website == "http://tischlerei-brandt.de"
    assert lead.instagram == "brandt_holz"
    assert lead.adresse == "Hauptstr. 3, 48149 Münster"
    assert osm.element_to_lead({"tags": {"office": "estate_agent", "name": "X"}}).segment == MAKLER


def test_overpass_query_enthaelt_segmente():
    q = osm.build_query(51.96, 7.62, 5000, [HANDWERK, MAKLER])
    assert 'office"="estate_agent' in q and "craft" in q and "around:5000" in q


def test_google_place_und_dedupe():
    g = place_to_lead({"id": "p1", "displayName": {"text": "Tischlerei Brandt"}, "rating": 4.8,
                       "userRatingCount": 51, "addressComponents": [{"longText": "Münster", "types": ["locality"]}]},
                      HANDWERK, "Tischler")
    o = Lead(name="Tischlerei Brandt", segment=HANDWERK, ort="Münster", website="http://brandt.de", quelle="osm")
    merged = dedupe([o, g])
    assert len(merged) == 1
    assert merged[0].website == "http://brandt.de" and merged[0].google_bewertungen == 51
    assert merged[0].quelle == "google,osm"
    assert place_to_lead({"businessStatus": "CLOSED_PERMANENTLY"}, HANDWERK, "x") is None


def test_pipeline_end_to_end(make_http, tmp_path):
    url = "http://elektro-mueller.de"
    http = make_http({url: FakeResponse(url, text=fixture("alt_handwerker.html"))})
    leads = [Lead(name="Elektro Müller", segment=HANDWERK, ort="Münster", website=url),
             Lead(name="Fliesen Özdemir", segment=HANDWERK, ort="Münster", quelle="osm")]
    out = tmp_path / "ergebnisse.json"
    ergebnisse = audit_alle(http, leads, out)
    assert len(ergebnisse) == 2 and len(lade_ergebnisse(out)) == 2
    # Zweiter Lauf überspringt bereits geprüfte Leads
    http.session.calls.clear()
    audit_alle(http, leads, out)
    assert http.session.calls == []

    export.export_csv(ergebnisse, tmp_path / "leads.csv")
    export.export_report(ergebnisse, tmp_path / "report.md", "Münster")
    with (tmp_path / "leads.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    namen = {r["Name"]: r for r in rows}
    assert "Website-Relaunch" in namen["Elektro Müller"]["Chancen"]
    assert namen["Fliesen Özdemir"]["Website"] == "—"
    assert "Website-Neubau" in namen["Fliesen Özdemir"]["Chancen"]
    assert "Ohne (funktionierende) Website: **1**" in (tmp_path / "report.md").read_text(encoding="utf-8")
    json.loads(out.read_text(encoding="utf-8"))
