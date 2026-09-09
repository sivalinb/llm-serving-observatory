import json
import re
import runpy
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXPORT = runpy.run_path(str(ROOT / "scripts/build_portfolio.py"))
ACADEMY = runpy.run_path(str(ROOT / "scripts/render_academy.py"))


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids, self.links, self.assets, self.quiz_names, self.labels = [], [], [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a":
            self.links.append(attrs["href"])
        if tag in {"script", "img", "link"}:
            self.assets.append(attrs.get("src", attrs.get("href")))
        if tag == "input" and attrs.get("type") == "radio":
            self.quiz_names.append(attrs["name"])
        if tag == "label" and "for" in attrs:
            self.labels.append(attrs["for"])
        assert tag not in {"iframe", "form"}


def test_curriculum_has_a_complete_ordered_path_and_primary_reading():
    data = ACADEMY["load_curriculum"]()
    assert len(data["lessons"]) == 20
    assert len(data["tracks"]) == 5
    assert all(sum(lesson["track"] == track for lesson in data["lessons"]) == 4 for track in data["tracks"])
    assert data["lessons"][0]["prerequisite"] is None
    for previous, lesson in zip(data["lessons"], data["lessons"][1:]):
        assert lesson["prerequisite"] == previous["id"]
    for lesson in data["lessons"]:
        assert len(lesson["concepts"]) == 3
        assert all(c["term"] and c["detail"] for c in lesson["concepts"])
        assert lesson["quiz"]["explanation"]
    text = json.dumps(data).lower()
    for concept in ["hbm", "gqa", "continuous batching", "speculative", "numa", "tensor", "rdma", "readiness", "iam", "kubernetes", "error budget", "prompt injection", "rag", "lora", "moe", "canary", "cost"]:
        assert concept in text


def test_academy_assets_links_quizzes_and_controller_wiring(tmp_path):
    EXPORT["build"](tmp_path)
    source = (tmp_path / "learn/index.html").read_text()
    page = Page(source)
    assert len(page.ids) == len(set(page.ids))
    assert set(page.labels) <= set(page.ids)
    assert len(set(page.quiz_names)) == 20
    assert all(page.quiz_names.count(name) == 3 for name in set(page.quiz_names))
    for url in page.links:
        parsed = urlsplit(url)
        if parsed.scheme:
            assert parsed.scheme == "https"
        elif not parsed.path and parsed.fragment:
            assert parsed.fragment in page.ids
        elif parsed.path == "/":
            if parsed.fragment:
                assert f'id="{parsed.fragment}"' in (tmp_path / "index.html").read_text()
    for asset in page.assets:
        assert (tmp_path / asset.lstrip("/")).is_file()
    script = (ROOT / "sites/academy.js").read_text()
    literal_ids = set(re.findall(r"(?:\$|read)\('([^']+)'", script))
    assert literal_ids <= set(page.ids), literal_ids - set(page.ids)
    assert source.count('class="lesson"') == 20
    assert source.count('class="exercise"') == 4
    assert "<strong>Not live:</strong>" in source
    assert "The OCI assistant is deployed privately" in source
    assert "not performance benchmarks" in source


def test_academy_is_static_private_by_design_and_not_a_fake_model():
    script = (ROOT / "sites/academy.js").read_text()
    for forbidden in ["fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "innerHTML", "eval(", "sendBeacon"]:
        assert forbidden not in script
    assert "hashchange" in script and "lesson.open = true" in script
    assert "input.checkValidity()" in script
    page = ACADEMY["render_academy"]()
    for token in ["type=\"radio\"", "<legend>", 'role="status"', "Simulated finite-run", "Hypothetical"]:
        assert token in page
    assert "<!-- LESSONS -->" not in page


def test_generated_html_escapes_curriculum_text(monkeypatch):
    data = ACADEMY["load_curriculum"]()
    payload = '<img src=x onerror="alert(1)">'
    data["lessons"][0]["summary"] = payload
    data["lessons"][0]["quiz"]["choices"][0] = payload
    monkeypatch.setitem(ACADEMY["render_academy"].__globals__, "load_curriculum", lambda: data)
    page = ACADEMY["render_academy"]()
    assert payload not in page
    assert '&lt;img src=x onerror=&quot;' in page
