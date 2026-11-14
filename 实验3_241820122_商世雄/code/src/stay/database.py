"""SQLite schema, connection ownership and transaction boundaries."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS hotel (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT NOT NULL,
 address TEXT NOT NULL, contact TEXT NOT NULL, time_zone TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PENDING','OPEN','CLOSED')),
 version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS app_user (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 display_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('CUSTOMER','STAFF','ADMIN')),
 hotel_id INTEGER REFERENCES hotel(id), enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
 CHECK((role='STAFF' AND hotel_id IS NOT NULL) OR (role!='STAFF' AND hotel_id IS NULL))
);
CREATE TABLE IF NOT EXISTS session (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES app_user(id),
 expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS room_type (
 id INTEGER PRIMARY KEY, hotel_id INTEGER NOT NULL REFERENCES hotel(id), name TEXT NOT NULL,
 capacity INTEGER NOT NULL CHECK(capacity>0), total_rooms INTEGER NOT NULL CHECK(total_rooms>0),
 version INTEGER NOT NULL DEFAULT 1, UNIQUE(id,hotel_id), UNIQUE(hotel_id,name)
);
CREATE TABLE IF NOT EXISTS room_day (
 room_type_id INTEGER NOT NULL REFERENCES room_type(id), stay_date TEXT NOT NULL,
 supply INTEGER NOT NULL CHECK(supply>=0), reserved INTEGER NOT NULL DEFAULT 0,
 price_cents INTEGER NOT NULL CHECK(price_cents>0), sold_out INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(room_type_id,stay_date),
 CHECK(reserved>=0 AND reserved<=supply), CHECK(sold_out IN (0,1))
);
CREATE TABLE IF NOT EXISTS booking (
 id TEXT PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES app_user(id),
 hotel_id INTEGER NOT NULL REFERENCES hotel(id), room_type_id INTEGER NOT NULL,
 check_in TEXT NOT NULL, check_out TEXT NOT NULL, rooms INTEGER NOT NULL CHECK(rooms>0),
 guests INTEGER NOT NULL CHECK(guests>0), contact_name TEXT NOT NULL, contact_phone TEXT NOT NULL,
 total_cents INTEGER NOT NULL CHECK(total_cents>0),
 status TEXT NOT NULL CHECK(status IN ('PENDING','CONFIRMED','CHECKED_IN','CHECKED_OUT',
 'CANCELLED','REJECTED','EXPIRED','NO_SHOW')),
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 pending_since TEXT NOT NULL, expires_at TEXT NOT NULL,
 FOREIGN KEY(room_type_id,hotel_id) REFERENCES room_type(id,hotel_id), CHECK(check_out>check_in)
);
CREATE TABLE IF NOT EXISTS booking_night (
 booking_id TEXT NOT NULL REFERENCES booking(id), room_type_id INTEGER NOT NULL,
 stay_date TEXT NOT NULL, unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents>0),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 allocation_state TEXT NOT NULL CHECK(allocation_state IN ('HELD','CONSUMED','RELEASED')),
 PRIMARY KEY(booking_id,stay_date),
 FOREIGN KEY(room_type_id,stay_date) REFERENCES room_day(room_type_id,stay_date)
);
CREATE TABLE IF NOT EXISTS request_record (
 actor_id INTEGER NOT NULL REFERENCES app_user(id), operation TEXT NOT NULL,
 request_key TEXT NOT NULL, payload_hash TEXT NOT NULL, result_json TEXT NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(actor_id,operation,request_key)
);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES app_user(id), hotel_id INTEGER,
 customer_id INTEGER, target TEXT NOT NULL, action TEXT NOT NULL,
 before_state TEXT NOT NULL, after_state TEXT NOT NULL, result TEXT NOT NULL,
 reason TEXT NOT NULL, occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_task (
 id INTEGER PRIMARY KEY, booking_id TEXT NOT NULL REFERENCES booking(id),
 message TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING'
 CHECK(state IN ('PENDING','DONE','RETRY')), attempts INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS hotel_search ON hotel(city,status);
CREATE INDEX IF NOT EXISTS room_hotel ON room_type(hotel_id);
CREATE INDEX IF NOT EXISTS booking_customer ON booking(customer_id,created_at);
CREATE INDEX IF NOT EXISTS booking_hotel ON booking(hotel_id,status,check_in);
CREATE INDEX IF NOT EXISTS booking_expiry ON booking(status,expires_at);
CREATE INDEX IF NOT EXISTS audit_hotel ON audit_log(hotel_id,occurred_at);
CREATE INDEX IF NOT EXISTS audit_actor ON audit_log(actor_id,occurred_at);
CREATE TRIGGER IF NOT EXISTS day_capacity_insert BEFORE INSERT ON room_day
WHEN NEW.supply>(SELECT total_rooms FROM room_type WHERE id=NEW.room_type_id)
BEGIN SELECT RAISE(ABORT,'daily supply exceeds total rooms'); END;
CREATE TRIGGER IF NOT EXISTS day_capacity_update BEFORE UPDATE OF supply ON room_day
WHEN NEW.supply>(SELECT total_rooms FROM room_type WHERE id=NEW.room_type_id)
BEGIN SELECT RAISE(ABORT,'daily supply exceeds total rooms'); END;
CREATE TRIGGER IF NOT EXISTS type_capacity_update BEFORE UPDATE OF total_rooms ON room_type
WHEN NEW.total_rooms<(SELECT COALESCE(MAX(supply),0) FROM room_day WHERE room_type_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'total rooms below daily supply'); END;
CREATE TRIGGER IF NOT EXISTS audit_immutable BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT,'audit logs are immutable'); END;
"""


class Database:
    """Use one connection per operation; never share a connection across threads."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            connection.execute("PRAGMA user_version=1")
        finally:
            connection.close()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
        finally:
            connection.rollback()
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            # SQLite has no SELECT FOR UPDATE. The write lock serializes checks
            # and updates, including all dates, before reading mutable stock.
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def backup(self, destination: Path) -> Path:
        destination = destination.resolve()
        if destination == self.path:
            raise ValueError("备份路径不能是当前数据库")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
            result = target.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError("备份完整性检查失败")
        finally:
            target.close()
            source.close()
        return destination
