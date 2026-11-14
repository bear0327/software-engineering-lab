"""Fresh file-backed database and a deterministic UTC clock for every test."""

from datetime import UTC, datetime

import pytest

from stay.application import Application
from stay.domain import BookingCommand, MutableClock


@pytest.fixture
def app(tmp_path):
    instance = Application(
        tmp_path / "test.sqlite3", MutableClock(datetime(2026, 11, 14, 2, tzinfo=UTC))
    )
    instance.seed_demo()
    return instance


@pytest.fixture
def sessions(app):
    return {
        name: app.auth.login(name, password)
        for name, password in [
            ("admin", "Admin2026!"),
            ("staff", "Staff2026!"),
            ("staff2", "Staff2026!"),
            ("customer", "Guest2026!"),
            ("customer2", "Guest2026!"),
        ]
    }


def command(app, room=1, start="2026-11-15", end="2026-11-17", rooms=1, guests=2):
    quote = app.pricing.quote(room, start, end, rooms, guests)
    return BookingCommand(
        room, start, end, rooms, guests, "测试顾客", "13800138000", quote["quote_id"]
    )
