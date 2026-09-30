"""Bewertung: aus den Messwerten (fakten) werden Prüfpunkte je Bereich, Punkte (0–100) und Maßnahmen.

Jeder Prüfpunkt ist automatisch aus den Messwerten ableitbar; was nicht gemessen werden konnte,
ist „nicht prüfbar“ (ok=None) und zählt nicht in die Punkte.
"""

from __future__ import annotations

import datetime as dt
import statistics

from .modelle import BEAUTY, FITNESS, GASTRO, GESUNDHEIT, HANDWERK, IMMOBILIEN, Bereich, Massnahme, Pruefpunkt

LOKALE_TYPEN = {"LocalBusiness", "Restaurant", "FoodEstablishment", "CafeOrCoffeeShop", "BarOrPub", "Bakery",
                "HomeAndConstructionBusiness", "Electrician", "Plumber", "RoofingContractor", "HVACBusiness",
                "GeneralContractor", "HousePainter", "Locksmith", "RealEstateAgent", "Dentist", "Physician",
                "MedicalBusiness", "MedicalClinic", "Physiotherapy", "HealthAndBeautyBusiness", "BeautySalon",
                "HairSalon", "NailSalon", "DaySpa", "ExerciseGym", "SportsActivityLocation", "ProfessionalService",
                "Store", "AutoRepair", "MovingCompany", "LegalService", "AccountingService", "Optician"}
GUTE_NOTEN = {"A+", "A", "A-", "B+", "B", "B-"}

# key -> (Text, Aufwand 1–5, Wirkung 1–5, Paket, Nutzen)
MASSNAHMEN = {
    "direkt": ("Adresse direkt zur Website leiten, Vorschaltseite entfernen", 1.0, 4.6, 1,
               "{Kunden} landen sofort auf Ihrer Website statt vor einer Warteseite."),
    "https": ("HTTPS erzwingen und alle Inhalte verschlüsselt laden", 1.3, 3.8, 1,
              "Kein „Nicht sicher“-Hinweis mehr im Browser."),
    "kontakt": ("Telefonnummer antippbar machen, Kontakt-Button gut sichtbar", 1.2, 4.2, 1,
                "Anrufen oder anfragen mit einem Fingertipp."),
    "formular": ("Kontaktformular reparieren oder ersetzen", 1.0, 2.8, 1, "Anfragen kommen wieder an."),
    "tempo": ("Bilder verkleinern (WebP), Ladezeit und Layout-Sprünge beheben", 1.8, 3.4, 1,
              "Schnellere Seite, weniger Absprünge, besseres Google-Ranking."),
    "seo_basis": ("Seitentitel, Beschreibungen, Überschriften und Bildtexte optimieren", 2.2, 3.3, 1,
                  "Bessere Darstellung in den Google-Ergebnissen."),
    "seo_technik": ("Eine eindeutige Adresse, sprechende URLs, Sitemap und robots.txt", 2.0, 2.9, 1,
                    "Google bündelt alle Signale auf eine Adresse."),
    "ki_daten": ("Unternehmensdaten für Google und KI (Schema.org) und llms.txt ergänzen", 1.8, 4.0, 1,
                 "ChatGPT & Co. verstehen Angebot, Adresse und Öffnungszeiten."),
    "sicherheit": ("Sicherheits-Header setzen, Admin-Link entfernen", 1.3, 2.3, 1, "Weniger Angriffsfläche."),
    "software": ("CMS und PHP auf aktuelle Versionen bringen", 1.5, 2.6, 1, "Bekannte Sicherheitslücken werden geschlossen."),
    "kernfunktion": ("", 3.2, 4.7, 2, ""),  # Text/Nutzen je Branche, siehe KERNFUNKTION
    "datenschutz": ("Impressum und Datenschutz aktualisieren, externe Dienste erst nach Einwilligung", 2.6, 3.7, 2,
                    "Weniger Abmahnrisiko."),
    "inhalte": ("Inhalte ausbauen: Leistungen, Ort, Öffnungszeiten, aktuelle Infos", 2.8, 3.8, 2,
                "Mehr Gründe für Google und {Kunden}, Sie zu wählen."),
    "relaunch": ("Neue Website: modern und fürs Handy gebaut", 4.7, 4.9, 2, "Ein Auftritt, der zu Ihrem Ruf passt."),
    "profile": ("Google-Profil und Verzeichnisse pflegen, mehr Bewertungen sammeln", 2.4, 4.4, 3,
                "Mehr Sichtbarkeit bei Google Maps und in KI-Antworten."),
    "social": ("Neue Fotos und Reels, Instagram aufbauen", 4.0, 4.4, 3, "Neue {Kunden} über Bilder und Videos gewinnen."),
}
KERNFUNKTION = {
    GASTRO: ("Speisekarte als eigene Seite, Buttons „Tisch reservieren“ und „Bestellen“",
             "Gäste finden Ihre Gerichte und reservieren direkt."),
    GESUNDHEIT: ("Online-Terminbuchung einbinden und Leistungen beschreiben", "Termine rund um die Uhr, weniger Anrufe."),
    BEAUTY: ("Online-Buchung einbinden, Leistungen und Preise zeigen", "Buchungen rund um die Uhr."),
    FITNESS: ("Online-Buchung einbinden, Kurse und Preise zeigen", "Buchungen rund um die Uhr."),
    HANDWERK: ("Leistungsseiten mit Anfrageformular und Referenzen", "Mehr passende Anfragen, weniger Rückfragen."),
    IMMOBILIEN: ("Objekte und Bewertungsanfrage prominent auf der Website", "Mehr Eigentümer-Anfragen."),
}
PAKETE = {1: "Paket 1 · Sofort-Fix", 2: "Paket 2 · Neue Website", 3: "Paket 3 · Sichtbarkeit & Content"}


