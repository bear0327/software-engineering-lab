"""Real threads and independent SQLite connections race for the last room."""

import threading
from concurrent.futures import ThreadPoolExecutor

from stay.domain import BusinessError
from tests.conftest import command


def test_twenty_customers_last_room(app, sessions):
    app.catalog.set_calendar(sessions["staff"], 1, "2026-11-15", "2026-11-17", 1, "299")
    selected = command(app)
    tokens = []
    for index in range(20):
        account = f"race{index}"
        app.auth.register(account, "Race2026!", account)
        tokens.append(app.auth.login(account, "Race2026!"))
    gate = threading.Barrier(20)

    def reserve(index):
        gate.wait(timeout=20)
        try:
            return ("SUCCESS", app.bookings.create(tokens[index], selected, f"race-{index}")["id"])
        except BusinessError as error:
            return error.code, None

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(reserve, range(20)))
    assert sum(code == "SUCCESS" for code, _ in results) == 1
    assert sum(code == "NO_ROOM" for code, _ in results) == 19
    assert app.reports.diagnose(sessions["admin"])["ok"]
    with app.database.read() as conn:
        assert conn.execute("SELECT count(*) FROM booking").fetchone()[0] == 1
        assert conn.execute(
            "SELECT MIN(reserved),MAX(reserved) FROM room_day WHERE "
            "room_type_id=1 AND stay_date IN ('2026-11-15','2026-11-16')"
        ).fetchone()[:] == (1, 1)


def test_same_key_twenty_retries_has_one_effect(app, sessions):
    selected = command(app)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(
            pool.map(
                lambda _: app.bookings.create(sessions["customer"], selected, "shared"), range(20)
            )
        )
    assert len({r["id"] for r in results}) == 1
    with app.database.read() as conn:
        assert (
            conn.execute(
                "SELECT reserved FROM room_day WHERE room_type_id=1 AND stay_date='2026-11-15'"
            ).fetchone()[0]
            == 1
        )


def test_confirm_cancel_race_is_a_legal_sequence(app, sessions):
    order = app.bookings.create(sessions["customer"], command(app), "new")
    gate = threading.Barrier(2)

    def operate(account, action):
        gate.wait(timeout=10)
        try:
            return app.bookings.transition(sessions[account], order["id"], action, 1, action)[
                "status"
            ]
        except BusinessError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        confirm = pool.submit(operate, "staff", "confirm")
        cancel = pool.submit(operate, "customer", "cancel")
        results = [confirm.result(), cancel.result()]
    final = app.bookings.get(sessions["customer"], order["id"])
    assert final["status"] in ("CONFIRMED", "CANCELLED")
    assert sum(r == "STALE_VERSION" or r == "INVALID_STATE" for r in results) == 1
    assert app.reports.diagnose(sessions["admin"])["ok"]
