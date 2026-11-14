"""Run reproducible quality checks and retain unedited stdout/stderr with exit codes."""

import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    evidence = ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    source_hashes = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in ("src", "tests")
        for path in sorted((ROOT / folder).rglob("*.py"))
    }
    commands = {
        "ruff": ["-m", "ruff", "check", "."],
        "format": ["-m", "ruff", "format", "--check", "."],
        "pylint": ["-m", "pylint", "src/stay", "--output-format=text"],
        "pytest": [
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "--cov=stay",
            "--cov-report=term-missing",
            "--cov-report=xml:evidence/coverage.xml",
            "--junitxml=evidence/tests.xml",
        ],
        "source-self-test": ["run.py", "--self-test", "--output", "evidence/source-self-test.json"],
        "line-count": ["scripts/line_count.py"],
    }
    results = []
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    for name, arguments in commands.items():
        command = [sys.executable, *arguments]
        run = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        (evidence / f"{name}.txt").write_text(
            "$ "
            + " ".join(command)
            + "\n\n"
            + run.stdout
            + run.stderr
            + f"\nExit code: {run.returncode}\n",
            encoding="utf-8",
        )
        results.append({"check": name, "exit_code": run.returncode})
        print(f"{name}: {run.returncode}", flush=True)
    manifest = {
        "executed_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
        "results": results,
        "ok": all(row["exit_code"] == 0 for row in results),
        "source_and_test_sha256": source_hashes,
    }
    (evidence / "verification.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
