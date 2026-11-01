from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from aegisflow.access import SourceAccess, SourcePolicy
from aegisflow.api import create_app, token_digest
from aegisflow.contracts import Request, Scope
from aegisflow.pilot_scenarios import pilot_scenarios
from aegisflow.store import Store
from aegisflow.triage import triage
from tests.access_helpers import access_for

NOW = datetime(2026, 11, 1, 18, tzinfo=UTC)
SCOPE = Scope(tenant_id="demo", subject_id="test", permissions={"read", "investigate"})


@pytest.mark.parametrize(
    "index,expected,delay",
    [
        (0, "ESCALATE", 25200),
        (1, "MONITOR", 0),
        (2, "COLLECT_EVIDENCE", 25200),
        (3, "COLLECT_EVIDENCE", None),
        (4, "ESCALATE", 32400),
    ],
)
def test_operational_outcomes(tmp_path, index, expected, delay):
    scenario = pilot_scenarios()[index]
    store = Store(tmp_path / "triage.db")
    request = Request(
        tenant_id="demo", order_id=scenario.order.order_id, idempotency_key="triage", as_of=NOW
    )
    case = store.run(SCOPE, request, scenario)
    decision = triage(case)
    assert decision.disposition == expected
    assert decision.external_action_executed is False
    assert set(decision.evidence_refs) <= {e.evidence_id for e in case.evidence}
    assert next((c.value for c in case.claims if c.code == "DELIVERY_DELAY"), None) == delay
    assert triage(Store(store.path).read(SCOPE, case.case_id)) == decision
    assert store.run(SCOPE, request, scenario) == case
    assert len(store.events(SCOPE, case.case_id)) == 3
    if expected == "COLLECT_EVIDENCE":
        assert decision.missing_evidence


def test_sla_boundary_and_missing_procedure(tmp_path):
    scenario = pilot_scenarios()[0]
    scenario = scenario.model_copy(
        update={
            "deliveries": (
                scenario.deliveries[0].model_copy(
                    update={"delivered_at": scenario.order.promised_at + timedelta(seconds=3600)}
                ),
            )
        }
    )
    request = Request(tenant_id="demo", order_id="PO-001", idempotency_key="boundary", as_of=NOW)
    store = Store(tmp_path / "boundary.db")
    assert triage(store.run(SCOPE, request, scenario)).disposition == "MONITOR"
    request = request.model_copy(update={"idempotency_key": "missing"})
    case = store.run(SCOPE, request, scenario.model_copy(update={"procedure": None}))
    assert triage(case).disposition == "COLLECT_EVIDENCE"


def test_catalog_and_triage_authorization_and_replay(tmp_path):
    other = Scope(tenant_id="other", subject_id="test", permissions={"read", "investigate"})
    credentials = {token_digest("owner"): SCOPE, token_digest("other"): other}
    policy_file = tmp_path / "acl.json"
    policy_file.write_text(access_for(SCOPE, other).load().model_dump_json())
    access = SourceAccess(policy_file)
    app = create_app(
        Store(tmp_path / "api.db"), credentials, pilot_scenarios(), source_access=access
    )
    headers = {"Authorization": "Bearer owner", "Idempotency-Key": "unique"}
    with TestClient(app) as client:
        assert client.get("/v1/orders").status_code == 401
        assert client.get("/v1/orders", headers=headers).json() == [
            "PO-001",
            "PO-002",
            "PO-003",
            "PO-004",
            "PO-005",
        ]
        assert client.get("/v1/orders", headers={"Authorization": "Bearer other"}).json() == []
        body = {"order_id": "PO-003", "as_of": NOW.isoformat()}
        result = client.post("/v1/cases", json=body, headers=headers)
        assert result.status_code == 201
        path = "/v1/cases/" + result.json()["case_id"] + "/triage"
        assert client.get(path, headers=headers).json()["disposition"] == "COLLECT_EVIDENCE"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer other"}).status_code == 404
        assert client.post("/v1/cases", json=body, headers=headers).json() == result.json()
        assert (
            client.post(
                "/v1/cases", json={**body, "order_id": "PO-002"}, headers=headers
            ).status_code
            == 409
        )
        policy_file.write_text(SourcePolicy(revision="revoked", grants=()).model_dump_json())
        assert client.get("/v1/orders", headers=headers).json() == []
        assert client.get(path, headers=headers).status_code == 404


def test_suite_reproducible():
    assert [s.model_dump_json() for s in pilot_scenarios()] == [
        s.model_dump_json() for s in pilot_scenarios()
    ]


def test_triage_schema():
    import json
    from pathlib import Path

    from aegisflow.triage import Triage

    assert json.loads(Path("schemas/Triage.schema.json").read_text()) == Triage.model_json_schema()
