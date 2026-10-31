# AegisFlow AI

**Evidence-driven operational decision support with deterministic controls and auditable workflows.**

[![CI](https://github.com/aegisflow-ai-labs/Aegisflow-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/aegisflow-ai-labs/Aegisflow-ai/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

AegisFlow AI investigates operational cases using traceable evidence and versioned
business rules. The long-term design introduces selectively activated specialists
and human-approved actions. Development starts with a reproducible, LLM-free
supplier-delay baseline, then adds capabilities in small, verified increments.

**Status:** synthetic, local-development prototype. The technical design PDF is a
target architecture; its performance values and roadmap are not measured results.
Code and documentation describe the current checkout; open PRs may contain features
that have not reached `main` yet.

## Implemented capabilities

- Deterministic order/delivery/SLA investigation using seeded synthetic inputs.
- Evidence-linked claims with source versions, immutable snapshots and SHA-256 checksums.
- Explicit uncertainty for missing, stale or conflicting evidence.
- Closed Pydantic contracts, versioned JSON Schemas and persisted input dependencies.
- Atomic case/audit persistence in SQLite or explicitly configured PostgreSQL.
- Tenant-aware API access, PostgreSQL RLS and restricted runtime-role checks.
- Exact tenant/subject/source grants, request-time ACL reload and live revocation.
- Idempotent request handling, concurrent replay protection and transaction rollback.
- HTTP input limits before JSON parsing: 64 KiB body, 16 KiB aggregate header
  names/values, and a five-second total body-read deadline.

The baseline makes **zero model calls** and performs **no external business actions**.
API case creation writes only to the configured local case database.

## Quick start: deterministic CLI

Requirements: Python 3.12+ and uv 0.13.4. CI covers Python 3.12 and 3.14;
local verification uses Python 3.14.5. PostgreSQL is optional for this CLI.

```sh
git clone https://github.com/aegisflow-ai-labs/Aegisflow-ai.git
cd Aegisflow-ai
uv sync --frozen --no-editable --reinstall-package aegisflow-ai
mkdir -p work
.venv/bin/python -m aegisflow generate --seed 42 > work/scenario.json
.venv/bin/python -m aegisflow run \
  --scenario work/scenario.json --db work/demo.db \
  --key demo-001 --as-of 2026-11-01T18:00:00Z
```

Expected result: `COMPLETED`, `DELIVERY_DELAY=25200`, `SLA_BREACH=true`, three audit
events and `active_roles=["A21"]`. Repeating the command returns the same persisted
case/events. Reusing its key with changed inputs returns `IDEMPOTENCY_CONFLICT`;
use a new key for a new investigation. Case IDs and capture times vary between new
runs; fixed inputs and an explicit investigation time reproduce business results.

## Local HTTP API

Run only on localhost with synthetic data. Authentication uses server-configured
development Bearer keys; OIDC and production identity management remain planned.

For a fresh checkout:

```sh
.venv/bin/python tools/setup_demo_api.py
export AEGISFLOW_AUTH_FILE=work/api-auth.json
export AEGISFLOW_SOURCE_ACL_FILE=work/source-acl.json
export AEGISFLOW_SCENARIO_FILE=fixtures/supply-delay-v1.json
export AEGISFLOW_DB=work/api.db
.venv/bin/uvicorn aegisflow.api:from_environment \
  --factory --host 127.0.0.1 --port 8000 --no-access-log
```

The setup command creates credential, request-header and ACL files with mode 0600.
It refuses existing files. Keep them outside version control; reuse an existing
setup rather than overwriting keys. The CLI does not require these environment
variables; HTTP configuration is explicit and `.env.example` is not auto-loaded.

In another terminal, run this from the repository directory. The header file keeps
the Bearer value out of the command's arguments:

```sh
curl --fail-with-body http://127.0.0.1:8000/v1/cases \
  --header @work/api-headers \
  --header 'Idempotency-Key: api-demo-001' \
  --data '{"order_id":"PO-001","as_of":"2026-11-01T18:00:00Z"}'
```

The synchronous POST returns HTTP 201 and the case. Authenticated read routes are:

- `GET /v1/cases/{case_id}`
- `GET /v1/cases/{case_id}/events`
- `GET /v1/cases/{case_id}/evidence/{evidence_id}`

Clients cannot supply their tenant or permissions. Errors use stable codes:
401 unauthenticated, 403 operation denied, 404 missing/denied resource,
409 idempotency conflict, 422 invalid schema, and 503 unavailable database/policy.
Input guards return 400 for invalid body length, 408 for the body-read deadline,
413 for an oversized body, and 431 for oversized headers. Limits also apply to
streams without a declared length and reject mismatched lengths.

### Source authorization and revocation

`work/source-acl.json` contains a versioned policy matching authenticated subjects
and exact source URIs. The [policy schema](schemas/SourcePolicy.schema.json) is
checked into the repository. No wildcard or implicit allow-all grant is supported.
To revoke access, remove the relevant URI or grant and replace the policy file
atomically. Subsequent requests reload the file; invalid/unavailable policy fails
closed instead of reusing previous grants.

Full case/event responses require every recorded input dependency. Individual
evidence requires its own source grant. Replay cannot bypass a revoked grant.
Missing/stale source facts are dependencies even without a snapshot. Historical
cases without recorded dependencies cannot return full reports/events/replays;
authorized individual evidence remains readable. Regenerate with a new key rather
than rewriting audit history.

Handled responses use `Cache-Control: no-store`. Revocation does not erase already
downloaded copies, and an in-flight request can finish under its loaded policy.
The synthetic CLI and internal storage APIs are trusted local interfaces and do
not enforce the HTTP policy. See [ADR-005](docs/adr/005-source-evidence-authorization.md).

## PostgreSQL setup and upgrades

PostgreSQL 18 is covered by integration tests. Provision a dedicated development
database and two roles: a schema owner for explicit migrations and a restricted,
non-owner runtime identity. Keep connection strings outside the repository.

Set `AEGISFLOW_DATABASE_URL` to the **owner** connection, then apply schema version 2:

```sh
.venv/bin/python -m aegisflow.postgres
```

Migrations run transactionally and are safe to repeat. Startup verifies the schema
version and never performs DDL. Grant these privileges to your provisioned runtime
role (example role name: `aegisflow_runtime`):

```sql
GRANT USAGE ON SCHEMA public TO aegisflow_runtime;
GRANT SELECT ON aegis_schema_version TO aegisflow_runtime;
GRANT SELECT, INSERT ON aegis_cases, aegis_events TO aegisflow_runtime;
```

Switch `AEGISFLOW_DATABASE_URL` to the **runtime** connection before starting the
API. Retain the auth/source/ACL environment variables above. PostgreSQL failures
never silently fall back to SQLite. The HTTP factory rejects ownership, privileged
role membership, RLS bypass or disabled RLS. Audit mutation is rejected, although
database owners can still change policies and triggers.

For a v1-to-v2 upgrade, stop the old API, back up the development database, migrate
with owner credentials, then deploy the new adapter with runtime credentials. Old
code rejects schema 2. There is no automatic downgrade or zero-downtime guarantee.
See [ADR-003](docs/adr/003-postgresql-persistence.md) and
[ADR-004](docs/adr/004-transaction-scoped-tenant-rls.md).

## Verification

```sh
sh tools/check.sh
mkdir -p work
.venv/bin/pip-audit --skip-editable --format cyclonedx-json --output work/sbom.json
gitleaks dir . --redact --no-banner
```

`tools/check.sh` reinstalls the checkout before lint, format, strict typing and tests.
For the complete suite, set `AEGISFLOW_TEST_DATABASE_URL` to an **administrative
connection on a disposable PostgreSQL instance**. Tests create/drop isolated
databases and temporary roles. Without it, PostgreSQL tests explicitly skip;
a skipped integration test is not a verified database behavior.

CI provisions PostgreSQL 18 for both Python versions, runs dependency auditing,
uploads a CycloneDX SBOM and scans the working tree/history with Gitleaks. The local
Gitleaks command requires the separate tool (8.30.1 was used). Dependency auditing
requires network access. See [verification records](docs/verification.md) for actual
results and each PR for current checks; none are a benchmark or security guarantee.

After contract changes, reinstall and run `.venv/bin/python tools/export_schemas.py`.
Tests verify generated schemas and the seeded fixture's provenance/checksum.

## Expert-role status

The [registry](docs/roles.json) contains **36 registered roles**, **1 implemented
capability subset**, and **1 tested capability subset**. A21 currently supports only
synthetic elapsed-time SLA analysis, not its entire target contract. The golden
case activates **one role: A21**; actual per-case activation is in `active_roles`.
Infrastructure work does not count as completion of additional expert roles.

## Scope, limitations and next steps

SLA uses elapsed UTC seconds, not business calendars. The grace threshold must be
exceeded for a breach. Undelivered orders use `as_of`; future delivery events are
excluded from calculations. Exact duplicates are deduplicated, conflicting events
cause abstention, and stock older than 24 hours or dated in the future is uncertain.
Procedures are reported as evidence; no escalation task is created.

RLS protects trusted application queries with missing tenant predicates. A SQL actor
can set another tenant context, so it does not secure a compromised server/database
credential. HTTP limits bound individual request input; TLS, rate limiting, global
concurrency budgets and production deployment remain separate work.

Next: review and merge the prerequisite security slices, then introduce OIDC and
credential lifecycle controls before bounded agentic routing and baseline comparison.
Real enterprise connectors, UI, root-cause inference, cost/risk alternatives,
exact-payload human approval, external-action idempotency, postcondition verification,
compensation, sealed audit, backup/recovery drills and the 300-case benchmark remain
planned. No production acceptance or measured PDF target is claimed.

## Contributing, security and license

Read [CONTRIBUTING.md](CONTRIBUTING.md) for engineering and English PR/review
conventions, and [SECURITY.md](SECURITY.md) for reporting and supported scope.
Technical decisions live in [docs/adr](docs/adr/); initial Turkish design records
remain available for historical traceability.

Licensed under [Apache-2.0](LICENSE). See [NOTICE](NOTICE) for attribution. Project
code, documentation and generated synthetic fixtures follow this license;
third-party dependencies retain their own terms. The reference PDF is not bundled.

Maintainers: [Miraç Keser](https://github.com/mirackeser) and
[Cansu Kalkan](https://github.com/cansukalkan).
