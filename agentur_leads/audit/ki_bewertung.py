"""Optional: inhaltliche Bewertung der Makler-Fotos mit Claude (Vision).

Die Heuristik in fotos.py erkennt technische Mängel. Claude bewertet zusätzlich,
was ein Fotograf bewerten würde: Perspektive, stürzende Linien, Licht,
Aufgeräumtheit, und ob leere/unmöblierte Räume Kandidaten für (KI-)Staging sind.
Aktivieren mit --ki-fotos und ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import base64
import io
from typing import Literal

from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from ..http import PoliteSession

MODEL = "claude-opus-5"
MAX_KANTE = 1568  # größere Bilder skaliert die API ohnehin herunter – spart Tokens


class FotoUrteil(BaseModel):
    bild_nr: int = Field(description="1-basierte Nummer des Bildes in der Reihenfolge der Anfrage")
    note: int = Field(description="1 (sehr schlecht) bis 10 (Profi-Niveau)")
    raumtyp: str = Field(description="z.B. Wohnzimmer, Küche, Außenansicht, Grundriss")
    leerer_raum: bool = Field(description="Raum ist leer oder kaum möbliert -> Staging-Kandidat")
    maengel: list[str] = Field(description="konkrete Mängel, z.B. 'stürzende Linien', 'Unordnung'")


class FotoGutachten(BaseModel):
    gesamtnote: int = Field(description="1-10, Durchschnittseindruck aller Objektfotos")
    professionell_fotografiert: bool
    urteile: list[FotoUrteil]
    staging_potenzial: Literal["hoch", "mittel", "gering"]
    top_verbesserungen: list[str] = Field(description="max. 3 konkrete Verbesserungen, auf Deutsch")
    verkaufsargument: str = Field(
        description="Ein Satz, mit dem eine Agentur dem Makler Foto/360°/Staging-Leistungen anbieten kann"
    )


PROMPT = """Du bist erfahrener Immobilienfotograf und bewertest die Objektfotos eines \
Immobilienmaklers von dessen Website. Bewerte jedes Bild einzeln und gib ein Gesamturteil. \
Achte auf: Licht/Belichtung (HDR, Fenster ausgebrannt?), stürzende Linien, Perspektive \
(Weitwinkel, Augenhöhe), Aufgeräumtheit, Bildschärfe, Auflösung, Handy-Look. \
Markiere leere oder spärlich möblierte Räume als Staging-Kandidaten. \
Bilder, die offensichtlich keine Objektfotos sind (Logos, Personen, Stockfotos), \
bewerte mit raumtyp 'kein Objektfoto' und lasse sie in der Gesamtnote außen vor. \
Antworte auf Deutsch."""


def _bild_block(daten: bytes) -> dict | None:
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(daten))).convert("RGB")
    except Exception:
        return None
    img.thumbnail((MAX_KANTE, MAX_KANTE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg",
                   "data": base64.standard_b64encode(buf.getvalue()).decode("utf-8")},
    }


def bewerte_fotos(http: PoliteSession, urls: list[str], max_bilder: int = 6) -> dict | None:
    """Gibt das Gutachten als dict zurück, oder None (kein Key, keine Bilder, Ablehnung)."""
    import anthropic  # optionale Abhängigkeit: pip install agentur-leads[ki]

    bloecke: list[dict] = []
    for url in urls:
        if len(bloecke) >= max_bilder:
            break
        try:
            resp = http.get(url)
        except Exception:
            continue
        if resp.status_code < 400 and (block := _bild_block(resp.content)):
            bloecke.append(block)
    if not bloecke:
        return None

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": [*bloecke, {"type": "text", "text": PROMPT}]}],
        output_format=FotoGutachten,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return None
    return response.parsed_output.model_dump()
