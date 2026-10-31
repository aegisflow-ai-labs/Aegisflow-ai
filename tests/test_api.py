import secrets
from pathlib import Path

from fastapi.testclient import TestClient

from aegisflow.api import create_app, token_digest
from aegisflow.contracts import Scope
from aegisflow.scenario import generate
from aegisflow.store import Store


def test_authenticated_api_and_acl(tmp_path: Path) -> None:
    token = secrets.token_urlsafe(32)
    other = secrets.token_urlsafe(32)
    reader = secrets.token_urlsafe(32)
    denied = secrets.token_urlsafe(32)
    credentials = {
        token_digest(token): Scope(
            tenant_id="demo", subject_id="owner", permissions={"read", "investigate"}
        ),
        token_digest(other): Scope(
            tenant_id="other", subject_id="other", permissions={"read", "investigate"}
        ),
        token_digest(reader): Scope(tenant_id="demo", subject_id="reader", permissions={"read"}),
        token_digest(denied): Scope(tenant_id="demo", subject_id="denied", permissions=set()),
    }
    app = create_app(Store(tmp_path / "api.db"), credentials, (generate(),))
    # Mutating caller-owned configuration cannot expand a running app's scopes.
    credentials.clear()
    with TestClient(app) as client:
        body = {"order_id": "PO-001", "as_of": "2026-11-01T18:00:00Z"}
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "request-1"}
        assert client.post("/v1/cases", json=body).status_code == 401
        assert (
            client.post(
                "/v1/cases", json=body, headers={**headers, "Authorization": "Bearer bad"}
            ).status_code
            == 401
        )
        first = client.post("/v1/cases", json=body, headers=headers)
        assert first.status_code == 201
        case = first.json()
        path = f"/v1/cases/{case['case_id']}"
        evidence = f"{path}/evidence/{case['evidence'][0]['evidence_id']}"
        assert client.post("/v1/cases", json=body, headers=headers).json() == case
        assert len(client.get(path + "/events", headers=headers).json()) == 3
        assert client.get(evidence, headers=headers).json() == case["evidence"][0]
        for route in (path, path + "/events", evidence):
            assert client.get(route).status_code == 401
            assert (
                client.get(route, headers={"Authorization": f"Bearer {other}"}).status_code == 404
            )
            assert (
                client.get(route, headers={"Authorization": f"Bearer {denied}"}).status_code == 403
            )
            assert (
                client.get(route, headers={"Authorization": f"Bearer {reader}"}).status_code == 200
            )
        assert client.get(path + "/evidence/unknown", headers=headers).status_code == 404
        assert (
            client.post(
                "/v1/cases", json=body, headers={**headers, "Authorization": f"Bearer {reader}"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/v1/cases", json=body, headers={**headers, "Authorization": f"Bearer {other}"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/v1/cases", json={**body, "tenant_id": "other"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/cases", json=body, headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 422
        )
        changed = client.post(
            "/v1/cases", json={**body, "as_of": "2026-11-01T19:00:00Z"}, headers=headers
        )
        assert changed.status_code == 409
        bad = client.post("/v1/cases", json={**body, "as_of": token}, headers=headers)
        assert bad.status_code == 422 and token not in bad.text


def test_api_failure_paths(tmp_path: Path, monkeypatch) -> None:
    import sqlite3

    import pytest

    from aegisflow.api import from_environment

    store = Store(tmp_path / "errors.db")
    token = secrets.token_urlsafe(32)
    scope = Scope(tenant_id="demo", subject_id="test", permissions={"read", "investigate"})
    with pytest.raises(ValueError):
        create_app(store, {}, (generate(),))
    with pytest.raises(ValueError):
        create_app(store, {token: scope}, (generate(),))
    with pytest.raises(ValueError):
        create_app(store, {token_digest(token): scope}, (generate(), generate()))
    auth_file = tmp_path / "auth.json"
    import json

    auth_file.write_text(json.dumps({token_digest(token): scope.model_dump(mode="json")}))
    monkeypatch.setenv("AEGISFLOW_AUTH_FILE", str(auth_file))
    monkeypatch.setenv("AEGISFLOW_SCENARIO_FILE", "fixtures/supply-delay-v1.json")
    monkeypatch.setenv("AEGISFLOW_DB", str(tmp_path / "environment.db"))
    with TestClient(from_environment()) as client:
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "test-1"}
        body = {"order_id": "PO-001", "as_of": "2026-11-01T18:00:00"}
        assert client.post("/v1/cases", headers=headers, json=body).status_code == 422
        body["as_of"] = "2020-01-01T00:00:00Z"
        assert client.post("/v1/cases", headers=headers, json=body).status_code == 422

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr(store, "read", fail)
    with TestClient(create_app(store, {token_digest(token): scope}, (generate(),))) as client:
        response = client.get("/v1/cases/unknown", headers=headers)
        assert response.status_code == 503
        assert "private" not in response.text
    monkeypatch.delenv("AEGISFLOW_AUTH_FILE")
    with pytest.raises(KeyError):
        from_environment()
