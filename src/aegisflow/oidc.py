"""Local-only Authorization Code + S256 PKCE flow; bounded in-memory sessions."""

import hashlib
import json
import secrets
import threading
import time
from base64 import urlsafe_b64encode
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jwt

from .contracts import Scope
from .identity import (
    IdentityUnavailable,
    JWTIdentity,
    PublicKeys,
    Unauthenticated,
    verification_keys,
)


class LoginRejected(Exception):
    pass


class LoginCapacity(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class LocalKeycloak:
    def __init__(self, issuer: str, client_id: str, callback: str) -> None:
        source = urlsplit(issuer)
        target = urlsplit(callback)
        if (
            source.scheme != "http"
            or source.hostname != "127.0.0.1"
            or source.port != 8080
            or source.path != "/realms/aegisflow-local"
            or source.query
            or source.fragment
            or source.username
            or target.scheme != "http"
            or target.hostname != "127.0.0.1"
            or target.port != 8000
            or target.path != "/auth/callback"
            or target.query
            or target.fragment
            or target.username
            or client_id != "aegisflow-local-browser"
        ):
            raise ValueError("This adapter accepts only the fixed local pilot endpoints")
        self.issuer, self.client_id, self.callback = issuer, client_id, callback

    def fetch(self, path: str, data: dict[str, str] | None = None) -> dict[str, object]:
        # All paths are application constants; redirects and token-controlled URLs are forbidden.
        if path not in (
            "/.well-known/openid-configuration",
            "/protocol/openid-connect/certs",
            "/protocol/openid-connect/token",
        ):
            raise ValueError("Unknown local provider endpoint")
        payload = urlencode(data).encode() if data is not None else None
        req = Request(self.issuer + path, data=payload, headers={"Accept": "application/json"})
        try:
            with build_opener(NoRedirect()).open(req, timeout=5) as response:
                body = response.read(65537)
            if len(body) > 65536:
                raise ValueError("Provider response too large")
            result = json.loads(body)
            if not isinstance(result, dict):
                raise TypeError("Invalid provider response")
            return result
        except HTTPError as error:
            if path == "/protocol/openid-connect/token" and error.code in (400, 401):
                raise LoginRejected() from error
            raise IdentityUnavailable("Local identity provider unavailable") from error
        except (URLError, OSError, ValueError, TypeError, RecursionError) as error:
            raise IdentityUnavailable("Local identity provider unavailable") from error

    def exchange(self, code: str, verifier: str) -> dict[str, object]:
        return self.fetch(
            "/protocol/openid-connect/token",
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "redirect_uri": self.callback,
                "code": code,
                "code_verifier": verifier,
            },
        )


