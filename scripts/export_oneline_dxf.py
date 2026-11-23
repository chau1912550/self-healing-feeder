"""Write the feeder's one-line diagram as a DXF for AutoCAD: cad/feeder_oneline.dxf.

Drawn from results/feeder_geometry.json and results/zones.csv (run python run.py first).
Open it in AutoCAD, tidy the layout, save as cad/feeder_oneline.dwg, then plot the
"A3 ONE-LINE" layout to exports/ and register the exports (see workflow.toml).

    .venv\\Scripts\\python scripts\\export_oneline_dxf.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shf import cad  # noqa: E402


def main() -> None:
    path = cad.export()
    print(f"wrote {path.relative_to(ROOT)} (drawn from results, fingerprint {cad.input_sha256()[:12]})")


if __name__ == "__main__":
    main()
