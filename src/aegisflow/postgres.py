"""PostgreSQL adapter and explicit, transactionally versioned initial migration."""

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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


RLS_MIGRATION = """
ALTER TABLE aegis_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE aegis_cases FORCE ROW LEVEL SECURITY;
CREATE POLICY aegis_case_tenant ON aegis_cases
USING (tenant_id = current_setting('aegis.tenant_id', true))
WITH CHECK (tenant_id = current_setting('aegis.tenant_id', true));
ALTER TABLE aegis_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE aegis_events FORCE ROW LEVEL SECURITY;
CREATE POLICY aegis_event_tenant ON aegis_events
USING (tenant_id = current_setting('aegis.tenant_id', true))
WITH CHECK (tenant_id = current_setting('aegis.tenant_id', true));
UPDATE aegis_schema_version SET version=2 WHERE version=1;
"""


@contextmanager
def tenant_transaction(dsn: str, scope: Scope) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """Tenant is supplied by trusted authentication, never by source or request fields."""
    with connect(dsn) as db:
        db.execute("SELECT set_config('aegis.tenant_id', %s, true)", (scope.tenant_id,))
        yield db


def connect(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    if not dsn.strip():
        raise ValueError("Explicit PostgreSQL connection required")
    return psycopg.connect(
        dsn, connect_timeout=5, options="-c statement_timeout=5000 -c lock_timeout=5000"
    )


def migrate(dsn: str) -> None:
    """Run with a schema owner, separately from the runtime role."""
    with connect(dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(62468101)")
        db.execute("CREATE TABLE IF NOT EXISTS aegis_schema_version (version INTEGER PRIMARY KEY)")
        rows = db.execute("SELECT version FROM aegis_schema_version").fetchall()
        if not rows:
            db.execute(MIGRATION)
            rows = [(1,)]
        if rows == [(1,)]:
            db.execute(RLS_MIGRATION)
        elif rows != [(2,)]:
            raise ValueError("Unsupported schema version")


class PostgresStore:
    def __init__(self, dsn: str, clock: Callable[[], datetime] | None = None) -> None:
        self.dsn = dsn
        self.clock = clock or (lambda: datetime.now(UTC))
        with connect(dsn) as db:
            if db.execute("SELECT version FROM aegis_schema_version").fetchall() != [(2,)]:
                raise ValueError("Unsupported schema version; run migration explicitly")

    def verify_runtime_role(self) -> None:
        """HTTP serving must not use a role capable of bypassing tenant policies."""
        with connect(self.dsn) as db:
            elevated = db.execute("""
                SELECT EXISTS (SELECT 1 FROM pg_roles
                WHERE (rolsuper OR rolbypassrls OR rolcreaterole)
                AND pg_has_role(current_user, oid, 'MEMBER'))
            """).fetchone()
            tables = db.execute("""
                SELECT relrowsecurity, relforcerowsecurity,
                       pg_has_role(current_user, relowner, 'MEMBER')
                FROM pg_class WHERE oid IN ('aegis_cases'::regclass, 'aegis_events'::regclass)
            """).fetchall()
            if (
                elevated != (False,)
                or len(tables) != 2
                or any(row != (True, True, False) for row in tables)
            ):
                raise ValueError("HTTP runtime requires a non-owner role without RLS bypass")

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
        with tenant_transaction(self.dsn, scope) as db:
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

    def transition_action(
        self, scope: Scope, case_id: str, operation: str, expected_digest: str | None = None
    ) -> dict[str, object]:
        from .actions import transition

        Store.authorize(scope, scope.tenant_id, "read")
        with tenant_transaction(self.dsn, scope) as db:
            lock_id = int.from_bytes(
                bytes.fromhex(digest(["action", scope.tenant_id, case_id])[:16]), signed=True
            )
            db.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))
            row = db.execute(
                "SELECT body FROM aegis_cases WHERE tenant_id=%s AND case_id=%s",
                (scope.tenant_id, case_id),
            ).fetchone()
            if row is None:
                raise NotFound("NOT_FOUND")
            case = Case.model_validate_json(str(row[0]))
            rows = db.execute(
                "SELECT body FROM aegis_events WHERE tenant_id=%s AND case_id=%s ORDER BY revision",
                (scope.tenant_id, case_id),
            ).fetchall()
            events = tuple(AuditEvent.model_validate_json(str(row[0])) for row in rows)
            now = self.clock()
            action, kind = transition(case, events, scope, operation, expected_digest, now)
            if kind is None:
                return action.model_dump(mode="json")
            event = AuditEvent.model_validate(
                {
                    "event_id": str(uuid4()),
                    "tenant_id": case.tenant_id,
                    "case_id": case_id,
                    "trace_id": case.trace_id,
                    "revision": len(events) + 1,
                    "event_type": kind,
                    "occurred_at": now,
                    "producer": "action-workflow-v1",
                    "causation_id": action.action_id,
                    "payload_refs": (action.action_id,),
                    "action_record": action.model_dump(mode="json"),
                }
            )
            db.execute(
                "INSERT INTO aegis_events VALUES (%s,%s,%s,%s,%s)",
                (event.event_id, scope.tenant_id, case_id, event.revision, event.model_dump_json()),
            )
            stored = db.execute(
                "SELECT body FROM aegis_events WHERE event_id=%s", (event.event_id,)
            ).fetchone()
            if stored is None or AuditEvent.model_validate_json(str(stored[0])) != event:
                raise RuntimeError("Action persistence verification failed")
            return action.model_dump(mode="json")

    def list_cases(self, scope: Scope, limit: int = 100, offset: int = 0) -> tuple[Case, ...]:
        Store.authorize(scope, scope.tenant_id, "read")
        if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
            raise ValueError("Invalid case page")
        with tenant_transaction(self.dsn, scope) as db:
            rows = db.execute(
                "SELECT body FROM aegis_cases WHERE tenant_id=%s "
                "ORDER BY (body::jsonb->>'created_at')::timestamptz DESC, case_id DESC LIMIT %s OFFSET %s",
                (scope.tenant_id, limit, offset),
            ).fetchall()
        return tuple(Case.model_validate_json(str(row[0])) for row in rows)

    def read(self, scope: Scope, case_id: str) -> Case:
        Store.authorize(scope, scope.tenant_id, "read")
        with tenant_transaction(self.dsn, scope) as db:
            row = db.execute(
                "SELECT body FROM aegis_cases WHERE tenant_id=%s AND case_id=%s",
                (scope.tenant_id, case_id),
            ).fetchone()
        if row is None:
            raise NotFound("NOT_FOUND")
        return Case.model_validate_json(str(row[0]))

    def events(self, scope: Scope, case_id: str) -> tuple[AuditEvent, ...]:
        self.read(scope, case_id)
        with tenant_transaction(self.dsn, scope) as db:
            rows = db.execute(
                "SELECT body FROM aegis_events WHERE tenant_id=%s AND case_id=%s ORDER BY revision",
                (scope.tenant_id, case_id),
            ).fetchall()
        return tuple(AuditEvent.model_validate_json(str(row[0])) for row in rows)


if __name__ == "__main__":
    migrate(os.environ["AEGISFLOW_DATABASE_URL"])
