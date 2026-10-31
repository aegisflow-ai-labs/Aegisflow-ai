import hashlib
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegisflow.contracts import Case, Request, Scenario, Scope
from aegisflow.engine import digest
from aegisflow.scenario import generate
from aegisflow.store import IdempotencyConflict, NotFound, PolicyDenied, Store

NOW = datetime(2026, 11, 1, 18, tzinfo=UTC)
SCOPE = Scope(
    tenant_id="demo", subject_id="analyst", permissions=frozenset({"investigate", "read"})
)


def request(**changes: object) -> Request:
    return Request.model_validate(
        {
            "tenant_id": "demo",
            "order_id": "PO-001",
            "idempotency_key": "request-1",
            "as_of": NOW,
            **changes,
        }
    )


def scenario(**changes: object) -> Scenario:
    return Scenario.model_validate({**generate().model_dump(), **changes})


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db", clock=lambda: NOW)


def test_golden_case_persistence_and_evidence(store: Store) -> None:
    case = store.run(SCOPE, request(), generate())
    assert case.status == "COMPLETED"
    values = {claim.code: claim.value for claim in case.claims}
    assert values == {
        "DELIVERY_DELAY": 25200,
        "SLA_BREACH": True,
        "INVENTORY": 20,
        "PROCEDURE": "Escalate to procurement after SLA breach",
    }
    assert store.read(SCOPE, case.case_id) == case
    assert case.active_roles == ("A21",) and case.model_calls == 0
    assert case.source_checksum == digest(generate().model_dump(mode="json"))
    for evidence in case.evidence:
        assert evidence.checksum == digest(evidence.snapshot)
    assert [e.event_type for e in store.events(SCOPE, case.case_id)] == [
        "CaseCreated",
        "EvidenceCollected",
        "InvestigationCompleted",
    ]
    assert [e.revision for e in store.events(SCOPE, case.case_id)] == [1, 2, 3]
    assert Store(store.path).read(SCOPE, case.case_id) == case


def test_seeded_dataset() -> None:
    assert generate().model_dump_json() == generate().model_dump_json()
    fixture = Path("fixtures/supply-delay-v1.json").read_text()
    assert Scenario.model_validate_json(fixture) == generate()
    manifest = json.loads(Path("fixtures/manifest.json").read_text())
    assert manifest["checksum"] == digest(generate().model_dump(mode="json"))
    assert (
        manifest["generator_sha256"]
        == hashlib.sha256(Path("src/aegisflow/scenario.py").read_bytes()).hexdigest()
    )


def test_retry_and_changed_source(store: Store) -> None:
    case = store.run(SCOPE, request(), generate())
    assert store.run(SCOPE, request(), generate()) == case
    assert len(store.events(SCOPE, case.case_id)) == 3
    with pytest.raises(IdempotencyConflict):
        store.run(SCOPE, request(as_of=NOW + timedelta(seconds=1)), generate())
    with pytest.raises(IdempotencyConflict):
        store.run(SCOPE, request(), generate(1))
    other_user = Scope(tenant_id="demo", subject_id="other", permissions=SCOPE.permissions)
    with pytest.raises(IdempotencyConflict):
        store.run(other_user, request(), generate())


def test_concurrent_retry(store: Store) -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        cases = list(pool.map(lambda _: store.run(SCOPE, request(), generate()), range(4)))
    assert len({case.case_id for case in cases}) == 1
    assert len(store.events(SCOPE, cases[0].case_id)) == 3


@pytest.mark.parametrize("missing", ["sla", "inventory", "procedure"])
def test_missing_evidence(store: Store, missing: str) -> None:
    case = store.run(SCOPE, request(), scenario(**{missing: None}))
    assert case.status == "NEEDS_EVIDENCE"
    assert f"MISSING_{missing.upper()}" in case.uncertainty
    if missing == "sla":
        assert "SLA_BREACH" not in {c.code for c in case.claims}


def test_conflicting_and_duplicate_events(store: Store) -> None:
    source = generate()
    duplicate = scenario(deliveries=(source.deliveries[0], source.deliveries[0]))
    assert store.run(SCOPE, request(), duplicate).status == "COMPLETED"
    event = source.deliveries[0].model_dump()
    event["delivered_at"] = NOW
    conflict = scenario(deliveries=(source.deliveries[0].model_dump(), event))
    case = store.run(SCOPE, request(idempotency_key="conflict"), conflict)
    assert case.status == "NEEDS_EVIDENCE"
    assert "CONFLICTING_DELIVERY_EVENTS" in case.uncertainty
    assert not {c.code for c in case.claims} & {"SLA_BREACH", "DELIVERY_DELAY"}


@pytest.mark.parametrize("seconds,breached", [(0, False), (3600, False), (3601, True)])
def test_sla_exact_boundary(store: Store, seconds: int, breached: bool) -> None:
    source = generate()
    event = source.deliveries[0].model_dump()
    event["delivered_at"] = source.order.promised_at + timedelta(seconds=seconds)
    case = store.run(SCOPE, request(), scenario(deliveries=(event,)))
    values = {c.code: c.value for c in case.claims}
    assert values["DELIVERY_DELAY"] == seconds
    assert values["SLA_BREACH"] is breached


def test_timezone_offsets_and_dst_elapsed_time(store: Store) -> None:
    source = generate().model_dump(mode="json")
    source["order"]["placed_at"] = "2026-10-24T00:00:00Z"
    source["order"]["promised_at"] = "2026-10-25T02:30:00+02:00"
    source["deliveries"][0]["delivered_at"] = "2026-10-25T02:30:00+01:00"
    source["inventory"]["captured_at"] = "2026-10-25T00:00:00Z"
    case = store.run(SCOPE, request(as_of="2026-10-25T03:00:00Z"), Scenario.model_validate(source))
    assert next(c.value for c in case.claims if c.code == "DELIVERY_DELAY") == 3600


