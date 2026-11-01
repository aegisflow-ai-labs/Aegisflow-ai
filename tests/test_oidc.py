import hashlib
import json
from base64 import urlsafe_b64encode
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from aegisflow.access import SourceAccess
from aegisflow.api import create_app
from aegisflow.identity import IdentityPolicy, JWTIdentity, PrincipalBinding, Unauthenticated
from aegisflow.login_ui import COOKIE
from aegisflow.oidc import BrowserLogin, LocalKeycloak, LoginCapacity, LoginRejected
from aegisflow.scenario import generate
from aegisflow.store import Store
from tests.access_helpers import access_for
from tests.test_identity import AUDIENCE, NOW, SCOPE, public_jwk

ISSUER = "http://127.0.0.1:8080/realms/aegisflow-local"
CLIENT = "aegisflow-local-browser"
CALLBACK = "http://127.0.0.1:8000/auth/callback"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def flow(tmp_path, signing_key, monkeypatch):
    keys, principals = tmp_path / "keys.json", tmp_path / "principals.json"
    keys.write_text(json.dumps({"keys": [public_jwk(signing_key)]}))
    principals.write_text(
        IdentityPolicy(
            revision="test-1",
            principals=(PrincipalBinding(external_subject="external-user", scope=SCOPE),),
        ).model_dump_json()
    )
    verifier = JWTIdentity(
        ISSUER,
        AUDIENCE,
        keys,
        principals,
        clock=lambda: NOW,
        profile="keycloak",
        client_id=CLIENT,
    )
    provider = LocalKeycloak(ISSUER, CLIENT, CALLBACK)
    login = BrowserLogin(verifier, provider, capacity=2)

    def exchange(code, secret):
        pending = next(iter(login.pending.values()), None)
        # The consumed pending flow is supplied by the test's authorization request.
        assert code == "code" and len(secret) >= 43 and pending is None
        access = encode(
            signing_key, {"aud": AUDIENCE, "jti": "token-1", "typ": "Bearer", "azp": CLIENT}
        )
        id_token = encode(signing_key, {"aud": CLIENT, "nonce": login.test_nonce})
        return {"access_token": access, "id_token": id_token, "token_type": "Bearer"}

    monkeypatch.setattr(provider, "exchange", exchange)
    return login


def encode(key, extra):
    return jwt.encode(
        {
            "iss": ISSUER,
            "sub": "external-user",
            "iat": int(NOW.timestamp()),
            "exp": int(NOW.timestamp()) + 600,
            **extra,
        },
        key,
        algorithm="RS256",
        headers={"kid": "key-1", "typ": "JWT"},
    )


