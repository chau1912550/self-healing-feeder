"""Generate A3 zone-level one-line DXF drawings (and optionally AutoCAD DWG + PDF exports)
for all 11 test feeders beyond IEEE 123-bus, directly from results/feeders/feeder_maps.json.

    .venv\\Scripts\\python scripts\\export_feeder_onelines.py --dxf-only
    .venv\\Scripts\\python scripts\\export_feeder_onelines.py --register
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shf import assets, feeder_cad  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dxf-only", action="store_true", help="write cad/oneline_<feeder>.dxf only (no AutoCAD needed)")
    ap.add_argument("--register", action="store_true", help="record fresh exports in exports/registered.json")
    ap.add_argument("--feeder", help="only export one feeder id (default: all 11 other feeders)")
    args = ap.parse_args()

    targets = (args.feeder,) if args.feeder else feeder_cad.OTHER_FEEDERS
    t0 = time.time()
    fp = feeder_cad.input_sha256()[:12]
    dxf_paths = {}
    for fid in targets:
        p = feeder_cad.export_one(fid)
        dxf_paths[fid] = p
        print(f"wrote {p.relative_to(ROOT)} (fingerprint {fp})")

    if args.dxf_only:
        print(f"done ({len(targets)} DXFs in {time.time() - t0:.1f} s)")
        return

    import importlib.util
    spec = importlib.util.spec_from_file_location("autocad_export", ROOT / "scripts" / "autocad_export.py")
    assert spec and spec.loader
    ax = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ax)

    exe = ax.accoreconsole()
    print(f"AutoCAD: {exe}")
    (ROOT / "exports").mkdir(parents=True, exist_ok=True)
    for fid in targets:
        dxf = dxf_paths[fid]
        dwg = ROOT / "cad" / f"oneline_{fid}.dwg"
        pdf = ROOT / "exports" / f"oneline_{fid}.pdf"
        t_one = time.time()
        ax.run(
            exe,
            dxf,
            [
                f'(command "_.SAVEAS" "2018" "{ax.lisp_path(dwg)}")',
                ax.plot("DWG To PDF.pc3", "ISO full bleed A3 (420.00 x 297.00 MM)", pdf, raster=False),
            ],
            readonly=False,
        )
        for p in (dwg, pdf):
            if not p.exists() or p.stat().st_mtime < t_one - 1:
                sys.exit(f"{p.relative_to(ROOT)} was not written by AutoCAD")
        print(f"  {fid:12s} -> {dwg.relative_to(ROOT)} ({dwg.stat().st_size / 1e3:.0f} kB), "
              f"{pdf.relative_to(ROOT)} ({pdf.stat().st_size / 1e3:.0f} kB)")
        if args.register:
            aid = feeder_cad.asset_id(fid)
            assets.register(aid)
            print(f"    registered {aid}")

    print(f"done ({len(targets)} feeders in {time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
