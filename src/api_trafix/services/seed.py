"""Idempotent reference-data seeder for the gate-in / gate-out cycle.

Phase 1 of the trafix-api-mock integration. Mirrors what the mock seeds for the
Salatiga site (``trafix-api-mock/trafix/db.py::seed``), mapped onto the modern
API-Trafix schema:

* the two physical gates the hardware addresses by wire id (``gate_code``),
* the two vehicle classes the LPR cannot distinguish (Motor / Mobil),
* one flat parking rate per class, including the lost-ticket and overnight
  stay fees that are printed on every ticket footer.

Every insert is guarded by an existence check, so running the seeder on a
populated database (or twice) is a no-op.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models import (
    Gate,
    GateStatus,
    GateType,
    ParkingRate,
    RateStatus,
    VehicleStatus,
    VehicleType,
)

logger = logging.getLogger(__name__)

# The wire gate ids the hardware uses (flow.md §3): entry is "1", exit is "2".
GATE_ENTRY_CODE = "1"
GATE_EXIT_CODE = "2"

GATE_ENTRY_NAME = "Gate Masuk"
GATE_EXIT_NAME = "Gate Keluar"

# Vehicle classes, matching the mock's vehicles 1 = Motor, 2 = Mobil.
VEHICLES = (
    {"code": "MOTOR", "name": "Motor"},
    {"code": "MOBIL", "name": "Mobil"},
)

# Flat tariffs from the real-site seed (trafix-api-mock/db.py:118-145). The
# ticket footer amounts are decoded from the captured printed ticket (flow.md
# §5); the grace period is the captured "Flat" tariff configuration.
RATES = {
    "MOTOR": {
        "name": "Tarif Motor",
        "base_price": 2000,
        "grace_period_minutes": 10,
        "ticket_charge": 10000,
        "stay_charge": 10000,
    },
    "MOBIL": {
        "name": "Tarif Mobil",
        "base_price": 4000,
        "grace_period_minutes": 10,
        "ticket_charge": 30000,
        "stay_charge": 25000,
    },
}


async def seed_reference_data(db: AsyncSession) -> None:
    """Insert reference rows the gate cycle needs. Safe to call repeatedly."""
    created_gates = 0

    entry_gate = await _get_or_create_gate(
        db, code=GATE_ENTRY_CODE, name=GATE_ENTRY_NAME, type=GateType.GATE_IN
    )
    created_gates += entry_gate

    exit_gate = await _get_or_create_gate(
        db, code=GATE_EXIT_CODE, name=GATE_EXIT_NAME, type=GateType.GATE_OUT
    )
    created_gates += exit_gate

    created_types = 0
    for vehicle in VEHICLES:
        vehicle_type = await db.scalar(
            select(VehicleType).where(VehicleType.code == vehicle["code"])
        )
        if vehicle_type is None:
            db.add(
                VehicleType(
                    code=vehicle["code"],
                    name=vehicle["name"],
                    status=VehicleStatus.ACTIVE,
                )
            )
            created_types += 1

    await db.flush()

    created_rates = 0
    for vehicle in VEHICLES:
        vehicle_type = await db.scalar(
            select(VehicleType).where(VehicleType.code == vehicle["code"])
        )
        if vehicle_type is None:
            continue
        rate = RATES[vehicle["code"]]
        existing = await db.scalar(
            select(ParkingRate).where(
                ParkingRate.vehicle_type_id == vehicle_type.id,
                ParkingRate.status == RateStatus.ACTIVE,
            )
        )
        if existing is None:
            db.add(
                ParkingRate(
                    name=rate["name"],
                    vehicle_type_id=vehicle_type.id,
                    base_price=rate["base_price"],
                    grace_period_minutes=rate["grace_period_minutes"],
                    ticket_charge=rate["ticket_charge"],
                    stay_charge=rate["stay_charge"],
                    status=RateStatus.ACTIVE,
                )
            )
            created_rates += 1

    await db.commit()
    logger.info(
        "reference data seeded (gates=%d, vehicle_types=%d, rates=%d)",
        created_gates,
        created_types,
        created_rates,
    )


async def _get_or_create_gate(
    db: AsyncSession, *, code: str, name: str, type: GateType
) -> int:
    """Return 1 when the gate row was created, else 0."""
    gate = await db.scalar(select(Gate).where(Gate.gate_code == code))
    if gate is None:
        db.add(
            Gate(
                name=name,
                gate_code=code,
                type=type,
                status=GateStatus.ONLINE,
            )
        )
        return 1
    return 0
