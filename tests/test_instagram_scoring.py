import datetime as dt

from agentur_leads.audit import instagram as ig
from agentur_leads.models import MAKLER, HANDWERK, InstagramAudit, Lead, LeadErgebnis, MaklerAudit, WebsiteAudit
from agentur_leads.scoring import bewerte

HEUTE = dt.datetime(2026, 9, 25, tzinfo=dt.timezone.utc)


def posts(tage: list[int]):
    return [{"timestamp": (HEUTE - dt.timedelta(days=t)).strftime("%Y-%m-%dT%H:%M:%S+0000"),
             "like_count": 20, "comments_count": 2} for t in tage]


def test_instagram_aktiv():
    data = {"business_discovery": {"followers_count": 1000, "media_count": 300,
                                   "media": {"data": posts([1, 5, 9, 14, 20, 28, 40])}}}
    a = ig.auswerten("x", data, HEUTE)
    assert a.beitraege_30_tage == 6 and a.tage_seit_letztem_post == 1
    assert a.aktivitaet == "sehr aktiv"
    assert a.engagement_rate == 2.2


def test_instagram_eingeschlafen():
    data = {"business_discovery": {"followers_count": 80, "media_count": 12, "media": {"data": posts([400, 500])}}}
    assert ig.auswerten("x", data, HEUTE).aktivitaet.startswith("eingeschlafen")


def test_instagram_ohne_token_nur_handle(make_http):
    a = ig.audit_instagram(make_http({}), "@meister_bau", "website")
    assert a.handle == "meister_bau" and "manuell" in a.aktivitaet


def test_handwerker_ohne_website_ist_a_lead():
    e = bewerte(LeadErgebnis(lead=Lead(name="Maler Klein", segment=HANDWERK, gewerk="Maler", ort="Telgte",
                                       quelle="google", google_rating=4.7, google_bewertungen=35),
                             instagram=InstagramAudit()))
    assert e.chancen[0].produkt == "Website-Neubau"
    assert e.prioritaet == "A"
    assert "Maler Telgte" in e.pitch


def test_makler_ohne_360_und_staging():
    e = LeadErgebnis(
        lead=Lead(name="Becker Immobilien", segment=MAKLER, website="https://b.de", quelle="osm"),
        website=WebsiteAudit(url="https://b.de", erreichbar=True, https=True, score=85),
        makler=MaklerAudit(foto_score=40, foto_probleme=["zu dunkel (4/6 Fotos)"]),
        instagram=InstagramAudit(handle="becker", aktivitaet="inaktiv (>2 Monate kein Post)",
                                 tage_seit_letztem_post=90),
    )
    produkte = [c.produkt for c in bewerte(e).chancen]
    assert {"Immobilienfotografie", "360°-Rundgänge", "KI-/Virtual-Staging", "Social-Media-Betreuung"} <= set(produkte)
    assert e.prioritaet == "A"


def test_gut_aufgestellter_betrieb_ist_c():
    e = bewerte(LeadErgebnis(
        lead=Lead(name="Top GmbH", segment=HANDWERK, website="https://top.de"),
        website=WebsiteAudit(erreichbar=True, score=95),
        instagram=InstagramAudit(handle="top", aktivitaet="aktiv", tage_seit_letztem_post=3),
    ))
    assert e.prioritaet == "C" and e.lead_score == 0
