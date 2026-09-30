"""Datenmodelle für den Verkaufsbericht."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlparse

# Branchen wie im Notion-Board „📥 Leads“
GASTRO = "Gastronomie"
HANDWERK = "Handwerk"
IMMOBILIEN = "Immobilien"
GESUNDHEIT = "Gesundheit"
BEAUTY = "Beauty"
FITNESS = "Fitness"
DIENSTLEISTUNG = "Dienstleistung"

# KI-Crawler: Such-/Abrufdienste entscheiden, ob ChatGPT & Co. eine Seite in Antworten nutzen können;
# Trainings-Crawler sammeln nur Trainingsdaten – sie auszusperren ist eine legitime Entscheidung.
KI_SUCHE_BOTS = ("OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User", "PerplexityBot")
KI_TRAINING_BOTS = ("GPTBot", "ClaudeBot", "Google-Extended", "CCBot")


@dataclass
class ReportLead:
    name: str
    website: str
    branche: str = ""  # siehe Konstanten oben
    kategorie: str = ""  # Fachrichtung / Gewerk / Immo-Typ, z.B. "Restaurant", "Dachdecker"
    kueche: str = ""  # Gastronomie: OSM-Küche, z.B. "vietnamese" (für die KI-Fragen)
    adresse: str = ""
    ort: str = ""
    google_rating: float | None = None
    google_bewertungen: int | None = None
    instagram: str = ""  # Handle, falls bekannt
    instagram_vorhanden: bool | None = None
    notion_page_id: str = ""
    notion_url: str = ""
    bericht_datum: str = ""  # Datum des letzten Berichts (aus Notion), leer = noch keiner

    @property
    def slug(self) -> str:
        basis = slug(f"{self.name}-{self.ort}" if self.ort else self.name)
        return f"{basis}-{self.notion_page_id.replace('-', '')[-6:]}" if self.notion_page_id else basis

    @property
    def domain(self) -> str:
        return registrierte_domain(self.website)


@dataclass
class Pruefpunkt:
    text: str  # Prüfpunkt, z.B. "Telefonnummer auf dem Handy antippbar"
    ok: bool | None  # None = nicht prüfbar (zählt nicht in die Punkte)
    befund: str = ""  # konkreter Messwert/Beleg
    gewicht: int = 1  # Wichtigkeit für Zusammenfassung und Hebel (1–5)
    massnahme: str = ""  # Schlüssel in pruefung.MASSNAHMEN
    kurz: str = ""  # Satz für „Das Wichtigste in Kürze“, falls nicht erfüllt
    gut: str = ""  # Satz für „Was schon gut ist“, falls erfüllt


@dataclass
class Bereich:
    key: str
    name: str
    punkte: list[Pruefpunkt] = field(default_factory=list)
    score_override: int | None = None  # z.B. Lighthouse-Leistungswert
    erklaerung: str = ""  # Satz unter der Tabelle

    @property
    def geprueft(self) -> list[Pruefpunkt]:
        return [p for p in self.punkte if p.ok is not None]

    @property
    def score(self) -> int | None:
        if self.score_override is not None:
            return self.score_override
        g = self.geprueft
        return round(100 * sum(p.ok for p in g) / len(g)) if g else None


@dataclass
class Massnahme:
    nr: int
    key: str
    text: str
    aufwand: float  # 1 (klein) – 5 (groß)
    wirkung: float  # 1 (klein) – 5 (groß)
    paket: int  # 1 Sofort-Fix, 2 Neue Website, 3 Sichtbarkeit & Content


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.replace("ß", "ss")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60] or "lead"


def normalisiere(text: str) -> str:
    """Für Namensvergleiche: klein, ohne Akzente, nur Buchstaben/Ziffern."""
    t = unicodedata.normalize("NFKD", text.lower().replace("ß", "ss")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", t)


def registrierte_domain(url: str) -> str:
    """'https://neu.beispiel-restaurant.de/x' -> 'beispiel-restaurant.de' (einfache Heuristik)."""
    host = urlparse(url if "//" in url else "//" + url).hostname or ""
    teile = host.lower().removeprefix("www.").split(".")
    if len(teile) >= 3 and teile[-2] in {"co", "com", "org", "net"} and len(teile[-1]) == 2:
        return ".".join(teile[-3:])
    return ".".join(teile[-2:]) if len(teile) >= 2 else host
