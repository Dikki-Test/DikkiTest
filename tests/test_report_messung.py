import datetime as dt

from bs4 import BeautifulSoup

from agentur_leads.report import messung
from agentur_leads.report.browser import dienst, ordne_dienste
from agentur_leads.report.modelle import registrierte_domain, slug

from .conftest import FakeResponse, fixture

HEUTE = dt.date(2026, 9, 30)


def test_seite_erkennt_platzhalter_bilder_und_strukturdaten():
    s, _ = messung.analysiere_seite(fixture("restaurant_alt.html"), "http://lotus-garten.de/?page_id=30")
    assert s.shortcode_reste == ["[contact_form]"]
    assert s.h1 == 2 and not s.meta_beschreibung
    assert (s.bilder, s.bilder_ohne_alt) == (2, 1)
    assert s.upload_jahre == [2015] and s.datei_jahre == [2023]  # Foto-Jahre getrennt von Datei-Jahren
    assert "Restaurant" in s.jsonld_typen
    assert s.oeffnungszeiten and s.query_url and s.tel_links == 0
    assert s.iframes == ["https://www.youtube.com/embed/abc123"]


def test_meta_refresh_vorschaltseite():
    html = '<html><head><meta http-equiv="refresh" content="3; url=http://neu.lotus-garten.de"></head></html>'
    assert messung.meta_refresh(BeautifulSoup(html, "html.parser"), "http://lotus-garten.de/") == (3.0, "http://neu.lotus-garten.de")
    assert messung.meta_refresh(BeautifulSoup("<html></html>", "html.parser"), "http://x.de/") is None


def test_startseite_folgt_vorschaltseite(make_http):
    vorschalt = '<html><head><meta http-equiv="refresh" content="3; url=http://neu.lotus-garten.de/"></head><body><img src="logo.png"></body></html>'
    http = make_http({
        "http://lotus-garten.de/": FakeResponse("http://lotus-garten.de/", text=vorschalt),
        "http://neu.lotus-garten.de/": FakeResponse("http://neu.lotus-garten.de/", text=fixture("restaurant_alt.html")),
    })
    r = messung.startseite(http, "http://lotus-garten.de/")
    assert r["vorschaltseite"]["verzoegerung_s"] == 3.0 and not r["vorschaltseite"]["viewport"]
    assert r["website_url"] == "http://neu.lotus-garten.de/"
    assert r["startseite"]["mobil_viewport"] and r["startseite"]["impressum"]


def test_varianten_eindeutig_und_https_erzwungen(make_http):
    ziel = "https://www.dach-x.de/"
    routes = {u: FakeResponse(ziel) for u in ["http://www.dach-x.de/", "https://www.dach-x.de/",
                                                  "http://dach-x.de/", "https://dach-x.de/"]}
    v = messung.varianten(make_http(routes), "https://www.dach-x.de/")
    assert v["eindeutig"] and v["https_verfuegbar"] and v["https_erzwungen"]


def test_varianten_ohne_umleitung(make_http):
    routes = {u: FakeResponse(u) for u in ["http://x.de/", "https://x.de/", "http://www.x.de/", "https://www.x.de/"]}
    v = messung.varianten(make_http(routes), "http://x.de/")
    assert not v["eindeutig"] and v["https_verfuegbar"] and not v["https_erzwungen"]
    assert v["erreichbare_varianten"] == 4


def test_server_php_eol_wordpress_und_admin_link(make_http, monkeypatch):
    monkeypatch.setitem(messung._WP_AKTUELL, "v", "7.1.2")
    info = messung.server_und_cms({"x-powered-by": "PHP/8.0.30", "strict-transport-security": "max-age=1"},
                                  fixture("restaurant_alt.html"), make_http({}), HEUTE)
    assert info["php"] == "8.0" and info["php_veraltet"] and info["php_eol"] == "2023-11-26"
    assert info["cms"] == "WordPress" and info["cms_ist_aktuell"]
    assert info["admin_link"]
    assert info["sicherheits_header"]["hsts"] and not info["sicherheits_header"]["csp"]


def test_php_mit_support_ist_nicht_veraltet(make_http, monkeypatch):
    monkeypatch.setitem(messung._WP_AKTUELL, "v", "")
    assert not messung.server_und_cms({"x-powered-by": "PHP/8.3.12"}, "<html></html>", make_http({}), HEUTE)["php_veraltet"]


def test_funktionen_speisekarte_pdf_und_reservierung():
    s, _ = messung.analysiere_seite(fixture("restaurant_alt.html"), "http://lotus-garten.de/")
    f = messung.funktionen([vars(s)], fixture("restaurant_alt.html"))
    assert f["speisekarte_art"] == "pdf" and f["speisekarte_pdf"].endswith(".pdf")
    assert not f["reservierung"]
    mit = messung.funktionen([{"url": "https://x.de/speisekarte", "titel": "Speisekarte", "pdfs": [], "iframes": []}],
                             '<a href="https://www.quandoo.de/place/x">Tisch reservieren</a>')
    assert mit["speisekarte_art"] == "html" and mit["reservierung"]


def test_robots_ki_bots_und_llms_txt(make_http):
    robots = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\nSitemap: https://x.de/sitemap.xml\n"
    http = make_http({
        "https://x.de/robots.txt": FakeResponse("https://x.de/robots.txt", text=robots, content_type="text/plain"),
        "https://x.de/sitemap.xml": FakeResponse("https://x.de/sitemap.xml", text="<urlset/>", content_type="application/xml"),
    })
    info = messung.robots_und_ki(http, "https://x.de/")
    assert info["ki_bots"]["GPTBot"] is False and info["ki_bots"]["ClaudeBot"] is True
    assert info["sitemap"] == "https://x.de/sitemap.xml" and not info["llms_txt"]


def test_dienste_und_domains():
    assert dienst("https://www.google.com/maps/embed?pb=1") == "Google Maps"
    assert dienst("https://i.ytimg.com/vi/x.jpg") == "YouTube"
    assert dienst("https://cdn.beispiel.de/app.js") == ""
    assert ordne_dienste({"Google", "Google Fonts", "YouTube"}) == ["YouTube", "Google Fonts"]
    assert registrierte_domain("https://neu.viethaus-restaurant.de/x") == "viethaus-restaurant.de"
    assert registrierte_domain("http://www.shop.co.uk") == "shop.co.uk"
    assert slug("Viet Haus – Aachen") == "viet-haus-aachen"
