import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import member as member_crud
from api_trafix.crud import member_subscription as crud
from api_trafix.crud import subscription_plan as plan_crud
from api_trafix.models import User, MemberStatus
from api_trafix.services import subscriptions as subscription_service
from api_trafix.services.audit import log_action
from api_trafix.schemas.member_subscription import (
    MemberSubscriptionCreate,
    MemberSubscriptionPage,
    MemberSubscriptionRead,
)

router = APIRouter(prefix="/member-subscriptions", tags=["Member Subscriptions"])


@router.get("/", response_model=MemberSubscriptionPage)
async def list_member_subscriptions(
    member_id: uuid.UUID | None = Query(default=None),
    plan_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    await subscription_service.auto_expire(db)
    items, total = await crud.get_all(
        db,
        member_id=member_id,
        plan_id=plan_id,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    total_pages = (total + page_size - 1) // page_size
    return MemberSubscriptionPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{subscription_id}", response_model=MemberSubscriptionRead)
async def get_member_subscription(
    subscription_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    await subscription_service.auto_expire(db)
    db_obj = await crud.get_by_id(db, subscription_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member subscription not found",
        )
    return db_obj


@router.post("/", response_model=MemberSubscriptionRead, status_code=status.HTTP_201_CREATED)
async def subscribe_member(
    payload: MemberSubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    member = await member_crud.get_by_id(db, payload.member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if member.status != MemberStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Member is not active"
        )

    plan = await plan_crud.get_by_id(db, payload.plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription plan not found"
        )
    if not plan.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Subscription plan is not active"
        )

    await subscription_service.auto_expire(db)
    existing = await crud.get_active_for_member(db, payload.member_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Member already has an active subscription",
        )

    db_obj = await crud.create(db, payload, plan)
    await log_action(
        db,
        module="member-subscription",
        action="create",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Subscribed member '{member.name}' to plan '{plan.name}'",
    )
    return db_obj


@router.post("/{subscription_id}/cancel", response_model=MemberSubscriptionRead)
async def cancel_member_subscription(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, subscription_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member subscription not found",
        )
    if db_obj.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only an active subscription can be cancelled",
        )
    db_obj = await crud.cancel(db, db_obj)
    await log_action(
        db,
        module="member-subscription",
        action="cancel",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Cancelled subscription for member '{db_obj.member.name}'",
    )
    return db_obj


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member_subscription(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, subscription_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member subscription not found",
        )
    await log_action(
        db,
        module="member-subscription",
        action="delete",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Deleted subscription for member '{db_obj.member.name}'",
    )
    await crud.delete(db, db_obj)
    return None
