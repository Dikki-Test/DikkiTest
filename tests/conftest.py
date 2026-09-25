from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from agentur_leads.http import PoliteSession

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def jpeg(breite: int, hoehe: int, hell: int = 150, muster: bool = True) -> bytes:
    """Testbild: mit Muster = scharf, ohne = flach/unscharf."""
    img = Image.new("RGB", (breite, hoehe), (hell, hell, hell))
    if muster:
        d = ImageDraw.Draw(img)
        schritt = max(4, breite // 100)
        for x in range(0, breite, schritt * 2):
            d.rectangle([x, 0, x + schritt, hoehe], fill=(min(255, hell + 90),) * 3)
        for y in range(0, hoehe, schritt * 3):
            d.line([0, y, breite, y], fill=(max(0, hell - 90),) * 3, width=2)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, url: str, status: int = 200, text: str = "", content: bytes | None = None,
                 content_type: str = "text/html; charset=utf-8", json_data=None):
        self.url = url
        self.status_code = status
        self.text = text
        self.content = content if content is not None else text.encode()
        self.headers = {"Content-Type": content_type}
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    """Ersetzt requests.Session – liefert Antworten aus einem dict {url: FakeResponse}."""

    def __init__(self, routes: dict[str, FakeResponse]):
        self.routes = routes
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url in self.routes:
            return self.routes[url]
        return FakeResponse(url, status=404, text="not found")

    post = get


@pytest.fixture
def make_http():
    def _make(routes: dict[str, FakeResponse], robots: bool = False) -> PoliteSession:
        return PoliteSession(delay_s=0, respect_robots=robots, session=FakeSession(routes))
    return _make
