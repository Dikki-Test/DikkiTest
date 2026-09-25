"""Export als CSV (Excel-freundlich: Semikolon, UTF-8 mit BOM) und Markdown-Kurzreport."""

from __future__ import annotations

import csv
from pathlib import Path

from .models import LeadErgebnis

SPALTEN = [
    "Priorität", "Score", "Name", "Segment", "Gewerk", "Ort", "Adresse", "Telefon", "E-Mail",
    "Website", "Website erreichbar", "Website-Score", "Website-Mängel", "Baukasten", "© Jahr",
    "Instagram", "Instagram-Aktivität", "Follower", "Posts 30 Tage", "Tage seit letztem Post",
    "Foto-Score", "Foto-Probleme", "KI-Fotonote", "360°", "360°-Anbieter", "Staging", "Drohne",
    "Makler-CRM", "Objekte (geschätzt)", "Google-Rating", "Google-Bewertungen",
    "Chancen", "Pitch", "Quelle",
]


def zeile(e: LeadErgebnis) -> dict[str, object]:
    w, m, ig, lead = e.website, e.makler, e.instagram, e.lead
    ja = lambda b: "ja" if b else "nein"  # noqa: E731
    return {
        "Priorität": e.prioritaet,
        "Score": e.lead_score,
        "Name": lead.name,
        "Segment": lead.segment,
        "Gewerk": lead.gewerk,
        "Ort": lead.ort,
        "Adresse": lead.adresse,
        "Telefon": lead.telefon,
        "E-Mail": lead.email,
        "Website": lead.website or "—",
        "Website erreichbar": ja(w.erreichbar) if w else "",
        "Website-Score": w.score if w and w.erreichbar else "",
        "Website-Mängel": " | ".join(w.maengel) if w else "",
        "Baukasten": w.baukasten if w else "",
        "© Jahr": (w.copyright_jahr or "") if w else "",
        "Instagram": f"@{ig.handle}" if ig and ig.handle else "",
        "Instagram-Aktivität": ig.aktivitaet if ig else "",
        "Follower": (ig.follower if ig and ig.follower is not None else ""),
        "Posts 30 Tage": (ig.beitraege_30_tage if ig and ig.beitraege_30_tage is not None else ""),
        "Tage seit letztem Post": (ig.tage_seit_letztem_post
                                   if ig and ig.tage_seit_letztem_post not in (None, 10_000) else ""),
        "Foto-Score": (m.foto_score if m and m.foto_score is not None else ""),
        "Foto-Probleme": " | ".join(m.foto_probleme) if m else "",
        "KI-Fotonote": (m.ki_foto_bewertung or {}).get("gesamtnote", "") if m else "",
        "360°": ja(m.rundgang_360) if m else "",
        "360°-Anbieter": ", ".join(m.rundgang_anbieter) if m else "",
        "Staging": ja(m.staging) if m else "",
        "Drohne": ja(m.drohne) if m else "",
        "Makler-CRM": ", ".join(m.crm_portal) if m else "",
        "Objekte (geschätzt)": (m.anzahl_objekte_geschaetzt or "") if m else "",
        "Google-Rating": lead.google_rating or "",
        "Google-Bewertungen": lead.google_bewertungen or "",
        "Chancen": " | ".join(f"{c.produkt} (+{c.punkte})" for c in e.chancen),
        "Pitch": e.pitch,
        "Quelle": lead.quelle,
    }


def sortiert(ergebnisse: list[LeadErgebnis]) -> list[LeadErgebnis]:
    return sorted(ergebnisse, key=lambda e: (e.prioritaet, -e.lead_score, e.lead.name))


def export_csv(ergebnisse: list[LeadErgebnis], pfad: Path) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with pfad.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        w.writeheader()
        for e in sortiert(ergebnisse):
            w.writerow(zeile(e))


def export_report(ergebnisse: list[LeadErgebnis], pfad: Path, region: str = "") -> None:
    alle = sortiert(ergebnisse)
    ohne_web = [e for e in alle if not e.lead.website or (e.website and not e.website.erreichbar)]
    makler = [e for e in alle if e.makler]
    kein_ig = [e for e in alle if not (e.instagram and e.instagram.handle)]
    zeilen = [
        f"# Lead-Report{(' – ' + region) if region else ''}",
        "",
        f"- Betriebe geprüft: **{len(alle)}** (A: {sum(e.prioritaet == 'A' for e in alle)}, "
        f"B: {sum(e.prioritaet == 'B' for e in alle)}, C: {sum(e.prioritaet == 'C' for e in alle)})",
        f"- Ohne (funktionierende) Website: **{len(ohne_web)}**",
        f"- Ohne Instagram: **{len(kein_ig)}**",
    ]
    if makler:
        zeilen += [
            f"- Makler mit Website: **{len(makler)}** – davon mit 360°: {sum(e.makler.rundgang_360 for e in makler)}, "
            f"mit Staging: {sum(e.makler.staging for e in makler)}",
        ]
    zeilen += ["", "## Top-Leads", "", "| Prio | Score | Name | Ort | Top-Chance | Pitch |", "|---|---|---|---|---|---|"]
    for e in alle[:25]:
        top = e.chancen[0].produkt if e.chancen else "—"
        zeilen.append(f"| {e.prioritaet} | {e.lead_score} | {e.lead.name} | {e.lead.ort} | {top} | "
                      f"{e.pitch.replace('|', '/')} |")
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
