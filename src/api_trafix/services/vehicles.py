"""Vehicle-class helpers shared by the gate cycle.

The gate hardware and the Tauri cashier address vehicle classes by the wire id
the mock uses (1 = Motor, 2 = Mobil, 3 = Ojol/Paket, 4 = Bus Besar). API-Trafix
keys them by ``vehicle_types.id`` UUID, so every boundary between the wire and
the schema translates through these helpers.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models.vehicle_types import VehicleType

# Wire id -> vehicle_types.code, matching the mock's Vehicles seed.
VEHICLE_CODES: dict[int, str] = {1: "MOTOR", 2: "MOBIL", 3: "OJOL", 4: "BUS"}
VEHICLE_IDS: dict[str, int] = {code: vehicle_id for vehicle_id, code in VEHICLE_CODES.items()}

# When the LPR cannot tell the classes apart (which is the norm on site), the
# transaction is recorded against this class. Matches the mock's behaviour of
# leaving vehicle_id NULL and the cashier's on-screen default.
DEFAULT_VEHICLE_CODE = "MOTOR"


async def vehicle_type_id(db: AsyncSession, vehicle_id: int | None) -> UUID | None:
    """The vehicle_types UUID for a wire id, else None."""
    code = VEHICLE_CODES.get(vehicle_id)
    if code is None:
        return None
    vehicle_type = await db.scalar(
        select(VehicleType).where(VehicleType.code == code)
    )
    return vehicle_type.id if vehicle_type is not None else None


async def vehicle_id_of(
    db: AsyncSession, vehicle_type_id: UUID | None
) -> int | None:
    """The wire id for a vehicle_types UUID, else None."""
    if vehicle_type_id is None:
        return None
    vehicle_type = await db.get(VehicleType, vehicle_type_id)
    if vehicle_type is None:
        return None
    return VEHICLE_IDS.get(vehicle_type.code)


async def vehicle_name(db: AsyncSession, vehicle_id: int | None) -> str | None:
    """The display name ("Motor") for a wire id, else None."""
    code = VEHICLE_CODES.get(vehicle_id)
    if code is None:
        return None
    vehicle_type = await db.scalar(
        select(VehicleType).where(VehicleType.code == code)
    )
    return vehicle_type.name if vehicle_type is not None else None


async def coerce_vehicle_type_id(
    db: AsyncSession, vehicle_id: int | None
) -> UUID | None:
    """A vehicle_types UUID that satisfies the NOT NULL constraint.

    An explicit wire id wins; otherwise the default class (Motor) is used, so
    an LPR entry that cannot distinguish classes still gets a valid row.
    """
    resolved = await vehicle_type_id(db, vehicle_id)
    if resolved is not None:
        return resolved
    vehicle_type = await db.scalar(
        select(VehicleType).where(VehicleType.code == DEFAULT_VEHICLE_CODE)
    )
    return vehicle_type.id if vehicle_type is not None else None
