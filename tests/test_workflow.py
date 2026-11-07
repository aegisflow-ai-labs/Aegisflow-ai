import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegisflow.api import create_app, token_digest
from aegisflow.contracts import Case, Request, Scope, WorkflowLimits
from aegisflow.evaluation import evaluate
from aegisflow.scenario import generate
from aegisflow.store import Store
from aegisflow.workflow import WorkflowBudgetExceeded, investigate
from tests.access_helpers import access_for

NOW = datetime(2026, 11, 1, 18, tzinfo=UTC)
SCOPE = Scope(tenant_id="demo", subject_id="test", permissions={"read", "investigate"})
REQUEST = Request(tenant_id="demo", order_id="PO-001", idempotency_key="workflow", as_of=NOW)


@pytest.mark.parametrize(
    "limits,reason",
    [
        ({"max_steps": 2}, "PLAN_EXCEEDS_BUDGET"),
        ({"max_tool_calls": 0}, "PLAN_EXCEEDS_BUDGET"),
        ({"allowed_tools": ()}, "TOOL_NOT_ALLOWED"),
        ({"max_source_bytes": 1}, "SOURCE_BYTES_EXCEEDED"),
    ],
)
def test_budget_rejection_precedes_analysis(monkeypatch, limits, reason):
    def forbidden(*args):
        pytest.fail("Analysis should not run after resource rejection")

    monkeypatch.setattr("aegisflow.workflow.baseline", forbidden)
    with pytest.raises(WorkflowBudgetExceeded, match=reason):
        investigate(REQUEST, generate(), "case", "test", NOW, limits=WorkflowLimits(**limits))


def test_deadline_rejects_slow_completed_step(monkeypatch):
    from aegisflow.engine import investigate as baseline

    ticks = [0.0]

    def slow_analysis(*args):
        ticks[0] = 10.0
        return baseline(*args)

    monkeypatch.setattr("aegisflow.workflow.baseline", slow_analysis)
    with pytest.raises(WorkflowBudgetExceeded, match="DEADLINE_EXCEEDED"):
        investigate(REQUEST, generate(), "case", "test", NOW, clock=lambda: ticks[0])


def test_trace_persistence_legacy_and_scope(tmp_path):
    store = Store(tmp_path / "workflow.db")
    case = store.run(SCOPE, REQUEST, generate())
    assert case.workflow is not None
    assert case.workflow.disposition == "ESCALATE"
    assert case.workflow.source_bytes <= case.workflow.limits.max_source_bytes
    assert Store(store.path).read(SCOPE, case.case_id) == case
    assert store.run(SCOPE, REQUEST, generate()) == case
    legacy = case.model_dump()
    del legacy["workflow"]
    assert Case.model_validate(legacy).workflow is None
    with pytest.raises(ValueError, match="scope mismatch"):
        investigate(
            REQUEST.model_copy(update={"tenant_id": "other"}), generate(), "case", "test", NOW
        )


def test_exhausted_workflow_never_persists_case_or_success_event(tmp_path, monkeypatch):
    def rejected(*args):
        raise WorkflowBudgetExceeded("DEADLINE_EXCEEDED")

    monkeypatch.setattr("aegisflow.store.investigate", rejected)
    store = Store(tmp_path / "failed.db")
    app = create_app(
        store, {token_digest("test"): SCOPE}, (generate(),), source_access=access_for(SCOPE)
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/cases",
            json={"order_id": "PO-001", "as_of": NOW.isoformat()},
            headers={"Authorization": "Bearer test", "Idempotency-Key": "failed"},
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "WORKFLOW_BUDGET_EXCEEDED"}
    assert store.list_cases(SCOPE) == ()
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_evaluation_reproducible_and_matches_recorded_artifact():
    suite = Path("fixtures/evaluations/supply-workflow-v1.json")
    result = evaluate(suite)
    assert result == evaluate(suite)
    assert result == json.loads(Path("docs/evaluation/supply-workflow-v1.json").read_text())
    assert result["passed"] is True and result["cases"] == 12


def test_wrong_expected_label_fails_evaluation(tmp_path):
    data = json.loads(Path("fixtures/evaluations/supply-workflow-v1.json").read_text())
    data["cases"][0]["expected_delay"] = 1
    suite = tmp_path / "wrong.json"
    suite.write_text(json.dumps(data))
    result = evaluate(suite)
    assert result["passed"] is False
    assert result["results"][0]["labels_match"] is False
    command = subprocess.run(
        [sys.executable, "-m", "aegisflow", "evaluate", "--suite", str(suite)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert command.returncode == 1
    assert json.loads(command.stdout)["passed"] is False
