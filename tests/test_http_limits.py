import asyncio
import json

import anyio
import pytest

from aegisflow.http_limits import RequestLimits


def exercise(messages, headers=(), delay=0, **limits):
    sent = []
    forwarded = []
    received = list(messages)

    async def application(scope, receive, send):
        forwarded.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        if delay:
            await anyio.sleep(delay)
        return received.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(
        RequestLimits(application, **limits)(
            {"type": "http", "headers": list(headers)}, receive, send
        )
    )
    return sent, forwarded


def request(body, more=False):
    return {"type": "http.request", "body": body, "more_body": more}


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"4")]])
def test_body_boundary_is_forwarded_once(headers):
    sent, forwarded = exercise([request(b"ab", True), request(b"cd")], headers, max_body_bytes=4)
    assert sent[0]["status"] == 200
    assert forwarded == [request(b"abcd")]


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"3")]])
def test_actual_stream_is_bounded_even_if_length_is_missing_or_false(headers):
    sent, forwarded = exercise([request(b"abc", True), request(b"de")], headers, max_body_bytes=4)
    assert sent[0]["status"] == 413 and not forwarded
    assert (b"cache-control", b"no-store") in sent[0]["headers"]


def test_declared_oversize_is_rejected_before_receiving_body():
    sent, forwarded = exercise([], [(b"content-length", b"999999999999999999999999")])
    assert sent[0]["status"] == 413 and not forwarded


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", b"-1")],
        [(b"content-length", b"x")],
        [(b"content-length", b"0"), (b"content-length", b"0")],
    ],
)
def test_invalid_length_fails_closed(headers):
    sent, forwarded = exercise([], headers)
    assert sent[0]["status"] == 400 and not forwarded


def test_truncated_body_is_not_forwarded():
    sent, forwarded = exercise([request(b"x")], [(b"content-length", b"2")])
    assert sent[0]["status"] == 400 and not forwarded


def test_headers_are_bounded_before_body_receive():
    sent, forwarded = exercise([], [(b"authorization", b"private-canary")], max_header_bytes=4)
    assert sent[0]["status"] == 431 and not forwarded
    assert b"private-canary" not in sent[1]["body"]


def test_body_read_has_total_deadline():
    sent, forwarded = exercise([request(b"x")], delay=0.05, read_timeout_seconds=0.005)
    assert sent[0]["status"] == 408 and not forwarded
    assert json.loads(sent[1]["body"]) == {"detail": "REQUEST_TIMEOUT"}


def test_disconnect_does_not_run_application():
    sent, forwarded = exercise([{"type": "http.disconnect"}])
    assert not sent and not forwarded


def test_limits_cannot_be_disabled_accidentally():
    with pytest.raises(ValueError):
        RequestLimits(None, max_body_bytes=0)


def test_zero_padded_length_cannot_trigger_integer_digit_limit():
    sent, forwarded = exercise(
        [request(b"abcd")], [(b"content-length", b"0" * 5000 + b"4")], max_body_bytes=4
    )
    assert sent[0]["status"] == 200 and forwarded == [request(b"abcd")]


def test_non_http_protocol_is_passed_through():
    scopes = []

    async def app(scope, receive, send):
        scopes.append(scope["type"])

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        pass

    asyncio.run(RequestLimits(app)({"type": "lifespan"}, receive, send))
    assert scopes == ["lifespan"]


def test_api_limits_reject_before_case_persistence(tmp_path):
    import secrets

    from fastapi.testclient import TestClient

    from aegisflow.api import create_app, token_digest
    from aegisflow.contracts import Scope
    from aegisflow.scenario import generate
    from aegisflow.store import Store
    from tests.access_helpers import access_for

    token = secrets.token_urlsafe(32)
    scope = Scope(tenant_id="demo", subject_id="test", permissions={"read", "investigate"})
    store = Store(tmp_path / "limits.db")
    app = create_app(
        store, {token_digest(token): scope}, (generate(),), source_access=access_for(scope)
    )
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "limits-1"}
    with TestClient(app) as client:
        response = client.post(
            "/v1/cases", json={"order_id": "PO-001", "as_of": "x" * 70000}, headers=headers
        )
        assert response.status_code == 413
        assert response.headers["Cache-Control"] == "no-store"
        response = client.post("/v1/cases", json={}, headers={**headers, "x-large": "x" * 17000})
        assert response.status_code == 431
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM cases").fetchone()[0] == 0
