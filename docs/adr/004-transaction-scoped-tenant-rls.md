# ADR-004 — Transaction-scoped PostgreSQL tenant RLS

Status: accepted for the synthetic pilot, 2026-11-01. Depends on ADR-003.

Migration 2 enables and forces row-level security on case and audit tables. Policies
use the tenant_id column for both USING and WITH CHECK. Missing/empty tenant context
matches no valid tenant: reads return no rows and inserts fail. Existing v1 data,
request fingerprints and grants are retained. DDL and schema-version advancement
share one transaction. Unknown schema versions are rejected. Migration replay is safe.

The adapter derives tenant context from trusted Scope, sets it using parameterized
set_config(..., true) inside the operation transaction, and retains explicit SQL
predicates. Context expires at commit/rollback, including on a reused connection.
Idempotency lookup, writes, read-after-write and audit reads use the same discipline.
The HTTP factory checks for active/forced RLS and rejects privileged roles, roles
with membership in privileged roles, and membership in either table's owning role.
Superusers/BYPASSRLS roles bypass PostgreSQL RLS even when FORCE is set, which is why
they must not serve HTTP. Administrative low-level adapter access remains available
for maintenance and tests; its results do not validate runtime isolation.

## Boundary and remaining risks

This is defense against omitted tenant predicates by trusted application code, not
protection against a compromised application/DB credential. A runtime SQL session
can set a custom PostgreSQL tenant variable to another tenant. Scope creation and
SQL remain trusted server operations: clients and models receive no SQL access or
ability to supply context. OIDC, credential lifecycle, per-source ACL/revocation,
SQL-injection hardening review, operational monitoring and production acceptance
remain separate work. Database owners can alter policies/triggers. Startup checks
are configuration guards, not proof against subsequent administrator changes.
RLS does not replace audit immutability or prevent constraint-based existence side
channels for an actor already possessing SQL access. See the PostgreSQL 18
[row-security reference](https://www.postgresql.org/docs/18/ddl-rowsecurity.html).

## Rollout

For this synthetic pilot, stop the v1 API, back up the development database, apply
migration 2 with the schema-owner credential, and start the v2 adapter using the
non-owner runtime credential. Old adapter v1 rejects schema 2: do not call this a
zero-downtime/backward-compatible application rollout. No automatic downgrade or
policy removal is provided. On migration error, the transaction rolls back the new
policies and version. Rerun only after addressing the reported schema conflict.

## Acceptance

Real PostgreSQL tests cover blank/missing context, unfiltered reads of case/audit
tables, cross-tenant writes, independent same-key requests in two tenants, commit
and rollback context clearing, v1 data preservation, migration failure rollback,
privileged/BYPASSRLS runtime rejection and disabled-RLS rejection. Existing domain,
API and storage tests remain required. Role counts are unchanged; OIDC/A02 is not
claimed as complete.
