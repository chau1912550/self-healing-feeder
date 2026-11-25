"""16 window features computed from the last K cycles of ADC samples (cheap enough for an MCU)."""
import numpy as np

from .frontend import N_CYCLE

K = 8
FEATURES = ["log_I1", "log_I3", "h2_ratio", "h3_ratio", "h5_ratio", "even_ratio", "dc_ratio",
            "peak_asym", "I3_cv", "I1_cv", "ph3_jitter", "cycle_diff", "even_std", "h3_trend",
            "I1_trend", "interharm"]
EPS = 1e-6


def window_features(amps):
    """amps: 1-D samples, whole cycles. Returns (X [n_windows, 16], end_cycle [n_windows])."""
    c = amps.reshape(-1, N_CYCLE)
    X = np.fft.rfft(c, axis=1) / (N_CYCLE / 2)
    X[:, 0] /= 2
    mag = np.abs(X)
    I1 = mag[:, 1] + EPS
    I3 = mag[:, 3] + EPS
    even = mag[:, 2] + mag[:, 4] + mag[:, 6]
    asym = (c.max(1) + c.min(1)) / (c.max(1) - c.min(1) + EPS)
    ph31 = np.exp(1j * (np.angle(X[:, 3]) - 3 * np.angle(X[:, 1])))
    energy = (c ** 2).sum(1) + EPS
    cdiff = np.zeros(len(c))
    cdiff[1:] = ((c[1:] - c[:-1]) ** 2).sum(1) / energy[1:]
    rows, ends = [], []
    h = K // 2
    for j in range(K - 1, len(c)):
        s = slice(j - K + 1, j + 1)
        i1, i3 = I1[s], I3[s]
        R = min(max(abs(ph31[s].mean()), EPS), 1.0)
        P = np.abs(np.fft.rfft(c[j - 3:j + 1].ravel())) ** 2
        rows.append([
            np.log10(i1.mean()), np.log10(i3.mean()),
            (mag[s, 2] / i1).mean(), (i3 / i1).mean(), (mag[s, 5] / i1).mean(),
            (even[s] / i1).mean(), (mag[s, 0] / i1).mean(), asym[s].mean(),
            i3.std() / i3.mean(), i1.std() / i1.mean(), np.sqrt(-2 * np.log(R)),
            cdiff[s].mean(), (even[s] / i1).std(),
            (i3[h:] / i1[h:]).mean() - (i3[:h] / i1[:h]).mean(),
            np.log10(i1[h:].mean() / i1[:h].mean()),
            1 - P[::4].sum() / (P.sum() + EPS),
        ])
        ends.append(j)
    return np.asarray(rows, np.float32), np.asarray(ends, np.int16)


def window_labels(ends, meta):
    """1 = at least K/2 arcing cycles in the window, 0 = no arc yet / normal, -1 = ambiguous (skipped)."""
    if not meta["is_hif"]:
        return np.zeros(len(ends), np.int8)
    s = meta["start_cycle"]
    y = np.full(len(ends), -1, np.int8)
    y[ends < s] = 0
    y[ends - s + 1 >= K // 2] = 1
    return y
