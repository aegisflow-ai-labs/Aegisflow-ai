"""Pure baseline: elapsed UTC seconds, no inference of root cause."""

import hashlib
import json
from datetime import UTC, datetime

from .contracts import Case, Claim, Evidence, Request, Scenario, Task


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def investigate(
    request: Request, scenario: Scenario, case_id: str, subject_id: str, now: datetime
) -> Case:
    evidence: list[Evidence] = []
    claims: list[Claim] = []
    uncertainty: list[str] = []

    def capture(name: str, snapshot: dict[str, object], version: str) -> str:
        ref = f"{case_id}:{name}"
        evidence.append(
            Evidence(
                evidence_id=ref,
                tenant_id=request.tenant_id,
                case_id=case_id,
                source_uri=f"{scenario.source_uri}/{name}",
                source_version=version,
                captured_at=now,
                checksum=digest(snapshot),
                snapshot=snapshot,
            )
        )
        return ref

    order = scenario.order
    order_ref = capture("order", order.model_dump(mode="json"), scenario.dataset_version)
    if request.as_of < order.placed_at:
        raise ValueError("İnceleme zamanı sipariş tarihinden önce olamaz")
    seen: dict[str, dict[str, object]] = {}
    delivered: set[datetime] = set()
    conflict = False
    for event in scenario.deliveries:
        payload = event.model_dump(mode="json")
        if event.event_id in seen and seen[event.event_id] != payload:
            conflict = True
        seen[event.event_id] = payload
        if event.delivered_at <= request.as_of:
            delivered.add(event.delivered_at.astimezone(UTC))
    delivery_ref = capture("deliveries", {"events": list(seen.values())}, scenario.dataset_version)
    if conflict or len(delivered) > 1:
        uncertainty.append("CONFLICTING_DELIVERY_EVENTS")
    else:
        endpoint = next(iter(delivered), request.as_of.astimezone(UTC))
        delay = max(0, (endpoint - order.promised_at.astimezone(UTC)).total_seconds())
        claims.append(
            Claim(code="DELIVERY_DELAY", value=delay, evidence_refs=(order_ref, delivery_ref))
        )
        if scenario.sla is None:
            uncertainty.append("MISSING_SLA")
        else:
            sla_ref = capture("sla", scenario.sla.model_dump(mode="json"), scenario.sla.version)
            claims.append(
                Claim(
                    code="SLA_BREACH",
                    value=delay > scenario.sla.grace_seconds,
                    evidence_refs=(order_ref, delivery_ref, sla_ref),
                )
            )
    if scenario.inventory is None:
        uncertainty.append("MISSING_INVENTORY")
    elif not 0 <= (request.as_of - scenario.inventory.captured_at).total_seconds() <= 86400:
        uncertainty.append("STALE_OR_FUTURE_INVENTORY")
    else:
        ref = capture(
            "inventory", scenario.inventory.model_dump(mode="json"), scenario.dataset_version
        )
        claims.append(
            Claim(code="INVENTORY", value=scenario.inventory.available, evidence_refs=(ref,))
        )
    if scenario.procedure is None:
        uncertainty.append("MISSING_PROCEDURE")
    else:
        ref = capture(
            "procedure", scenario.procedure.model_dump(mode="json"), scenario.procedure.version
        )
        claims.append(
            Claim(code="PROCEDURE", value=scenario.procedure.instruction, evidence_refs=(ref,))
        )
    status = "NEEDS_EVIDENCE" if uncertainty else "COMPLETED"
    return Case(
        case_id=case_id,
        tenant_id=request.tenant_id,
        subject_id=subject_id,
        trace_id=f"trace:{case_id}",
        source_version=scenario.dataset_version,
        source_checksum=digest(scenario.model_dump(mode="json")),
        input_source_uris=scenario.input_source_uris(),
        status=status,
        created_at=now,
        as_of=request.as_of,
        task=Task(
            task_id=f"task:{case_id}",
            case_id=case_id,
            tenant_id=request.tenant_id,
            role_id="A21",
            status=status,
        ),
        claims=tuple(claims),
        evidence=tuple(evidence),
        uncertainty=tuple(uncertainty),
    )
