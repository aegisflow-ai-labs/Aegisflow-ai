"""Live file policy revocation must cover every response path, not just evidence GET."""

import json
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegisflow.access import SourceAccess, SourceGrant, SourcePolicy, SourcePolicyUnavailable
from aegisflow.api import create_app, token_digest
from aegisflow.contracts import Scenario, Scope
from aegisflow.scenario import generate
from aegisflow.store import Store

SCOPE = Scope(tenant_id="demo", subject_id="analyst", permissions={"read", "investigate"})
BODY = {"order_id": "PO-001", "as_of": "2026-11-01T18:00:00Z"}


def write_policy(path, uris, scope=SCOPE):
    policy = SourcePolicy(
        revision="test-v1",
        grants=(
            SourceGrant(tenant_id=scope.tenant_id, subject_id=scope.subject_id, source_uris=uris),
        ),
    )
    temporary = path.with_suffix(".new")
    temporary.write_text(policy.model_dump_json())
    temporary.replace(path)


@pytest.fixture
def api(tmp_path):
    source = generate()
    policy_file = tmp_path / "policy.json"
    write_policy(policy_file, source.input_source_uris())
    token = secrets.token_urlsafe(32)
    store = Store(tmp_path / "cases.db")
    app = create_app(
        store, {token_digest(token): SCOPE}, (source,), source_access=SourceAccess(policy_file)
    )
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "acl-1"}
    with TestClient(app) as client:
        yield client, headers, policy_file, store


def test_live_revocation_blocks_case_events_evidence_and_replay(api):
    client, headers, path, store = api
    created = client.post("/v1/cases", json=BODY, headers=headers)
    assert created.status_code == 201
    case = created.json()
    prefix = f"/v1/cases/{case['case_id']}"
    removed = case["evidence"][0]
    allowed = case["evidence"][1]
    write_policy(path, [u for u in case["input_source_uris"] if u != removed["source_uri"]])
    for route in (prefix, prefix + "/events", prefix + "/evidence/" + removed["evidence_id"]):
        response = client.get(route, headers=headers)
        assert response.status_code == 404
        assert response.json() == {"detail": "NOT_FOUND"}
        assert response.headers["Cache-Control"] == "no-store"
    for key in ("acl-1", "new-request"):
        assert (
            client.post(
                "/v1/cases", json=BODY, headers={**headers, "Idempotency-Key": key}
            ).status_code
            == 404
        )
    assert (
        client.get(prefix + "/evidence/" + allowed["evidence_id"], headers=headers).json()
        == allowed
    )
    assert len(store.events(SCOPE, case["case_id"])) == 3
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM cases").fetchone()[0] == 1
    # Regrant without restarting; idempotency remains unchanged.
    write_policy(path, case["input_source_uris"])
    assert client.post("/v1/cases", json=BODY, headers=headers).json() == case


@pytest.mark.parametrize("fault", ["missing", "malformed", "oversize"])
def test_policy_failure_does_not_reuse_previous_grants(api, fault):
    client, headers, path, _ = api
    case = client.post("/v1/cases", json=BODY, headers=headers).json()
    if fault == "missing":
        path.unlink()
    elif fault == "oversize":
        path.write_bytes(b"x" * 1_000_001)
    else:
        path.write_text('{"private-canary":')
    for route in (
        f"/v1/cases/{case['case_id']}",
        f"/v1/cases/{case['case_id']}/events",
        f"/v1/cases/{case['case_id']}/evidence/{case['evidence'][0]['evidence_id']}",
    ):
        response = client.get(route, headers=headers)
        assert response.status_code == 503
        assert response.json() == {"detail": "DEPENDENCY_UNAVAILABLE"}
    assert client.post("/v1/cases", json=BODY, headers=headers).status_code == 503


@pytest.mark.parametrize("mismatch", ["subject", "tenant", "wildcard", "empty"])
def test_grants_are_exact_and_default_deny(api, mismatch):
    client, headers, path, store = api
    if mismatch == "subject":
        write_policy(
            path,
            generate().input_source_uris(),
            Scope(tenant_id="demo", subject_id="someone-else", permissions={"read"}),
        )
    elif mismatch == "tenant":
        write_policy(
            path,
            generate().input_source_uris(),
            Scope(tenant_id="other", subject_id="analyst", permissions={"read"}),
        )
    else:
        write_policy(path, ["*"] if mismatch == "wildcard" else [])
    assert client.post("/v1/cases", json=BODY, headers=headers).status_code == 404
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM cases").fetchone()[0] == 0


