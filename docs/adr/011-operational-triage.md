# ADR-011: Evidence-gated operational triage

Status: accepted for the synthetic pilot

The single-order browser demo proved infrastructure but did not help users distinguish
operational outcomes. Add five reproducible orders and a versioned decision-support
policy before adding a model or external actions. This slice is independent of PR #10;
its proposed visual redesign is not an accepted requirement.

## Behavior

The local Keycloak demo loads supply-triage-suite-v1:
PO-001 late delivery (7 hours); PO-002 on-time delivery; PO-003 missing SLA;
PO-004 conflicting delivery records; PO-005 no delivery recorded (9 hours overdue).
All use the same synthetic source namespace and existing source ACL. The namespace
is dataset-scoped, not an order-level authorization boundary.

GET /v1/orders lists only orders in the caller's tenant whose input sources the
caller can investigate. Browser selection uses this catalog and rechecks permissions
on submission. Investigation time is explicitly fixed at 2026-11-01T18:00:00Z.

GET /v1/cases/{case_id}/triage returns supply-triage-v1, derived from the
persisted case and protected by case read and source permissions:
- Missing/conflicting evidence: COLLECT_EVIDENCE, never an escalation recommendation.
- Complete evidence and SLA breach: ESCALATE, backed by the captured procedure.
- Complete evidence within SLA: MONITOR.

The response includes case ID, policy version, evidence references, gaps and an
explicit false external-action flag. It is a reproducible read projection, not a
new persisted action, approval or audit event. Original cases and audit records
remain unchanged. Any future policy revision requires a new version; this endpoint
currently exposes only v1.

## Limits and next slice

This is recommendation support, not autonomous procurement. Root cause, supplier
risk, stockout impact, alternative sourcing costs and business-day calendars cannot
be inferred from these inputs. No new specialist role is claimed.
Next: versioned action proposals with exact-payload approval, execution ledger and
idempotent synthetic adapter, before any real external writes.
