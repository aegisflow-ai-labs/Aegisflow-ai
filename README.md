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
- Five-order browser pilot with tenant/source-filtered selection and evidence-gated operational recommendations.
- Evidence-linked claims with source versions, immutable snapshots and SHA-256 checksums.
- Explicit uncertainty for missing, stale or conflicting evidence.
- Closed Pydantic contracts, versioned JSON Schemas and persisted input dependencies.
- Atomic case/audit persistence in SQLite or explicitly configured PostgreSQL.
- Tenant-aware API access, PostgreSQL RLS and restricted runtime-role checks.
- Optional signed access-token verification with issuer/audience/time checks and local revocation.
- Local Keycloak browser login using Authorization Code + S256 PKCE, opaque sessions and CSRF checks.
- Exact tenant/subject/source grants, request-time ACL reload and live revocation.
- Idempotent request handling, concurrent replay protection and transaction rollback.
- Exact-content action proposal/approval and one atomic synthetic execution receipt, recorded in the immutable audit log.
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

Run only on localhost with synthetic data. The default demo uses server-configured
development Bearer keys; optional signed-token verification is described below.
A separate local Keycloak browser pilot is available below; production identity management remains planned.

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

Next: bounded task routing with deterministic permissions/tool budgets and baseline
comparison. Production identity acceptance remains a separate deployment gate.
Real enterprise connectors, a full operational UI, root-cause inference, cost/risk alternatives,
production approval lifecycle, external-action idempotency and external postcondition verification,
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

## Try signed access-token verification

For a disposable demo without Docker, an identity account or a password:

```sh
uv sync --frozen --no-editable --reinstall-package aegisflow-ai
.venv/bin/python tools/jwt_demo.py
```

The command starts a localhost API and prints a ready-to-copy `curl` command for a
second terminal. It uses a fresh private directory under `work/`, a ten-minute signed
access token, and an in-memory signing key that is never saved. Stop with Ctrl+C;
run again for a new demo after expiry. Use `--port 8001` if port 8000 is occupied.
No browser login screen or real identity provider is involved in this demonstration.

For explicit server configuration, set `AEGISFLOW_AUTH_MODE=jwt` and configure:

- `AEGISFLOW_JWT_ISSUER`: exact trusted issuer.
- `AEGISFLOW_JWT_AUDIENCE`: this API's expected audience.
- `AEGISFLOW_JWKS_FILE`: trusted public keys matching [PublicKeys.schema.json](schemas/PublicKeys.schema.json).
- `AEGISFLOW_PRINCIPALS_FILE`: server subject-to-scope mappings and revoked token IDs
  matching [IdentityPolicy.schema.json](schemas/IdentityPolicy.schema.json).

Retain the existing source ACL, scenario and database configuration. JWT mode does
not read or fall back to the development AUTH_FILE. Default `development` mode is
retained for the earlier demo. Configure modes explicitly when deploying a server.

Only RS256 signed `at+jwt` access tokens with required claims and a maximum
15-minute lifetime are accepted. Keys/subject mappings are reread on subsequent
requests. A signed tenant/admin claim cannot override server permissions. Revocation
is local-file based. This default RFC 9068 profile is separate from the explicit
Keycloak profile used below. Production OIDC lifecycle and refresh remain planned. See [ADR-007](docs/adr/007-signed-access-verification.md).


## Try browser login with local Keycloak

The local Docker helper currently supports macOS/Linux. Requirements: Docker running,
Python/uv as above, and free localhost ports 8000/8080.
Stop the earlier JWT/API demo first. From the repository directory:

```sh
uv sync --frozen --no-editable --reinstall-package aegisflow-ai
.venv/bin/python tools/keycloak_demo.py
```

Open **http://127.0.0.1:8000/** and choose **Sign in with Keycloak**. Username:
`analyst`. Open `work/keycloak-local/login.txt` locally for the randomly generated
password (on macOS: `open work/keycloak-local/login.txt`). Enter it on Keycloak's
localhost page, then choose **Investigate demo case**. The result shows 25,200 seconds
of delay, an SLA breach and five source snapshots. **Sign out** ends the application
session immediately; choose **Finish signing out of Keycloak**, then confirm there
to end its SSO session as well.

The helper starts a digest-pinned Keycloak 26.8.1 container and provisions an isolated
realm/client/test user without a default password or bootstrap administrator. Private
files under ignored `work/keycloak-local/` use mode 0600. Do not share these files,
commit them or upload the directory as a CI artifact. The import volume also holds
local test credentials; treat Docker access as trusted. Existing policy files and
container state are preserved on restart. Incomplete or conflicting setups fail
rather than silently resetting accounts. An intentional account reset is a separate
operator action; there is no automatic destructive reset.

Ctrl+C in the helper terminal stops the API and its Keycloak container. If interrupted
before cleanup, `.venv/bin/python tools/keycloak_demo.py stop` stops only the owned
provider container; stop the foreground API separately. Demo cases remain in the local
SQLite file. No enterprise system is modified.

This is a **single-process, local HTTP pilot**, not a production deployment. All local
processes are trusted: cookies are host-scoped rather than port-scoped and intentionally
lack `Secure` on HTTP. Sessions are bounded, held only in server memory and expire
with the signed tokens (at most ten minutes here). Restarting the API clears sessions.
Access/ID tokens never enter page HTML or browser storage. Refresh tokens are not used
or persisted. Subject/JTI and source grants are rechecked on requests; provider-side
logout/revocation from another device is not instantly propagated. Back-channel logout, shared session storage, TLS/domain isolation, production
rate limits and credential recovery are not implemented. See [ADR-008](docs/adr/008-local-keycloak-browser-login.md).