class ProviderKeys:
    """Fixed-source, demand-refreshed JWKS; no token-triggered network refresh."""

    def __init__(
        self, provider: LocalKeycloak, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.provider, self.clock = provider, clock
        self._public: PublicKeys | None = None
        self._expires = 0.0
        self._retry_at = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> PublicKeys:
        with self._lock:
            now = self.clock()
            if self._public is not None and now < self._expires:
                return self._public
            if now < self._retry_at:
                raise IdentityUnavailable("Public-key refresh cooling down")
            try:
                raw = self.provider.fetch("/protocol/openid-connect/certs")
                items = raw.get("keys")
                if not isinstance(items, list) or not 1 <= len(items) <= 16:
                    raise ValueError("Invalid provider key set")
                accepted = []
                for item in items:
                    if not isinstance(item, dict):
                        raise TypeError("Invalid provider key")
                    # Keycloak also publishes encryption keys and certificate metadata.
                    # Strip only public certificate metadata, never private key material.
                    if any(k in item for k in ("d", "p", "q", "dp", "dq", "qi", "oth", "k")):
                        raise ValueError("Private key material forbidden")
                    if item.get("alg") == "RS256" and item.get("use") == "sig":
                        accepted.append(
                            {k: v for k, v in item.items() if k not in ("x5c", "x5t", "x5t#S256")}
                        )
                public = PublicKeys.model_validate({"keys": accepted})
                verification_keys(public)  # Validate key size/material before caching success.
            except (
                IdentityUnavailable,
                ValueError,
                TypeError,
                RecursionError,
                jwt.PyJWTError,
            ) as error:
                self._public = None
                self._retry_at = self.clock() + 5
                raise IdentityUnavailable("Trusted provider keys unavailable") from error
            self._public = public
            self._expires = now + 60
            self._retry_at = 0.0
            return public


@dataclass(frozen=True)
class Pending:
    binding: str
    verifier: str
    nonce: str
    expiry: float


@dataclass(frozen=True)
class Session:
    access: str
    csrf: str
    expiry: float


def hashed(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class BrowserLogin:
    def __init__(self, identity: JWTIdentity, provider: LocalKeycloak, capacity: int = 100) -> None:
        if (
            identity.profile != "keycloak"
            or identity.issuer != provider.issuer
            or identity.client_id != provider.client_id
            or capacity < 1
        ):
            raise ValueError("Browser login requires a matching local Keycloak identity")
        self.identity, self.provider, self.capacity = identity, provider, capacity
        self.pending: dict[str, Pending] = {}
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()

    def _prune(self) -> None:
        now = self.identity.clock().timestamp()
        self.pending = {k: v for k, v in self.pending.items() if v.expiry > now}
        self.sessions = {k: v for k, v in self.sessions.items() if v.expiry > now}

    def begin(self) -> tuple[str, str]:
        state, binding, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(4))
        with self.lock:
            self._prune()
            if len(self.pending) >= self.capacity:
                raise LoginCapacity()
            self.pending[hashed(state)] = Pending(
                hashed(binding), verifier, nonce, self.identity.clock().timestamp() + 300
            )
        challenge = (
            urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        )
        return self.provider.issuer + "/protocol/openid-connect/auth?" + urlencode(
            {
                "client_id": self.provider.client_id,
                "redirect_uri": self.provider.callback,
                "response_type": "code",
                "scope": "openid",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        ), binding

    def complete(self, state: str, binding: str, code: str, issuer: str) -> str:
        if (
            not state
            or not binding
            or not code
            or max(len(state), len(binding), len(code)) > 2048
            or issuer != self.provider.issuer
        ):
            raise LoginRejected()
        with self.lock:
            self._prune()
            pending = self.pending.get(hashed(state))
            if pending is None or not secrets.compare_digest(pending.binding, hashed(binding)):
                raise LoginRejected()
            del self.pending[hashed(state)]  # Single-use even when exchange fails.
        result = self.provider.exchange(code, pending.verifier)
        access, id_token = result.get("access_token"), result.get("id_token")
        if (
            not isinstance(access, str)
            or not isinstance(id_token, str)
            or result.get("token_type") != "Bearer"
        ):
            raise LoginRejected()
        try:
            _, expiry = self.identity.verify_login(access, id_token, pending.nonce)
        except Unauthenticated as error:
            raise LoginRejected() from error
        sid = secrets.token_urlsafe(32)
        with self.lock:
            self._prune()
            if len(self.sessions) >= self.capacity:
                raise LoginCapacity()
            self.sessions[hashed(sid)] = Session(access, secrets.token_urlsafe(32), expiry)
        return sid

    def user(self, sid: str | None) -> tuple[Scope, Session]:
        if not sid or len(sid) > 128:
            raise Unauthenticated()
        with self.lock:
            self._prune()
            session = self.sessions.get(hashed(sid))
        if session is None:
            raise Unauthenticated()
        try:
            scope = self.identity.authenticate("Bearer " + session.access)
        except Unauthenticated:
            with self.lock:
                self.sessions.pop(hashed(sid), None)
            raise
        return scope, session

    def logout(self, sid: str, csrf: str) -> None:
        _, session = self.user(sid)
        if not secrets.compare_digest(session.csrf.encode(), csrf.encode()):
            raise LoginRejected()
        with self.lock:
            self.sessions.pop(hashed(sid), None)
