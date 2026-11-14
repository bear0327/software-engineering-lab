"""Exercise actual Tk widgets and page callbacks with isolated test data."""

import pytest

from stay.desktop import Desktop
from stay.pages import (
    CalendarPage,
    HotelsPage,
    LogsPage,
    NotificationsPage,
    OrdersPage,
    RoomsPage,
    SearchPage,
    StaffPage,
    StatsPage,
    SystemPage,
)


@pytest.fixture
def window(app):
    desktop = Desktop(app, start_worker=False)
    desktop.withdraw()
    yield desktop
    desktop.close()


@pytest.mark.parametrize(
    "account,pages",
    [
        ("customer", [SearchPage, OrdersPage, LogsPage]),
        ("staff", [OrdersPage, RoomsPage, CalendarPage, StatsPage, LogsPage, NotificationsPage]),
        ("staff2", [OrdersPage, RoomsPage, CalendarPage, StatsPage, LogsPage, NotificationsPage]),
        (
            "admin",
            [HotelsPage, StaffPage, OrdersPage, StatsPage, LogsPage, NotificationsPage, SystemPage],
        ),
    ],
)
def test_all_role_pages_construct_and_refresh(window, sessions, account, pages):
    window.token = sessions[account]
    window.actor = window.app.auth.current(window.token)
    window.shell()
    for page_type in pages:
        window.show_page(page_type)
        window.update_idletasks()
        assert window.page.winfo_exists()
    if account == "staff2":
        window.show_page(CalendarPage)
        assert window.page.room.get() == "3"


def test_gui_query_book_confirm_cancel(window, sessions, monkeypatch):
    monkeypatch.setattr("stay.pages.messagebox.askyesno", lambda *_a, **_k: True)
    monkeypatch.setattr("stay.pages.show_text", lambda *_a, **_k: None)
    window.token = sessions["customer"]
    window.actor = window.app.auth.current(window.token)
    window.shell()
    page = window.page
    page.table.tree.selection_set("0")
    monkeypatch.setattr(page, "form", lambda *_a: {"name": "界面测试", "phone": "13800138000"})
    page.book()
    page.book()  # Same accepted selection and contact must reuse the request key.
    assert len(window.app.bookings.list(window.token)) == 1
    window.token = sessions["staff"]
    window.actor = window.app.auth.current(window.token)
    window.shell()
    window.page.table.tree.selection_set("0")
    window.page.transition("confirm")
    window.token = sessions["customer"]
    window.actor = window.app.auth.current(window.token)
    window.shell()
    window.show_page(OrdersPage)
    window.page.table.tree.selection_set("0")
    window.page.transition("cancel")
    assert window.app.bookings.list(window.token)[0]["status"] == "CANCELLED"
