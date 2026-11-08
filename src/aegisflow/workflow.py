"""Fixed, bounded workflow foundation. No model planner or external tool execution."""

import time
from collections.abc import Callable
from datetime import datetime

from .contracts import Case, Request, Scenario, WorkflowLimits, WorkflowRun, WorkflowStep
from .engine import investigate as baseline
from .integrity import canonical, digest
from .planning import Planner, PlannerUnavailable, PlanRejected, context_for, propose, validate
from .triage import triage


class WorkflowBudgetExceeded(Exception):
    pass


def _run(
    request: Request,
    scenario: Scenario,
    case_id: str,
    subject_id: str,
    now: datetime,
    *,
    limits: WorkflowLimits | None = None,
    clock: Callable[[], float] = time.monotonic,
    planner: Planner | None = None,
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
    plan = None
    steps = [WorkflowStep(name="SOURCE_CHECK", tool_calls=1), WorkflowStep(name="SLA_ANALYSIS")]
    if planner is not None:
        context = context_for(case)
        try:
            raw = planner(context)
        except Exception as error:
            raise PlannerUnavailable("PLANNER_UNAVAILABLE") from error
        checkpoint()
        plan = validate(raw, context, limits)
        if "EVIDENCE_REVIEW" in plan.steps:
            if any(digest(e.snapshot) != e.checksum for e in case.evidence):
                raise PlanRejected("EVIDENCE_INTEGRITY_MISMATCH")
            steps.append(WorkflowStep(name="EVIDENCE_REVIEW"))
            checkpoint()
    disposition = triage(case).disposition
    steps.append(WorkflowStep(name="TRIAGE"))
    checkpoint()
    trace = WorkflowRun(
        limits=limits,
        source_checksum=digest(scenario.model_dump(mode="json")),
        source_bytes=source_bytes,
        steps=tuple(steps),
        version="bounded-supply-v2" if plan else "bounded-supply-v1",
        plan=plan,
        planner_calls=1 if plan else 0,
        disposition=disposition,
    )
    result = Case.model_validate({**case.model_dump(), "workflow": trace})
    checkpoint()
    return result


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
    return _run(request, scenario, case_id, subject_id, now, limits=limits, clock=clock)


def investigate_adaptive(
    request: Request,
    scenario: Scenario,
    case_id: str,
    subject_id: str,
    now: datetime,
    *,
    limits: WorkflowLimits | None = None,
    clock: Callable[[], float] = time.monotonic,
    planner: Planner = propose,
) -> Case:
    return _run(
        request,
        scenario,
        case_id,
        subject_id,
        now,
        limits=limits or WorkflowLimits(max_steps=4),
        clock=clock,
        planner=planner,
    )
