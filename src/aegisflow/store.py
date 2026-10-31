"""Local SQLite transaction boundary; callers supply trusted Scope, never source data."""

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .contracts import AuditEvent, Case, Request, Scenario, Scope
from .engine import digest, investigate


class PolicyDenied(Exception):
    pass


class NotFound(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


class Store:
    def __init__(self, path: Path, clock: Callable[[], datetime] | None = None) -> None:
        self.path = path
        self.clock = clock or (lambda: datetime.now(UTC))
        with closing(self.connect()) as db, db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Desteklenmeyen veritabanı sürümü")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL,
                    UNIQUE(tenant_id, request_key));
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id),
                    revision INTEGER NOT NULL, body TEXT NOT NULL,
                    UNIQUE(case_id, revision));
                CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'audit append only'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'audit append only'); END;
                PRAGMA user_version = 1;
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def authorize(scope: Scope, tenant: str, permission: str) -> None:
        if scope.tenant_id != tenant or permission not in scope.permissions:
            raise PolicyDenied("POLICY_DENIED: Bu işlem için yetki yok")

    def run(self, scope: Scope, request: Request, scenario: Scenario) -> Case:
        self.authorize(scope, request.tenant_id, "investigate")
        if (
            scenario.order.tenant_id != scope.tenant_id
            or scenario.order.order_id != request.order_id
        ):
            raise NotFound("NOT_FOUND: Kaynak bulunamadı")
        payload = request.model_dump(mode="json")
        payload["as_of"] = request.as_of.astimezone(UTC).isoformat()
        fingerprint = digest(
            {
                "request": payload,
                "source": scenario.model_dump(mode="json"),
                "subject_id": scope.subject_id,
            }
        )
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT fingerprint, body FROM cases WHERE tenant_id=? AND request_key=?",
                (scope.tenant_id, request.idempotency_key),
            ).fetchone()
            if existing:
                if existing[0] != fingerprint:
                    raise IdempotencyConflict("IDEMPOTENCY_CONFLICT: Aynı anahtarla farklı istek")
                return Case.model_validate_json(existing[1])
            now = self.clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("Saat dilimli sistem saati gerekli")
            case = investigate(request, scenario, str(uuid4()), scope.subject_id, now)
            db.execute(
                "INSERT INTO cases VALUES (?, ?, ?, ?, ?)",
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
                    "INSERT INTO events VALUES (?, ?, ?, ?)",
                    (event.event_id, case.case_id, revision, event.model_dump_json()),
                )
            # Read-after-write verifies the persisted report before committing.
            stored = db.execute(
                "SELECT body FROM cases WHERE case_id=?", (case.case_id,)
            ).fetchone()
            if stored is None or Case.model_validate_json(stored[0]) != case:
                raise RuntimeError("Kayıt doğrulaması başarısız")
            return case

    def read(self, scope: Scope, case_id: str) -> Case:
        self.authorize(scope, scope.tenant_id, "read")
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT body FROM cases WHERE case_id=? AND tenant_id=?", (case_id, scope.tenant_id)
            ).fetchone()
        if row is None:
            raise NotFound("NOT_FOUND: Vaka bulunamadı")
        return Case.model_validate_json(row[0])

    def events(self, scope: Scope, case_id: str) -> tuple[AuditEvent, ...]:
        self.read(scope, case_id)
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT body FROM events WHERE case_id=? ORDER BY revision", (case_id,)
            ).fetchall()
        return tuple(AuditEvent.model_validate(json.loads(row[0])) for row in rows)
