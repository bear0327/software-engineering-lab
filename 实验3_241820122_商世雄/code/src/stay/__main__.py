"""CLI entry points for the desktop application, verification and safe restore."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from stay.application import Application
from stay.domain import BookingCommand, BusinessError
from stay.reports import ReportService


def default_database() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    return base / "StayHotel" / "stay.sqlite3"


def self_test() -> dict:
    with tempfile.TemporaryDirectory(prefix="stay-check-") as directory:
        app = Application(Path(directory) / "check.sqlite3")
        app.seed_demo()
        customer = app.auth.login("customer", "Guest2026!")
        staff = app.auth.login("staff", "Staff2026!")
        admin = app.auth.login("admin", "Admin2026!")
        day = app.clock.now().astimezone(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)
        start, end = day.isoformat(), (day + timedelta(days=2)).isoformat()
        quote = app.pricing.quote(1, start, end, 1, 2)
        command = BookingCommand(1, start, end, 1, 2, "运行检查", "13800138000", quote["quote_id"])
        key = uuid.uuid4().hex
        order = app.bookings.create(customer, command, key)
        assert app.bookings.create(customer, command, key)["id"] == order["id"]
        confirmed = app.bookings.transition(staff, order["id"], "confirm", 1, uuid.uuid4().hex)
        check = app.reports.diagnose(admin)
        assert check["ok"]
        backup = app.jobs.backup(admin)
        assert backup["diagnostics"]["ok"]
        return {
            "ok": True,
            "order_id": order["id"],
            "status": confirmed["status"],
            "price_cents": order["total_cents"],
            "idempotency": True,
            "consistency": check,
            "backup_checked": True,
        }


def restore_to_new_file(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if not source.is_file() or destination.exists() or source == destination:
        raise ValueError("请选择已有备份和一个尚不存在的恢复目标，不覆盖正在使用的数据")
    destination.parent.mkdir(parents=True, exist_ok=True)
    original = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    target = sqlite3.connect(destination)
    try:
        original.backup(target)
        target.row_factory = sqlite3.Row
        if target.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("不是支持的酒店系统备份版本")
        result = ReportService.check_consistency(target)
        if not result["ok"]:
            raise ValueError("恢复后的数据一致性检查未通过")
        return {"ok": True, "restored_to": str(destination), "diagnostics": result}
    finally:
        original.close()
        target.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="泊岸酒店预订系统")
    parser.add_argument("--db", type=Path, default=default_database())
    parser.add_argument("--self-test", action="store_true", help="在隔离数据库中执行运行检查")
    parser.add_argument("--output", type=Path, help="将运行检查结果写为JSON")
    parser.add_argument("--restore", type=Path, help="恢复备份，不会覆盖现有数据库")
    parser.add_argument("--destination", type=Path, help="恢复目标，必须为新文件")
    args = parser.parse_args()
    try:
        if args.self_test or args.restore:
            if args.restore and not args.destination:
                parser.error("恢复时必须给出--destination")
            result = (
                restore_to_new_file(args.restore, args.destination) if args.restore else self_test()
            )
            output = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(output, encoding="utf-8")
            if os.sys.stdout is not None:
                print(output)
            return 0
        args.db.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=args.db.parent / "application.log",
            encoding="utf-8",
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        app = Application(args.db)
        app.seed_demo()
        # Keep CLI self-test/restore available without a graphical display.
        from stay.desktop import Desktop  # pylint: disable=import-outside-toplevel

        Desktop(app).mainloop()
        return 0
    except (BusinessError, OSError, ValueError, sqlite3.Error) as error:
        logging.exception("Startup or verification failed")
        if os.sys.stderr is not None:
            print(str(error), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
