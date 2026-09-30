"""Woher die Leads für Berichte kommen: Notion-Board „📥 Leads“, Ergebnisdateien des Lead-Finders
oder eine einzelne URL."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import MAKLER
from .modelle import HANDWERK, IMMOBILIEN, ReportLead

BEWERTUNG = re.compile(r"Google\s*([0-5][,.]\d)\s*★?\s*\((\d[\d.]*)\s*Bewertungen?\)", re.I)
KUECHE = re.compile(r"Küche:\s*([A-Za-z_;]+)")
AUSSCHLIESSEN = {"❌ Geschlossen", "❓ Verdacht geschlossen", "👻 Keine Online-Präsenz"}


def ort_aus_adresse(adresse: str) -> str:
    """'Rathausplatz 5, 52072 Aachen' -> 'Aachen'."""
    if not adresse:
        return ""
    teil = adresse.split(",")[-1].strip()
    return re.sub(r"^\d{4,5}\s*", "", teil).strip()


def bewertung_aus_text(text: str) -> tuple[float | None, int | None]:
    m = BEWERTUNG.search(text or "")
    if not m:
        return None, None
    return float(m.group(1).replace(",", ".")), int(m.group(2).replace(".", ""))


def _wert(prop: dict | None):
    if not prop:
        return None
    typ = prop.get("type")
    v = prop.get(typ)
    if typ in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in v or [])
    if typ in ("select", "status"):
        return (v or {}).get("name")
    if typ == "multi_select":
        return [x.get("name") for x in v or []]
    if typ == "date":
        return (v or {}).get("start")
    return v  # url, number, email, phone_number, checkbox


def lead_aus_notion(seite: dict) -> ReportLead:
    w = {name: _wert(prop) for name, prop in seite.get("properties", {}).items()}
    return _lead_aus_werten(w, seite.get("id", ""), seite.get("url", ""))


def _lead_aus_werten(w: dict, page_id: str, url: str) -> ReportLead:
    rating, anzahl = bewertung_aus_text(w.get("KI-Einschätzung") or "")
    kueche = KUECHE.search(w.get("Notiz") or "")
    ig = (w.get("Instagram-Handle") or "").strip().lstrip("@")
    ig_da = {"ja": True, "nein": False}.get(w.get("Instagram vorhanden") or "")
    return ReportLead(
        name=(w.get("Name") or "").replace("[", "").replace("]", "").strip(),
        website=(w.get("Website") or "").strip(),
        branche=w.get("Branche") or "",
        kategorie=w.get("Fachrichtung") or w.get("Gewerk") or w.get("Immo-Typ") or "",
        kueche=kueche.group(1) if kueche else "",
        adresse=w.get("Adresse") or "",
        ort=ort_aus_adresse(w.get("Adresse") or ""),
        google_rating=rating, google_bewertungen=anzahl,
        instagram=ig, instagram_vorhanden=True if ig else ig_da,
        notion_page_id=page_id, notion_url=url,
        bericht_datum=w.get("Report-Datum") or "",
    )


def lead_aus_zeile(z: dict) -> ReportLead:
    """Flache Board-Zeile, wie sie der Notion-Connector oder ein Export liefert ({"Name": …, "url": …})."""
    url = z.get("url") or ""
    m = re.search(r"([0-9a-f]{32})", url.replace("-", ""))
    page_id = ""
    if m:
        h = m.group(1)
        page_id = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
    werte = {**z, "Report-Datum": z.get("date:Report-Datum:start") or z.get("Report-Datum") or ""}
    return _lead_aus_werten(werte, page_id, url)


def notion_filter(seite: dict) -> bool:
    """Nur Leads mit Website und ohne Ausschluss-Qualität (geschlossen, keine Online-Präsenz)."""
    q = _wert(seite.get("properties", {}).get("Qualität"))
    return q not in AUSSCHLIESSEN


def leads_aus_datei(pfad: Path) -> list[ReportLead]:
    """Liest output/leads.json bzw. ergebnisse.json des Lead-Finders oder einen Notion-Export (flache Zeilen)."""
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    if isinstance(daten, dict):  # Antwort einer Board-Abfrage: {"results": [...]}
        daten = daten.get("results", [])
    if daten and "Name" in daten[0] and "url" in daten[0]:  # flache Board-Zeilen aus Notion
        return [lead_aus_zeile(z) for z in daten if (z.get("Website") or "").strip()
                and z.get("Qualität") not in AUSSCHLIESSEN]
    leads = []
    for d in daten:
        lead = d.get("lead", d)
        website = (d.get("website") or {}).get("final_url") or lead.get("website", "")
        if not website:
            continue
        leads.append(ReportLead(
            name=lead["name"], website=website,
            branche=IMMOBILIEN if lead.get("segment") == MAKLER else HANDWERK,
            kategorie=lead.get("gewerk", ""), adresse=lead.get("adresse", ""),
            ort=lead.get("ort") or ort_aus_adresse(lead.get("adresse", "")),
            google_rating=lead.get("google_rating"), google_bewertungen=lead.get("google_bewertungen"),
            instagram=lead.get("instagram", ""),
        ))
    return leads
