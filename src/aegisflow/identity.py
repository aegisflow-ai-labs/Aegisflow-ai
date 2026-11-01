"""Narrow RS256 access-token verifier; provider login/discovery are separate work."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

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


class JWTIdentity:
    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_file: Path,
        principals_file: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not issuer or not audience or len(issuer) > 1024 or len(audience) > 256:
            raise ValueError("Explicit issuer and audience required")
        self.issuer = issuer
        self.audience = audience
        self.jwks_file = jwks_file
        self.principals_file = principals_file
        self.clock = clock or (lambda: datetime.now(UTC))
        self._load()  # Fail startup rather than downgrade authentication.

    def _load(self) -> tuple[dict[str, jwt.PyJWK], IdentityPolicy]:
        try:
            public = PublicKeys.model_validate_json(load_json(self.jwks_file))
            keys = {}
            for item in public.keys:
                key = jwt.PyJWK.from_dict(item.model_dump(mode="json"), algorithm="RS256")
                if not 2048 <= key.key.key_size <= 8192:
                    raise ValueError("Unsupported RSA size")
                keys[item.kid] = key
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
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") not in ("at+jwt", "application/at+jwt")
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
                    "require": ["iss", "aud", "sub", "exp", "iat", "nbf", "jti", "client_id"],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            now = self.clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise IdentityUnavailable("Timezone-aware verification clock required")
            numeric = [claims[name] for name in ("iat", "nbf", "exp")]
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
            for name in ("sub", "jti", "client_id"):
                if not isinstance(claims[name], str) or not 1 <= len(claims[name]) <= 256:
                    raise Unauthenticated()
            if claims["jti"] in policy.revoked_jti:
                raise Unauthenticated()
            for principal in policy.principals:
                if principal.external_subject == claims["sub"]:
                    return principal.scope
        except (jwt.PyJWTError, ValueError, TypeError, RecursionError) as error:
            raise Unauthenticated() from error
        raise Unauthenticated()
