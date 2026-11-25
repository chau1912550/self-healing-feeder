"""Integration checks ensuring the bundled Tier-1 hif_sensor/ subproject and its published
docs/hif-sensor/ report page stay verified alongside self-healing-feeder."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIF_DIR = ROOT / "hif_sensor"
DOCS_HIF = ROOT / "docs" / "hif-sensor"


def test_hif_sensor_provenance_and_published_page():
    assert (HIF_DIR / "hif" / "provenance.py").is_file()
    sys.path.insert(0, str(HIF_DIR))
    try:
        import importlib
        prov = importlib.import_module("hif.provenance")
        res = prov.verify_manifest(HIF_DIR, HIF_DIR / "results" / "provenance" / "manifest.json")
    finally:
        sys.path.remove(str(HIF_DIR))
    assert res["ok"], f"hif_sensor provenance mismatch: {res}"
    assert res["checked"] >= 7

    html_path = DOCS_HIF / "index.html"
    assert html_path.is_file(), "Run python -m shf.dashboard to build docs/hif-sensor/index.html"
    body = html_path.read_text(encoding="utf-8")
    # Every figure and data link referenced in docs/hif-sensor/index.html must exist on disk.
    for rel in re.findall(r'(?:src|href)="(figures/[^"]+|data/[^"]+)"', body):
        assert (DOCS_HIF / rel).is_file(), f"Missing published asset docs/hif-sensor/{rel}"
    # Unified 3-tab hub links back to root FLISR and Monitor
    assert "../index.html" in body
    assert "../monitor/" in body
    # Verify exact Phase 0 model constants match published JSON
    m = json.loads((HIF_DIR / "results" / "metrics.json").read_text(encoding="utf-8"))
    assert m["model"]["params"] == 417
    assert m["model"]["bytes_int8_weights_float_bias"] == 504
