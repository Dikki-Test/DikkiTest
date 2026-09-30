"""Diagramme und Screenshot-Collagen für den Bericht (PNG/JPEG, 200 dpi).

Farben: Ampel wie Lighthouse (rot < 50, orange < 90, grün ≥ 90), der Betrieb selbst in Indigo.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Wedge  # noqa: E402

from .modelle import Massnahme  # noqa: E402

FONTS = Path(__file__).parent / "fonts"
for _f in FONTS.glob("*.ttf"):
    font_manager.fontManager.addfont(str(_f))
plt.rcParams.update({
    "font.family": ["Inter", "DejaVu Sans"], "font.size": 11,
    "axes.edgecolor": "#E5E7EB", "axes.labelcolor": "#374151", "xtick.color": "#6B7280", "ytick.color": "#374151",
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
})
INK, MUTED, TRACK = "#111827", "#6B7280", "#F1F5F9"
GOOD, MID, BAD = "#16A34A", "#F59E0B", "#DC2626"
ACCENT, OTHER = "#4F46E5", "#CBD5E1"
PAKET_FARBE = {1: ACCENT, 2: "#0F766E", 3: "#B45309"}
DPI = 200


def ampel(v: float) -> str:
    return GOOD if v >= 90 else MID if v >= 50 else BAD


def de(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def _speichern(fig, pfad: Path) -> Path:
    fig.savefig(pfad, dpi=DPI, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    return pfad


def _achsen_schlank(ax, links: bool = True) -> None:
    for s in ("top", "right", "left") if links else ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)


def gesamtnote(wert: int, pfad: Path) -> Path:
    fig, ax = plt.subplots(figsize=(4.6, 3.1))
    ax.set_xlim(-1.15, 1.15), ax.set_ylim(-0.42, 1.12), ax.axis("off"), ax.set_aspect("equal")
    ax.add_patch(Wedge((0, 0), 1, 0, 180, width=0.22, color=TRACK))
    ax.add_patch(Wedge((0, 0), 1, 180 - 180 * wert / 100, 180, width=0.22, color=ampel(wert)))
    ax.text(0, 0.18, f"{wert}", ha="center", va="center", fontsize=46, fontweight="bold", color=INK)
    ax.text(0, -0.13, "von 100 Punkten", ha="center", va="center", fontsize=11, color=MUTED)
    ax.text(-0.89, -0.1, "0", ha="center", fontsize=9, color=MUTED)
    ax.text(0.89, -0.1, "100", ha="center", fontsize=9, color=MUTED)
    ax.text(0, -0.36, "Gesamtnote Online-Auftritt", ha="center", fontsize=12, fontweight="bold", color=INK)
    return _speichern(fig, pfad)


def bereiche(werte: list[tuple[str, int]], pfad: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(werte) + 0.7))
    namen, zahlen = [w[0] for w in werte][::-1], [w[1] for w in werte][::-1]
    ax.barh(namen, [100] * len(zahlen), color=TRACK, height=0.62)
    ax.barh(namen, zahlen, color=[ampel(v) for v in zahlen], height=0.62)
    for i, v in enumerate(zahlen):
        ax.text(v + 1.5, i, f"{v}", va="center", fontsize=12, fontweight="bold", color=INK)
    ax.set_xlim(0, 100), ax.set_xticks([0, 50, 90, 100]), ax.tick_params(axis="y", labelsize=11.5)
    _achsen_schlank(ax)
    ax.axvline(90, color=GOOD, lw=1, ls=(0, (3, 3)))
    ax.text(90, len(zahlen) - 0.35, "Ziel ≥ 90", color=GOOD, fontsize=9, ha="center")
    ax.set_title("Ergebnis nach Bereichen (0–100 Punkte)", loc="left", fontsize=13, fontweight="bold", color=INK, pad=12)
    return _speichern(fig, pfad)


def lighthouse_ringe(mobil: dict, desktop: dict, titel: str, pfad: Path) -> Path:
    namen = [("performance", "Ladezeit"), ("accessibility", "Barrierefreiheit"),
             ("best-practices", "Best Practices"), ("seo", "SEO-Grundlagen")]
    fig, axes = plt.subplots(1, 4, figsize=(8.6, 2.9))
    for ax, (k, name) in zip(axes, namen):
        v = mobil.get(k, 0)
        ax.set_xlim(-1.2, 1.2), ax.set_ylim(-1.75, 1.2), ax.axis("off"), ax.set_aspect("equal")
        ax.add_patch(Circle((0, 0), 1, color=ampel(v), alpha=0.12))
        ax.add_patch(Wedge((0, 0), 1, 90 - 360 * v / 100, 90, width=0.16, color=ampel(v)))
        ax.text(0, 0, f"{v}", ha="center", va="center", fontsize=24, fontweight="bold", color=ampel(v))
        ax.text(0, -1.3, name, ha="center", fontsize=11, fontweight="bold", color=INK)
        if k in desktop:
            ax.text(0, -1.68, f"Desktop: {desktop[k]}", ha="center", fontsize=9.5, color=MUTED)
    fig.suptitle(titel, x=0.02, ha="left", fontsize=13, fontweight="bold", color=INK)
    return _speichern(fig, pfad)


def wartezeit(vorschalt_s: float | None, lcp_mobil: float, lcp_desktop: float | None, pfad: Path) -> Path:
    zeilen = [("Handy", lcp_mobil)] + ([("Computer", lcp_desktop)] if lcp_desktop is not None else [])
    v = vorschalt_s or 0
    maximum = max(10, v + max(z[1] for z in zeilen) + 1.8)
    fig, ax = plt.subplots(figsize=(8.6, 1.1 + 0.9 * len(zeilen)))
    for i, (name, lcp) in enumerate(zeilen[::-1]):
        if v:
            ax.barh(i, v, color=BAD, height=0.5)
            ax.text(v / 2, i, "Vorschaltseite", ha="center", va="center", color="white", fontsize=9.5, fontweight="bold")
        ax.barh(i, lcp, left=v, color=MID if lcp > 2.5 else GOOD, height=0.5)
        ax.text(v + lcp / 2, i, f"Laden {de(lcp)} s", ha="center", va="center", color=INK, fontsize=9.5, fontweight="bold")
        ax.text(v + lcp + 0.12, i, f"≈ {de(v + lcp)} s", va="center", fontsize=12, fontweight="bold", color=INK)
    ax.set_yticks(range(len(zeilen))), ax.set_yticklabels([z[0] for z in zeilen[::-1]], fontsize=11.5)
    ax.axvline(2.5, color=GOOD, lw=1.6, ls=(0, (4, 3)))
    ax.text(2.55, len(zeilen) - 0.58, "Google-Empfehlung: Hauptinhalt nach ≤ 2,5 s", color=GOOD, fontsize=9.5, va="center")
    ax.set_xlim(0, maximum), ax.set_ylim(-0.5, len(zeilen) - 0.4)
    ax.set_xlabel("Sekunden bis das Hauptbild sichtbar ist (Labormessung)", fontsize=9.5, color=MUTED)
    _achsen_schlank(ax)
    titel = "So lange wartet ein Besucher, bis er Ihre Seite sieht" if v else "So lange dauert es, bis Ihre Seite sichtbar ist"
    ax.set_title(titel, loc="left", fontsize=13, fontweight="bold", color=INK, pad=10)
    return _speichern(fig, pfad)


def seitengewicht(gewicht_kb: dict, einsparung_kb: float, pfad: Path) -> Path:
    teile = [("Bilder", gewicht_kb.get("image", 0), "#EF4444"), ("Skripte", gewicht_kb.get("script", 0), "#6366F1"),
             ("Design (CSS)", gewicht_kb.get("stylesheet", 0), "#14B8A6"), ("Schriften", gewicht_kb.get("font", 0), "#A855F7"),
             ("Text (HTML)", gewicht_kb.get("document", 0), "#F59E0B")]
    teile = [t for t in teile if t[1] > 0] or [("Sonstiges", gewicht_kb.get("total", 1), OTHER)]
    gesamt = sum(t[1] for t in teile)
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    ax.pie([t[1] for t in teile], colors=[t[2] for t in teile], startangle=90, counterclock=False,
           wedgeprops=dict(width=0.3, edgecolor="white", linewidth=2))
    ax.text(0, 0.1, f"{de(gesamt / 1024)} MB", ha="center", va="center", fontsize=20, fontweight="bold", color=INK)
    ax.text(0, -0.2, "Startseite", ha="center", va="center", fontsize=10, color=MUTED)
    labels = [f"{t[0]}: " + (f"{de(t[1] / 1024, 2)} MB ({round(100 * t[1] / gesamt)} %)" if t[1] > 1000 else f"{round(t[1])} KB")
              for t in teile]
    ax.legend(labels, loc="center left", bbox_to_anchor=(1.0, 0.55), frameon=False, fontsize=10.5)
    if einsparung_kb >= 200:
        ax.text(1.28, -0.62, f"Einsparbar: ca. {de(einsparung_kb / 1024)} MB\ndurch moderne Bildformate (WebP)",
                transform=ax.transData, fontsize=10, color=BAD, fontweight="bold", va="top")
    ax.set_title("Datenmenge beim Aufruf", loc="left", fontsize=13, fontweight="bold", color=INK)
    return _speichern(fig, pfad)


def ki_quellen(ki: dict, eigene_domain: str, pfad: Path) -> Path:
    c = Counter(h for f in ki["fragen"] if "quellen" in f for h in f["quellen"])
    top = c.most_common(10)
    namen, werte = [t[0] for t in top][::-1], [t[1] for t in top][::-1]
    fig, ax = plt.subplots(figsize=(8, 0.4 * len(namen) + 1.2))
    ax.barh(namen, werte, color=[ACCENT if n == eigene_domain else OTHER for n in namen], height=0.62)
    for i, w in enumerate(werte):
        ax.text(w + 0.1, i, str(w), va="center", fontsize=10.5, fontweight="bold", color=INK)
    ax.set_yticks(range(len(namen))), ax.set_yticklabels(["Ihre Website" if n == eigene_domain else n for n in namen])
    for t in ax.get_yticklabels():
        if t.get_text() == "Ihre Website":
            t.set_color(ACCENT), t.set_fontweight("bold")
    _achsen_schlank(ax)
    ax.set_xticks([])
    ax.set_title(f"Welche Seiten die KI-Suche als Quelle nutzt\n{sum(c.values())} Quellen-Links bei {len(ki['fragen'])} Fragen",
                 loc="left", fontsize=13, fontweight="bold", color=INK)
    return _speichern(fig, pfad)


def ki_nennungen(ki: dict, name: str, pfad: Path) -> Path:
    allgemein = [f for f in ki["fragen"] if f.get("typ") == "allgemein" and "empfehlungen" in f]
    c = Counter(e for f in allgemein for e in dict.fromkeys(f["empfehlungen"]))
    c[name] = sum(bool(f.get("genannt")) for f in allgemein)
    for e in [e for e in c if e != name and name.lower() in e.lower()]:
        del c[e]  # die eigene Nennung nicht doppelt zählen
    top = sorted(c.items(), key=lambda x: (-x[1], x[0] != name, x[0]))[:10][::-1]
    namen, werte = [t[0] for t in top], [t[1] for t in top]
    n = len(allgemein)
    fig, ax = plt.subplots(figsize=(8, 0.4 * len(namen) + 1.2))
    ax.barh(namen, werte, color=[ACCENT if x == name else OTHER for x in namen], height=0.62)
    for i, w in enumerate(werte):
        ax.text(w + 0.04, i, f"{w} von {n}", va="center", fontsize=10, color=INK)
    for t in ax.get_yticklabels():
        if t.get_text() == name:
            t.set_color(ACCENT), t.set_fontweight("bold")
    ax.set_xlim(0, n + 0.8), ax.set_xticks([])
    _achsen_schlank(ax)
    ax.set_title("Wen die KI-Suche bei allgemeinen Fragen empfiehlt", loc="left", fontsize=13, fontweight="bold", color=INK)
    return _speichern(fig, pfad)


def vergleich(zeilen: list[dict], name: str, titel: str, pfad: Path) -> Path:
    """Google-Bewertungen im Vergleich (zeilen: name, rating, reviews)."""
    zeilen = sorted(zeilen, key=lambda z: -z["rating"])[::-1]
    fig, ax = plt.subplots(figsize=(8.2, 0.5 * len(zeilen) + 1.0))
    untergrenze = min(3.5, min(z["rating"] for z in zeilen) - 0.2)
    for i, z in enumerate(zeilen):
        farbe = ACCENT if z["name"] == name else OTHER
        ax.barh(i, z["rating"] - untergrenze, left=untergrenze, color=farbe, height=0.6)
        ax.text(z["rating"] + 0.015, i, f"{de(z['rating'])} ★  ({format(z['reviews'], ',').replace(',', '.')} Bew.)",
                va="center", fontsize=9.5, color=INK)
    ax.set_yticks(range(len(zeilen))), ax.set_yticklabels([z["name"] for z in zeilen], fontsize=10.5)
    for t in ax.get_yticklabels():
        if t.get_text() == name:
            t.set_color(ACCENT), t.set_fontweight("bold")
    ax.set_xlim(untergrenze, 5.45), ax.set_xticks([])
    _achsen_schlank(ax)
    ax.spines["bottom"].set_visible(False)
    ax.set_title(titel, loc="left", fontsize=13, fontweight="bold", color=INK)
    return _speichern(fig, pfad)


def _freier_platz(x: float, y: float, belegt: list[tuple[float, float]], rx: float = 0.36, ry: float = 0.5) -> tuple[float, float]:
    """Nächster freier Platz um (x, y) im selben Quadranten (Grenze bei 3).

    rx/ry: Punktdurchmesser plus Luft in Achseneinheiten; die y-Achse ist im Bild gestaucht, daher ry > rx.
    """
    richtungen = [(1, 0), (-1, 0), (0, -1), (0, 1), (0.7, -0.7), (-0.7, -0.7), (0.7, 0.7), (-0.7, 0.7)]
    for r in range(5):
        for dx, dy in richtungen[: 1 if r == 0 else None]:
            nx, ny = x + dx * r * rx, y + dy * r * ry
            if ((nx < 3) != (x < 3) or (ny < 3) != (y < 3) or abs(nx - 3) < 0.22 or abs(ny - 3) < 0.3
                    or not (0.8 <= nx <= 5.2 and 0.8 <= ny <= 4.8)):
                continue
            if all(((nx - a) / rx) ** 2 + ((ny - b) / ry) ** 2 >= 1 for a, b in belegt):
                return nx, ny
    return x, y


def massnahmen_matrix(ms: list[Massnahme], pfad: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    ax.set_xlim(0.5, 5.5), ax.set_ylim(0.5, 5.5)
    for (x, y), farbe in [((0.55, 3.05), "#DCFCE7"), ((3.05, 3.05), "#E0E7FF"), ((0.55, 0.55), "#F8FAFC"), ((3.05, 0.55), "#F8FAFC")]:
        ax.add_patch(FancyBboxPatch((x, y), 2.4, 2.4, boxstyle="round,pad=0,rounding_size=0.08", color=farbe, lw=0))
    ax.text(0.7, 5.3, "SOFORT UMSETZEN", fontsize=9, fontweight="bold", color=GOOD, va="top")
    ax.text(3.2, 5.3, "GROSSE HEBEL – PLANEN", fontsize=9, fontweight="bold", color=ACCENT, va="top")
    ax.text(0.7, 0.72, "NEBENBEI", fontsize=9, fontweight="bold", color=MUTED)
    ax.text(3.2, 0.72, "SPÄTER", fontsize=9, fontweight="bold", color=MUTED)
    belegt: list[tuple[float, float]] = []
    for m in ms:
        x, y = _freier_platz(m.aufwand, min(m.wirkung, 4.75), belegt)
        belegt.append((x, y))
        ax.scatter([x], [y], s=620, color=PAKET_FARBE[m.paket], zorder=3, linewidths=0)
        ax.text(x, y, str(m.nr), ha="center", va="center", color="white", fontsize=10, fontweight="bold", zorder=4)
    ax.set_xticks([1, 3, 5]), ax.set_xticklabels(["klein", "mittel", "groß"])
    ax.set_yticks([1, 3, 5]), ax.set_yticklabels(["klein", "mittel", "groß"])
    ax.set_xlabel("Aufwand", fontsize=11, color=INK), ax.set_ylabel("Wirkung", fontsize=11, color=INK)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    pakete = sorted({m.paket for m in ms})
    namen = {1: "Paket 1 · Sofort-Fix", 2: "Paket 2 · Neue Website", 3: "Paket 3 · Sichtbarkeit & Content"}
    ax.legend(handles=[Line2D([0], [0], marker="o", color="w", markerfacecolor=PAKET_FARBE[p], markersize=11, label=namen[p])
                       for p in pakete], loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=3, frameon=False, fontsize=9.5)
    ax.set_title("Maßnahmen nach Aufwand und Wirkung", loc="left", fontsize=13, fontweight="bold", color=INK, pad=10)
    return _speichern(fig, pfad)


# --- Screenshot-Collagen -------------------------------------------------------------------

def _telefon(pfad: Path, breite: int = 420):
    from PIL import Image, ImageDraw
    im = Image.open(pfad).convert("RGB")
    im = im.crop((0, 0, im.width, min(im.height, int(im.width * 844 / 390))))
    im = im.resize((breite, int(im.height * breite / im.width)), Image.LANCZOS)
    rand = 14
    rahmen = Image.new("RGB", (im.width + 2 * rand, im.height + 2 * rand), "#111827")
    maske = Image.new("L", im.size, 0)
    ImageDraw.Draw(maske).rounded_rectangle((0, 0, im.width - 1, im.height - 1), 28, fill=255)
    rahmen.paste(im, (rand, rand), maske)
    rmaske = Image.new("L", rahmen.size, 0)
    ImageDraw.Draw(rmaske).rounded_rectangle((0, 0, rahmen.width - 1, rahmen.height - 1), 40, fill=255)
    return rahmen, rmaske


def handy_collage(mobil: Path, pfad: Path, vorschalt: Path | None = None, verzoegerung: float | None = None) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    fett = ImageFont.truetype(str(FONTS / "Inter-700.ttf"), 30)
    b, bm = _telefon(mobil)
    if vorschalt and vorschalt.exists():
        a, am = _telefon(vorschalt)
        breite, hoehe = a.width + b.width + 220, max(a.height, b.height) + 150
        c = Image.new("RGB", (breite, hoehe), "white")
        d = ImageDraw.Draw(c)
        c.paste(a, (40, 100), am)
        c.paste(b, (breite - 40 - b.width, 100), bm)
        sek = de(verzoegerung or 0, 0)
        d.text((40 + a.width // 2, 40), f"Sekunde 0–{sek}: Vorschaltseite", font=fett, fill=BAD, anchor="mm")
        d.text((breite - 40 - b.width // 2, 40), "danach: die eigentliche Website", font=fett, fill=INK, anchor="mm")
        mx, my = breite // 2, 100 + a.height // 2
        d.polygon([(mx - 40, my - 34), (mx + 36, my), (mx - 40, my + 34)], fill="#9CA3AF")
        d.text((mx, my + 70), f"{sek} s", font=fett, fill=MUTED, anchor="mm")
    else:
        titel = "So sieht Ihre Website auf dem Handy aus"
        breite = max(b.width, round(fett.getlength(titel))) + 80
        c = Image.new("RGB", (breite, b.height + 120), "white")
        ImageDraw.Draw(c).text((breite // 2, 40), titel, font=fett, fill=INK, anchor="mm")
        c.paste(b, ((breite - b.width) // 2, 90), bm)
    c.save(pfad, quality=85)
    return pfad


def desktop_rahmen(desktop: Path, url: str, pfad: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(desktop).convert("RGB").resize((1200, 750), Image.LANCZOS)
    leiste = 64
    c = Image.new("RGB", (im.width + 2, im.height + leiste + 2), "#E5E7EB")
    d = ImageDraw.Draw(c)
    d.rectangle((1, 1, im.width, leiste), fill="#F3F4F6")
    for i, farbe in enumerate(["#EF4444", "#F59E0B", "#22C55E"]):
        d.ellipse((22 + i * 28, 24, 38 + i * 28, 40), fill=farbe)
    d.rounded_rectangle((130, 14, im.width - 40, 50), 16, fill="white")
    d.text((150, 32), url.split("//")[-1].rstrip("/"), font=ImageFont.truetype(str(FONTS / "Inter-400.ttf"), 20),
           fill="#374151", anchor="lm")
    c.paste(im, (1, leiste + 1))
    c.save(pfad, quality=85)
    return pfad
