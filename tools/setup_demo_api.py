"""Generate local development credentials without printing secrets."""

import json
import os
import secrets
from pathlib import Path

from aegisflow.access import SourceGrant, SourcePolicy
from aegisflow.api import token_digest
from aegisflow.contracts import Scope
from aegisflow.scenario import generate

Path("work").mkdir(exist_ok=True)
token = secrets.token_urlsafe(32)
scope = Scope(tenant_id="demo", subject_id="local-demo", permissions={"read", "investigate"})
for name, content in (
    (
        "work/source-acl.json",
        SourcePolicy(
            revision="demo-v1",
            grants=(
                SourceGrant(
                    tenant_id=scope.tenant_id,
                    subject_id=scope.subject_id,
                    source_uris=generate().input_source_uris(),
                ),
            ),
        ).model_dump_json(indent=2),
    ),
    ("work/api-token", token),
    ("work/api-auth.json", json.dumps({token_digest(token): scope.model_dump(mode="json")})),
):
    with os.fdopen(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
        file.write(content)
print("Yerel kimlik dosyaları work/ içinde oluşturuldu; var olan dosyalar üzerine yazılmaz.")
