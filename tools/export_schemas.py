"""Run from repository root after syncing the package."""

import json
from pathlib import Path

from aegisflow import contracts

for name in ("Request", "Scenario", "Case", "Task", "Evidence", "AuditEvent"):
    model = getattr(contracts, name)
    Path(f"schemas/{name}.schema.json").write_text(
        json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    )
