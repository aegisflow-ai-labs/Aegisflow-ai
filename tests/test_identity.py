import json
import secrets
from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from aegisflow.api import create_app, token_digest
from aegisflow.contracts import Scope
from aegisflow.identity import (
    IdentityPolicy,
    IdentityUnavailable,
    JWTIdentity,
    PrincipalBinding,
    Unauthenticated,
)
from aegisflow.scenario import generate
from aegisflow.store import Store
from tests.access_helpers import access_for

NOW = datetime(2026, 11, 1, 10, tzinfo=UTC)
SCOPE = Scope(tenant_id="demo", subject_id="local-demo", permissions={"read", "investigate"})
ISSUER = "https://issuer.example.test"
AUDIENCE = "aegisflow-api"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(key, kid="key-1"):
    return {
        **jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True),
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
    }


@pytest.fixture
def identity(tmp_path, signing_key):
    keys = tmp_path / "keys.json"
    principals = tmp_path / "principals.json"
    keys.write_text(json.dumps({"keys": [public_jwk(signing_key)]}))
    principals.write_text(
        IdentityPolicy(
            revision="test-1",
            principals=(PrincipalBinding(external_subject="external-user", scope=SCOPE),),
        ).model_dump_json()
    )
    return JWTIdentity(ISSUER, AUDIENCE, keys, principals, clock=lambda: NOW)


def signed(key, claims=None, headers=None):
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "external-user",
        "iat": int(NOW.timestamp()),
        "nbf": int(NOW.timestamp()),
        "exp": int(NOW.timestamp()) + 600,
        "jti": "token-1",
        "client_id": "test-client",
    }
    payload.update(claims or {})
    return jwt.encode(
        payload,
        key,
        algorithm="RS256",
        headers={"typ": "at+jwt", "kid": "key-1", **(headers or {})},
    )


def test_signed_token_uses_server_permissions_not_claims(identity, signing_key):
    token = signed(signing_key, {"tenant_id": "other", "permissions": ["admin"], "scope": "admin"})
    assert identity.authenticate("Bearer " + token) == SCOPE


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://wrong.test"},
        {"aud": "other-api"},
        {"sub": "unknown"},
        {"exp": int(NOW.timestamp())},
        {"nbf": int(NOW.timestamp()) + 1},
        {"iat": int(NOW.timestamp()) + 1},
        {"exp": int(NOW.timestamp()) + 901},
        {"iat": True},
        {"nbf": "123"},
        {"exp": float(NOW.timestamp()) + 10},
        {"client_id": ""},
        {"jti": ""},
        {"sub": ""},
    ],
)
def test_invalid_claims_are_rejected(identity, signing_key, claims):
    with pytest.raises(Unauthenticated):
        identity.authenticate("Bearer " + signed(signing_key, claims))


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "exp", "iat", "nbf", "jti", "client_id"])
def test_required_claims(identity, signing_key, claim):
    payload = jwt.decode(signed(signing_key), options={"verify_signature": False})
    del payload[claim]
    token = jwt.encode(
        payload, signing_key, algorithm="RS256", headers={"kid": "key-1", "typ": "at+jwt"}
    )
    with pytest.raises(Unauthenticated):
        identity.authenticate("Bearer " + token)


@pytest.mark.parametrize(
    "headers",
    [
        {"typ": "JWT"},
        {"kid": "unknown"},
        {"kid": ""},
        {"jku": "https://attacker.test/keys"},
        {"x5u": "http://127.0.0.1:1/secret"},
        {"jwk": {}},
        {"crit": ["custom"]},
    ],
)
def test_untrusted_header_cannot_choose_type_key_or_network(identity, signing_key, headers):
    with pytest.raises(Unauthenticated):
        identity.authenticate("Bearer " + signed(signing_key, headers=headers))