def test_undelivered_future_event_not_used(store: Store) -> None:
    case = store.run(SCOPE, request(as_of="2026-11-01T10:00:00Z"), generate())
    assert next(c.value for c in case.claims if c.code == "DELIVERY_DELAY") == 3600
    equivalent = request(as_of="2026-11-01T13:00:00+03:00")
    assert store.run(SCOPE, equivalent, generate()) == case


@pytest.mark.parametrize("timestamp", ["2026-10-30T00:00:00Z", "2026-11-02T00:00:00Z"])
def test_stale_or_future_stock(store: Store, timestamp: str) -> None:
    case = store.run(
        SCOPE, request(), scenario(inventory={"available": 20, "captured_at": timestamp})
    )
    assert "STALE_OR_FUTURE_INVENTORY" in case.uncertainty
    assert "INVENTORY" not in {c.code for c in case.claims}


@pytest.mark.parametrize(
    "changes", [{"as_of": "2026-11-01T18:00:00"}, {"order_id": ""}, {"extra": "ignored?"}]
)
def test_invalid_request(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        request(**changes)


@pytest.mark.parametrize(
    "changes", [{"quantity": -1}, {"quantity": True}, {"promised_at": "2020-01-01T00:00:00Z"}]
)
def test_invalid_order(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        scenario(order={**generate().order.model_dump(), **changes})


def test_scope_boundaries(store: Store) -> None:
    case = store.run(SCOPE, request(), generate())
    other = Scope(tenant_id="other", subject_id="analyst", permissions=SCOPE.permissions)
    with pytest.raises(PolicyDenied):
        store.run(other, request(), generate())
    for _ in range(100):
        with pytest.raises(NotFound):
            store.read(other, case.case_id)
    with pytest.raises(NotFound):
        store.events(other, case.case_id)
    denied = Scope(tenant_id="demo", subject_id="analyst", permissions=frozenset())
    with pytest.raises(PolicyDenied):
        store.run(denied, request(), generate())
    with pytest.raises(PolicyDenied):
        store.read(denied, case.case_id)
    with pytest.raises(NotFound):
        store.run(SCOPE, request(order_id="unknown"), generate())
    with pytest.raises(NotFound):
        store.run(
            SCOPE,
            request(),
            scenario(order={**generate().order.model_dump(), "tenant_id": "other"}),
        )


def test_rollback_and_append_only_audit(store: Store) -> None:
    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_event BEFORE INSERT ON events "
            "BEGIN SELECT RAISE(ABORT, 'failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.run(SCOPE, request(), generate())
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM cases").fetchone()[0] == 0
        db.execute("DROP TRIGGER fail_event")
    case = store.run(SCOPE, request(), generate())
    for sql in ("UPDATE events SET revision=9", "DELETE FROM events"):
        with store.connect() as db, pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)
    assert len(store.events(SCOPE, case.case_id)) == 3


def test_claim_references_cannot_be_forged(store: Store) -> None:
    case = store.run(SCOPE, request(), generate()).model_dump()
    case["claims"][0]["evidence_refs"] = ["missing"]
    with pytest.raises(ValidationError):
        Case.model_validate(case)


def test_invalid_clock_and_time_leave_no_case(store: Store) -> None:
    with pytest.raises(ValueError):
        store.run(SCOPE, request(as_of="2020-01-01T00:00:00Z"), generate())
    store.clock = lambda: datetime(2026, 11, 1)
    with pytest.raises(ValueError):
        store.run(SCOPE, request(), generate())
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM cases").fetchone()[0] == 0


def test_cli_e2e_and_error(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "aegisflow",
        "run",
        "--scenario",
        "fixtures/supply-delay-v1.json",
        "--db",
        str(tmp_path / "cli.db"),
        "--key",
        "cli-1",
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    assert json.loads(first.stdout) == json.loads(second.stdout)
    assert json.loads(first.stdout)["case"]["status"] == "COMPLETED"
    invalid = subprocess.run(
        command + ["--as-of", "invalid"], capture_output=True, text=True, check=False
    )
    assert invalid.returncode == 1 and "INVALID_SCHEMA" in invalid.stderr
    missing = subprocess.run(
        [*command[:5], "missing.json", *command[6:]], capture_output=True, text=True, check=False
    )
    assert missing.returncode == 1 and "DEPENDENCY_UNAVAILABLE" in missing.stderr


def test_fractional_sla_boundary(store: Store) -> None:
    source = generate()
    event = source.deliveries[0].model_dump()
    event["delivered_at"] = source.order.promised_at + timedelta(seconds=3600, microseconds=1)
    case = store.run(SCOPE, request(), scenario(deliveries=(event,)))
    assert next(c.value for c in case.claims if c.code == "SLA_BREACH") is True


def test_schema_files_match_contracts() -> None:
    from aegisflow import contracts

    for name in ("Request", "Scenario", "Case", "Task", "Evidence", "AuditEvent"):
        model = getattr(contracts, name)
        assert (
            json.loads(Path(f"schemas/{name}.schema.json").read_text()) == model.model_json_schema()
        )


def test_role_registry_reports_only_implemented_subset(store: Store) -> None:
    registry = json.loads(Path("docs/roles.json").read_text())
    assert {r["role_id"] for r in registry} == {f"A{i:02}" for i in range(1, 37)}
    assert sum(r["registered"] for r in registry) == 36
    assert [r["role_id"] for r in registry if r["implemented"]] == ["A21"]
    assert [r["role_id"] for r in registry if r["tested"]] == ["A21"]
    assert store.run(SCOPE, request(), generate()).active_roles == ("A21",)
