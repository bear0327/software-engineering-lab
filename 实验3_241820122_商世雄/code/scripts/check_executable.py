"""Launch the real Windows executable, capture its GUI and close it normally."""

import ctypes
import hashlib
import json
import subprocess
import tempfile
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]


def main():
    executable = ROOT / "dist/StayHotel/StayHotel.exe"
    user32 = ctypes.windll.user32
    user32.WaitForInputIdle.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    user32.WaitForInputIdle.restype = wintypes.DWORD
    handles = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    with tempfile.TemporaryDirectory(prefix="stay-executable-") as directory:
        process = subprocess.Popen([str(executable), "--db", str(Path(directory) / "demo.sqlite3")])
        try:
            wait_result = user32.WaitForInputIdle(wintypes.HANDLE(process._handle), 30000)
            if wait_result:
                raise RuntimeError(f"Executable GUI did not become ready: {wait_result}")

            @callback_type
            def visit(handle, _context):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
                if pid.value == process.pid and user32.IsWindowVisible(handle):
                    handles.append(handle)
                return True

            user32.EnumWindows(visit, 0)
            if not handles:
                raise RuntimeError("Executable has no visible application window")
            handle = handles[0]
            rect = wintypes.RECT()
            user32.GetWindowRect(handle, ctypes.byref(rect))
            output = ROOT.parent / "运行材料/界面截图/10_EXE启动.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom)).save(output)
            user32.PostMessageW(handle, 0x0010, 0, 0)  # WM_CLOSE: normal application shutdown.
            exit_code = process.wait(timeout=30)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        result = {
            "ok": exit_code == 0,
            "executable": executable.name,
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "visible_window": True,
            "exit_code": exit_code,
            "screenshot": output.name,
        }
        (ROOT / "evidence/executable-gui.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
