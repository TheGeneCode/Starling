# ruff: noqa: INP001
"""
PostToolUse hook: run ruff on an edited .py file and feed findings back to Claude.

Reads the hook payload from stdin. Exits 2 with ruff's findings on stderr when the
edited file has lint errors (Claude Code feeds exit-2 stderr back to the model);
exits 0 otherwise. Files outside the project root are ignored.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def should_check(file_path: str) -> bool:
    """Return True when the edited file is a Python file inside the project."""
    if not file_path.endswith(".py"):
        return False
    target = Path(file_path)
    if not target.exists():
        return False
    try:
        target.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return False
    return True


def main() -> int:
    """Run ruff against the file named in the hook payload."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not should_check(file_path):
        return 0
    uv = shutil.which("uv")
    if uv is None:
        return 0
    # Fixed argv; only the lint target varies, and it is path-validated above.
    try:
        result = subprocess.run(  # noqa: S603
            [uv, "run", "--no-sync", "ruff", "check", file_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=50,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    # ruff exits 1 for lint findings; 2 (or uv's own spawn failure) means the
    # tool itself broke, which is not feedback the model can act on.
    if result.returncode == 1:
        sys.stderr.write(result.stdout + result.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
