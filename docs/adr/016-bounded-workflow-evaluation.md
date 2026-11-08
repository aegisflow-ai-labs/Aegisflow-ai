# ADR-016: Bounded investigation workflow and baseline evaluation

Status: accepted fixed-v1 foundation; new cases use v2 as described in ADR-017.

## Decision and acceptance

Wrap the existing pure baseline in bounded-supply-v1: SOURCE_CHECK,
SLA_ANALYSIS, TRIAGE. This is a fixed deterministic workflow foundation,
not an LLM planner or a newly implemented specialist role.

The server uses a closed limits contract: three steps, one logical in-memory
read_synthetic_snapshot invocation, at most 1,000,000 UTF-8 canonical source
bytes, and a 5,000 ms checkpoint deadline by default. Limits cannot be supplied
through case creation or source text. Reject impossible plans/denied tools before
analysis and reject oversized sources before the baseline is called.
Deadline checks occur between synchronous stages and before return; they do not
preempt running Python or bound database commit time. No hard real-time guarantee
is claimed.

Persist the validated workflow trace inside new cases, tied to source checksum.
Workflow completion means its stages completed, including NEEDS_EVIDENCE outcomes.
The existing authenticated/source-authorized store path executes the wrapper
before inserting a case, so budget failure persists no case or success event.
Existing case audit and action boundaries remain intact. Old case JSON without
workflow is readable; replay preserves that historical record instead of
backfilling an invented trace. No SQL migration is needed.
Defaults are server code, not client-configurable resource grants. Programmatic
limits are available for tests/controlled callers; fingerprint/version migration
policy must be decided before exposing configurable execution policies.

## Evaluation

supply-workflow-eval-v1 contains 12 explicit labeled synthetic development cases:
five pilot outcomes; below/equal/above SLA boundaries; missing/stale inventory;
missing procedure; equivalent timezone offsets. The evaluation checks independent
expected status/delay/SLA/disposition labels AND baseline/candidate business
projection equivalence, excluding only the added workflow trace.

The baseline remains directly callable and unchanged. The evaluation deliberately
calls the same baseline inside the candidate: this proves orchestration regression
compatibility, not independent model accuracy or an algorithmic quality gain.
The versioned source fixture, suite checksum and deterministic JSON report are
committed. CLI returns nonzero on disagreement. CI reruns it and publishes its
report for Python 3.12/3.14.

Acceptance:
- Budget, tool allowlist, deadline and scope failures tested.
- Source-linked trace survives reopen/replay in SQLite/PostgreSQL.
- Rejected workflow creates no case/success audit, including restricted RLS runtime.
- Baseline and labels match in all 12 development fixtures.
- Historical cases remain readable; browser exposes trace or its absence.
- Role state remains 36 registered, one implemented/tested A21 subset, one
  activated role in the golden case, zero model calls.

Next: richer evaluation coverage and a constrained proposal/validation boundary
for adaptive task selection. A model provider, data egress and cost ceiling must
be explicitly configured before any model integration.
