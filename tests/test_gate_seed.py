"""Idempotency and value tests for the reference-data seeder."""

from sqlalchemy import func, select

from api_trafix.models import Gate, ParkingRate, VehicleType
from api_trafix.services.seed import (
    GATE_ENTRY_CODE,
    GATE_ENTRY_NAME,
    GATE_EXIT_CODE,
    GATE_EXIT_NAME,
    RATES,
    seed_reference_data,
)

GATE_COUNT = 2
VEHICLE_TYPE_COUNT = 2
RATE_COUNT = 2


async def _count(db, model) -> int:
    result = await db.execute(select(func.count()).select_from(model))
    return result.scalar_one()


async def test_seed_creates_reference_data(db_sessionmaker):
    async with db_sessionmaker() as db:
        await seed_reference_data(db)

        assert await _count(db, Gate) == GATE_COUNT
        assert await _count(db, VehicleType) == VEHICLE_TYPE_COUNT
        assert await _count(db, ParkingRate) == RATE_COUNT

        gates = {gate.gate_code: gate for gate in (await db.scalars(select(Gate))).all()}
        assert gates[GATE_ENTRY_CODE].name == GATE_ENTRY_NAME
        assert gates[GATE_EXIT_CODE].name == GATE_EXIT_NAME

        vehicle_types = {
            vehicle.code: vehicle
            for vehicle in (await db.scalars(select(VehicleType))).all()
        }
        assert set(vehicle_types) == {"MOTOR", "MOBIL"}

        rates = (await db.scalars(select(ParkingRate))).all()
        for rate in rates:
            config = RATES[rate.vehicle_type.code]
            assert rate.base_price == config["base_price"]
            assert rate.grace_period_minutes == config["grace_period_minutes"]
            assert rate.ticket_charge == config["ticket_charge"]
            assert rate.stay_charge == config["stay_charge"]


async def test_seed_is_idempotent(db_sessionmaker):
    async with db_sessionmaker() as db:
        await seed_reference_data(db)
        await seed_reference_data(db)

        assert await _count(db, Gate) == GATE_COUNT
        assert await _count(db, VehicleType) == VEHICLE_TYPE_COUNT
        assert await _count(db, ParkingRate) == RATE_COUNT
