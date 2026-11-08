"""Development regression evaluation, with explicit labels; not a held-out benchmark."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from .contracts import Contract, Identifier, Request, Scenario
from .engine import investigate as baseline
from .integrity import digest
from .triage import triage
from .workflow import investigate, investigate_adaptive


class EvaluationCase(Contract):
    name: Identifier
    scenario: Scenario
    expected_status: Literal["COMPLETED", "NEEDS_EVIDENCE"]
    expected_delay: int | None
    expected_breach: bool | None
    expected_disposition: Literal["ESCALATE", "MONITOR", "COLLECT_EVIDENCE"]


class EvaluationSuite(Contract):
    version: Literal["supply-workflow-eval-v1", "supply-workflow-eval-v2"]
    cases: Annotated[tuple[EvaluationCase, ...], Field(min_length=1, max_length=500)]


def evaluate(path: Path, variant: str = "fixed-v1") -> dict[str, object]:
    if variant not in ("fixed-v1", "validated-v2"):
        raise ValueError("Unknown evaluation workflow")
    runner = investigate_adaptive if variant == "validated-v2" else investigate
    with path.open("rb") as file:
        payload = file.read(1000001)
    if len(payload) > 1000000:
        raise ValueError("Evaluation suite too large")
    suite = EvaluationSuite.model_validate_json(payload)
    if len({c.name for c in suite.cases}) != len(suite.cases):
        raise ValueError("Duplicate evaluation name")
    now = datetime(2026, 11, 1, 18, tzinfo=UTC)
    rows = []
    for sample in suite.cases:
        request = Request(
            tenant_id="demo",
            order_id=sample.scenario.order.order_id,
            idempotency_key=sample.name,
            as_of=now,
        )
        case_id = "evaluation:" + sample.name
        reference = baseline(request, sample.scenario, case_id, "evaluation", now)
        candidate = runner(request, sample.scenario, case_id, "evaluation", now)
        claims = {claim.code: claim.value for claim in candidate.claims}
        labels_match = (
            candidate.status == sample.expected_status
            and claims.get("DELIVERY_DELAY") == sample.expected_delay
            and claims.get("SLA_BREACH") is sample.expected_breach
            and triage(candidate).disposition == sample.expected_disposition
        )
        equivalent = reference.model_dump(exclude={"workflow"}) == candidate.model_dump(
            exclude={"workflow"}
        )
        trace = candidate.workflow
        rows.append(
            {
                "name": sample.name,
                "labels_match": labels_match,
                "baseline_equivalent": equivalent,
                "steps": len(trace.steps) if trace else 0,
                "tool_calls": sum(s.tool_calls for s in trace.steps) if trace else 0,
            }
        )
        if variant == "validated-v2":
            rows[-1]["planner_calls"] = trace.planner_calls if trace else 0
            rows[-1]["evidence_review_selected"] = bool(
                trace and any(s.name == "EVIDENCE_REVIEW" for s in trace.steps)
            )
    passed = all(r["labels_match"] and r["baseline_equivalent"] for r in rows)
    return {
        "suite_version": suite.version,
        "suite_checksum": digest(json.loads(payload)),
        "workflow_version": "bounded-supply-v2"
        if variant == "validated-v2"
        else "bounded-supply-v1",
        "cases": len(rows),
        "passed": passed,
        "model_calls": 0,
        "results": rows,
        "interpretation": "Development regression set; no held-out accuracy, latency or improvement claim.",
    }
