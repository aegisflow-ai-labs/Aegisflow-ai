# ADR-009: Bounded local key refresh and persisted token cutoff

- Status: accepted for the local synthetic pilot
- Date: 2026-11-01
- Extends ADR-007 and ADR-008; production identity acceptance remains open.

## Context and scope

The local browser pilot initially snapshots Keycloak keys only on startup. Principal
removal already denies access but also prevents later login. Close these two specific
lifecycle gaps before bounded task routing. Keep the deterministic case/evidence/audit
service, expert-role status and model-call count unchanged. Avoid introducing a remote
admin API, distributed sessions or a Keycloak bootstrap administrator for this slice.

## Decision

Allow the verifier exactly one trusted source: its existing public-key file or an
explicit application-configured supplier. The local helper selects a fixed-endpoint
Keycloak supplier with a monotonic 60-second cache. Refresh only when an authentication
request needs an expired set. Unknown token kids do not trigger refresh. Serialize
refreshes across threads and back off five seconds after a failed attempt. On expiry
and failure, return generic 503 without stale/disk fallback. Existing fresh cached
keys can work until expiry. New/removed keys may take up to 60 seconds to be observed;
new unknown keys produce 401 during that window. This availability tradeoff limits
unauthenticated fetch amplification and stale trust without adding a background worker.

Reuse the bounded public JWK contracts and RSA checks. Accept Keycloak public
certificate metadata but never private fields, untrusted URLs, redirects, unknown
fields on selected signing keys, weak keys or duplicate kids. The fixed provider
transport retains its five-second timeout and 64 KiB response cap. File-based JWT
mode and its request-time file reload remain unchanged.

Add optional nonnegative integer `tokens_valid_after` to each PrincipalBinding.
Zero means no cutoff; otherwise reject signed access tokens whose iat is at or before
that UTC second. Permissions still come from server mappings. Retain request-time
policy reload independently of key caching. A rejected browser session is deleted;
removing the cutoff later cannot resurrect that opaque session identifier.

Provide only a trusted local operator CLI for the configured test user. Atomically
replace a validated, bounded, mode-0600 policy under an advisory process lock; retain
grants, other principals, JTI revocations and the maximum existing/current cutoff.
Change policy revision on each operation. Failed validation/write must not report
success or replace good policy. Lock coordination applies only to this tool. This is
configuration-based local revocation, not a complete administrator audit trail.

## Acceptance and compatibility

- Old policy files remain readable with default zero; generated schema is checked.
- Cutoff equality is denied; tokens issued in a later second can sign in.
- Malformed/expired provider keys fail closed, successful refresh recovers, and concurrent
  requests share fetches. Unknown kids cannot amplify requests within the cache TTL.
- Browser/API source and tenant checks remain active; an old cookie cannot be reused
  after revoke/re-login. Cutoff is stored independently of memory-only sessions.
- Full PostgreSQL suite, real Keycloak/Chrome flow and security scans must pass.

The policy extension does not require a database migration. Older closed parsers
reject the new field; do not erase revocation cutoffs to make an old deployment start.
A rollback requires explicit policy compatibility planning. No full Keycloak rotation
via its administration console is claimed: rotation/removal/failure boundaries are
simulated in tests; the browser test exercises the real configured JWKS endpoint and
actual local session revocation/re-login.

## Limits and next slice

Local HTTP/process/Docker trust boundaries remain as ADR-008. There is no instant
provider-side revocation, back-channel logout, refresh-token use, multi-process cache,
production TLS/domain isolation or remote administration. Production identity is a
separate deployment acceptance gate. Next, define bounded task routing and deterministic
permission/tool/cost limits against the existing baseline before adding model calls.

References: [Keycloak certificate endpoint](https://github.com/keycloak/keycloak/blob/main/docs/guides/securing-apps/partials/oidc/available-endpoints.adoc),
[PyJWT key client/cache API](https://pyjwt.readthedocs.io/en/stable/api.html).
