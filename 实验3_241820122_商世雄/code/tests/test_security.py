"""Role isolation, resource ownership, session revocation and password storage."""

import pytest

from stay.domain import BusinessError
from stay.security import hash_password, verify_password
from tests.conftest import command


def illegal_action(app, token, operation, order):
    actions = {
        "read": lambda: app.bookings.get(token, order["id"]),
        "cancel": lambda: app.bookings.transition(token, order["id"], "cancel", 1, "bad-cancel"),
        "confirm": lambda: app.bookings.transition(token, order["id"], "confirm", 1, "bad-confirm"),
        "force": lambda: app.bookings.transition(
            token, order["id"], "force_cancel", 1, "bad-force", "reason"
        ),
        "calendar": lambda: app.catalog.set_calendar(
            token, 1, "2026-11-15", "2026-11-17", 10, "399"
        ),
        "rooms": lambda: app.catalog.create_room(token, 1, "unauthorized", 2, 1),
        "hotel": lambda: app.catalog.set_status(token, 1, "CLOSED", "unauthorized"),
        "staff": lambda: app.auth.create_staff(token, "newstaff", "Newpass2026!", "staff", 1),
        "enable": lambda: app.auth.set_enabled(token, 2, False),
        "stats": lambda: app.reports.statistics(token, "2026-11-01", "2026-11-30"),
        "diagnose": lambda: app.reports.diagnose(token),
        "contact": lambda: app.bookings.update_contact(
            token, order["id"], "bad", "13800138001", 1, "bad-contact"
        ),
        "create": lambda: app.bookings.create(token, command(app), "bad-create"),
    }
    actions[operation]()


DENIED = (
    [
        ("customer2", action)
        for action in [
            "read",
            "cancel",
            "confirm",
            "force",
            "calendar",
            "rooms",
            "hotel",
            "staff",
            "enable",
            "stats",
            "diagnose",
            "contact",
        ]
    ]
    + [
        ("staff2", action)
        for action in [
            "read",
            "cancel",
            "confirm",
            "force",
            "calendar",
            "rooms",
            "hotel",
            "staff",
            "enable",
            "contact",
            "create",
        ]
    ]
    + [
        ("admin", action)
        for action in ["cancel", "confirm", "rooms", "calendar", "contact", "create"]
    ]
    + [("guest", action) for action in ["read", "cancel", "confirm", "calendar", "stats"]]
)


@pytest.mark.parametrize(("account", "operation"), DENIED)
def test_illegal_requests_leave_business_data_unchanged(app, sessions, account, operation):
    order = app.bookings.create(sessions["customer"], command(app), "legitimate")
    with app.database.read() as conn:
        before = [
            tuple(r) for r in conn.execute("SELECT * FROM room_day ORDER BY room_type_id,stay_date")
        ]
    token = sessions.get(account, "forged-session-token")
    with pytest.raises(BusinessError):
        illegal_action(app, token, operation, order)
    assert app.bookings.get(sessions["customer"], order["id"])["version"] == 1
    with app.database.read() as conn:
        assert before == [
            tuple(r) for r in conn.execute("SELECT * FROM room_day ORDER BY room_type_id,stay_date")
        ]


def test_independent_password_salts():
    left, right = hash_password("Strong2026!"), hash_password("Strong2026!")
    assert left != right and "Strong2026!" not in left
    assert verify_password("Strong2026!", left)
    assert not verify_password("incorrect", left)
    assert not verify_password("anything", "malformed")


def test_disable_account_revokes_existing_sessions(app, sessions):
    staff = app.auth.current(sessions["staff"])
    app.auth.set_enabled(sessions["admin"], staff.id, False)
    with pytest.raises(BusinessError):
        app.auth.current(sessions["staff"])
    with pytest.raises(BusinessError):
        app.auth.login("staff", "Staff2026!")


def test_customer_log_scope_and_no_phone_leak(app, sessions):
    app.bookings.create(sessions["customer"], command(app), "one")
    assert app.audit.query(sessions["customer"])
    assert not app.audit.query(sessions["customer2"])
    assert not app.audit.query(sessions["staff2"])
    assert "13800138000" not in str(app.audit.query(sessions["admin"]))


def test_logout_and_expiry(app, sessions):
    app.auth.logout(sessions["customer"])
    with pytest.raises(BusinessError):
        app.auth.current(sessions["customer"])
    app.clock.advance(hours=8)
    with pytest.raises(BusinessError):
        app.auth.current(sessions["staff"])
