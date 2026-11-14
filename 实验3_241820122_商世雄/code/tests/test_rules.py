"""Calendar limits, fixed statistics definitions and isolated restore."""

from dataclasses import replace

import pytest

from stay.__main__ import restore_to_new_file
from stay.application import Application
from stay.domain import BookingCommand, BusinessError, cents, nights, positive_int
from tests.conftest import command


@pytest.mark.parametrize("value", [0, -1, True, "1.5", "abc", None])
def test_invalid_integer(value):
    with pytest.raises(BusinessError):
        positive_int(value, "数量")


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "12.345", "bad"])
def test_invalid_price(value):
    with pytest.raises(BusinessError):
        cents(value)


def test_night_interval():
    assert nights("2026-11-01", "2026-11-03") == ["2026-11-01", "2026-11-02"]
    with pytest.raises(BusinessError):
        nights("2026-11-03", "2026-11-03")


def test_calendar_cannot_reduce_below_held_stock(app, sessions):
    app.bookings.create(sessions["customer"], command(app, rooms=2), "new")
    with pytest.raises(BusinessError):
        app.catalog.set_calendar(sessions["staff"], 1, "2026-11-15", "2026-11-17", 1, "299")
    assert app.reports.diagnose(sessions["admin"])["ok"]


def test_sold_out_allows_shrink_but_not_increase(app, sessions):
    order = app.bookings.create(sessions["customer"], command(app), "new")
    app.catalog.set_calendar(sessions["staff"], 1, "2026-11-15", "2026-11-17", 10, "299", True)
    with pytest.raises(BusinessError):
        app.bookings.quote_modification(
            sessions["customer"], order["id"], 1, "2026-11-15", "2026-11-17", 2, 2
        )
    quote = app.bookings.quote_modification(
        sessions["customer"], order["id"], 1, "2026-11-15", "2026-11-16", 1, 2
    )
    new = BookingCommand(
        1, "2026-11-15", "2026-11-16", 1, 2, "test", "13800138000", quote["quote_id"]
    )
    app.bookings.modify(sessions["customer"], order["id"], new, 1, "shrink")
    assert app.reports.diagnose(sessions["admin"])["ok"]


def test_closed_hotel_retains_orders_until_individual_handling(app, sessions):
    order = app.bookings.create(sessions["customer"], command(app), "new")
    app.catalog.set_status(sessions["admin"], 1, "CLOSED", "临时检修")
    assert app.bookings.get(sessions["customer"], order["id"])["status"] == "PENDING"
    with pytest.raises(BusinessError):
        app.pricing.quote(1, "2026-11-15", "2026-11-17", 1, 2)
    app.bookings.transition(
        sessions["admin"], order["id"], "force_cancel", 1, "exception", "临时检修"
    )
    tasks = app.reports.notifications(sessions["admin"])
    assert len(tasks) == 1
    app.reports.mark_notification(sessions["admin"], tasks[0]["id"], True)
    assert app.reports.notifications(sessions["admin"])[0]["state"] == "DONE"


def test_statistics_three_orders_nine_room_nights(app, sessions):
    orders = []
    for index, (rooms, start, end) in enumerate(
        [
            (2, "2026-11-15", "2026-11-18"),
            (1, "2026-11-16", "2026-11-17"),
            (1, "2026-11-17", "2026-11-19"),
        ]
    ):
        row = app.bookings.create(
            sessions["customer"], command(app, rooms=rooms, start=start, end=end), str(index)
        )
        orders.append(
            app.bookings.transition(sessions["staff"], row["id"], "confirm", 1, f"confirm-{index}")
        )
    result = app.reports.statistics(sessions["staff"], "2026-11-15", "2026-11-17")
    assert result["orders"] == 3 and result["room_nights"] == 9
    assert app.reports.statistics(sessions["staff"], "2026-11-15", "2026-11-15")["room_nights"] == 6
    assert app.reports.statistics(sessions["staff"], "2026-11-17", "2026-11-17")["room_nights"] == 2
    assert app.reports.statistics(sessions["staff2"], "2026-11-15", "2026-11-17")["orders"] == 0


def test_backup_restore_to_separate_database(app, sessions, tmp_path):
    app.bookings.create(sessions["customer"], command(app), "new")
    manifest = app.jobs.backup(sessions["admin"])
    backup = app.jobs.backup_dir / manifest["file"]
    restored = tmp_path / "recovered.sqlite3"
    assert restore_to_new_file(backup, restored)["ok"]
    recovered = Application(restored, app.clock)
    admin = recovered.auth.login("admin", "Admin2026!")
    assert recovered.reports.diagnose(admin)["ok"]
    with pytest.raises(ValueError):
        restore_to_new_file(backup, restored)


def test_contact_change_confirmed_does_not_reset_clock(app, sessions):
    row = app.bookings.create(sessions["customer"], command(app), "new")
    row = app.bookings.transition(sessions["staff"], row["id"], "confirm", 1, "confirm")
    app.clock.advance(minutes=5)
    result = app.bookings.update_contact(
        sessions["customer"], row["id"], "新联系人", "13800138001", 2, "contact"
    )
    assert result["status"] == "CONFIRMED" and result["expires_at"] == row["expires_at"]


def test_modified_quote_failure_keeps_original(app, sessions):
    row = app.bookings.create(sessions["customer"], command(app), "new")
    quote = app.bookings.quote_modification(
        sessions["customer"], row["id"], 1, "2026-11-15", "2026-11-18", 1, 2
    )
    app.catalog.set_calendar(sessions["staff"], 1, "2026-11-17", "2026-11-18", 0, "299")
    changed = replace(command(app), check_out="2026-11-18", accepted_quote=quote["quote_id"])
    with pytest.raises(BusinessError):
        app.bookings.modify(sessions["customer"], row["id"], changed, 1, "modify")
    assert app.bookings.get(sessions["customer"], row["id"]) == row


def test_undated_browse_and_price_filter(app):
    rows = app.pricing.search("南京")
    assert rows and all("total_cents" not in row for row in rows)
    with pytest.raises(BusinessError):
        app.pricing.search("南京", maximum=10000)
    assert (
        app.pricing.search("南京", "2026-11-15", "2026-11-17", maximum=55000)[0]["room_type_id"]
        == 3
    )


@pytest.mark.parametrize("minutes,success", [(479, True), (480, False)])
def test_confirmed_cancellation_cutoff(app, sessions, minutes, success):
    row = app.bookings.create(
        sessions["customer"], command(app, start="2026-11-14", end="2026-11-16"), "new"
    )
    app.bookings.transition(sessions["staff"], row["id"], "confirm", 1, "confirm")
    app.clock.advance(minutes=minutes)
    token = app.auth.login("customer", "Guest2026!")
    if success:
        assert (
            app.bookings.transition(token, row["id"], "cancel", 2, "cancel")["status"]
            == "CANCELLED"
        )
    else:
        with pytest.raises(BusinessError) as error:
            app.bookings.transition(token, row["id"], "cancel", 2, "cancel")
        assert error.value.code == "CANCEL_CUTOFF"
