"""Optionale Quelle: Google Places API (New) – Text Search.

Vorteil gegenüber OSM: deutlich vollständiger, inkl. websiteUri. Fehlt websiteUri
hier, ist "keine Website" ein starkes Signal. Benötigt GOOGLE_PLACES_API_KEY.
"""

from __future__ import annotations

from ..http import PoliteSession
from ..models import HANDWERK, MAKLER, Lead

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.addressComponents",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.rating",
    "places.userRatingCount",
    "places.businessStatus",
    "nextPageToken",
])

HANDWERK_SUCHBEGRIFFE = [
    "Elektriker", "Sanitär Heizung", "Dachdecker", "Maler", "Tischler Schreiner",
    "Fliesenleger", "Zimmerei", "Garten- und Landschaftsbau", "Metallbau", "Bodenleger",
]
MAKLER_SUCHBEGRIFFE = ["Immobilienmakler"]


def _city(components: list[dict]) -> str:
    for c in components or []:
        if "locality" in c.get("types", []):
            return c.get("longText", "")
    return ""


def place_to_lead(place: dict, segment: str, gewerk: str) -> Lead | None:
    if place.get("businessStatus") not in (None, "OPERATIONAL"):
        return None
    return Lead(
        name=place.get("displayName", {}).get("text", ""),
        segment=segment,
        gewerk=gewerk,
        adresse=place.get("formattedAddress", ""),
        ort=_city(place.get("addressComponents", [])),
        telefon=place.get("nationalPhoneNumber", ""),
        website=place.get("websiteUri", ""),
        quelle="google",
        quelle_id=place.get("id", ""),
        google_rating=place.get("rating"),
        google_bewertungen=place.get("userRatingCount"),
    )


def search(http: PoliteSession, api_key: str, text: str, segment: str, gewerk: str,
           max_pages: int = 3) -> list[Lead]:
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}
    body: dict = {"textQuery": text, "languageCode": "de", "regionCode": "DE", "pageSize": 20}
    leads: list[Lead] = []
    for _ in range(max_pages):
        resp = http.post(SEARCH_URL, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        for place in data.get("places", []):
            lead = place_to_lead(place, segment, gewerk)
            if lead and lead.name:
                leads.append(lead)
        token = data.get("nextPageToken")
        if not token:
            break
        body["pageToken"] = token
    return leads


def discover(http: PoliteSession, api_key: str, region: str, segmente: list[str],
             begriffe: list[str] | None = None) -> list[Lead]:
    leads: list[Lead] = []
    if HANDWERK in segmente:
        for b in begriffe or HANDWERK_SUCHBEGRIFFE:
            leads += search(http, api_key, f"{b} in {region}", HANDWERK, b)
    if MAKLER in segmente:
        for b in MAKLER_SUCHBEGRIFFE:
            leads += search(http, api_key, f"{b} in {region}", MAKLER, "Immobilienmakler")
    return leads
