import re
import runpy
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

EXPORT = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/build_portfolio.py"))
ASSETS, ROOT, build, replace_once = (EXPORT[key] for key in ("ASSETS", "ROOT", "build", "replace_once"))
SITE_ASSETS = EXPORT["SITE_ASSETS"]


class PortfolioPage(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.ids, self.links, self.assets = [], [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a":
            self.links.append(attrs["href"])
        if tag in {"script", "img", "link"}:
            self.assets.append(attrs.get("src", attrs.get("href")))
        assert tag not in {"form", "iframe"}


def test_public_portfolio_is_honest_and_all_links_resolve(tmp_path):
    build(tmp_path)
    source = (tmp_path / "index.html").read_text()
    page = PortfolioPage(source)
    assert 'data-deployment="portfolio"' in source
    assert "Live AI chat is not online yet." in source
    assert "COMING WITH OCI DEPLOYMENT" in source
    assert "Not live traffic" in source
    assert "not ChatGPT-powered answers" in source
    assert len(page.ids) == len(set(page.ids))
    for url in page.links + page.assets:
        parsed = urlsplit(url)
        if parsed.netloc:
            assert parsed.scheme == "https"
            assert parsed.netloc == "github.com"
        elif parsed.path == "/":
            continue
        elif parsed.path:
            target = tmp_path / parsed.path.lstrip("/")
            assert target.is_file() or (target / "index.html").is_file(), url
        elif parsed.fragment:
            assert parsed.fragment in page.ids, url
    assert {f"/static/{name}.svg" for name in (
        "architecture", "request-flow", "hardware-flow", "service-architecture"
    )} <= set(page.assets)
    script = (tmp_path / "static/home.js").read_text()
    assert set(re.findall(r"\$\('([^']+)'\)", script)) <= set(page.ids)
    assert "if (!portfolio && legacy.includes" in script
    assert "if (!portfolio && ['localhost'" in script
    assert "fetch(" not in script and "localStorage" not in script


def test_export_is_allowlisted_and_deterministic(tmp_path):
    build(tmp_path)
    snapshot = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert set(snapshot) == {"index.html", "404.html", "learn/index.html"} | {f"static/{a}" for a in ASSETS + SITE_ASSETS}
    build(tmp_path)
    assert snapshot == {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    # Exporting does not disable the real application or leak its interactive assets.
    assert 'href="/assistant"' in (ROOT / "observatory/static/home.html").read_text()
    assert not any("assistant" in Path(p).name or p.endswith(".sqlite") for p in snapshot)


def test_stale_output_and_symlinks_are_rejected(tmp_path):
    stale = tmp_path / "private.sqlite"
    stale.write_text("must not publish")
    with pytest.raises(ValueError, match="unexpected"):
        build(tmp_path)
    assert not (tmp_path / "index.html").exists()
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "index.html").symlink_to(stale)
    with pytest.raises(ValueError, match="symlinks"):
        build(clean)
    assert stale.read_text() == "must not publish"


def test_source_contract_fails_closed():
    with pytest.raises(ValueError, match="contract changed"):
        replace_once("new wording", "old wording", "replacement")
    with pytest.raises(ValueError, match="contract changed"):
        replace_once("same same", "same", "replacement")
