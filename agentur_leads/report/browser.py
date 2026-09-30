"""Browser-Messung mit Playwright (optional): Screenshots, externe Dienste und Cookies vor jeder
Einwilligung, unverschlüsselt geladene Inhalte, horizontales Scrollen auf dem Handy.

Installation: pip install "agentur-leads[report]" && playwright install chromium
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from .modelle import registrierte_domain

log = logging.getLogger(__name__)

# Dienste, die personenbezogene Daten (mind. die IP) an Dritte übertragen und daher erst nach
# Einwilligung laden sollten. Hostname (oder dessen Endung) -> Anzeigename.
DIENSTE = {
    "fonts.googleapis.com": "Google Fonts", "fonts.gstatic.com": "Google Fonts",
    "maps.googleapis.com": "Google Maps", "maps.gstatic.com": "Google Maps",
    "youtube.com": "YouTube", "ytimg.com": "YouTube", "googlevideo.com": "YouTube",
    "youtube-nocookie.com": "YouTube",
    "google-analytics.com": "Google Analytics", "analytics.google.com": "Google Analytics",
    "googletagmanager.com": "Google Tag Manager",
    "doubleclick.net": "Google-Werbenetz (DoubleClick)", "googlesyndication.com": "Google-Werbenetz",
    "googleadservices.com": "Google Ads",
    "facebook.com": "Facebook/Meta", "facebook.net": "Facebook/Meta",
    "instagram.com": "Instagram", "cdninstagram.com": "Instagram",
    "tiktok.com": "TikTok", "linkedin.com": "LinkedIn", "licdn.com": "LinkedIn",
    "hotjar.com": "Hotjar", "clarity.ms": "Microsoft Clarity", "bing.com": "Microsoft Bing",
    "vimeo.com": "Vimeo", "vimeocdn.com": "Vimeo", "pinterest.com": "Pinterest",
}
CMP_MARKER = ["cookiebot", "usercentrics", "cookielaw.org", "onetrust", "borlabs", "complianz", "cmplz", "cookieyes",
              "cookie-law-info", "real-cookie-banner", "klaro", "consentmanager", "cmpbox", "iubenda", "termly",
              "didomi", "cookiefirst", "ccm19", "cookie-notice", "moove_gdpr", "gdpr-cookie-consent"]
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")


def dienst(url: str) -> str:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host in ("www.google.com", "google.com", "www.google.de"):
        return "Google Maps" if p.path.startswith("/maps") else "Google reCAPTCHA" if "recaptcha" in p.path else "Google"
    for suffix, name in DIENSTE.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    return ""


WICHTIG = ["YouTube", "Google Maps", "Google Analytics", "Google Tag Manager", "Facebook/Meta", "Google Fonts",
           "Google-Werbenetz (DoubleClick)", "Instagram", "TikTok", "Hotjar", "Microsoft Clarity"]


def ordne_dienste(dienste: set[str]) -> list[str]:
    """Wichtigste zuerst; das allgemeine „Google“ nur, wenn kein konkreter Google-Dienst erkannt wurde."""
    if any(d.startswith("Google") and d != "Google" for d in dienste) or "YouTube" in dienste:
        dienste = dienste - {"Google"}
    return sorted(dienste, key=lambda d: (WICHTIG.index(d) if d in WICHTIG else len(WICHTIG), d))


def proxy_args() -> list[str]:
    """In Umgebungen mit HTTPS-Proxy nur https:// darüber leiten (http:// geht direkt)."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        return []
    p = urlparse(proxy)
    return [f"--proxy-server=https={p.hostname}:{p.port}"] if p.hostname and p.port else []


