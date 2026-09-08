import re
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from observatory.app import create_app
from observatory.retrieval import search

ROOT = Path(__file__).resolve().parents[1]


class GuidePage(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.ids, self.steps, self.panels, self.examples, self.links = [], [], [], [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if 'data-guide-step' in attrs:
            self.steps.append(attrs['data-guide-step'])
        if 'data-guide-panel' in attrs:
            self.panels.append(attrs['data-guide-panel'])
            assert 'hidden' not in attrs  # No-script readers get the whole explanation.
        if 'data-question' in attrs:
            self.examples.append(attrs['data-question'])
            if tag == 'button' and attrs.get('type') == 'button':
                assert 3 <= len(attrs['data-question']) <= 800
        if tag == 'a':
            self.links.append(attrs.get('href', ''))


def test_guide_structure_links_examples_and_existing_controller_contract():
    source = (ROOT / 'observatory/static/assistant.html').read_text()
    page = GuidePage(source)
    assert len(page.ids) == len(set(page.ids))
    assert page.steps == page.panels == [str(i) for i in range(7)]
    for link in page.links:
        if link.startswith('#'):
            assert link[1:] in page.ids
    for filename in ('guide.js', 'assistant.js'):
        script = (ROOT / 'observatory/static' / filename).read_text()
        assert set(re.findall(r"(?:getElementById|\$)\('([^']+)'\)", script)) <= set(page.ids)
    assert len(page.examples) == 7
    assert all(search(question) for question in page.examples)
    assert 'No raw container logs' in source
    assert 'This walkthrough never reads your key' in source
    assert 'previous conversation is not sent as context' in source
    assert 'not your OCI password' in source
    assert 'same personal key' in source and 'separate operator grant' in source


def test_guide_has_no_network_secrets_storage_or_automatic_form_submission():
    script = (ROOT / 'observatory/static/guide.js').read_text()
    for forbidden in ('fetch(', 'XMLHttpRequest', 'localStorage', 'sessionStorage', 'access-key',
                      'new-key', 'invite-code', '.submit(', 'requestSubmit', 'innerHTML'):
        assert forbidden not in script
    for expected in ('visibilitychange', 'IntersectionObserver', 'pagehide', 'pageshow',
                     'hashchange', 'ArrowRight', 'ArrowLeft', 'prefers-reduced-motion'):
        assert expected in script
    css = (ROOT / 'observatory/static/guide.css').read_text()
    assert '@media(prefers-reduced-motion:reduce)' in css
    assert '@media(max-width:760px)' in css


def test_guide_served_on_shared_profile_without_changing_auth_or_public_export(tmp_path):
    with TestClient(create_app(assistant_only=True, db_path=tmp_path / 'lab.sqlite')) as client:
        response = client.get('/assistant')
        assert response.status_code == 200 and 'From your key to your first insight.' in response.text
        for asset in ('guide.css', 'guide.js'):
            assert client.get('/static/' + asset).status_code == 200
        assert 'href="/assistant#system"' in client.get('/observability').text
        assert client.get('/api/observability/session').status_code == 401
        assert client.get('/api/service/me').status_code == 401
    caddy = (ROOT / 'infra/Caddyfile').read_text()
    assert '/static/guide.css' in caddy and '/static/guide.js' in caddy
    export = (ROOT / 'scripts/build_portfolio.py').read_text()
    assert '"guide.js"' not in export and '"guide.css"' not in export
