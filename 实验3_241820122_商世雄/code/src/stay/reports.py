"""Authorized statistics, notifications and consistency diagnostics."""

from __future__ import annotations

import sqlite3

from stay.audit import AuditService, ensure_admin
from stay.database import Database
from stay.domain import Clock, Role, parse_date, require, stamp
from stay.security import AuthorizationPolicy, AuthService


class ReportService:
    def __init__(self, database: Database, auth: AuthService, audit: AuditService, clock: Clock):
        self.database, self.auth, self.audit, self.clock = database, auth, audit, clock

    def statistics(
        self,
        token: str,
        start: str,
        end: str,
        room_id: int | None = None,
        hotel_id: int | None = None,
    ) -> dict:
        require(parse_date(start) <= parse_date(end), "INVALID_DATE", "统计开始日不能晚于结束日")
        with self.database.read() as connection:
            actor = self.auth.resolve(connection, token)
            AuthorizationPolicy.role(actor, Role.STAFF, Role.ADMIN)
            clauses = [
                "b.status IN ('CONFIRMED','CHECKED_IN','CHECKED_OUT')",
                "b.check_in>=?",
                "b.check_in<=?",
            ]
            args = [start, end]
            if actor.role == Role.STAFF:
                if hotel_id is not None:
                    AuthorizationPolicy.hotel(actor, hotel_id)
                hotel_id = actor.hotel_id
            if hotel_id is not None:
                clauses.append("b.hotel_id=?")
                args.append(hotel_id)
            if room_id is not None:
                clauses.append("b.room_type_id=?")
                args.append(room_id)
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT b.id,b.hotel_id,b.room_type_id,b.status,b.rooms,b.check_in,b.check_out,"
                    "b.rooms*CAST(julianday(b.check_out)-julianday(b.check_in) AS INTEGER) room_nights "
                    "FROM booking b WHERE " + " AND ".join(clauses) + " ORDER BY b.check_in,b.id",
                    args,
                )
            ]
            return {
                "orders": len(rows),
                "room_nights": sum(row["room_nights"] for row in rows),
                "rows": rows,
                "start_inclusive": start,
                "end_inclusive": end,
            }

    def notifications(self, token: str) -> list[dict]:
        with self.database.read() as connection:
            actor = self.auth.resolve(connection, token)
            AuthorizationPolicy.role(actor, Role.STAFF, Role.ADMIN)
            sql = (
                "SELECT n.*,b.hotel_id FROM notification_task n JOIN booking b ON b.id=n.booking_id"
            )
            args = []
            if actor.role == Role.STAFF:
                sql += " WHERE b.hotel_id=?"
                args.append(actor.hotel_id)
            return [
                dict(row) for row in connection.execute(sql + " ORDER BY n.id DESC LIMIT 200", args)
            ]

    def mark_notification(self, token: str, task_id: int, completed: bool) -> None:
        require(isinstance(completed, bool), "INVALID_INPUT", "通知处理状态无效")
        with self.database.transaction() as connection:
            actor = self.auth.resolve(connection, token)
            AuthorizationPolicy.role(actor, Role.STAFF, Role.ADMIN)
            row = connection.execute(
                "SELECT n.*,b.hotel_id FROM notification_task n JOIN booking b "
                "ON b.id=n.booking_id WHERE n.id=?",
                (task_id,),
            ).fetchone()
            require(row is not None, "NOT_FOUND", "通知待办不存在")
            AuthorizationPolicy.hotel(actor, row["hotel_id"])
            state = "DONE" if completed else "RETRY"
            connection.execute(
                "UPDATE notification_task SET state=?,attempts=attempts+1,updated_at=? WHERE id=?",
                (state, stamp(self.clock.now()), task_id),
            )
            self.audit.append(
                connection,
                actor,
                "NOTIFICATION_UPDATE",
                str(task_id),
                row["state"],
                state,
                scope={"hotel_id": row["hotel_id"]},
            )

    def diagnose(self, token: str) -> dict:
        with self.database.read() as connection:
            ensure_admin(connection, self.auth, token)
            return self.check_consistency(connection)

    @staticmethod
    def check_consistency(connection: sqlite3.Connection) -> dict:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
        stock = [
            dict(row)
            for row in connection.execute(
                "SELECT d.room_type_id,d.stay_date,d.supply,d.reserved,COALESCE(SUM(CASE "
                "WHEN n.allocation_state!='RELEASED' THEN n.quantity ELSE 0 END),0) calculated "
                "FROM room_day d LEFT JOIN booking_night n ON n.room_type_id=d.room_type_id "
                "AND n.stay_date=d.stay_date GROUP BY d.room_type_id,d.stay_date "
                "HAVING d.reserved!=calculated OR d.reserved<0 OR d.reserved>d.supply"
            )
        ]
        totals = [
            dict(row)
            for row in connection.execute(
                "SELECT b.id,b.total_cents,COALESCE(SUM(n.quantity*n.unit_price_cents),0) calculated "
                "FROM booking b LEFT JOIN booking_night n ON n.booking_id=b.id "
                "GROUP BY b.id HAVING b.total_cents!=calculated"
            )
        ]
        return {
            "ok": integrity == "ok" and not foreign_keys and not stock and not totals,
            "integrity": integrity,
            "foreign_keys": foreign_keys,
            "stock_errors": stock,
            "price_errors": totals,
        }
