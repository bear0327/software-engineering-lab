"""Role-scoped desktop pages; every mutation still calls an authorized service."""

from __future__ import annotations

import json
import tkinter as tk
import uuid
from datetime import date, timedelta
from tkinter import messagebox, ttk
from zoneinfo import ZoneInfo

from stay.domain import (
    STATUS_NAMES,
    BookingCommand,
    Role,
    Status,
    cents,
    digest,
    instant,
    money,
    positive_int,
    require,
)
from stay.widgets import DataTable, FormDialog, entry, show_text


class Page(ttk.Frame):
    def __init__(self, desktop, title: str, subtitle: str):
        super().__init__(desktop.content, padding=20)
        self.desktop = desktop
        self.app = desktop.app
        self.request_keys = {}
        ttk.Label(self, text=title, style="Heading.TLabel").pack(anchor="w")
        ttk.Label(self, text=subtitle, style="Muted.TLabel", wraplength=1000).pack(
            anchor="w", pady=(8, 16)
        )
        self.toolbar = ttk.Frame(self)
        self.toolbar.pack(fill="x", pady=(0, 12))

    @property
    def token(self):
        return self.desktop.token

    def button(self, label, action, parent=None):
        ttk.Button(
            parent or self.toolbar, text=label, command=lambda: self.desktop.invoke(action)
        ).pack(side="left", padx=(0, 8), pady=4)

    def selected(self, table: DataTable) -> dict:
        row = table.selected()
        require(row is not None, "INVALID_INPUT", "请先选择一条记录")
        return row

    def form(self, title: str, fields: list[tuple]) -> dict | None:
        return FormDialog(self.desktop, title, fields).result

    def success(self, message: str):
        self.desktop.notice.set(message)

    def command_key(self, payload):
        fingerprint = digest(payload)
        return self.request_keys.setdefault(fingerprint, uuid.uuid4().hex)


