# ADR-005 — Source authorization and live revocation at the HTTP boundary

Status: accepted for the synthetic pilot, 2026-11-01. Depends on ADR-004.

## Decision

Require an explicit server-owned SourcePolicy, versioned by schema_version and
revision, with grants keyed by exact tenant, subject and source URI. No wildcard,
prefix, cross-tenant or implicit allow-all grant exists. Source identities currently
refer to the five synthetic input components (order, deliveries, SLA, inventory,
procedure), not individual business rows. Policy never comes from request bodies,
scenario content, a model output or persisted case ownership.

The environment factory requires AEGISFLOW_SOURCE_ACL_FILE. It validates policy at
startup and loads one immutable policy snapshot for every authenticated HTTP
request. Update the file atomically on the same filesystem. Missing, malformed or
oversized (>1 MB) policies fail closed with a generic 503; no stale grant cache or
allow-all fallback is used. Unknown/denied resources both return generic 404. Broad
operation permission and tenant checks remain independent. A fixed SourcePolicy
object is supported for embedded/tests; it is intentionally immutable/static.

## Response coverage

POST checks all input sources before executing, including idempotent retries, and
checks persisted input dependencies before returning the report. New Case records
include additive input_source_uris. This includes missing/stale source inputs:
absence and freshness findings are derived information even when no evidence
snapshot was produced. Schema v1 JSON gains an optional field for storage backward
readability; new generation always populates it. Evidence references must be included
in a nonempty dependency list.

A full case read requires every input dependency. Events also require the full list
because their payload references can reveal the investigation. A single evidence
read requires only that evidence's exact source grant, after normal case/tenant/read
checks. No partial report is assembled: filtering snapshots without filtering
claims, status and uncertainty would leak derived information.

Historical cases without recorded input dependencies fail closed on full case,
event and replay responses; no guess or silent backfill is performed. Authorized
individual evidence remains readable. Re-run using a new request key to obtain a
new report with explicit dependencies. Existing database rows and audit history
are not rewritten and no database migration is required for this additive field.

Successful and handled-error HTTP responses carry Cache-Control: no-store and Pragma: no-cache. This advises
clients/proxies not to reuse sensitive responses; already downloaded copies cannot
be clawed back. Revocation takes effect when a subsequent request loads the new
file; an already in-flight request may finish using its earlier policy snapshot.
This is not an atomic revocation barrier across running requests.

## Boundaries and rollout

This is service-layer authorization, separate from PostgreSQL tenant RLS. Trusted
storage/domain callers and the local synthetic CLI are internal and do not read the
HTTP ACL file. A compromised server/SQL credential remains outside this guarantee.
Credential revocation, OIDC, per-row ACLs, external source authorization/revocation,
central policy distribution, administrative policy-change audit and production
acceptance remain planned. No HTTP policy-edit endpoint is introduced. Role counts
remain unchanged; the PDF's full security roles are not claimed complete.

Before upgrading, provision a valid ACL file and set its required environment path.
Existing token/auth files are not overwritten by the demo generator; provision the
ACL separately for an existing installation. Policies are server configuration:
restrict filesystem access and replace atomically. API contract version becomes
0.3.0. Missing configuration prevents startup. See README for the explicit grant
example and commands.

Validation covers runtime revoke/regrant, retry and new-key denial without extra
DB effects, same-tenant subject separation, tenant separation, missing grants,
malformed/missing/oversized policy, historical records, missing input dependencies,
no-store responses, source-policy schema, clean credential generation and PostgreSQL
RLS-backed requests. These scoped tests are not a production security certification.
