"""Kommandozeile.

Beispiele:
  agentur-leads finden  --region "Münster" --radius 15 --segment handwerk makler
  agentur-leads pruefen --leads output/leads.json
  agentur-leads start   --region "Münster" --radius 15 --ki-fotos
  agentur-leads report  --url https://beispiel.de --name "Beispiel GmbH" --branche Handwerk --ort Münster
  agentur-leads report  --notion --veroeffentlichen --max 20
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


def report(args: argparse.Namespace, http: PoliteSession) -> None:
    """Verkaufsberichte erzeugen – für eine URL, eine Ergebnisdatei oder alle Leads aus Notion."""
    import datetime as dt

    from .report import lauf
    from .report.modelle import ReportLead
    from .report.quelle import lead_aus_notion, leads_aus_datei, notion_filter

    token = os.environ.get("NOTION_TOKEN", "")
    notion = None
    if args.notion or args.veroeffentlichen:
        if not token:
            sys.exit("NOTION_TOKEN fehlt (.env oder Umgebungsvariable) – siehe README, Abschnitt Verkaufsberichte")
        from .report.notion import Notion
        notion = Notion(token)

    if args.url:
        leads = [ReportLead(name=args.name or args.url, website=args.url, branche=args.branche, kategorie=args.kategorie,
                            ort=args.ort, adresse=args.adresse, google_rating=args.rating,
                            google_bewertungen=args.bewertungen, kueche=args.kueche)]
    elif args.notion:
        seiten = notion.leads(args.datenquelle)
        leads = [lead_aus_notion(x) for x in seiten if notion_filter(x)]
        print(f"→ {len(leads)} Leads mit Website aus Notion ({len(seiten) - len(leads)} ausgeschlossen)", file=sys.stderr)
    else:
        leads = leads_aus_datei(Path(args.leads))
    if args.max:
        leads = leads[: args.max]
    if args.veroeffentlichen and args.notion:
        notion.felder_sicherstellen(args.datenquelle)

    opt = lauf.Optionen(out=Path(args.out), agentur=args.agentur, max_seiten=args.max_seiten,
                        lighthouse_laeufe=args.lighthouse_laeufe, browser=not args.ohne_browser,
                        lighthouse=not args.ohne_lighthouse, observatory=not args.ohne_observatory,
                        ki=not args.ohne_ki, neu_messen=args.neu, datum=dt.date.today())

    def fortschritt(i: int, n: int, b) -> None:
        status = b.fehler or f"{b.gesamt}/100" + (f" → {b.notion_url}" if b.notion_url else "")
        print(f"  [{i}/{n}] {b.lead.name}: {status}", file=sys.stderr)

    berichte = lauf.lauf(leads, http, opt, notion=notion, eltern_id=args.notion_seite,
                         veroeffentlichen_an=args.veroeffentlichen, trockenlauf=args.trockenlauf,
                         parallel=args.parallel, fortschritt=fortschritt)
    ok = [b for b in berichte if not b.fehler]
    print(f"✓ {len(ok)} Berichte erstellt, {len(berichte) - len(ok)} mit Fehlern → {opt.out / 'uebersicht.csv'}",
          file=sys.stderr)


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

    sp = sub.add_parser("report", help="Verkaufsbericht (Website, SEO, KI-Auffindbarkeit) mit Diagrammen, optional nach Notion")
    quelle = sp.add_mutually_exclusive_group(required=True)
    quelle.add_argument("--url", help="einzelne Website prüfen")
    quelle.add_argument("--notion", action="store_true", help="alle Leads mit Website aus dem Notion-Leads-Board")
    quelle.add_argument("--leads", help="Ergebnisdatei des Lead-Finders (leads.json / ergebnisse.json)")
    sp.add_argument("--name", default="", help="Betriebsname (mit --url)")
    sp.add_argument("--branche", default="", help="Gastronomie, Handwerk, Immobilien, Gesundheit, Beauty, Fitness, Dienstleistung")
    sp.add_argument("--kategorie", default="", help='z.B. "Restaurant", "Dachdecker", "Zahnarzt"')
    sp.add_argument("--kueche", default="", help='Gastronomie: Küche wie in OSM, z.B. "vietnamese"')
    sp.add_argument("--ort", default="")
    sp.add_argument("--adresse", default="")
    sp.add_argument("--rating", type=float, default=None, help="Google-Bewertung, z.B. 4.7")
    sp.add_argument("--bewertungen", type=int, default=None, help="Anzahl Google-Bewertungen")
    sp.add_argument("--datenquelle", default=os.environ.get("NOTION_LEADS_DATENQUELLE", "88b8eea0-e22a-82b8-a85c-87d4690ec17b"),
                    help="Notion-Data-Source-ID des Leads-Boards")
    sp.add_argument("--veroeffentlichen", action="store_true",
                    help="Bericht als Unterseite des Leads in Notion anlegen und Report-Score/-Datum setzen")
    sp.add_argument("--notion-seite", default="", help="Elternseite in Notion (mit --url/--leads und --veroeffentlichen)")
    sp.add_argument("--trockenlauf", action="store_true", help="Notion-Blöcke nur als JSON schreiben, nichts hochladen")
    sp.add_argument("--out", default="output/berichte")
    sp.add_argument("--agentur", default=os.environ.get("AGENTUR_NAME", "GG Studios"))
    sp.add_argument("--max", type=int, default=0, help="max. Anzahl Leads (0 = alle)")
    sp.add_argument("--max-seiten", type=int, default=15, help="Seiten je Website crawlen (Default 15)")
    sp.add_argument("--lighthouse-laeufe", type=int, default=3, help="lokale Lighthouse-Messungen am Handy (Median)")
    sp.add_argument("--parallel", type=int, default=1, help="Leads gleichzeitig messen (Default 1)")
    sp.add_argument("--neu", action="store_true", help="neu messen, auch wenn schon ein Bericht existiert")
    sp.add_argument("--ohne-browser", action="store_true", help="keine Screenshots/Datenschutz-Messung (ohne Playwright)")
    sp.add_argument("--ohne-lighthouse", action="store_true")
    sp.add_argument("--ohne-observatory", action="store_true", help="kein Scan beim Mozilla HTTP Observatory")
    sp.add_argument("--ohne-ki", action="store_true", help="keine KI-Stichprobe (sonst mit ANTHROPIC_API_KEY)")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    http = PoliteSession(delay_s=args.delay, respect_robots=not args.ignoriere_robots)

    if args.cmd == "finden":
        leads = finden(args, http)
        speichere_leads(Path(args.out) / "leads.json", leads)
    elif args.cmd == "pruefen":
        pruefen(args, http, lade_leads(Path(args.leads)))
    elif args.cmd == "report":
        report(args, http)
    else:
        leads = finden(args, http)
        speichere_leads(Path(args.out) / "leads.json", leads)
        pruefen(args, http, leads)


if __name__ == "__main__":
    main()
