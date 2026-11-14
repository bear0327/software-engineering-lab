"""Local SQLite benchmark: 10k hotels, 50k room types, 100k orders, 1.5m room days."""

import json
import os
import platform
import sqlite3
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stay.application import Application  # noqa: E402
from stay.domain import BookingCommand, BusinessError, stamp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def timed_batch(operation, indexes):
    gate = threading.Barrier(20)

    def call(index):
        gate.wait(timeout=30)
        start = perf_counter()
        try:
            code, detail = operation(index)
        except BusinessError as error:
            code, detail = error.code, None
        except Exception as error:  # Preserve every failed sample in the denominator.
            code, detail = type(error).__name__, str(error)
        return {"index": index, "seconds": perf_counter() - start, "code": code, "detail": detail}

    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(call, indexes))


def summarize(rows, limit, expected):
    times = sorted(r["seconds"] for r in rows)
    return {
        "samples": len(rows),
        "p50_seconds": times[len(times) // 2],
        "p95_seconds": times[int(len(times) * 0.95) - 1],
        "max_seconds": max(times),
        "correct_within_limit": sum(r["seconds"] <= limit and r["code"] in expected for r in rows),
        "limit_seconds": limit,
        "codes": {
            code: sum(r["code"] == code for r in rows) for code in sorted({r["code"] for r in rows})
        },
    }


def run_benchmark(directory):
    app = Application(Path(directory) / "benchmark.sqlite3")
    app.auth.bootstrap("admin", "Admin2026!")
    admin = app.auth.login("admin", "Admin2026!")
    customers = []
    for index in range(20):
        app.auth.register(f"bench{index}", "Bench2026!", "性能测试")
        customers.append(app.auth.login(f"bench{index}", "Bench2026!"))
    today = app.clock.now().astimezone(ZoneInfo("Asia/Shanghai")).date()
    dates = [(today + timedelta(days=i + 1)).isoformat() for i in range(30)]
    created = stamp(app.clock.now())
    seed_start = perf_counter()
    with app.database.transaction() as conn:
        conn.executemany(
            "INSERT INTO hotel VALUES(?,?,?,?,?,?,'OPEN',1)",
            (
                (
                    i,
                    f"基线酒店{i}",
                    f"城市{i % 40:02d}",
                    "基线测试路1号",
                    "02580001234",
                    "Asia/Shanghai",
                )
                for i in range(1, 10001)
            ),
        )
        conn.executemany(
            "INSERT INTO room_type VALUES(?,?,?,?,?,1)",
            ((i, (i - 1) // 5 + 1, f"房型{(i - 1) % 5 + 1}", 2, 1000) for i in range(1, 50001)),
        )
        conn.executemany(
            "INSERT INTO room_day VALUES(?,?,?,?,?,0,1)",
            (
                (room, day, 1000, 2 if day == dates[0] else 0, 29900)
                for room in range(1, 50001)
                for day in dates
            ),
        )
        conn.executemany(
            "INSERT INTO booking(id,customer_id,hotel_id,room_type_id,check_in,check_out,rooms,"
            "guests,contact_name,contact_phone,total_cents,status,created_at,updated_at,"
            "pending_since,expires_at) VALUES(?,?,?,?,?,?,1,1,?,?,29900,'CONFIRMED',?,?,?,?)",
            (
                (
                    f"BASE{i:06d}",
                    2,
                    ((i - 1) % 50000) // 5 + 1,
                    (i - 1) % 50000 + 1,
                    dates[0],
                    dates[1],
                    "性能数据",
                    "13800138000",
                    created,
                    created,
                    created,
                    created,
                )
                for i in range(1, 100001)
            ),
        )
        conn.executemany(
            "INSERT INTO booking_night VALUES(?,?,?,29900,1,'HELD')",
            ((f"BASE{i:06d}", (i - 1) % 50000 + 1, dates[0]) for i in range(1, 100001)),
        )
    app.auth.create_staff(admin, "benchstaff", "Bench2026!", "测试前台", 1)
    staff = app.auth.login("benchstaff", "Bench2026!")
    before = app.reports.diagnose(admin)
    assert before["ok"]
    seed_seconds = perf_counter() - seed_start

    def query(index):
        length = [1, 2, 3, 7][index % 4]
        empty = index % 10 == 9
        results = app.pricing.search(
            "不存在的城市" if empty else "城市01",
            dates[0],
            dates[length],
            1,
            2,
            "房型1",
            20000,
            30000 * length,
        )
        assert bool(results) != empty
        assert all(r["total_cents"] == 29900 * length for r in results)
        return "CORRECT", len(results)

    queries = []
    for batch in range(5):
        queries.extend(timed_batch(query, range(batch * 20, (batch + 1) * 20)))
    quote = app.pricing.quote(1, dates[0], dates[2], 1, 2)
    command = BookingCommand(
        1, dates[0], dates[2], 1, 2, "并发测试", "13800138000", quote["quote_id"]
    )

    def book(index):
        order = app.bookings.create(customers[index % 20], command, f"request-{index}")
        return "SUCCESS", order["id"]

    bookings = []
    for batch in range(4):
        bookings.extend(timed_batch(book, range(batch * 20, (batch + 1) * 20)))
    with app.database.read() as conn:
        reserved = conn.execute(
            "SELECT MAX(reserved) FROM room_day WHERE room_type_id=1 "
            "AND stay_date>=? AND stay_date<?",
            (dates[0], dates[2]),
        ).fetchone()[0]
    # Give each night exactly one remaining room, while retaining earlier orders.
    for day in dates[:2]:
        with app.database.read() as conn:
            held = conn.execute(
                "SELECT reserved FROM room_day WHERE room_type_id=1 AND stay_date=?", (day,)
            ).fetchone()[0]
        next_day = (datetime.fromisoformat(day).date() + timedelta(days=1)).isoformat()
        app.catalog.set_calendar(staff, 1, day, next_day, held + 1, "299")
    bookings.extend(timed_batch(book, range(80, 100)))
    after = app.reports.diagnose(admin)
    counts = {code: sum(r["code"] == code for r in bookings) for code in ("SUCCESS", "NO_ROOM")}
    expected = (
        all(r["code"] == "SUCCESS" for r in bookings[:80])
        and counts == {"SUCCESS": 81, "NO_ROOM": 19}
        and after["ok"]
    )
    return {
        "executed_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "sqlite": sqlite3.sqlite_version,
        "logical_cpus": os.cpu_count(),
        "scope": "Local in-process service calls; not the LAB2 Ubuntu/HTTP/JMeter environment",
        "data": {
            "hotels": 10000,
            "room_types": 50000,
            "orders_before": 100000,
            "room_days": 1500000,
            "database_bytes": app.database.path.stat().st_size,
        },
        "seed_and_initial_check_seconds": seed_seconds,
        "query_summary": summarize(queries, 2, {"CORRECT"}),
        "booking_summary": summarize(bookings, 3, {"SUCCESS", "NO_ROOM"}),
        "expected_booking_results": expected,
        "consistency_before": before,
        "consistency_after": after,
        "query_samples": queries,
        "booking_samples": bookings,
        "reserved_before_last_round": reserved,
    }


def main():
    temporary_base = (
        Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "opencode"
    )
    temporary_base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stay-benchmark-", dir=temporary_base) as directory:
        result = run_benchmark(directory)
    output = ROOT / "evidence" / "benchmark.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("query_summary", "booking_summary", "expected_booking_results")
            },
            indent=2,
        )
    )
    return 0 if result["expected_booking_results"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
