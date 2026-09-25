"""Kostenlose Quelle: OpenStreetMap (Nominatim zum Geocoden + Overpass API).

Hinweis: In OSM fehlt oft das website-Tag, obwohl der Betrieb eine Website hat.
"Keine Website" aus OSM ist daher nur ein Verdacht – der Audit prüft zusätzlich
per Google Places (falls Key vorhanden) bzw. markiert es als "unbestätigt".
"""

from __future__ import annotations

import re

from ..http import PoliteSession
from ..models import HANDWERK, MAKLER, Lead

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# OSM craft=* -> deutsches Gewerk
HANDWERK_CRAFTS: dict[str, str] = {
    "electrician": "Elektriker",
    "plumber": "Sanitär/Installateur",
    "hvac": "Heizung/Klima",
    "heating_engineer": "Heizungsbauer",
    "carpenter": "Zimmerer/Tischler",
    "joiner": "Tischler/Schreiner",
    "roofer": "Dachdecker",
    "painter": "Maler",
    "tiler": "Fliesenleger",
    "floorer": "Bodenleger",
    "plasterer": "Stuckateur/Putzer",
    "stonemason": "Steinmetz",
    "glaziery": "Glaser",
    "window_construction": "Fensterbau",
    "metal_construction": "Metallbau",
    "locksmith": "Schlosser",
    "gardener": "Garten- und Landschaftsbau",
    "builder": "Bauunternehmen",
    "insulation": "Dämmung",
    "scaffolder": "Gerüstbau",
    "chimney_sweeper": "Schornsteinfeger",
    "sanitary": "Sanitär",
    "kitchen_fitter": "Küchenmonteur",
}


def geocode(http: PoliteSession, region: str) -> tuple[float, float]:
    resp = http.api_get(
        NOMINATIM_URL,
        params={"q": region, "format": "json", "limit": 1, "countrycodes": "de,at,ch"},
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise ValueError(f"Region nicht gefunden: {region}")
    return float(data[0]["lat"]), float(data[0]["lon"])


def build_query(lat: float, lon: float, radius_m: int, segmente: list[str],
                crafts: list[str] | None = None) -> str:
    parts: list[str] = []
    if HANDWERK in segmente:
        craft_re = "|".join(crafts or HANDWERK_CRAFTS)
        parts.append(f'nwr(around:{radius_m},{lat},{lon})["craft"~"^({craft_re})$"]["name"];')
    if MAKLER in segmente:
        parts.append(f'nwr(around:{radius_m},{lat},{lon})["office"="estate_agent"]["name"];')
    return "[out:json][timeout:120];(" + "".join(parts) + ");out center tags;"


def _normalize_url(url: str) -> str:
    url = url.strip()
    if url and not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    return url


def _instagram_from_tags(tags: dict[str, str]) -> str:
    raw = tags.get("contact:instagram") or tags.get("instagram") or ""
    m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", raw)
    if m:
        return m.group(1)
    return raw.lstrip("@").strip()


def element_to_lead(el: dict) -> Lead | None:
    tags = el.get("tags", {})
    name = tags.get("name")
    if not name:
        return None
    if tags.get("office") == "estate_agent":
        segment, gewerk = MAKLER, "Immobilienmakler"
    else:
        segment = HANDWERK
        gewerk = HANDWERK_CRAFTS.get(tags.get("craft", ""), tags.get("craft", ""))
    strasse = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")]))
    ort = " ".join(filter(None, [tags.get("addr:postcode"), tags.get("addr:city")]))
    return Lead(
        name=name,
        segment=segment,
        gewerk=gewerk,
        adresse=", ".join(filter(None, [strasse, ort])),
        ort=tags.get("addr:city", ""),
        telefon=tags.get("phone") or tags.get("contact:phone") or "",
        email=tags.get("email") or tags.get("contact:email") or "",
        website=_normalize_url(tags.get("website") or tags.get("contact:website") or tags.get("url") or ""),
        instagram=_instagram_from_tags(tags),
        quelle="osm",
        quelle_id=f"{el.get('type')}/{el.get('id')}",
    )


def discover(http: PoliteSession, region: str, radius_km: float, segmente: list[str],
             crafts: list[str] | None = None) -> list[Lead]:
    lat, lon = geocode(http, region)
    query = build_query(lat, lon, int(radius_km * 1000), segmente, crafts)
    resp = http.post(OVERPASS_URL, data={"data": query})
    resp.raise_for_status()
    leads = [element_to_lead(el) for el in resp.json().get("elements", [])]
    return [lead for lead in leads if lead is not None]
