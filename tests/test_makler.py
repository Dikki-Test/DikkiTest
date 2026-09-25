from agentur_leads.audit import fotos as fotomod
from agentur_leads.audit import makler as maklermod
from agentur_leads.audit import website as web

from .conftest import FakeResponse, fixture, jpeg

BASE = "https://becker-immo.de"


def routes():
    img = "image/jpeg"
    return {
        BASE + "/": FakeResponse(BASE + "/", text=fixture("makler_start.html")),
        BASE + "/immobilien/": FakeResponse(BASE + "/immobilien/", text=fixture("makler_liste.html")),
        BASE + "/expose/1234": FakeResponse(BASE + "/expose/1234", text=fixture("makler_expose.html")),
        BASE + "/expose/1235": FakeResponse(BASE + "/expose/1235", text="<html><body>Haus</body></html>"),
        BASE + "/bilder/wohnzimmer.jpg": FakeResponse("", content=jpeg(640, 480, hell=60, muster=False),
                                                      content_type=img),
        BASE + "/bilder/kueche.jpg": FakeResponse("", content=jpeg(720, 1280, hell=60, muster=False),
                                                  content_type=img),
        BASE + "/img/hero.jpg": FakeResponse("", content=jpeg(1600, 900, hell=140), content_type=img),
    }


def test_makler_audit_findet_360_staging_crm_und_fotoprobleme(make_http):
    http = make_http(routes())
    w, soup = web.audit_website(http, BASE + "/")
    m = maklermod.audit_makler(http, w.final_url, soup)
    assert BASE + "/immobilien/" in m.objektseiten
    assert m.rundgang_360 and "Matterport" in m.rundgang_anbieter
    assert m.staging and m.staging_hinweise
    assert "onOffice" in m.crm_portal
    assert m.anzahl_objekte_geschaetzt >= 3
    assert m.fotos_geprueft == 3
    # Exposé-Fotos zuerst und die sind dunkel/klein/unscharf
    assert m.fotos[0].url.endswith("wohnzimmer.jpg")
    assert m.foto_score is not None and m.foto_score < 70
    assert any("zu dunkel" in p for p in m.foto_probleme)


def test_logos_werden_uebersprungen():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(fixture("makler_start.html"), "html.parser")
    urls = fotomod.bild_urls(soup, BASE + "/")
    assert urls == [BASE + "/img/hero.jpg"]


def test_srcset_nimmt_groesstes_bild():
    assert fotomod._groesste_srcset("a.jpg 480w, b.jpg 1920w, c.jpg 960w") == "b.jpg"


def test_gutes_foto_ohne_probleme():
    fa = fotomod.analysiere_bild("x", jpeg(2000, 1333, hell=140))
    assert fa is not None and fa.probleme == []
    score, probleme = fotomod.foto_score([fa])
    assert score == 100 and probleme == []


def test_kein_360_ohne_marker():
    m = maklermod.MaklerAudit()
    maklermod.scanne_html("<html><body>Schöne Wohnung, 3 Zimmer</body></html>", m)
    assert not m.rundgang_360 and not m.staging
