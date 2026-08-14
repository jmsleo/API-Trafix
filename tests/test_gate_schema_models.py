"""Schema tests for the gate-cycle model changes.

Pure metadata introspection — no database required. These pin the contract the
migration SQL (``migrations/2026_08_14_gate_cycle_schema.sql``) and the
migration-completeness check in ``conftest.py`` are expected to uphold.
"""

from api_trafix.models import Gate, GateEvent, Member, ParkingRate, ParkTransaction


def _column(model, name):
    columns = model.__table__.columns
    assert name in columns, f"missing column {name} on {model.__tablename__}"
    return columns[name]


def test_parking_rates_has_flat_mode_fields():
    for name in ("grace_period_minutes", "ticket_charge", "stay_charge"):
        column = _column(ParkingRate, name)
        assert column.type.python_type is int
        assert column.nullable is True


def test_park_transactions_has_gate_cycle_columns():
    for name in (
        "card_number",
        "payment_status",
        "payment_type",
        "paid_at",
        "duration",
        "plate_out",
        "keterangan",
        "cam_in",
        "camin_lpr",
        "cam_out",
        "camout_lpr",
        "cam_payment",
    ):
        _column(ParkTransaction, name)

    assert _column(ParkTransaction, "payment_type").default.arg == "cash"
    assert _column(ParkTransaction, "cam_in").default.arg == "-"
    assert _column(ParkTransaction, "paid_at").type.python_type is not None


def test_park_transactions_relaxed_not_null_columns():
    for name in ("police_number", "entry_operator_id", "entry_shift_id"):
        assert _column(ParkTransaction, name).nullable is True


def test_gates_have_gate_code():
    column = _column(Gate, "gate_code")
    assert column.nullable is True
    assert column.unique is True


def test_members_have_card_number():
    column = _column(Member, "card_number")
    assert column.nullable is True
    assert column.unique is True


def test_gate_event_table_shape():
    assert GateEvent.__tablename__ == "gate_events"
    for name in (
        "id",
        "ts",
        "source",
        "gate_code",
        "topic",
        "method",
        "ticket_number",
        "detail",
    ):
        _column(GateEvent, name)
    assert _column(GateEvent, "source").nullable is False
    assert _column(GateEvent, "ticket_number").nullable is True
