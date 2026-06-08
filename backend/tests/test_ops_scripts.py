"""Sanity checks for the operational shell scripts (bash parse / shellcheck-lite)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# backend/tests/test_ops_scripts.py -> parents[2] == repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = [
    REPO_ROOT / "infra" / "scripts" / "backup_db.sh",
    REPO_ROOT / "infra" / "scripts" / "restore_db.sh",
]


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_exists_and_is_executable(script: Path) -> None:
    assert script.is_file(), f"missing {script}"
    assert script.stat().st_mode & 0o111, f"{script.name} is not executable"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_parses_with_bash(script: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:  # extremely unlikely on CI/dev, but don't hard-fail
        pytest.skip("bash not available")
    result = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_is_strict_mode(script: Path) -> None:
    # Guard against accidentally dropping `set -euo pipefail` (fail-fast scripts).
    assert "set -euo pipefail" in script.read_text(encoding="utf-8")
