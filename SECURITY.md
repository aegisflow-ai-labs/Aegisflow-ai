# Security policy

## Supported scope

AegisFlow AI is a synthetic, local-development prototype. There is no supported
production release or published security SLA. Fixes target the current main branch;
unmerged PRs must be evaluated against their own code and checks. Use only synthetic
data and bind the development HTTP server to localhost.

## Report a vulnerability privately

Use GitHub's [private vulnerability reporting form](https://github.com/aegisflow-ai-labs/Aegisflow-ai/security/advisories/new).
Include the affected commit, prerequisites, minimal synthetic reproduction, expected
versus actual behavior and impact. Do not submit secrets, real enterprise records,
or exploit another party's systems. If private reporting is unavailable, open a
minimal issue requesting a private contact without publishing sensitive details.

## Current controls

- Explicit server authentication, operation/tenant checks and source ACLs.
- Transaction-scoped PostgreSQL tenant RLS and restricted HTTP runtime-role checks.
- Evidence-linked claims, guarded replay, append-only audit controls and rollback.
- Bounded request body/header input and total body-read deadline before JSON parsing.
- Locked dependencies, CI security scans, secret scanning and push protection.
- Protected main with required reviews and checks, including administrators.

Controls are defense in depth. They do not establish production isolation or immunity
to attacks. Runtime keys remain development credentials; production OIDC, TLS termination,
rate/concurrency controls, external source ACLs, key lifecycle and sealed audit storage
are planned. SQL credentials/server code are trusted; arbitrary SQL can change tenant
context, and DB owners can change policies. File ACL revocation affects subsequent
requests, not responses already downloaded or work already in flight.

Never place credentials in issues, source, fixtures or logs. Demo credential files
are local, mode 0600, and ignored under work/. Rotate any exposed credential even
if a scanner reports no findings. Scan results cover known signatures/advisories
and the tested snapshot; newly enabled repository scans may still be processing.

## Signed access-token mode

Optional JWT mode verifies signatures, issuer/audience, type, required claims and
integer time bounds using a trusted local public-key file. It does not accept
header-supplied keys/URLs or downgrade to development credentials. Server mappings,
not token role/tenant claims, determine permissions. Public key and principal/JTI
revocation updates apply to subsequent requests. See ADR-007 for the narrow supported
profile and remaining OIDC/provider lifecycle work. The disposable demo signs only
local synthetic requests and is not an authorization server or browser login.


## Local browser pilot

The optional Keycloak pilot uses a separate explicit token profile, authorization
code/S256 PKCE, one-use browser-bound state/nonce, opaque HttpOnly SameSite cookies,
CSRF validation and request-time principal/source policy reload. Session/token state
is bounded and kept in server memory; access/ID tokens are not placed in page HTML
or browser storage. Requests to unavailable policy/key/provider dependencies fail
closed. The fixed provider endpoints accept no token-controlled URLs or redirects.

This pilot binds only to loopback and intentionally uses HTTP cookies without Secure.
Cookies are shared across ports on the same host: all local processes and Docker are
trusted. Do not expose it to a network or use real credentials. Logout revokes only
the current application session immediately; follow the displayed provider link and
confirm to end Keycloak SSO. Other sessions/provider changes are not instantly
revoked. Production TLS, host isolation, shared session storage, production key lifecycle,
back-channel logout, recovery and operational limits remain open (ADR-008).

Generated password/import files belong only under private ignored work/ storage.
Do not upload work/ in CI artifacts. A directory-wide secret scan will correctly
flag these local credentials; scan the version-controlled source snapshot/history
separately and never suppress actual source findings to hide demo files.


## Local identity lifecycle

The Keycloak helper uses a fixed-endpoint, per-process public-key cache with at most
60 seconds of freshness and a five-second failed-fetch cooldown. Unknown kids never
force refresh; key removals take effect at the next expired-cache request. Expired
keys are not reused on failure. Fresh keys can continue working until TTL expiry;
this is not instant provider-side revocation. No token chooses a URL, key source or
refresh schedule. The file-based JWT mode still reloads its trusted file per request.

A persisted per-principal issued-at cutoff revokes local tokens and sessions on
subsequent requests while preserving the account and grants. The local operator
command uses an advisory process lock plus atomic private-file replacement and does
not lower prior cutoffs. Its lock does not coordinate arbitrary external file editors.
Only trusted operators may change policies. This is not Keycloak SSO termination,
back-channel logout, a remote administrative API or a complete operator audit trail.
Preserve cutoffs across upgrades/rollbacks; see ADR-009 for compatibility and limits.
