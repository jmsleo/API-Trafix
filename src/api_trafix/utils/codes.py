import random
from datetime import datetime, timezone

MEMBER_CODE_PREFIX = "FP"
TICKET_PREFIX = "TKT"
REFERENCE_PREFIX = "PAY"


def _date_part() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def generate_member_code() -> str:
    return f"{MEMBER_CODE_PREFIX}-{_date_part()}-{random.randint(0, 9999):04d}"


def generate_ticket_number() -> str:
    return f"{TICKET_PREFIX}-{_date_part()}-{random.randint(0, 999999):06d}"


def generate_reference_number() -> str:
    return f"{REFERENCE_PREFIX}-{_date_part()}-{datetime.now(timezone.utc).strftime('%H%M%S')}-{random.randint(0, 9999):04d}"
