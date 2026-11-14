"""Order lifecycle: validation, atomic stock changes and safe retries."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import timedelta

from stay.audit import AuditService, CommandExecutor
from stay.database import Database
from stay.domain import (
    Actor,
    BookingCommand,
    BusinessError,
    Clock,
    Role,
    Status,
    cutoff,
    instant,
    local_today,
    phone,
    require,
    stamp,
    text,
)
from stay.inventory import InventoryService, PricingService
from stay.security import AuthorizationPolicy, AuthService


class TransitionPolicy:
    @staticmethod
    def authorize(actor: Actor, action: str) -> None:
        roles = {
            "confirm": (Role.STAFF,),
            "reject": (Role.STAFF,),
            "check_in": (Role.STAFF,),
            "check_out": (Role.STAFF,),
            "cancel": (Role.CUSTOMER,),
            "force_cancel": (Role.ADMIN,),
        }
        require(action in roles, "INVALID_ACTION", "操作类型不存在")
        AuthorizationPolicy.role(actor, *roles[action])

    @staticmethod
    def target(row: sqlite3.Row, action: str, now, zone: str) -> Status:
        current = Status(row["status"])
        allowed = {
            "confirm": (Status.PENDING, Status.CONFIRMED),
            "reject": (Status.PENDING, Status.REJECTED),
            "check_in": (Status.CONFIRMED, Status.CHECKED_IN),
            "check_out": (Status.CHECKED_IN, Status.CHECKED_OUT),
        }
        if action in ("cancel", "force_cancel"):
            require(
                current in (Status.PENDING, Status.CONFIRMED), "INVALID_STATE", "当前订单不能取消"
            )
            if action == "cancel" and current == Status.CONFIRMED:
                require(
                    now < cutoff(row["check_in"], zone, 18),
                    "CANCEL_CUTOFF",
                    "已超过入住日18:00取消时限",
                )
            return Status.CANCELLED
        expected, target = allowed[action]
        require(current == expected, "INVALID_STATE", "当前订单状态不允许此操作，请刷新")
        today = local_today(now, zone)
        if action == "check_in":
            require(today == row["check_in"], "INVALID_DATE", "只能在计划入住日办理入住")
        if action == "check_out":
            require(today >= row["check_out"], "INVALID_DATE", "不支持提前退房")
        return target


class BookingService:
    def __init__(self, database: Database, auth: AuthService, audit: AuditService, clock: Clock):
        self.database, self.auth, self.audit, self.clock = database, auth, audit, clock
        self.pricing = PricingService(database, clock)
        self.inventory = InventoryService()
        self.commands = CommandExecutor(database, auth, audit, clock)

    @staticmethod
    def _row(connection: sqlite3.Connection, booking_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT b.*,h.time_zone,h.name hotel_name,r.name room_name FROM booking b "
            "JOIN hotel h ON h.id=b.hotel_id JOIN room_type r ON r.id=b.room_type_id WHERE b.id=?",
            (booking_id,),
        ).fetchone()
        require(row is not None, "NOT_FOUND", "订单不存在")
        return row

    def _view(self, connection: sqlite3.Connection, booking_id: str) -> dict:
        result = dict(self._row(connection, booking_id))
        result["nights"] = [
            dict(item)
            for item in connection.execute(
                "SELECT * FROM booking_night WHERE booking_id=? ORDER BY stay_date",
                (booking_id,),
            )
        ]
        return result

    def get(self, token: str, booking_id: str) -> dict:
        with self.database.read() as connection:
            actor = self.auth.resolve(connection, token)
            AuthorizationPolicy.booking(actor, self._row(connection, booking_id))
            return self._view(connection, booking_id)

    def list(
        self, token: str, status: str = "", hotel_id: int | None = None, offset: int = 0
    ) -> list[dict]:
        with self.database.read() as connection:
            actor = self.auth.resolve(connection, token)
            clauses, args = ["1=1"], []
            if actor.role == Role.CUSTOMER:
                clauses.append("b.customer_id=?")
                args.append(actor.id)
            elif actor.role == Role.STAFF:
                clauses.append("b.hotel_id=?")
                args.append(actor.hotel_id)
            if hotel_id is not None:
                if actor.role == Role.STAFF:
                    AuthorizationPolicy.hotel(actor, hotel_id)
                clauses.append("b.hotel_id=?")
                args.append(hotel_id)
            if status:
                require(status in list(Status), "INVALID_INPUT", "订单状态无效")
                clauses.append("b.status=?")
                args.append(status)
            args.append(max(0, int(offset)))
            rows = connection.execute(
                "SELECT b.*,h.name hotel_name,r.name room_name FROM booking b "
                "JOIN hotel h ON h.id=b.hotel_id JOIN room_type r ON r.id=b.room_type_id WHERE "
                + " AND ".join(clauses)
                + " ORDER BY b.created_at DESC,b.id LIMIT 200 OFFSET ?",
                args,
            )
            return [dict(row) for row in rows]

    def create(self, token: str, command: BookingCommand, request_key: str) -> dict:
        def apply(connection, actor):
            AuthorizationPolicy.role(actor, Role.CUSTOMER)
            command.validate()
            quote = self.pricing.calculate(
                connection,
                command.room_type_id,
                command.check_in,
                command.check_out,
                command.rooms,
                command.guests,
            )
            self._check_quote(command, quote)
            new = {(command.room_type_id, item["date"]): command.rooms for item in quote["nights"]}
            self.inventory.replace(connection, {}, new)
            booking_id, now = "HB" + uuid.uuid4().hex[:18].upper(), self.clock.now()
            connection.execute(
                "INSERT INTO booking(id,customer_id,hotel_id,room_type_id,check_in,check_out,rooms,"
                "guests,contact_name,contact_phone,total_cents,status,created_at,updated_at,"
                "pending_since,expires_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,'PENDING',?,?,?,?)",
                (
                    booking_id,
                    actor.id,
                    quote["hotel_id"],
                    command.room_type_id,
                    command.check_in,
                    command.check_out,
                    command.rooms,
                    command.guests,
                    command.contact_name.strip(),
                    command.contact_phone.strip(),
                    quote["total_cents"],
                    stamp(now),
                    stamp(now),
                    stamp(now),
                    stamp(now + timedelta(minutes=30)),
                ),
            )
            self._save_nights(connection, booking_id, command, quote)
            self.audit.append(
                connection,
                actor,
                "BOOKING_CREATE",
                booking_id,
                after=Status.PENDING,
                scope={"hotel_id": quote["hotel_id"], "customer_id": actor.id},
            )
            return {"ok": True, "booking": self._view(connection, booking_id)}

        return self.commands.execute(token, "create", request_key, asdict(command), apply)[
            "booking"
        ]

    @staticmethod
    def _check_quote(command: BookingCommand, quote: dict) -> None:
        if command.accepted_quote != quote["quote_id"]:
            raise BusinessError("PRICE_CHANGED", "价格已经变化，请重新查看并接受新报价", quote)

    @staticmethod
    def _save_nights(connection, booking_id: str, command: BookingCommand, quote: dict) -> None:
        connection.executemany(
            "INSERT INTO booking_night VALUES(?,?,?,?,?,'HELD')",
            [
                (booking_id, command.room_type_id, item["date"], item["unit_cents"], command.rooms)
                for item in quote["nights"]
            ],
        )

    def quote_modification(
        self,
        token: str,
        booking_id: str,
        room_id: int,
        start: str,
        end: str,
        rooms: int,
        guests: int,
    ) -> dict:
        with self.database.read() as connection:
            actor = self.auth.resolve(connection, token)
            row = self._row(connection, booking_id)
            AuthorizationPolicy.role(actor, Role.CUSTOMER)
            AuthorizationPolicy.booking(actor, row)
            require(row["status"] == Status.PENDING, "INVALID_STATE", "只有待确认订单允许改期")
            require(self.clock.now() < instant(row["expires_at"]), "EXPIRED", "确认时限已到")
            quote = self.pricing.calculate(
                connection,
                room_id,
                start,
                end,
                rooms,
                guests,
                self.inventory.allocations(connection, booking_id),
            )
            require(quote["hotel_id"] == row["hotel_id"], "INVALID_INPUT", "不支持跨酒店修改")
            return quote

    def modify(
        self, token: str, booking_id: str, command: BookingCommand, version: int, request_key: str
    ) -> dict:
        def apply(connection, actor):
            AuthorizationPolicy.role(actor, Role.CUSTOMER)
            row = self._row(connection, booking_id)
            AuthorizationPolicy.booking(actor, row)
            due = self.finalize_due(connection, row)
            if due:
                return due
            require(row["version"] == version, "STALE_VERSION", "订单已更新，请刷新后修改")
            require(row["status"] == Status.PENDING, "INVALID_STATE", "已确认后只能修改联系人")
            command.validate()
            old = self.inventory.allocations(connection, booking_id)
            quote = self.pricing.calculate(
                connection,
                command.room_type_id,
                command.check_in,
                command.check_out,
                command.rooms,
                command.guests,
                old,
            )
            require(quote["hotel_id"] == row["hotel_id"], "INVALID_INPUT", "不支持跨酒店修改")
            self._check_quote(command, quote)
            new = {(command.room_type_id, item["date"]): command.rooms for item in quote["nights"]}
            self.inventory.replace(connection, old, new)
            old_summary = json.dumps(
                {
                    "dates": [row["check_in"], row["check_out"]],
                    "room": row["room_type_id"],
                    "rooms": row["rooms"],
                    "total_cents": row["total_cents"],
                    "night_prices": [
                        {
                            "date": night["stay_date"],
                            "unit_cents": night["unit_price_cents"],
                            "quantity": night["quantity"],
                        }
                        for night in connection.execute(
                            "SELECT * FROM booking_night WHERE booking_id=? ORDER BY stay_date",
                            (booking_id,),
                        )
                    ],
                },
                ensure_ascii=False,
            )
            connection.execute("DELETE FROM booking_night WHERE booking_id=?", (booking_id,))
            self._save_nights(connection, booking_id, command, quote)
            now = self.clock.now()
            connection.execute(
                "UPDATE booking SET room_type_id=?,check_in=?,check_out=?,rooms=?,guests=?,"
                "contact_name=?,contact_phone=?,total_cents=?,version=version+1,updated_at=?,"
                "pending_since=?,expires_at=? WHERE id=?",
                (
                    command.room_type_id,
                    command.check_in,
                    command.check_out,
                    command.rooms,
                    command.guests,
                    command.contact_name.strip(),
                    command.contact_phone.strip(),
                    quote["total_cents"],
                    stamp(now),
                    stamp(now),
                    stamp(now + timedelta(minutes=30)),
                    booking_id,
                ),
            )
            self.audit.append(
                connection,
                actor,
                "BOOKING_MODIFY",
                booking_id,
                old_summary,
                "PENDING",
                scope=dict(row),
            )
            return {"ok": True, "booking": self._view(connection, booking_id)}

        payload = {"id": booking_id, "version": version, **asdict(command)}
        return self.commands.execute(token, "modify", request_key, payload, apply)["booking"]

    def update_contact(
        self, token: str, booking_id: str, name: str, telephone: str, version: int, request_key: str
    ) -> dict:
        def apply(connection, actor):
            AuthorizationPolicy.role(actor, Role.CUSTOMER)
            row = self._row(connection, booking_id)
            AuthorizationPolicy.booking(actor, row)
            due = self.finalize_due(connection, row)
            if due:
                return due
            require(row["version"] == version, "STALE_VERSION", "订单已更新，请刷新")
            require(
                row["status"] in (Status.PENDING, Status.CONFIRMED),
                "INVALID_STATE",
                "当前状态不能修改联系人",
            )
            now = self.clock.now()
            pending = row["status"] == Status.PENDING
            connection.execute(
                "UPDATE booking SET contact_name=?,contact_phone=?,version=version+1,updated_at=?,"
                "pending_since=?,expires_at=? WHERE id=?",
                (
                    text(name, "联系人", 50),
                    phone(telephone),
                    stamp(now),
                    stamp(now) if pending else row["pending_since"],
                    stamp(now + timedelta(minutes=30)) if pending else row["expires_at"],
                    booking_id,
                ),
            )
            self.audit.append(
                connection,
                actor,
                "CONTACT_UPDATE",
                booking_id,
                row["status"],
                row["status"],
                "联系人信息变更（隐私字段不记录原文）",
                dict(row),
            )
            return {"ok": True, "booking": self._view(connection, booking_id)}

        payload = {"id": booking_id, "name": name, "phone": telephone, "version": version}
        return self.commands.execute(token, "contact", request_key, payload, apply)["booking"]

    def transition(
        self,
        token: str,
        booking_id: str,
        action: str,
        version: int,
        request_key: str,
        reason: str = "",
    ) -> dict:
        def apply(connection, actor):
            row = self._row(connection, booking_id)
            AuthorizationPolicy.booking(actor, row)
            TransitionPolicy.authorize(actor, action)
            due = self.finalize_due(connection, row)
            if due:
                return due
            require(row["version"] == version, "STALE_VERSION", "订单已更新，请刷新")
            if action in ("reject", "force_cancel"):
                text(reason, "处理原因", 500)
            if action == "check_in":
                require(
                    reason.strip() == "现场核验通过",
                    "VERIFICATION_REQUIRED",
                    "请先记录现场核验通过",
                )
            target = TransitionPolicy.target(row, action, self.clock.now(), row["time_zone"])
            self._change_status(connection, row, target, actor, action, reason)
            return {"ok": True, "booking": self._view(connection, booking_id)}

        payload = {"id": booking_id, "action": action, "version": version, "reason": reason}
        return self.commands.execute(token, action, request_key, payload, apply)["booking"]

    def _change_status(
        self, connection, row, target: Status, actor: Actor | None, action: str, reason: str
    ) -> None:
        now = self.clock.now()
        if target in (Status.CANCELLED, Status.REJECTED, Status.EXPIRED, Status.NO_SHOW):
            self.inventory.release(connection, row["id"], local_today(now, row["time_zone"]))
        elif target == Status.CHECKED_OUT:
            connection.execute(
                "UPDATE booking_night SET allocation_state='CONSUMED' "
                "WHERE booking_id=? AND allocation_state='HELD'",
                (row["id"],),
            )
        connection.execute(
            "UPDATE booking SET status=?,version=version+1,updated_at=? WHERE id=?",
            (target, stamp(now), row["id"]),
        )
        self.audit.append(
            connection, actor, action, row["id"], row["status"], target, reason, dict(row)
        )
        if target in (Status.CANCELLED, Status.REJECTED, Status.EXPIRED, Status.NO_SHOW):
            connection.execute(
                "INSERT INTO notification_task(booking_id,message,created_at,updated_at) "
                "VALUES(?,?,?,?)",
                (row["id"], f"订单状态更新为{target}：{reason}", stamp(now), stamp(now)),
            )

    def finalize_due(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict | None:
        now, target = self.clock.now(), None
        if row["status"] == Status.PENDING and now >= instant(row["expires_at"]):
            target = Status.EXPIRED
        elif row["status"] == Status.CONFIRMED and now >= cutoff(
            row["check_in"], row["time_zone"], following_day=True
        ):
            target = Status.NO_SHOW
        if target:
            self._change_status(connection, row, target, None, "LIFECYCLE", "已达到处理时限")
            # Return an error without throwing inside the savepoint, so the
            # expiry and its single release commit before reporting rejection.
            return BusinessError(str(target), "订单已超时或已标记未入住，请刷新").response()
        return None

    def sweep_due(self, connection: sqlite3.Connection) -> int:
        rows = list(
            connection.execute(
                "SELECT id FROM booking WHERE status IN ('PENDING','CONFIRMED') ORDER BY id"
            )
        )
        return sum(
            bool(self.finalize_due(connection, self._row(connection, row["id"]))) for row in rows
        )