def test_none_hmac_tampering_and_bad_input(identity, signing_key):
    good = signed(signing_key)
    payload = jwt.decode(good, options={"verify_signature": False})
    unsigned = jwt.encode(
        payload, key="", algorithm="none", headers={"kid": "key-1", "typ": "at+jwt"}
    )
    hmac = jwt.encode(
        payload,
        key=secrets.token_bytes(32),
        algorithm="HS256",
        headers={"kid": "key-1", "typ": "at+jwt"},
    )
    parts = good.split(".")
    damaged = ".".join([parts[0], parts[1], ("A" if parts[2][0] != "A" else "B") + parts[2][1:]])
    for token in (unsigned, hmac, damaged, "bad", "x" * 8193):
        with pytest.raises(Unauthenticated):
            identity.authenticate("Bearer " + token)
    for header in (None, "", "Basic x", "Bearer "):
        with pytest.raises(Unauthenticated):
            identity.authenticate(header)


def test_live_subject_and_token_revocation(identity, signing_key):
    token = signed(signing_key)
    assert identity.authenticate("Bearer " + token) == SCOPE
    original = identity.principals_file.read_text()
    identity.principals_file.write_text(
        IdentityPolicy(revision="revoke-subject", principals=()).model_dump_json()
    )
    with pytest.raises(Unauthenticated):
        identity.authenticate("Bearer " + token)
    policy = json.loads(original)
    policy["revoked_jti"] = ["token-1"]
    identity.principals_file.write_text(json.dumps(policy))
    with pytest.raises(Unauthenticated):
        identity.authenticate("Bearer " + token)


def test_key_rotation_reload_and_no_stale_fallback(identity, signing_key):
    token = signed(signing_key)
    old = identity.jwks_file.read_text()
    identity.jwks_file.write_text(json.dumps({"keys": [public_jwk(signing_key, "key-2")]}))
    with pytest.raises(Unauthenticated):
        identity.authenticate("Bearer " + token)
    assert identity.authenticate("Bearer " + signed(signing_key, headers={"kid": "key-2"})) == SCOPE
    identity.jwks_file.write_text("{bad")
    with pytest.raises(IdentityUnavailable):
        identity.authenticate("Bearer " + token)
    identity.jwks_file.write_text(old)
    assert identity.authenticate("Bearer " + token) == SCOPE


def test_bad_trusted_config_fails_closed(identity, signing_key):
    identity.principals_file.unlink()
    with pytest.raises(IdentityUnavailable):
        identity.authenticate("Bearer " + signed(signing_key))
    with pytest.raises(IdentityUnavailable):
        JWTIdentity(ISSUER, AUDIENCE, identity.jwks_file, identity.principals_file)


def test_duplicate_keys_and_private_material_rejected(identity, signing_key):
    key = public_jwk(signing_key)
    for keys in ([key, key], [{**key, "d": "private-canary"}]):
        identity.jwks_file.write_text(json.dumps({"keys": keys}))
        with pytest.raises(IdentityUnavailable):
            identity._load()


def test_jwt_http_mode_has_no_static_credential_fallback(identity, signing_key, tmp_path):
    store = Store(tmp_path / "identity.db")
    with pytest.raises(ValueError):
        create_app(
            store,
            {token_digest("old-dev-token"): SCOPE},
            (generate(),),
            source_access=access_for(SCOPE),
            identity=identity,
        )
    app = create_app(store, {}, (generate(),), source_access=access_for(SCOPE), identity=identity)
    body = {"order_id": "PO-001", "as_of": "2026-11-01T18:00:00Z"}
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + signed(signing_key), "Idempotency-Key": "jwt-1"}
        result = client.post("/v1/cases", json=body, headers=headers)
        assert result.status_code == 201
        case = result.json()
        assert case["tenant_id"] == SCOPE.tenant_id
        assert (
            client.post(
                "/v1/cases", json=body, headers={**headers, "Authorization": "Bearer old-dev-token"}
            ).status_code
            == 401
        )
        identity.principals_file.write_text(
            IdentityPolicy(revision="revoked", principals=()).model_dump_json()
        )
        assert client.get("/v1/cases/" + case["case_id"], headers=headers).status_code == 401
        identity.principals_file.write_text("private-canary")
        response = client.get("/v1/cases/" + case["case_id"], headers=headers)
        assert response.status_code == 503 and "private-canary" not in response.text


