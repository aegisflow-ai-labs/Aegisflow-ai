# ADR-003 — Explicit PostgreSQL migration and transactional persistence

Status: accepted for the synthetic pilot, 2026-11-01.

Add psycopg 3 as a second persistence adapter. Keep the SQLite CLI and domain
contracts unchanged. The HTTP factory uses PostgreSQL when AEGISFLOW_DATABASE_URL
is explicitly configured; connection failures never silently fall back to SQLite.
The initial migration is versioned in postgres.py and invoked separately with a
schema-owner credential. Application startup checks schema version 1 without DDL.
Migration DDL and version insertion share a transaction; a migration advisory lock
serializes concurrent attempts. Unknown versions fail closed. No existing SQLite
data is copied automatically, and no destructive downgrade command is provided.

The PostgreSQL adapter uses parameterized SQL and one transaction for each case and
its three audit events. A transaction-level advisory lock derived from tenant/key
serializes identical requests; UNIQUE(tenant_id, request_key) also protects storage.
Hash collisions can serialize unrelated requests but cannot change request identity.
A mismatched fingerprint returns conflict. Read-after-write validates the persisted
case before commit. All connections have 5-second connection, statement and lock
limits. Operations fail explicitly rather than retrying unknown writes.

Audit rows use a composite tenant/case foreign key. UPDATE, DELETE and TRUNCATE are
rejected by a trigger. Runtime credentials need only schema USAGE, schema-version
SELECT, and case/event SELECT+INSERT. They must not own tables. Tests prove these
grants support the workflow while denying migration, DDL and audit mutation.
Schema owners and superusers can still alter triggers; this is not tamper-proof
external audit storage. Source snapshots remain in the case document.

Tenant authorization is enforced by the application on all reads/writes and by the
composite FK on audit references. Row-level security is not implemented: the runtime
DB credential can SELECT rows for all tenants. Do not describe this as production
multi-tenant isolation. OIDC, RLS, connection pooling, backups, schema upgrades,
separate audit sealing, production deployment and performance evaluation remain open.
No additional expert role is counted as implemented by this adapter.

Validation: PostgreSQL 18.4 locally, isolated databases per integration test; CI uses
PostgreSQL 18. Tests cover migration/reopen/version rejection, concurrent replay,
fingerprint conflict, tenant access, composite foreign keys, transaction rollback,
append-only audit, non-owner runtime permissions, and HTTP evidence/error behavior.
