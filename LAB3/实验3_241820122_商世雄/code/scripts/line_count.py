"""Count physical lines and Python logical statements, excluding tests and generated files."""

import ast
import io
import json
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count_file(path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    excluded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                excluded.update(range(node.lineno, node.end_lineno + 1))
    comments = set()
    code = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comments.add(token.start[0])
        elif token.type not in {
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENDMARKER,
            tokenize.ENCODING,
        }:
            code.update(range(token.start[0], token.end[0] + 1))
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "physical": len(source.splitlines()),
        "code_without_docstrings": len(code - excluded),
        "comment_only": len(comments - code),
        "logical_statements": sum(isinstance(node, ast.stmt) for node in ast.walk(tree)),
    }


def main():
    rows = [count_file(p) for p in sorted((ROOT / "src").rglob("*.py"))]
    totals = {key: sum(row[key] for row in rows) for key in rows[0] if key != "path"}
    result = {
        "scope": "src/stay only; no tests, scripts, caches or generated GUI code",
        "files": rows,
        "totals": totals,
    }
    destination = ROOT / "evidence" / "line-count.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
