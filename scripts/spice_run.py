"""Build and run the two LTspice circuits, export their waveforms, summarize them.

    .venv\\Scripts\\python scripts\\spice_run.py [--register]

1. Read the fault bus's Thevenin impedance and pre-fault load from OpenDSS.
2. Write spice/fault_dc_offset.asc and run LTspice in batch mode (no window).
3. Turn the worst-case fault current into the CT secondary current (spice/ct_secondary.pwl),
   write spice/ct_adc_frontend.asc and run it.
4. Export resampled waveforms to exports/spice_*.csv and the numbers to
   results/spice/summary.json; --register records the exports in exports/registered.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shf import assets, config, spice  # noqa: E402


def meas(log: Path) -> dict:
    """`.meas` results from an LTspice log (last value per name; one line per step)."""
    text = log.read_bytes().decode("utf-16-le", errors="ignore") if b"\x00" in log.read_bytes()[:200] \
        else log.read_text(errors="ignore")
    out: dict[str, list[float]] = {}
    for name, val in re.findall(r"^(\w+):\s.*?=\s*([-+0-9.eE]+)", text, re.M):   # single run: "name: MAX(..)=v"
        out.setdefault(name.lower(), []).append(float(val))
    for name, block in re.findall(r"^Measurement: (\w+)\n\s*step\t[^\n]*\n((?:\s+\d+\t[^\n]*\n?)+)", text, re.M):
        out[name.lower()] = [float(line.split("\t")[1]) for line in block.strip().splitlines()]   # stepped run
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", action="store_true", help="record the fresh exports in exports/registered.json")
    args = ap.parse_args()
    start = time.time()
    config.SPICE_DIR.mkdir(exist_ok=True)
    spice.EXPORTS.mkdir(exist_ok=True)
    spice.SUMMARY.parent.mkdir(parents=True, exist_ok=True)

    print("1) Values from OpenDSS")
    p = spice.fault_params()
    fe = spice.frontend_params(p)
    print(f"   bus {p['bus']}: Rth {p['rth']:.4f} ohm, Xth {p['xth']:.4f} ohm (X/R {p['x_over_r']:.2f}), "
          f"fault {p['i_fault_thevenin']:.0f} A Thevenin / {p['i_fault_opendss']:.0f} A OpenDSS")

    print("2) Fault current with and without DC offset")
    spice.FAULT_ASC.write_bytes(spice.fault_asc(p))
    _, steps = spice.read_raw(spice.run(spice.FAULT_ASC))
    m = meas(spice.FAULT_ASC.with_suffix(".log"))
    if len(steps) != 2 or "irms_fault" not in m:
        sys.exit(f"unexpected LTspice output: {len(steps)} steps, measurements {sorted(m)}")
    i_ss = m["irms_fault"][-1]
    grid = np.arange(0, spice.T_END + spice.GRID_S / 2, spice.GRID_S)
    a = [spice.resample(st, grid, ["I(Lth)", "V(f)"]) for st in steps]
    np.savetxt(spice.EXPORTS / "spice_fault_current.csv",
               np.column_stack([grid * 1000, a[0]["I(Lth)"], a[1]["I(Lth)"], a[0]["V(f)"], a[1]["V(f)"]]),
               delimiter=",", fmt="%.6g", comments="",
               header="time_ms,i_no_offset_a,i_max_offset_a,v_f_no_offset_v,v_f_max_offset_v")

    print("3) CT and ADC front end")
    worst = steps[1]
    # the CT input on the same 20 us grid as the exports: small enough to keep in git, and far
    # finer than the 60 Hz signal and the 480 Hz filter need
    np.savetxt(spice.PWL, np.column_stack([grid, a[1]["I(Lth)"] / fe["ct_ratio"]]), fmt="%.7g")
    spice.CT_ASC.write_bytes(spice.ct_asc(fe))
    _, ct_steps = spice.read_raw(spice.run(spice.CT_ASC))
    ct = ct_steps[0]
    c = spice.resample(ct, grid, ["V(cs)", "V(adc)"])
    np.savetxt(spice.EXPORTS / "spice_ct_adc.csv",
               np.column_stack([grid * 1000, np.interp(grid, worst["time"], worst["I(Lth)"]) / fe["ct_ratio"],
                                c["V(cs)"], c["V(adc)"]]),
               delimiter=",", fmt="%.6g", comments="", header="time_ms,i_secondary_a,v_burden_v,v_adc_v")

    print("4) Arcing high-impedance fault vs fixed resistance")
    h = spice.hif_params(p)
    spice.HIF_ASC.write_bytes(spice.hif_asc(h))
    _, hif_steps = spice.read_raw(spice.run(spice.HIF_ASC))
    mh = meas(spice.HIF_ASC.with_suffix(".log"))
    if len(hif_steps) != len(h["cases"]) or not {"irms_arc", "irms_lin"} <= set(mh):
        sys.exit(f"unexpected LTspice output: {len(hif_steps)} steps, measurements {sorted(mh)}")
    hgrid = np.arange(0, spice.HIF_T_END + spice.GRID_S / 2, spice.GRID_S)
    cols, head = [hgrid * 1000], ["time_ms"]
    for c, st in zip(h["cases"], hif_steps):
        cols += [np.interp(hgrid, st["time"], -st["I(Larc)"]), np.interp(hgrid, st["time"], -st["I(Llin)"])]
        head += [f"i_arc_{c['r_fault']:g}ohm_a", f"i_fixed_{c['r_fault']:g}ohm_a"]
    np.savetxt(spice.EXPORTS / "spice_hif.csv", np.column_stack(cols), delimiter=",", fmt="%.6g",
               comments="", header=",".join(head))

    print("5) Summary")
    summary = spice.summarize(p, fe, {"Irms_fault": i_ss}, steps, ct)
    summary["hif"] = spice.summarize_hif(h, p, fe, hif_steps, mh)
    summary["runtime_s"] = round(time.time() - start, 1)
    spice.SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    fr, fp, f = summary["fault_rms_a"], summary["first_peak"], summary["frontend"]
    print(f"   steady fault {fr['ltspice_steady']:.0f} A RMS (Thevenin {fr['thevenin']:.0f}, OpenDSS {fr['opendss_3ph_sw1']:.0f})")
    print(f"   first peak {fp['no_offset']['peak_a']:.0f} A without offset, {fp['max_offset']['peak_a']:.0f} A with "
          f"(asymmetry {fp['max_offset']['asymmetry']:.2f}; tau {summary['model']['tau_ms']:.1f} ms)")
    print(f"   ADC {f['vadc_min']:.2f}..{f['vadc_max']:.2f} V, {f['clipped_samples']} clipped samples, "
          f"{f['primary_amps_per_count']:.1f} A per count, DFT within 5% after {f['dft_settle_ms_within_5pct']} ms")
    for key, c in summary["hif"]["cases"].items():
        print(f"   HIF {key} ohm: {c['irms_arc']:.2f} A RMS arc / {c['irms_linear']:.2f} A fixed; 60 Hz part "
              f"{c['i1_arc_vs_linear']:.3f} of fixed; 3rd {c['h3_arc_pct']:.1f}%, DC {c['dc_arc_a']:.3f} A; "
              f"ADC span {c['adc_counts_span_arc']} counts, DFT error {c['dft_error_arc_pct']:+.1f}%")
    if args.register:
        for asset_id in ("spice-fault", "spice-ct", "spice-hif"):
            assets.register(asset_id)
            print(f"   registered {asset_id}")
    print(f"done in {time.time() - start:.0f} s")


if __name__ == "__main__":
    main()
