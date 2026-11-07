"""Fixed, bounded workflow foundation. No model planner or external tool execution."""

import time
from collections.abc import Callable
from datetime import datetime

from .contracts import Case, Request, Scenario, WorkflowLimits, WorkflowRun, WorkflowStep
from .engine import investigate as baseline
from .integrity import canonical, digest
from .triage import triage


class WorkflowBudgetExceeded(Exception):
    pass


def investigate(
    request: Request,
    scenario: Scenario,
    case_id: str,
    subject_id: str,
    now: datetime,
    *,
    limits: WorkflowLimits | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Case:
    limits = limits or WorkflowLimits()
    started = clock()

    def checkpoint() -> None:
        if (clock() - started) * 1000 >= limits.deadline_ms:
            raise WorkflowBudgetExceeded("DEADLINE_EXCEEDED")

    # Reject an impossible plan before reading sources or doing analysis.
    if limits.max_steps < 3 or limits.max_tool_calls < 1:
        raise WorkflowBudgetExceeded("PLAN_EXCEEDS_BUDGET")
    if "read_synthetic_snapshot" not in limits.allowed_tools:
        raise WorkflowBudgetExceeded("TOOL_NOT_ALLOWED")
    if scenario.order.tenant_id != request.tenant_id or scenario.order.order_id != request.order_id:
        raise ValueError("Workflow source scope mismatch")
    checkpoint()
    serialized = canonical(scenario.model_dump(mode="json"))
    source_bytes = len(serialized.encode("utf-8"))
    if source_bytes > limits.max_source_bytes:
        raise WorkflowBudgetExceeded("SOURCE_BYTES_EXCEEDED")
    checkpoint()
    case = baseline(request, scenario, case_id, subject_id, now)
    checkpoint()
    disposition = triage(case).disposition
    checkpoint()
    trace = WorkflowRun(
        limits=limits,
        source_checksum=digest(scenario.model_dump(mode="json")),
        source_bytes=source_bytes,
        steps=(
            WorkflowStep(name="SOURCE_CHECK", tool_calls=1),
            WorkflowStep(name="SLA_ANALYSIS"),
            WorkflowStep(name="TRIAGE"),
        ),
        disposition=disposition,
    )
    result = Case.model_validate({**case.model_dump(), "workflow": trace})
    checkpoint()
    return result
