"""Build a wheel, source archive and Windows one-directory portable application."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    evidence = ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    steps = [
        ("build-wheel", [sys.executable, "-m", "build"]),
        (
            "build-executable",
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onedir",
                "--windowed",
                "--name",
                "StayHotel",
                "--paths",
                "src",
                "--collect-all",
                "tzdata",
                "run.py",
            ],
        ),
        (
            "frozen-self-test",
            [
                str(ROOT / "dist/StayHotel/StayHotel.exe"),
                "--self-test",
                "--output",
                "evidence/frozen-self-test.json",
            ],
        ),
    ]
    results = []
    for name, command in steps:
        run = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
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
        results.append({"step": name, "exit_code": run.returncode})
        print(f"{name}: {run.returncode}", flush=True)
        if run.returncode:
            break
    result = {
        "executed_at": datetime.now(UTC).isoformat(),
        "steps": results,
        "ok": len(results) == len(steps) and all(r["exit_code"] == 0 for r in results),
    }
    (evidence / "build.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
