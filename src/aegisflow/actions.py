"""Exact-content approval and idempotent synthetic execution, backed by audit events."""

from datetime import datetime

from .contracts import Action, ActionPayload, AuditEvent, Case, Scope
from .engine import digest
from .store import PolicyDenied
from .triage import triage


class ActionConflict(Exception):
    pass


def transition(
    case: Case,
    events: tuple[AuditEvent, ...],
    scope: Scope,
    operation: str,
    expected_digest: str | None,
    now: datetime,
) -> tuple[Action, str | None]:
    permission = {"propose": "investigate", "approve": "approve", "execute": "execute"}.get(
        operation
    )
    if permission is None or permission not in scope.permissions:
        raise PolicyDenied("POLICY_DENIED")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone-aware clock required")
    previous = next((e for e in reversed(events) if e.action_record is not None), None)
    action = previous.action_record if previous else None
    if operation == "propose":
        if action is not None:
            return action, None
        decision = triage(case)
        if decision.disposition != "ESCALATE":
            raise ActionConflict("CASE_NOT_ACTIONABLE")
        order = next(e for e in case.evidence if e.evidence_id.endswith(":order"))
        payload = ActionPayload(
            case_id=case.case_id,
            tenant_id=case.tenant_id,
            order_id=str(order.snapshot["order_id"]),
            source_checksum=case.source_checksum,
            message="Request procurement review of the evidenced supplier SLA breach.",
            evidence_refs=decision.evidence_refs,
        )
        checksum = digest(payload.model_dump(mode="json"))
        return Action(
            action_id=checksum,
            case_id=case.case_id,
            payload=payload,
            content_digest=checksum,
            status="PROPOSED",
            proposed_by=scope.subject_id,
        ), "ActionProposed"
    if action is None:
        raise ActionConflict("PROPOSAL_REQUIRED")
    if (
        expected_digest != action.content_digest
        or digest(action.payload.model_dump(mode="json")) != action.content_digest
    ):
        raise ActionConflict("ACTION_CONTENT_MISMATCH")
    if operation == "approve":
        if action.status in ("APPROVED", "EXECUTED"):
            return action, None
        return action.model_copy(
            update={"status": "APPROVED", "approved_by": scope.subject_id, "approved_at": now}
        ), "ActionApproved"
    if action.status == "PROPOSED":
        raise ActionConflict("APPROVAL_REQUIRED")
    if action.status == "EXECUTED":
        return action, None
    # The synthetic queue receipt is committed in the same immutable event as execution.
    receipt = "synthetic:" + action.action_id
    return action.model_copy(update={"status": "EXECUTED", "receipt_id": receipt}), "ActionExecuted"
