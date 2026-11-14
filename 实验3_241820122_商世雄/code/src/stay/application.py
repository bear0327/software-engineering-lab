"""Composition root and deterministic demonstration data."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from stay.audit import AuditService
from stay.booking import BookingService
from stay.catalog import CatalogService
from stay.database import Database
from stay.domain import Clock
from stay.inventory import PricingService
from stay.maintenance import LifecycleJob
from stay.reports import ReportService
from stay.security import AuthService


class Application:
    def __init__(self, path: str | Path, clock: Clock | None = None):
        self.clock = clock or Clock()
        self.database = Database(path)
        self.auth = AuthService(self.database, self.clock)
        self.audit = AuditService(self.database, self.auth, self.clock)
        self.catalog = CatalogService(self.database, self.auth, self.audit, self.clock)
        self.pricing = PricingService(self.database, self.clock)
        self.bookings = BookingService(self.database, self.auth, self.audit, self.clock)
        self.reports = ReportService(self.database, self.auth, self.audit, self.clock)
        self.jobs = LifecycleJob(self.bookings, self.database.path.parent / "backups")

    def seed_demo(self) -> dict:
        """Initialize a fresh demo database; never reset an existing database."""
        with self.database.read() as connection:
            if connection.execute("SELECT id FROM app_user LIMIT 1").fetchone():
                return {"created": False}
        self.auth.bootstrap("admin", "Admin2026!")
        token = self.auth.login("admin", "Admin2026!")
        first = self.catalog.create_hotel(
            token, "南京泊岸酒店", "南京", "鼓楼区湖南路18号", "02580001234"
        )
        second = self.catalog.create_hotel(
            token, "秦淮栖居酒店", "南京", "秦淮区白鹭街29号", "02580005678"
        )
        self.catalog.set_status(token, first, "OPEN", "资料审核通过")
        self.catalog.set_status(token, second, "OPEN", "资料审核通过")
        self.auth.create_staff(token, "staff", "Staff2026!", "王前台", first)
        self.auth.create_staff(token, "staff2", "Staff2026!", "李前台", second)
        self.auth.register("customer", "Guest2026!", "商同学")
        self.auth.register("customer2", "Guest2026!", "测试顾客")
        staff = self.auth.login("staff", "Staff2026!")
        staff2 = self.auth.login("staff2", "Staff2026!")
        room1 = self.catalog.create_room(staff, first, "舒适大床房", 2, 10)
        room2 = self.catalog.create_room(staff, first, "城景双床房", 2, 8)
        room3 = self.catalog.create_room(staff2, second, "标准大床房", 2, 6)
        start = self.clock.now().astimezone(ZoneInfo("Asia/Shanghai")).date()
        end = start + timedelta(days=60)
        for session, room, total, price in [
            (staff, room1, 10, "299"),
            (staff, room2, 8, "359"),
            (staff2, room3, 6, "269"),
        ]:
            self.catalog.set_calendar(
                session, room, start.isoformat(), end.isoformat(), total, price
            )
        self.auth.logout(token)
        self.auth.logout(staff)
        self.auth.logout(staff2)
        return {"created": True, "hotels": [first, second], "rooms": [room1, room2, room3]}
