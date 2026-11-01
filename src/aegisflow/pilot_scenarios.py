"""Versioned synthetic triage suite; never represents connected business data."""

from datetime import timedelta

from .contracts import Scenario
from .scenario import generate

SUITE_VERSION = "supply-triage-suite-v1"


def pilot_scenarios() -> tuple[Scenario, ...]:
    base = generate()
    results = []
    for index, kind in enumerate(
        ("delayed", "on_time", "missing_sla", "conflicting", "pending"), 1
    ):
        payload = base.model_dump()
        order_id = f"PO-{index:03}"
        payload["order"]["order_id"] = order_id
        for delivery in payload["deliveries"]:
            delivery["order_id"] = order_id
        if kind == "on_time":
            payload["deliveries"][0]["delivered_at"] = base.order.promised_at
        elif kind == "missing_sla":
            payload["sla"] = None
        elif kind == "conflicting":
            payload["deliveries"] += (
                {
                    **payload["deliveries"][0],
                    "event_id": "delivery-conflict",
                    "delivered_at": base.order.promised_at + timedelta(hours=3),
                },
            )
        elif kind == "pending":
            payload["deliveries"] = ()
        results.append(Scenario.model_validate(payload))
    return tuple(results)
