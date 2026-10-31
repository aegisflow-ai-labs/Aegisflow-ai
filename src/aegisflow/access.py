"""Server-owned, exact-match source authorization for the synthetic HTTP pilot."""

from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from .contracts import Contract, Identifier, Scope
from .store import NotFound

SourceURI = Annotated[str, Field(min_length=1, max_length=1024)]


class SourceGrant(Contract):
    tenant_id: Identifier
    subject_id: Identifier
    source_uris: frozenset[SourceURI]


class SourcePolicy(Contract):
    revision: Identifier
    grants: tuple[SourceGrant, ...]

    @model_validator(mode="after")
    def unique_principals(self) -> "SourcePolicy":
        keys = [(grant.tenant_id, grant.subject_id) for grant in self.grants]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate source policy principal")
        return self

    def authorize(self, scope: Scope, source_uris: tuple[str, ...]) -> None:
        allowed = next(
            (
                g.source_uris
                for g in self.grants
                if g.tenant_id == scope.tenant_id and g.subject_id == scope.subject_id
            ),
            frozenset(),
        )
        if not source_uris or not set(source_uris).issubset(allowed):
            # Do not disclose whether a denied source exists.
            raise NotFound("NOT_FOUND")


class SourcePolicyUnavailable(Exception):
    pass


class SourceAccess:
    def __init__(self, policy: SourcePolicy | Path) -> None:
        self._policy = policy

    def load(self) -> SourcePolicy:
        """One immutable snapshot per HTTP request; never reuse a stale file on failure."""
        if isinstance(self._policy, SourcePolicy):
            return self._policy
        try:
            with self._policy.open("rb") as file:
                payload = file.read(1_000_001)
            if len(payload) > 1_000_000:
                raise ValueError("Source policy too large")
            return SourcePolicy.model_validate_json(payload)
        except (OSError, ValueError) as error:
            raise SourcePolicyUnavailable("Source policy unavailable") from error
