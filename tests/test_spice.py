"""LTspice circuits: the generated schematics are wired as drawn, the .raw reader works,
and the results agree with the study (no LTspice or OpenDSS needed to run these)."""
import json
import math
import struct

import numpy as np
import pytest

from shf import config, spice

# pin offsets (local, R0) for the symbols the generator uses, from LTspice's symbol table
PINS = {"res": [(16, 16), (16, 96)], "ind": [(16, 16), (16, 96)], "voltage": [(0, 16), (0, 96)],
        "bv": [(0, 16), (0, 96)], "current": [(0, 0), (0, 80)], "cap": [(16, 0), (16, 64)],
        "diode": [(16, 0), (16, 64)]}
ROT = {"R0": lambda x, y: (x, y), "R90": lambda x, y: (-y, x), "R180": lambda x, y: (-x, -y),
       "R270": lambda x, y: (y, -x)}

P = {"bus": "60", "vpk": 3396.6, "rth": 0.184, "lth": 9.05e-4, "rload": 4.39, "lload": 4.22e-3, "rf": 0.01,
     "alpha_no_offset": 61.65, "alpha_max_offset": 151.65}
FE = {"ct_ratio": 1000, "rb": 0.14, "rf": 1000.0, "cf": 330e-9, "bias": 1.65, "vref": 3.3}
H = {"bus": "60", "vpk": 3396.6, "rs": 0.3, "ls": 1.5e-3, "vp": 1019.0, "vn": 1121.0,
     "cases": [{"r_fault": 100.0, "r_arc": 70.0}, {"r_fault": 400.0, "r_arc": 280.0}]}


def _parse(asc: bytes):
    wires, flags, pins, parts = [], [], [], []
    for line in asc.decode("ascii").splitlines():
        f = line.split()
        if f[:1] == ["WIRE"]:
            wires.append(tuple(map(int, f[1:5])))
        elif f[:1] == ["FLAG"]:
            flags.append((int(f[1]), int(f[2])))
        elif f[:1] == ["SYMBOL"]:
            sx, sy, rot = int(f[2]), int(f[3]), f[4]
            mine = [(sx + ROT[rot](px, py)[0], sy + ROT[rot](px, py)[1]) for px, py in PINS[f[1]]]
            pins += mine
            parts.append(set(mine))
    return wires, flags, pins, parts


def _on(pt, w):
    x, y = pt
    x1, y1, x2, y2 = w
    return (x1 == x2 == x and min(y1, y2) <= y <= max(y1, y2)) or (y1 == y2 == y and min(x1, x2) <= x <= max(x1, x2))


@pytest.mark.parametrize("asc", [spice.fault_asc(P), spice.ct_asc(FE), spice.hif_asc(H)], ids=["fault", "ct", "hif"])
def test_schematic_is_wired_as_drawn(asc):
    wires, flags, pins, parts = _parse(asc)
    assert all(w[0] == w[2] or w[1] == w[3] for w in wires), "diagonal wire"
    ends = {(w[0], w[1]) for w in wires} | {(w[2], w[3]) for w in wires}
    for pin in pins:                       # every pin is met by a wire end: nothing left floating
        assert pin in ends, f"pin {pin} not wired"
    for fl in flags:                       # every label sits on a wire
        assert any(_on(fl, w) for w in wires), f"flag {fl} off any wire"
    for w in wires:                        # no wire spans both pins of one part (silent short)
        assert not any({(w[0], w[1]), (w[2], w[3])} == part for part in parts), w


def test_raw_reader_splits_steps(tmp_path):
    names = ["time", "V(f)", "I(Lth)"]
    head = ("Title: test\nPlotname: Transient Analysis\nFlags: real forward stepped\n"
            f"No. Variables: {len(names)}\nNo. Points: 6\nVariables:\n"
            + "".join(f"\t{i}\t{n}\t{'time' if i == 0 else 'x'}\n" for i, n in enumerate(names)) + "Binary:\n")
    rows = [(0.0, 1, 2), (1e-3, 3, 4), (2e-3, 5, 6), (0.0, 7, 8), (-1e-3, 9, 10), (2e-3, 11, 12)]
    data = b"".join(struct.pack("<dff", *r) for r in rows)
    p = tmp_path / "x.raw"
    p.write_bytes(head.encode("utf-16-le") + data)
    hdr, steps = spice.read_raw(p)
    assert len(steps) == 2 and hdr["No. Points"] == "6"
    assert list(steps[1]["time"]) == [0.0, 1e-3, 2e-3]          # negative-flagged time read as its magnitude
    assert list(steps[1]["I(Lth)"]) == [8, 10, 12]


def test_burden_is_sized_from_the_fault_level():
    fe = spice.frontend_params({"i_fault_thevenin": 6119.0})
    peak_v = 6119.0 * math.sqrt(2) / fe["ct_ratio"] * fe["rb"]
    assert abs(peak_v - config.FRONTEND_HEADROOM_V) < 0.1 * config.FRONTEND_HEADROOM_V
    assert peak_v + fe["bias"] < fe["vref"]


def test_ltspice_results_agree_with_the_study():
    path = config.RESULTS / "spice" / "summary.json"
    if not path.exists():
        pytest.skip("run python scripts/spice_run.py")
    s = json.loads(path.read_text(encoding="utf-8"))
    rms = s["fault_rms_a"]
    assert abs(rms["ltspice_steady"] / rms["thevenin"] - 1) < 0.01        # the circuit is the Thevenin model
    assert abs(rms["ltspice_steady"] / rms["opendss_3ph_sw1"] - 1) < 0.05  # and close to the full OpenDSS fault
    worst, none = s["first_peak"]["max_offset"], s["first_peak"]["no_offset"]
    assert worst["peak_a"] > none["peak_a"] and 1.0 < worst["asymmetry"] < 1.3
    assert s["frontend"]["vadc_max"] <= config.ADC_VREF + 0.5 and s["frontend"]["vadc_min"] >= -0.5
    assert np.isfinite(s["frontend"]["primary_amps_per_count"])


def test_arc_resistance_matches_the_rms_target():
    # with no arc voltage the arc is a plain resistor: R = Vrms / Irms
    assert abs(spice.arc_resistance(1000.0, 0.0, 0.0, 7.0710678) - 100.0) < 0.01
    # a higher arc voltage leaves less of the sine to drive current, so R must drop for the same RMS
    assert spice.arc_resistance(1000.0, 300.0, 330.0, 5.0) < spice.arc_resistance(1000.0, 0.0, 0.0, 5.0)


def test_arc_and_fixed_fault_have_the_same_rms_but_not_the_same_waveform():
    path = config.RESULTS / "spice" / "summary.json"
    if not path.exists():
        pytest.skip("run python scripts/spice_run.py")
    s = json.loads(path.read_text(encoding="utf-8"))
    if "hif" not in s:
        pytest.skip("run python scripts/spice_run.py")
    cases = s["hif"]["cases"]
    assert set(cases) == {f"{r:g}" for r in config.HIF_R_CASES}
    for c in cases.values():
        assert abs(c["irms_arc"] / c["irms_linear"] - 1) < 0.02          # matched as designed
        assert c["i1_arc_vs_linear"] < 1                                 # less of it is 60 Hz
        assert c["h3_arc_pct"] > 5 and c["thd_linear_pct"] < 1          # the arc is rich in harmonics, the resistor is not
        assert (c["dc_arc_a"] < 0) == (config.HIF_VN_FRAC < config.HIF_VP_FRAC) or config.HIF_VN_FRAC == config.HIF_VP_FRAC
