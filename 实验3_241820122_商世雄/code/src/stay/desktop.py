"""Native Tkinter desktop shell, session handling and background maintenance."""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from stay.application import Application
from stay.domain import ROLE_NAMES, BusinessError, Role
from stay.pages import (
    CalendarPage,
    HotelsPage,
    LogsPage,
    NotificationsPage,
    OrdersPage,
    RoomsPage,
    SearchPage,
    StaffPage,
    StatsPage,
    SystemPage,
)
from stay.widgets import FormDialog


class MaintenanceWorker:
    def __init__(self, app: Application):
        self.app = app
        self.stop_event = threading.Event()
        self.events = queue.Queue()
        self.thread = threading.Thread(target=self.run, name="lifecycle-worker", daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try:
                result = self.app.jobs.run()
                self.app.jobs.auto_backup()
                if result["lifecycle_changes"]:
                    self.events.put(
                        f"后台已处理{result['lifecycle_changes']}笔到期订单，请刷新列表"
                    )
            except (sqlite3.Error, OSError):
                logging.exception("Background maintenance failed")
                self.events.put("后台处理暂时失败，稍后重试；写接口仍会检查截止时间")
            self.stop_event.wait(5)

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2)


class Desktop(tk.Tk):
    def __init__(self, app: Application, start_worker: bool = True):
        super().__init__()
        self.app = app
        self.token = ""
        self.actor = None
        self.page = None
        self.worker = MaintenanceWorker(app)
        self.title("泊岸酒店预订系统")
        self.geometry("1280x840")
        self.minsize(1100, 700)
        self.configure(background="#F3F6F7")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), background="#F3F6F7")
        style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 18), foreground="#172B3A")
        style.configure("Muted.TLabel", foreground="#637A86")
        style.configure("Treeview", background="white", fieldbackground="white", rowheight=31)
        style.configure("Treeview.Heading", padding=8)
        style.configure("TButton", padding=(10, 7))
        self.notice = tk.StringVar(value="就绪")
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        ttk.Label(self, textvariable=self.notice, style="Muted.TLabel", padding=8).pack(fill="x")
        self.content = self.body
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.login_view()
        if start_worker:
            self.worker.start()
            self.after(1000, self.poll_worker)

    def invoke(self, action):
        try:
            return action()
        except BusinessError as error:
            messagebox.showerror(
                "操作未完成", f"{error.message}\n\n错误代码：{error.code}", parent=self
            )
            self.notice.set(error.message)
        except (ValueError, TypeError):
            messagebox.showerror("输入格式错误", "请检查数字、日期及必填信息。", parent=self)
        except (sqlite3.Error, OSError):
            logging.exception("Desktop operation failed")
            messagebox.showerror(
                "暂时无法完成", "操作没有完整提交，请刷新后使用原请求重试。", parent=self
            )
        return None

    def clear(self):
        for child in self.body.winfo_children():
            child.destroy()

    def login_view(self):
        self.clear()
        box = ttk.Frame(self.body, padding=40)
        box.place(relx=0.5, rely=0.45, anchor="center")
        ttk.Label(box, text="泊岸酒店预订系统", style="Heading.TLabel").pack(pady=(0, 14))
        ttk.Label(box, text="查询、预订和酒店日常管理", style="Muted.TLabel").pack(pady=(0, 25))
        self.account = tk.StringVar(value="customer")
        self.password = tk.StringVar()
        ttk.Label(box, text="账号").pack(anchor="w")
        ttk.Entry(box, textvariable=self.account, width=38).pack(pady=(6, 16))
        ttk.Label(box, text="密码").pack(anchor="w")
        secret = ttk.Entry(box, textvariable=self.password, width=38, show="*")
        secret.pack(pady=(6, 20))
        secret.bind("<Return>", lambda _event: self.invoke(self.login))
        ttk.Button(box, text="登录", command=lambda: self.invoke(self.login)).pack(fill="x", pady=5)
        ttk.Button(box, text="注册顾客账号", command=lambda: self.invoke(self.register)).pack(
            fill="x", pady=5
        )
        ttk.Button(box, text="游客查房", command=lambda: self.shell(guest=True)).pack(
            fill="x", pady=5
        )
        ttk.Label(
            box, text="首次使用账号见运行说明，工作人员账号由管理员创建。", style="Muted.TLabel"
        ).pack(pady=(24, 0))

    def login(self):
        self.token = self.app.auth.login(self.account.get(), self.password.get())
        self.actor = self.app.auth.current(self.token)
        self.password.set("")
        self.shell()

    def register(self):
        result = FormDialog(
            self,
            "注册顾客",
            [("account", "账号", ""), ("name", "姓名", ""), ("password", "密码（8至128位）", "")],
        ).result
        if result:
            self.app.auth.register(result["account"], result["password"], result["name"])
            self.account.set(result["account"])
            messagebox.showinfo("注册成功", "请使用新账号登录。", parent=self)

    def shell(self, guest=False):
        self.clear()
        top = ttk.Frame(self.body, padding=(20, 12))
        top.pack(fill="x")
        ttk.Label(top, text="泊岸 / STAY", style="Heading.TLabel").pack(side="left")
        label = (
            "游客（只读）" if guest else f"{self.actor.username} · {ROLE_NAMES[self.actor.role]}"
        )
        ttk.Label(top, text=label).pack(side="right", padx=16)
        ttk.Button(top, text="返回登录" if guest else "退出登录", command=self.logout).pack(
            side="right"
        )
        if not guest:
            ttk.Button(
                top, text="修改密码", command=lambda: self.invoke(self.change_password)
            ).pack(side="right", padx=8)
        layout = ttk.Frame(self.body)
        layout.pack(fill="both", expand=True)
        side = ttk.Frame(layout, padding=12, width=185)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.content = ttk.Frame(layout)
        self.content.pack(side="left", fill="both", expand=True)
        menus = [("酒店与空房", SearchPage)]
        if not guest:
            role = self.actor.role
            if role == Role.CUSTOMER:
                menus += [("我的订单", OrdersPage), ("订单操作历史", LogsPage)]
            elif role == Role.STAFF:
                menus = [
                    ("本酒店订单", OrdersPage),
                    ("房型资料", RoomsPage),
                    ("每日库存与价格", CalendarPage),
                    ("统计", StatsPage),
                    ("操作日志", LogsPage),
                    ("通知待办", NotificationsPage),
                ]
            else:
                menus = [
                    ("酒店审核与启停", HotelsPage),
                    ("工作人员账号", StaffPage),
                    ("平台订单 / 异常", OrdersPage),
                    ("全平台统计", StatsPage),
                    ("全平台日志", LogsPage),
                    ("通知待办", NotificationsPage),
                    ("数据检查与备份", SystemPage),
                ]
        for title, page_type in menus:
            ttk.Button(
                side,
                text=title,
                command=lambda page=page_type: self.invoke(lambda: self.show_page(page)),
            ).pack(fill="x", pady=5)
        self.show_page(menus[0][1])

    def show_page(self, page_type):
        for child in self.content.winfo_children():
            child.destroy()
        self.page = page_type(self)
        self.page.pack(fill="both", expand=True)

    def logout(self):
        if self.token:
            self.app.auth.logout(self.token)
        self.token, self.actor = "", None
        self.login_view()

    def change_password(self):
        result = FormDialog(
            self,
            "修改密码",
            [
                ("old_password", "原密码", ""),
                ("new_password", "新密码（8至128位）", ""),
                ("repeat_password", "确认新密码", ""),
            ],
        ).result
        if not result:
            return
        if result["new_password"] != result["repeat_password"]:
            raise BusinessError("INVALID_INPUT", "两次新密码不一致")
        self.app.auth.change_password(self.token, result["old_password"], result["new_password"])
        self.token, self.actor = "", None
        self.login_view()
        self.notice.set("密码已修改，所有旧登录已失效，请重新登录")

    def poll_worker(self):
        try:
            while True:
                self.notice.set(self.worker.events.get_nowait())
        except queue.Empty:
            pass
        self.after(1000, self.poll_worker)

    def close(self):
        if self.worker.thread.is_alive():
            self.worker.close()
        self.destroy()
