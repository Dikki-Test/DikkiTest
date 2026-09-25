"""Aus den Audits werden Verkaufschancen, ein Lead-Score und ein Pitch-Einstieg."""

from __future__ import annotations

from .models import MAKLER, Chance, LeadErgebnis

AKTIV = {"sehr aktiv", "aktiv"}


def bewerte(e: LeadErgebnis) -> LeadErgebnis:
    c: list[Chance] = []
    web = e.website
    hat_website = bool(e.lead.website)

    # --- Website -----------------------------------------------------------
    if not hat_website:
        sicher = "google" in e.lead.quelle
        c.append(Chance(
            "Website-Neubau", 40 if sicher else 30,
            "Keine Website gefunden" + ("" if sicher else " (laut OSM – vor Kontakt kurz googeln)"),
        ))
    elif web and not web.erreichbar:
        c.append(Chance("Website-Neubau", 35, f"Website nicht erreichbar ({web.fehler or 'Fehler'})"))
    elif web and web.score < 50:
        c.append(Chance("Website-Relaunch", 30, "; ".join(web.maengel[:4])))
    elif web and web.score < 75:
        c.append(Chance("Website-Optimierung", 15, "; ".join(web.maengel[:3])))

    # --- Instagram ---------------------------------------------------------
    ig = e.instagram
    if ig is None or not ig.handle:
        c.append(Chance("Social-Media-Aufbau", 15, "Kein Instagram-Account gefunden"))
    elif ig.aktivitaet not in AKTIV and not ig.aktivitaet.startswith("Account gefunden"):
        c.append(Chance("Social-Media-Betreuung", 20, f"Instagram @{ig.handle}: {ig.aktivitaet}"))
    elif ig.aktivitaet.startswith("Account gefunden"):
        c.append(Chance("Social-Media-Betreuung (prüfen)", 5, f"Instagram @{ig.handle} – Aktivität manuell prüfen"))

    # --- Makler: Fotos, 360°, Staging ---------------------------------------
    m = e.makler
    if e.lead.segment == MAKLER and m is not None and (web and web.erreichbar):
        ki = m.ki_foto_bewertung or {}
        schwache_fotos = (m.foto_score is not None and m.foto_score < 70) or (ki and ki.get("gesamtnote", 10) <= 5)
        if schwache_fotos:
            grund = "; ".join(m.foto_probleme[:3]) or "; ".join(ki.get("top_verbesserungen", [])[:2])
            c.append(Chance("Immobilienfotografie", 20, grund or "Fotoqualität unterdurchschnittlich"))
        if not m.rundgang_360:
            c.append(Chance("360°-Rundgänge", 15, "Keine 360°-/3D-Rundgänge auf der Website gefunden"))
        if not m.staging:
            hoch = ki.get("staging_potenzial") == "hoch"
            c.append(Chance("KI-/Virtual-Staging", 15 if hoch else 10,
                            "Leere Räume ohne Staging" if hoch else "Kein (virtuelles) Home-Staging erkennbar"))
        if not m.drohne:
            c.append(Chance("Drohnenaufnahmen", 5, "Keine Luftaufnahmen erkennbar"))
    elif e.lead.segment == MAKLER and not hat_website:
        c.append(Chance("Makler-Komplettpaket", 10, "Ohne Website auch keine eigene Objektpräsentation"))

    # --- Zusatzsignal: Google-Bewertungen = Betrieb läuft, hat Budget -------
    bonus = 0
    if e.lead.google_bewertungen and e.lead.google_bewertungen >= 20 and (e.lead.google_rating or 0) >= 4.0:
        bonus = 10

    e.chancen = sorted(c, key=lambda x: -x.punkte)
    e.lead_score = min(100, sum(x.punkte for x in c) + bonus)
    e.prioritaet = "A" if e.lead_score >= 55 else "B" if e.lead_score >= 30 else "C"
    e.pitch = pitch(e)
    return e


def pitch(e: LeadErgebnis) -> str:
    """Ein Satz als Gesprächseinstieg – konkret, mit dem stärksten Befund."""
    if not e.chancen:
        return "Gut aufgestellt – nur für Referenz/Netzwerk kontaktieren."
    top = e.chancen[0]
    name = e.lead.name
    suche = f"{e.lead.gewerk or 'Ihr Gewerk'} {e.lead.ort}".strip()
    vorlagen = {
        "Website-Neubau": f"{name} ist online kaum auffindbar – wer nach '{suche}' sucht, landet beim Wettbewerb. "
                          f"Angebot: schlanke Website in 2 Wochen.",
        "Website-Relaunch": f"Die Website von {name} verliert Anfragen: {top.begruendung}. Angebot: Relaunch mobil-first.",
        "Website-Optimierung": f"Kleine Hebel bei {name}: {top.begruendung}.",
        "Social-Media-Aufbau": f"{name} ist auf Instagram nicht präsent – ideal für Vorher/Nachher-Content aus dem Alltag.",
        "Social-Media-Betreuung": f"{top.begruendung} – wir übernehmen Content & Posting regelmäßig.",
        "Immobilienfotografie": f"Die Objektfotos von {name} zeigen Schwächen ({top.begruendung}) – "
                                f"Profi-Fotos verkaufen schneller und zu besseren Preisen.",
        "360°-Rundgänge": f"{name} bietet keine 360°-Rundgänge – spart Besichtigungstouristen und wirkt modern.",
        "KI-/Virtual-Staging": f"Leere Räume bei {name} lassen sich per KI-Staging günstig einrichten – "
                               f"ohne Möbel schleppen.",
    }
    return vorlagen.get(top.produkt, f"{top.produkt}: {top.begruendung}")
