"""Local sanity check (no training): filter matches LTspice, a few events, feature shapes, example figure."""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hif.features import FEATURES, window_features, window_labels  # noqa: E402
from hif.frontend import FS_ADC, N_CYCLE, cutoff_hz  # noqa: E402
from hif.waveforms import DISTURBANCES, SURFACES, make_event  # noqa: E402

lt = json.loads((ROOT / "circuit" / "ltspice_results.json").read_text())["ac"]["f_minus3dB_Hz"]
print(f"filter -3 dB: python {cutoff_hz():.1f} Hz vs LTspice {lt:.1f} Hz")

rng = np.random.default_rng(1)
cases = [("hif", s) for s in SURFACES] + [("normal", d) for d in DISTURBANCES]
fig, axes = plt.subplots(len(cases), 1, figsize=(10, 1.6 * len(cases)), sharex=True)
t = np.arange(60 * N_CYCLE) / FS_ADC * 1000
for ax, (kind, name) in zip(axes, cases):
    if kind == "hif":
        amps, meta = make_event(rng, True, surface=name, disturbance="none")
    else:
        amps, meta = make_event(rng, False, disturbance=name)
    X, ends = window_features(amps)
    y = window_labels(ends, meta)
    assert X.shape == (53, len(FEATURES)) and np.isfinite(X).all(), (name, X.shape)
    print(f"{kind:6s} {name:15s} base {meta['base_rms']:5.1f} A  arc {meta['arc_rms']:5.2f} A  "
          f"windows {len(y)} (hif {int((y == 1).sum())}, skip {int((y == -1).sum())})")
    ax.plot(t, amps, lw=0.6)
    ax.axvline(meta["start_cycle"] * 1000 / 60, color="r", lw=0.8)
    ax.set_ylabel(name, rotation=0, ha="right", fontsize=8)
axes[-1].set_xlabel("time (ms), red line = event start")
fig.tight_layout()
out = ROOT / "results" / "figures"
out.mkdir(parents=True, exist_ok=True)
fig.savefig(out / "example_waveforms.png", dpi=110)
print("saved", out / "example_waveforms.png")
