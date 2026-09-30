"""KI-Stichprobe (optional, braucht ANTHROPIC_API_KEY): Wird der Betrieb genannt, wenn Kunden einen
KI-Assistenten mit Websuche fragen? Und nutzt die KI die eigene Website als Quelle?

Je Lead 3 Fragen (2 allgemeine, 1 nach dem Namen) über Claude mit dem Websuche-Tool.
Kosten: 10 $ je 1.000 Suchen plus Tokens; das Modell lässt sich mit KI_SUCHE_MODELL ändern.
"""

from __future__ import annotations

import logging
import os
import re

from .modelle import GASTRO, GESUNDHEIT, HANDWERK, IMMOBILIEN, ReportLead, normalisiere, registrierte_domain

log = logging.getLogger(__name__)

STANDARD_MODELL = "claude-opus-5-5"
SYSTEM = (
    "Du bist ein hilfreicher Assistent und beantwortest Fragen von Menschen, die vor Ort einen Betrieb suchen. "
    "Nutze die Websuche. Empfiehl konkrete Betriebe mit je einem kurzen Satz Begründung. Antworte auf Deutsch. "
    "Beende deine Antwort mit einer eigenen Zeile im Format 'EMPFEHLUNGEN: Name 1; Name 2; Name 3' "
    "(nur die Betriebsnamen, die du empfohlen oder beschrieben hast)."
)
KUECHE = {
    "asian": "asiatisches", "vietnamese": "vietnamesisches", "italian": "italienisches", "greek": "griechisches",
    "chinese": "chinesisches", "indian": "indisches", "thai": "thailändisches", "japanese": "japanisches",
    "sushi": "japanisches", "turkish": "türkisches", "german": "deutsches", "regional": "regionales",
    "mexican": "mexikanisches", "arab": "arabisches", "persian": "persisches", "french": "französisches",
    "spanish": "spanisches", "american": "amerikanisches", "korean": "koreanisches", "lebanese": "libanesisches",
}
GEWERK = {
    "Elektro": "Elektriker", "Sanitär/Heizung": "Installateur für Sanitär und Heizung", "Maler": "Maler",
    "Tischler/Schreiner": "Schreiner", "Dachdecker": "Dachdecker", "Fliesenleger": "Fliesenleger",
    "Schlosser/Metallbau": "Metallbauer", "Zimmerei": "Zimmerer", "Bodenleger": "Bodenleger", "Glaser": "Glaser",
    "Maurer/Bau": "Bauunternehmer", "Trockenbau": "Trockenbauer", "Rollladen/Sonnenschutz": "Rollladenbauer",
    "Garten- und Landschaftsbau": "Gartenbaubetrieb", "Allround/Hausmeister": "Hausmeisterservice",
}
FEMININ = ("praxis", "verwaltung", "kanzlei", "werkstatt", "schule", "agentur", "therapie", "apotheke", "klinik")
NEUTRUM = ("restaurant", "café", "cafe", "studio", "bistro", "hotel", "büro", "unternehmen", "imbiss", "lokal")
RECHTSFORM = re.compile(r"\b(inh\.?|inhaber).*$|\b(gmbh|mbh|ug|ag|kg|ohg|gbr|e\.?\s?k\.?|& co\.?|co\.)\b", re.I)


def begriff(lead: ReportLead) -> str:
    """Wonach ein Kunde sucht, z.B. 'vietnamesisches Restaurant', 'Dachdecker', 'Zahnarztpraxis'."""
    k = lead.kategorie.strip()
    if lead.branche == GASTRO:
        basis = k if k and k.lower() not in {"gastronomie"} else "Restaurant"
        adj = KUECHE.get(lead.kueche.lower().split(";")[0].strip(), "")
        return f"{adj} {basis}".strip() if adj and basis == "Restaurant" else basis
    if lead.branche == HANDWERK:
        return GEWERK.get(k, k or "Handwerksbetrieb")
    if lead.branche == GESUNDHEIT:
        return f"{k}-Praxis" if k and "praxis" not in k.lower() else (k or "Arztpraxis")
    if lead.branche == IMMOBILIEN:
        return "Hausverwaltung" if "verwaltung" in k.lower() and "makler" not in k.lower() else "Immobilienmakler"
    return k or lead.branche or "Betrieb"


def _artikel(wort: str) -> tuple[str, str]:
    """(unbestimmter Artikel im Akkusativ, 'der/die/das beste …') – Adjektive werden schwach dekliniert."""
    *adjektive, nomen = wort.split()
    if nomen.lower().endswith(FEMININ):
        return f"eine {wort}", f"die beste {wort}"
    if nomen.lower().endswith(NEUTRUM):
        schwach = [a[:-1] if a.endswith("es") else a for a in adjektive]  # vietnamesisches -> vietnamesische
        return f"ein {wort}", " ".join(["das beste", *schwach, nomen])
    return f"einen {wort}", f"der beste {wort}"


def fragen(lead: ReportLead) -> list[dict]:
    wort = begriff(lead)
    unbestimmt, beste = _artikel(wort)
    ort = lead.ort or "meiner Stadt"
    return [
        {"typ": "allgemein", "frage": f"Ich suche {unbestimmt} in {ort}. Wen kannst du empfehlen?"},
        {"typ": "allgemein", "frage": f"Wer ist {beste} in {ort}?"},
        {"typ": "marke", "frage": f"Was weißt du über {lead.name} in {ort}? Öffnungszeiten, Bewertungen und Website?"},
    ]


