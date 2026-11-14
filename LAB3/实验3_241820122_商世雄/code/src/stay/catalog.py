"""Hotel approval, room types and daily supply/price administration."""

from __future__ import annotations

import sqlite3

from stay.audit import AuditService, ensure_admin
from stay.database import Database
from stay.domain import (
    Clock,
    Role,
    cents,
    nights,
    nonnegative_int,
    phone,
    positive_int,
    require,
    text,
    timezone,
)
from stay.security import AuthorizationPolicy, AuthService


class CatalogService:
    def __init__(self, database: Database, auth: AuthService, audit: AuditService, clock: Clock):
        self.database, self.auth, self.audit, self.clock = database, auth, audit, clock

    def create_hotel(
        self,
        token: str,
        name: str,
        city: str,
        address: str,
        contact: str,
        zone: str = "Asia/Shanghai",
    ) -> int:
        name, city, address = text(name, "酒店名称"), text(city, "城市"), text(address, "地址", 240)
        contact = phone(contact)
        timezone(zone)
        with self.database.transaction() as connection:
            actor = ensure_admin(connection, self.auth, token)
            cursor = connection.execute(
                "INSERT INTO hotel(name,city,address,contact,time_zone,status) "
                "VALUES(?,?,?,?,?,'PENDING')",
                (name, city, address, contact, zone),
            )
            self.audit.append(
                connection,
                actor,
                "HOTEL_CREATE",
                str(cursor.lastrowid),
                after="PENDING",
                scope={"hotel_id": cursor.lastrowid},
            )
            return cursor.lastrowid

    def list_hotels(self, token: str = "", city: str = "") -> list[dict]:
        with self.database.read() as connection:
            actor = self.auth.resolve(connection, token) if token else None
            clauses, args = ["1=1"], []
            if not actor or actor.role == Role.CUSTOMER:
                clauses.append("status='OPEN'")
            elif actor.role == Role.STAFF:
                clauses.append("id=?")
                args.append(actor.hotel_id)
            if city:
                clauses.append("city=?")
                args.append(city.strip())
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM hotel WHERE " + " AND ".join(clauses) + " ORDER BY id",
                    args,
                )
            ]

    def set_status(self, token: str, hotel_id: int, status: str, reason: str) -> None:
        require(status in ("OPEN", "CLOSED"), "INVALID_INPUT", "酒店状态无效")
        reason = text(reason, "处理原因", 500)
        with self.database.transaction() as connection:
            actor = ensure_admin(connection, self.auth, token)
            hotel = connection.execute("SELECT * FROM hotel WHERE id=?", (hotel_id,)).fetchone()
            require(hotel is not None, "NOT_FOUND", "酒店不存在")
            connection.execute(
                "UPDATE hotel SET status=?,version=version+1 WHERE id=?", (status, hotel_id)
            )
            self.audit.append(
                connection,
                actor,
                "HOTEL_STATUS",
                str(hotel_id),
                hotel["status"],
                status,
                reason,
                {"hotel_id": hotel_id},
            )
            # Closing never rewrites all orders. The administrator handles each
            # affected booking separately, with a reason and notification task.

    def create_room(self, token: str, hotel_id: int, name: str, capacity: int, total: int) -> int:
        capacity, total = positive_int(capacity, "可住人数", 20), positive_int(total, "房间总数")
        name = text(name, "房型名称", 80)
        with self.database.transaction() as connection:
            actor = self.auth.resolve(connection, token)
            AuthorizationPolicy.role(actor, Role.STAFF)
            AuthorizationPolicy.hotel(actor, hotel_id)
            require(
                connection.execute("SELECT id FROM hotel WHERE id=?", (hotel_id,)).fetchone()
                is not None,
                "NOT_FOUND",
                "酒店不存在",
            )
            require(
                connection.execute(
                    "SELECT id FROM room_type WHERE hotel_id=? AND name=?", (hotel_id, name)
                ).fetchone()
                is None,
                "CONFLICT",
                "本酒店已有同名房型",
            )
            cursor = connection.execute(
                "INSERT INTO room_type(hotel_id,name,capacity,total_rooms) VALUES(?,?,?,?)",
                (hotel_id, name, capacity, total),
            )
            self.audit.append(
                connection,
                actor,
                "ROOM_CREATE",
                str(cursor.lastrowid),
                scope={"hotel_id": hotel_id},
            )
            return cursor.lastrowid

    def list_rooms(self, token: str, hotel_id: int | None = None) -> list[dict]:
        with self.database.read() as connection:
            actor = self.auth.resolve(connection, token)
            AuthorizationPolicy.role(actor, Role.STAFF, Role.ADMIN)
            if actor.role == Role.STAFF:
                hotel_id = actor.hotel_id
            sql = "SELECT r.*,h.name hotel_name FROM room_type r JOIN hotel h ON h.id=r.hotel_id"
            args = []
            if hotel_id is not None:
                sql += " WHERE r.hotel_id=?"
                args.append(hotel_id)
            return [dict(row) for row in connection.execute(sql + " ORDER BY r.id", args)]

    def update_room(
        self, token: str, room_id: int, name: str, capacity: int, total: int, version: int
    ) -> None:
        capacity, total = positive_int(capacity, "容量", 20), positive_int(total, "房间总数")
        with self.database.transaction() as connection:
            actor = self.auth.resolve(connection, token)
            AuthorizationPolicy.role(actor, Role.STAFF)
            room = self._room(connection, room_id)
            AuthorizationPolicy.hotel(actor, room["hotel_id"])
            require(room["version"] == version, "STALE_VERSION", "房型已被修改，请刷新")
            highest = connection.execute(
                "SELECT COALESCE(MAX(supply),0) FROM room_day WHERE room_type_id=?", (room_id,)
            ).fetchone()[0]
            require(total >= highest, "CAPACITY_CONFLICT", "总房数不能小于日历中的供给")
            conflict = connection.execute(
                "SELECT id FROM room_type WHERE hotel_id=? AND name=? AND id!=?",
                (room["hotel_id"], name, room_id),
            ).fetchone()
            require(conflict is None, "CONFLICT", "本酒店已有同名房型")
            connection.execute(
                "UPDATE room_type SET name=?,capacity=?,total_rooms=?,version=version+1 WHERE id=?",
                (text(name, "房型名称", 80), capacity, total, room_id),
            )
            self.audit.append(
                connection, actor, "ROOM_UPDATE", str(room_id), scope={"hotel_id": room["hotel_id"]}
            )

    @staticmethod
    def _room(connection: sqlite3.Connection, room_id: int) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM room_type WHERE id=?", (room_id,)).fetchone()
        require(row is not None, "NOT_FOUND", "房型不存在")
        return row

    def set_calendar(
        self,
        token: str,
        room_id: int,
        start: str,
        end: str,
        supply: int,
        price: str,
        sold_out: bool = False,
        expected_version: int | None = None,
    ) -> None:
        dates = nights(start, end)
        supply, price_value = nonnegative_int(supply, "供给总量"), cents(price)
        require(isinstance(sold_out, bool), "INVALID_INPUT", "停售标记无效")
        with self.database.transaction() as connection:
            actor = self.auth.resolve(connection, token)
            AuthorizationPolicy.role(actor, Role.STAFF)
            room = self._room(connection, room_id)
            AuthorizationPolicy.hotel(actor, room["hotel_id"])
            require(supply <= room["total_rooms"], "CAPACITY_CONFLICT", "每日供给不能超过房间总数")
            for day in dates:
                old = connection.execute(
                    "SELECT * FROM room_day WHERE room_type_id=? AND stay_date=?", (room_id, day)
                ).fetchone()
                if expected_version is not None:
                    require(
                        len(dates) == 1 and old is not None and old["version"] == expected_version,
                        "STALE_VERSION",
                        "日历已被修改，请刷新",
                    )
                require(
                    old is None or supply >= old["reserved"],
                    "CAPACITY_CONFLICT",
                    f"{day}供给不足覆盖已占用",
                )
                connection.execute(
                    "INSERT INTO room_day(room_type_id,stay_date,supply,price_cents,sold_out) "
                    "VALUES(?,?,?,?,?) "
                    "ON CONFLICT(room_type_id,stay_date) DO UPDATE SET supply=excluded.supply,"
                    "price_cents=excluded.price_cents,sold_out=excluded.sold_out,"
                    "version=room_day.version+1",
                    (room_id, day, supply, price_value, int(sold_out)),
                )
            self.audit.append(
                connection,
                actor,
                "CALENDAR_UPDATE",
                f"{room_id}:{start}:{end}",
                reason=f"供给{supply}；价格{price_value}分；停售{sold_out}",
                scope={"hotel_id": room["hotel_id"]},
            )

    def calendar(self, token: str, room_id: int, start: str, end: str) -> list[dict]:
        dates = nights(start, end)
        with self.database.read() as connection:
            actor = self.auth.resolve(connection, token)
            AuthorizationPolicy.role(actor, Role.STAFF, Role.ADMIN)
            room = self._room(connection, room_id)
            AuthorizationPolicy.hotel(actor, room["hotel_id"])
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT *,supply-reserved available FROM room_day WHERE room_type_id=? "
                    "AND stay_date>=? AND stay_date<? ORDER BY stay_date",
                    (room_id, dates[0], end),
                )
            ]
