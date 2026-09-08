import asyncio
import json
import runpy
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from observatory.app import create_app
from observatory.assistant import Assistant, Question, Settings, bounded_events
from observatory.assistant_store import AssistantStore, Rejected, digest
from observatory.retrieval import citation_check, prompt, search


def user(store, **kwargs):
    credentials = store.redeem(store.invite(**kwargs), "Learner")
    return store.authenticate(credentials["api_key"]), credentials["api_key"]


def event(data):
    return "data: " + json.dumps(data) + "\n\n"


def model_response(usage=True):
    body = event({"choices": [{"delta": {"content": "CPU inference uses host RAM [S1]."}}]})
    body += event({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    if usage:
        body += event({"choices": [], "usage": {"prompt_tokens": 90, "completion_tokens": 12}})
    return body + "data: [DONE]\n\n"


def service(tmp_path, response=None, **settings):
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "servingops-cpu"
        assert body["stream_options"]["include_usage"]
        return httpx.Response(200, text=model_response() if response is None else response)

    return Assistant(
        AssistantStore(tmp_path / "users.sqlite"),
        Settings(enabled=True, **settings),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_invite_once_expiry_and_hashes(tmp_path):
    store = AssistantStore(tmp_path / "s.sqlite")
    invite = store.invite()
    credentials = store.redeem(invite, "A")
    assert store.authenticate(credentials["api_key"])["name"] == "A"
    assert store.db.execute("SELECT digest FROM keys").fetchone()[0] == digest(
        credentials["api_key"]
    )
    assert credentials["api_key"] not in str(list(store.db.iterdump()))
    with pytest.raises(Rejected):
        store.redeem(invite, "B")
    expired = store.invite()
    store.db.execute("UPDATE invites SET expires=0")
    with pytest.raises(Rejected):
        store.redeem(expired, "B")
    store.close()


def test_rotation_revocation(tmp_path):
    store = AssistantStore(tmp_path / "s.sqlite")
    person, old = user(store)
    new = store.rotate(person["id"])
    with pytest.raises(Rejected):
        store.authenticate(old)
    assert store.authenticate(new)["id"] == person["id"]
    store.revoke(person["id"])
    with pytest.raises(Rejected):
        store.authenticate(new)
    store.close()


def test_atomic_capacity_across_connections(tmp_path):
    path = tmp_path / "s.sqlite"
    first, second = AssistantStore(path), AssistantStore(path)
    person, _ = user(first)

    def reserve(pair):
        store, idem = pair
        try:
            return store.reserve(person, idem, 100, 10000, 90)
        except Rejected as error:
            return error.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, [(first, "a"), (second, "b")]))
    assert outcomes.count("capacity") == 1
    assert first.usage(person["id"])["requests_today"] == 1
    first.close()
    second.close()


@pytest.mark.parametrize("limit,expected", [(99, "daily_tokens"), (1000, "monthly_tokens")])
def test_quota_denial_no_admission(tmp_path, limit, expected):
    store = AssistantStore(tmp_path / "s.sqlite")
    person, _ = user(store, tokens=limit)
    with pytest.raises(Rejected, match=expected):
        store.reserve(person, "a", 100, 99, 90)
    assert store.usage(person["id"])["requests_today"] == 0
    store.close()


def test_reconcile_duplicate_cancel_and_daily_request_limit(tmp_path):
    store = AssistantStore(tmp_path / "s.sqlite")
    person, _ = user(store, requests=2)
    rid = store.reserve(person, "a", 500, 10000, 90)
    store.finish(rid, {"id": rid, "status": "ok", "tokens": {"total": 100}})
    with pytest.raises(Rejected, match="duplicate_request"):
        store.reserve(person, "a", 500, 10000, 90)
    rid = store.reserve(person, "b", 500, 10000, 90)
    store.finish(rid, {"id": rid, "status": "cancelled", "tokens": {"total": 1}})
    assert store.usage(person["id"])["quota_tokens_today"] == 600
    with pytest.raises(Rejected, match="daily_requests"):
        store.reserve(person, "c", 500, 10000, 90)
    store.delete_history(person["id"])
    assert store.records(person["id"]) == []
    assert store.usage(person["id"])["quota_tokens_today"] == 600
    store.close()


def test_abandoned_admission_and_unknown_usage_retain_reservation(tmp_path):
    store = AssistantStore(tmp_path / "s.sqlite")
    person, _ = user(store)
    store.reserve(person, "a", 100, 10000, 90)
    store.db.execute("UPDATE ledger SET created=?", (time.time() - 181,))
    rid = store.reserve(person, "b", 100, 10000, 90)
    store.finish(rid, {"status": "ok", "tokens": {"total": None}})
    assert store.usage(person["id"])["quota_tokens_today"] == 200
    assert store.db.execute("SELECT status FROM ledger WHERE idem='a'").fetchone()[0] == "abandoned"
    store.close()


def test_online_backup_is_usable_and_no_overwrite(tmp_path):
    store = AssistantStore(tmp_path / "s.sqlite")
    person, key = user(store)
    store.backup(tmp_path / "backup.sqlite")
    restored = AssistantStore(tmp_path / "backup.sqlite")
    assert restored.authenticate(key)["id"] == person["id"]
    assert restored.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with pytest.raises(FileExistsError):
        store.backup(tmp_path / "backup.sqlite")
    restored.close()
    store.close()


def test_disabled_search_auth_and_personal_history(tmp_path):
    svc = service(tmp_path)
    person, key = user(svc.store)
    second, key2 = user(svc.store)
    headers = {"Authorization": "Bearer " + key}
    with TestClient(create_app(db_path=tmp_path / "lab.sqlite", assistant_service=svc)) as client:
        assert client.get("/api/service/me").status_code == 401
        assert client.post("/api/service/search", json={"question": "CPU RAM"}).status_code == 401
        assert client.get("/api/service/me", headers=headers).json()["user"]["id"] == person["id"]
        answer = client.post(
            "/api/service/answer",
            headers=dict(headers, **{"Idempotency-Key": "request_0123456789"}),
            json={"question": "How is CPU RAM used?"},
        )
        assert answer.status_code == 200
        assert '"status": "ok"' in answer.text
        assert '"input": 90' in answer.text and '"reasoning": null' in answer.text
        assert answer.headers["cache-control"] == "no-store"
        history = client.get("/api/service/history", headers=headers).json()["records"]
        assert len(history) == 1
        assert "host RAM" not in json.dumps(history) and "How is" not in json.dumps(history)
        assert (
            client.get("/api/service/history", headers={"Authorization": "Bearer " + key2}).json()[
                "records"
            ]
            == []
        )
        assert (
            client.get(
                "/api/service/history?user_id=" + person["id"],
                headers={"Authorization": "Bearer " + key2},
            ).json()["records"]
            == []
        )
        duplicate = client.post(
            "/api/service/answer",
            headers=dict(headers, **{"Idempotency-Key": "request_0123456789"}),
            json={"question": "Different question about CPU"},
        )
        assert duplicate.status_code == 409
        assert (
            client.post(
                "/api/service/answer", headers=headers, json={"question": "CPU RAM"}
            ).status_code
            == 422
        )
        assert client.post(
            "/api/service/search", headers=headers, json={"question": "CPU RAM"}
        ).json()["sources"]
        svc.settings = Settings()
        assert (
            client.post(
                "/api/service/answer",
                headers=dict(headers, **{"Idempotency-Key": "request_9999999999"}),
                json={"question": "CPU RAM"},
            ).status_code
            == 503
        )
        assert svc.store.usage(person["id"])["requests_today"] == 1
        assert svc.store.usage(second["id"])["requests_today"] == 0


@pytest.mark.parametrize(
    "body",
    [
        model_response(False),
        "data: [DONE]\n\n",
        'data: {"error":"private body"}\n\n',
        'data: {"choices":[]}',
        "data: []\n\n",
    ],
)
async def test_unknown_usage_and_malformed_streams(tmp_path, body):
    svc = service(tmp_path, body)
    person, _ = user(svc.store)
    stream = svc.prepare(person, Question(question="CPU RAM and memory"), "a", None)
    chunks = [chunk async for chunk in stream.body_iterator]
    record = svc.store.records(person["id"])[0]
    assert record["tokens"]["total"] is None
    assert svc.store.usage(person["id"])["quota_tokens_today"] == record["reserved_tokens_estimate"]
    assert "private body" not in json.dumps(chunks)
    assert record["status"] == ("ok" if body == model_response(False) else "error")
    await svc.client.aclose()
    svc.store.close()


async def test_cancel_releases_capacity_and_no_refund(tmp_path):
    svc = service(tmp_path)
    person, _ = user(svc.store)
    stream = svc.prepare(person, Question(question="CPU RAM and memory"), "a", None)
    await anext(stream.body_iterator)
    await stream.body_iterator.aclose()
    stream.cleanup()
    assert svc.store.records(person["id"])[0]["status"] == "cancelled"
    assert svc.store.usage(person["id"])["quota_tokens_today"] > 0
    # Also handle disconnect before the generator starts.
    second = svc.prepare(person, Question(question="CPU RAM and memory"), "b", None)
    second.cleanup()
    assert (
        svc.store.db.execute("SELECT COUNT(*) FROM ledger WHERE status='running'").fetchone()[0]
        == 0
    )
    await svc.client.aclose()
    svc.store.close()


async def test_deadline(tmp_path):
    async def slow(request):
        await asyncio.sleep(2)
        return httpx.Response(200, text=model_response())

    svc = Assistant(
        AssistantStore(tmp_path / "s.sqlite"),
        Settings(enabled=True, deadline=1),
        httpx.AsyncClient(transport=httpx.MockTransport(slow)),
    )
    person, _ = user(svc.store)
    stream = svc.prepare(person, Question(question="CPU RAM and memory"), "a", None)
    result = [chunk async for chunk in stream.body_iterator]
    assert '"status": "timeout"' in result[-1]
    assert svc.store.usage(person["id"])["quota_tokens_today"] > 100
    await svc.client.aclose()
    svc.store.close()


async def test_stream_limits_and_crlf():
    good = httpx.Response(200, content=b'data: {"x":1}\r\n\r\ndata: [DONE]\r\n\r\n')
    assert [value async for value in bounded_events(good)] == [{"x": 1}]
    with pytest.raises(ValueError, match="size limit"):
        async for _ in bounded_events(httpx.Response(200, content=b"x" * 65537)):
            pass


def test_retrieval_citations_and_context():
    sources = search("CPU RAM HBM memory")
    assert sources[0]["document_id"] == "memory"
    assert len(sources) <= 3
    assert search("zzzzzzzzzzzzz") == []
    assert citation_check("Fact [S1]", sources) == "present"
    assert citation_check("Fact [S999]", sources) == "invalid_ids"
    assert citation_check("Fact", sources) == "missing"
    assert "untrusted" in prompt("CPU RAM?", sources)[0]["content"]


def test_retrieval_teaching_fixture():
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/evaluate_retrieval.py"))
    result = module["evaluate"]()
    assert result["cases"] == 15
    assert result["recall_at_3"] == 1.0


def test_backup_contents_never_include_plaintext_secrets(tmp_path):
    store = AssistantStore(tmp_path / "s.sqlite")
    _, key = user(store)
    store.backup(tmp_path / "backup.sqlite")
    with sqlite3.connect(tmp_path / "backup.sqlite") as db:
        assert key not in "\n".join(db.iterdump())
    store.close()


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "https://user:secret@example.com", "http://x/?secret=foo"]
)
def test_config_rejects_unsafe_url(url):
    with pytest.raises(ValueError):
        Settings(url=url)
