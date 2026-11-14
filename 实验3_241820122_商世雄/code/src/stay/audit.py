"""Append-only business history and transactional request replay."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

from stay.database import Database
from stay.domain import Actor, BusinessError, Clock, Role, digest, stamp, text
from stay.security import AuthorizationPolicy, AuthService


class AuditService:
    def __init__(self, database: Database, auth: AuthService, clock: Clock):
        self.database, self.auth, self.clock = database, auth, clock

    def append(
        self,
        connection: sqlite3.Connection,
        actor: Actor | None,
        action: str,
        target: str,
        before: str = "",
        after: str = "",
        reason: str = "",
        scope: dict | None = None,
        result: str = "SUCCESS",
    ) -> None:
        scope = scope or {}
        connection.execute(
            "INSERT INTO audit_log(actor_id,hotel_id,customer_id,target,action,before_state,"
            "after_state,result,reason,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                actor.id if actor else None,
                scope.get("hotel_id"),
                scope.get("customer_id"),
                str(target),
                action,
                before,
                after,
                result,
                reason[:500],
                stamp(self.clock.now()),
            ),
        )

    def query(
        self,
        token: str,
        actor_id: int | None = None,
        action: str = "",
        start: str = "",
        end: str = "",
        offset: int = 0,
    ) -> list[dict]:
        with self.database.read() as connection:
            actor = self.auth.resolve(connection, token)
            clauses, args = ["1=1"], []
            if actor.role == Role.STAFF:
                clauses.append("a.hotel_id=?")
                args.append(actor.hotel_id)
            elif actor.role == Role.CUSTOMER:
                clauses.append("a.customer_id=?")
                args.append(actor.id)
            for value, clause in [
                (actor_id, "a.actor_id=?"),
                (action, "a.action=?"),
                (start, "a.occurred_at>=?"),
                (end, "a.occurred_at<=?"),
            ]:
                if value not in (None, ""):
                    clauses.append(clause)
                    args.append(value)
            args.append(max(0, int(offset)))
            rows = connection.execute(
                "SELECT a.*,COALESCE(u.username,'系统') actor_name FROM audit_log a "
                "LEFT JOIN app_user u ON u.id=a.actor_id WHERE "
                + " AND ".join(clauses)
                + " ORDER BY a.id DESC LIMIT 200 OFFSET ?",
                args,
            )
            return [dict(row) for row in rows]


class CommandExecutor:
    """Cache completed business results, but never cache infrastructure failures."""

    def __init__(self, database: Database, auth: AuthService, audit: AuditService, clock: Clock):
        self.database, self.auth, self.audit, self.clock = database, auth, audit, clock

    def execute(
        self,
        token: str,
        operation: str,
        request_key: str,
        payload: dict,
        handler: Callable[[sqlite3.Connection, Actor], dict],
    ) -> dict:
        request_key = text(request_key, "请求标识", 128)
        fingerprint = digest(payload)
        with self.database.transaction() as connection:
            actor = self.auth.resolve(connection, token)
            old = connection.execute(
                "SELECT * FROM request_record WHERE actor_id=? AND operation=? AND request_key=?",
                (actor.id, operation, request_key),
            ).fetchone()
            if old:
                if old["payload_hash"] != fingerprint:
                    raise BusinessError("REQUEST_KEY_CONFLICT", "相同请求标识不能用于不同内容")
                result = json.loads(old["result_json"])
            else:
                connection.execute("SAVEPOINT business")
                try:
                    result = handler(connection, actor)
                except BusinessError as error:
                    connection.execute("ROLLBACK TO business")
                    result = error.response()
                connection.execute("RELEASE business")
                if not result.get("ok", True):
                    self.audit.append(
                        connection,
                        actor,
                        operation,
                        str(payload.get("id", "")),
                        reason=result["code"],
                        result="FAILED",
                    )
                connection.execute(
                    "INSERT INTO request_record VALUES(?,?,?,?,?,?)",
                    (
                        actor.id,
                        operation,
                        request_key,
                        fingerprint,
                        json.dumps(result, ensure_ascii=False),
                        stamp(self.clock.now()),
                    ),
                )
        if not result.get("ok", True):
            raise BusinessError(result["code"], result["message"], result.get("details"))
        return result


def ensure_admin(connection: sqlite3.Connection, auth: AuthService, token: str) -> Actor:
    actor = auth.resolve(connection, token)
    AuthorizationPolicy.role(actor, Role.ADMIN)
    return actor
