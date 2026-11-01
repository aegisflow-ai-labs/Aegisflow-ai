import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegisflow.actions import ActionConflict
from aegisflow.api import create_app, token_digest
from aegisflow.contracts import Action, Request, Scope
from aegisflow.pilot_scenarios import pilot_scenarios
from aegisflow.store import NotFound, PolicyDenied, Store
from tests.access_helpers import access_for

NOW = datetime(2026, 11, 1, 18, tzinfo=UTC)
SCOPE = Scope(
    tenant_id="demo",
    subject_id="operator",
    permissions={"read", "investigate", "approve", "execute"},
)


def make_case(store, index=0):
    scenario = pilot_scenarios()[index]
    return store.run(
        SCOPE,
        Request(
            tenant_id="demo",
            order_id=scenario.order.order_id,
            idempotency_key=f"action-{index}",
            as_of=NOW,
        ),
        scenario,
    )


def exercise_workflow(store):
    case = make_case(store)
    with pytest.raises(ActionConflict, match="PROPOSAL_REQUIRED"):
        store.transition_action(SCOPE, case.case_id, "execute", "0" * 64)
    proposal = store.transition_action(SCOPE, case.case_id, "propose")
    assert proposal["status"] == "PROPOSED"
    checksum = proposal["content_digest"]
    assert store.transition_action(SCOPE, case.case_id, "propose") == proposal
    with pytest.raises(ActionConflict, match="APPROVAL_REQUIRED"):
        store.transition_action(SCOPE, case.case_id, "execute", checksum)
    with pytest.raises(ActionConflict, match="ACTION_CONTENT_MISMATCH"):
        store.transition_action(SCOPE, case.case_id, "approve", "0" * 64)
    analyst = SCOPE.model_copy(update={"permissions": frozenset({"read", "investigate"})})
    for operation in ("approve", "execute"):
        with pytest.raises(PolicyDenied):
            store.transition_action(analyst, case.case_id, operation, checksum)
    approved = store.transition_action(SCOPE, case.case_id, "approve", checksum)
    assert approved["approved_by"] == "operator"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: store.transition_action(SCOPE, case.case_id, "execute", checksum),
                range(8),
            )
        )
    assert all(r == results[0] for r in results)
    assert results[0]["status"] == "EXECUTED"
    assert results[0]["receipt_id"].startswith("synthetic:")
    assert results[0]["external_action_executed"] is False
    assert [e.event_type for e in store.events(SCOPE, case.case_id)] == [
        "CaseCreated",
        "EvidenceCollected",
        "InvestigationCompleted",
        "ActionProposed",
        "ActionApproved",
        "ActionExecuted",
    ]
    assert all(e.actor_id == "operator" for e in store.events(SCOPE, case.case_id)[3:])
    with pytest.raises(NotFound):
        store.transition_action(
            SCOPE.model_copy(update={"tenant_id": "other"}), case.case_id, "propose"
        )
    return case, results[0]


def test_sqlite_workflow_reopen_and_concurrency(tmp_path):
    store = Store(tmp_path / "actions.db")
    case, result = exercise_workflow(store)
    assert (
        Store(store.path).transition_action(
            SCOPE, case.case_id, "execute", result["content_digest"]
        )
        == result
    )


@pytest.mark.parametrize("index", [1, 2, 3])
def test_non_actionable_cases_cannot_propose(tmp_path, index):
    store = Store(tmp_path / "blocked.db")
    case = make_case(store, index)
    with pytest.raises(ActionConflict, match="CASE_NOT_ACTIONABLE"):
        store.transition_action(SCOPE, case.case_id, "propose")
    assert len(store.events(SCOPE, case.case_id)) == 3


