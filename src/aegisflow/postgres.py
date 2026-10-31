"""PostgreSQL adapter and explicit, transactionally versioned initial migration."""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import psycopg

from .contracts import AuditEvent, Case, Request, Scenario, Scope
from .engine import digest, investigate
from .store import IdempotencyConflict, NotFound, Store

MIGRATION = """
CREATE TABLE aegis_cases (
    case_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (tenant_id, case_id), UNIQUE (tenant_id, request_key)
);
CREATE TABLE aegis_events (
    event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0), body TEXT NOT NULL,
    FOREIGN KEY (tenant_id, case_id) REFERENCES aegis_cases (tenant_id, case_id),
    UNIQUE (tenant_id, case_id, revision)
);
CREATE FUNCTION aegis_reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit append only'; END;
$$;
CREATE TRIGGER aegis_audit_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON aegis_events
FOR EACH STATEMENT EXECUTE FUNCTION aegis_reject_audit_mutation();
INSERT INTO aegis_schema_version VALUES (1);
"""


def connect(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(
        dsn, connect_timeout=5, options="-c statement_timeout=5000 -c lock_timeout=5000"
    )


def migrate(dsn: str) -> None:
    """Run with a schema owner, separately from the runtime role."""
    with connect(dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(62468101)")
        db.execute("CREATE TABLE IF NOT EXISTS aegis_schema_version (version INTEGER PRIMARY KEY)")
        rows = db.execute("SELECT version FROM aegis_schema_version").fetchall()
        if rows == [(1,)]:
            return
        if rows:
            raise ValueError("Unsupported schema version")
        db.execute(MIGRATION)


class PostgresStore:
    def __init__(self, dsn: str, clock: Callable[[], datetime] | None = None) -> None:
        self.dsn = dsn
        self.clock = clock or (lambda: datetime.now(UTC))
        with connect(dsn) as db:
            if db.execute("SELECT version FROM aegis_schema_version").fetchall() != [(1,)]:
                raise ValueError("Unsupported schema version; run migration explicitly")

    def run(self, scope: Scope, request: Request, scenario: Scenario) -> Case:
        Store.authorize(scope, request.tenant_id, "investigate")
        if (
            scenario.order.tenant_id != scope.tenant_id
            or scenario.order.order_id != request.order_id
        ):
            raise NotFound("NOT_FOUND")
        payload = request.model_dump(mode="json")
        payload["as_of"] = request.as_of.astimezone(UTC).isoformat()
        fingerprint = digest(
            {
                "request": payload,
                "source": scenario.model_dump(mode="json"),
                "subject_id": scope.subject_id,
            }
        )
        lock_hash = digest([scope.tenant_id, request.idempotency_key])
        lock_id = int.from_bytes(bytes.fromhex(lock_hash[:16]), signed=True)
        with connect(self.dsn) as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))
            existing = db.execute(
                "SELECT fingerprint, body FROM aegis_cases WHERE tenant_id=%s AND request_key=%s",
                (scope.tenant_id, request.idempotency_key),
            ).fetchone()
            if existing:
                if existing[0] != fingerprint:
                    raise IdempotencyConflict("IDEMPOTENCY_CONFLICT")
                return Case.model_validate_json(str(existing[1]))
            now = self.clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("Timezone-aware clock required")
            case = investigate(request, scenario, str(uuid4()), scope.subject_id, now)
            db.execute(
                "INSERT INTO aegis_cases VALUES (%s,%s,%s,%s,%s)",
                (
                    case.case_id,
                    case.tenant_id,
                    request.idempotency_key,
                    fingerprint,
                    case.model_dump_json(),
                ),
            )
            for revision, kind, refs in (
                (1, "CaseCreated", (case.case_id,)),
                (2, "EvidenceCollected", tuple(e.evidence_id for e in case.evidence)),
                (3, "InvestigationCompleted", (case.task.task_id,)),
            ):
                event = AuditEvent.model_validate(
                    {
                        "event_id": str(uuid4()),
                        "tenant_id": case.tenant_id,
                        "case_id": case.case_id,
                        "trace_id": case.trace_id,
                        "revision": revision,
                        "event_type": kind,
                        "occurred_at": now,
                        "causation_id": case.task.task_id,
                        "payload_refs": refs,
                    }
                )
                db.execute(
                    "INSERT INTO aegis_events VALUES (%s,%s,%s,%s,%s)",
                    (
                        event.event_id,
                        case.tenant_id,
                        case.case_id,
                        revision,
                        event.model_dump_json(),
                    ),
                )
            stored = db.execute(
                "SELECT body FROM aegis_cases WHERE tenant_id=%s AND case_id=%s",
                (case.tenant_id, case.case_id),
            ).fetchone()
            if stored is None or Case.model_validate_json(str(stored[0])) != case:
                raise RuntimeError("Persistence verification failed")
            return case

    def read(self, scope: Scope, case_id: str) -> Case:
        Store.authorize(scope, scope.tenant_id, "read")
        with connect(self.dsn) as db:
            row = db.execute(
                "SELECT body FROM aegis_cases WHERE tenant_id=%s AND case_id=%s",
                (scope.tenant_id, case_id),
            ).fetchone()
        if row is None:
            raise NotFound("NOT_FOUND")
        return Case.model_validate_json(str(row[0]))

    def events(self, scope: Scope, case_id: str) -> tuple[AuditEvent, ...]:
        self.read(scope, case_id)
        with connect(self.dsn) as db:
            rows = db.execute(
                "SELECT body FROM aegis_events WHERE tenant_id=%s AND case_id=%s ORDER BY revision",
                (scope.tenant_id, case_id),
            ).fetchall()
        return tuple(AuditEvent.model_validate_json(str(row[0])) for row in rows)


if __name__ == "__main__":
    migrate(os.environ["AEGISFLOW_DATABASE_URL"])