def browser_messung(website_url: str, ordner: Path, unterseiten: list[str] | None = None,
                    vorschaltseite: str = "") -> dict:
    try:
        from playwright.sync_api import Error as PWError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"fehler": "Playwright nicht installiert"}

    ordner.mkdir(parents=True, exist_ok=True)
    domain = registrierte_domain(website_url)
    ergebnis: dict = {"seiten": {}, "screenshots": {}, "fehler": ""}

    def eigen(url: str) -> bool:
        return registrierte_domain(url) == domain

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None, args=proxy_args())

            def besuche(url: str, *, mobil: bool, warte_ms: int, screenshot: str = "") -> dict:
                ctx = browser.new_context(
                    viewport={"width": 390, "height": 844} if mobil else {"width": 1440, "height": 900},
                    device_scale_factor=2 if mobil else 1, is_mobile=mobil, has_touch=mobil,
                    user_agent=IPHONE_UA if mobil else None, locale="de-DE")
                page = ctx.new_page()
                anfragen: list[str] = []
                page.on("request", lambda r: anfragen.append(r.url))
                info: dict = {"url": url}
                try:
                    resp = page.goto(url, wait_until="load", timeout=45000)
                    page.wait_for_timeout(warte_ms)
                    info["status"] = resp.status if resp else None
                    info["final_url"] = page.url
                    html = page.content().lower()
                    info["cmp"] = [m for m in CMP_MARKER if m in html or any(m in a.lower() for a in anfragen)]
                    info["dienste"] = sorted({d for a in anfragen if (d := dienst(a)) and not eigen(a)})
                    info["fremd_hosts"] = sorted({urlparse(a).hostname or "" for a in anfragen if not eigen(a)} - {""})
                    info["cookies_dritt"] = sorted({f"{c['domain']}:{c['name']}" for c in ctx.cookies()
                                                    if not c["domain"].lstrip(".").endswith(domain)})
                    if page.url.startswith("https://"):
                        # Chrome stuft http://-Bilder selbst auf https hoch – daher auch im Quelltext nachsehen
                        im_dom = page.evaluate("""() => [...document.querySelectorAll(
                            'img[src^="http:"], script[src^="http:"], iframe[src^="http:"], source[src^="http:"],'
                            + 'link[rel="stylesheet"][href^="http:"]')].map(e => e.getAttribute('src') || e.getAttribute('href'))""")
                        info["unverschluesselt"] = sorted({a for a in anfragen + im_dom if a.startswith("http://")})[:30]
                    if mobil:
                        info["doc_breite"] = page.evaluate("document.documentElement.scrollWidth")
                    if screenshot:
                        pfad = ordner / screenshot
                        page.screenshot(path=str(pfad), type="jpeg", quality=82)
                        ergebnis["screenshots"][screenshot.rsplit(".", 1)[0]] = str(pfad)
                except PWError as e:
                    info["fehler"] = str(e).splitlines()[0][:160]
                finally:
                    ctx.close()
                return info

            if vorschaltseite:
                ergebnis["seiten"]["vorschaltseite"] = besuche(vorschaltseite, mobil=True, warte_ms=800,
                                                               screenshot="screen_vorschalt_mobil.jpg")
            ergebnis["seiten"]["start_desktop"] = besuche(website_url, mobil=False, warte_ms=2500,
                                                          screenshot="screen_desktop.jpg")
            ergebnis["seiten"]["start_mobil"] = besuche(website_url, mobil=True, warte_ms=2500,
                                                        screenshot="screen_mobil.jpg")
            for i, url in enumerate((unterseiten or [])[:3]):
                ergebnis["seiten"][f"unterseite_{i + 1}"] = besuche(url, mobil=False, warte_ms=3500)
            browser.close()
    except Exception as e:  # Browser-Start o.ä. – Bericht entsteht trotzdem, nur ohne Screenshots
        log.warning("Browser-Messung fehlgeschlagen: %s", e)
        ergebnis["fehler"] = str(e).splitlines()[0][:200]

    seiten = [s for s in ergebnis["seiten"].values() if not s.get("fehler") and "dienste" in s]
    ergebnis["dienste_ohne_einwilligung"] = ordne_dienste({d for s in seiten for d in s["dienste"]})
    ergebnis["dienste_je_seite"] = {s["url"]: s["dienste"] for s in seiten if s["dienste"]}
    ergebnis["cookies_dritt"] = sorted({c for s in seiten for c in s.get("cookies_dritt", [])})
    ergebnis["cmp_erkannt"] = sorted({m for s in seiten for m in s.get("cmp", [])})
    ergebnis["unverschluesselt"] = sorted({u for s in seiten for u in s.get("unverschluesselt", [])})
    mobil = ergebnis["seiten"].get("start_mobil", {})
    ergebnis["handy_ueberbreite"] = (mobil.get("doc_breite") or 0) > 400
    return ergebnis
