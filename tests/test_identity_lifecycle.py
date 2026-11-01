import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from aegisflow.api import create_app
from aegisflow.identity import IdentityPolicy, IdentityUnavailable, JWTIdentity, Unauthenticated
from aegisflow.oidc import LocalKeycloak, ProviderKeys
from aegisflow.scenario import generate
from aegisflow.store import Store
from tests.access_helpers import access_for
from tests.test_identity import AUDIENCE, NOW, SCOPE, public_jwk, signed

ISSUER = "http://127.0.0.1:8080/realms/aegisflow-local"
CLIENT = "aegisflow-local-browser"
CALLBACK = "http://127.0.0.1:8000/auth/callback"


@pytest.fixture(scope="module")
def keys():
    return tuple(rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2))


@pytest.fixture
def provider(keys, monkeypatch):
    source = LocalKeycloak(ISSUER, CLIENT, CALLBACK)
    state = {"clock": 100.0, "calls": 0, "keys": [public_jwk(keys[0])]}
    counter = Lock()

    def fetch(path):
        assert path == "/protocol/openid-connect/certs"
        with counter:
            state["calls"] += 1
        if state.get("fail"):
            raise IdentityUnavailable("private provider failure")
        return {"keys": state["keys"]}

    monkeypatch.setattr(source, "fetch", fetch)
    return ProviderKeys(source, clock=lambda: state["clock"]), state


def test_key_refresh_exact_expiry_rotation_removal_and_metadata(provider, keys):
    source, state = provider
    state["keys"][0]["x5c"] = ["trusted public certificate metadata"]
    assert source().keys[0].kid == "key-1"
    assert state["calls"] == 1
    state["keys"] = [public_jwk(keys[1], "key-2")]
    state["clock"] = 159.999
    assert source().keys[0].kid == "key-1"
    state["clock"] = 160
    assert [k.kid for k in source().keys] == ["key-2"]
    assert state["calls"] == 2


def test_expired_failure_has_no_stale_fallback_and_bounded_retries(provider):
    source, state = provider
    source()
    state.update(clock=160, fail=True)
    for _ in range(10):
        with pytest.raises(IdentityUnavailable):
            source()
    assert state["calls"] == 2
    state["clock"] = 164.999
    with pytest.raises(IdentityUnavailable):
        source()
    assert state["calls"] == 2
    state.update(clock=165, fail=False)
    assert source().keys and state["calls"] == 3


@pytest.mark.parametrize(
    "invalid",
    [
        [],
        [None],
        [{}],
        [{"alg": "RS256", "use": "sig", "kid": "bad"}],
        [{"d": "private"}],
        [{"alg": "HS256", "use": "sig"}],
    ],
)
def test_malformed_or_unsupported_provider_sets_fail_closed(provider, invalid):
    source, state = provider
    state["keys"] = invalid
    with pytest.raises(IdentityUnavailable):
        source()
    with pytest.raises(IdentityUnavailable):
        source()
    assert state["calls"] == 1


def test_duplicate_private_weak_and_untrusted_fields_rejected(provider, keys):
    source, state = provider
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    key = public_jwk(keys[0])
    for invalid in (
        [key, key],
        [{**key, "d": "private"}],
        [public_jwk(weak)],
        [{**key, "jku": "https://evil.invalid"}],
        [{**key, "n": "!"}],
        [key] * 17,
    ):
        state["clock"] += 5
        state["keys"] = invalid
        with pytest.raises(IdentityUnavailable):
            source()


def test_concurrent_requests_share_one_refresh(provider):
    source, state = provider
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: source(), range(30)))
    assert len(results) == 30 and state["calls"] == 1
    state["clock"] = 160
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda _: source(), range(30)))
    assert state["calls"] == 2


def policy_file(tmp_path):
    path = tmp_path / "principals.json"
    path.write_text(
        IdentityPolicy.model_validate(
            {
                "revision": "test-1",
                "principals": [
                    {"external_subject": "external-user", "scope": SCOPE.model_dump(mode="json")}
                ],
            }
        ).model_dump_json()
    )
    return path


def test_dynamic_keys_no_file_fallback_unknown_kid_no_fetch_and_live_revocation(
    provider, keys, tmp_path
):
    source, state = provider
    policy = policy_file(tmp_path)
    # Use the unchanged RFC 9068 token profile with a configured trusted key supplier.
    from tests.test_identity import ISSUER as TOKEN_ISSUER

    identity = JWTIdentity(
        TOKEN_ISSUER, AUDIENCE, None, policy, clock=lambda: NOW, key_source=source
    )
    assert identity.authenticate("Bearer " + signed(keys[0])) == SCOPE
    for kid in ("unknown-1", "unknown-2", "unknown-3"):
        with pytest.raises(Unauthenticated):
            identity.authenticate("Bearer " + signed(keys[0], headers={"kid": kid}))
    assert state["calls"] == 1
    state.update(clock=160, keys=[public_jwk(keys[1], "key-2")])
    assert identity.authenticate("Bearer " + signed(keys[1], headers={"kid": "key-2"})) == SCOPE
    with pytest.raises(Unauthenticated):
        identity.authenticate("Bearer " + signed(keys[0]))
    data = json.loads(policy.read_text())
    data["principals"][0]["tokens_valid_after"] = int(NOW.timestamp())
    policy.write_text(json.dumps(data))
    with pytest.raises(Unauthenticated):
        identity.authenticate("Bearer " + signed(keys[1], headers={"kid": "key-2"}))
    restarted = JWTIdentity(
        TOKEN_ISSUER, AUDIENCE, None, policy, clock=lambda: NOW, key_source=source
    )
    with pytest.raises(Unauthenticated):
        restarted.authenticate("Bearer " + signed(keys[1], headers={"kid": "key-2"}))
    identity.clock = lambda: NOW + timedelta(seconds=1)
    new = signed(keys[1], {"iat": int(NOW.timestamp()) + 1}, headers={"kid": "key-2"})
    assert identity.authenticate("Bearer " + new) == SCOPE
    assert state["calls"] == 2


