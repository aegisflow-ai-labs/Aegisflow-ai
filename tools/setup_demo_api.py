"""Generate local development credentials without printing secrets."""

import json
import os
import secrets
from pathlib import Path

from aegisflow.api import token_digest
from aegisflow.contracts import Scope

Path("work").mkdir(exist_ok=True)
token = secrets.token_urlsafe(32)
scope = Scope(tenant_id="demo", subject_id="local-demo", permissions={"read", "investigate"})
for name, content in (
    ("work/api-token", token),
    ("work/api-auth.json", json.dumps({token_digest(token): scope.model_dump(mode="json")})),
):
    with os.fdopen(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
        file.write(content)
print("Yerel kimlik dosyaları work/ içinde oluşturuldu; var olan dosyalar üzerine yazılmaz.")
