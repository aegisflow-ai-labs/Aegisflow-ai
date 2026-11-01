# ADR-013: Persisted, multi-page operational workspace

Status: implemented for review

## Problem

An agent map plus an anchored form did not provide case management. Navigation
did not identify the current section and completed cases could not be reopened
from a browser history view.

## Decision

Provide distinct routes:
- /: dashboard derived from the latest authorized stored-case page.
- /cases: creation form, order/case search, status filtering and paged case history.
- /cases/{id}: persisted case recommendation, evidence, chronology and report.
- /agents: capability map and local search/filter controls.
- /evidence: case-linked source snapshot index.
- /activity: actual persisted case audit events.
- /access: current identity and sign-out.

Every shell has one aria-current page link, a matching breadcrumb and document
title. Mobile navigation remains available. Investigation POST redirects to the
persisted case URL; reopening uses the existing read and source authorization.

Both stores expose stable newest-first case paging, bounded to 100 rows per
page. GET /v1/cases uses tenant read permission and filters each row against the
current source grants. PostgreSQL executes this in its existing tenant
transaction/RLS boundary. No schema migration is required.

## Scope and limitations

Pagination applies before source filtering; a page can contain fewer than 100
visible cases or be empty. Counts, evidence and audit indexes explicitly describe
the latest authorized case page, not global totals. Search/status filter the
selected page. No full-text index or global analytics is claimed. The underlying
orders remain synthetic; additional specialists and external action execution
are outside this slice.

## Validation

SQLite/PostgreSQL tests cover paging, persistence, tenant isolation and denied
read permission. API/browser tests cover revocation, navigation state, case
reopening, evidence/audit views and responsive layouts.
