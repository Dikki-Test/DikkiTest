"""Quellen, um Betriebe in einer Region zu finden."""

from __future__ import annotations

from ..models import Lead


def dedupe(leads: list[Lead]) -> list[Lead]:
    """Führt Duplikate (gleicher Name + Ort) zusammen; fehlende Felder werden ergänzt."""
    merged: dict[str, Lead] = {}
    for lead in leads:
        existing = merged.get(lead.key)
        if existing is None:
            merged[lead.key] = lead
            continue
        for attr in ("adresse", "telefon", "email", "website", "instagram", "gewerk"):
            if not getattr(existing, attr) and getattr(lead, attr):
                setattr(existing, attr, getattr(lead, attr))
        if existing.google_rating is None and lead.google_rating is not None:
            existing.google_rating = lead.google_rating
            existing.google_bewertungen = lead.google_bewertungen
        existing.quelle = ",".join(sorted(set(existing.quelle.split(",")) | {lead.quelle}))
    return list(merged.values())
