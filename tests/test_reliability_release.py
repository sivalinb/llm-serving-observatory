import copy
import re
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLOUD = runpy.run_path(str(ROOT / "scripts/reliability_cloud.py"))
BUILD = runpy.run_path(str(ROOT / "scripts/build_portfolio.py"))["build"]


def approved_plan():
    result = {"resource_changes": [{"address": address, "mode": "managed", "change": {
        "actions": ["create"], "after": {}}} for address in CLOUD["ADDRESSES"]]}
    values = {item["address"]: item["change"]["after"] for item in result["resource_changes"]}
    values["oci_apm_apm_domain.lab"]["is_free_tier"] = True
    values["oci_kms_vault.lab"]["vault_type"] = "DEFAULT"
    values["oci_kms_key.secrets"]["protection_mode"] = "SOFTWARE"
    values["oci_objectstorage_bucket.backups"].update(access_type="NoPublicAccess", storage_tier="Standard")
    return result


def test_initial_plan_is_exact_create_only_and_explicitly_free():
    plan = approved_plan()
    assert len(CLOUD["validate_plan"](plan)) == 17
    changed = copy.deepcopy(plan)
    changed["resource_changes"][0]["change"]["actions"] = ["update"]
    with pytest.raises(ValueError):
        CLOUD["validate_plan"](changed)
    with pytest.raises(ValueError):
        CLOUD["validate_plan"]({"resource_changes": plan["resource_changes"][:-1]})
    for address, field, bad in [("oci_apm_apm_domain.lab", "is_free_tier", False),
                                ("oci_kms_vault.lab", "vault_type", "VIRTUAL_PRIVATE"),
                                ("oci_objectstorage_bucket.backups", "access_type", "ObjectRead")]:
        changed = copy.deepcopy(plan)
        next(x for x in changed["resource_changes"] if x["address"] == address)["change"]["after"][field] = bad
        with pytest.raises(ValueError):
            CLOUD["validate_plan"](changed)


def test_public_architecture_is_complete_static_and_has_no_api_calls(tmp_path):
    BUILD(tmp_path)
    page = (tmp_path / "reliability/index.html").read_text()
    script = (tmp_path / "static/reliability.js").read_text()
    ids = re.findall(r'\bid="([^"]+)"', page)
    assert len(ids) == len(set(ids))
    assert set(re.findall(r"getElementById\('([^']+)'", script)) <= set(ids)
    assert page.count('<article class=') == 4 and page.count('<li>') == 20
    assert '__ARCHITECTURE__' not in page and '<svg ' in page
    for forbidden in ('fetch(', 'XMLHttpRequest', 'localStorage', 'sessionStorage', 'innerHTML', 'sendBeacon'):
        assert forbidden not in script
    assert 'prefers-reduced-motion' in script and 'visibilitychange' in script and 'pagehide' in script
    assert 'no live telemetry' in page and 'no cloud actions' in page
    assert 'Cloud Reliability Lab' in (tmp_path / 'learn/index.html').read_text()
    assert '/reliability/' in (tmp_path / 'index.html').read_text()
