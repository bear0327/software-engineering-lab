"""Password hashing, revocable sessions and role/ownership policies."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import timedelta
from typing import TYPE_CHECKING

from stay.database import Database
from stay.domain import Actor, BusinessError, Clock, Role, instant, require, stamp, text

if TYPE_CHECKING:
    from stay.audit import AuditService


def hash_password(password: str) -> str:
    require(
        isinstance(password, str) and 8 <= len(password) <= 128,
        "INVALID_INPUT",
        "密码长度须为8至128",
    )
    salt = secrets.token_bytes(16)
    iterations = 260000
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${hashed.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, AttributeError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def username(value: str) -> str:
    value = text(value, "账号", 40)
    require(
        bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", value)),
        "INVALID_INPUT",
        "账号使用3至40位字母、数字、点或下划线",
    )
    return value


class AuthorizationPolicy:
    @staticmethod
    def role(actor: Actor, *roles: Role) -> None:
        require(actor.role in roles, "FORBIDDEN", "当前身份无权执行此操作")

    @staticmethod
    def hotel(actor: Actor, hotel_id: int) -> None:
        require(
            actor.role == Role.ADMIN or (actor.role == Role.STAFF and actor.hotel_id == hotel_id),
            "FORBIDDEN",
            "只能处理所属酒店的数据",
        )

    @staticmethod
    def booking(actor: Actor, booking: sqlite3.Row) -> None:
        allowed = actor.role == Role.ADMIN
        allowed |= actor.role == Role.CUSTOMER and actor.id == booking["customer_id"]
        allowed |= actor.role == Role.STAFF and actor.hotel_id == booking["hotel_id"]
        require(allowed, "FORBIDDEN", "无权访问该订单")


class AuthService:
    def __init__(self, database: Database, clock: Clock):
        self.database = database
        self.clock = clock
        self.audit: AuditService | None = None

    def bootstrap(self, account: str, password: str) -> int:
        """Create exactly one initial administrator for a fresh database."""
        account, encoded = username(account), hash_password(password)
        with self.database.transaction() as connection:
            existing = connection.execute("SELECT id FROM app_user WHERE role='ADMIN'").fetchone()
            if existing:
                return existing["id"]
            cursor = connection.execute(
                "INSERT INTO app_user(username,password_hash,display_name,role) "
                "VALUES(?,?,?,'ADMIN')",
                (account, encoded, "平台管理员"),
            )
            return cursor.lastrowid

    def register(self, account: str, password: str, display_name: str) -> int:
        return self._create(account, password, display_name, Role.CUSTOMER)

    def _create(
        self, account: str, password: str, name: str, role: Role, hotel_id: int | None = None
    ) -> int:
        account, encoded, name = username(account), hash_password(password), text(name, "姓名", 50)
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    "INSERT INTO app_user(username,password_hash,display_name,role,hotel_id) "
                    "VALUES(?,?,?,?,?)",
                    (account, encoded, name, role, hotel_id),
                )
                return cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise BusinessError("CONFLICT", "账号已存在或酒店无效") from error

    def login(self, account: str, password: str) -> str:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM app_user WHERE username=?", (account,)
            ).fetchone()
            require(
                row is not None
                and row["enabled"]
                and verify_password(password, row["password_hash"]),
                "AUTH_FAILED",
                "账号、密码错误或账号已停用",
            )
            token = secrets.token_urlsafe(32)
            connection.execute(
                "INSERT INTO session VALUES(?,?,?)",
                (
                    token_hash(token),
                    row["id"],
                    stamp(self.clock.now() + timedelta(hours=8)),
                ),
            )
            return token

    def resolve(self, connection: sqlite3.Connection, token: str) -> Actor:
        require(isinstance(token, str) and bool(token), "UNAUTHENTICATED", "请先登录")
        row = connection.execute(
            "SELECT u.*,s.expires_at FROM session s JOIN app_user u ON u.id=s.user_id "
            "WHERE s.token_hash=?",
            (token_hash(token),),
        ).fetchone()
        require(
            row is not None and row["enabled"] and instant(row["expires_at"]) > self.clock.now(),
            "UNAUTHENTICATED",
            "登录已失效，请重新登录",
        )
        return Actor(row["id"], row["username"], Role(row["role"]), row["hotel_id"])

    def current(self, token: str) -> Actor:
        with self.database.read() as connection:
            return self.resolve(connection, token)

    def logout(self, token: str) -> None:
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM session WHERE token_hash=?", (token_hash(token),))

    def create_staff(
        self, token: str, account: str, password: str, name: str, hotel_id: int
    ) -> int:
        encoded = hash_password(password)
        account, name = username(account), text(name, "姓名", 50)
        try:
            with self.database.transaction() as connection:
                actor = self.resolve(connection, token)
                AuthorizationPolicy.role(actor, Role.ADMIN)
                require(
                    connection.execute("SELECT id FROM hotel WHERE id=?", (hotel_id,)).fetchone()
                    is not None,
                    "NOT_FOUND",
                    "酒店不存在",
                )
                cursor = connection.execute(
                    "INSERT INTO app_user(username,password_hash,display_name,role,hotel_id) "
                    "VALUES(?,?,?,'STAFF',?)",
                    (account, encoded, name, hotel_id),
                )
                if self.audit:
                    self.audit.append(
                        connection,
                        actor,
                        "STAFF_CREATE",
                        str(cursor.lastrowid),
                        after="ENABLED",
                        scope={"hotel_id": hotel_id},
                    )
                return cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise BusinessError("CONFLICT", "账号已存在") from error

    def list_staff(self, token: str) -> list[dict]:
        with self.database.read() as connection:
            AuthorizationPolicy.role(self.resolve(connection, token), Role.ADMIN)
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT u.id,u.username,u.display_name,u.hotel_id,u.enabled,h.name hotel_name "
                    "FROM app_user u JOIN hotel h ON h.id=u.hotel_id "
                    "WHERE u.role='STAFF' ORDER BY u.id"
                )
            ]

    def set_enabled(self, token: str, user_id: int, enabled: bool) -> None:
        require(isinstance(enabled, bool), "INVALID_INPUT", "启用状态无效")
        with self.database.transaction() as connection:
            actor = self.resolve(connection, token)
            AuthorizationPolicy.role(actor, Role.ADMIN)
            row = connection.execute("SELECT * FROM app_user WHERE id=?", (user_id,)).fetchone()
            require(
                row is not None and row["role"] == Role.STAFF, "FORBIDDEN", "此入口只管理工作人员"
            )
            connection.execute("UPDATE app_user SET enabled=? WHERE id=?", (int(enabled), user_id))
            if not enabled:
                connection.execute("DELETE FROM session WHERE user_id=?", (user_id,))
            if self.audit:
                self.audit.append(
                    connection,
                    actor,
                    "STAFF_STATUS",
                    str(user_id),
                    str(row["enabled"]),
                    str(int(enabled)),
                    scope={"hotel_id": row["hotel_id"]},
                )

    def change_password(self, token: str, old_password: str, new_password: str) -> None:
        encoded = hash_password(new_password)
        with self.database.transaction() as connection:
            actor = self.resolve(connection, token)
            row = connection.execute(
                "SELECT password_hash FROM app_user WHERE id=?", (actor.id,)
            ).fetchone()
            require(
                verify_password(old_password, row["password_hash"]), "AUTH_FAILED", "原密码不正确"
            )
            connection.execute(
                "UPDATE app_user SET password_hash=? WHERE id=?", (encoded, actor.id)
            )
            connection.execute("DELETE FROM session WHERE user_id=?", (actor.id,))
            if self.audit:
                self.audit.append(
                    connection,
                    actor,
                    "PASSWORD_CHANGE",
                    str(actor.id),
                    scope={
                        "hotel_id": actor.hotel_id,
                        "customer_id": actor.id if actor.role == Role.CUSTOMER else None,
                    },
                )
