"""Order state, time boundaries, refunds of future nights and preserved prices."""

import sqlite3
from dataclasses import replace

import pytest

from stay.domain import BusinessError, Status, instant
from tests.conftest import command


def reserved(app, room=1):
    with app.database.read() as conn:
        return {
            r["stay_date"]: r["reserved"]
            for r in conn.execute("SELECT * FROM room_day WHERE room_type_id=?", (room,))
        }


def test_create_and_cancel(app, sessions):
    order = app.bookings.create(sessions["customer"], command(app), "new")
    assert order["status"] == Status.PENDING and len(order["nights"]) == 2
    assert reserved(app)["2026-11-15"] == 1
    assert reserved(app)["2026-11-17"] == 0
    cancelled = app.bookings.transition(sessions["customer"], order["id"], "cancel", 1, "cancel")
    assert cancelled["status"] == Status.CANCELLED
    assert reserved(app)["2026-11-15"] == 0
    replay = app.bookings.transition(sessions["customer"], order["id"], "cancel", 1, "cancel")
    assert replay == cancelled and reserved(app)["2026-11-15"] == 0
    assert app.reports.diagnose(sessions["admin"])["ok"]


def test_checkout_preserves_historical_stock(app, sessions):
    order = app.bookings.create(sessions["customer"], command(app), "new")
    order = app.bookings.transition(sessions["staff"], order["id"], "confirm", 1, "confirm")
    assert reserved(app)["2026-11-15"] == 1
    app.clock.advance(days=1)
    staff = app.auth.login("staff", "Staff2026!")
    order = app.bookings.transition(staff, order["id"], "check_in", 2, "in", "现场核验通过")
    assert order["status"] == Status.CHECKED_IN
    app.clock.advance(days=2)
    # Login again because sessions last eight hours.
    staff = app.auth.login("staff", "Staff2026!")
    order = app.bookings.transition(staff, order["id"], "check_out", 3, "out")
    assert order["status"] == Status.CHECKED_OUT
    assert reserved(app)["2026-11-15"] == reserved(app)["2026-11-16"] == 1
    assert all(n["allocation_state"] == "CONSUMED" for n in order["nights"])


def test_strict_expiry_commits_before_rejection(app, sessions):
    order = app.bookings.create(sessions["customer"], command(app), "new")
    app.clock.advance(minutes=30)
    with pytest.raises(BusinessError, match="超时"):
        app.bookings.transition(sessions["staff"], order["id"], "confirm", 1, "confirm")
    assert app.bookings.get(sessions["customer"], order["id"])["status"] == Status.EXPIRED
    assert reserved(app)["2026-11-15"] == 0
    app.jobs.run()
    assert reserved(app)["2026-11-15"] == 0


def test_one_second_before_deadline(app, sessions):
    order = app.bookings.create(sessions["customer"], command(app), "new")
    app.clock.advance(minutes=29, seconds=59)
    result = app.bookings.transition(sessions["staff"], order["id"], "confirm", 1, "confirm")
    assert result["status"] == Status.CONFIRMED
    app.clock.advance(seconds=2)
    assert app.jobs.run()["lifecycle_changes"] == 0


def test_no_show_releases_only_future_nights(app, sessions):
    order = app.bookings.create(
        sessions["customer"], command(app, start="2026-11-14", end="2026-11-17"), "new"
    )
    app.bookings.transition(sessions["staff"], order["id"], "confirm", 1, "confirm")
    app.clock.advance(hours=14)  # 00:00 next day in Asia/Shanghai.
    assert app.jobs.run()["lifecycle_changes"] == 1
    assert reserved(app)["2026-11-14"] == 1
    assert reserved(app)["2026-11-15"] == reserved(app)["2026-11-16"] == 0
    customer = app.auth.login("customer", "Guest2026!")
    assert app.bookings.get(customer, order["id"])["status"] == Status.NO_SHOW


def test_overlap_shrink_does_not_block_itself(app, sessions):
    app.catalog.set_calendar(sessions["staff"], 1, "2026-11-15", "2026-11-17", 1, "299")
    order = app.bookings.create(sessions["customer"], command(app), "new")
    app.clock.advance(minutes=5)
    quote = app.bookings.quote_modification(
        sessions["customer"], order["id"], 1, "2026-11-15", "2026-11-16", 1, 2
    )
    changed = replace(
        command(app, room=2),
        room_type_id=1,
        check_in="2026-11-15",
        check_out="2026-11-16",
        accepted_quote=quote["quote_id"],
    )
    result = app.bookings.modify(sessions["customer"], order["id"], changed, 1, "modify")
    assert reserved(app)["2026-11-15"] == 1 and reserved(app)["2026-11-16"] == 0
    assert result["total_cents"] == 29900
    assert (instant(result["expires_at"]) - app.clock.now()).total_seconds() == 1800


def test_price_change_requires_acceptance(app, sessions):
    original = command(app)
    app.catalog.set_calendar(sessions["staff"], 1, "2026-11-15", "2026-11-17", 10, "359")
    with pytest.raises(BusinessError) as exc:
        app.bookings.create(sessions["customer"], original, "new")
    assert exc.value.code == "PRICE_CHANGED"
    assert reserved(app)["2026-11-15"] == 0
    order = app.bookings.create(sessions["customer"], command(app), "new-accepted")
    app.catalog.set_calendar(sessions["staff"], 1, "2026-11-15", "2026-11-17", 10, "399")
    assert app.bookings.get(sessions["customer"], order["id"])["total_cents"] == 71800


def test_key_conflict_and_original_result(app, sessions):
    original = command(app)
    first = app.bookings.create(sessions["customer"], original, "same")
    assert app.bookings.create(sessions["customer"], original, "same") == first
    with pytest.raises(BusinessError) as exc:
        app.bookings.create(sessions["customer"], replace(original, contact_name="另一人"), "same")
    assert exc.value.code == "REQUEST_KEY_CONFLICT"


def test_mid_transaction_failure_rolls_back(app, sessions, monkeypatch):
    original = command(app)

    def fail(*_args):
        raise sqlite3.OperationalError("simulated disk write failure")

    monkeypatch.setattr(app.bookings, "_save_nights", fail)
    with pytest.raises(sqlite3.OperationalError):
        app.bookings.create(sessions["customer"], original, "fault")
    assert reserved(app)["2026-11-15"] == 0
    with app.database.read() as conn:
        assert conn.execute("SELECT count(*) FROM booking").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM request_record").fetchone()[0] == 0


@pytest.mark.parametrize("action", ["confirm", "check_in", "check_out", "reject"])
def test_terminal_orders_cannot_resume(app, sessions, action):
    order = app.bookings.create(sessions["customer"], command(app), "new")
    app.bookings.transition(sessions["customer"], order["id"], "cancel", 1, "cancel")
    with pytest.raises(BusinessError):
        app.bookings.transition(sessions["staff"], order["id"], action, 2, action, "现场核验通过")
    assert reserved(app)["2026-11-15"] == 0
