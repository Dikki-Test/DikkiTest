"""Orchestrierung: Leads auditieren, bewerten, Zwischenstände speichern (fortsetzbar)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from .audit import instagram as igmod
from .audit import makler as maklermod
from .audit import website as webmod
from .http import PoliteSession
from .models import MAKLER, Lead, LeadErgebnis
from .scoring import bewerte

log = logging.getLogger(__name__)


def audit_lead(http: PoliteSession, lead: Lead, ig_token: str = "", ig_id: str = "",
               ki_fotos: bool = False, max_fotos: int = 12) -> LeadErgebnis:
    e = LeadErgebnis(lead=lead)
    soup = None
    if lead.website:
        e.website, soup = webmod.audit_website(http, lead.website)

    if lead.segment == MAKLER and e.website and e.website.erreichbar:
        e.makler = maklermod.audit_makler(http, e.website.final_url or lead.website, soup, max_fotos=max_fotos)
        if ki_fotos and e.makler.fotos:
            try:
                from .audit.ki_bewertung import bewerte_fotos
                e.makler.ki_foto_bewertung = bewerte_fotos(http, [f.url for f in e.makler.fotos])
            except Exception as ex:  # KI ist optional – Lauf nie daran scheitern lassen
                log.warning("KI-Fotobewertung für %s fehlgeschlagen: %s", lead.name, ex)

    handle, quelle = lead.instagram, "quelle" if lead.instagram else ""
    if not handle and e.website:
        handle = e.website.social_links.get("instagram", "")
        quelle = "website" if handle else ""
    e.instagram = igmod.audit_instagram(http, handle, quelle, ig_token, ig_id)
    return bewerte(e)


def lade_leads(pfad: Path) -> list[Lead]:
    return [Lead(**d) for d in json.loads(pfad.read_text(encoding="utf-8"))]


def speichere_leads(pfad: Path, leads: list[Lead]) -> None:
    from dataclasses import asdict
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps([asdict(x) for x in leads], ensure_ascii=False, indent=2), encoding="utf-8")


def lade_ergebnisse(pfad: Path) -> list[LeadErgebnis]:
    if not pfad.exists():
        return []
    return [LeadErgebnis.from_dict(d) for d in json.loads(pfad.read_text(encoding="utf-8"))]


def speichere_ergebnisse(pfad: Path, ergebnisse: list[LeadErgebnis]) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps([e.to_dict() for e in ergebnisse], ensure_ascii=False, indent=2), encoding="utf-8")


def audit_alle(http: PoliteSession, leads: list[Lead], ausgabe: Path, *, ig_token: str = "", ig_id: str = "",
               ki_fotos: bool = False, max_fotos: int = 12,
               fortschritt: Callable[[int, int, Lead], None] | None = None) -> list[LeadErgebnis]:
    """Auditiert alle Leads; bereits auditierte (gleicher key) werden übersprungen."""
    ergebnisse = lade_ergebnisse(ausgabe)
    fertig = {e.lead.key for e in ergebnisse}
    offen = [lead for lead in leads if lead.key not in fertig]
    for i, lead in enumerate(offen, 1):
        if fortschritt:
            fortschritt(i, len(offen), lead)
        try:
            ergebnisse.append(audit_lead(http, lead, ig_token, ig_id, ki_fotos, max_fotos))
        except Exception as ex:
            log.exception("Audit für %s fehlgeschlagen: %s", lead.name, ex)
            continue
        speichere_ergebnisse(ausgabe, ergebnisse)  # nach jedem Lead: Abbruch-sicher
    return ergebnisse
