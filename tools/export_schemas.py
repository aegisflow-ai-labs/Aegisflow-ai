"""Run from repository root after syncing the package."""

import json
from pathlib import Path

from aegisflow import contracts
from aegisflow.access import SourcePolicy
from aegisflow.identity import IdentityPolicy, PublicKeys
from aegisflow.triage import Triage

for name in (
    "Request",
    "Scenario",
    "Case",
    "Task",
    "Evidence",
    "AuditEvent",
    "Action",
    "ActionPayload",
):
    model = getattr(contracts, name)
    Path(f"schemas/{name}.schema.json").write_text(
        json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    )

Path("schemas/SourcePolicy.schema.json").write_text(
    json.dumps(SourcePolicy.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
)

for name, model in (
    ("IdentityPolicy", IdentityPolicy),
    ("PublicKeys", PublicKeys),
    ("Triage", Triage),
):
    Path(f"schemas/{name}.schema.json").write_text(
        json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    )
