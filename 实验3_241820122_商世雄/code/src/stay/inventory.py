"""Read quotes and apply net changes to an entire stay, never a partial stay."""

from __future__ import annotations

import sqlite3

from stay.database import Database
from stay.domain import BusinessError, Clock, digest, local_today, nights, positive_int, require


class PricingService:
    def __init__(self, database: Database, clock: Clock):
        self.database, self.clock = database, clock

    def quote(self, room_id: int, start: str, end: str, rooms: int = 1, guests: int = 1) -> dict:
        with self.database.read() as connection:
            return self.calculate(connection, room_id, start, end, rooms, guests)

    def calculate(
        self,
        connection: sqlite3.Connection,
        room_id: int,
        start: str,
        end: str,
        rooms: int,
        guests: int,
        original: dict | None = None,
    ) -> dict:
        dates = nights(start, end)
        rooms, guests = positive_int(rooms, "间数"), positive_int(guests, "人数")
        room = connection.execute(
            "SELECT r.*,h.status hotel_status,h.time_zone,h.name hotel_name FROM room_type r "
            "JOIN hotel h ON h.id=r.hotel_id WHERE r.id=?",
            (room_id,),
        ).fetchone()
        require(room is not None, "NOT_FOUND", "房型不存在")
        require(
            start >= local_today(self.clock.now(), room["time_zone"]),
            "INVALID_DATE",
            "不能预订过去的日期",
        )
        require(room["hotel_status"] == "OPEN", "HOTEL_CLOSED", "酒店未营业，不能预订或改期")
        require(guests <= room["capacity"] * rooms, "CAPACITY_CONFLICT", "人数超过房型容量乘以间数")
        rows = list(
            connection.execute(
                "SELECT * FROM room_day WHERE room_type_id=? AND stay_date>=? AND stay_date<? ORDER BY stay_date",
                (room_id, start, end),
            )
        )
        require(len(rows) == len(dates), "NO_ROOM", "部分日期尚未设置库存或价格")
        old = original or {}
        items = []
        for row in rows:
            previous = old.get((room_id, row["stay_date"]), 0)
            delta = rooms - previous
            require(
                not row["sold_out"] or delta <= 0,
                "SOLD_OUT",
                f"{row['stay_date']}已停售，不能增加占用",
            )
            available = row["supply"] - row["reserved"] + previous
            require(available >= rooms, "NO_ROOM", f"{row['stay_date']}房量不足")
            items.append(
                {
                    "date": row["stay_date"],
                    "unit_cents": row["price_cents"],
                    "available": available,
                    "sold_out": bool(row["sold_out"]),
                }
            )
        # A quote fingerprints prices and selected parameters, not availability:
        # another customer's cancellation must not invalidate unchanged prices.
        signature = digest(
            {
                "room": room_id,
                "dates": [(i["date"], i["unit_cents"]) for i in items],
                "rooms": rooms,
                "guests": guests,
            }
        )
        return {
            "room_type_id": room_id,
            "hotel_id": room["hotel_id"],
            "hotel_name": room["hotel_name"],
            "room_name": room["name"],
            "check_in": start,
            "check_out": end,
            "rooms": rooms,
            "guests": guests,
            "nights": items,
            "total_cents": sum(i["unit_cents"] for i in items) * rooms,
            "per_room_cents": sum(i["unit_cents"] for i in items),
            "quote_id": signature,
        }

    def search(
        self,
        city: str = "",
        start: str = "",
        end: str = "",
        rooms: int = 1,
        guests: int = 1,
        room_name: str = "",
        minimum: int = 0,
        maximum: int | None = None,
    ) -> list[dict]:
        require(bool(start) == bool(end), "INVALID_DATE", "请同时填写入住和离店日期")
        require(
            minimum >= 0 and (maximum is None or maximum >= minimum),
            "INVALID_INPUT",
            "价格范围无效",
        )
        if start:
            nights(start, end)
        else:
            require(minimum == 0 and maximum is None, "INVALID_INPUT", "无日期时不能按全程价格筛选")
        result = []
        with self.database.read() as connection:
            sql = (
                "SELECT r.id room_type_id,r.name room_name,r.capacity,h.id hotel_id,"
                "h.name hotel_name,h.city,h.address FROM room_type r JOIN hotel h ON h.id=r.hotel_id "
                "WHERE h.status='OPEN'"
            )
            args = []
            if city.strip():
                sql += " AND h.city=?"
                args.append(city.strip())
            if room_name.strip():
                sql += " AND instr(r.name,?)>0"
                args.append(room_name.strip())
            for row in connection.execute(sql + " ORDER BY h.id,r.id LIMIT 200", args):
                item = dict(row)
                if start:
                    try:
                        item.update(
                            self.calculate(
                                connection, row["room_type_id"], start, end, rooms, guests
                            )
                        )
                    except BusinessError as error:
                        if error.code in (
                            "NO_ROOM",
                            "SOLD_OUT",
                            "CAPACITY_CONFLICT",
                            "INVALID_DATE",
                        ):
                            continue
                        raise
                    price = item["per_room_cents"]
                    if price < minimum or (maximum is not None and price > maximum):
                        continue
                result.append(item)
        return result


class InventoryService:
    @staticmethod
    def allocations(connection: sqlite3.Connection, booking_id: str) -> dict:
        return {
            (row["room_type_id"], row["stay_date"]): row["quantity"]
            for row in connection.execute(
                "SELECT * FROM booking_night WHERE booking_id=? AND allocation_state='HELD'",
                (booking_id,),
            )
        }

    @staticmethod
    def replace(connection: sqlite3.Connection, old: dict, new: dict) -> None:
        for key in sorted(old.keys() | new.keys()):
            delta = new.get(key, 0) - old.get(key, 0)
            if delta:
                cursor = connection.execute(
                    "UPDATE room_day SET reserved=reserved+?,version=version+1 "
                    "WHERE room_type_id=? AND stay_date=? AND reserved+? BETWEEN 0 AND supply "
                    "AND (?<=0 OR sold_out=0)",
                    (delta, *key, delta, delta),
                )
                require(cursor.rowcount == 1, "NO_ROOM", f"{key[1]}库存发生变化，请重新查询")

    def release(self, connection: sqlite3.Connection, booking_id: str, today: str) -> None:
        rows = list(
            connection.execute(
                "SELECT * FROM booking_night WHERE booking_id=? AND allocation_state='HELD'",
                (booking_id,),
            )
        )
        for row in rows:
            if row["stay_date"] >= today:
                self.replace(
                    connection, {(row["room_type_id"], row["stay_date"]): row["quantity"]}, {}
                )
                state = "RELEASED"
            else:
                state = "CONSUMED"
            connection.execute(
                "UPDATE booking_night SET allocation_state=? WHERE booking_id=? AND stay_date=?",
                (state, booking_id, row["stay_date"]),
            )
