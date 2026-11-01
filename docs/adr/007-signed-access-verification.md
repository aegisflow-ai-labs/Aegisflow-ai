# ADR-007 — Signed access-token verification before provider integration

Status: accepted for the synthetic pilot, 2026-11-01.

## Decision and boundaries

Add an explicitly selected JWT authentication mode; retain development keys for the
local synthetic baseline. Modes cannot be mixed. An unknown mode or missing JWT
configuration fails startup; verification failure never falls back to a development
key. This is an API resource-server verifier, not an OIDC browser login, authorization
server, PKCE/callback flow, session system, refresh-token service or completed A02 role.

Use PyJWT with the cryptography backend rather than implementing signatures. The
allowed algorithm is fixed to RS256, with 2048–8192-bit public RSA keys selected by
kid from a bounded, trusted local JWKS file. Private key fields and unsupported key
metadata are rejected. Token headers cannot supply URLs/keys; jku/jwk/x5u/x5c/crit
are rejected and no network request is made. Header typ must be at+jwt or
application/at+jwt, excluding ordinary ID-token JWT headers.

Issuer and audience are explicit server configuration. Signed iss/aud/sub/exp/iat/
nbf/jti/client_id claims are required. Numeric dates must be integers (not booleans
or strings); expiry is exclusive, future iat/nbf is denied, and token lifetime is
at most 900 seconds, with zero clock leeway. Signature, issuer, audience and string
claim validation run through PyJWT. An injected aware clock applies all temporal
checks deterministically; library temporal checks are disabled only to avoid a
second, non-injectable clock. These checks are covered by negative tests.

This deliberately narrow profile is inspired by
[RFC 9068](https://www.rfc-editor.org/rfc/rfc9068.html). It requires nbf and imposes
additional local limits; do not claim full provider interoperability or RFC-wide
conformance. Provider headers/claims must be reconciled explicitly during integration.
Algorithm selection follows [PyJWT's guidance](https://pyjwt.readthedocs.io/en/stable/api.html).

## Authorization and lifecycle

The fixed issuer's external subject maps to a trusted Scope in a server-owned
IdentityPolicy file. Incoming tenant, roles, scope and permissions do not assign
application privileges. Existing operation checks, tenant RLS and source policy
remain independently required. Read keys and identity policy on every request:
removing a subject, revoking a jti or removing a key takes effect on subsequent
requests. Unsupported/invalid credentials return generic 401; unavailable/malformed
trusted configuration returns generic 503 without stale-cache fallback or token echo.

Files are read at most 64 KiB, with at most 16 public keys. Update files atomically.
Key and policy files are separate snapshots: coordinated updates can temporarily
fail closed; there is no cross-file transaction or in-flight revocation guarantee.
No network key discovery/rotation, automatic revocation retention cleanup, issuer
logout notification or distributed policy administration is implemented. Maintain
revocation entries at least until relevant token expiry. Do not use this as a
production identity service without the provider and lifecycle work.

## Usable local demo

`tools/jwt_demo.py` starts a disposable localhost API without Docker or accounts.
It creates a fresh private directory, generates a signing key in memory, saves only
public verification material and a short-lived request header, and discards the
signing key. Files use 0600; the directory uses 0700. The demo token lasts ten minutes;
restart for a fresh demo. This is a verifier demonstration, not a real login screen.

The current workstation's Docker client cannot reach a running Docker daemon.
A local Keycloak login is a candidate next slice after Docker Desktop is started;
no container, realm, user account or live Keycloak integration is claimed here.
The user has no existing identity provider; deployment credentials were not assumed.
