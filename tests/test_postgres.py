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
from tests.access_helpers import access_for

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
        db.execute("UPDATE aegis_schema_version SET version=3")
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


def test_api_postgres_evidence_and_dependency_failure(dsn, runtime_dsn):
    import secrets

    token = secrets.token_urlsafe(32)
    migrate(dsn)
    app = create_app(
        PostgresStore(runtime_dsn),
        {token_digest(token): SCOPE},
        (generate(),),
        source_access=access_for(SCOPE),
    )
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


@pytest.fixture
def runtime_dsn(dsn):
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
        yield runtime_dsn
    finally:
        with connect(dsn) as db:
            db.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            db.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_runtime_role_cannot_migrate_or_mutate_audit(runtime_dsn):
    store = PostgresStore(runtime_dsn)
    store.verify_runtime_role()
    case = store.run(SCOPE, REQUEST, generate())
    assert store.read(SCOPE, case.case_id) == case
    assert len(store.events(SCOPE, case.case_id)) == 3
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        migrate(runtime_dsn)
    with connect(runtime_dsn) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("DELETE FROM aegis_events")
    with connect(runtime_dsn) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("CREATE TABLE unauthorized (id int)")


def test_rls_filters_unscoped_queries_and_rejects_cross_tenant_writes(runtime_dsn):
    from aegisflow.contracts import Scenario
    from aegisflow.postgres import tenant_transaction

    store = PostgresStore(runtime_dsn)
    own = store.run(SCOPE, REQUEST, generate())
    other = Scope(tenant_id="other", subject_id="other", permissions={"read", "investigate"})
    source = generate().model_dump(mode="json")
    source["order"]["tenant_id"] = "other"
    other_request = Request.model_validate({**REQUEST.model_dump(), "tenant_id": "other"})
    foreign = store.run(other, other_request, Scenario.model_validate(source))
    assert own.case_id != foreign.case_id  # Same idempotency key is independent per tenant.
    with connect(runtime_dsn) as db:
        assert db.execute("SELECT case_id FROM aegis_cases").fetchall() == []
        assert db.execute("SELECT event_id FROM aegis_events").fetchall() == []
    with tenant_transaction(runtime_dsn, SCOPE) as db:
        assert db.execute("SELECT case_id FROM aegis_cases").fetchall() == [(own.case_id,)]
        assert db.execute("SELECT count(*) FROM aegis_events").fetchone()[0] == 3
        assert (
            db.execute(
                "SELECT body FROM aegis_cases WHERE case_id=%s", (foreign.case_id,)
            ).fetchall()
            == []
        )
    with (
        tenant_transaction(runtime_dsn, SCOPE) as db,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        db.execute(
            "INSERT INTO aegis_cases VALUES (%s,'other','forged','hash','{}')", (str(uuid4()),)
        )
    with (
        tenant_transaction(runtime_dsn, SCOPE) as db,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        db.execute(
            "INSERT INTO aegis_events VALUES (%s,'other',%s,99,'{}')",
            (str(uuid4()), foreign.case_id),
        )
    with connect(runtime_dsn) as db, pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(
            "INSERT INTO aegis_cases VALUES (%s,'demo','missing-context','hash','{}')",
            (str(uuid4()),),
        )


@pytest.mark.parametrize("rollback", [False, True])
def test_tenant_context_clears_on_reused_connection(runtime_dsn, rollback):
    store = PostgresStore(runtime_dsn)
    store.run(SCOPE, REQUEST, generate())
    with connect(runtime_dsn) as db:
        db.execute("SELECT set_config('aegis.tenant_id','demo',true)")
        assert db.execute("SELECT count(*) FROM aegis_cases").fetchone()[0] == 1
        if rollback:
            db.rollback()
        else:
            db.commit()
        assert db.execute("SELECT count(*) FROM aegis_cases").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM aegis_events").fetchone()[0] == 0


def test_http_rejects_privileged_or_rls_disabled_runtime(dsn, runtime_dsn):
    import secrets

    creds = {token_digest(secrets.token_urlsafe(32)): SCOPE}
    with pytest.raises(ValueError):
        create_app(PostgresStore(dsn), creds, (generate(),), source_access=access_for(SCOPE))
    with connect(dsn) as db:
        db.execute("ALTER TABLE aegis_cases DISABLE ROW LEVEL SECURITY")
    with pytest.raises(ValueError):
        create_app(
            PostgresStore(runtime_dsn), creds, (generate(),), source_access=access_for(SCOPE)
        )


def test_http_rejects_bypassrls_role(dsn, runtime_dsn):
    with connect(runtime_dsn) as db:
        role = db.execute("SELECT current_user").fetchone()[0]
    with connect(dsn) as db:
        db.execute(sql.SQL("ALTER ROLE {} BYPASSRLS").format(sql.Identifier(role)))
    with pytest.raises(ValueError):
        PostgresStore(runtime_dsn).verify_runtime_role()


def test_v1_migration_preserves_existing_rows(dsn):
    from aegisflow.engine import investigate
    from aegisflow.postgres import MIGRATION

    old = investigate(REQUEST, generate(), str(uuid4()), SCOPE.subject_id, REQUEST.as_of)
    with connect(dsn) as db:
        db.execute("CREATE TABLE aegis_schema_version (version INTEGER PRIMARY KEY)")
        db.execute(MIGRATION)
        db.execute(
            "INSERT INTO aegis_cases VALUES (%s,%s,%s,'old-fingerprint',%s)",
            (old.case_id, old.tenant_id, REQUEST.idempotency_key, old.model_dump_json()),
        )
    migrate(dsn)
    migrate(dsn)
    assert PostgresStore(dsn).read(SCOPE, old.case_id) == old
    with connect(dsn) as db:
        assert db.execute("SELECT version FROM aegis_schema_version").fetchall() == [(2,)]
        assert db.execute("SELECT fingerprint FROM aegis_cases").fetchall() == [
            ("old-fingerprint",)
        ]


def test_failed_rls_migration_rolls_back_policies_and_version(dsn):
    from aegisflow.postgres import MIGRATION

    with connect(dsn) as db:
        db.execute("CREATE TABLE aegis_schema_version (version INTEGER PRIMARY KEY)")
        db.execute(MIGRATION)
        db.execute("CREATE POLICY aegis_event_tenant ON aegis_events USING (false)")
    with pytest.raises(psycopg.errors.DuplicateObject):
        migrate(dsn)
    with connect(dsn) as db:
        assert db.execute("SELECT version FROM aegis_schema_version").fetchall() == [(1,)]
        assert db.execute(
            "SELECT relrowsecurity FROM pg_class WHERE oid='aegis_cases'::regclass"
        ).fetchone() == (False,)
        assert (
            db.execute(
                "SELECT count(*) FROM pg_policies WHERE policyname='aegis_case_tenant'"
            ).fetchone()[0]
            == 0
        )


def test_blank_postgres_connection_is_rejected():
    with pytest.raises(ValueError):
        connect("  ")


def test_source_revocation_cannot_bypass_postgres_replay(runtime_dsn, tmp_path):
    import secrets

    from aegisflow.access import SourceAccess, SourcePolicy

    token = secrets.token_urlsafe(32)
    policy_file = tmp_path / "acl.json"
    policy_file.write_text(access_for(SCOPE).load().model_dump_json())
    store = PostgresStore(runtime_dsn)
    app = create_app(
        store, {token_digest(token): SCOPE}, (generate(),), source_access=SourceAccess(policy_file)
    )
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "pg-revoke"}
    with TestClient(app) as client:
        body = {"order_id": "PO-001", "as_of": "2026-11-01T18:00:00Z"}
        response = client.post("/v1/cases", json=body, headers=headers)
        assert response.status_code == 201
        case = response.json()
        replacement = policy_file.with_suffix(".new")
        replacement.write_text(SourcePolicy(revision="revoked", grants=()).model_dump_json())
        replacement.replace(policy_file)
        for route in (
            f"/v1/cases/{case['case_id']}",
            f"/v1/cases/{case['case_id']}/events",
            f"/v1/cases/{case['case_id']}/evidence/{case['evidence'][0]['evidence_id']}",
        ):
            assert client.get(route, headers=headers).status_code == 404
        assert client.post("/v1/cases", json=body, headers=headers).status_code == 404
        assert len(store.events(SCOPE, case["case_id"])) == 3


def test_jwt_authentication_and_principal_revocation_with_rls(runtime_dsn, tmp_path):
    import json

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from aegisflow.identity import IdentityPolicy, JWTIdentity, PrincipalBinding

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = {
        **jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True),
        "kid": "pg-key",
        "use": "sig",
        "alg": "RS256",
    }
    keys = tmp_path / "keys.json"
    principals = tmp_path / "principals.json"
    keys.write_text(json.dumps({"keys": [public]}))
    principals.write_text(
        IdentityPolicy(
            revision="pg-1", principals=(PrincipalBinding(external_subject="pg-user", scope=SCOPE),)
        ).model_dump_json()
    )
    now = datetime.now(UTC)
    identity = JWTIdentity(
        "https://issuer.example.test", "aegisflow-api", keys, principals, clock=lambda: now
    )
    token = jwt.encode(
        {
            "iss": identity.issuer,
            "aud": identity.audience,
            "sub": "pg-user",
            "jti": "pg-1",
            "client_id": "test-client",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(now.timestamp()) + 600,
        },
        key,
        algorithm="RS256",
        headers={"kid": "pg-key", "typ": "at+jwt"},
    )
    store = PostgresStore(runtime_dsn)
    app = create_app(store, {}, (generate(),), source_access=access_for(SCOPE), identity=identity)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + token, "Idempotency-Key": "pg-identity"}
        body = {"order_id": "PO-001", "as_of": "2026-11-01T18:00:00Z"}
        response = client.post("/v1/cases", json=body, headers=headers)
        assert response.status_code == 201
        case = response.json()
        assert client.post("/v1/cases", json=body, headers=headers).json() == case
        principals.write_text(
            IdentityPolicy(revision="pg-revoked", principals=()).model_dump_json()
        )
        assert client.get("/v1/cases/" + case["case_id"], headers=headers).status_code == 401
        assert client.post("/v1/cases", json=body, headers=headers).status_code == 401
        assert len(store.events(SCOPE, case["case_id"])) == 3


