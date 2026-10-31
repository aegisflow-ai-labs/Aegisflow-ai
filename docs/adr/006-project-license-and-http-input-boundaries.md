# ADR-006 — Apache-2.0 adoption and bounded HTTP input

Status: prepared for maintainer review, 2026-11-01.

## License and documentation

The project owner authorized selecting a license. Adopt Apache-2.0 for project-owned
code, documentation and generated synthetic fixtures, with the unchanged official
LICENSE text and project NOTICE. Update packaging and fixture metadata consistently.
The reference PDF is not redistributed. Dependencies keep their own licenses; this
change does not claim a comprehensive third-party license audit. Existing contributors
must confirm licensing authority in the adoption review; no copyright assignment or
Apache Software Foundation affiliation is implied. The selection is motivated by
Apache-2.0's explicit patent/contribution provisions, not a claim that MIT is less
professional. References: [license](https://www.apache.org/licenses/LICENSE-2.0.txt)
and [application FAQ](https://apache.org/foundation/license-faq.html).

Replace the accumulated multilingual README with one English entry point. Keep
historical Turkish design/ADR material for traceability. PR/review language remains
English. Follow-up reports must identify actual checks and user approvals/actions.

## Input-boundary finding and fix

The HTTP pilot had no application-level bound before JSON parsing, so a large or
slow request could consume resources outside the scenario-file size check. Add a
pure ASGI guard: 65,536 body bytes, 16,384 aggregate header-name/value bytes, and a
five-second total body-read deadline. Bound the actual stream even without a length
or with a false length. Reject invalid/duplicate/mismatched Content-Length values.
Compare normalized length strings before integer conversion; zero padding must not
trigger Python's integer digit limit. Buffer at most one bounded body and forward it
once. Disconnect stops work; lifespan and other protocols pass through. Error
responses contain only stable codes and no-store headers. This is not global rate
limiting, TLS, request-line/header-read timeout control or production DoS protection.

Generate a local 0600 curl-header file to avoid putting the development Bearer key in
process arguments. Refuse existing demo files before writing any new configuration;
this prevents a failed repeat setup from leaving mixed/partial credentials.

## Repository settings

Using the mirackeser account, enable GitHub secret scanning, push protection, private
vulnerability reporting and dependency vulnerability alerts, then read them back.
No automatic merge or second-account approval is enabled. Required-review main
protection remains intact. These repository settings are already active independently
of merging the code PR. Scanner availability and alert states are not proof that all
vulnerabilities have been found. SECURITY.md documents the reporting path and limits.

## Scope

This slice depends on the source authorization work; it does not start OIDC or
agentic routing. Existing synthetic-only limitations, role counts and external-action
restrictions remain unchanged. Tests cover boundary sizes, streamed/false lengths,
invalid lengths, a body-read deadline, disconnect, lifecycle passthrough, actual API
rejection before persistence, and non-overwriting credential setup. Validate clean
installation and verify LICENSE/NOTICE and License-Expression in the built wheel.
