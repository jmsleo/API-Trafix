import re
from typing import Annotated, Any

from pydantic import BeforeValidator, EmailStr, Field, StringConstraints

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]

Name = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
ShortName = Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)]
Code = Annotated[str, StringConstraints(min_length=1, max_length=20, strip_whitespace=True)]
Email = Annotated[EmailStr, StringConstraints(strip_whitespace=True)]


def _normalize_phone(value: Any) -> Any:
    if value is None:
        return value
    return re.sub(r"[\s()\-.]", "", str(value).strip())


PhoneNumber = Annotated[
    str,
    BeforeValidator(_normalize_phone),
    StringConstraints(
        min_length=9,
        max_length=16,
        strip_whitespace=True,
        pattern=r"^(\+?62|0)[2-9][0-9]{7,12}$",
    ),
]

TicketNumber = Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)]
PoliceNumber = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=20,
        strip_whitespace=True,
        pattern=r"^[A-Za-z0-9 .-]+$",
    ),
]
ReferenceNumber = Annotated[str, StringConstraints(min_length=1, max_length=64, strip_whitespace=True)]
ModuleName = Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)]
RoleName = Annotated[str, StringConstraints(min_length=1, max_length=20, strip_whitespace=True)]
IpAddress = Annotated[
    str,
    StringConstraints(
        min_length=7,
        max_length=45,
        pattern=r"^[0-9A-Fa-f:.]+$",
    ),
]
