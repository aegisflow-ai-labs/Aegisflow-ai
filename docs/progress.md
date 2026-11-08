# Scope progress — 2026-11-08

This is a scope assessment, not a measured completion metric. Technical-design
PDF targets are not measured results. PR contents are review-ready work until
merged; mainline status must be checked independently.

## Current acceptance evidence

The initial deterministic vertical slice is implemented and verified: versioned
requirements/ADRs and contracts, seeded supply scenario, evidence-linked delay/SLA
analysis, abstention, persistence/audit, idempotency, tests and CI.

Additional implemented pilot infrastructure includes authenticated tenant/source
access, PostgreSQL RLS, multi-page case/evidence/audit views and exact-content
approval with atomic synthetic action receipts. External business execution is
not implemented.

The fixed workflow retains its 12-case labeled regression evaluation. This slice
adds a validated follow-up proposal boundary, selective integrity review on
uncertain cases and a separate 24-case development evaluation. Passing it does not establish general accuracy, production
readiness or PDF benchmark targets.

## Overall estimate

Approximately **15–20% of the complete PDF product vision** is addressed, as an
engineering scope estimate. The initial deterministic slice's acceptance is met;
the broader agentic product remains early. This range is not computed from test
counts, page counts or the number of registered roles. Scope weights have not been
formally agreed, so a precise percentage would be misleading.

Remaining major work: adaptive planning/routing, most specialist capabilities,
real data connectors, alternative/risk/cost reasoning, production approval and
dispatch/recovery, held-out evaluation and operational deployment/observability.

Role status remains: 36 registered; one A21 subset implemented; one subset tested;
one role activated in the golden case. Model calls remain zero. Infrastructure
resembling a role is not counted as a completed specialist.
