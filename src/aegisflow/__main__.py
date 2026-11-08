"""Local synthetic-only CLI. OS user owns the local trust boundary."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from .contracts import Request, Scenario, Scope
from .evaluation import evaluate
from .scenario import generate
from .store import IdempotencyConflict, NotFound, PolicyDenied, Store
from .workflow import WorkflowBudgetExceeded


def main() -> int:
    parser = argparse.ArgumentParser(description="AegisFlow sentetik deterministik pilot")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("generate")
    seed.add_argument("--seed", type=int, default=42)
    run = sub.add_parser("run")
    run.add_argument("--scenario", type=Path, required=True)
    run.add_argument("--db", type=Path, required=True)
    run.add_argument("--key", required=True)
    run.add_argument("--as-of", default="2026-11-01T18:00:00Z")
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument(
        "--suite", type=Path, default=Path("fixtures/evaluations/supply-workflow-v1.json")
    )
    evaluation.add_argument("--workflow", choices=["fixed-v1", "validated-v2"], default="fixed-v1")
    args = parser.parse_args()
    try:
        if args.command == "evaluate":
            report = evaluate(args.suite, args.workflow)
            print(json.dumps(report, indent=2))
            return 0 if report["passed"] else 1
        if args.command == "generate":
            print(generate(args.seed).model_dump_json(indent=2))
        else:
            if args.scenario.stat().st_size > 1_000_000:
                raise ValueError("Kaynak boyutu sınırı aşıldı")
            scenario = Scenario.model_validate_json(args.scenario.read_text())
            # Deliberately fixed local scope: no caller-controlled tenant or identity flags.
            scope = Scope(
                tenant_id="demo",
                subject_id="local-demo",
                permissions=frozenset({"investigate", "read"}),
            )
            request = Request.model_validate(
                {
                    "tenant_id": "demo",
                    "order_id": "PO-001",
                    "idempotency_key": args.key,
                    "as_of": args.as_of,
                }
            )
            store = Store(args.db)
            case = store.run(scope, request, scenario)
            print(
                json.dumps(
                    {
                        "case": case.model_dump(mode="json"),
                        "events": [
                            e.model_dump(mode="json") for e in store.events(scope, case.case_id)
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0
    except WorkflowBudgetExceeded:
        print("WORKFLOW_BUDGET_EXCEEDED", file=sys.stderr)
    except (ValidationError, ValueError):
        print("INVALID_SCHEMA: Girdi veya zaman alanları geçersiz", file=sys.stderr)
    except (PolicyDenied, NotFound, IdempotencyConflict) as error:
        print(str(error), file=sys.stderr)
    except (OSError, sqlite3.Error):
        print(
            "DEPENDENCY_UNAVAILABLE: Yerel dosya veya kayıt deposuna erişilemiyor", file=sys.stderr
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
