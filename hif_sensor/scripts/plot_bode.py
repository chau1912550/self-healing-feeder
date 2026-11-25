"""Bode plot of the LTspice AC run (exported to SQLite) vs the Python front-end model."""
import sqlite3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hif.frontend import GAIN_V_PER_A, analog_den  # noqa: E402

rows = sqlite3.connect(sys.argv[1]).execute(
    'SELECT frequency, "V(adc)|mag_db20", "V(adc)|phase_deg" FROM samples ORDER BY point').fetchall()
f, db, ph = map(np.array, zip(*rows))
db_rel = db - 20 * np.log10(GAIN_V_PER_A)
_, h = signal.freqs([1.0], analog_den(), worN=2 * np.pi * f)
fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
a1.semilogx(f, db_rel, label="LTspice (op-amp model, clamps)")
a1.semilogx(f, 20 * np.log10(np.abs(h)), "--", label="Python model (ideal op-amp)")
for x, txt in ((2045, "-3 dB at 2.05 kHz"), (7680, "Nyquist 7.68 kHz: -46 dB")):
    a1.axvline(x, color="gray", lw=0.7)
    a1.text(x * 1.05, -15 if x < 5000 else -60, txt, fontsize=8)
a1.set_ylim(-100, 5)
a1.set_ylabel("gain vs 60 Hz (dB)")
a1.legend(fontsize=8)
a2.semilogx(f, ph)
a2.set_ylabel("phase (deg)")
a2.set_xlabel("frequency (Hz)")
a1.set_title("HIF sensor front end: 4th-order Butterworth anti-alias filter")
fig.tight_layout()
fig.savefig(ROOT / "results" / "figures" / "front_end_bode.png", dpi=120)
print("max |LTspice - python| below 5 kHz (dB):",
      round(float(np.max(np.abs(db_rel - 20 * np.log10(np.abs(h)))[f < 5000])), 3))
