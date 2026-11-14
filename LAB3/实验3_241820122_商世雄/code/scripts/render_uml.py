"""Render PlantUML sources using an explicitly supplied local PlantUML jar."""

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jar", type=Path, required=True)
    args = parser.parse_args()
    directory = Path(__file__).resolve().parents[2] / "UML"
    command = [
        "java",
        "-Djava.awt.headless=true",
        "-jar",
        str(args.jar.resolve()),
        "-charset",
        "UTF-8",
        "-tpng",
        "*.puml",
    ]
    result = subprocess.run(command, cwd=directory, capture_output=True, check=False)
    if result.returncode:
        print(result.stderr.decode("utf-8", errors="replace"))
        return result.returncode
    images = []
    for source in sorted(directory.glob("*.puml")):
        with Image.open(source.with_suffix(".png")) as image:
            images.append(
                {
                    "file": source.with_suffix(".png").name,
                    "width": image.width,
                    "height": image.height,
                }
            )
            image.verify()
    output = directory.parent / "code/evidence/uml-render.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"renderer": args.jar.name, "images": images}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Rendered and decoded {len(images)} UML PNG files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
