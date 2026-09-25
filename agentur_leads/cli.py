"""Kommandozeile.

Beispiele:
  agentur-leads finden  --region "Münster" --radius 15 --segment handwerk makler
  agentur-leads pruefen --leads output/leads.json
  agentur-leads start   --region "Münster" --radius 15 --ki-fotos
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import export
from .discovery import dedupe
from .discovery import google_places, osm
from .http import PoliteSession
from .models import HANDWERK, MAKLER, Lead
from .pipeline import audit_alle, lade_leads, speichere_leads


def _lade_env(pfad: Path = Path(".env")) -> None:
    """Minimaler .env-Loader (ohne Zusatzpaket)."""
    if not pfad.exists():
        return
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if zeile and not zeile.startswith("#") and "=" in zeile:
            k, v = zeile.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def finden(args: argparse.Namespace, http: PoliteSession) -> list[Lead]:
    leads: list[Lead] = []
    if not args.nur_google:
        print(f"→ OpenStreetMap: {args.region} (+{args.radius} km) …", file=sys.stderr)
        leads += osm.discover(http, args.region, args.radius, args.segment)
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if key:
        print("→ Google Places …", file=sys.stderr)
        leads += google_places.discover(http, key, args.region, args.segment)
    elif args.nur_google:
        sys.exit("GOOGLE_PLACES_API_KEY fehlt (.env)")
    leads = dedupe(leads)
    if args.max:
        leads = leads[: args.max]
    print(f"✓ {len(leads)} Betriebe gefunden "
          f"({sum(not x.website for x in leads)} ohne bekannte Website)", file=sys.stderr)
    return leads


def pruefen(args: argparse.Namespace, http: PoliteSession, leads: list[Lead]) -> None:
    out = Path(args.out)

    def fortschritt(i: int, n: int, lead: Lead) -> None:
        print(f"  [{i}/{n}] {lead.name} ({lead.website or 'keine Website'})", file=sys.stderr)

    ergebnisse = audit_alle(
        http, leads, out / "ergebnisse.json",
        ig_token=os.environ.get("IG_GRAPH_TOKEN", ""),
        ig_id=os.environ.get("IG_BUSINESS_ACCOUNT_ID", ""),
        ki_fotos=args.ki_fotos, max_fotos=args.max_fotos, fortschritt=fortschritt,
    )
    export.export_csv(ergebnisse, out / "leads.csv")
    export.export_report(ergebnisse, out / "report.md", getattr(args, "region", ""))
    a = sum(e.prioritaet == "A" for e in ergebnisse)
    print(f"✓ {len(ergebnisse)} geprüft, {a} A-Leads → {out / 'leads.csv'}, {out / 'report.md'}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    _lade_env()
    p = argparse.ArgumentParser(prog="agentur-leads", description="Leads für Web- & Social-Agentur finden und prüfen")
    p.add_argument("--delay", type=float, default=1.0, help="Sekunden zwischen Anfragen je Host (Default 1.0)")
    p.add_argument("--ignoriere-robots", action="store_true", help="robots.txt nicht beachten (nicht empfohlen)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def region_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--region", required=True, help='z.B. "Münster" oder "48143 Münster"')
        sp.add_argument("--radius", type=float, default=15, help="Radius in km (OSM), Default 15")
        sp.add_argument("--segment", nargs="+", choices=[HANDWERK, MAKLER], default=[HANDWERK, MAKLER])
        sp.add_argument("--nur-google", action="store_true", help="nur Google Places statt OSM")
        sp.add_argument("--max", type=int, default=0, help="max. Anzahl Leads (0 = alle)")

    def audit_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--out", default="output", help="Ausgabeordner (Default: output)")
        sp.add_argument("--ki-fotos", action="store_true", help="Makler-Fotos zusätzlich mit Claude bewerten")
        sp.add_argument("--max-fotos", type=int, default=12, help="Fotos je Makler prüfen (Default 12)")

    sp = sub.add_parser("finden", help="Betriebe in einer Region finden → leads.json")
    region_args(sp)
    sp.add_argument("--out", default="output")

    sp = sub.add_parser("pruefen", help="leads.json auditieren → ergebnisse.json, leads.csv, report.md")
    sp.add_argument("--leads", default="output/leads.json")
    audit_args(sp)

    sp = sub.add_parser("start", help="finden + pruefen in einem Lauf")
    region_args(sp)
    audit_args(sp)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    http = PoliteSession(delay_s=args.delay, respect_robots=not args.ignoriere_robots)

    if args.cmd == "finden":
        leads = finden(args, http)
        speichere_leads(Path(args.out) / "leads.json", leads)
    elif args.cmd == "pruefen":
        pruefen(args, http, lade_leads(Path(args.leads)))
    else:
        leads = finden(args, http)
        speichere_leads(Path(args.out) / "leads.json", leads)
        pruefen(args, http, leads)


if __name__ == "__main__":
    main()
