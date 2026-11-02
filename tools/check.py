#!/usr/bin/env python3
"""Run the repository's lightweight source checks and unit tests."""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    files = []
    for directory in ("build", "config", "rootfs", "src", "tests", "tools"):
        base = ROOT / directory
        if base.exists():
            files.extend(p for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    failures = []
    shells = 0
    for path in sorted(files):
        if path.suffix == ".py":
            try:
                ast.parse(path.read_text(), filename=str(path))
            except (SyntaxError, UnicodeError) as error:
                failures.append(f"{path.relative_to(ROOT)}: {error}")
        else:
            try:
                first_line = path.open("rb").readline(256).decode("utf-8")
            except UnicodeError:
                continue
            if first_line.startswith("#!") and ("/sh" in first_line or "bash" in first_line):
                interpreter = "bash" if "bash" in first_line else "sh"
                result = subprocess.run([interpreter, "-n", str(path)], capture_output=True, text=True)
                shells += 1
                if result.returncode:
                    failures.append(result.stderr)
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        return 1
    print(f"Syntax checks passed ({shells} shell scripts).", flush=True)
    unit_dir = ROOT / "tests/unit"
    if not unit_dir.is_dir() or not list(unit_dir.glob("test_*.py")):
        print("No unit tests found; refusing an empty validation run.", file=sys.stderr)
        return 1
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(unit_dir), "-v"],
        cwd=ROOT,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
