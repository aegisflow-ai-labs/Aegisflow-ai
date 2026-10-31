# Contributing

Use English for pull request titles, descriptions, review comments, approval summaries,
and commit messages. Conversations may use the collaborators' preferred language.
New technical documentation should use English; retain existing Turkish source
references and historical records without rewriting their meaning.

Keep changes small and reviewable. Inspect repository instructions and existing changes
before editing. Describe implemented behavior separately from planned capabilities.
Include the problem, resulting behavior, actual validation, limitations, and follow-up
scope in each pull request. Do not describe unrun checks as passing. Do not claim PDF
targets as measured results. Role registration, implementation, testing, and per-case
activation are distinct states.

Run `sh tools/check.sh`. For persistence changes, also set
`AEGISFLOW_TEST_DATABASE_URL` to a disposable PostgreSQL instance and run the suite;
these tests create and drop isolated databases and require an administrative test role.
CI runs these tests against PostgreSQL 18. Never use production data or credentials.
Run dependency and secret scans when introducing dependencies or configuration.

Do not merge a pull request just because CI passes. Human review and project acceptance
remain separate from automated checks. External business actions must remain disabled
until exact-payload approval, idempotency, and postcondition verification are implemented.

## Licensing and release review

Project-owned contributions are submitted under Apache-2.0; retain applicable third-party
notices and verify that you have the rights to contribute. Do not relicense third-party
code or data by adding a project header. Before merging the initial license adoption,
maintainers must confirm licensing authority for existing contributions. Dependencies
keep their own licenses. LICENSE and NOTICE must be present in distributed packages.

At the end of each engineering slice, report actual checks, remaining limitations,
PR dependencies, the review/approval needed and any user action. A chat instruction is
not itself a GitHub approving review. Do not submit an approval as a second maintainer
or change accounts for review without that person's explicit instruction and review
intent. CI passing, chat authorization and independent code review are distinct.
