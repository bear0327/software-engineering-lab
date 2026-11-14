"""Install the wheel into an isolated target and run it without system site-packages."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    wheel = sorted((ROOT / "dist").glob("*.whl"))[-1]
    evidence = ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    logs = []
    with tempfile.TemporaryDirectory(prefix="stay-wheel-") as directory:
        command = [sys.executable, "-m", "pip", "install", "--target", directory, str(wheel)]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        logs.extend(["$ " + " ".join(command), result.stdout, result.stderr])
        if result.returncode:
            raise RuntimeError("Wheel installation failed: " + result.stderr)
        program = (
            "import json,sys; sys.path.insert(0,sys.argv[1]); "
            "import stay; from stay.__main__ import self_test; "
            "print(json.dumps({'loaded_from':stay.__file__,'result':self_test()},indent=2))"
        )
        command = [sys.executable, "-I", "-S", "-c", program, directory]
        result = subprocess.run(
            command,
            cwd=directory,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        logs.extend(
            [
                "$ " + " ".join(command),
                result.stdout,
                result.stderr,
                f"Exit code: {result.returncode}",
            ]
        )
        (evidence / "wheel-install.txt").write_text("\n".join(logs), encoding="utf-8")
        if result.returncode:
            return result.returncode
        result_data = json.loads(result.stdout)
        assert Path(result_data["loaded_from"]).is_relative_to(Path(directory))
        (evidence / "wheel-install.json").write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print("Installed wheel smoke check passed without system site-packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
