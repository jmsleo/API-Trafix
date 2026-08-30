"""Idempotent reference-data seeder for the gate-in / gate-out cycle.

Phases 1-2 of the trafix-api-mock integration. Mirrors what the mock seeds for
the Salatiga site (``trafix-api-mock/trafix/db.py::seed``), mapped onto the
modern API-Trafix schema:

* the two physical gates the hardware addresses by wire id (``gate_code``),
* the vehicle classes the LPR cannot always distinguish (Motor / Mobil, plus
  the cashier-only Ojol/Paket and Bus Besar),
* one flat parking rate per class, including the lost-ticket and overnight
  stay fees that are printed on every ticket footer,
* a demo member (Angelo / H4818AI / RFID 006343040) so member auto-entry can
  be exercised end to end,
* a bootstrap admin login (ADMIN_USERNAME / ADMIN_PASSWORD, default
  ``admin`` / ``admin123``) so the /users API can be used at all — it is only
  created while the users table is empty.

Every insert is guarded by an existence check, so running the seeder on a
populated database (or twice) is a no-op.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.settings import get_settings
from api_trafix.core.security import hash_password
from api_trafix.models import (
    Gate,
    GateStatus,
    GateType,
    Member,
    MemberStatus,
    MemberSubscription,
    MemberVehicle,
    ParkingRate,
    RateStatus,
    SubscriptionPlan,
    User,
    UserRole,
    UserStatus,
    VehicleStatus,
    VehicleType,
)

logger = logging.getLogger(__name__)

# The wire gate ids the hardware uses (flow.md §3): entry is "1", exit is "2".
GATE_ENTRY_CODE = "1"
GATE_EXIT_CODE = "2"

GATE_ENTRY_NAME = "Gate Masuk"
GATE_EXIT_NAME = "Gate Keluar"

# Vehicle classes, matching the mock's vehicles 1 = Motor, 2 = Mobil, plus the
# cashier-only classes 3 = Ojol/Paket and 4 = Bus Besar (mock db.py:78-81).
VEHICLES = (
    {"code": "MOTOR", "name": "Motor"},
    {"code": "MOBIL", "name": "Mobil"},
    {"code": "OJOL", "name": "Ojol/Paket"},
    {"code": "BUS", "name": "Bus Besar"},
)

# Flat tariffs from the real-site seed (trafix-api-mock/db.py:118-145). The
# ticket footer amounts are decoded from the captured printed ticket (flow.md
# §5); the grace period is the captured "Flat" tariff configuration.
RATES = {
    "MOTOR": {
        "name": "Tarif Motor",
        "fee_category": "flat",
        "base_price": 2000,
        "grace_period_minutes": 10,
        "ticket_charge": 10000,
        "stay_charge": 10000,
    },
    "MOBIL": {
        "name": "Tarif Mobil",
        "fee_category": "flat",
        "base_price": 4000,
        "grace_period_minutes": 10,
        "ticket_charge": 30000,
        "stay_charge": 25000,
    },
    "OJOL": {
        "name": "Tarif Ojol/Paket",
        "fee_category": "flat",
        "base_price": 0,
        "grace_period_minutes": 0,
        "ticket_charge": 0,
        "stay_charge": 0,
    },
    "BUS": {
        "name": "Tarif Bus Besar",
        "fee_category": "flat",
        "base_price": 6000,
        "grace_period_minutes": 10,
        "ticket_charge": 50000,
        "stay_charge": 40000,
    },
}

# Demo member, from the captured API response (mock db.py:192-209).
DEMO_MEMBER = {
    "name": "Angelo",
    "police_number": "H4818AI",
    "member_code": "H4818AI",
    "card_number": "006343040",
    "vehicle_code": "MOTOR",
    "subscription_days": 365,
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
                    price=RATES[vehicle["code"]]["base_price"],
                    status=VehicleStatus.ACTIVE,
                )
            )
            created_types += 1
        elif vehicle_type.price is None:
            # Backfill rows predating vehicle_types.price so the operator
            # screen shows the familiar flat rates without the SQL migration.
            vehicle_type.price = RATES[vehicle["code"]]["base_price"]

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
                    fee_category=rate["fee_category"],
                    grace_period_minutes=rate["grace_period_minutes"],
                    ticket_charge=rate["ticket_charge"],
                    stay_charge=rate["stay_charge"],
                    status=RateStatus.ACTIVE,
                )
            )
            created_rates += 1

    created_member = await _seed_demo_member(db)
    created_admin = await _seed_bootstrap_admin(db)

    await db.commit()
    logger.info(
        "reference data seeded (gates=%d, vehicle_types=%d, rates=%d, member=%d, admin=%d)",
        created_gates,
        created_types,
        created_rates,
        created_member,
        created_admin,
    )


async def _seed_bootstrap_admin(db: AsyncSession) -> int:
    """Create the first admin login so /users is reachable at all.

    Only runs while the users table is empty: once any account exists the
    admins manage accounts through the API and the seeder stays out of the
    way. Returns 1 when a new admin was created, else 0.
    """
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    if user_count > 0:
        return 0

    settings = get_settings()
    if settings.admin_password == "admin123":
        logger.warning(
            "creating bootstrap admin '%s' with the DEFAULT password; "
            "set ADMIN_PASSWORD in .env before going live",
            settings.admin_username,
        )
    db.add(
        User(
            name=settings.admin_name,
            username=settings.admin_username,
            password=hash_password(settings.admin_password),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
    )
    return 1


async def _seed_demo_member(db: AsyncSession) -> int:
    """Create the demo member and its vehicle + active subscription.

    Returns 1 when a new member was created, else 0.
    """
    if await db.scalar(
        select(Member).where(Member.card_number == DEMO_MEMBER["card_number"])
    ) is not None:
        return 0

    vehicle_type = await db.scalar(
        select(VehicleType).where(VehicleType.code == DEMO_MEMBER["vehicle_code"])
    )
    if vehicle_type is None:
        return 0

    plan = await db.scalar(
        select(SubscriptionPlan).where(SubscriptionPlan.is_active.is_(True))
    )
    if plan is None:
        plan = SubscriptionPlan(
            name="Demo Bulanan",
            duration_in_days=30,
            price=100000,
            vehicle_type_id=vehicle_type.id,
            is_active=True,
        )
        db.add(plan)
        await db.flush()

    member = Member(
        member_code=DEMO_MEMBER["member_code"],
        name=DEMO_MEMBER["name"],
        status=MemberStatus.ACTIVE,
        card_number=DEMO_MEMBER["card_number"],
    )
    db.add(member)
    await db.flush()

    db.add(
        MemberVehicle(
            member_id=member.id,
            vehicle_type_id=vehicle_type.id,
            police_number=DEMO_MEMBER["police_number"],
        )
    )
    today = datetime.now(UTC).date()
    db.add(
        MemberSubscription(
            member_id=member.id,
            plan_id=plan.id,
            start_date=today,
            end_date=today + timedelta(days=DEMO_MEMBER["subscription_days"]),
            status="active",
        )
    )
    return 1


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
