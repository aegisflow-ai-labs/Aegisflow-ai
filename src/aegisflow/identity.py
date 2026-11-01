"""RS256 verification profiles; provider transport and browser sessions stay separate."""

import hashlib
import secrets
from base64 import urlsafe_b64encode
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import jwt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import Contract, Identifier, Scope

BoundedString = Annotated[str, Field(min_length=1, max_length=256)]


class PublicJWK(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kty: Literal["RSA"]
    use: Literal["sig"]
    alg: Literal["RS256"]
    kid: Identifier
    n: Annotated[str, Field(min_length=1, max_length=2048)]
    e: Annotated[str, Field(min_length=1, max_length=16)]
    key_ops: tuple[Literal["verify"]] = ("verify",)


class PublicKeys(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    keys: Annotated[tuple[PublicJWK, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def unique_keys(self) -> "PublicKeys":
        if len({key.kid for key in self.keys}) != len(self.keys):
            raise ValueError("Duplicate key identifier")
        return self


class PrincipalBinding(Contract):
    external_subject: BoundedString
    scope: Scope
    tokens_valid_after: Annotated[int, Field(strict=True, ge=0)] = 0


class IdentityPolicy(Contract):
    revision: Identifier
    principals: tuple[PrincipalBinding, ...]
    revoked_jti: frozenset[BoundedString] = frozenset()

    @model_validator(mode="after")
    def unique_principals(self) -> "IdentityPolicy":
        if len({p.external_subject for p in self.principals}) != len(self.principals):
            raise ValueError("Duplicate external subject")
        return self


class Unauthenticated(Exception):
    pass


class IdentityUnavailable(Exception):
    pass


def load_json(path: Path) -> str:
    with path.open("rb") as file:
        payload = file.read(65537)
    if len(payload) > 65536:
        raise ValueError("Identity configuration too large")
    return payload.decode("utf-8")


def verification_keys(public: PublicKeys) -> dict[str, jwt.PyJWK]:
    keys = {}
    for item in public.keys:
        key = jwt.PyJWK.from_dict(item.model_dump(mode="json"), algorithm="RS256")
        if not 2048 <= key.key.key_size <= 8192:
            raise ValueError("Unsupported RSA size")
        keys[item.kid] = key
    return keys


class JWTIdentity:
    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_file: Path | None,
        principals_file: Path,
        clock: Callable[[], datetime] | None = None,
        profile: Literal["rfc9068", "keycloak"] = "rfc9068",
        client_id: str | None = None,
        key_source: Callable[[], PublicKeys] | None = None,
    ) -> None:
        if not issuer or not audience or len(issuer) > 1024 or len(audience) > 256:
            raise ValueError("Explicit issuer and audience required")
        if profile not in ("rfc9068", "keycloak") or (profile == "keycloak" and not client_id):
            raise ValueError("Explicit Keycloak client required")
        if (jwks_file is None) == (key_source is None):
            raise ValueError("Exactly one trusted public-key source required")
        self.key_source = key_source
        self.profile = profile
        self.client_id = client_id
        self.issuer = issuer
        self.audience = audience
        self.jwks_file = jwks_file
        self.principals_file = principals_file
        self.clock = clock or (lambda: datetime.now(UTC))
        self._load()  # Fail startup rather than downgrade authentication.

    def _load(self) -> tuple[dict[str, jwt.PyJWK], IdentityPolicy]:
        try:
            if self.key_source is not None:
                public = self.key_source()
            elif self.jwks_file is not None:
                public = PublicKeys.model_validate_json(load_json(self.jwks_file))
            else:
                raise IdentityUnavailable("Trusted public-key source unavailable")
            keys = verification_keys(public)
            policy = IdentityPolicy.model_validate_json(load_json(self.principals_file))
            return keys, policy
        except (OSError, ValueError, jwt.PyJWTError) as error:
            raise IdentityUnavailable("Identity configuration unavailable") from error

    def authenticate(self, authorization: str | None) -> Scope:
        if not authorization:
            raise Unauthenticated()
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 8192:
            raise Unauthenticated()
        claims, policy = self._verify_access(token)
        for principal in policy.principals:
            if principal.external_subject == claims["sub"]:
                if principal.tokens_valid_after and claims["iat"] <= principal.tokens_valid_after:
                    raise Unauthenticated()
                return principal.scope
        raise Unauthenticated()

    def _verify_access(self, token: str) -> tuple[dict[str, Any], IdentityPolicy]:
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ")
                not in (
                    ("JWT",) if self.profile == "keycloak" else ("at+jwt", "application/at+jwt")
                )
                or any(name in header for name in ("jku", "jwk", "x5u", "x5c", "crit"))
            ):
                raise Unauthenticated()
            keys, policy = self._load()
            kid = header.get("kid")
            if not isinstance(kid, str) or kid not in keys:
                raise Unauthenticated()
            claims = jwt.decode(
                token,
                keys[kid],
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "require": ["iss", "aud", "sub", "exp", "iat", "jti"]
                    + (["azp", "typ"] if self.profile == "keycloak" else ["nbf", "client_id"]),
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            now = self.clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise IdentityUnavailable("Timezone-aware verification clock required")
            if self.profile == "keycloak" and (
                claims.get("typ") != "Bearer" or claims.get("azp") != self.client_id
            ):
                raise Unauthenticated()
            numeric = [claims["iat"], claims.get("nbf", claims["iat"]), claims["exp"]]
            if any(type(value) is not int for value in numeric):
                raise Unauthenticated()
            issued, not_before, expiry = numeric
            if (
                issued > now.timestamp()
                or not_before > now.timestamp()
                or expiry <= now.timestamp()
                or expiry <= issued
                or expiry - issued > 900
                or not_before >= expiry
            ):
                raise Unauthenticated()
            for name in ("sub", "jti", "azp" if self.profile == "keycloak" else "client_id"):
                if not isinstance(claims[name], str) or not 1 <= len(claims[name]) <= 256:
                    raise Unauthenticated()
            if claims["jti"] in policy.revoked_jti:
                raise Unauthenticated()
            return claims, policy
        except (jwt.PyJWTError, ValueError, TypeError, RecursionError) as error:
            raise Unauthenticated() from error

    def verify_login(self, access_token: str, id_token: str, nonce: str) -> tuple[Scope, int]:
        if self.profile != "keycloak":
            raise Unauthenticated()
        scope = self.authenticate("Bearer " + access_token)
        access_claims, _ = self._verify_access(access_token)
        try:
            if len(id_token) > 8192:
                raise Unauthenticated()
            header = jwt.get_unverified_header(id_token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") != "JWT"
                or any(key in header for key in ("jku", "jwk", "x5u", "x5c", "crit"))
            ):
                raise Unauthenticated()
            keys, _ = self._load()
            kid = header.get("kid")
            if not isinstance(kid, str) or kid not in keys:
                raise Unauthenticated()
            claims = jwt.decode(
                id_token,
                keys[kid],
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.client_id,
                options={
                    "require": ["iss", "aud", "sub", "exp", "iat", "nonce"],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            now = self.clock().timestamp()
            if (
                type(claims["iat"]) is not int
                or type(claims["exp"]) is not int
                or claims["iat"] > now
                or claims["exp"] <= now
                or claims["exp"] <= claims["iat"]
                or claims["exp"] - claims["iat"] > 900
                or claims["sub"] != access_claims["sub"]
                or not isinstance(claims["nonce"], str)
                or not secrets.compare_digest(claims["nonce"].encode(), nonce.encode())
                or ("azp" in claims and claims["azp"] != self.client_id)
                or (
                    isinstance(claims["aud"], list)
                    and len(claims["aud"]) > 1
                    and claims.get("azp") != self.client_id
                )
            ):
                raise Unauthenticated()
            if "nbf" in claims and (type(claims["nbf"]) is not int or claims["nbf"] > now):
                raise Unauthenticated()
            if "at_hash" in claims:
                expected = (
                    urlsafe_b64encode(hashlib.sha256(access_token.encode()).digest()[:16])
                    .rstrip(b"=")
                    .decode()
                )
                if not isinstance(claims["at_hash"], str) or not secrets.compare_digest(
                    claims["at_hash"].encode(), expected.encode()
                ):
                    raise Unauthenticated()
            return scope, min(int(claims["exp"]), int(access_claims["exp"]))
        except (jwt.PyJWTError, ValueError, TypeError, RecursionError) as error:
            raise Unauthenticated() from error
