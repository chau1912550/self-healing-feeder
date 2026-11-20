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

def test_app_exports_go_stale_when_their_source_changes(tmp_path):
    from shf import assets
    (tmp_path / "cad").mkdir()
    (tmp_path / "exports").mkdir()
    src, exp = tmp_path / "cad" / "oneline.dwg", tmp_path / "exports" / "oneline.pdf"
    src.write_bytes(b"drawing v1")
    exp.write_bytes(b"pdf v1")
    manifest, reg = tmp_path / "workflow.toml", tmp_path / "exports" / "registered.json"
    manifest.write_text('[[asset]]\nid = "oneline"\ntool = "AutoCAD"\nsource = "cad/oneline.dwg"\n'
                        'export = "exports/oneline.pdf"\nsupports = "test"\n', encoding="utf-8")
    a = assets.load(manifest)[0]
    assert not assets.status(a, tmp_path, assets.registered(reg))[0]          # exported but not registered
    assets.register("oneline", tmp_path, manifest, reg)
    assert assets.status(a, tmp_path, assets.registered(reg))[0]
    src.write_bytes(b"drawing v2")                                             # edited after the export
    ok, msg = assets.status(a, tmp_path, assets.registered(reg))
    assert not ok and "changed after its export" in msg
    with pytest.raises(KeyError):
        assets.register("nope", tmp_path, manifest, reg)