def test_execution_insert_failure_rolls_back(tmp_path):
    store = Store(tmp_path / "rollback.db")
    case = make_case(store)
    proposal = store.transition_action(SCOPE, case.case_id, "propose")
    store.transition_action(SCOPE, case.case_id, "approve", proposal["content_digest"])
    import sqlite3

    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_execution BEFORE INSERT ON events WHEN NEW.revision=6 BEGIN SELECT RAISE(ABORT,'injected'); END;"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.transition_action(SCOPE, case.case_id, "execute", proposal["content_digest"])
    assert len(store.events(SCOPE, case.case_id)) == 5
    with store.connect() as db:
        db.execute("DROP TRIGGER fail_execution")
    assert (
        store.transition_action(SCOPE, case.case_id, "execute", proposal["content_digest"])[
            "status"
        ]
        == "EXECUTED"
    )


def test_api_content_tampering_source_revocation_and_permission(tmp_path):
    from aegisflow.access import SourceAccess, SourcePolicy

    file = tmp_path / "acl.json"
    file.write_text(access_for(SCOPE).load().model_dump_json())
    analyst = SCOPE.model_copy(update={"permissions": frozenset({"read", "investigate"})})
    store = Store(tmp_path / "api.db")
    case = make_case(store)
    app = create_app(
        store,
        {token_digest("operator"): SCOPE, token_digest("analyst"): analyst},
        pilot_scenarios(),
        source_access=SourceAccess(file),
    )
    path = "/v1/cases/" + case.case_id + "/action"
    headers = {"Authorization": "Bearer operator"}
    with TestClient(app) as client:
        assert client.post(path + "/propose", json={}).status_code == 401
        assert (
            client.post(
                path + "/propose", json={"message": "tampered"}, headers=headers
            ).status_code
            == 422
        )
        proposal = client.post(path + "/propose", json={}, headers=headers).json()
        body = {"content_digest": proposal["content_digest"]}
        assert client.post(path + "/execute", json=body, headers=headers).status_code == 409
        assert (
            client.post(
                path + "/approve", json=body, headers={"Authorization": "Bearer analyst"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                path + "/approve", json={"content_digest": "0" * 64}, headers=headers
            ).status_code
            == 409
        )
        assert client.post(path + "/approve", json=body, headers=headers).status_code == 200
        assert client.post(path + "/execute", json=body, headers=headers).status_code == 200
        assert client.get(path, headers=headers).json()["status"] == "EXECUTED"
        file.write_text(SourcePolicy(revision="revoked", grants=()).model_dump_json())
        assert client.get(path, headers=headers).status_code == 404
        assert client.post(path + "/execute", json=body, headers=headers).status_code == 404


def test_action_schema():
    assert json.loads(Path("schemas/Action.schema.json").read_text()) == Action.model_json_schema()


def test_action_contract_rejects_changed_content(tmp_path):
    from pydantic import ValidationError

    store = Store(tmp_path / "integrity.db")
    case = make_case(store)
    action = store.transition_action(SCOPE, case.case_id, "propose")
    action["payload"]["message"] = "Changed after review"
    with pytest.raises(ValidationError):
        Action.model_validate(action)


def test_local_opt_in_preserves_revocations_and_other_principals(tmp_path, monkeypatch):
    import tools.keycloak_demo as helper
    from aegisflow.identity import IdentityPolicy, PrincipalBinding

    monkeypatch.setattr(helper, "DIRECTORY", tmp_path)
    other = SCOPE.model_copy(update={"subject_id": "other"})
    original = IdentityPolicy(
        revision="before",
        revoked_jti={"revoked-token"},
        principals=(
            PrincipalBinding(
                external_subject="local",
                scope=SCOPE.model_copy(update={"permissions": frozenset({"read", "investigate"})}),
                tokens_valid_after=123,
            ),
            PrincipalBinding(external_subject="other", scope=other),
        ),
    )
    (tmp_path / "login.json").write_text(json.dumps({"subject": "local"}))
    (tmp_path / "principals.json").write_text(original.model_dump_json())
    helper.enable_synthetic_actions()
    updated = IdentityPolicy.model_validate_json((tmp_path / "principals.json").read_text())
    assert updated.principals[1] == original.principals[1]
    assert updated.revoked_jti == original.revoked_jti
    assert updated.principals[0].tokens_valid_after == 123
    assert updated.principals[0].scope.permissions == SCOPE.permissions
