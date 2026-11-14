"""Reusable desktop forms, tables and read-only detail windows."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class DataTable(ttk.Frame):
    def __init__(self, parent, columns: list[tuple[str, str, int]]):
        super().__init__(parent)
        self.rows = {}
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings", height=15)
        for key, label, width in columns:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=65, anchor="w")
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def set_rows(self, rows: list[dict], formatter: Callable | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        keys = self.tree["columns"]
        for index, original in enumerate(rows):
            display = formatter(original) if formatter else original
            iid = str(index)
            self.tree.insert("", "end", iid=iid, values=[display.get(k, "") for k in keys])
            self.rows[iid] = original

    def selected(self) -> dict | None:
        selection = self.tree.selection()
        return self.rows.get(selection[0]) if selection else None


class FormDialog(tk.Toplevel):
    def __init__(self, parent, title: str, fields: list[tuple]):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result = None
        self.variables = {}
        self.transient(parent)
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        for index, field in enumerate(fields):
            key, label, value = field[:3]
            options = field[3] if len(field) > 3 else None
            variable = tk.StringVar(value=str(value))
            self.variables[key] = variable
            ttk.Label(frame, text=label).grid(row=index, column=0, sticky="w", padx=(0, 14), pady=7)
            if options:
                control = ttk.Combobox(
                    frame, textvariable=variable, values=options, state="readonly", width=37
                )
            else:
                control = ttk.Entry(
                    frame, textvariable=variable, width=40, show="*" if "password" in key else ""
                )
            control.grid(row=index, column=1, sticky="ew", pady=7)
            if index == 0:
                control.focus_set()
        controls = ttk.Frame(frame)
        controls.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(controls, text="确定", command=self.submit).pack(side="left", padx=5)
        ttk.Button(controls, text="取消", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda _event: self.submit())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.grab_set()
        self.wait_window()

    def submit(self):
        self.result = {key: variable.get().strip() for key, variable in self.variables.items()}
        self.destroy()


def show_text(parent, title: str, value: str) -> None:
    window = tk.Toplevel(parent)
    window.title(title)
    window.geometry("850x650")
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    viewer = tk.Text(frame, wrap="word", font=("Microsoft YaHei UI", 11), padx=12, pady=12)
    scroll = ttk.Scrollbar(frame, command=viewer.yview)
    viewer.configure(yscrollcommand=scroll.set)
    viewer.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    viewer.insert("1.0", value)
    viewer.configure(state="disabled")


def entry(parent, label: str, value: str = "", width: int = 16) -> tk.StringVar:
    frame = ttk.Frame(parent)
    frame.pack(side="left", padx=(0, 12), pady=6)
    ttk.Label(frame, text=label).pack(anchor="w")
    variable = tk.StringVar(value=value)
    ttk.Entry(frame, textvariable=variable, width=width).pack(anchor="w", pady=(5, 0))
    return variable
