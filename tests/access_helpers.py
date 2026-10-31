from aegisflow.access import SourceAccess, SourceGrant, SourcePolicy
from aegisflow.contracts import Scope
from aegisflow.scenario import generate


def access_for(*scopes: Scope) -> SourceAccess:
    return SourceAccess(
        SourcePolicy(
            revision="test-v1",
            grants=tuple(
                SourceGrant(
                    tenant_id=s.tenant_id,
                    subject_id=s.subject_id,
                    source_uris=generate().input_source_uris(),
                )
                for s in scopes
            ),
        )
    )
