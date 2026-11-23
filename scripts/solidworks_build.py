"""Build the generic 3D equipment in SolidWorks and export it (Windows, SolidWorks 2026).

    .venv\\Scripts\\python scripts\\solidworks_build.py [--part NAME|all] [--register]

Attaches to the running SolidWorks (or starts it), builds mech/<part>.sldprt from the size
tables in config.py, and saves exports/<part>.step, .glb (for the report's 3D view) and .png.
--register records the exports in exports/registered.json (asset ids mech-<part>-glb/-step/-png).
Do not click inside SolidWorks while it runs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shf import assets, mech  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="all", choices=["all", *mech.PARTS], help="which part to build")
    ap.add_argument("--register", action="store_true", help="record the fresh exports in exports/registered.json")
    args = ap.parse_args()
    start = time.time()
    names = list(mech.PARTS) if args.part == "all" else [args.part]
    for name in names:
        t = time.time()
        summary = mech.build(name)
        missing = [n for n, f in summary["files"].items() if not f["exists"] or not f["bytes"]]
        if missing:
            sys.exit(f"SolidWorks did not write: {', '.join(missing)}")
        sizes = ", ".join(f"{n} {f['bytes'] / 1e3:.0f} kB" for n, f in summary["files"].items())
        print(f"  {name}: {summary['solids']} solids in {time.time() - t:.0f} s ({sizes})")
        if args.register:
            for kind in ("glb", "step", "png"):
                assets.register(f"mech-{name.replace('_', '-')}-{kind}")
    print(json.dumps({"parts": names, "seconds": round(time.time() - start)}))


if __name__ == "__main__":
    main()
