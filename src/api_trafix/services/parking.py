from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.crud import member as member_crud
from api_trafix.crud import member_subscription as subscription_crud
from api_trafix.crud import member_vehicle as member_vehicle_crud
from api_trafix.crud import operator_session as operator_session_crud
from api_trafix.crud import park_transaction as park_transaction_crud
from api_trafix.models import (
    MemberStatus,
    ParkingSlot,
    ParkingStatus,
    ParkTransaction,
    Payment,
    PaymentStatus,
    User,
)
from api_trafix.schemas.park_transaction import (
    ParkTransactionCheckOut,
    ParkTransactionCreate,
)
from api_trafix.services import cache as cache_service
from api_trafix.services import subscriptions as subscription_service
from api_trafix.services.audit import log_action
from api_trafix.services.errors import ServiceError
from api_trafix.services.fees import calculate_fee, resolve_rate
from api_trafix.utils.codes import generate_reference_number, generate_ticket_number


async def _get_slot(db: AsyncSession, vehicle_type_id):
    result = await db.execute(
        select(ParkingSlot)
        .where(ParkingSlot.vehicle_type_id == vehicle_type_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _decrement_slot(db: AsyncSession, vehicle_type_id) -> None:
    slot = await _get_slot(db, vehicle_type_id)
    if slot is None:
        return
    if slot.available_capacity <= 0:
        raise ServiceError(
            409, "No available parking slots for this vehicle type"
        )
    slot.available_capacity -= 1


async def _release_slot(db: AsyncSession, vehicle_type_id) -> None:
    slot = await _get_slot(db, vehicle_type_id)
    if slot is None:
        return
    if slot.available_capacity < slot.total_capacity:
        slot.available_capacity += 1


async def _member_subscription_active(db: AsyncSession, member_id) -> bool:
    await subscription_service.auto_expire(db)
    sub = await subscription_crud.get_active_for_member(db, member_id)
    return sub is not None


async def check_in(
    db: AsyncSession, operator: User, payload: ParkTransactionCreate
) -> ParkTransaction:
    session = await operator_session_crud.get_active_for_operator(db, operator.id)
    if session is None:
        raise ServiceError(409, "Operator has no active session")

    police_number = payload.police_number.strip().upper()
    vehicle = await member_vehicle_crud.get_by_police_number(db, police_number)

    is_member = False
    vehicle_type_id = payload.vehicle_type_id
    if vehicle is not None:
        vehicle_type_id = vehicle.vehicle_type_id
        member = await member_crud.get_by_id(db, vehicle.member_id)
        member_subscription_active = (
            member is not None
            and member.status == MemberStatus.ACTIVE
            and await _member_subscription_active(db, vehicle.member_id)
        )
        is_member = member_subscription_active

    if vehicle_type_id is None:
        raise ServiceError(
            400,
            "vehicle_type_id is required for non-member vehicles",
        )

    await _decrement_slot(db, vehicle_type_id)
    rate = await resolve_rate(db, vehicle_type_id)

    db_obj = ParkTransaction(
        ticket_number=generate_ticket_number(),
        police_number=police_number,
        vehicle_type_id=vehicle_type_id,
        member_vehicle_id=vehicle.id if vehicle is not None else None,
        entry_time=datetime.now(timezone.utc),
        entry_gate_id=session.gate_id,
        entry_shift_id=session.shift_id,
        entry_operator_id=operator.id,
        parking_rate_id=rate.id if rate is not None else None,
        status_parking=ParkingStatus.PARKED,
        is_member=is_member,
        total_fee=0,
        detection_method=payload.detection_method,
    )
    db.add(db_obj)
    await db.commit()

    await log_action(
        db,
        "park_transaction",
        "check_in",
        user_id=operator.id,
        role=operator.role.value,
        description=(
            f"Check-in {police_number} ticket {db_obj.ticket_number} "
            f"member={is_member}"
        ),
    )
    return await park_transaction_crud.get_by_id(db, db_obj.id)


async def check_out(
    db: AsyncSession,
    operator: User,
    transaction_id,
    payload: ParkTransactionCheckOut,
) -> ParkTransaction:
    db_obj = await park_transaction_crud.get_by_id(db, transaction_id)
    if db_obj is None:
        raise ServiceError(404, "Park transaction not found")
    if db_obj.status_parking != ParkingStatus.PARKED:
        raise ServiceError(400, "Only a parked transaction can be checked out")

    session = await operator_session_crud.get_active_for_operator(db, operator.id)
    if session is None:
        raise ServiceError(409, "Operator has no active session")

    member_subscription_active = False
    if db_obj.member_vehicle_id is not None:
        vehicle = await member_vehicle_crud.get_by_id(db, db_obj.member_vehicle_id)
        if vehicle is not None:
            member_subscription_active = await _member_subscription_active(
                db, vehicle.member_id
            )

    fee = await calculate_fee(
        db,
        db_obj.vehicle_type_id,
        is_member=db_obj.is_member,
        member_subscription_active=member_subscription_active,
    )

    now = datetime.now(timezone.utc)
    db.add(
        Payment(
            park_transaction_id=db_obj.id,
            amount=fee,
            method=payload.payment_method,
            status=PaymentStatus.SUCCESS,
            reference_number=generate_reference_number(),
            paid_at=now,
        )
    )
    db_obj.exit_time = now
    db_obj.exit_gate_id = session.gate_id
    db_obj.exit_shift_id = session.shift_id
    db_obj.exit_operator_id = operator.id
    db_obj.total_fee = fee
    db_obj.status_parking = ParkingStatus.COMPLETED
    await _release_slot(db, db_obj.vehicle_type_id)
    await db.commit()

    await log_action(
        db,
        "park_transaction",
        "check_out",
        user_id=operator.id,
        role=operator.role.value,
        description=(
            f"Check-out {db_obj.police_number} ticket {db_obj.ticket_number} "
            f"fee={fee} method={payload.payment_method.value}"
        ),
    )
    await cache_service.invalidate("finance:dashboard:*")
    return await park_transaction_crud.get_by_id(db, db_obj.id)


async def void(db: AsyncSession, user: User, transaction_id) -> ParkTransaction:
    db_obj = await park_transaction_crud.get_by_id(db, transaction_id)
    if db_obj is None:
        raise ServiceError(404, "Park transaction not found")
    if db_obj.status_parking != ParkingStatus.PARKED:
        raise ServiceError(400, "Only a parked transaction can be voided")

    db_obj.status_parking = ParkingStatus.VOID
    await _release_slot(db, db_obj.vehicle_type_id)
    await db.commit()

    await log_action(
        db,
        "park_transaction",
        "void",
        user_id=user.id,
        role=user.role.value,
        description=f"Void {db_obj.police_number} ticket {db_obj.ticket_number}",
    )
    return await park_transaction_crud.get_by_id(db, db_obj.id)
