"""Closed proposal boundary; deterministic policy remains authoritative."""

from collections.abc import Callable

from pydantic import ValidationError

from .contracts import Case, FollowupPlan, PlanningContext, WorkflowLimits
from .integrity import digest

Planner = Callable[[PlanningContext], object]


class PlanRejected(Exception):
    pass


class PlannerUnavailable(Exception):
    pass


def context_for(case: Case) -> PlanningContext:
    return PlanningContext(
        case_id=case.case_id,
        tenant_id=case.tenant_id,
        source_checksum=case.source_checksum,
        status=case.status,
        uncertainty=case.uncertainty,
        evidence_count=len(case.evidence),
    )


def propose(context: PlanningContext) -> object:
    gaps = context.status == "NEEDS_EVIDENCE" or bool(context.uncertainty)
    return {
        "context_digest": digest(context.model_dump(mode="json")),
        "steps": ["EVIDENCE_REVIEW", "TRIAGE"] if gaps else ["TRIAGE"],
        "reason": "EVIDENCE_GAP_REVIEW" if gaps else "STANDARD_TRIAGE",
    }


def validate(raw: object, context: PlanningContext, limits: WorkflowLimits) -> FollowupPlan:
    try:
        # Revalidate model objects too; model_copy is not a trusted validation boundary.
        plan = FollowupPlan.model_validate(
            raw.model_dump() if isinstance(raw, FollowupPlan) else raw
        )
    except ValidationError as error:
        raise PlanRejected("INVALID_PLAN_SCHEMA") from error
    if plan.context_digest != digest(context.model_dump(mode="json")):
        raise PlanRejected("PLAN_CONTEXT_MISMATCH")
    gaps = context.status == "NEEDS_EVIDENCE" or bool(context.uncertainty)
    expected = ("EVIDENCE_REVIEW", "TRIAGE") if gaps else ("TRIAGE",)
    reason = "EVIDENCE_GAP_REVIEW" if gaps else "STANDARD_TRIAGE"
    if plan.steps != expected or plan.reason != reason:
        raise PlanRejected("REQUIRED_FOLLOWUP_MISMATCH")
    if 2 + len(plan.steps) > limits.max_steps:
        raise PlanRejected("PLAN_EXCEEDS_REMAINING_BUDGET")
    return plan