def begin(flow):
    url, binding = flow.begin()
    args = parse_qs(urlsplit(url).query)
    flow.test_nonce = args["nonce"][0]
    pending = next(iter(flow.pending.values()))
    expected = (
        urlsafe_b64encode(hashlib.sha256(pending.verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert args["code_challenge"] == [expected]
    assert args["code_challenge_method"] == ["S256"]
    return args["state"][0], binding


def session(flow):
    state, binding = begin(flow)
    return flow.complete(state, binding, "code", ISSUER)


def test_pkce_browser_binding_and_single_use(flow):
    state, binding = begin(flow)
    for wrong in ("wrong", ""):
        with pytest.raises(LoginRejected):
            flow.complete(state, wrong, "code", ISSUER)
    with pytest.raises(LoginRejected):
        flow.complete(state, binding, "code", "https://evil.invalid")
    sid = flow.complete(state, binding, "code", ISSUER)
    assert flow.user(sid)[0] == SCOPE
    with pytest.raises(LoginRejected):
        flow.complete(state, binding, "code", ISSUER)
    with pytest.raises(LoginRejected):
        flow.logout(sid, "ş")
    flow.logout(sid, flow.user(sid)[1].csrf)
    with pytest.raises(Unauthenticated):
        flow.user(sid)


def test_expiry_and_capacity(flow):
    state, binding = begin(flow)
    flow.begin()
    with pytest.raises(LoginCapacity):
        flow.begin()
    flow.identity.clock = lambda: NOW.replace(hour=11)
    with pytest.raises(LoginRejected):
        flow.complete(state, binding, "code", ISSUER)
    assert flow.begin()


@pytest.mark.parametrize(
    "changes",
    [
        {"nonce": "wrong"},
        {"nonce": "ş"},
        {"sub": "different"},
        {"aud": "other"},
        {"exp": int(NOW.timestamp())},
        {"iat": True},
        {"azp": "wrong"},
        {"aud": [CLIENT, "other"]},
        {"at_hash": "wrong"},
        {"nbf": int(NOW.timestamp()) + 1},
    ],
)
def test_id_token_validation(flow, signing_key, changes):
    access = encode(signing_key, {"aud": AUDIENCE, "jti": "one", "typ": "Bearer", "azp": CLIENT})
    id_token = encode(signing_key, {"aud": CLIENT, "nonce": "nonce", **changes})
    with pytest.raises(Unauthenticated):
        flow.identity.verify_login(access, id_token, "nonce")


@pytest.mark.parametrize("changes", [{"typ": "ID"}, {"azp": "other"}, {"aud": CLIENT}])
def test_id_token_cannot_be_access_token(flow, signing_key, changes):
    token = encode(
        signing_key, {"aud": AUDIENCE, "jti": "one", "typ": "Bearer", "azp": CLIENT, **changes}
    )
    with pytest.raises(Unauthenticated):
        flow.identity.authenticate("Bearer " + token)


def test_browser_ui_csrf_idempotency_revocation_and_host(flow, tmp_path):
    policy_file = tmp_path / "acl.json"
    policy_file.write_text(access_for(SCOPE).load().model_dump_json())
    access = SourceAccess(policy_file)
    app = create_app(
        Store(tmp_path / "browser.db"),
        {},
        (generate(),),
        source_access=access,
        identity=flow.identity,
        browser_login=flow,
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/", headers={"Host": "evil.invalid"}).status_code == 400
        assert client.get("/").status_code == 200
        assert client.get("/auth/callback?code=x&state=x&iss=x").status_code == 400
        sid = session(flow)
        client.cookies.set(COOKIE, sid)
        home = client.get("/")
        csrf = flow.user(sid)[1].csrf
        assert "Ready to investigate." in home.text
        assert flow.user(sid)[1].access not in home.text
        assert "frame-ancestors 'none'" in home.headers["content-security-policy"]
        data = {"csrf": csrf, "key": "browser-1"}
        assert client.post("/demo/investigate", data={**data, "csrf": "ş"}).status_code == 403
        assert (
            client.post("/demo/investigate", data=data, headers={"Origin": "null"}).status_code
            == 403
        )
        assert (
            client.post(
                "/demo/investigate", data=data, headers={"Origin": "https://evil.invalid"}
            ).status_code
            == 403
        )
        result = client.post("/demo/investigate", data=data)
        assert result.status_code == 200 and "25200" in result.text
        assert client.post("/demo/investigate", data=data).text == result.text
        body = {"order_id": "PO-001", "as_of": "2026-11-01T18:00:00Z"}
        assert (
            client.post("/v1/cases", json=body, headers={"Idempotency-Key": "b-api"}).status_code
            == 403
        )
        api = client.post(
            "/v1/cases", json=body, headers={"Idempotency-Key": "b-api", "X-CSRF-Token": csrf}
        )
        assert api.status_code == 201
        policy_file.write_text(json.dumps({"revision": "revoked", "grants": []}))
        assert client.post("/demo/investigate", data=data).status_code == 403
        assert client.get("/v1/cases/" + api.json()["case_id"]).status_code == 404
        flow.identity.principals_file.write_text(
            IdentityPolicy(revision="revoked", principals=()).model_dump_json()
        )
        assert client.post("/demo/investigate", data=data).status_code == 401


def test_local_provider_rejects_external_endpoints():
    with pytest.raises(ValueError):
        LocalKeycloak("https://evil.invalid", CLIENT, CALLBACK)
    with pytest.raises(ValueError):
        LocalKeycloak(ISSUER, CLIENT, "http://evil.invalid/auth/callback")
    with pytest.raises(ValueError):
        LocalKeycloak(ISSUER, CLIENT, CALLBACK).fetch("/untrusted")


def test_callback_cookie_flags_logout_and_corrupt_policy(flow, tmp_path):
    app = create_app(
        Store(tmp_path / "cookies.db"),
        {},
        (generate(),),
        source_access=access_for(SCOPE),
        identity=flow.identity,
        browser_login=flow,
    )
    with TestClient(app, base_url="http://127.0.0.1:8000", follow_redirects=False) as client:
        start = client.get("/auth/login")
        assert start.status_code == 303
        assert (
            "HttpOnly" in start.headers["set-cookie"]
            and "SameSite=lax" in start.headers["set-cookie"]
        )
        query = parse_qs(urlsplit(start.headers["location"]).query)
        flow.test_nonce = query["nonce"][0]
        callback = client.get(
            "/auth/callback", params={"state": query["state"][0], "code": "code", "iss": ISSUER}
        )
        assert callback.status_code == 303
        assert "HttpOnly" in callback.headers["set-cookie"]
        assert callback.headers["referrer-policy"] == "no-referrer"
        sid = client.cookies.get(COOKIE)
        csrf = flow.user(sid)[1].csrf
        assert (
            client.get(
                "/auth/callback", params={"state": query["state"][0], "code": "code", "iss": ISSUER}
            ).status_code
            == 400
        )
        original = flow.identity.principals_file.read_text()
        flow.identity.principals_file.write_text("broken private canary")
        failed = client.get("/")
        assert failed.status_code == 503 and "canary" not in failed.text
        flow.identity.principals_file.write_text(original)
        assert (
            client.post("/auth/logout", data={"csrf": "wrong", "key": "logout"}).status_code == 403
        )
        logout = client.post("/auth/logout", data={"csrf": csrf, "key": "logout"})
        assert logout.status_code == 200 and "Application session ended." in logout.text
        assert ISSUER in logout.text
        with pytest.raises(Unauthenticated):
            flow.user(sid)


def test_failed_exchange_consumes_flow(flow, monkeypatch):
    state, binding = begin(flow)

    def reject(*args):
        raise LoginRejected()

    monkeypatch.setattr(flow.provider, "exchange", reject)
    with pytest.raises(LoginRejected):
        flow.complete(state, binding, "code", ISSUER)
    assert not flow.pending and not flow.sessions


def test_session_capacity_expiry_and_optional_token_hash(flow, signing_key):
    first = session(flow)
    second = session(flow)
    assert first != second
    with pytest.raises(LoginCapacity):
        session(flow)
    assert len(flow.sessions) == 2
    access = encode(signing_key, {"aud": AUDIENCE, "jti": "one", "typ": "Bearer", "azp": CLIENT})
    digest = urlsafe_b64encode(hashlib.sha256(access.encode()).digest()[:16]).rstrip(b"=").decode()
    id_token = encode(signing_key, {"aud": CLIENT, "nonce": "nonce", "at_hash": digest})
    assert flow.identity.verify_login(access, id_token, "nonce")[0] == SCOPE
    flow.identity.clock = lambda: NOW.replace(minute=10)
    with pytest.raises(Unauthenticated):
        flow.user(first)
    assert not flow.sessions


def test_helper_private_setup_preserves_credentials_and_rejects_partial(tmp_path, monkeypatch):
    from tools import keycloak_demo

    directory = tmp_path / "keycloak"
    monkeypatch.setattr(keycloak_demo, "DIRECTORY", directory)
    keycloak_demo.prepare()
    assert directory.stat().st_mode & 0o777 == 0o700
    for file in directory.iterdir():
        assert file.stat().st_mode & 0o777 == 0o600
    original = (directory / "login.json").read_bytes()
    keycloak_demo.prepare()
    assert (directory / "login.json").read_bytes() == original
    realm = json.loads((directory / "realm.json").read_text())
    client = realm["clients"][0]
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["redirectUris"] == [CALLBACK]
    assert not client["directAccessGrantsEnabled"] and not client["implicitFlowEnabled"]
    (directory / "login.txt").unlink()
    with pytest.raises(RuntimeError):
        keycloak_demo.prepare()
    assert (directory / "login.json").read_bytes() == original
