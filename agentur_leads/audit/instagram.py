"""Instagram-Check: Gibt es einen Account – und wie aktiv ist er?

Wir scrapen Instagram bewusst NICHT (Meta-Nutzungsbedingungen, Login-Wall,
schnelle IP-Sperren). Stattdessen:

1. Handle finden: aus der Website (Social-Links) oder der Lead-Quelle.
2. Aktivität messen über die offizielle Instagram Graph API "Business Discovery"
   (liefert Follower, Beitragsanzahl und die letzten Posts mit Datum/Likes für
   Business- und Creator-Accounts). Dafür braucht es einen eigenen
   Instagram-Business-Account + Meta-App-Token (IG_GRAPH_TOKEN, IG_BUSINESS_ACCOUNT_ID).
3. Ohne Token: Status "Handle gefunden – Aktivität manuell prüfen".
"""

from __future__ import annotations

import datetime as dt

import requests

from ..http import PoliteSession
from ..models import InstagramAudit

GRAPH_URL = "https://graph.facebook.com/v21.0/{ig_id}"


def klassifiziere(audit: InstagramAudit) -> str:
    if not audit.handle:
        return "kein Account gefunden"
    if audit.tage_seit_letztem_post is None:
        return "Account gefunden – Aktivität manuell prüfen"
    if audit.beitraege_gesamt == 0:
        return "leer (0 Beiträge)"
    if audit.tage_seit_letztem_post > 180:
        return "eingeschlafen (>6 Monate kein Post)"
    if audit.tage_seit_letztem_post > 60:
        return "inaktiv (>2 Monate kein Post)"
    if (audit.beitraege_30_tage or 0) >= 6:
        return "sehr aktiv"
    if (audit.beitraege_30_tage or 0) >= 3:
        return "aktiv"
    return "unregelmäßig"


def auswerten(handle: str, data: dict, heute: dt.datetime | None = None) -> InstagramAudit:
    """Wertet eine Business-Discovery-Antwort aus."""
    heute = heute or dt.datetime.now(dt.timezone.utc)
    bd = data.get("business_discovery", {})
    audit = InstagramAudit(handle=handle, follower=bd.get("followers_count"),
                           beitraege_gesamt=bd.get("media_count"))
    posts = bd.get("media", {}).get("data", [])
    zeiten = []
    for p in posts:
        try:
            zeiten.append(dt.datetime.strptime(p["timestamp"], "%Y-%m-%dT%H:%M:%S%z"))
        except (KeyError, ValueError):
            continue
    if zeiten:
        audit.tage_seit_letztem_post = (heute - max(zeiten)).days
        audit.beitraege_30_tage = sum(1 for z in zeiten if (heute - z).days <= 30)
        audit.beitraege_90_tage = sum(1 for z in zeiten if (heute - z).days <= 90)
    elif audit.beitraege_gesamt == 0:
        audit.tage_seit_letztem_post = 10_000
    if posts and audit.follower:
        interaktionen = [p.get("like_count", 0) + p.get("comments_count", 0) for p in posts]
        audit.engagement_rate = round(100 * sum(interaktionen) / len(interaktionen) / audit.follower, 2)
    audit.aktivitaet = klassifiziere(audit)
    return audit


def audit_instagram(http: PoliteSession, handle: str, quelle: str,
                    token: str = "", ig_id: str = "") -> InstagramAudit:
    handle = (handle or "").lstrip("@").strip().rstrip("/")
    if not handle:
        return InstagramAudit()
    if not (token and ig_id):
        audit = InstagramAudit(handle=handle, quelle=quelle)
        audit.aktivitaet = klassifiziere(audit)
        return audit
    fields = (f"business_discovery.username({handle})"
              "{followers_count,media_count,media.limit(25){timestamp,like_count,comments_count,media_type}}")
    try:
        resp = http.api_get(GRAPH_URL.format(ig_id=ig_id), params={"fields": fields, "access_token": token})
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        audit = InstagramAudit(handle=handle, quelle=quelle, fehler=type(e).__name__)
        audit.aktivitaet = klassifiziere(audit)
        return audit
    if "error" in data:
        # Häufig: privater Account oder kein Business-/Creator-Account
        audit = InstagramAudit(handle=handle, quelle=quelle, fehler=data["error"].get("message", "API-Fehler")[:200])
        audit.aktivitaet = klassifiziere(audit)
        return audit
    audit = auswerten(handle, data)
    audit.quelle = quelle
    return audit
