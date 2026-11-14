"""Capture only real application windows, with an isolated database and demo orders."""

import json
import sys
import tempfile
import tkinter as tk
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stay.application import Application  # noqa: E402
from stay.desktop import Desktop  # noqa: E402
from stay.domain import BookingCommand  # noqa: E402
from stay.pages import (  # noqa: E402
    CalendarPage,
    HotelsPage,
    OrdersPage,
    SearchPage,
    StaffPage,
    StatsPage,
    SystemPage,
)


def capture(desktop, output):
    desktop.update_idletasks()
    desktop.lift()
    desktop.attributes("-topmost", True)
    ready = tk.BooleanVar(master=desktop, value=False)
    desktop.after(250, lambda: ready.set(True))
    desktop.wait_variable(ready)
    x, y = desktop.winfo_rootx(), desktop.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x + desktop.winfo_width(), y + desktop.winfo_height())).save(output)


def main():
    output = ROOT.parent / "运行材料" / "界面截图"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stay-capture-") as directory:
        app = Application(Path(directory) / "capture.sqlite3")
        app.seed_demo()
        customer = app.auth.login("customer", "Guest2026!")
        staff = app.auth.login("staff", "Staff2026!")
        admin = app.auth.login("admin", "Admin2026!")
        today = app.clock.now().astimezone(ZoneInfo("Asia/Shanghai")).date()
        for index, (offset, length, rooms) in enumerate([(1, 3, 2), (2, 1, 1), (3, 2, 1)]):
            start, end = (
                (today + timedelta(days=offset)).isoformat(),
                (today + timedelta(days=offset + length)).isoformat(),
            )
            quote = app.pricing.quote(1, start, end, rooms, 2)
            command = BookingCommand(
                1, start, end, rooms, 2, "商同学", "13800138000", quote["quote_id"]
            )
            order = app.bookings.create(customer, command, f"capture-{index}")
            app.bookings.transition(staff, order["id"], "confirm", 1, f"confirm-{index}")
        desktop = Desktop(app, start_worker=False)
        width = min(1440, desktop.winfo_screenwidth() - 80)
        height = min(870, desktop.winfo_screenheight() - 100)
        desktop.geometry(f"{width}x{height}+20+20")
        pages = [
            ("01_登录", "", None),
            ("02_查房报价", customer, SearchPage),
            ("03_顾客订单", customer, OrdersPage),
            ("04_酒店订单", staff, OrdersPage),
            ("05_逐日库存", staff, CalendarPage),
            ("06_统计3单9间夜", staff, StatsPage),
            ("07_酒店审核", admin, HotelsPage),
            ("08_工作人员", admin, StaffPage),
            ("09_数据一致性", admin, SystemPage),
        ]
        captured = []
        try:
            for name, token, page_type in pages:
                if token:
                    desktop.token, desktop.actor = token, app.auth.current(token)
                    desktop.shell()
                    desktop.show_page(page_type)
                if page_type == SystemPage:
                    desktop.page.diagnose()
                path = output / f"{name}.png"
                capture(desktop, path)
                captured.append(
                    {
                        "file": path.name,
                        "width": desktop.winfo_width(),
                        "height": desktop.winfo_height(),
                        "method": "PIL.ImageGrab of real Tk window",
                    }
                )
        finally:
            desktop.close()
        (output / "capture.json").write_text(
            json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"Saved {len(captured)} application screenshots to {output}")


if __name__ == "__main__":
    main()
