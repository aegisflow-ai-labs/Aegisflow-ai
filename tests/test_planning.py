import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegisflow.api import create_app, token_digest
from aegisflow.contracts import FollowupPlan, Request, Scope, WorkflowLimits
from aegisflow.evaluation import evaluate
from aegisflow.pilot_scenarios import pilot_scenarios
from aegisflow.planning import PlannerUnavailable, PlanRejected, propose
from aegisflow.store import Store
from aegisflow.workflow import investigate_adaptive
from tests.access_helpers import access_for

NOW = datetime(2026, 11, 1, 18, tzinfo=UTC)
SCOPE = Scope(tenant_id="demo", subject_id="test", permissions={"read", "investigate"})


def run(index=0, **kwargs):
    source = pilot_scenarios()[index]
    request = Request(
        tenant_id="demo", order_id=source.order.order_id, idempotency_key="planning", as_of=NOW
    )
    return investigate_adaptive(request, source, "planning-case", "test", NOW, **kwargs)


@pytest.mark.parametrize("index,steps", [(0, 3), (1, 3), (2, 4), (3, 4), (4, 3)])
def test_selective_followup_steps(index, steps):
    case = run(index)
    assert len(case.workflow.steps) == steps
    assert case.workflow.plan is not None
    assert case.workflow.version == "bounded-supply-v2"
    assert sum(s.tool_calls for s in case.workflow.steps) == 1
    assert case.model_calls == 0 and case.active_roles == ("A21",)
    if steps == 4:
        assert case.status == "NEEDS_EVIDENCE"


@pytest.mark.parametrize(
    "changes",
    [
        {"steps": ["EXECUTE_ACTION"]},
        {"role_id": "A30"},
        {"destination": "https://evil.invalid"},
        {"steps": ["TRIAGE", "EVIDENCE_REVIEW"]},
        {"steps": ["EVIDENCE_REVIEW", "TRIAGE"], "reason": "EVIDENCE_GAP_REVIEW"},
        {"context_digest": "0" * 64},
    ],
)
def test_untrusted_proposals_fail_closed(changes):
    def unsafe(context):
        return {**propose(context), **changes}

    with pytest.raises(PlanRejected):
        run(planner=unsafe)


def test_missing_evidence_cannot_skip_review_or_exceed_budget():
    def skip(context):
        return {**propose(context), "steps": ["TRIAGE"], "reason": "STANDARD_TRIAGE"}

    with pytest.raises(PlanRejected, match="REQUIRED_FOLLOWUP_MISMATCH"):
        run(2, planner=skip)
    with pytest.raises(PlanRejected, match="BUDGET"):
        run(2, limits=WorkflowLimits(max_steps=3))


def test_model_copy_bypass_revalidated():
    def unsafe(context):
        valid = FollowupPlan.model_validate(propose(context))
        return valid.model_copy(update={"role_id": "A30"})

    with pytest.raises(PlanRejected):
        run(planner=unsafe)


def test_planner_failure_does_not_fallback():
    def failed(context):
        raise RuntimeError("sensitive-provider-content")

    with pytest.raises(PlannerUnavailable):
        run(planner=failed)


def test_review_rejects_tampered_evidence(monkeypatch):
    from aegisflow.engine import investigate as baseline

    def tampered(*args):
        case = baseline(*args)
        evidence = case.evidence[0].model_copy(update={"snapshot": {"altered": True}})
        return case.model_copy(update={"evidence": (evidence, *case.evidence[1:])})

    monkeypatch.setattr("aegisflow.workflow.baseline", tampered)
    with pytest.raises(PlanRejected, match="EVIDENCE_INTEGRITY_MISMATCH"):
        run(2)


def test_rejected_plan_is_not_persisted_or_echoed(tmp_path, monkeypatch):
    def failed(*args):
        raise PlannerUnavailable("sensitive-provider-content")

    monkeypatch.setattr("aegisflow.store.investigate", failed)
    store = Store(tmp_path / "planning.db")
    app = create_app(
        store, {token_digest("test"): SCOPE}, pilot_scenarios(), source_access=access_for(SCOPE)
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/cases",
            json={"order_id": "PO-001", "as_of": NOW.isoformat()},
            headers={"Authorization": "Bearer test", "Idempotency-Key": "planning"},
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "WORKFLOW_PLAN_UNAVAILABLE"}
    assert store.list_cases(SCOPE) == ()


def test_both_evaluation_versions_reproducible():
    for version, variant, count in (("v1", "fixed-v1", 12), ("v2", "validated-v2", 24)):
        result = evaluate(Path(f"fixtures/evaluations/supply-workflow-{version}.json"), variant)
        assert result["passed"] and result["cases"] == count
        assert result == json.loads(
            Path(f"docs/evaluation/supply-workflow-{version}.json").read_text()
        )


def test_valid_plan_cannot_be_replayed_for_another_case():
    def replay(context):
        return propose(context.model_copy(update={"case_id": "other-case"}))

    with pytest.raises(PlanRejected, match="PLAN_CONTEXT_MISMATCH"):
        run(planner=replay)


def test_slow_planner_obeys_checkpoint_deadline():
    from aegisflow.workflow import WorkflowBudgetExceeded

    ticks = [0.0]

    def slow(context):
        ticks[0] = 10.0
        return propose(context)

    with pytest.raises(WorkflowBudgetExceeded, match="DEADLINE_EXCEEDED"):
        run(planner=slow, clock=lambda: ticks[0])


def test_historical_v1_trace_remains_readable():
    from aegisflow.contracts import Case
    from aegisflow.workflow import investigate

    source = pilot_scenarios()[0]
    request = Request(
        tenant_id="demo", order_id=source.order.order_id, idempotency_key="historical", as_of=NOW
    )
    historical = investigate(request, source, "historical-case", "test", NOW).model_dump(
        mode="json"
    )
    del historical["workflow"]["plan"]
    del historical["workflow"]["planner_calls"]
    restored = Case.model_validate(historical)
    assert restored.workflow.version == "bounded-supply-v1"
    assert restored.workflow.plan is None and restored.workflow.planner_calls == 0
