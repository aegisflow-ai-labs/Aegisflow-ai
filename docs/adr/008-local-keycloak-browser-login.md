# ADR-008: Local Keycloak browser login

- Status: accepted for local synthetic pilot only
- Date: 2026-11-01

## Context

The signed-token verifier does not give maintainers a usable sign-in screen. Docker
is now available and the previous JWT slice is merged. A real identity-provider flow
must preserve tenant/source authorization and the deterministic baseline. The design
PDF is a target reference and does not establish production identity acceptance.

## Decision

Use a digest-pinned Keycloak 26.8.1 local container with one isolated realm and public
client. Enable authorization code with S256 PKCE; disable implicit, password grants,
service accounts and registration. Fix the provider/callback endpoints and redirects
to 127.0.0.1:8080 and :8000. Do not fetch token-selected keys or follow HTTP redirects.
The helper checks trusted discovery metadata and explicitly provisions public keys.

Keep the RFC 9068 API verification profile unchanged by default. The explicit
Keycloak profile requires a signed Bearer access token, exact API audience, issuer,
client azp, bounded lifetime and server principal mapping. Verify ID-token signature,
client audience, subject, nonce, time and optional at_hash before creating a session.

Bind single-use state to an HttpOnly browser cookie and five-minute server record.
Use a fresh PKCE verifier/nonce for every login. Keep access tokens only in a bounded
in-memory session map behind random opaque identifiers. Validate session/JWT and live
principal policy on every request. Do not persist refresh or ID tokens. Cookie writes
require a constant-time CSRF check; reject foreign/null Origin when present. HTML uses
CSP without scripts, frames or remote assets. The callback suppresses referrers;
ordinary pages use same-origin referrers so Chrome supplies same-origin POST Origin.

Reuse the existing case service, idempotency, tenant checks, source policy and audit
persistence for both API and browser. The pilot form selects only synthetic PO-001
at a fixed investigation time. UI work does not implement another expert role.

## Consequences and limits

This remains a single-process local HTTP environment. Cookies cannot be port-isolated
and are not Secure on HTTP; local processes and Docker are trusted. Production needs
TLS/domain isolation, durable/shared sessions, operational budgets, key refresh,
credential lifecycle and provider revocation/logout propagation. Local sessions expire
at the earlier access/ID token expiry and are lost on restart. Logout removes the
application session and renders an explicit link to Keycloak's confirmation screen.
This avoids cross-origin form redirects being blocked by the restrictive CSP. Abandoning
confirmation leaves provider SSO active. Other devices' sessions are unaffected.

Private generated files are ignored and mode 0600; the import volume has nonroot-read
permissions. No default password/admin is configured. Preserve existing accounts and
operator revocations on restart. No automatic reset or production connector is added.

## Validation

Unit/integration checks cover token confusion, nonce/issuer/audience/time errors,
state binding/replay/expiry/capacity, CSRF, live access revocation and generic failures.
A real browser/Keycloak check covers sign-in, deterministic investigation, cookie
flags, logout, keyboard entry and desktop/mobile overflow. These checks are not a
complete accessibility audit or production security acceptance.

References: [Keycloak Docker guide](https://www.keycloak.org/getting-started/getting-started-docker),
[realm import](https://www.keycloak.org/server/importExport),
[OAuth security best current practice](https://www.rfc-editor.org/rfc/rfc9700.html).
