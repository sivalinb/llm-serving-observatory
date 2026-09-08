import json
from pathlib import Path
from xml.etree import ElementTree

import hcl2
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_yaml_and_json_parse():
    for directory in ["observability", "infra", ".github"]:
        for path in (ROOT / directory).rglob("*.yaml"):
            yaml.safe_load(path.read_text())
        for path in (ROOT / directory).rglob("*.json"):
            json.loads(path.read_text())
    for path in ROOT.glob("compose*.yaml"):
        assert "services" in yaml.safe_load(path.read_text())


def test_terraform_syntax():
    for path in (ROOT / "infra/oci").glob("*.tf"):
        with path.open() as source:
            assert hcl2.load(source)


def test_svg_assets_and_no_external_scripts():
    for name in [
        "architecture.svg",
        "request-flow.svg",
        "hardware-flow.svg",
        "service-architecture.svg",
        "icon.svg",
    ]:
        root = ElementTree.parse(ROOT / "observatory/static" / name).getroot()
        assert root.tag.endswith("svg")
    assert '<script src="https:' not in (ROOT / "observatory/static/index.html").read_text()
