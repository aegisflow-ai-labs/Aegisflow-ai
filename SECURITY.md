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
to attacks. Runtime keys remain development credentials; OIDC, TLS termination,
rate/concurrency controls, external source ACLs, key lifecycle and sealed audit storage
are planned. SQL credentials/server code are trusted; arbitrary SQL can change tenant
context, and DB owners can change policies. File ACL revocation affects subsequent
requests, not responses already downloaded or work already in flight.

Never place credentials in issues, source, fixtures or logs. Demo credential files
are local, mode 0600, and ignored under work/. Rotate any exposed credential even
if a scanner reports no findings. Scan results cover known signatures/advisories
and the tested snapshot; newly enabled repository scans may still be processing.