def test_case_history_paging_and_tenant_isolation(dsn):
    migrate(dsn)
    store = PostgresStore(dsn)
    cases = [
        store.run(SCOPE, REQUEST.model_copy(update={"idempotency_key": f"history-{i}"}), generate())
        for i in range(3)
    ]
    listed = PostgresStore(dsn).list_cases(SCOPE)
    assert {c.case_id for c in listed} == {c.case_id for c in cases}
    assert store.list_cases(SCOPE, limit=1, offset=1) == listed[1:2]
    assert store.list_cases(SCOPE.model_copy(update={"tenant_id": "other"})) == ()
    with pytest.raises(PolicyDenied):
        store.list_cases(SCOPE.model_copy(update={"permissions": frozenset()}))


def test_postgres_action_workflow_concurrency(runtime_dsn):
    from tests.test_actions import exercise_workflow

    store = PostgresStore(runtime_dsn)
    store.verify_runtime_role()
    exercise_workflow(store)


def test_postgres_action_insert_rollback(dsn):
    from tests.test_actions import SCOPE as ACTION_SCOPE
    from tests.test_actions import make_case

    migrate(dsn)
    store = PostgresStore(dsn)
    case = make_case(store)
    proposal = store.transition_action(ACTION_SCOPE, case.case_id, "propose")
    store.transition_action(ACTION_SCOPE, case.case_id, "approve", proposal["content_digest"])
    with connect(dsn) as db:
        db.execute("ALTER TABLE aegis_events ADD CONSTRAINT fail_execution CHECK (revision < 6)")
    with pytest.raises(psycopg.errors.CheckViolation):
        store.transition_action(ACTION_SCOPE, case.case_id, "execute", proposal["content_digest"])
    assert len(store.events(ACTION_SCOPE, case.case_id)) == 5
