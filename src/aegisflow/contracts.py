"""Versioned, closed contracts. Source text never grants permissions."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .integrity import digest

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1


class Scope(Contract):
    """Trusted local caller context; NOT an authentication mechanism."""

    tenant_id: Identifier
    subject_id: Identifier
    permissions: frozenset[Literal["investigate", "read", "approve", "execute"]]


class Request(Contract):
    tenant_id: Identifier
    order_id: Identifier
    idempotency_key: Identifier
    as_of: AwareDatetime


class Order(Contract):
    order_id: Identifier
    tenant_id: Identifier
    quantity: Annotated[int, Field(strict=True, gt=0)]
    promised_at: AwareDatetime
    placed_at: AwareDatetime

    @model_validator(mode="after")
    def chronology(self) -> "Order":
        if self.promised_at < self.placed_at:
            raise ValueError("Teslim tarihi sipariş tarihinden önce olamaz")
        return self


class Delivery(Contract):
    event_id: Identifier
    order_id: Identifier
    delivered_at: AwareDatetime


class Inventory(Contract):
    available: Annotated[int, Field(strict=True, ge=0)]
    captured_at: AwareDatetime


class SLA(Contract):
    grace_seconds: Annotated[int, Field(strict=True, ge=0, le=604800)]
    version: Identifier


class Procedure(Contract):
    version: Identifier
    instruction: Literal["Escalate to procurement after SLA breach"]


class Scenario(Contract):
    dataset_version: Literal["supply-delay-v1"] = "supply-delay-v1"
    seed: int
    generator_version: Literal["1"] = "1"
    source_uri: Literal["synthetic://supply-delay-v1"] = "synthetic://supply-delay-v1"
    access_class: Literal["synthetic"] = "synthetic"
    order: Order
    deliveries: tuple[Delivery, ...]
    inventory: Inventory | None
    sla: SLA | None
    procedure: Procedure | None

    def input_source_uris(self) -> tuple[str, ...]:
        # Absence/staleness is also information about a source, so retain all inputs.
        return tuple(
            f"{self.source_uri}/{name}"
            for name in ("order", "deliveries", "sla", "inventory", "procedure")
        )

    @model_validator(mode="after")
    def references(self) -> "Scenario":
        for event in self.deliveries:
            if event.order_id != self.order.order_id:
                raise ValueError("Teslimat farklı siparişe bağlı")
            if event.delivered_at < self.order.placed_at:
                raise ValueError("Teslimat siparişten önce olamaz")
        return self


class Evidence(Contract):
    evidence_id: Identifier
    tenant_id: Identifier
    case_id: Identifier
    source_uri: str
    source_version: str
    captured_at: AwareDatetime
    checksum: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    snapshot: dict[str, object]


class Claim(Contract):
    code: Literal["DELIVERY_DELAY", "SLA_BREACH", "INVENTORY", "PROCEDURE"]
    value: int | float | bool | str
    evidence_refs: Annotated[tuple[Identifier, ...], Field(min_length=1)]


class Task(Contract):
    task_id: Identifier
    case_id: Identifier
    tenant_id: Identifier
    role_id: Literal["A21"]
    status: Literal["COMPLETED", "NEEDS_EVIDENCE"]
    policy_version: Literal["elapsed-seconds-v1"] = "elapsed-seconds-v1"
    allowed_tools: tuple[Literal["read_synthetic_snapshot"], ...] = ("read_synthetic_snapshot",)
    max_source_bytes: Literal[1000000] = 1000000


class WorkflowLimits(Contract):
    max_steps: Annotated[int, Field(strict=True, ge=1, le=8)] = 3
    max_tool_calls: Annotated[int, Field(strict=True, ge=0, le=1)] = 1
    max_source_bytes: Annotated[int, Field(strict=True, ge=1, le=1000000)] = 1000000
    deadline_ms: Annotated[int, Field(strict=True, ge=1, le=60000)] = 5000
    allowed_tools: tuple[Literal["read_synthetic_snapshot"], ...] = ("read_synthetic_snapshot",)


class PlanningContext(Contract):
    case_id: Identifier
    tenant_id: Identifier
    source_checksum: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    status: Literal["COMPLETED", "NEEDS_EVIDENCE"]
    uncertainty: tuple[
        Literal[
            "CONFLICTING_DELIVERY_EVENTS",
            "MISSING_SLA",
            "MISSING_INVENTORY",
            "STALE_OR_FUTURE_INVENTORY",
            "MISSING_PROCEDURE",
        ],
        ...,
    ]
    evidence_count: Annotated[int, Field(strict=True, ge=0, le=5)]


class FollowupPlan(Contract):
    version: Literal["followup-plan-v1"] = "followup-plan-v1"
    context_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    role_id: Literal["A21"] = "A21"
    steps: Annotated[
        tuple[Literal["EVIDENCE_REVIEW", "TRIAGE"], ...], Field(min_length=1, max_length=2)
    ]
    reason: Literal["STANDARD_TRIAGE", "EVIDENCE_GAP_REVIEW"]

    @model_validator(mode="after")
    def canonical_followup(self) -> "FollowupPlan":
        expected = (
            ("TRIAGE",) if self.reason == "STANDARD_TRIAGE" else ("EVIDENCE_REVIEW", "TRIAGE")
        )
        if self.steps != expected:
            raise ValueError("Invalid follow-up ordering")
        return self


class WorkflowStep(Contract):
    name: Literal["SOURCE_CHECK", "SLA_ANALYSIS", "EVIDENCE_REVIEW", "TRIAGE"]
    status: Literal["COMPLETED"] = "COMPLETED"
    tool_calls: Annotated[int, Field(strict=True, ge=0, le=1)] = 0


class WorkflowRun(Contract):
    version: Literal["bounded-supply-v1", "bounded-supply-v2"] = "bounded-supply-v1"
    plan: FollowupPlan | None = None
    planner_calls: Annotated[int, Field(strict=True, ge=0, le=1)] = 0
    limits: WorkflowLimits
    source_checksum: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    source_bytes: Annotated[int, Field(strict=True, ge=1)]
    steps: tuple[WorkflowStep, ...]
    disposition: Literal["ESCALATE", "MONITOR", "COLLECT_EVIDENCE"]
    model_calls: Literal[0] = 0

    @model_validator(mode="after")
    def budgets(self) -> "WorkflowRun":
        expected: tuple[str, ...] = ("SOURCE_CHECK", "SLA_ANALYSIS", "TRIAGE")
        if self.version == "bounded-supply-v2":
            if self.plan is None or self.planner_calls != 1:
                raise ValueError("Validated follow-up plan required")
            expected = ("SOURCE_CHECK", "SLA_ANALYSIS", *self.plan.steps)
        elif self.plan is not None or self.planner_calls != 0:
            raise ValueError("Fixed workflow cannot contain adaptive plan")
        if tuple(s.name for s in self.steps) != expected:
            raise ValueError("Unexpected workflow plan")
        if (
            len(self.steps) > self.limits.max_steps
            or sum(s.tool_calls for s in self.steps) > self.limits.max_tool_calls
            or self.source_bytes > self.limits.max_source_bytes
        ):
            raise ValueError("Workflow budget exceeded")
        if (
            tuple(s.tool_calls for s in self.steps) != (1,) + (0,) * (len(self.steps) - 1)
            or "read_synthetic_snapshot" not in self.limits.allowed_tools
        ):
            raise ValueError("Invalid workflow tool trace")
        return self


class Case(Contract):
    case_id: Identifier
    tenant_id: Identifier
    subject_id: Identifier
    trace_id: Identifier
    source_version: str
    source_checksum: str
    input_source_uris: tuple[Annotated[str, Field(min_length=1, max_length=1024)], ...] = ()
    status: Literal["COMPLETED", "NEEDS_EVIDENCE"]
    created_at: AwareDatetime
    as_of: AwareDatetime
    task: Task
    claims: tuple[Claim, ...]
    evidence: tuple[Evidence, ...]
    uncertainty: tuple[str, ...]
    active_roles: tuple[Literal["A21"], ...] = ("A21",)
    model_calls: Literal[0] = 0
    workflow: WorkflowRun | None = None

    @model_validator(mode="after")
    def links(self) -> "Case":
        if self.workflow is not None and self.workflow.source_checksum != self.source_checksum:
            raise ValueError("Workflow source mismatch")
        if self.workflow and self.workflow.plan:
            context = PlanningContext(
                case_id=self.case_id,
                tenant_id=self.tenant_id,
                source_checksum=self.source_checksum,
                status=self.status,
                uncertainty=self.uncertainty,
                evidence_count=len(self.evidence),
            )
            if self.workflow.plan.context_digest != digest(context.model_dump(mode="json")):
                raise ValueError("Workflow plan context mismatch")
            expected_reason = (
                "EVIDENCE_GAP_REVIEW"
                if self.status == "NEEDS_EVIDENCE" or self.uncertainty
                else "STANDARD_TRIAGE"
            )
            if self.workflow.plan.reason != expected_reason:
                raise ValueError("Workflow follow-up does not cover case uncertainty")
        refs = {e.evidence_id for e in self.evidence}
        if self.input_source_uris and any(
            e.source_uri not in self.input_source_uris for e in self.evidence
        ):
            raise ValueError("Evidence source missing from input dependencies")
        if any(set(c.evidence_refs) - refs for c in self.claims):
            raise ValueError("Kanıtsız iddia")
        if any(e.tenant_id != self.tenant_id or e.case_id != self.case_id for e in self.evidence):
            raise ValueError("Kanıt kapsamı uyuşmuyor")
        if self.task.case_id != self.case_id or self.task.tenant_id != self.tenant_id:
            raise ValueError("Görev kapsamı uyuşmuyor")
        return self


class ActionPayload(Contract):
    kind: Literal["SYNTHETIC_PROCUREMENT_REVIEW"] = "SYNTHETIC_PROCUREMENT_REVIEW"
    case_id: Identifier
    tenant_id: Identifier
    order_id: Identifier
    source_checksum: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    destination: Literal["synthetic://procurement-review"] = "synthetic://procurement-review"
    message: Annotated[str, Field(min_length=1, max_length=500)]
    evidence_refs: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=64)]
    policy_version: Literal["supply-action-v1"] = "supply-action-v1"


class Action(Contract):
    action_id: Identifier
    case_id: Identifier
    payload: ActionPayload
    content_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    status: Literal["PROPOSED", "APPROVED", "EXECUTED"]
    proposed_by: Identifier
    approved_by: Identifier | None = None
    approved_at: AwareDatetime | None = None
    receipt_id: Identifier | None = None
    external_action_executed: Literal[False] = False

    @model_validator(mode="after")
    def approval_integrity(self) -> "Action":
        if (
            self.case_id != self.payload.case_id
            or self.action_id != self.content_digest
            or digest(self.payload.model_dump(mode="json")) != self.content_digest
        ):
            raise ValueError("Action content integrity mismatch")
        if self.status == "PROPOSED":
            if (
                self.approved_by is not None
                or self.approved_at is not None
                or self.receipt_id is not None
            ):
                raise ValueError("Unapproved action contains approval or execution")
        elif self.approved_by is None or self.approved_at is None:
            raise ValueError("Approval record required")
        if self.status == "EXECUTED":
            if self.receipt_id != "synthetic:" + self.action_id:
                raise ValueError("Synthetic receipt mismatch")
        elif self.receipt_id is not None:
            raise ValueError("Unexpected execution receipt")
        return self


class AuditEvent(Contract):
    event_id: Identifier
    tenant_id: Identifier
    case_id: Identifier
    trace_id: Identifier
    revision: Annotated[int, Field(gt=0)]
    event_type: Literal[
        "CaseCreated",
        "EvidenceCollected",
        "InvestigationCompleted",
        "ActionProposed",
        "ActionApproved",
        "ActionExecuted",
    ]
    occurred_at: AwareDatetime
    producer: Literal["deterministic-baseline-v1", "action-workflow-v1"] = (
        "deterministic-baseline-v1"
    )
    action_record: Action | None = None
    actor_id: Identifier | None = None
    causation_id: Identifier
    payload_refs: tuple[Identifier, ...]

    @model_validator(mode="after")
    def action_scope(self) -> "AuditEvent":
        if self.event_type.startswith("Action"):
            expected = {
                "ActionProposed": "PROPOSED",
                "ActionApproved": "APPROVED",
                "ActionExecuted": "EXECUTED",
            }
            if (
                self.action_record is None
                or self.action_record.status != expected[self.event_type]
                or self.producer != "action-workflow-v1"
                or self.action_record.case_id != self.case_id
                or self.action_record.payload.tenant_id != self.tenant_id
            ):
                raise ValueError("Action event scope mismatch")
        elif self.action_record is not None:
            raise ValueError("Unexpected action record")
        return self
