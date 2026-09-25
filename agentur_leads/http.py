"""Höflicher HTTP-Client: eigener User-Agent, robots.txt, Rate-Limit pro Host."""

from __future__ import annotations

import threading
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

DEFAULT_UA = "AgenturLeadsBot/0.1 (+regionale Web- und Social-Agentur; Kontakt siehe Impressum)"


class PoliteSession:
    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        delay_s: float = 1.0,
        timeout_s: float = 15.0,
        respect_robots: bool = True,
        session: requests.Session | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.delay_s = delay_s
        self.timeout_s = timeout_s
        self.respect_robots = respect_robots
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept-Language": "de-DE,de;q=0.9,en;q=0.5"}
        )
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def _wait_for_host(self, host: str) -> None:
        with self._lock:
            last = self._last_hit.get(host, 0.0)
            wait = self.delay_s - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            self._last_hit[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                resp = self.session.get(base + "/robots.txt", timeout=self.timeout_s)
                if resp.status_code >= 400:
                    self._robots[base] = None  # keine robots.txt -> alles erlaubt
                else:
                    rp.parse(resp.text.splitlines())
                    self._robots[base] = rp
            except requests.RequestException:
                self._robots[base] = None
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    def get(self, url: str, **kwargs) -> requests.Response:
        if not self.allowed(url):
            raise PermissionError(f"robots.txt verbietet Abruf: {url}")
        self._wait_for_host(urlparse(url).netloc)
        kwargs.setdefault("timeout", self.timeout_s)
        kwargs.setdefault("allow_redirects", True)
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        """Für APIs (Overpass, Google Places) – kein robots.txt-Check."""
        self._wait_for_host(urlparse(url).netloc)
        kwargs.setdefault("timeout", max(self.timeout_s, 60))
        return self.session.post(url, **kwargs)

    def api_get(self, url: str, **kwargs) -> requests.Response:
        """GET gegen offizielle APIs – kein robots.txt-Check."""
        self._wait_for_host(urlparse(url).netloc)
        kwargs.setdefault("timeout", self.timeout_s)
        return self.session.get(url, **kwargs)
