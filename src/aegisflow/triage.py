"""Deterministic decision support derived only from a persisted investigation."""

from typing import Literal

from .contracts import Case, Contract, Identifier


class Triage(Contract):
    case_id: Identifier
    policy_version: Literal["supply-triage-v1"] = "supply-triage-v1"
    disposition: Literal["ESCALATE", "MONITOR", "COLLECT_EVIDENCE"]
    next_step: str
    rationale: str
    evidence_refs: tuple[Identifier, ...]
    missing_evidence: tuple[str, ...]
    external_action_executed: Literal[False] = False


def triage(case: Case) -> Triage:
    claims = {claim.code: claim for claim in case.claims}
    breach, procedure = claims.get("SLA_BREACH"), claims.get("PROCEDURE")
    missing = list(case.uncertainty)
    if breach is None:
        missing.append("SLA_RESULT_UNAVAILABLE")
    if procedure is None:
        missing.append("PROCEDURE_UNAVAILABLE")
    refs = tuple(dict.fromkeys(ref for claim in case.claims for ref in claim.evidence_refs))
    if case.status != "COMPLETED" or missing:
        disposition = "COLLECT_EVIDENCE"
        next_step = "Resolve the listed evidence gaps, then investigate again."
        rationale = "The available evidence does not support an operational recommendation."
    elif breach is not None and breach.value is True:
        disposition = "ESCALATE"
        next_step = "Have a procurement owner review the SLA breach and contact the supplier."
        rationale = "Delivery delay exceeds the agreed grace period; the captured procedure requires escalation."
    elif breach is not None and breach.value is False:
        disposition = "MONITOR"
        next_step = (
            "Continue monitoring delivery; the current SLA rule does not require escalation."
        )
        rationale = "The observed delay is within the supplier SLA grace period."
    else:
        disposition = "COLLECT_EVIDENCE"
        next_step = "Verify the SLA result before making an operational decision."
        rationale = "The SLA result is not a boolean decision."
        missing.append("INVALID_SLA_RESULT")
    return Triage(
        case_id=case.case_id,
        disposition=disposition,
        next_step=next_step,
        rationale=rationale,
        evidence_refs=refs,
        missing_evidence=tuple(dict.fromkeys(missing)),
    )
