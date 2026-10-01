"""Gesamtlauf für viele Leads aus einem Notion-Export: Berichte und PDFs lokal erzeugen, Fortschritt protokollieren.

Ist NOTION_TOKEN gesetzt, hängt das Skript jedes fertige PDF selbst im Leads-Board an (Report-PDF, -Score,
-Datum) – ohne weitere Schritte. Ohne Token entstehen die Berichte nur lokal; veröffentlicht wird dann über den
Notion-Connector (siehe connector_upload.py).

  python scripts/gesamtlauf.py output/berichte/leads_export.json [--max N] [--parallel 3] [--ki]

Reihenfolge: Potenzial Hoch → Mittel → Niedrig. Fortsetzbar: frische Messungen (≤ 14 Tage) werden
wiederverwendet, veröffentlichte Leads (veroeffentlicht.json bzw. Report-Datum im Export) übersprungen.
Jeder fertige Lead wird als Zeile in <out>/status.jsonl festgehalten.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

from agentur_leads.http import PoliteSession
from agentur_leads.report import lauf
from agentur_leads.report.quelle import AUSSCHLIESSEN, lead_aus_zeile

RANG = {"Hoch": 0, "Mittel": 1, "Niedrig": 2}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("export", help="JSON mit flachen Board-Zeilen (Liste oder {'results': [...]})")
    ap.add_argument("--out", default="output/berichte")
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--ki", action="store_true", help="KI-Stichprobe (braucht ANTHROPIC_API_KEY, kostet)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING, filename=out / "gesamtlauf.log",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    daten = json.loads(Path(args.export).read_text(encoding="utf-8"))
    zeilen = daten.get("results", []) if isinstance(daten, dict) else daten
    zeilen = [z for z in zeilen if (z.get("Website") or "").strip() and z.get("Qualität") not in AUSSCHLIESSEN
              and z.get("Status") not in ("Verloren", "Gewonnen")]
    zeilen.sort(key=lambda z: (RANG.get(z.get("Potenzial"), 3), z.get("Branche") or "", z.get("Name") or ""))
    leads = [lead_aus_zeile(z) for z in zeilen]
    if args.max:
        leads = leads[: args.max]
    opt = lauf.Optionen(out=out, lighthouse_laeufe=3, lighthouse_schnell=True, ki=args.ki)
    notion = None
    if os.environ.get("NOTION_TOKEN"):
        from agentur_leads.report.notion import Notion
        notion = Notion(os.environ["NOTION_TOKEN"])
    status, start = out / "status.jsonl", time.time()

    def fortschritt(i: int, n: int, b) -> None:
        zeile = {"i": i, "n": n, "slug": b.lead.slug, "name": b.lead.name, "page_id": b.lead.notion_page_id,
                 "gesamt": b.gesamt if b.bereiche else None, "pdf": str(b.pdf) if b.pdf else "",
                 "fehler": b.fehler, "datum": b.fakten.get("datum", ""), "sek": round(time.time() - start),
                 "veroeffentlicht": bool(notion and not b.fehler and (b.ordner / "veroeffentlicht.json").exists())}
        with status.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(zeile, ensure_ascii=False) + "\n")

    print(f"{len(leads)} Leads" + (" – PDFs werden per NOTION_TOKEN angehängt" if notion else ""), flush=True)
    lauf.lauf(leads, PoliteSession(), opt, notion=notion, veroeffentlichen_an=notion is not None,
              trockenlauf=notion is None, parallel=args.parallel, fortschritt=fortschritt)
    print("fertig", round(time.time() - start), "s", flush=True)


if __name__ == "__main__":
    main()
