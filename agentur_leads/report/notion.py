"""Notion-REST-API: Leads lesen, PDF und Bilder hochladen, Berichtsseite anlegen, Lead-Felder setzen.

Braucht NOTION_TOKEN (interne Integration, die mit dem Leads-Board verbunden ist).
"""

from __future__ import annotations

import logging
import mimetypes
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)
API = "https://api.notion.com/v1"
VERSION = "2026-03-11"
MAX_OBEN = 90  # Top-Level-Blöcke je Anfrage (API-Grenze 100)
MAX_GESAMT = 450  # Blöcke inkl. verschachtelter je Anfrage (API-Grenze 1000)

# Felder im Leads-Board, die ein Berichtslauf füllt (werden bei Bedarf angelegt)
LEAD_FELDER = {"Report-Score": {"number": {"format": "number"}}, "Report-Datum": {"date": {}}, "Report-PDF": {"files": {}}}
SEITEN_FELD = {"Report": {"url": {}}}  # nur mit Unterseite (--mit-seite)


def lead_felder(mit_seite: bool = False) -> dict:
    return {**LEAD_FELDER, **(SEITEN_FELD if mit_seite else {})}


class NotionFehler(RuntimeError):
    pass


def _anzahl(block: dict) -> int:
    inhalt = block.get(block.get("type", ""), {})
    return 1 + sum(_anzahl(k) for k in inhalt.get("children", []) if isinstance(k, dict))


def stapel(bloecke: list[dict]) -> list[list[dict]]:
    """Teilt die Blöcke in Anfragen auf, die unter den API-Grenzen bleiben."""
    alle, aktuell, n = [], [], 0
    for b in bloecke:
        k = _anzahl(b)
        if aktuell and (len(aktuell) >= MAX_OBEN or n + k > MAX_GESAMT):
            alle.append(aktuell)
            aktuell, n = [], 0
        aktuell.append(b)
        n += k
    if aktuell:
        alle.append(aktuell)
    return alle


class Notion:
    def __init__(self, token: str, session: requests.Session | None = None, pause_s: float = 0.35) -> None:
        self.s = session or requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Notion-Version": VERSION})
        self.pause_s = pause_s  # Notion erlaubt im Schnitt ~3 Anfragen pro Sekunde
        self._letzte = 0.0

    def _anfrage(self, methode: str, pfad: str, **kw) -> dict:
        for versuch in range(6):
            warte = self.pause_s - (time.monotonic() - self._letzte)
            if warte > 0:
                time.sleep(warte)
            self._letzte = time.monotonic()
            try:
                r = self.s.request(methode, API + pfad, timeout=90, **kw)
            except requests.RequestException as e:
                log.warning("Notion %s %s: %s – neuer Versuch", methode, pfad, e)
                time.sleep(2 ** versuch)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(float(r.headers.get("Retry-After") or 2 ** versuch))
                continue
            if r.status_code >= 400:
                raise NotionFehler(f"{methode} {pfad}: HTTP {r.status_code} {r.text[:400]}")
            return r.json()
        raise NotionFehler(f"{methode} {pfad}: zu viele Fehlversuche")

    def leads(self, datenquelle: str, nur_mit_website: bool = True) -> list[dict]:
        body: dict = {"page_size": 100}
        if nur_mit_website:
            body["filter"] = {"property": "Website", "url": {"is_not_empty": True}}
        seiten: list[dict] = []
        while True:
            d = self._anfrage("POST", f"/data_sources/{datenquelle}/query", json=body)
            seiten += d.get("results", [])
            if not d.get("has_more"):
                return seiten
            body["start_cursor"] = d["next_cursor"]

    def felder_sicherstellen(self, datenquelle: str, felder: dict | None = None) -> None:
        felder = felder or LEAD_FELDER
        ds = self._anfrage("GET", f"/data_sources/{datenquelle}")
        fehlend = {k: v for k, v in felder.items() if k not in ds.get("properties", {})}
        if fehlend:
            log.info("Lege Felder im Leads-Board an: %s", ", ".join(fehlend))
            self._anfrage("PATCH", f"/data_sources/{datenquelle}", json={"properties": fehlend})

    def hochladen(self, pfad: Path, name: str = "") -> str:
        """Lädt eine Datei hoch (bis 20 MB, Workspace-Grenzen gelten); name = Dateiname in Notion."""
        name = name or pfad.name
        typ = mimetypes.guess_type(pfad.name)[0] or "application/octet-stream"
        fu = self._anfrage("POST", "/file_uploads", json={"filename": name, "content_type": typ})
        with pfad.open("rb") as fh:
            self._anfrage("POST", f"/file_uploads/{fu['id']}/send", files={"file": (name, fh, typ)})
        return fu["id"]

    def seite_anlegen(self, eltern_id: str, titel: str, icon: str, bloecke: list[dict]) -> dict:
        erste, *rest = stapel(bloecke) or [[]]
        seite = self._anfrage("POST", "/pages", json={
            "parent": {"page_id": eltern_id},
            "icon": {"type": "emoji", "emoji": icon},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": titel}}]}},
            "children": erste,
        })
        for teil in rest:
            self._anfrage("PATCH", f"/blocks/{seite['id']}/children", json={"children": teil})
        return seite

    def seite_aktualisieren(self, page_id: str, properties: dict) -> dict:
        return self._anfrage("PATCH", f"/pages/{page_id}", json={"properties": properties})