class SearchPage(Page):
    def __init__(self, desktop):
        super().__init__(
            desktop, "酒店与空房查询", "按一间房整个住宿区间的价格筛选；无日期时仅浏览资料。"
        )
        today = self.app.clock.now().astimezone(ZoneInfo("Asia/Shanghai")).date()
        self.city = entry(self.toolbar, "城市", "南京", 10)
        self.start = entry(self.toolbar, "入住日期", (today + timedelta(days=1)).isoformat(), 13)
        self.end = entry(self.toolbar, "离店日期", (today + timedelta(days=3)).isoformat(), 13)
        self.rooms = entry(self.toolbar, "间数", "1", 5)
        self.guests = entry(self.toolbar, "人数", "2", 5)
        more = ttk.Frame(self)
        more.pack(fill="x", pady=(0, 12))
        self.name = entry(more, "房型名称", "", 14)
        self.minimum = entry(more, "最低整段价（元）", "", 14)
        self.maximum = entry(more, "最高整段价（元）", "", 14)
        self.button("查询", self.refresh, more)
        self.button("报价明细", self.details, more)
        self.button("预订选中房型", self.book, more)
        self.table = DataTable(
            self,
            [
                ("hotel_name", "酒店", 180),
                ("city", "城市", 80),
                ("room_name", "房型", 140),
                ("capacity", "单间容量", 90),
                ("price", "单间全程价格", 130),
                ("address", "地址", 220),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.last_payload = None
        self.request_key = uuid.uuid4().hex
        self.refresh()

    def refresh(self):
        rows = self.app.pricing.search(
            self.city.get(),
            self.start.get(),
            self.end.get(),
            positive_int(self.rooms.get(), "间数"),
            positive_int(self.guests.get(), "人数"),
            self.name.get(),
            cents(self.minimum.get()) if self.minimum.get() else 0,
            cents(self.maximum.get()) if self.maximum.get() else None,
        )
        self.table.set_rows(
            rows,
            lambda row: {
                **row,
                "price": "¥" + money(row["per_room_cents"])
                if "per_room_cents" in row
                else "选择日期后报价",
            },
        )
        self.last_payload = None
        self.request_key = uuid.uuid4().hex
        self.success(f"查到{len(rows)}个房型" if rows else "暂无符合条件的可订房型")

    def details(self):
        row = self.selected(self.table)
        lines = [f"{row['hotel_name']} / {row['room_name']}"]
        for night in row.get("nights", []):
            lines.append(
                f"{night['date']}  单间¥{money(night['unit_cents'])}  可用{night['available']}间"
            )
        if "total_cents" in row:
            lines.append(f"{row['rooms']}间总价 ¥{money(row['total_cents'])}")
        else:
            lines.append("没有完整住宿日期，尚未计算总价，也不作可订承诺。")
        show_text(self.desktop, "逐夜报价", "\n\n".join(lines))

    def book(self):
        require(
            self.desktop.actor is not None and self.desktop.actor.role == Role.CUSTOMER,
            "FORBIDDEN",
            "请使用顾客账号登录后预订",
        )
        row = self.selected(self.table)
        require("quote_id" in row, "INVALID_INPUT", "请填写日期并重新查询")
        fields = self.form("填写联系人", [("name", "联系人", ""), ("phone", "联系电话", "")])
        if not fields:
            return
        command = BookingCommand(
            row["room_type_id"],
            row["check_in"],
            row["check_out"],
            row["rooms"],
            row["guests"],
            fields["name"],
            fields["phone"],
            row["quote_id"],
        )
        if command != self.last_payload:
            self.request_key = uuid.uuid4().hex
            self.last_payload = command
        if not messagebox.askyesno(
            "确认预订", f"本次总价¥{money(row['total_cents'])}，是否接受并提交？", parent=self
        ):
            return
        order = self.app.bookings.create(self.token, command, self.request_key)
        self.success(f"预订成功：{order['id']}，等待酒店确认")
        show_text(
            self.desktop,
            "预订成功",
            f"订单号：{order['id']}\n状态：待确认\n"
            f"确认截止（UTC）：{order['expires_at']}\n费用由酒店线下结算。",
        )


class OrdersPage(Page):
    def __init__(self, desktop):
        super().__init__(
            desktop, "订单管理", "提交操作时重新检查版本、状态和确认截止时间；请先选择订单。"
        )
        self.state = tk.StringVar()
        options = ttk.Combobox(
            self.toolbar,
            textvariable=self.state,
            values=[""] + list(STATUS_NAMES.values()),
            state="readonly",
            width=12,
        )
        options.pack(side="left", padx=(0, 12))
        self.button("刷新", self.refresh)
        self.button("查看详情", self.details)
        role = desktop.actor.role
        actions = {
            Role.CUSTOMER: [
                ("修改联系人", self.contact),
                ("修改住宿", self.modify),
                ("取消订单", lambda: self.transition("cancel")),
            ],
            Role.STAFF: [
                ("确认", lambda: self.transition("confirm")),
                ("拒绝", lambda: self.transition("reject")),
                ("办理入住", lambda: self.transition("check_in")),
                ("正常退房", lambda: self.transition("check_out")),
            ],
            Role.ADMIN: [("异常取消", lambda: self.transition("force_cancel"))],
        }
        for label, action in actions[role]:
            self.button(label, action)
        self.table = DataTable(
            self,
            [
                ("id", "订单编号", 230),
                ("hotel_name", "酒店", 150),
                ("room_name", "房型", 120),
                ("check_in", "入住", 110),
                ("check_out", "离店", 110),
                ("rooms", "间数", 65),
                ("price", "总价", 100),
                ("state", "状态", 90),
                ("version", "版本", 60),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        state = next((key for key, label in STATUS_NAMES.items() if label == self.state.get()), "")
        rows = self.app.bookings.list(self.token, state)
        self.table.set_rows(
            rows,
            lambda row: {
                **row,
                "price": money(row["total_cents"]),
                "state": STATUS_NAMES[Status(row["status"])],
            },
        )
        self.success(f"显示{len(rows)}笔订单（最多200笔）")

    def details(self):
        row = self.app.bookings.get(self.token, self.selected(self.table)["id"])
        lines = [
            f"订单：{row['id']}",
            f"{row['hotel_name']} / {row['room_name']}",
            f"状态：{STATUS_NAMES[Status(row['status'])]}，版本：{row['version']}",
            f"{row['check_in']}入住 → {row['check_out']}离店，{row['rooms']}间，{row['guests']}人",
            f"联系人：{row['contact_name']} / "
            f"{row['contact_phone'][:3]}****{row['contact_phone'][-4:]}",
            f"总价：¥{money(row['total_cents'])}",
            "酒店确认截止："
            + instant(row["expires_at"])
            .astimezone(ZoneInfo(row["time_zone"]))
            .strftime("%Y-%m-%d %H:%M:%S %Z"),
            "逐夜成交明细：",
        ]
        for night in row["nights"]:
            lines.append(
                f"  {night['stay_date']}  ¥{money(night['unit_price_cents'])} × "
                f"{night['quantity']}间，{night['allocation_state']}"
            )
        lines.append("操作历史：")
        for item in self.app.audit.query(self.token):
            if item["target"] == row["id"]:
                lines.append(
                    f"  {item['occurred_at']}  {item['action']}  {item['result']}  {item['reason']}"
                )
        show_text(self.desktop, "订单详情", "\n\n".join(lines))

    def transition(self, action):
        row, reason = self.selected(self.table), ""
        if action in ("reject", "force_cancel"):
            result = self.form("填写处理原因", [("reason", "原因", "")])
            if not result:
                return
            reason = result["reason"]
        if action == "check_in":
            if not messagebox.askyesno(
                "现场核验", "已在现场核对顾客身份和本酒店订单？", parent=self
            ):
                return
            reason = "现场核验通过"
        if action in ("cancel", "force_cancel") and not messagebox.askyesno(
            "确认取消", "取消后不可恢复，确定继续？", parent=self
        ):
            return
        result = self.app.bookings.transition(
            self.token,
            row["id"],
            action,
            row["version"],
            self.command_key([row["id"], action, row["version"], reason]),
            reason,
        )
        self.refresh()
        self.success(f"处理成功：{STATUS_NAMES[Status(result['status'])]}")

    def contact(self):
        row = self.selected(self.table)
        result = self.form(
            "修改联系人",
            [("name", "联系人", row["contact_name"]), ("phone", "联系电话", row["contact_phone"])],
        )
        if result:
            self.app.bookings.update_contact(
                self.token,
                row["id"],
                result["name"],
                result["phone"],
                row["version"],
                self.command_key([row["id"], "contact", row["version"], result]),
            )
            self.refresh()

    def modify(self):
        row = self.selected(self.table)
        result = self.form(
            "修改住宿方案",
            [
                ("room", "新房型编号（限原酒店）", row["room_type_id"]),
                ("start", "入住日期", row["check_in"]),
                ("end", "离店日期", row["check_out"]),
                ("rooms", "房间数", row["rooms"]),
                ("guests", "入住人数", row["guests"]),
            ],
        )
        if not result:
            return
        quote = self.app.bookings.quote_modification(
            self.token,
            row["id"],
            positive_int(result["room"], "房型编号"),
            result["start"],
            result["end"],
            positive_int(result["rooms"], "间数"),
            positive_int(result["guests"], "人数"),
        )
        if not messagebox.askyesno(
            "接受新价格", f"新总价¥{money(quote['total_cents'])}，是否保存？", parent=self
        ):
            return
        command = BookingCommand(
            quote["room_type_id"],
            quote["check_in"],
            quote["check_out"],
            quote["rooms"],
            quote["guests"],
            row["contact_name"],
            row["contact_phone"],
            quote["quote_id"],
        )
        self.app.bookings.modify(
            self.token,
            row["id"],
            command,
            row["version"],
            self.command_key([row["id"], "modify", row["version"], result, quote["quote_id"]]),
        )
        self.refresh()


class RoomsPage(Page):
    def __init__(self, desktop):
        super().__init__(desktop, "房型资料", "只管理本酒店的房型数量，不分配具体房间号。")
        self.button("刷新", self.refresh)
        self.button("新增房型", self.create)
        self.button("编辑选中房型", self.edit)
        self.table = DataTable(
            self,
            [
                ("id", "编号", 70),
                ("hotel_name", "酒店", 200),
                ("name", "房型名称", 220),
                ("capacity", "单间人数", 110),
                ("total_rooms", "总房数", 110),
                ("version", "版本", 80),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        self.table.set_rows(self.app.catalog.list_rooms(self.token))

    def create(self):
        result = self.form(
            "新增房型",
            [("name", "名称", ""), ("capacity", "可住人数", "2"), ("total", "房间总数", "10")],
        )
        if result:
            self.app.catalog.create_room(
                self.token,
                self.desktop.actor.hotel_id,
                result["name"],
                positive_int(result["capacity"], "人数"),
                positive_int(result["total"], "房数"),
            )
            self.refresh()

    def edit(self):
        row = self.selected(self.table)
        result = self.form(
            "编辑房型",
            [
                ("name", "名称", row["name"]),
                ("capacity", "可住人数", row["capacity"]),
                ("total", "房间总数", row["total_rooms"]),
            ],
        )
        if result:
            self.app.catalog.update_room(
                self.token,
                row["id"],
                result["name"],
                positive_int(result["capacity"], "人数"),
                positive_int(result["total"], "房数"),
                row["version"],
            )
            self.refresh()


class CalendarPage(Page):
    def __init__(self, desktop):
        super().__init__(
            desktop,
            "每日库存与价格",
            "供给总量 − 已占用 = 剩余；价格按元输入，离店日不包含在批量设置中。",
        )
        today = self.app.clock.now().astimezone(ZoneInfo("Asia/Shanghai")).date()
        owned_rooms = self.app.catalog.list_rooms(self.token)
        self.room = entry(
            self.toolbar, "房型编号", str(owned_rooms[0]["id"]) if owned_rooms else "", 8
        )
        self.start = entry(self.toolbar, "开始日", today.isoformat(), 13)
        self.end = entry(
            self.toolbar, "结束日（不含）", (today + timedelta(days=14)).isoformat(), 13
        )
        self.button("查询日历", self.refresh)
        self.button("批量设置", self.batch)
        self.button("编辑选中日期", self.edit)
        self.table = DataTable(
            self,
            [
                ("stay_date", "住宿日期", 140),
                ("supply", "供给总量", 120),
                ("reserved", "已占用", 120),
                ("available", "剩余", 120),
                ("price", "单晚价格", 140),
                ("sales", "销售状态", 120),
                ("version", "版本", 100),
            ],
        )
        self.table.pack(fill="both", expand=True)
        if owned_rooms:
            self.refresh()

    def refresh(self):
        room_id = positive_int(self.room.get(), "房型编号")
        rows = self.app.catalog.calendar(self.token, room_id, self.start.get(), self.end.get())
        self.table.set_rows(
            rows,
            lambda row: {
                **row,
                "price": money(row["price_cents"]),
                "sales": "停售" if row["sold_out"] else "可售",
            },
        )

    def apply(self, start, end, initial, version=None):
        values = self.form(
            "设置房量与价格",
            [
                ("supply", "供给总量", initial.get("supply", 10)),
                ("price", "单晚价格（元）", money(initial.get("price_cents", 29900))),
                (
                    "sales",
                    "销售状态",
                    "停售" if initial.get("sold_out") else "可售",
                    ["可售", "停售"],
                ),
            ],
        )
        if values:
            self.app.catalog.set_calendar(
                self.token,
                positive_int(self.room.get(), "房型编号"),
                start,
                end,
                values["supply"],
                values["price"],
                values["sales"] == "停售",
                version,
            )
            self.refresh()

    def batch(self):
        self.apply(self.start.get(), self.end.get(), {})

    def edit(self):
        row = self.selected(self.table)
        end = (date.fromisoformat(row["stay_date"]) + timedelta(days=1)).isoformat()
        self.apply(row["stay_date"], end, row, row["version"])


class HotelsPage(Page):
    def __init__(self, desktop):
        super().__init__(
            desktop,
            "酒店审核与营业状态",
            "停业立即阻止新订；未入住订单请到订单管理逐笔处理，已入住订单人工协调。",
        )
        self.button("刷新", self.refresh)
        self.button("登记酒店", self.create)
        self.button("审核通过 / 恢复营业", lambda: self.change("OPEN"))
        self.button("标记停业", lambda: self.change("CLOSED"))
        self.table = DataTable(
            self,
            [
                ("id", "编号", 70),
                ("name", "酒店", 180),
                ("city", "城市", 100),
                ("address", "地址", 230),
                ("contact", "联系电话", 150),
                ("state", "状态", 110),
                ("time_zone", "时区", 150),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        labels = {"OPEN": "营业中", "CLOSED": "停业", "PENDING": "待审核"}
        self.table.set_rows(
            self.app.catalog.list_hotels(self.token),
            lambda row: {**row, "state": labels[row["status"]]},
        )

    def create(self):
        fields = self.form(
            "登记酒店",
            [
                ("name", "酒店名称", ""),
                ("city", "城市", "南京"),
                ("address", "地址", ""),
                ("phone", "联系电话", ""),
                ("zone", "IANA时区", "Asia/Shanghai"),
            ],
        )
        if fields:
            self.app.catalog.create_hotel(
                self.token,
                fields["name"],
                fields["city"],
                fields["address"],
                fields["phone"],
                fields["zone"],
            )
            self.refresh()

    def change(self, status):
        row = self.selected(self.table)
        result = self.form("填写状态变更原因", [("reason", "原因", "")])
        if result:
            self.app.catalog.set_status(self.token, row["id"], status, result["reason"])
            self.refresh()


class StaffPage(Page):
    def __init__(self, desktop):
        super().__init__(
            desktop,
            "工作人员账号",
            "账号绑定唯一酒店；停用后已有登录立即失效，历史订单和日志保留。",
        )
        self.button("刷新", self.refresh)
        self.button("创建账号", self.create)
        self.button("启用", lambda: self.enable(True))
        self.button("停用", lambda: self.enable(False))
        self.table = DataTable(
            self,
            [
                ("id", "编号", 70),
                ("username", "账号", 150),
                ("display_name", "姓名", 150),
                ("hotel_id", "酒店编号", 110),
                ("hotel_name", "所属酒店", 230),
                ("state", "状态", 110),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        self.table.set_rows(
            self.app.auth.list_staff(self.token),
            lambda row: {**row, "state": "启用" if row["enabled"] else "停用"},
        )

    def create(self):
        result = self.form(
            "创建工作人员",
            [
                ("account", "账号", ""),
                ("password", "初始密码（至少8位）", ""),
                ("name", "姓名", ""),
                ("hotel", "酒店编号", "1"),
            ],
        )
        if result:
            self.app.auth.create_staff(
                self.token,
                result["account"],
                result["password"],
                result["name"],
                positive_int(result["hotel"], "酒店编号"),
            )
            self.refresh()

    def enable(self, enabled):
        self.app.auth.set_enabled(self.token, self.selected(self.table)["id"], enabled)
        self.refresh()


class StatsPage(Page):
    def __init__(self, desktop):
        super().__init__(
            desktop,
            "预订与间夜统计",
            "按计划入住日统计，开始日与结束日均计入；只计已确认、已入住和已退房。",
        )
        today = self.app.clock.now().astimezone(ZoneInfo("Asia/Shanghai")).date()
        self.start = entry(self.toolbar, "开始日（含）", today.isoformat(), 13)
        self.end = entry(self.toolbar, "结束日（含）", (today + timedelta(days=30)).isoformat(), 13)
        self.room = entry(self.toolbar, "房型编号（可空）", "", 12)
        self.button("统计", self.refresh)
        self.summary = tk.StringVar()
        ttk.Label(self, textvariable=self.summary, style="Heading.TLabel").pack(
            anchor="w", pady=(0, 15)
        )
        self.table = DataTable(
            self,
            [
                ("id", "订单", 240),
                ("status", "状态", 140),
                ("rooms", "间数", 100),
                ("check_in", "入住", 130),
                ("check_out", "离店", 130),
                ("room_nights", "间夜数", 110),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        result = self.app.reports.statistics(
            self.token,
            self.start.get(),
            self.end.get(),
            positive_int(self.room.get(), "房型编号") if self.room.get() else None,
        )
        self.summary.set(f"有效预订 {result['orders']} 笔     已预订 {result['room_nights']} 间夜")
        self.table.set_rows(
            result["rows"], lambda row: {**row, "status": STATUS_NAMES[Status(row["status"])]}
        )


class LogsPage(Page):
    def __init__(self, desktop):
        super().__init__(desktop, "操作记录", "按身份限制查询范围，日志只读；每次显示最多200条。")
        self.actor = entry(self.toolbar, "操作者编号（可空）", "", 17)
        self.action = entry(self.toolbar, "动作类型（可空）", "", 20)
        self.start = entry(self.toolbar, "UTC起点（可空）", "", 22)
        self.end = entry(self.toolbar, "UTC终点（可空）", "", 22)
        self.button("查询", self.refresh)
        self.table = DataTable(
            self,
            [
                ("occurred_at", "UTC时间", 230),
                ("actor_name", "操作者", 130),
                ("action", "动作", 180),
                ("target", "对象", 230),
                ("before_state", "原状态", 110),
                ("after_state", "新状态", 110),
                ("result", "结果", 100),
                ("reason", "原因", 240),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        self.table.set_rows(
            self.app.audit.query(
                self.token,
                int(self.actor.get()) if self.actor.get() else None,
                self.action.get(),
                self.start.get(),
                self.end.get(),
            )
        )


class NotificationsPage(Page):
    def __init__(self, desktop):
        super().__init__(
            desktop, "通知待办", "记录线下联系结果，不接入短信或第三方渠道；联系失败可标记重试。"
        )
        self.button("刷新", self.refresh)
        self.button("已联系", lambda: self.mark(True))
        self.button("联系失败 / 重试", lambda: self.mark(False))
        self.table = DataTable(
            self,
            [
                ("id", "编号", 70),
                ("booking_id", "订单", 240),
                ("message", "通知内容", 400),
                ("state", "处理状态", 100),
                ("attempts", "尝试次数", 100),
            ],
        )
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        self.table.set_rows(self.app.reports.notifications(self.token))

    def mark(self, done):
        self.app.reports.mark_notification(self.token, self.selected(self.table)["id"], done)
        self.refresh()


class SystemPage(Page):
    def __init__(self, desktop):
        super().__init__(
            desktop,
            "数据检查与备份",
            "备份使用SQLite在线备份接口；恢复只在关闭程序后通过命令行输出到新的数据库文件。",
        )
        self.button("一致性检查", self.diagnose)
        self.button("立即备份", self.backup)
        self.button("运行到期处理", self.sweep)
        self.output = tk.Text(self, wrap="word", font=("Consolas", 11), padx=16, pady=16)
        self.output.pack(fill="both", expand=True)
        self.output.insert(
            "1.0",
            f"当前数据库：{self.app.database.path}\n\n后台每5秒检查超时与未入住，每24小时自动备份。",
        )
        self.output.configure(state="disabled")

    def display(self, result):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", json.dumps(result, ensure_ascii=False, indent=2))
        self.output.configure(state="disabled")

    def diagnose(self):
        self.display(self.app.reports.diagnose(self.token))

    def backup(self):
        self.display(self.app.jobs.backup(self.token))

    def sweep(self):
        self.display(self.app.jobs.run())