def kunden(branche: str) -> str:
    return {GASTRO: "Gäste", GESUNDHEIT: "Patienten"}.get(branche, "Kunden")


def _de(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def _anteil(n: int, gesamt: int) -> float:
    return n / gesamt if gesamt else 0.0


def bewerte(f: dict, heute: dt.date | None = None) -> list[Bereich]:
    heute = heute or dt.date.today()
    lead = f["lead"]
    branche = lead.get("branche", "")
    k = kunden(branche)
    seiten = [s for s in f.get("seiten", []) if not s.get("fehler") and (s.get("status") or 200) < 400]
    start = seiten[0] if seiten else {}
    sa = f.get("startseite", {})
    lh_m = (f.get("lighthouse") or {}).get("mobil") or {}
    lh_d = (f.get("lighthouse") or {}).get("desktop") or {}
    lh_ok = bool(lh_m.get("scores"))
    br = f.get("browser") or {}
    br_ok = bool(br.get("seiten")) and not br.get("fehler")
    var = f.get("varianten") or {}
    srv = f.get("server") or {}
    rob = f.get("robots") or {}
    fn = f.get("funktionen") or {}
    ds = f.get("datenschutz") or {}
    ki = f.get("ki_suche")
    vs = f.get("vorschaltseite")

    # --- Ladezeit & Technik -------------------------------------------------------------
    t = Bereich("technik", "Ladezeit & Technik",
                erklaerung="Die Punktzahl ist der Lighthouse-Leistungswert auf dem Handy." if lh_ok else "")
    if lh_ok:
        lcp, fcp, cls = lh_m.get("lcp"), lh_m.get("fcp"), lh_m.get("cls")
        g = lh_m.get("gewicht_kb", {})
        gesamt_kb, bilder_kb = g.get("total", 0), g.get("image", 0)
        t.score_override = lh_m["scores"].get("performance")
        t.punkte += [
            Pruefpunkt("Hauptinhalt auf dem Handy nach höchstens 2,5 s sichtbar", lcp is not None and lcp <= 2.5,
                       f"{_de(lcp)} s (Labormessung)" if lcp else "", 4, "tempo",
                       kurz=f"Auf dem Handy dauert es {_de(lcp)} s, bis der Hauptinhalt erscheint – Google empfiehlt höchstens 2,5 s." if lcp else "",
                       gut="Die Seite lädt auf dem Handy zügig."),
            Pruefpunkt("Erster Inhalt nach höchstens 1,8 s", fcp is not None and fcp <= 1.8, f"{_de(fcp)} s" if fcp else "", 2, "tempo"),
            Pruefpunkt("Seite springt beim Laden nicht (CLS ≤ 0,1)", cls is not None and cls <= 0.1,
                       _de(cls, 2) if cls is not None else "", 2, "tempo"),
            Pruefpunkt("Datenmenge laut Lighthouse im grünen Bereich", bool(lh_m.get("gewicht_ok")),
                       f"{_de(gesamt_kb / 1024)} MB, davon {round(100 * bilder_kb / gesamt_kb)} % Bilder" if gesamt_kb else "",
                       2, "tempo"),
        ]
        if lh_d.get("lcp") is not None:
            t.punkte.append(Pruefpunkt("Computer: Hauptinhalt nach höchstens 2,5 s", lh_d["lcp"] <= 2.5,
                                       f"{_de(lh_d['lcp'])} s", 1, "tempo"))
    else:
        t.punkte.append(Pruefpunkt("Ladezeit gemessen", None, "Lighthouse nicht verfügbar"))

    # --- Kunden-Erlebnis ------------------------------------------------------------------
    e = Bereich("erlebnis", f"{k}-Erlebnis")
    startdomain = lead.get("website", "").split("//")[-1].split("/")[0]
    e.punkte.append(Pruefpunkt(
        "Startadresse führt direkt zur Website", not vs,
        f"Vorschaltseite leitet erst nach {_de(vs['verzoegerung_s'], 0)} s weiter" + ("" if vs.get("viewport") else ", nicht fürs Handy angepasst")
        if vs else "direkt", 5 if vs else 1, "direkt",
        kurz=f"Wer {startdomain} aufruft, sieht zuerst {_de(vs['verzoegerung_s'], 0)} Sekunden lang eine Vorschaltseite." if vs else ""))
    e.punkte += _kernfunktionen(branche, fn, seiten, k)
    tel = any(s.get("tel_links") for s in seiten) or sa.get("telefon_klickbar", False)
    e.punkte.append(Pruefpunkt("Telefonnummer auf dem Handy antippbar", tel,
                               "antippbar" if tel else "Nummer steht als reiner Text da", 3, "kontakt",
                               kurz="Die Telefonnummer lässt sich auf dem Handy nicht antippen.",
                               gut="Die Telefonnummer ist auf dem Handy antippbar."))
    reste = sorted({r for s in seiten for r in s.get("shortcode_reste", [])})
    formular = any(s.get("formular") for s in seiten)
    e.punkte.append(Pruefpunkt(
        "Kontaktformular funktioniert", False if reste else (True if formular else None),
        f"statt Formular steht „{reste[0]}“ auf der Seite" if reste else ("Formular vorhanden" if formular else "kein Formular"),
        4 if reste else 2, "formular",
        kurz=f"Auf der Website steht statt eines Kontaktformulars nur der Platzhalter „{reste[0]}“." if reste else ""))
    oz = any(s.get("oeffnungszeiten") for s in seiten)
    e.punkte.append(Pruefpunkt("Öffnungs- bzw. Erreichbarkeitszeiten sichtbar", oz, "vorhanden" if oz else "nicht gefunden",
                               2, "inhalte", gut="Öffnungszeiten sind auf der Website zu finden."))
    viewport = sa.get("mobil_viewport", False)
    ueberbreit = br.get("handy_ueberbreite", False) if br_ok else False
    e.punkte.append(Pruefpunkt(
        "Website passt sich dem Handy an", viewport and not ueberbreit,
        "responsives Layout" if viewport and not ueberbreit else ("kein Handy-Layout (Viewport fehlt)" if not viewport
                                                                 else "Seite ist breiter als der Handy-Bildschirm"),
        4, "relaunch" if not viewport else "tempo",
        kurz="Die Website ist nicht fürs Handy gebaut – dort kommen heute die meisten Besucher her." if not viewport else "",
        gut="Die Website passt sich dem Handy an."))
    jahre = ([j for s in seiten for j in s.get("upload_jahre", []) + s.get("datei_jahre", [])]
             + ([sa["copyright_jahr"]] if sa.get("copyright_jahr") else []))
    neuestes = max(jahre) if jahre else None
    e.punkte.append(Pruefpunkt(
        "Aktuelle Inhalte", None if neuestes is None else neuestes >= heute.year - 1,
        f"neuestes erkennbares Jahr: {neuestes}" if neuestes else "nicht erkennbar", 3, "inhalte",
        kurz=f"Die neuesten erkennbaren Inhalte stammen von {neuestes}." if neuestes and neuestes < heute.year - 1 else ""))
    if lh_ok:
        a11y = lh_m["scores"].get("accessibility", 0)
        fehl = (lh_m.get("fehlgeschlagen") or {}).get("accessibility", [])
        e.punkte.append(Pruefpunkt("Barrierefreiheit laut Lighthouse mindestens 90", a11y >= 90,
                                   f"{a11y}/100" + (f": {fehl[0]}" if fehl and a11y < 90 else ""), 1, "seo_basis"))

    # --- Sicherheit & Datenschutz -----------------------------------------------------------
    s_ = Bereich("sicherheit", "Sicherheit & Datenschutz")
    https_ok = var.get("https_verfuegbar")
    s_.punkte.append(Pruefpunkt(
        "Verschlüsselung (HTTPS) erzwungen", bool(var.get("https_erzwungen")) if var else None,
        "keine verschlüsselte Verbindung möglich" if var and not https_ok else
        ("http:// bleibt ohne Umleitung erreichbar" if var and not var.get("https_erzwungen") else "erzwungen"),
        4, "https",
        kurz="Die Website ist nicht durchgehend verschlüsselt – Browser zeigen „Nicht sicher“ an." if var and not https_ok else "",
        gut="Die Verbindung ist verschlüsselt (HTTPS)."))
    unsicher = len(br.get("unverschluesselt", [])) if br_ok else lh_m.get("unsichere_anfragen", 0)
    if https_ok:
        s_.punkte.append(Pruefpunkt("Alle Inhalte verschlüsselt geladen", unsicher == 0,
                                    f"{unsicher} Dateien über http:// eingebunden" if unsicher else "ja", 2, "https",
                                    gut="Alle Inhalte werden verschlüsselt geladen."))
    obs = f.get("observatory") or {}
    if obs.get("grade"):
        s_.punkte.append(Pruefpunkt("Sicherheits-Header gesetzt", obs["grade"] in GUTE_NOTEN,
                                    f"Mozilla Observatory: Note {obs['grade']} ({obs.get('score')}/100)", 2, "sicherheit"))
    elif srv.get("sicherheits_header"):
        n = sum(srv["sicherheits_header"].values())
        s_.punkte.append(Pruefpunkt("Sicherheits-Header gesetzt", n >= 4, f"{n} von 6 Sicherheits-Headern", 2, "sicherheit"))
    if srv.get("cms") == "WordPress" and srv.get("cms_version"):
        s_.punkte.append(Pruefpunkt("WordPress aktuell", srv.get("cms_ist_aktuell"),
                                    f"Version {srv['cms_version']}" + (" (aktuell)" if srv.get("cms_ist_aktuell")
                                                                       else f", aktuell ist {srv.get('cms_aktuell')}"),
                                    2, "software", gut="Das CMS ist auf dem neuesten Stand."))
    if srv.get("php"):
        eol = srv.get("php_eol") or ""
        s_.punkte.append(Pruefpunkt(
            "PHP-Version erhält Sicherheitsupdates", not srv.get("php_veraltet"),
            f"PHP {srv['php']}" + (f" – seit {dt.date.fromisoformat(eol).strftime('%d.%m.%Y')} ohne Updates" if srv.get("php_veraltet") and eol else ""),
            3, "software",
            kurz=f"Der Server läuft mit PHP {srv['php']}, das keine Sicherheitsupdates mehr bekommt." if srv.get("php_veraltet") else ""))
    s_.punkte.append(Pruefpunkt("Admin-Zugang nicht öffentlich verlinkt", not srv.get("admin_link", False),
                                "Admin-Link auf der Startseite" if srv.get("admin_link") else "nicht verlinkt", 1, "sicherheit",
                                gut="Der Admin-Zugang ist nicht öffentlich verlinkt."))
    s_.punkte.append(Pruefpunkt("Impressum verlinkt", bool(sa.get("impressum")), "vorhanden" if sa.get("impressum") else "nicht gefunden",
                                4, "datenschutz", kurz="Auf der Website ist kein Impressum verlinkt (Abmahnrisiko).",
                                gut="Ein Impressum ist verlinkt."))
    if not ds.get("url"):
        s_.punkte.append(Pruefpunkt("Datenschutzerklärung auf DSGVO-Stand", False, "keine Datenschutzerklärung verlinkt", 3,
                                    "datenschutz", kurz="Es ist keine Datenschutzerklärung verlinkt."))
    else:
        ort_ds = "nur als Abschnitt im Impressum; " if ds.get("im_impressum") else ""
        s_.punkte.append(Pruefpunkt("Datenschutzerklärung auf DSGVO-Stand", ds.get("dsgvo") and not ds.get("im_impressum"),
                                    ort_ds + ("nennt die DSGVO" if ds.get("dsgvo") else "erwähnt die DSGVO nicht – vermutlich veraltet"),
                                    3, "datenschutz", gut="Die Datenschutzerklärung ist auf DSGVO-Stand."))
    if br_ok:
        dienste = br.get("dienste_ohne_einwilligung", [])
        cookies = br.get("cookies_dritt", [])
        s_.punkte.append(Pruefpunkt(
            "Externe Dienste erst nach Einwilligung", not dienste,
            (", ".join(dienste[:4]) + " laden ohne Zustimmung" + (f"; {len(cookies)} Cookies von Drittanbietern" if cookies else ""))
            if dienste else "keine ohne Zustimmung", 4, "datenschutz",
            kurz=f"{', '.join(dienste[:3])} laden, bevor Besucher zugestimmt haben." if dienste else "",
            gut="Externe Dienste laden nicht ohne Zustimmung."))
    else:
        eingebettet = sorted({x for s in seiten for x in s.get("iframes", []) if any(d in x for d in ("youtube", "google.com/maps", "vimeo"))})
        if eingebettet:
            s_.punkte.append(Pruefpunkt("Externe Dienste erst nach Einwilligung", False,
                                        f"{len(eingebettet)} eingebettete Videos/Karten direkt eingebunden", 4, "datenschutz"))

    # --- Google-Sichtbarkeit (SEO) ---------------------------------------------------------
    o = Bereich("seo", "Google-Sichtbarkeit (SEO)")
    n = len(seiten)
    mit_titel = sum(1 for s in seiten if s.get("titel"))
    mit_desc = sum(1 for s in seiten if s.get("meta_beschreibung"))
    eine_h1 = sum(1 for s in seiten if s.get("h1") == 1)
    bilder, ohne_alt = start.get("bilder", 0), start.get("bilder_ohne_alt", 0)
    query = [s["url"] for s in seiten if s.get("query_url")]
    o.punkte += [
        Pruefpunkt("Seitentitel vorhanden", mit_titel == n and n > 0, f"{mit_titel} von {n} Seiten", 2, "seo_basis"),
        Pruefpunkt("Meta-Beschreibungen", _anteil(mit_desc, n) >= 0.8, f"{mit_desc} von {n} Seiten", 3, "seo_basis",
                   kurz="Keine Seite hat eine Beschreibung für die Google-Ergebnisse." if n and mit_desc == 0 else ""),
        Pruefpunkt("Eine Hauptüberschrift (H1) pro Seite", _anteil(eine_h1, n) >= 0.8, f"{eine_h1} von {n} Seiten korrekt", 2, "seo_basis"),
        Pruefpunkt("Bildbeschreibungen (Alt-Texte)", None if not bilder else _anteil(ohne_alt, bilder) <= 0.2,
                   f"{ohne_alt} von {bilder} Bildern der Startseite ohne" if bilder else "keine Bilder", 2, "seo_basis"),
        Pruefpunkt("Sprechende Seitenadressen", not query,
                   f"z. B. „{query[0].split('/')[-1][:30]}“ statt eines Namens wie „/ueber-uns“" if query else "ja", 2, "seo_technik"),
        Pruefpunkt("Eine eindeutige Adresse", var.get("eindeutig") if var else None,
                   f"{var.get('erreichbare_varianten')} Varianten ohne Umleitung erreichbar" if var and not var.get("eindeutig") else "ja",
                   3, "seo_technik"),
        Pruefpunkt("Sitemap vorhanden", bool(rob.get("sitemap")), "vorhanden" if rob.get("sitemap") else "nicht gefunden", 2, "seo_technik"),
        Pruefpunkt("robots.txt vorhanden", rob.get("robots_status") == 200 if rob else None,
                   "vorhanden" if rob.get("robots_status") == 200 else f"fehlt (Status {rob.get('robots_status')})", 1, "seo_technik"),
        Pruefpunkt("Genug Text auf der Startseite", start.get("woerter", 0) >= 300,
                   f"ca. {start.get('woerter', 0)} Wörter inkl. Menü", 3, "inhalte",
                   kurz=f"Auf der Startseite stehen nur rund {start.get('woerter', 0)} Wörter – zu wenig, damit Google Sie einordnet."
                   if start.get("woerter", 0) < 150 else ""),
    ]
    ort = lead.get("ort", "")
    if ort:
        o.punkte.append(Pruefpunkt("Ort im Seitentitel", ort.lower() in (sa.get("title") or "").lower(),
                                   f"„{(sa.get('title') or '')[:60]}“", 2, "seo_basis"))

    # --- KI-Auffindbarkeit ------------------------------------------------------------------
    q = Bereich("ki", "KI-Auffindbarkeit")
    bots = rob.get("ki_bots") or {}
    gesperrt = [b for b, erlaubt in bots.items() if not erlaubt] + [
        b for b, st in (rob.get("ua_test") or {}).items() if isinstance(st, int) and st in (401, 403, 429, 503)]
    q.punkte.append(Pruefpunkt("KI-Crawler dürfen die Seite lesen", not gesperrt if bots else None,
                               ("gesperrt: " + ", ".join(sorted(set(gesperrt)))) if gesperrt else "erlaubt", 3, "ki_daten",
                               kurz="Die Website sperrt KI-Crawler aus – ChatGPT & Co. können sie nicht lesen." if gesperrt else "",
                               gut="KI-Crawler werden nicht ausgesperrt."))
    typen = sorted({t_ for s in seiten for t_ in s.get("jsonld_typen", [])})
    lokal = [t_ for t_ in typen if t_ in LOKALE_TYPEN or t_.endswith(("Business", "Contractor", "Store", "Service"))]
    q.punkte.append(Pruefpunkt("Strukturierte Unternehmensdaten (Schema.org)", bool(lokal),
                               ", ".join(lokal[:3]) if lokal else ("nur " + ", ".join(typen[:3]) if typen else "keine vorhanden"),
                               4, "ki_daten",
                               kurz="Es fehlen strukturierte Daten, mit denen Google und KI-Assistenten Angebot, Adresse und Öffnungszeiten sicher erkennen."
                               ))
    if branche == GASTRO:
        q.punkte.append(Pruefpunkt("Speisekarte als Text auf der Website", fn.get("speisekarte_art") == "html",
                                   {"html": "als Seite vorhanden", "pdf": "nur als PDF"}.get(fn.get("speisekarte_art", ""), "nicht gefunden"),
                                   3, "kernfunktion"))
    q.punkte.append(Pruefpunkt("llms.txt (Kurzprofil für KI-Systeme)", bool(rob.get("llms_txt")) if rob else None,
                               "vorhanden" if rob.get("llms_txt") else "fehlt", 1, "ki_daten"))
    if ki and ki.get("gesamt"):
        q.punkte.append(Pruefpunkt(
            "Bei allgemeinen Fragen von der KI empfohlen", ki["allgemein_genannt"] > 0,
            f"bei {ki['allgemein_genannt']} von {ki['allgemein_gesamt']} Fragen genannt", 4, "profile",
            kurz=f"Bei allgemeinen Fragen nach {'Restaurants' if branche == GASTRO else 'Anbietern'} in {ort or 'Ihrer Stadt'} empfiehlt die KI andere Betriebe."
            if ki["allgemein_genannt"] == 0 else "",
            gut="KI-Assistenten empfehlen Sie bei allgemeinen Fragen."))
        q.punkte.append(Pruefpunkt("Eigene Website wird als Quelle genutzt", ki["eigene_quelle"] > 0,
                                   f"in {ki['eigene_quelle']} von {ki['gesamt']} Antworten", 3, "ki_daten"))
    else:
        q.punkte.append(Pruefpunkt("KI-Stichprobe", None, "nicht durchgeführt"))

    # --- Social Media & Content -------------------------------------------------------------
    c = Bereich("social", "Social Media & Content")
    links = sa.get("social_links") or {}
    handle = lead.get("instagram") or links.get("instagram", "")
    if handle or lead.get("instagram_vorhanden") is True:
        ig_ok, ig_befund = True, f"@{handle}" if handle else "vorhanden"
    elif lead.get("instagram_vorhanden") is False:
        ig_ok, ig_befund = False, "keins gefunden"
    else:
        ig_ok, ig_befund = None, "auf der Website nicht verlinkt"
    c.punkte.append(Pruefpunkt("Instagram-Profil", ig_ok, ig_befund, 3, "social",
                               kurz="Auf Instagram sind Sie nicht zu finden.", gut="Sie sind auf Instagram vertreten."))
    c.punkte.append(Pruefpunkt("Social-Profile auf der Website verlinkt", bool(links),
                               ", ".join(sorted(links)) if links else "keine Links", 2, "social"))
    upload = max((j for s in seiten for j in s.get("upload_jahre", [])), default=None)
    c.punkte.append(Pruefpunkt("Aktuelle Fotos auf der Website", None if upload is None else upload >= heute.year - 2,
                               f"neueste Fotos von {upload}" if upload else "nicht erkennbar", 3, "social"))
    r, nb = lead.get("google_rating"), lead.get("google_bewertungen")
    c.punkte.append(Pruefpunkt("Google-Profil mit vielen guten Bewertungen",
                               None if nb is None else (nb >= 50 and (r or 0) >= 4.3),
                               f"{_de(r)} ★ bei {nb} Bewertungen" if nb is not None and r else "nicht bekannt", 3, "profile",
                               gut=f"Starke Bewertungen: {_de(r)} ★ bei {nb} Google-Bewertungen." if r and nb else ""))
    return [t, e, s_, o, q, c]


def _kernfunktionen(branche: str, fn: dict, seiten: list[dict], k: str) -> list[Pruefpunkt]:
    formular = any(s.get("formular") for s in seiten)
    if branche == GASTRO:
        art = fn.get("speisekarte_art", "")
        return [
            Pruefpunkt("Speisekarte als eigene Seite", art == "html",
                       {"html": "als Seite vorhanden", "pdf": "nur als PDF"}.get(art, "nicht gefunden"), 4, "kernfunktion",
                       kurz="Die Speisekarte gibt es nur als PDF – Google und KI finden Ihre Gerichte kaum." if art == "pdf"
                       else ("Auf der Website ist keine Speisekarte zu finden." if not art else ""),
                       gut="Die Speisekarte steht als eigene Seite auf der Website."),
            Pruefpunkt("Online reservieren oder bestellen", fn.get("reservierung") or fn.get("bestellung"),
                       "möglich" if fn.get("reservierung") or fn.get("bestellung") else "nur per Anruf oder E-Mail", 3, "kernfunktion",
                       gut="Gäste können online reservieren oder bestellen."),
        ]
    if branche == GESUNDHEIT:
        return [Pruefpunkt("Online-Terminbuchung", fn.get("termin"), "vorhanden" if fn.get("termin") else "nicht gefunden", 4,
                           "kernfunktion", kurz="Patienten können keinen Termin online buchen.", gut="Termine lassen sich online buchen."),
                Pruefpunkt("Leistungen beschrieben", fn.get("leistungen"), "vorhanden" if fn.get("leistungen") else "nicht gefunden",
                           2, "inhalte")]
    if branche in (BEAUTY, FITNESS):
        return [Pruefpunkt("Online-Buchung", fn.get("buchung"), "vorhanden" if fn.get("buchung") else "nicht gefunden", 4,
                           "kernfunktion", kurz=f"{k} können keinen Termin online buchen.", gut="Termine lassen sich online buchen."),
                Pruefpunkt("Leistungen und Preise beschrieben", fn.get("leistungen"),
                           "vorhanden" if fn.get("leistungen") else "nicht gefunden", 2, "inhalte")]
    if branche == IMMOBILIEN:
        return [Pruefpunkt("Aktuelle Objekte sichtbar", fn.get("objekte"), "vorhanden" if fn.get("objekte") else "nicht gefunden",
                           3, "kernfunktion"),
                Pruefpunkt("Bewertungsanfrage für Eigentümer", fn.get("bewertung"),
                           "vorhanden" if fn.get("bewertung") else "nicht gefunden", 3, "kernfunktion",
                           kurz="Eigentümer finden keinen direkten Weg zur Immobilienbewertung.")]
    return [Pruefpunkt("Leistungen beschrieben", fn.get("leistungen"), "vorhanden" if fn.get("leistungen") else "nicht gefunden",
                       3, "kernfunktion" if branche == HANDWERK else "inhalte"),
            Pruefpunkt("Anfrageformular", formular, "vorhanden" if formular else "nicht gefunden", 3,
                       "kernfunktion" if branche == HANDWERK else "formular",
                       kurz="Interessenten können keine Anfrage per Formular stellen." if branche == HANDWERK else "")]


def gesamtnote(bereiche: list[Bereich]) -> int:
    werte = [b.score for b in bereiche if b.score is not None]
    return round(statistics.mean(werte)) if werte else 0


def massnahmen(bereiche: list[Bereich], branche: str, gesamt: int) -> list[Massnahme]:
    """Maßnahmen aus nicht erfüllten Prüfpunkten, sortiert nach Gewicht; bei schwachem Gesamtbild ein Relaunch."""
    gewicht: dict[str, int] = {}
    for b in bereiche:
        for p in b.punkte:
            if p.ok is False and p.massnahme:
                gewicht[p.massnahme] = gewicht.get(p.massnahme, 0) + p.gewicht
    if gesamt < 45 or "relaunch" in gewicht:
        gewicht["relaunch"] = max(gewicht.get("relaunch", 0), max(gewicht.values(), default=0) + 1)
    liste = []
    for i, key in enumerate(sorted(gewicht, key=lambda x: (MASSNAHMEN[x][3], -gewicht[x]))):
        text, aufwand, wirkung, paket, _ = MASSNAHMEN[key]
        if key == "kernfunktion":
            text = KERNFUNKTION.get(branche, ("Leistungen klar darstellen, Anfrage mit einem Klick", ""))[0]
        liste.append(Massnahme(i + 1, key, text, aufwand, wirkung, paket))
    return liste


def nutzen(key: str, branche: str) -> str:
    if key == "kernfunktion":
        return KERNFUNKTION.get(branche, ("", "Mehr Anfragen über die Website."))[1]
    return MASSNAHMEN[key][4].replace("{Kunden}", kunden(branche))


def hebel(bereiche: list[Bereich], ms: list[Massnahme], n: int = 3) -> list[Massnahme]:
    gewicht: dict[str, int] = {}
    for b in bereiche:
        for p in b.punkte:
            if p.ok is False and p.massnahme:
                gewicht[p.massnahme] = gewicht.get(p.massnahme, 0) + p.gewicht
    return sorted([m for m in ms if m.key in gewicht], key=lambda m: (-gewicht[m.key] * m.wirkung / m.aufwand ** 0.5))[:n]


def befunde_kurz(bereiche: list[Bereich], n: int = 3) -> list[str]:
    """Die wichtigsten nicht erfüllten Punkte als Sätze (für „Das Wichtigste in Kürze“), je Maßnahme einer."""
    kandidaten = [(p.gewicht, 0 if p.kurz else 1, i, p) for i, b in enumerate(bereiche) for p in b.punkte if p.ok is False]
    kandidaten.sort(key=lambda x: (-x[0], x[1], x[2]))
    saetze, gesehen = [], set()
    for *_, p in kandidaten:
        if p.massnahme in gesehen:
            continue
        gesehen.add(p.massnahme)
        saetze.append(p.kurz or f"{p.text}: {p.befund}")
        if len(saetze) == n:
            break
    return saetze


def staerken(bereiche: list[Bereich], n: int = 6) -> list[str]:
    gut = sorted(((p.gewicht, p.gut or p.text) for b in bereiche for p in b.punkte if p.ok is True), key=lambda x: -x[0])
    return list(dict.fromkeys(t for _, t in gut))[:n]