def test_legacy_case_without_input_dependencies_fails_closed(api):
    client, headers, _, store = api
    case = client.post("/v1/cases", json=BODY, headers=headers).json()
    old = dict(case)
    del old["input_source_uris"]
    with store.connect() as db:
        db.execute("UPDATE cases SET body=? WHERE case_id=?", (json.dumps(old), case["case_id"]))
    assert client.get(f"/v1/cases/{case['case_id']}", headers=headers).status_code == 404
    assert client.get(f"/v1/cases/{case['case_id']}/events", headers=headers).status_code == 404
    assert client.post("/v1/cases", json=BODY, headers=headers).status_code == 404
    evidence = case["evidence"][0]
    assert (
        client.get(
            f"/v1/cases/{case['case_id']}/evidence/{evidence['evidence_id']}", headers=headers
        ).json()
        == evidence
    )


def test_policy_configuration_is_closed_and_required(tmp_path):
    with pytest.raises(SourcePolicyUnavailable):
        SourceAccess(tmp_path / "missing").load()
    grant = SourceGrant(tenant_id="demo", subject_id="analyst", source_uris=[])
    with pytest.raises(ValueError):
        SourcePolicy(revision="test", grants=(grant, grant))
    with pytest.raises(ValueError):
        SourcePolicy.model_validate({"revision": "test", "grants": [], "allow_all": True})


def test_missing_input_source_is_still_a_dependency(tmp_path):
    source = Scenario.model_validate({**generate().model_dump(), "inventory": None})
    path = tmp_path / "policy.json"
    write_policy(path, source.input_source_uris())
    token = secrets.token_urlsafe(32)
    with TestClient(
        create_app(
            Store(tmp_path / "cases.db"),
            {token_digest(token): SCOPE},
            (source,),
            source_access=SourceAccess(path),
        )
    ) as client:
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "missing-input"}
        case = client.post("/v1/cases", json=BODY, headers=headers).json()
        assert case["status"] == "NEEDS_EVIDENCE"
        assert not any(e["source_uri"].endswith("/inventory") for e in case["evidence"])
        write_policy(path, [u for u in source.input_source_uris() if not u.endswith("/inventory")])
        assert client.get(f"/v1/cases/{case['case_id']}", headers=headers).status_code == 404


def test_source_policy_schema_and_clean_demo_setup(tmp_path, monkeypatch):
    import subprocess
    import sys

    from aegisflow.api import from_environment

    assert (
        json.loads(Path("schemas/SourcePolicy.schema.json").read_text())
        == SourcePolicy.model_json_schema()
    )
    script = Path("tools/setup_demo_api.py").resolve()
    result = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    work = tmp_path / "work"
    for name in ("api-auth.json", "api-token", "api-headers", "source-acl.json"):
        assert (work / name).stat().st_mode & 0o777 == 0o600
    token = (work / "api-token").read_text()
    assert token not in result.stdout and token not in result.stderr
    monkeypatch.setenv("AEGISFLOW_AUTH_MODE", "development")
    monkeypatch.setenv("AEGISFLOW_AUTH_FILE", str(work / "api-auth.json"))
    monkeypatch.setenv("AEGISFLOW_SOURCE_ACL_FILE", str(work / "source-acl.json"))
    monkeypatch.setenv(
        "AEGISFLOW_SCENARIO_FILE", str(Path("fixtures/supply-delay-v1.json").resolve())
    )
    monkeypatch.setenv("AEGISFLOW_DB", str(work / "demo.db"))
    monkeypatch.delenv("AEGISFLOW_DATABASE_URL", raising=False)
    with TestClient(from_environment()) as client:
        response = client.post(
            "/v1/cases",
            json=BODY,
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "setup-demo"},
        )
        assert response.status_code == 201
        assert response.headers["Cache-Control"] == "no-store"
    monkeypatch.delenv("AEGISFLOW_SOURCE_ACL_FILE")
    with pytest.raises(KeyError):
        from_environment()


def test_demo_setup_does_not_leave_partial_credentials_when_files_exist(tmp_path):
    import subprocess
    import sys

    script = Path("tools/setup_demo_api.py").resolve()
    work = tmp_path / "work"
    work.mkdir()
    (work / "api-token").write_text("existing-private-canary")
    result = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    assert (work / "api-token").read_text() == "existing-private-canary"
    assert not (work / "source-acl.json").exists()
    assert "existing-private-canary" not in result.stdout + result.stderr
