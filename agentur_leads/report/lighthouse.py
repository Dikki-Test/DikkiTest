"""Ladezeit und Qualität mit Google Lighthouse.

Mit PAGESPEED_API_KEY über die PageSpeed-Insights-API (schnell, inkl. Felddaten echter Nutzer, falls
Google genug Besuche kennt). Sonst lokal mit der Lighthouse-CLI (npm i -g lighthouse) und Chromium.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests

from .browser import proxy_args

log = logging.getLogger(__name__)
PSI = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
KATEGORIEN = ["performance", "accessibility", "best-practices", "seo"]
FELD_METRIKEN = {
    "LARGEST_CONTENTFUL_PAINT_MS": "lcp_ms",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "cls_x100",
    "INTERACTION_TO_NEXT_PAINT": "inp_ms",
    "FIRST_CONTENTFUL_PAINT_MS": "fcp_ms",
}


def auswerten(lhr: dict) -> dict:
    """Die für den Bericht relevanten Werte aus einem Lighthouse-Ergebnis."""
    a = lhr.get("audits", {})

    def wert(key: str, teiler: float = 1.0) -> float | None:
        v = (a.get(key) or {}).get("numericValue")
        return None if v is None else v / teiler

    def details(key: str) -> dict:
        return (a.get(key) or {}).get("details") or {}

    fehlgeschlagen = {}
    for cid, kat in lhr.get("categories", {}).items():
        if cid != "performance":
            fehlgeschlagen[cid] = [a[r["id"]]["title"] for r in kat.get("auditRefs", [])
                                   if r.get("weight", 0) > 0 and (a.get(r["id"]) or {}).get("score") is not None
                                   and a[r["id"]]["score"] < 0.9][:8]
    return {
        "version": lhr.get("lighthouseVersion"),
        "final_url": lhr.get("finalDisplayedUrl") or lhr.get("finalUrl"),
        "scores": {k: round((v.get("score") or 0) * 100) for k, v in lhr.get("categories", {}).items()},
        "fcp": wert("first-contentful-paint", 1000), "lcp": wert("largest-contentful-paint", 1000),
        "cls": wert("cumulative-layout-shift"), "tbt": wert("total-blocking-time"), "si": wert("speed-index", 1000),
        "gewicht_kb": {i["resourceType"]: round(i.get("transferSize", 0) / 1024)
                       for i in details("resource-summary").get("items", [])},
        "gewicht_ok": ((a.get("total-byte-weight") or {}).get("score") or 0) >= 0.9,
        "einsparung_bilder_kb": round((details("modern-image-formats").get("overallSavingsBytes") or 0) / 1024),
        "unsichere_anfragen": len(details("is-on-https").get("items") or []),
        "fehlgeschlagen": fehlgeschlagen,
        "laufzeitfehler": (lhr.get("runtimeError") or {}).get("code", ""),
    }


def psi(url: str, strategie: str, key: str, timeout: float = 150) -> dict:
    params = [("url", url), ("strategy", strategie), ("locale", "de"), ("key", key)] + [("category", k) for k in KATEGORIEN]
    try:
        d = requests.get(PSI, params=params, timeout=timeout).json()
    except (requests.RequestException, ValueError) as e:
        return {"fehler": type(e).__name__}
    if "error" in d:
        return {"fehler": str(d["error"].get("message", ""))[:160]}
    out = auswerten(d.get("lighthouseResult", {}))
    out["quelle"] = "über PageSpeed Insights"
    feld = (d.get("loadingExperience") or {})
    if feld.get("metrics") and not feld.get("origin_fallback"):
        out["felddaten"] = {kurz: {"wert": m.get("percentile"), "kategorie": m.get("category")}
                            for lang, kurz in FELD_METRIKEN.items() if (m := feld["metrics"].get(lang))}
        out["felddaten"]["gesamt"] = feld.get("overall_category")
    return out


_CHROME: dict[str, str] = {}


def _chrome_pfad() -> str:
    if "p" not in _CHROME:
        pfad = os.environ.get("CHROME_PATH", "")
        if not pfad:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    pfad = pw.chromium.executable_path
            except Exception:
                pfad = shutil.which("chromium") or shutil.which("google-chrome") or ""
        _CHROME["p"] = pfad
    return _CHROME["p"]


def lokal(url: str, strategie: str, laeufe: int = 1, timeout: float = 240) -> dict:
    exe, chrome = shutil.which("lighthouse"), _chrome_pfad()
    if not exe or not chrome:
        return {"fehler": "Lighthouse-CLI oder Chrome nicht gefunden"}
    flags = " ".join(["--headless=new", "--no-sandbox", "--disable-dev-shm-usage", *proxy_args()])
    ergebnisse = []
    for _ in range(max(1, laeufe)):
        with tempfile.TemporaryDirectory() as tmp:
            ziel = Path(tmp) / "lh.json"
            cmd = [exe, url, "--quiet", "--locale=de", "--output=json", f"--output-path={ziel}",
                   f"--chrome-flags={flags}", "--max-wait-for-load=60000"]
            if strategie == "desktop":
                cmd.append("--preset=desktop")
            try:
                subprocess.run(cmd, env={**os.environ, "CHROME_PATH": chrome}, timeout=timeout,
                               capture_output=True, check=False)
                ergebnisse.append(auswerten(json.loads(ziel.read_text(encoding="utf-8"))))
            except (subprocess.TimeoutExpired, OSError, ValueError) as e:
                log.warning("Lighthouse (%s) für %s fehlgeschlagen: %s", strategie, url, e)
    gueltig = [e for e in ergebnisse if e.get("scores") and not e.get("laufzeitfehler")]
    if not gueltig:
        return {"fehler": "Lighthouse lieferte kein Ergebnis"}
    gueltig.sort(key=lambda e: e["scores"].get("performance", 0))
    median = gueltig[len(gueltig) // 2]
    median["quelle"] = "lokal gemessen"
    median["laeufe"] = [e["scores"].get("performance") for e in ergebnisse if e.get("scores")]
    return median


def lighthouse(url: str, laeufe_mobil: int = 3) -> dict:
    key = os.environ.get("PAGESPEED_API_KEY", "")
    if key:
        return {"mobil": psi(url, "mobile", key), "desktop": psi(url, "desktop", key)}
    return {"mobil": lokal(url, "mobile", laeufe_mobil), "desktop": lokal(url, "desktop", 1)}
