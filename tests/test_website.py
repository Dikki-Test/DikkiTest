import datetime as dt

from agentur_leads.audit import website as web
from agentur_leads.models import WebsiteAudit

from .conftest import FakeResponse, fixture

HEUTE = dt.date(2026, 9, 25)


def test_alte_handwerker_seite_hat_viele_maengel():
    a = WebsiteAudit(url="http://elektro-mueller.de", erreichbar=True, https=False)
    web.analyse_html(fixture("alt_handwerker.html"), a.url, a)
    web.score(a, HEUTE)
    assert not a.mobil_viewport
    assert a.impressum and not a.datenschutz
    assert a.copyright_jahr == 2016
    assert "jQuery 1.x" in a.veraltete_technik
    assert "Tabellen-Layout" in a.veraltete_technik
    assert a.score < 50
    assert any("Smartphones" in m for m in a.maengel)


def test_moderne_seite_erkennt_social_und_wordpress():
    a = WebsiteAudit(url="https://schulte-dach.de", erreichbar=True, https=True, ladezeit_s=0.4)
    web.analyse_html(fixture("moderner_handwerker.html"), a.url, a)
    web.score(a, HEUTE)
    assert a.baukasten == "WordPress"
    assert a.social_links["instagram"] == "dachdeckerei.schulte"
    assert a.social_links["facebook"].endswith("/dachschulte")  # sharer-Link ignoriert
    assert a.kontaktformular and a.telefon_klickbar
    assert a.score >= 90


def test_nicht_erreichbar(make_http):
    http = make_http({"http://kaputt.de": FakeResponse("http://kaputt.de", status=500)})
    a, soup = web.audit_website(http, "http://kaputt.de")
    assert not a.erreichbar and soup is None
    assert a.score == 0 and "HTTP 500" in a.maengel[0]


def test_robots_txt_wird_beachtet(make_http):
    routes = {
        "https://x.de/robots.txt": FakeResponse("https://x.de/robots.txt", text="User-agent: *\nDisallow: /",
                                                content_type="text/plain"),
    }
    a, _ = web.audit_website(make_http(routes, robots=True), "https://x.de/")
    assert not a.erreichbar and "robots.txt" in a.fehler
