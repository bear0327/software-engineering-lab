"""Launch from a source checkout without installing the project."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from stay.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
