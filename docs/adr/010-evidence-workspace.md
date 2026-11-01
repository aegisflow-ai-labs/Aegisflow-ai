# ADR-010: Evidence workspace

Status: accepted for the local pilot

## Context

The initial browser page verified identity and investigation behavior but did not
provide a coherent operational workspace. Product usability is the next slice;
this does not expand specialist implementation or authorize external actions.

## Decision

Keep the server-rendered FastAPI application and existing authentication boundary.
Use a dark navy workspace, teal accent, system typography, consistent navigation,
and a dotted evidence map. Reference imagery informs visual hierarchy only;
AegisFlow has its own branding and displays no invented integrations or activity.

Before execution, show the available synthetic workflow. After execution, derive
evidence, finding, activated-role and model-call counts from the persisted case.
Native disclosure controls expose escaped source snapshots, versions and checksums.
Retain the complete source-linked report. Registered/implemented/tested capability
status is explicitly separate from per-case activation.

Use responsive layouts and visible keyboard focus. No external fonts, scripts,
analytics or new dependencies are needed; the restrictive CSP remains unchanged.

## Validation and limits

Browser checks cover real Keycloak login, investigation, source disclosure,
desktop/mobile/landscape overflow, revocation and logout. A regression test checks
untrusted source rendering and case-derived counts. This is a local synthetic
workspace, not a production operations console. Multi-case navigation, graph
pan/zoom, additional specialists and external integrations remain future work.
