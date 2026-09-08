import re
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from observatory.app import create_app

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids, self.links, self.sources = [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag in {"script", "link"}:
            self.sources.append(attrs.get("src", attrs.get("href")))


def test_homepage_root_and_private_lab_are_distinct(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "lab.sqlite")) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Make it visible." in home.text
        assert "EXPLANATORY ANIMATION" in home.text and "Not live traffic" in home.text
        assert "invited assistant" in home.text
        assert 'id="run-form"' not in home.text
        assert 'id="run-form"' in client.get("/lab").text
        assert "Your serving field guide" in client.get("/assistant").text
        for asset in ["home.css", "home.js"]:
            response = client.get("/static/" + asset)
            assert response.status_code == 200
            assert response.headers["x-content-type-options"] == "nosniff"


def test_homepage_ids_links_assets_and_diagram():
    source = (ROOT / "observatory/static/home.html").read_text()
    page = Page(source)
    assert len(page.ids) == len(set(page.ids))
    for link in page.links:
        if link.startswith("#"):
            assert link[1:] in page.ids
    for asset in page.sources:
        assert asset.startswith("/static/")
        assert (ROOT / "observatory" / asset.lstrip("/")).is_file()
    script = (ROOT / "observatory/static/home.js").read_text()
    # Statically verify every literal controller ID has a matching element.
    assert set(re.findall(r"\$\('([^']+)'\)", script)) <= set(page.ids)
    svg = ElementTree.fromstring(re.search(r"<svg.*?</svg>", source, re.S).group())
    for element in svg.iter():
        for attr in ["x", "y", "width", "height", "rx"]:
            if attr in element.attrib:
                assert float(element.attrib[attr]) >= 0


def test_homepage_motion_and_no_network_activity():
    script = (ROOT / "observatory/static/home.js").read_text()
    css = (ROOT / "observatory/static/home.css").read_text()
    assert "prefers-reduced-motion: reduce" in script
    assert "prefers-reduced-motion:reduce" in css
    assert "visibilitychange" in script and "IntersectionObserver" in script
    assert "fetch(" not in script and "XMLHttpRequest" not in script
    assert "localStorage" not in script and "innerHTML" not in script
