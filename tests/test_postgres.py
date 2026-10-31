"""Real PostgreSQL tests: each test owns and drops a separate database."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from aegisflow.api import create_app, token_digest
from aegisflow.contracts import Request, Scope
from aegisflow.postgres import PostgresStore, connect, migrate
from aegisflow.scenario import generate
from aegisflow.store import IdempotencyConflict, NotFound, PolicyDenied

SCOPE = Scope(tenant_id="demo", subject_id="test", permissions={"read", "investigate"})
REQUEST = Request(
    tenant_id="demo",
    order_id="PO-001",
    idempotency_key="test-1",
    as_of=datetime(2026, 11, 1, 18, tzinfo=UTC),
)


@pytest.fixture
def dsn():
    base = os.environ.get("AEGISFLOW_TEST_DATABASE_URL")
    if not base:
        pytest.skip("Set AEGISFLOW_TEST_DATABASE_URL for real PostgreSQL integration tests")
    name = "aegis_test_" + uuid4().hex
    with psycopg.connect(base, autocommit=True) as db:
        db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    result = make_conninfo(base, dbname=name)
    try:
        yield result
    finally:
        with psycopg.connect(base, autocommit=True) as db:
            db.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_migration_and_reopen(dsn):
    with pytest.raises(psycopg.errors.UndefinedTable):
        PostgresStore(dsn)
    migrate(dsn)
    migrate(dsn)
    store = PostgresStore(dsn)
    case = store.run(SCOPE, REQUEST, generate())
    assert case.status == "COMPLETED"
    assert next(c.value for c in case.claims if c.code == "DELIVERY_DELAY") == 25200
    assert PostgresStore(dsn).read(SCOPE, case.case_id) == case
    assert len(store.events(SCOPE, case.case_id)) == 3
    with connect(dsn) as db:
        db.execute("UPDATE aegis_schema_version SET version=2")
    with pytest.raises(ValueError):
        migrate(dsn)
    with pytest.raises(ValueError):
        PostgresStore(dsn)


def test_concurrent_idempotency_and_conflict(dsn):
    migrate(dsn)
    store = PostgresStore(dsn)
    with ThreadPoolExecutor(max_workers=4) as pool:
        cases = list(pool.map(lambda _: store.run(SCOPE, REQUEST, generate()), range(4)))
    assert len({c.case_id for c in cases}) == 1
    assert len(store.events(SCOPE, cases[0].case_id)) == 3
    with pytest.raises(IdempotencyConflict):
        store.run(SCOPE, REQUEST, generate(1))


def test_tenant_scope_and_composite_foreign_key(dsn):
    migrate(dsn)
    store = PostgresStore(dsn)
    case = store.run(SCOPE, REQUEST, generate())
    other = Scope(tenant_id="other", subject_id="other", permissions={"read", "investigate"})
    for method in (store.read, store.events):
        with pytest.raises(NotFound):
            method(other, case.case_id)
    with pytest.raises(PolicyDenied):
        store.run(other, REQUEST, generate())
    with connect(dsn) as db, pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(
            "INSERT INTO aegis_events VALUES (%s,%s,%s,1,'{}')",
            (str(uuid4()), "other", case.case_id),
        )
    with connect(dsn) as db:
        assert db.execute("SELECT count(*) FROM aegis_events").fetchone()[0] == 3


def test_audit_failure_rolls_back_entire_case(dsn):
    migrate(dsn)
    with connect(dsn) as db:
        db.execute("ALTER TABLE aegis_events ADD CONSTRAINT injected_failure CHECK (revision < 2)")
    with pytest.raises(psycopg.errors.CheckViolation):
        PostgresStore(dsn).run(SCOPE, REQUEST, generate())
    with connect(dsn) as db:
        assert db.execute("SELECT count(*) FROM aegis_cases").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM aegis_events").fetchone()[0] == 0


@pytest.mark.parametrize(
    "command",
    ["UPDATE aegis_events SET revision=99", "DELETE FROM aegis_events", "TRUNCATE aegis_events"],
)
def test_audit_mutation_rejected(dsn, command):
    migrate(dsn)
    store = PostgresStore(dsn)
    case = store.run(SCOPE, REQUEST, generate())
    with connect(dsn) as db, pytest.raises(psycopg.errors.RaiseException):
        db.execute(command)
    assert len(store.events(SCOPE, case.case_id)) == 3


def test_api_postgres_evidence_and_dependency_failure(dsn):
    import secrets

    token = secrets.token_urlsafe(32)
    migrate(dsn)
    app = create_app(PostgresStore(dsn), {token_digest(token): SCOPE}, (generate(),))
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "http-pg"}
    with TestClient(app) as client:
        body = {"order_id": "PO-001", "as_of": "2026-11-01T18:00:00Z"}
        response = client.post("/v1/cases", headers=headers, json=body)
        assert response.status_code == 201
        case = response.json()
        assert client.post("/v1/cases", headers=headers, json=body).json() == case
        path = f"/v1/cases/{case['case_id']}/evidence/{case['evidence'][0]['evidence_id']}"
        assert client.get(path, headers=headers).json() == case["evidence"][0]
        with connect(dsn) as db:
            db.execute("DROP TABLE aegis_events")
        failure = client.get(f"/v1/cases/{case['case_id']}/events", headers=headers)
        assert failure.status_code == 503 and dsn not in failure.text


def test_runtime_role_cannot_migrate_or_mutate_audit(dsn):
    import secrets

    migrate(dsn)
    role = "aegis_runtime_" + uuid4().hex
    password = secrets.token_urlsafe(32)
    with connect(dsn) as db:
        db.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        db.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        db.execute(
            sql.SQL("GRANT SELECT ON aegis_schema_version TO {}").format(sql.Identifier(role))
        )
        db.execute(
            sql.SQL("GRANT SELECT, INSERT ON aegis_cases, aegis_events TO {}").format(
                sql.Identifier(role)
            )
        )
    runtime_dsn = make_conninfo(dsn, user=role, password=password)
    try:
        store = PostgresStore(runtime_dsn)
        case = store.run(SCOPE, REQUEST, generate())
        assert store.read(SCOPE, case.case_id) == case
        assert len(store.events(SCOPE, case.case_id)) == 3
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            migrate(runtime_dsn)
        with connect(runtime_dsn) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("DELETE FROM aegis_events")
        with connect(runtime_dsn) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("CREATE TABLE unauthorized (id int)")
    finally:
        with connect(dsn) as db:
            db.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            db.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
