# ADR-014: Exact-content approval and atomic synthetic execution

Status: implemented for review

## Decision

Connect evidenced escalation recommendations to a controlled action workflow.
Only complete, escalation-eligible cases may propose a fixed procurement-review
payload. The server chooses kind, tenant, case, order, destination, source
checksum, evidence references and message; clients cannot supply arbitrary actions.

Canonical JSON SHA-256 identifies the full payload. The action ID is its digest.
Approval records identity and aware timestamp against that exact digest.
Execution verifies it again and requires a recorded approval.

Use the existing append-only case event tables as the action ledger:
ActionProposed, ActionApproved, ActionExecuted each carry a closed, validated
Action snapshot. This is an additive v1 contract extension; old case/audit records
remain readable through the absent optional action_record default.
Readers must be upgraded before writers use the new event kinds. No SQL migration
or extra database privilege is required.

SQLite BEGIN IMMEDIATE and PostgreSQL transaction advisory locks serialize
transitions per case. State is reconstructed within the write transaction.
Repeated requests return the current action without another event. A synthetic
execution consists of one committed ActionExecuted record with a deterministic
receipt; no external effect is attempted. Read-after-insert verifies the persisted
record before commit. Insert failure rolls back the transition.

## Access and browser behavior

Read and current source permissions gate every API/browser operation.
Proposing requires investigate, approving requires approve, and executing requires
execute. Cookie writes retain CSRF and origin checks. The local helper provides
an explicit enable-synthetic-actions operator command; startup does not expand
existing principal grants. It preserves principal identity, existing grants and
revocation cutoffs. Browser tests opt in only for the local synthetic account.

Action center and case links expose the full payload, digest, status and receipt.
Case and action event scopes are validated. Source text never grants permissions.
This implements workflow infrastructure, not the full A28/A29/A30 specialist roles.

## Verification and scope

Tests cover no proposal/on-time/missing/conflicting cases, content tampering,
permission/tenant/source revocation, CSRF, replay, eight concurrent executions,
SQLite reopen, PostgreSQL restricted runtime role/RLS and rollback on insert error.
The real Keycloak browser check runs proposal, explicit approval and execution.

The synthetic receipt is the simulator's effect ledger, not proof of delivery to
an external system. Production requires separate approvers as policy dictates,
expiry/rejection/cancellation, durable dispatch, connector-specific idempotency,
postcondition verification and recovery. These are not implemented by this ADR.
