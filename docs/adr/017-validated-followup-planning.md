# ADR-017: Validated follow-up proposals and selective evidence review

Status: implemented for review

## Decision

After the fixed source check and SLA analysis, bounded-supply-v2 makes exactly
one rule-based follow-up proposal. Complete cases proceed to TRIAGE; incomplete
or conflicting cases require EVIDENCE_REVIEW then TRIAGE. Review verifies all
captured snapshot checksums, preserves uncertainty and never fills missing facts.

The proposal boundary is closed and treated as untrusted: only A21 and the two
follow-up step names are permitted; no arbitrary tools, URLs, authorization,
approval or execution instructions are accepted. Ordering/reason must agree with
server policy, the remaining step budget must suffice, and a canonical context
digest binds the proposal to case, tenant, source, status and evidence gaps.
Revalidate model instances too, so unchecked model_copy cannot bypass validation.

The planner receives typed status metadata, not source prose or instructions.
Production uses the local deterministic proposer. An optional programmatic
callback exists for boundary tests/controlled extensions; it is trusted code,
not a sandbox for arbitrary Python or a model-provider integration. No LLM or
network planner is configured. Planner failure/invalid output stops the workflow;
there is no hidden fallback or retry. The existing cooperative deadline also
checks planner return. Python calls cannot be preempted by these checkpoints.

## Persistence and compatibility

New stored cases use v2 (up to four steps, one planner invocation, one logical
in-memory source read, zero model calls). Validated proposals and chosen steps are
persisted with the case. Invalid plans create no case/success event inside the
existing SQLite/PostgreSQL transaction boundary. API creation still accepts only
order/time, not a caller plan or budget. Source and tenant authorization remain
before orchestration. State changes still require their separate approval path.

Fixed v1 is retained as an explicitly callable/evaluable runner. Existing cases
and idempotency replays retain their original trace, including v1 or no trace.
Readers must support v2 before deploying v2 writers. There is no SQL migration.
This implements orchestration controls, not A24 or other full specialist roles.

## Evaluation and acceptance

Retain the recorded 12-case v1 suite/report unchanged. Add a versioned 24-case v2
development suite and explicit CLI workflow selection. Added labels cover combined
missing sources, future/stale inventory, exact freshness boundary, zero/week SLA,
identical duplicate events, same-ID conflicts and future delivery.
Reports check expected business labels and equivalence to the original baseline,
plus actual step/planner counts and evidence-review selection. CI publishes both.

Negative tests cover unknown steps/roles/extra fields, skipped or unnecessary
review, wrong context, model-copy bypass, insufficient remaining budget,
planner exception/deadline, corrupted evidence and rollback under SQLite and
restricted PostgreSQL RLS. Browser checks show three-step complete versus
four-step incomplete outcomes.

These are labeled synthetic development regressions, not held-out accuracy or
PDF benchmark results. Next: an evidence acquisition boundary and evaluation
of task selection before selecting any external model provider, egress policy
and monetary budget.
