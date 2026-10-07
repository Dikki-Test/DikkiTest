import importlib.util
import json
from pathlib import Path

import pytest

SKRIPT = Path(__file__).resolve().parents[1] / "scripts" / "connector_upload.py"


@pytest.fixture
def cu(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("connector_upload", SKRIPT)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    monkeypatch.setattr(modul, "OUT", tmp_path)
    monkeypatch.setattr(modul, "STATUS", tmp_path / "status.jsonl")
    monkeypatch.setattr(modul, "ERLEDIGT", tmp_path / "veroeffentlicht.jsonl")
    return modul


def test_token_haengt_fertige_pdfs_direkt_an(cu, tmp_path, monkeypatch):
    from agentur_leads.report import notion as notion_modul

    zeilen = [{"slug": "a", "name": "Lotus Garten", "page_id": "p1", "gesamt": 34, "pdf": "x", "fehler": "",
               "datum": "2026-10-01"},
              {"slug": "b", "name": "Kaputt", "page_id": "p2", "gesamt": None, "pdf": "", "fehler": "nicht erreichbar",
               "datum": "2026-10-01"},
              {"slug": "c", "name": "Schon da", "page_id": "p3", "gesamt": 50, "pdf": "x", "fehler": "",
               "datum": "2026-10-01"}]
    (tmp_path / "status.jsonl").write_text("\n".join(json.dumps(z) for z in zeilen), encoding="utf-8")
    for slug in ("a", "c"):
        (tmp_path / slug).mkdir()
        (tmp_path / slug / "bericht.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / "c" / "veroeffentlicht.json").write_text("{}", encoding="utf-8")

    aufrufe = []

    class FakeNotion:
        def __init__(self, token):
            aufrufe.append(("token", token))

        def hochladen(self, pfad, name=""):
            aufrufe.append(("hochladen", pfad.parent.name, name))
            return "fu-1"

        def seite_aktualisieren(self, page_id, properties):
            aufrufe.append(("aktualisieren", page_id, properties["Report-PDF"]["files"][0]["file_upload"]["id"],
                            properties["Report-Score"], properties["Report-Datum"]))

    monkeypatch.setattr(notion_modul, "Notion", FakeNotion)
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        cu.mit_token(10)

    monkeypatch.setenv("NOTION_TOKEN", "test-token")
    cu.mit_token(10)
    assert aufrufe == [("token", "test-token"), ("hochladen", "a", "Website-Check Lotus Garten 2026-10-01.pdf"),
                       ("aktualisieren", "p1", "fu-1", {"number": 34}, {"date": {"start": "2026-10-01"}})]
    assert cu.erledigt() == {"a", "c"} and cu.offen(10) == []
