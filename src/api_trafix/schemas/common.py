from typing import Annotated

from pydantic import EmailStr, Field, StringConstraints

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]

Name = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
ShortName = Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)]
Code = Annotated[str, StringConstraints(min_length=1, max_length=20, strip_whitespace=True)]
Email = Annotated[EmailStr, StringConstraints(strip_whitespace=True)]
PhoneNumber = Annotated[str, StringConstraints(min_length=7, max_length=20, pattern=r"^\+?[0-9 ()-]+$")]

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
