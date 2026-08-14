import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import subscription_plan as crud
from api_trafix.models import User
from api_trafix.services.audit import log_action
from api_trafix.schemas.subscription_plan import (
    SubscriptionPlanCreate,
    SubscriptionPlanPage,
    SubscriptionPlanRead,
    SubscriptionPlanStatusUpdate,
    SubscriptionPlanUpdate,
)

router = APIRouter(prefix="/subscription-plans", tags=["Subscription Plans"])


@router.get("/", response_model=SubscriptionPlanPage)
async def list_subscription_plans(
    search: str | None = Query(default=None, max_length=100),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await crud.get_all(
        db, search=search, is_active=is_active, page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size
    return SubscriptionPlanPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{plan_id}", response_model=SubscriptionPlanRead)
async def get_subscription_plan(plan_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, plan_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription plan not found"
        )
    return db_obj


@router.post("/", response_model=SubscriptionPlanRead, status_code=status.HTTP_201_CREATED)
async def create_subscription_plan(
    payload: SubscriptionPlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    existing = await crud.get_by_name(db, payload.name)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Name already exists"
        )
    db_obj = await crud.create(db, payload)
    await log_action(
        db,
        module="subscription-plan",
        action="create",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Created subscription plan '{db_obj.name}'",
    )
    return db_obj


@router.put("/{plan_id}", response_model=SubscriptionPlanRead)
async def update_subscription_plan(
    plan_id: uuid.UUID,
    payload: SubscriptionPlanUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, plan_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription plan not found"
        )

    if payload.name and payload.name != db_obj.name:
        existing = await crud.get_by_name(db, payload.name)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Name already exists"
            )

    db_obj = await crud.update(db, db_obj, payload)
    await log_action(
        db,
        module="subscription-plan",
        action="update",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Updated subscription plan '{db_obj.name}'",
    )
    return db_obj


@router.patch("/{plan_id}/status", response_model=SubscriptionPlanRead)
async def update_subscription_plan_status(
    plan_id: uuid.UUID,
    payload: SubscriptionPlanStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, plan_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription plan not found"
        )
    db_obj = await crud.update(db, db_obj, payload)
    await log_action(
        db,
        module="subscription-plan",
        action="update-status",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Changed subscription plan '{db_obj.name}' active status to {db_obj.is_active}",
    )
    return db_obj


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, plan_id)
    if db_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription plan not found"
        )
    if await crud.is_in_use(db, plan_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plan is in use by member subscriptions",
        )
    await log_action(
        db,
        module="subscription-plan",
        action="delete",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Deleted subscription plan '{db_obj.name}'",
    )
    await crud.delete(db, db_obj)
    return None
