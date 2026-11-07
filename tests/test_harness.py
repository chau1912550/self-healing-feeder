"""The API registry and the content check (no OpenDSS needed)."""
import subprocess
import sys
from pathlib import Path

import pytest

from shf import apis

ROOT = Path(__file__).resolve().parent.parent


def test_api_registry_parses_and_planned_keys_are_refused():
    rows = apis.registry()
    assert rows and all(r["Status"] in apis.STATUSES for r in rows)
    planned = next(r for r in rows if r["Status"] == "planned")
    with pytest.raises(PermissionError):
        apis.key(planned["Name"])
    with pytest.raises(KeyError):
        apis.key("no such service")


def test_content_check_passes_on_the_committed_results():
    out = subprocess.run([sys.executable, str(ROOT / "harness" / "check.py")], capture_output=True, text=True,
                         encoding="utf-8", cwd=ROOT)
    assert out.returncode == 0, out.stdout
