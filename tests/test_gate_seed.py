"""Idempotency and value tests for the reference-data seeder."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from api_trafix.config.settings import get_settings
from api_trafix.core.security import hash_password, verify_password
from api_trafix.models import (
    Gate,
    Member,
    MemberSubscription,
    OperatorSession,
    OperatorShiftAssignment,
    ParkingRate,
    SubscriptionPlan,
    User,
    UserRole,
    UserStatus,
    VehicleType,
)
from api_trafix.services.seed import (
    DEMO_MEMBER,
    GATE_ENTRY_CODE,
    GATE_ENTRY_NAME,
    GATE_EXIT_CODE,
    GATE_EXIT_NAME,
    RATES,
    seed_reference_data,
)

GATE_COUNT = 2
VEHICLE_TYPE_COUNT = 4
RATE_COUNT = 4


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
        assert set(vehicle_types) == {"MOTOR", "MOBIL", "OJOL", "BUS"}

        rates = (await db.scalars(select(ParkingRate))).all()
        for rate in rates:
            config = RATES[rate.vehicle_type.code]
            assert rate.fee_category == config["fee_category"]
            assert rate.base_price == config["base_price"]
            assert rate.grace_period_minutes == config["grace_period_minutes"]
            assert rate.ticket_charge == config["ticket_charge"]
            assert rate.stay_charge == config["stay_charge"]


async def test_seed_creates_the_demo_member(db_sessionmaker):
    async with db_sessionmaker() as db:
        await seed_reference_data(db)

        member = await db.scalar(
            select(Member)
            .options(selectinload(Member.vehicles))
            .where(Member.card_number == DEMO_MEMBER["card_number"])
        )
        assert member is not None
        assert member.name == DEMO_MEMBER["name"]
        assert member.member_code == DEMO_MEMBER["member_code"]

        vehicle = member.vehicles[0]
        assert vehicle.police_number == DEMO_MEMBER["police_number"]

        subscription = await db.scalar(
            select(MemberSubscription).where(MemberSubscription.member_id == member.id)
        )
        assert subscription is not None
        assert subscription.status == "active"


async def test_seed_is_idempotent(db_sessionmaker):
    async with db_sessionmaker() as db:
        await seed_reference_data(db)
        await seed_reference_data(db)

        assert await _count(db, Gate) == GATE_COUNT
        assert await _count(db, VehicleType) == VEHICLE_TYPE_COUNT
        assert await _count(db, ParkingRate) == RATE_COUNT
        assert await _count(db, Member) == 1
        assert await _count(db, SubscriptionPlan) == 1


async def _clear_users(db) -> None:
    # Sessions/assignments hard-reference users (no cascade), so clear them
    # first — stale rows from earlier runs would block the delete otherwise.
    await db.execute(delete(OperatorSession))
    await db.execute(delete(OperatorShiftAssignment))
    await db.execute(delete(User))
    await db.commit()


async def test_seed_creates_bootstrap_admin(db_sessionmaker):
    async with db_sessionmaker() as db:
        await _clear_users(db)
        await seed_reference_data(db)

        admin = await db.scalar(select(User).where(User.role == UserRole.ADMIN))
        assert admin is not None
        assert admin.username == get_settings().admin_username
        assert admin.name == get_settings().admin_name
        assert admin.status == UserStatus.ACTIVE
        assert verify_password(get_settings().admin_password, admin.password)


async def test_bootstrap_admin_skipped_when_users_exist(db_sessionmaker):
    async with db_sessionmaker() as db:
        await _clear_users(db)
        db.add(
            User(
                name="Root",
                username="root",
                password=hash_password("irrelevant"),
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
            )
        )
        await db.commit()

        await seed_reference_data(db)

        users = (await db.scalars(select(User))).all()
        assert [user.username for user in users] == ["root"]
