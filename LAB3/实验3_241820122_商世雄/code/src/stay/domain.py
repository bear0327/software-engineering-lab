"""Value objects, business errors, validation and time calculations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Role(StrEnum):
    CUSTOMER = "CUSTOMER"
    STAFF = "STAFF"
    ADMIN = "ADMIN"


class Status(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    NO_SHOW = "NO_SHOW"


STATUS_NAMES = dict(
    zip(
        Status,
        ["待确认", "已确认", "已入住", "已退房", "已取消", "已拒绝", "已超时", "未入住"],
        strict=True,
    )
)
ROLE_NAMES = {Role.CUSTOMER: "顾客", Role.STAFF: "酒店工作人员", Role.ADMIN: "平台管理员"}
VALID_STATUSES = (Status.CONFIRMED, Status.CHECKED_IN, Status.CHECKED_OUT)


class BusinessError(Exception):
    """An expected error safe to present to a user."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def response(self) -> dict:
        return {"ok": False, "code": self.code, "message": self.message, "details": self.details}


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise BusinessError(code, message)


def positive_int(value: Any, field: str, maximum: int = 10000) -> int:
    require(not isinstance(value, bool), "INVALID_INPUT", f"{field}必须是整数")
    try:
        number = int(str(value))
    except (TypeError, ValueError) as error:
        raise BusinessError("INVALID_INPUT", f"{field}必须是整数") from error
    require(0 < number <= maximum, "INVALID_INPUT", f"{field}须在1至{maximum}之间")
    return number


def nonnegative_int(value: Any, field: str) -> int:
    if str(value) == "0":
        return 0
    return positive_int(value, field)


def text(value: Any, field: str, maximum: int = 120) -> str:
    require(isinstance(value, str), "INVALID_INPUT", f"{field}不能为空")
    result = value.strip()
    require(0 < len(result) <= maximum, "INVALID_INPUT", f"{field}长度须为1至{maximum}")
    return result


def phone(value: str) -> str:
    result = text(value, "联系电话", 30)
    require(
        bool(re.fullmatch(r"[+\d][\d -]{5,28}\d", result)), "INVALID_INPUT", "联系电话格式不正确"
    )
    return result


def cents(value: Any) -> int:
    try:
        amount = Decimal(str(value))
        require(amount.is_finite(), "INVALID_INPUT", "价格必须是有效数字")
        require(amount > 0, "INVALID_INPUT", "价格须大于0")
        require(amount <= 1000000, "INVALID_INPUT", "价格过大")
        require(amount == amount.quantize(Decimal("0.01")), "INVALID_INPUT", "价格最多保留两位小数")
        return int(amount * 100)
    except (InvalidOperation, ValueError, TypeError) as error:
        raise BusinessError("INVALID_INPUT", "价格格式不正确") from error


def money(value: int) -> str:
    return f"{value / 100:.2f}"


def parse_date(value: str) -> date:
    try:
        result = date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise BusinessError("INVALID_DATE", "日期须为YYYY-MM-DD格式") from error
    require(result.isoformat() == value, "INVALID_DATE", "日期须为YYYY-MM-DD格式")
    return result


def nights(start: str, end: str) -> list[str]:
    first, last = parse_date(start), parse_date(end)
    length = (last - first).days
    require(0 < length <= 366, "INVALID_DATE", "离店须晚于入住，单次查询不超过366晚")
    return [(first + timedelta(days=offset)).isoformat() for offset in range(length)]


def timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, TypeError, ValueError) as error:
        raise BusinessError("INVALID_INPUT", "时区名称无效，例如Asia/Shanghai") from error


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def local_today(now: datetime, zone: str) -> str:
    return now.astimezone(timezone(zone)).date().isoformat()


def cutoff(day: str, zone: str, hour: int = 0, following_day: bool = False) -> datetime:
    point = parse_date(day) + timedelta(days=int(following_day))
    return (
        datetime.combine(point, datetime.min.time(), timezone(zone))
        .replace(hour=hour)
        .astimezone(UTC)
    )


def digest(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True)
class Actor:
    id: int
    username: str
    role: Role
    hotel_id: int | None


@dataclass(frozen=True)
class BookingCommand:
    room_type_id: int
    check_in: str
    check_out: str
    rooms: int
    guests: int
    contact_name: str
    contact_phone: str
    accepted_quote: str

    def __post_init__(self):
        for field, label in [("room_type_id", "房型编号"), ("rooms", "间数"), ("guests", "人数")]:
            object.__setattr__(self, field, positive_int(getattr(self, field), label, 100000000))

    def validate(self) -> list[str]:
        positive_int(self.room_type_id, "房型编号", 100000000)
        positive_int(self.rooms, "间数")
        positive_int(self.guests, "人数")
        text(self.contact_name, "联系人", 50)
        phone(self.contact_phone)
        text(self.accepted_quote, "报价标识", 100)
        return nights(self.check_in, self.check_out)


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class MutableClock(Clock):
    """A controllable clock used only by isolated tests."""

    def __init__(self, value: datetime):
        require(value.tzinfo is not None, "INVALID_INPUT", "测试时间必须带时区")
        self.value = value.astimezone(UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)
