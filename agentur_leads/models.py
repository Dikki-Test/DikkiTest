"""Datenmodelle für Leads und Audit-Ergebnisse."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

HANDWERK = "handwerk"
MAKLER = "makler"


@dataclass
class Lead:
    name: str
    segment: str  # HANDWERK oder MAKLER
    gewerk: str = ""  # z.B. "Elektriker", "Immobilienmakler"
    adresse: str = ""
    ort: str = ""
    telefon: str = ""
    email: str = ""
    website: str = ""
    instagram: str = ""  # Handle ohne @, falls schon aus der Quelle bekannt
    quelle: str = ""  # "osm" | "google"
    quelle_id: str = ""
    google_rating: float | None = None
    google_bewertungen: int | None = None

    @property
    def key(self) -> str:
        """Stabiler Schlüssel zum Deduplizieren (Name + Ort, normalisiert)."""
        base = f"{self.name}|{self.ort}".lower()
        return "".join(ch for ch in base if ch.isalnum() or ch == "|")


@dataclass
class WebsiteAudit:
    url: str = ""
    erreichbar: bool = False
    status_code: int | None = None
    final_url: str = ""
    https: bool = False
    ladezeit_s: float | None = None
    mobil_viewport: bool = False
    title: str = ""
    meta_description: bool = False
    impressum: bool = False
    datenschutz: bool = False
    kontaktformular: bool = False
    telefon_klickbar: bool = False
    copyright_jahr: int | None = None
    baukasten: str = ""  # z.B. "Jimdo", "Wix", "WordPress"
    veraltete_technik: list[str] = field(default_factory=list)
    social_links: dict[str, str] = field(default_factory=dict)
    score: int = 0  # 0-100, höher = besser
    maengel: list[str] = field(default_factory=list)
    fehler: str = ""


@dataclass
class FotoAnalyse:
    url: str
    breite: int = 0
    hoehe: int = 0
    helligkeit: float = 0.0  # 0-255
    schaerfe: float = 0.0  # Varianz der Kantenkarte, höher = schärfer
    hochformat: bool = False
    probleme: list[str] = field(default_factory=list)


@dataclass
class MaklerAudit:
    objektseiten: list[str] = field(default_factory=list)
    anzahl_objekte_geschaetzt: int = 0
    rundgang_360: bool = False
    rundgang_anbieter: list[str] = field(default_factory=list)
    staging: bool = False
    staging_hinweise: list[str] = field(default_factory=list)
    drohne: bool = False
    video: bool = False
    crm_portal: list[str] = field(default_factory=list)  # onOffice, FLOWFACT, ...
    fotos_geprueft: int = 0
    foto_score: int | None = None  # 0-100
    foto_probleme: list[str] = field(default_factory=list)
    ki_foto_bewertung: dict[str, Any] | None = None
    fotos: list[FotoAnalyse] = field(default_factory=list)


@dataclass
class InstagramAudit:
    handle: str = ""
    quelle: str = ""  # "website" | "quelle" | ""
    follower: int | None = None
    beitraege_gesamt: int | None = None
    beitraege_30_tage: int | None = None
    beitraege_90_tage: int | None = None
    tage_seit_letztem_post: int | None = None
    engagement_rate: float | None = None  # (Likes+Kommentare)/Follower je Post, in %
    aktivitaet: str = "kein Account gefunden"
    fehler: str = ""


@dataclass
class Chance:
    produkt: str
    punkte: int
    begruendung: str


@dataclass
class LeadErgebnis:
    lead: Lead
    website: WebsiteAudit | None = None
    makler: MaklerAudit | None = None
    instagram: InstagramAudit | None = None
    chancen: list[Chance] = field(default_factory=list)
    lead_score: int = 0
    prioritaet: str = "C"
    pitch: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LeadErgebnis":
        makler = None
        if d.get("makler"):
            m = dict(d["makler"])
            m["fotos"] = [FotoAnalyse(**f) for f in m.get("fotos", [])]
            makler = MaklerAudit(**m)
        return cls(
            lead=Lead(**d["lead"]),
            website=WebsiteAudit(**d["website"]) if d.get("website") else None,
            makler=makler,
            instagram=InstagramAudit(**d["instagram"]) if d.get("instagram") else None,
            chancen=[Chance(**c) for c in d.get("chancen", [])],
            lead_score=d.get("lead_score", 0),
            prioritaet=d.get("prioritaet", "C"),
            pitch=d.get("pitch", ""),
        )
