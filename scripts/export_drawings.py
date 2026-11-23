"""Technical drawings of the six SolidWorks parts: DXF from the part geometry, then AutoCAD.

    .venv\\Scripts\\python scripts\\export_drawings.py --register        # all six
    .venv\\Scripts\\python scripts\\export_drawings.py --part recloser   # one
    .venv\\Scripts\\python scripts\\export_drawings.py --dxf-only        # no AutoCAD: DXF only

Writes cad/drawing_<part>.dxf (shf/mechdraw.py), then AutoCAD's command-line engine
(accoreconsole) saves cad/drawing_<part>.dwg and plots layout "A3 DRAWING" to
exports/drawing_<part>.pdf (A3, 1:1 in paper mm) and .png.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from shf import assets, mech, mechdraw  # noqa: E402
from autocad_export import accoreconsole, lisp_path, run  # noqa: E402

LAYOUT = "A3 DRAWING"


def plot(device: str, paper: str, out: Path, raster: bool) -> str:
    middle = ['"_E"', '"_Fit"', '"_C"'] if raster else ['"_L"', '"1:1"', '"0,0"']
    units = [] if raster else ['"_M"']
    args = (['"_.-PLOT"', '"_Y"', f'"{LAYOUT}"', f'"{device}"', f'"{paper}"', *units, '"_L"', '"_N"', *middle,
             '"_Y"', '"."', '"_Y"', '"_N"', '"_N"', '"_N"', f'"{lisp_path(out)}"', '"_N"', '"_Y"'])
    return f"(command {' '.join(args)})"


def outputs(name: str) -> dict[str, Path]:
    return {"dxf": mechdraw.path(name), "dwg": ROOT / "cad" / f"drawing_{name}.dwg",
            "pdf": ROOT / "exports" / f"drawing_{name}.pdf", "png": ROOT / "exports" / f"drawing_{name}.png"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="all", choices=["all", *mech.PARTS])
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--dxf-only", action="store_true")
    args = ap.parse_args()
    names = list(mech.PARTS)
    todo = names if args.part == "all" else [args.part]
    exe = None if args.dxf_only else accoreconsole()
    for name in todo:
        start = time.time()
        o = outputs(name)
        mechdraw.export(name, names.index(name) + 1, len(names))
        print(f"{name}: wrote {o['dxf'].relative_to(ROOT)}")
        if exe is None:
            continue
        run(exe, o["dxf"], [f'(command "_.SAVEAS" "2018" "{lisp_path(o["dwg"])}")',
                            plot("DWG To PDF.pc3", "ISO full bleed A3 (420.00 x 297.00 MM)", o["pdf"], False)],
            readonly=False)
        run(exe, o["dwg"], [plot("PublishToWeb PNG.pc3", "QHD (2560.00 x 1440.00 Pixels)", o["png"], True)],
            readonly=True)
        for k in ("dwg", "pdf", "png"):
            p = o[k]
            if not p.exists() or p.stat().st_mtime < start - 1:
                sys.exit(f"{p.relative_to(ROOT)} was not written by this run")
            print(f"  wrote {p.relative_to(ROOT)} ({p.stat().st_size / 1e3:.0f} kB)")
        if args.register:
            for k in ("pdf", "png"):
                assets.register(f"drawing-{name.replace('_', '-')}-{k}")
            print("  registered")


if __name__ == "__main__":
    main()
