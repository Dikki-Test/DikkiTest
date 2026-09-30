"""Berichtsinhalt als einfache Block-Liste – und zwei Ausgaben daraus:

- Notion-Markdown (z.B. zum Einfügen über den Notion-Connector oder als Vorschau)
- Notion-API-Blöcke (JSON für POST /v1/pages bzw. PATCH /v1/blocks/{id}/children)

Inline-Formatierung im Text: **fett**, *kursiv*, `code`. Alles andere ist reiner Text.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Union

from .modelle import Bereich, Massnahme
from .pruefung import PAKETE, befunde_kurz, hebel, kunden, nutzen, staerken


@dataclass
class H:  # Überschrift
    text: str
    ebene: int = 2
    toggle: list["Block"] = field(default_factory=list)  # nicht leer = aufklappbare Überschrift


@dataclass
class P:  # Absatz
    text: str


@dataclass
class Liste:
    punkte: list[str]
    nummeriert: bool = False


@dataclass
class Hinweis:  # Callout; zeilen[0] wird fett dargestellt, wenn titel=True
    icon: str
    farbe: str  # gray, blue, green, yellow, red, purple, orange
    zeilen: list[str]
    titel: bool = True


@dataclass
class Tabelle:
    kopf: list[str]
    zeilen: list[list[tuple[str, str]]]  # (Text, Farbe: "" | "green" | "red" | "yellow")


@dataclass
class Bild:
    pfad: Path
    unterschrift: str = ""


@dataclass
class Spalten:
    spalten: list[list["Block"]]  # nur Bild, P, Liste, Hinweis (Notion-API: max. 2 Ebenen je Anfrage)
    anteile: list[int] | None = None


@dataclass
class Trenner:
    pass


Block = Union[H, P, Liste, Hinweis, Tabelle, Bild, Spalten, Trenner]


# --- Bericht zusammenstellen -------------------------------------------------------------------

def _pruef_tabelle(b: Bereich) -> Tabelle:
    zeilen = []
    for p in b.punkte:
        ergebnis = ("✅ erfüllt", "green") if p.ok else ("❌ offen", "red") if p.ok is False else ("– nicht geprüft", "")
        zeilen.append([(p.text, ""), ergebnis, (p.befund, "")])
    return Tabelle(["Prüfpunkt", "Ergebnis", "Befund"], zeilen)


def baue_bericht(f: dict, bereiche: list[Bereich], gesamt: int, ms: list[Massnahme], bilder: dict[str, Path],
                 agentur: str, datum: dt.date) -> list[Block]:
    lead = f["lead"]
    branche = lead.get("branche", "")
    k = kunden(branche)
    r, nb = lead.get("google_rating"), lead.get("google_bewertungen")
    geprueft = ", ".join(dict.fromkeys(u.split("//")[-1].rstrip("/") for u in
                                       [lead.get("website", ""), f.get("website_url", "")] if u))
    bl: list[Block] = [Hinweis("📊", "gray", [
        f"**Online-Check für {lead['name']}**" + (f" · {lead['adresse']}" if lead.get("adresse") else ""),
        f"Erstellt von {agentur} am {datum.strftime('%d.%m.%Y')} · Geprüft: {geprueft}"], titel=False)]

    # Kopf: Gesamtnote + das Wichtigste
    if r and r >= 4.5 and gesamt < 60:
        headline = f"Ihre {k} sind begeistert. Ihre Website zeigt das noch nicht."
    elif gesamt < 50:
        headline = f"Ihr Online-Auftritt verschenkt {k}."
    elif gesamt < 75:
        headline = "Solide Basis – mit klaren Hebeln nach oben."
    else:
        headline = "Starker Auftritt – mit Feinschliff noch besser."
    punkte = ([f"**{_de(r)} ★ bei {nb} Google-Bewertungen**: Ihr Ruf ist {'stark' if r >= 4.5 else 'solide'}."]
              if r and nb else []) + befunde_kurz(bereiche, 3)
    rechts: list[Block] = [H("Das Wichtigste in Kürze", 3), P(f"**{headline}**"), Liste(punkte)]
    if "gesamtnote" in bilder:
        bl.append(Spalten([[Bild(bilder["gesamtnote"])], rechts], [40, 60]))
    else:
        bl += rechts
    if "bereiche" in bilder:
        bl.append(Bild(bilder["bereiche"]))
    hebel_liste = [f"**{m.text}** – {nutzen(m.key, branche)}" for m in hebel(bereiche, ms)]
    gut = staerken(bereiche)
    spalte_links = [Hinweis("🎯", "blue", ["Die größten Hebel", *[f"{i}. {h}" for i, h in enumerate(hebel_liste, 1)]])]
    spalte_rechts = [Hinweis("✅", "green", ["Was schon gut ist", *[f"• {g}" for g in gut]])] if gut else []
    bl.append(Spalten([spalte_links, spalte_rechts]) if spalte_rechts else spalte_links[0])
    bl.append(Trenner())

    # 1. Erster Eindruck
    bl.append(H("1. Erster Eindruck"))
    vs = f.get("vorschaltseite")
    if "handy" in bilder:
        bl.append(Bild(bilder["handy"], f"Wer {lead.get('website', '').split('//')[-1].rstrip('/')} aufruft, sieht "
                                        f"{_de(vs['verzoegerung_s'], 0)} Sekunden lang eine Vorschaltseite." if vs else
                       "Die Startseite auf dem Handy."))
    if "desktop" in bilder:
        bl.append(Bild(bilder["desktop"], "Die Startseite auf dem Computer."))
    if not ("handy" in bilder or "desktop" in bilder):
        bl.append(P("*Screenshots waren bei dieser Messung nicht möglich.*"))

    # 2.–7. Bereiche
    for nr, b in enumerate(bereiche, 2):
        bl.append(H(f"{nr}. {b.name}" + (f" · {b.score}/100" if b.score is not None else "")))
        if b.key == "technik":
            if "wartezeit" in bilder:
                bl.append(Bild(bilder["wartezeit"]))
            if "lighthouse" in bilder:
                bl.append(Bild(bilder["lighthouse"]))
            if "seitengewicht" in bilder:
                bl.append(Bild(bilder["seitengewicht"]))
        if b.key == "ki":
            bl += _ki_abschnitt(f, bilder, lead)
        if b.key == "social" and "vergleich" in bilder:
            bl.append(Bild(bilder["vergleich"]))
        bl.append(_pruef_tabelle(b))
        if b.erklaerung:
            bl.append(P(f"*{b.erklaerung}*"))
        if b.key == "sicherheit":
            bl.append(P("*Hinweise zu Datenschutz und Impressum sind technische Beobachtungen, keine Rechtsberatung.*"))
    bl.append(Trenner())

    # Maßnahmen und Angebot
    bl.append(H(f"{len(bereiche) + 2}. Maßnahmenplan"))
    if "massnahmen" in bilder:
        bl.append(Bild(bilder["massnahmen"]))
    stufe = lambda v: "klein" if v < 2.0 else "mittel" if v < 3.8 else "groß"  # noqa: E731
    bl.append(Tabelle(["Nr.", "Maßnahme", "Aufwand", "Wirkung", "Paket"],
                      [[(f"**{m.nr}**", ""), (m.text, ""), (stufe(m.aufwand), ""), (stufe(m.wirkung), ""), (PAKETE[m.paket], "")]
                       for m in ms]))
    bl.append(H(f"{len(bereiche) + 3}. Unser Angebot"))
    nr = {p: [m.nr for m in ms if m.paket == p] for p in (1, 2, 3)}
    spalten = []
    for p, icon, farbe, beschreibung, einheit in [
        (1, "🔧", "purple", "Schnelle Verbesserungen mit großer Wirkung auf der bestehenden Website.", "€"),
        (2, "🚀", "green", "Moderne Website, fürs Handy gebaut – inklusive Paket 1.", "€"),
        (3, "📸", "orange", "Laufende Pflege von Google-Profil, Fotos und Reels, monatlicher Google- und KI-Check.", "€ pro Monat"),
    ]:
        wort = "Maßnahme" if len(nr[p]) == 1 else "Maßnahmen"
        text = f"{wort} {_nummern(nr[p])}: {beschreibung}" if nr[p] else beschreibung
        spalten.append([Hinweis(icon, farbe, [PAKETE[p], text, "Dauer: (eintragen)", f"Preis: (eintragen) {einheit}"])])
    bl.append(Spalten(spalten))
    bl.append(Hinweis("📝", "yellow", ["Intern, vor dem Versand löschen:", "Dauer und Preise in den Paketen eintragen."]))

    # Methodik
    bl.append(H("Methodik & Quellen", 2, toggle=[Liste(_methodik(f, datum))]))
    return bl


def _nummern(n: list[int]) -> str:
    if len(n) > 2 and n == list(range(n[0], n[-1] + 1)):
        return f"{n[0]}–{n[-1]}"
    return ", ".join(map(str, n))


def _ki_abschnitt(f: dict, bilder: dict[str, Path], lead: dict) -> list[Block]:
    ki = f.get("ki_suche")
    if not ki or not ki.get("gesamt"):
        return [P("Immer mehr Menschen fragen KI-Assistenten wie ChatGPT statt Google. Ob eine KI Ihren Betrieb "
                  "empfiehlt, hängt davon ab, ob sie Ihre Website lesen und verstehen kann – das prüft die Tabelle unten.")]
    out: list[Block] = [P(f"Immer mehr Menschen fragen KI-Assistenten statt Google. Wir haben {len(ki['fragen'])} typische "
                          f"Fragen gestellt und ausgewertet, wen die KI nennt und welche Quellen sie nutzt.")]
    zeilen = []
    for q in ki["fragen"]:
        if "fehler" in q:
            zeilen.append([(f"„{q['frage']}“", ""), ("– Fehler", ""), ("–", ""), (q["fehler"], "")])
            continue
        andere = [e for e in q.get("empfehlungen", []) if lead["name"].lower() not in e.lower()]
        zeilen.append([(f"„{q['frage']}“", ""),
                       ("✅ ja", "green") if q["genannt"] else ("❌ nein", "red"),
                       ("✅ ja", "green") if q["eigene_quelle"] else ("❌ nein", "red"),
                       (", ".join(andere[:4]) + (" …" if len(andere) > 4 else "") if andere else "–", "")])
    out.append(Tabelle(["Frage", "Genannt?", "Eigene Website als Quelle?", "Andere genannte Betriebe"], zeilen))
    for key in ("ki_nennungen", "ki_quellen"):
        if key in bilder:
            out.append(Bild(bilder[key]))
    out.append(P(f"*Stichprobe am {f.get('datum', '')} mit Claude ({ki.get('modell')}) und Websuche, je Frage ein Abruf. "
                 "Antworten schwanken je nach Anbieter und Zeitpunkt.*"))
    return out


def _methodik(f: dict, datum: dt.date) -> list[str]:
    lh = (f.get("lighthouse") or {}).get("mobil") or {}
    zeilen = [f"Alle Messungen am {datum.strftime('%d.%m.%Y')}."]
    if lh.get("scores"):
        laeufe = f", Median aus {len(lh['laeufe'])} Messungen" if lh.get("laeufe") and len(lh["laeufe"]) > 1 else ""
        zeilen.append(f"**Ladezeit:** Google Lighthouse {lh.get('version', '')} ({lh.get('quelle', 'lokal gemessen')}{laeufe}), "
                      "simuliertes Mittelklasse-Smartphone mit 4G. Laborwerte, echte Ladezeiten schwanken.")
    zeilen += [
        "**Sicherheit:** Mozilla HTTP Observatory und eigene Auswertung der Server-Antworten.",
        "**Datenschutz:** automatischer Browser-Aufruf ohne Einwilligung; erfasst wurden aufgerufene Dienste und Cookies.",
        f"**SEO:** Auswertung von {len(f.get('seiten', []))} Seiten der Website.",
        "**KI-Auffindbarkeit:** robots.txt, Strukturdaten und llms.txt"
        + (", dazu eine Stichprobe mit einem KI-Assistenten mit Websuche." if f.get("ki_suche") else "."),
        "**Punkte:** je Bereich der Anteil erfüllter Prüfpunkte, bei „Ladezeit & Technik“ der Lighthouse-Leistungswert "
        "(Handy). Die Gesamtnote ist der Durchschnitt der Bereiche.",
        "Dieser Bericht ist keine Rechtsberatung.",
    ]
    return zeilen


def _de(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


# --- Ausgabe 1: Notion-Markdown -------------------------------------------------------------------

_ESC = re.compile(r"([\\~$\[\]<>{}|^])")


def _md_text(t: str) -> str:
    """Escaped Sonderzeichen, lässt **, * und ` stehen; Domains als Code, damit Notion sie nicht verlinkt."""
    t = _ESC.sub(r"\\\1", t)
    return re.sub(r"(?<![\w`/@])((?:https?://)?(?:[\w-]+\.)+(?:de|com|net|org|eu|info|at|ch)(?:/[\w./?=&%-]*)?)(?![\w`])",
                  r"`\1`", t)


MD_FARBE = {"gray": "gray_bg", "blue": "blue_bg", "green": "green_bg", "yellow": "yellow_bg", "red": "red_bg",
            "purple": "purple_bg", "orange": "orange_bg"}


def als_markdown(bloecke: list[Block], bildquelle: Callable[[Path], str], einzug: str = "") -> str:
    zeilen: list[str] = []
    for b in bloecke:
        if isinstance(b, H):
            zeilen.append(f"{einzug}{'#' * b.ebene} {_md_text(b.text)}" + (' {toggle="true"}' if b.toggle else ""))
            if b.toggle:
                zeilen.append(als_markdown(b.toggle, bildquelle, einzug + "\t"))
        elif isinstance(b, P):
            zeilen.append(einzug + _md_text(b.text))
        elif isinstance(b, Liste):
            zeilen += [f"{einzug}{f'{i}.' if b.nummeriert else '-'} {_md_text(x)}" for i, x in enumerate(b.punkte, 1)]
        elif isinstance(b, Hinweis):
            zeilen.append(f'{einzug}<callout icon="{b.icon}" color="{MD_FARBE[b.farbe]}">')
            for i, z in enumerate(b.zeilen):
                zeilen.append(f"{einzug}\t" + (f"**{_md_text(z)}**" if i == 0 and b.titel else _md_text(z)))
            zeilen.append(f"{einzug}</callout>")
        elif isinstance(b, Tabelle):
            zeilen.append(f'{einzug}<table header-row="true">')
            for zeile in [[(k, "") for k in b.kopf]] + b.zeilen:
                zeilen.append(f"{einzug}\t<tr>")
                for text, farbe in zeile:
                    attr = f' color="{MD_FARBE[farbe]}"' if farbe else ""
                    zeilen.append(f"{einzug}\t\t<td{attr}>{_md_text(text)}</td>")
                zeilen.append(f"{einzug}\t</tr>")
            zeilen.append(f"{einzug}</table>")
        elif isinstance(b, Bild):
            zeilen.append(f'{einzug}<image src="{bildquelle(b.pfad)}">{_md_text(b.unterschrift)}</image>')
        elif isinstance(b, Spalten):
            zeilen.append(f"{einzug}<columns>")
            for i, spalte in enumerate(b.spalten):
                anteil = f' ratio="{b.anteile[i]}"' if b.anteile else ""
                zeilen.append(f"{einzug}\t<column{anteil}>")
                zeilen.append(als_markdown(spalte, bildquelle, einzug + "\t\t"))
                zeilen.append(f"{einzug}\t</column>")
            zeilen.append(f"{einzug}</columns>")
        elif isinstance(b, Trenner):
            zeilen.append(f"{einzug}---")
    return "\n".join(zeilen)


# --- Ausgabe 2: Notion-API-Blöcke --------------------------------------------------------------------

API_FARBE = {"gray": "gray_background", "blue": "blue_background", "green": "green_background",
             "yellow": "yellow_background", "red": "red_background", "purple": "purple_background",
             "orange": "orange_background"}
_INLINE = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`")


def rich_text(text: str, farbe: str = "") -> list[dict]:
    """Mini-Markdown (**fett**, *kursiv*, `code`) -> Notion rich_text (Stücke ≤ 2000 Zeichen)."""
    teile: list[tuple[str, dict]] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            teile.append((text[pos:m.start()], {}))
        if m.group(1) is not None:
            teile.append((m.group(1), {"bold": True}))
        elif m.group(2) is not None:
            teile.append((m.group(2), {"italic": True}))
        else:
            teile.append((m.group(3), {"code": True}))
        pos = m.end()
    if pos < len(text):
        teile.append((text[pos:], {}))
    out = []
    for inhalt, anno in teile:
        for i in range(0, len(inhalt), 2000):
            stueck = {"type": "text", "text": {"content": inhalt[i:i + 2000]}}
            annotations = {**anno, **({"color": API_FARBE[farbe]} if farbe else {})}
            if annotations:
                stueck["annotations"] = annotations
            out.append(stueck)
    return out[:100]


def _block(typ: str, inhalt: dict) -> dict:
    return {"object": "block", "type": typ, typ: inhalt}


def als_notion_bloecke(bloecke: list[Block], upload_id: Callable[[Path], str]) -> list[dict]:
    out: list[dict] = []
    for b in bloecke:
        if isinstance(b, H):
            typ = f"heading_{min(max(b.ebene, 1), 3)}"
            inhalt = {"rich_text": rich_text(b.text)}
            if b.toggle:
                inhalt["is_toggleable"] = True
                inhalt["children"] = als_notion_bloecke(b.toggle, upload_id)
            out.append(_block(typ, inhalt))
        elif isinstance(b, P):
            out.append(_block("paragraph", {"rich_text": rich_text(b.text)}))
        elif isinstance(b, Liste):
            typ = "numbered_list_item" if b.nummeriert else "bulleted_list_item"
            out += [_block(typ, {"rich_text": rich_text(x)}) for x in b.punkte]
        elif isinstance(b, Hinweis):
            text = "\n".join(f"**{z}**" if i == 0 and b.titel else z for i, z in enumerate(b.zeilen))
            out.append(_block("callout", {"rich_text": rich_text(text), "icon": {"type": "emoji", "emoji": b.icon},
                                          "color": API_FARBE[b.farbe]}))
        elif isinstance(b, Tabelle):
            zeilen = [[(k, "") for k in b.kopf]] + b.zeilen
            out.append(_block("table", {
                "table_width": len(b.kopf), "has_column_header": True, "has_row_header": False,
                "children": [_block("table_row", {"cells": [rich_text(t, farbe) for t, farbe in z]}) for z in zeilen]}))
        elif isinstance(b, Bild):
            inhalt = {"type": "file_upload", "file_upload": {"id": upload_id(b.pfad)}}
            if b.unterschrift:
                inhalt["caption"] = rich_text(b.unterschrift)
            out.append(_block("image", inhalt))
        elif isinstance(b, Spalten):
            out.append(_block("column_list", {"children": [
                _block("column", {"children": als_notion_bloecke(spalte, upload_id)}) for spalte in b.spalten]}))
        elif isinstance(b, Trenner):
            out.append(_block("divider", {}))
    return out


def bilder_in(bloecke: list[Block]) -> list[Path]:
    pfade: list[Path] = []
    for b in bloecke:
        if isinstance(b, Bild):
            pfade.append(b.pfad)
        elif isinstance(b, Spalten):
            for spalte in b.spalten:
                pfade += bilder_in(spalte)
        elif isinstance(b, H) and b.toggle:
            pfade += bilder_in(b.toggle)
    return pfade
