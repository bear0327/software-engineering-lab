"""Lifecycle jobs, retention and online backups with verifiable manifests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

from stay.audit import ensure_admin
from stay.booking import BookingService
from stay.domain import stamp
from stay.reports import ReportService


class LifecycleJob:
    def __init__(self, booking: BookingService, backup_dir: Path):
        self.booking = booking
        self.backup_dir = backup_dir

    def run(self) -> dict:
        with self.booking.database.transaction() as connection:
            count = self.booking.sweep_due(connection)
            now = self.booking.clock.now()
            connection.execute("DELETE FROM session WHERE expires_at<=?", (stamp(now),))
            removed = connection.execute(
                "DELETE FROM audit_log WHERE occurred_at<?", (stamp(now - timedelta(days=180)),)
            ).rowcount
        return {"lifecycle_changes": count, "expired_logs_removed": removed}

    def backup(self, token: str) -> dict:
        with self.booking.database.read() as connection:
            ensure_admin(connection, self.booking.auth, token)
        now = self.booking.clock.now()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        path = self.backup_dir / (now.strftime("stay-%Y%m%d-%H%M%S-%f") + ".sqlite3")
        self.booking.database.backup(path)
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            diagnostics = ReportService.check_consistency(connection)
        manifest = {
            "file": path.name,
            "created_at": stamp(now),
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "diagnostics": diagnostics,
        }
        path.with_suffix(".json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest

    def auto_backup(self) -> Path | None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        markers = sorted(self.backup_dir.glob("auto-*.sqlite3"))
        now = self.booking.clock.now()
        if markers:
            latest = markers[-1]
            age = now.timestamp() - latest.stat().st_mtime
            if age < 24 * 3600:
                return None
        path = self.backup_dir / (now.strftime("auto-%Y%m%d-%H%M%S-%f") + ".sqlite3")
        return self.booking.database.backup(path)
