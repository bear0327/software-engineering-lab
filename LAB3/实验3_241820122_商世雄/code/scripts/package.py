"""Create clean source/material and portable archives; require a real PDF for final submission."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
SUBMISSION = CODE.parent
LAB = SUBMISSION.parent


def included(path):
    relative = path.relative_to(SUBMISSION)
    if any(
        part in {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "build", ".git"}
        or part.endswith(".egg-info")
        for part in relative.parts
    ):
        return False
    if path.name in {".coverage", "coverage.xml"} or path.suffix in {".pyc", ".spec"}:
        return False
    return not (path.suffix in {".sqlite3", ".db"} or ".sqlite3-" in path.name)


def describe(path):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        count = len(archive.namelist())
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "files": count,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--final", action="store_true", help="Require 实验报告.pdf before packaging"
    )
    args = parser.parse_args()
    report = SUBMISSION / "实验报告.pdf"
    report_ready = report.is_file() and report.read_bytes().startswith(b"%PDF-")
    if args.final and not report_ready:
        parser.error("缺少有效的实验报告.pdf，请先独立完成报告，不能把程序材料包当作最终提交")
    portable = CODE / "dist/StayHotel"
    if not (portable / "StayHotel.exe").is_file():
        parser.error("请先执行 scripts/build.py 生成可运行程序")
    archives = []
    target = LAB / (SUBMISSION.name + (".zip" if args.final else "_程序与材料.zip"))
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(SUBMISSION.rglob("*")):
            if path.is_file() and included(path):
                archive.write(
                    path, (Path(SUBMISSION.name) / path.relative_to(SUBMISSION)).as_posix()
                )
    archives.append(describe(target))
    target = LAB / "泊岸酒店预订系统_Windows便携版.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(portable.rglob("*")):
            if path.is_file():
                archive.write(path, (Path("StayHotel") / path.relative_to(portable)).as_posix())
        archive.writestr(
            "启动说明.txt",
            "解压完整目录后打开StayHotel/StayHotel.exe。\n"
            "顾客customer / Guest2026!；酒店staff / Staff2026!；管理员admin / Admin2026!。\n"
            "不要单独复制exe，需保留_internal目录。演示账号请勿用于真实资料。\n",
        )
    archives.append(describe(target))
    result = {
        "final_submission": args.final,
        "report_pdf_present": report_ready,
        "archives": archives,
    }
    (LAB / "归档校验.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