def kern(name: str) -> str:
    """Normalisierter Kernname ohne Rechtsform/Inhaber, für die Suche im Antworttext."""
    return normalisiere(RECHTSFORM.sub("", name))


ALLGEMEINE_WOERTER = {"praxis", "dr", "med", "restaurant", "cafe", "bar", "bistro", "pizzeria", "salon", "studio",
                      "friseur", "physiotherapie", "zahnarzt", "zahnarztpraxis", "die", "der", "das", "und", "am", "im"}


def genannt(lead: ReportLead, text: str) -> bool:
    """Taucht der Betrieb im Text auf? Voller Kernname, die ersten zwei markanten Wörter oder die Domain."""
    t = normalisiere(text)
    kandidaten = [kern(lead.name)]
    woerter = [w for w in (normalisiere(x) for x in RECHTSFORM.sub("", lead.name).split()) if w and w not in ALLGEMEINE_WOERTER]
    if len(woerter) >= 2:
        kandidaten.append(woerter[0] + woerter[1])
    if lead.domain:
        kandidaten.append(normalisiere(lead.domain.split(".")[0]))
    return any(len(k) >= 6 and k in t for k in kandidaten) or (len(kandidaten[0]) >= 4 and kandidaten[0] in t)


def auswerten_antwort(content: list, lead: ReportLead) -> dict:
    """Liest Antworttext, Empfehlungen und Quellen-URLs aus den Content-Blöcken einer Messages-Antwort."""
    texte, quellen, suchen = [], [], 0
    for block in content:
        typ = getattr(block, "type", "")
        if typ == "text":
            texte.append(block.text or "")
            for c in getattr(block, "citations", None) or []:
                if getattr(c, "url", None):
                    quellen.append(c.url)
        elif typ == "web_search_tool_result":
            inhalt = getattr(block, "content", None)
            if isinstance(inhalt, list):
                suchen += 1
                quellen.extend(r.url for r in inhalt if getattr(r, "url", None))
    text = "\n".join(texte)
    m = re.search(r"EMPFEHLUNGEN:\s*(.+)", text)
    empfehlungen = [x.strip(" .*") for x in m.group(1).split(";") if x.strip(" .*")] if m else []
    hosts = [registrierte_domain(u) for u in dict.fromkeys(quellen)]
    return {
        "antwort": re.sub(r"\n?EMPFEHLUNGEN:.*", "", text).strip()[:1500],
        "empfehlungen": empfehlungen[:10],
        "quellen": hosts,
        "suchen": suchen,
        "genannt": genannt(lead, text),
        "eigene_quelle": bool(lead.domain) and lead.domain in hosts,
    }


def ki_stichprobe(lead: ReportLead) -> dict | None:
    """None ohne API-Schlüssel oder SDK; sonst Ergebnis je Frage plus Zusammenfassung."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic()
    modell = os.environ.get("KI_SUCHE_MODELL") or STANDARD_MODELL
    werkzeug = {"type": "web_search_20260209", "name": "web_search", "max_uses": 2, "allowed_callers": ["direct"],
                "user_location": {"type": "approximate", "city": lead.ort, "country": "DE",
                                  "timezone": "Europe/Berlin"} if lead.ort else {"type": "approximate", "country": "DE"}}
    ergebnisse = []
    for f in fragen(lead):
        nachrichten = [{"role": "user", "content": f["frage"]}]
        inhalt = []  # alle Blöcke der Antwort, auch aus pausierten Teilen (Suchergebnisse, Quellen)
        try:
            for _ in range(3):  # pause_turn: pausierte Antwort unverändert anhängen und fortsetzen lassen
                antwort = client.beta.messages.create(
                    model=modell, max_tokens=4000, system=SYSTEM, messages=nachrichten, tools=[werkzeug],
                    output_config={"effort": "low"},
                    # Bei einer Ablehnung durch Sicherheitsfilter serverseitig auf ein Ersatzmodell ausweichen
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                )
                inhalt += antwort.content
                if antwort.stop_reason != "pause_turn":
                    break
                nachrichten.append({"role": "assistant", "content": antwort.content})
        except anthropic.APIError as e:
            log.warning("KI-Stichprobe für %s fehlgeschlagen: %s", lead.name, e)
            ergebnisse.append({**f, "fehler": type(e).__name__})
            continue
        if antwort.stop_reason == "refusal":
            ergebnisse.append({**f, "fehler": "abgelehnt"})
            continue
        ergebnisse.append({**f, **auswerten_antwort(inhalt, lead)})
    gueltig = [e for e in ergebnisse if "fehler" not in e]
    allgemein = [e for e in gueltig if e["typ"] == "allgemein"]
    return {
        "modell": modell,
        "fragen": ergebnisse,
        "allgemein_genannt": sum(e["genannt"] for e in allgemein),
        "allgemein_gesamt": len(allgemein),
        "eigene_quelle": sum(e["eigene_quelle"] for e in gueltig),
        "gesamt": len(gueltig),
        "suchen": sum(e.get("suchen", 0) for e in gueltig),
    }
