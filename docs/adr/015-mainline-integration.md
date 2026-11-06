# ADR-015: Integrate the workspace and controlled-action slices

Status: implemented for review

## Context

PR #12 was approved and merged into the PR #11 feature branch. PR #10 separately
reached main, so the workspace branch could not merge cleanly. Starting another
product slice before resolving this would accumulate incompatible UI assumptions.

## Resolution

Merge main into the workspace branch. Keep the current multi-page shell,
persisted case views, controlled actions and sign-in recovery. Do not restore the
superseded single-page layout or its unused rendering functions.

Preserve main's security regression by adapting the untrusted source URI/snapshot
escaping check to the current case workbench. Preserve the checksum disclosure,
desktop overflow and mobile landscape browser checks alongside the existing
navigation, sign-in return, evidence, scenario and action lifecycle checks.

CI also exposed horizontal overflow with long unresolved results at landscape width. Bound metric grid tracks and allow metrics/map controls to wrap instead of weakening the overflow assertions.

No dependency versions, data contracts, migrations, business rules or specialist
implementation states are changed by this integration. Update current README
wording to describe the actual map preview and persisted case views.

## Acceptance and next slice

Run the required lint, format, strict type and full SQLite/PostgreSQL checks,
real Keycloak browser flow and dependency audit on the merged tree. CI must check
the resulting head. Human review of PR #11 is still required before mainline merge;
approval of its already-merged child PR is not approval of the complete parent.

After integration acceptance, the next planned capability is a bounded,
versioned investigation workflow with explicit task/tool budgets and a
reproducible baseline evaluation. Additional role implementation or model use
must be supported by its own acceptance evidence.