With the helper running, reproduce the browser check:

```sh
.venv/bin/playwright install chromium
.venv/bin/python tools/check_keycloak.py
```

For an installed Google Chrome instead of downloading Chromium, set
`AEGISFLOW_BROWSER_CHANNEL=chrome`. Screenshots stay under ignored `work/browser-check/`.
CI runs this same flow against a real Keycloak container in a separate browser job,
including revocation of an active session, re-login and rejection of its old cookie.


### Local session revocation and signing-key changes

The Keycloak helper refreshes public verification keys on demand after at most 60
seconds of cached freshness. Only the fixed local provider's certificate endpoint is
used. Unknown token key IDs return 401 without triggering extra fetches. After a key
is removed, tokens using it stop working when the cached set expires. If refresh
fails, authentication returns 503 rather than using expired cached keys; retries are
limited to one attempt per five seconds per process. Fresh cached keys remain usable
until their expiry, so provider changes/outages are not detected instantly. There is
no on-disk fallback in this mode. The separate file-configured JWT demo stays unchanged.

To invalidate the local demo user's existing AegisFlow access tokens and browser
sessions without deleting the account, run from the repository in another terminal:

```sh
.venv/bin/python tools/keycloak_demo.py revoke-sessions
```

The command atomically persists a per-principal `tokens_valid_after` UTC second in
`work/keycloak-local/principals.json`, preserves grants/passwords and never lowers an
existing cutoff. Tokens issued **at or before** that second are rejected on subsequent
requests. Wait until the next second and sign in again; Keycloak SSO may make this
immediate without asking for a password. Already downloaded results and in-flight
requests are not recalled. Restarting the API retains the cutoff. This command does
not end Keycloak SSO or other applications' sessions, and is a trusted local operator
tool rather than a remotely accessible administration API or a complete security
audit trail. Do not run it during somebody else's demo without coordination.

Existing policy files without the new field remain valid (default zero: no cutoff).
Older strict parsers reject the new field; rollback must preserve revocation semantics,
not silently erase it. No database migration is required. See [ADR-009](docs/adr/009-local-identity-lifecycle.md).

## Operational triage pilot

The Keycloak demo now loads five synthetic purchase orders. Select one before
clicking **Investigate demo case**:

- PO-001: 7-hour delay → procurement escalation recommendation.
- PO-002: on time → monitor.
- PO-003: missing SLA → collect evidence.
- PO-004: conflicting deliveries → collect evidence.
- PO-005: no delivery recorded, 9 hours overdue → escalation recommendation.

The scenario clock is fixed at **2026-11-01 18:00 UTC**. The case workbench presents delay in hours, SLA status, source-linked findings,
a timeline and expandable evidence snapshots. The result explains the
next step and exposes its evidence references and policy version. No supplier is
contacted. Existing case IDs, source snapshots and audit events remain available.
Authorized API clients can read the order catalog at `GET /v1/orders` and the
recommendation at `GET /v1/cases/{case_id}/triage`.
See [ADR-011](docs/adr/011-operational-triage.md) for policy and scope.

## Workspace navigation

After local sign-in, the command center shows persisted case activity. Use
**Investigations** to create a case, filter the history and reopen previous
results. **Agent map**, **Evidence library**, **Audit trail** and **Access &
session** have separate routes with a visible active navigation state.

Case creation redirects to a stable case URL. Refreshing that URL reads the
stored result; it does not create another investigation. The API case index is
`GET /v1/cases?offset=0`. Each page scans at most 100 tenant cases and filters
them by current source access; dashboard counts and evidence/audit indexes cover
that page. See [ADR-013](docs/adr/013-persisted-workspace-navigation.md).

## Controlled synthetic actions

An SLA-breach case can now progress through **Action center**:

1. **Prepare action proposal** constructs a fixed synthetic procurement-review payload.
2. **Approve this exact action** records the human identity, time and payload SHA-256.
3. **Execute synthetic action** atomically records one synthetic queue receipt.

The local operator must explicitly enable demo approval/execution permissions:

```sh
.venv/bin/python tools/keycloak_demo.py enable-synthetic-actions
```

This updates only the configured local demo principal and preserves other grants
and revocations. Existing users are not automatically granted approval rights.
The browser smoke test opts in explicitly for its synthetic test account.

API: `GET /v1/cases/{case_id}/action` reads the current state.
`POST /v1/cases/{case_id}/action/propose` accepts `{}`.
The `approve` and `execute` routes accept
`{"content_digest":"<exact SHA-256 from the proposal>"}`.
Cookie-authenticated writes also require the existing CSRF header.

Missing/conflicting evidence, unauthorized approvals, mismatched content and
execution before approval are rejected. Concurrent/repeated execution returns
the same receipt without a second execution event. Execution is a local
simulation represented by its committed audit record; no supplier, email service
or enterprise system is contacted. A local operator may hold all demo permissions;
production separation of duties, approval expiry, cancellation and external
connector recovery remain future work. See [ADR-014](docs/adr/014-controlled-synthetic-actions.md).