def test_one_command_demo_and_environment_factory(tmp_path, monkeypatch):
    import subprocess
    import sys
    from pathlib import Path

    from aegisflow.access import SourceAccess
    from aegisflow.api import from_environment

    directory = tmp_path / "demo"
    result = subprocess.run(
        [
            sys.executable,
            str(Path("tools/jwt_demo.py").resolve()),
            "--setup-only",
            "--directory",
            str(directory),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    header = (directory / "headers.txt").read_text().splitlines()[0].removeprefix("Authorization: ")
    assert header not in result.stdout + result.stderr
    assert not any(p.suffix == ".pem" for p in directory.iterdir())
    for file in directory.iterdir():
        assert file.stat().st_mode & 0o777 == 0o600
    monkeypatch.setenv("AEGISFLOW_AUTH_MODE", "jwt")
    monkeypatch.setenv("AEGISFLOW_JWT_ISSUER", "https://aegisflow.invalid/local-demo")
    monkeypatch.setenv("AEGISFLOW_JWT_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("AEGISFLOW_JWKS_FILE", str(directory / "jwks.json"))
    monkeypatch.setenv("AEGISFLOW_PRINCIPALS_FILE", str(directory / "principals.json"))
    monkeypatch.setenv("AEGISFLOW_SOURCE_ACL_FILE", str(directory / "source-acl.json"))
    monkeypatch.setenv(
        "AEGISFLOW_SCENARIO_FILE", str(Path("fixtures/supply-delay-v1.json").resolve())
    )
    monkeypatch.setenv("AEGISFLOW_DB", str(directory / "cases.db"))
    monkeypatch.delenv("AEGISFLOW_DATABASE_URL", raising=False)
    # There is no development AUTH_FILE: JWT mode must not require or fall back to it.
    monkeypatch.delenv("AEGISFLOW_AUTH_FILE", raising=False)
    with TestClient(from_environment()) as client:
        headers = {"Authorization": header, "Idempotency-Key": "demo-1"}
        response = client.post(
            "/v1/cases",
            json={"order_id": "PO-001", "as_of": "2026-11-01T18:00:00Z"},
            headers=headers,
        )
        assert response.status_code == 201
        assert SourceAccess(directory / "source-acl.json").load().grants
    monkeypatch.setenv("AEGISFLOW_AUTH_MODE", "typo")
    with pytest.raises(ValueError):
        from_environment()
    monkeypatch.setenv("AEGISFLOW_AUTH_MODE", "jwt")
    monkeypatch.delenv("AEGISFLOW_JWKS_FILE")
    with pytest.raises(KeyError):
        from_environment()


def test_weak_key_and_exact_expiry_boundary(identity, signing_key):
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    original = identity.jwks_file.read_text()
    identity.jwks_file.write_text(json.dumps({"keys": [public_jwk(weak)]}))
    with pytest.raises(IdentityUnavailable):
        identity._load()
    identity.jwks_file.write_text(original)
    assert (
        identity.authenticate("Bearer " + signed(signing_key, {"exp": int(NOW.timestamp()) + 1}))
        == SCOPE
    )
    identity.clock = lambda: NOW.replace(tzinfo=None)
    with pytest.raises(IdentityUnavailable):
        identity.authenticate("Bearer " + signed(signing_key))


def test_identity_schemas():
    from pathlib import Path

    from aegisflow.identity import PublicKeys

    for name, model in (("IdentityPolicy", IdentityPolicy), ("PublicKeys", PublicKeys)):
        assert (
            json.loads(Path(f"schemas/{name}.schema.json").read_text()) == model.model_json_schema()
        )


def test_identity_policy_duplicate_subject_and_invalid_scope_rejected():
    binding = PrincipalBinding(external_subject="user", scope=SCOPE)
    with pytest.raises(ValueError):
        IdentityPolicy(revision="bad", principals=(binding, binding))
    with pytest.raises(ValueError):
        PrincipalBinding.model_validate(
            {
                "external_subject": "user",
                "scope": {
                    "tenant_id": "demo",
                    "subject_id": "local-demo",
                    "permissions": ["admin"],
                },
            }
        )
