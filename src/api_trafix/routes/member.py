import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import member as crud
from api_trafix.crud import subscription_plan as plan_crud
from api_trafix.crud import vehicle_type as vehicle_type_crud
from api_trafix.models import MemberStatus, User, VehicleStatus
from api_trafix.schemas.member import MemberCreate, MemberPage, MemberRead, MemberUpdate
from api_trafix.services.audit import log_action

router = APIRouter(prefix="/members", tags=["Members"])


@router.get("/", response_model=MemberPage)
async def list_members(
    search: str | None = Query(default=None, max_length=100),
    status_filter: MemberStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    items, total = await crud.get_all(
        db, search=search, status=status_filter, page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size
    return MemberPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{member_id}", response_model=MemberRead)
async def get_member(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, member_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    return db_obj


@router.post("/", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def create_member(
    payload: MemberCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    if payload.vehicle_type_id is not None:
        vehicle_type = await vehicle_type_crud.get_by_id(db, payload.vehicle_type_id)
        if vehicle_type is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle type not found"
            )
        if vehicle_type.status != VehicleStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vehicle type is not active",
            )
        if await crud.police_number_exists(db, payload.police_number):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Police number already registered",
            )

    if await crud.card_number_exists(db, payload.card_number):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Card number already registered",
        )

    plan = None
    if payload.plan_id is not None:
        plan = await plan_crud.get_by_id(db, payload.plan_id)
        if plan is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription plan not found",
            )
        if not plan.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Subscription plan is not active",
            )
        if payload.status != MemberStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Member is not active",
            )

    db_obj = await crud.create(db, payload, plan=plan)
    await log_action(
        db,
        module="member",
        action="create",
        user_id=current_user.id,
        role=current_user.role.value,
        description=(
            f"Registered member '{db_obj.name}' ({db_obj.member_code})"
            + (
                f" with vehicle '{payload.police_number}'"
                if payload.police_number
                else ""
            )
            + (f" with card '{payload.card_number}'" if payload.card_number else "")
            + (f" subscribed to plan '{plan.name}'" if plan is not None else "")
        ),
    )
    return db_obj


@router.put("/{member_id}", response_model=MemberRead)
async def update_member(
    member_id: uuid.UUID,
    payload: MemberUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, member_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    if (
        payload.card_number is not None
        and payload.card_number != db_obj.card_number
        and await crud.card_number_exists(db, payload.card_number, exclude_id=db_obj.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Card number already registered",
        )
    db_obj = await crud.update(db, db_obj, payload)
    await log_action(
        db,
        module="member",
        action="update",
        user_id=current_user.id,
        role=current_user.role.value,
        description=(
            f"Updated member '{db_obj.name}' ({db_obj.member_code})"
            + (
                f" card set to '{payload.card_number}'"
                if payload.card_number
                else " card cleared"
                if "card_number" in payload.model_dump(exclude_unset=True)
                else ""
            )
        ),
    )
    return db_obj


@router.patch("/{member_id}/block", response_model=MemberRead)
async def block_member(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, member_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    db_obj = await crud.block(db, db_obj)
    await log_action(
        db,
        module="member",
        action="block",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Blocked member '{db_obj.name}' ({db_obj.member_code})",
    )
    return db_obj


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, member_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        )
    await log_action(
        db,
        module="member",
        action="delete",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Deleted member '{db_obj.name}' ({db_obj.member_code})",
    )
    await crud.delete(db, db_obj)