def test_unavailable_dynamic_keys_return_generic_503(provider, keys, tmp_path):
    from tests.test_identity import ISSUER as TOKEN_ISSUER

    source, state = provider
    identity = JWTIdentity(
        TOKEN_ISSUER, AUDIENCE, None, policy_file(tmp_path), clock=lambda: NOW, key_source=source
    )
    app = create_app(
        Store(tmp_path / "cases.db"),
        {},
        (generate(),),
        source_access=access_for(SCOPE),
        identity=identity,
    )
    state.update(clock=160, fail=True)
    with TestClient(app) as client:
        response = client.post(
            "/v1/cases",
            headers={"Authorization": "Bearer " + signed(keys[0]), "Idempotency-Key": "outage"},
            json={"order_id": "PO-001", "as_of": "2026-11-01T18:00:00Z"},
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "DEPENDENCY_UNAVAILABLE"}


def test_operator_cutoff_is_atomic_private_monotonic_and_preserves_grants(
    tmp_path, monkeypatch, capsys
):
    from tools import keycloak_demo

    monkeypatch.setattr(keycloak_demo, "DIRECTORY", tmp_path)
    monkeypatch.setattr(keycloak_demo.time, "time", lambda: NOW.timestamp())
    path = policy_file(tmp_path)
    (tmp_path / "login.json").write_text(json.dumps({"subject": "external-user"}))
    data = json.loads(path.read_text())
    data["principals"].append(
        {
            "external_subject": "other-user",
            "scope": SCOPE.model_dump(mode="json"),
            "tokens_valid_after": 7,
        }
    )
    path.write_text(json.dumps(data))
    original = IdentityPolicy.model_validate_json(path.read_text())
    keycloak_demo.revoke_sessions()
    updated = IdentityPolicy.model_validate_json(path.read_text())
    assert updated.principals[0].scope == original.principals[0].scope
    assert updated.principals[0].tokens_valid_after == int(NOW.timestamp())
    assert updated.revoked_jti == original.revoked_jti
    assert updated.principals[1] == original.principals[1]
    assert path.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(keycloak_demo.time, "time", lambda: NOW.timestamp() - 100)
    keycloak_demo.revoke_sessions()
    assert IdentityPolicy.model_validate_json(path.read_text()).principals == updated.principals
    path.write_text("broken private canary")
    with pytest.raises(ValueError):
        keycloak_demo.revoke_sessions()
    assert path.read_text() == "broken private canary"
    assert "canary" not in capsys.readouterr().out


@pytest.mark.parametrize("cutoff", [-1, True, "1", 1.5])
def test_cutoff_contract_rejects_invalid_input(tmp_path, cutoff):
    data = json.loads(policy_file(tmp_path).read_text())
    data["principals"][0]["tokens_valid_after"] = cutoff
    with pytest.raises(ValueError):
        IdentityPolicy.model_validate(data)


def test_exactly_one_key_source_and_startup_failure(provider, tmp_path):
    from tests.test_identity import ISSUER as TOKEN_ISSUER

    source, state = provider
    policy = policy_file(tmp_path)
    with pytest.raises(ValueError):
        JWTIdentity(TOKEN_ISSUER, AUDIENCE, None, policy)
    with pytest.raises(ValueError):
        JWTIdentity(TOKEN_ISSUER, AUDIENCE, tmp_path / "unused.json", policy, key_source=source)
    state["fail"] = True
    with pytest.raises(IdentityUnavailable):
        JWTIdentity(TOKEN_ISSUER, AUDIENCE, None, policy, key_source=source)


def test_failed_operator_write_preserves_existing_policy(tmp_path, monkeypatch):
    from tools import keycloak_demo

    monkeypatch.setattr(keycloak_demo, "DIRECTORY", tmp_path)
    path = policy_file(tmp_path)
    original = path.read_bytes()
    (tmp_path / "login.json").write_text(json.dumps({"subject": "external-user"}))

    def fail_write(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(keycloak_demo, "write_private", fail_write)
    with pytest.raises(OSError):
        keycloak_demo.revoke_sessions()
    assert path.read_bytes() == original
