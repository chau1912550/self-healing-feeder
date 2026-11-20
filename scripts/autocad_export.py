"""Drive AutoCAD from the command line: DXF -> DWG -> A3 PDF + PNG, with no clicking.

Uses accoreconsole.exe, the command-line AutoCAD engine installed with AutoCAD (Windows only).
It runs in the background and does not touch an AutoCAD window you have open.

    .venv\\Scripts\\python scripts\\export_oneline_dxf.py           # results/ -> cad/feeder_oneline.dxf
    .venv\\Scripts\\python scripts\\autocad_export.py --register    # -> .dwg, exports/*.pdf, *.png, registered

Steps (each an AutoLISP script, so names with spaces stay intact):
  1. open cad/feeder_oneline.dxf, SAVEAS cad/feeder_oneline.dwg (AutoCAD 2018 format)
  2. plot layout "A3 ONE-LINE" with DWG To PDF.pc3, ISO full bleed A3, 1:1, with lineweights
  3. plot the same layout with PublishToWeb PNG.pc3, QHD 2560 x 1440 px, fit to extents, centred
Set SHF_ACCORECONSOLE to the exe if AutoCAD is installed somewhere else.
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shf import assets  # noqa: E402

DXF = ROOT / "cad" / "feeder_oneline.dxf"
DWG = ROOT / "cad" / "feeder_oneline.dwg"
PDF = ROOT / "exports" / "feeder_oneline.pdf"
PNG = ROOT / "exports" / "feeder_oneline.png"
LAYOUT = "A3 ONE-LINE"


def accoreconsole() -> Path:
    if os.environ.get("SHF_ACCORECONSOLE"):
        return Path(os.environ["SHF_ACCORECONSOLE"])
    found = sorted(glob.glob(r"C:\Program Files\Autodesk\AutoCAD *\accoreconsole.exe"))
    if not found:
        sys.exit("accoreconsole.exe not found: install AutoCAD or set SHF_ACCORECONSOLE")
    return Path(found[-1])   # newest version


def lisp_path(p: Path) -> str:
    return str(p).replace("\\", "/")


def plot(device: str, paper: str, out: Path, raster: bool) -> str:
    """One -PLOT call. Vector: whole layout at 1:1 in mm. Raster: fit the extents, centred."""
    if raster:
        middle = ['"_E"', '"_Fit"', '"_C"']
        units = []
    else:
        middle = ['"_L"', '"1:1"', '"0,0"']
        units = ['"_M"']
    args = (['"_.-PLOT"', '"_Y"', f'"{LAYOUT}"', f'"{device}"', f'"{paper}"', *units, '"_L"', '"_N"', *middle,
             '"_Y"', '"."', '"_Y"', '"_N"', '"_N"', '"_N"', f'"{lisp_path(out)}"', '"_N"', '"_Y"'])
    return f"(command {' '.join(args)})"


def run(exe: Path, drawing: Path, lines: list[str], readonly: bool) -> str:
    head = ['(setvar "FILEDIA" 0)', '(setvar "CMDDIA" 0)', '(setvar "EXPERT" 5)']
    with tempfile.TemporaryDirectory() as tmp:
        scr = Path(tmp) / "step.scr"
        scr.write_text("\n".join(head + lines + ['(princ "\\nSHF-DONE\\n")', ""]), encoding="utf-8")
        cmd = [str(exe), "/i", str(drawing), "/s", str(scr), "/l", "en-US"] + (["/readonly"] if readonly else [])
        out = subprocess.run(cmd, capture_output=True, timeout=300).stdout
    text = out.decode("utf-16-le", errors="ignore") if out.count(b"\x00") > len(out) // 4 else out.decode("utf-8", "ignore")
    if "SHF-DONE" not in text:
        sys.exit("AutoCAD did not finish the script:\n" + text[-2000:])
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", action="store_true", help="record the fresh exports in exports/registered.json")
    args = ap.parse_args()
    if not DXF.exists():
        sys.exit(f"{DXF} missing: python scripts/export_oneline_dxf.py")
    exe = accoreconsole()
    PDF.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    print(f"AutoCAD: {exe}")
    run(exe, DXF, [f'(command "_.SAVEAS" "2018" "{lisp_path(DWG)}")',
                   plot("DWG To PDF.pc3", "ISO full bleed A3 (420.00 x 297.00 MM)", PDF, raster=False)], readonly=False)
    run(exe, DWG, [plot("PublishToWeb PNG.pc3", "QHD (2560.00 x 1440.00 Pixels)", PNG, raster=True)], readonly=True)
    for p in (DWG, PDF, PNG):
        if not p.exists() or p.stat().st_mtime < start - 1:
            sys.exit(f"{p.relative_to(ROOT)} was not written by this run")
        print(f"  wrote {p.relative_to(ROOT)} ({p.stat().st_size / 1e3:.0f} kB)")
    if args.register:
        for asset_id in ("oneline-pdf", "oneline-png"):
            assets.register(asset_id)
            print(f"  registered {asset_id}")
    print(f"done in {time.time() - start:.0f} s")


if __name__ == "__main__":
    main()
