"""Seeded synthetic data, fixed clock and versioned generator."""

import random
from datetime import UTC, datetime, timedelta

from .contracts import SLA, Delivery, Inventory, Order, Procedure, Scenario


def generate(seed: int = 42) -> Scenario:
    rng = random.Random(seed)
    promised = datetime(2026, 11, 1, 9, tzinfo=UTC)
    return Scenario(
        seed=seed,
        order=Order(
            order_id="PO-001",
            tenant_id="demo",
            quantity=100,
            placed_at=promised - timedelta(days=3),
            promised_at=promised,
        ),
        deliveries=(
            Delivery(
                event_id="delivery-001",
                order_id="PO-001",
                delivered_at=promised + timedelta(hours=rng.randint(2, 8)),
            ),
        ),
        inventory=Inventory(available=20, captured_at=promised),
        sla=SLA(grace_seconds=3600, version="sla-v1"),
        procedure=Procedure(
            version="sop-v1", instruction="Escalate to procurement after SLA breach"
        ),
    )
