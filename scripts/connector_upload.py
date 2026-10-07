"""Berichts-PDFs über den Notion-Connector (MCP) veröffentlichen – ohne NOTION_TOKEN.

Ablauf je Paket (Claude mit Notion-Connector):
  1. python scripts/connector_upload.py offen 10       → nächste fertige, unveröffentlichte Berichte (JSON)
  2. je Bericht notion-create-file-upload(filename=dateiname) → upload_url, upload_headers, id
  3. python scripts/connector_upload.py hochladen auftraege.json   (Liste: slug, dateiname, upload_url, upload_headers)
  4. je Bericht notion-update-page update_properties:
       {"Report-PDF": [{"type": "file_upload", "file_upload": {"id": ID}}], "Report-Score": gesamt,
        "date:Report-Datum:start": datum, "date:Report-Datum:is_datetime": 0}
  5. python scripts/connector_upload.py erledigt SLUG …

Weitere Befehle: stand (Fortschritt), export DATEI … (Antworten der Board-Abfrage im Ansichtsmodus zu
output/berichte/leads_export.json zusammenführen).

Mit NOTION_TOKEN: token [N] hängt die fertigen PDFs direkt per Notion-API an – ohne Connector, ohne
Freigaben und ohne neu zu messen.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parents[1] / "output" / "berichte"
STATUS, ERLEDIGT = OUT / "status.jsonl", OUT / "veroeffentlicht.jsonl"


def zeilen(pfad: Path) -> list[dict]:
    return [json.loads(z) for z in pfad.read_text(encoding="utf-8").splitlines() if z.strip()] if pfad.exists() else []


def erledigt() -> set[str]:
    """Über den Connector markiert oder vom Gesamtlauf per NOTION_TOKEN veröffentlicht."""
    return {z["slug"] for z in zeilen(ERLEDIGT)} | {p.parent.name for p in OUT.glob("*/veroeffentlicht.json")}


def dateiname(z: dict) -> str:
    name = "".join(c if c not in '\\/:*?"<>|' else " " for c in z["name"]).strip()
    return f"Website-Check {name} {z['datum']}.pdf"


def offen(k: int) -> list[dict]:
    fertig, schon = {}, erledigt()
    for z in zeilen(STATUS):  # letzte Zeile je Lead zählt
        fertig[z["slug"]] = z
    return [{**z, "dateiname": dateiname(z)} for z in fertig.values()
            if z["slug"] not in schon and z.get("pdf") and z.get("page_id") and not z.get("fehler")][:k]


def hochladen(datei: Path) -> None:
    for a in json.loads(datei.read_text(encoding="utf-8")):
        try:
            with (OUT / a["slug"] / "bericht.pdf").open("rb") as fh:
                r = requests.post(a["upload_url"], headers=a.get("upload_headers") or {},
                                  files={"file": (a["dateiname"], fh, "application/pdf")}, timeout=120)
            ok = r.status_code < 300
            print(json.dumps({"slug": a["slug"], "ok": ok, "status": r.status_code, "antwort": "" if ok else r.text[:200]},
                             ensure_ascii=False))
        except (OSError, requests.RequestException) as e:
            print(json.dumps({"slug": a["slug"], "ok": False, "fehler": str(e)[:200]}, ensure_ascii=False))


def markieren(slugs: list[str]) -> None:
    status = {z["slug"]: z for z in zeilen(STATUS)}
    with ERLEDIGT.open("a", encoding="utf-8") as fh:
        for s in slugs:
            fh.write(json.dumps({"slug": s, "gesamt": status.get(s, {}).get("gesamt")}, ensure_ascii=False) + "\n")
            (OUT / s / "veroeffentlicht.json").write_text(json.dumps({"pdf": True}), encoding="utf-8")


def stand() -> None:
    alle = {z["slug"]: z for z in zeilen(STATUS)}
    fehler = [z for z in alle.values() if z.get("fehler")]
    letzte = zeilen(STATUS)[-1] if alle else {}
    print(json.dumps({"fertig": len(alle), "davon_fehler": len(fehler), "veroeffentlicht": len(erledigt()),
                      "gesamt": letzte.get("n", 0), "sekunden": letzte.get("sek", 0)}))


def export(dateien: list[str]) -> None:
    gesehen, alle = set(), []
    for d in dateien:
        for z in json.loads(Path(d).read_text(encoding="utf-8")).get("results", []):
            if z.get("url") not in gesehen:
                gesehen.add(z.get("url"))
                alle.append(z)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "leads_export.json").write_text(json.dumps(alle, ensure_ascii=False), encoding="utf-8")
    mit_web = sum(1 for z in alle if (z.get("Website") or "").strip())
    fertig = sum(1 for z in alle if z.get("date:Report-Datum:start"))
    print(json.dumps({"zeilen": len(alle), "mit_website": mit_web, "schon_mit_report": fertig}))


def mit_token(k: int) -> None:
    """Fertige PDFs direkt per NOTION_TOKEN anhängen – ohne Connector, ohne Freigaben, ohne neu zu messen."""
    from agentur_leads.report.lauf import Bericht, lead_eigenschaften, pdf_dateiname
    from agentur_leads.report.modelle import ReportLead
    from agentur_leads.report.notion import Notion

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        sys.exit("NOTION_TOKEN fehlt")
    notion, liste = Notion(token), offen(k)
    for i, z in enumerate(liste, 1):
        b = Bericht(lead=ReportLead(z["name"], "", notion_page_id=z["page_id"]), ordner=OUT / z["slug"],
                    fakten={"datum": z["datum"]}, gesamt=z["gesamt"], pdf=OUT / z["slug"] / "bericht.pdf")
        try:
            pdf_id = notion.hochladen(b.pdf, pdf_dateiname(b))
            notion.seite_aktualisieren(z["page_id"], lead_eigenschaften(b, pdf_id))
        except (OSError, requests.RequestException, RuntimeError) as e:  # ein Fehlschlag hält den Rest nicht auf
            print(json.dumps({"i": i, "slug": z["slug"], "ok": False, "fehler": str(e)[:200]}, ensure_ascii=False),
                  flush=True)
            continue
        markieren([z["slug"]])
        print(json.dumps({"i": i, "n": len(liste), "slug": z["slug"], "ok": True}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    befehl, rest = sys.argv[1], sys.argv[2:]
    if befehl == "offen":
        print(json.dumps(offen(int(rest[0]) if rest else 10), ensure_ascii=False))
    elif befehl == "hochladen":
        hochladen(Path(rest[0]))
    elif befehl == "erledigt":
        markieren(rest)
    elif befehl == "stand":
        stand()
    elif befehl == "token":
        mit_token(int(sys.argv[2]) if len(sys.argv) > 2 else 100000)
    elif befehl == "export":
        export(rest)
