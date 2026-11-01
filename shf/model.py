"""ML fault-zone classifier and its evaluation.

Validation is grouped by fault bus (GroupKFold): the model is always tested on
buses it never saw a fault at during training. A random row split would leak
near-duplicate rows (same bus, different resistance) into the test set and
overstate accuracy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

from .faults import DEVICES

N_FOLDS = 5
DROPOUT_RATE = 0.15   # share of training rows with one sensor blanked out


def feature_columns(df: pd.DataFrame, kind: str = "full") -> list[str]:
    """'full': magnitudes + incremental (pre/post) quantities from each device's
    event record. 'magnitude': only the instantaneous magnitudes a basic SCADA
    poll would return (phase currents, residual current, phase voltages)."""
    cols = []
    for d in DEVICES:
        if kind == "full":
            keys = ["Ia", "Ib", "Ic", "dIa", "dIb", "dIc", "I0", "dI0", "dI2",
                    "Va", "Vb", "Vc", "dVa", "dVb", "dVc"]
        elif kind == "magnitude":
            keys = ["Ia", "Ib", "Ic", "I0", "Va", "Vb", "Vc"]
        else:
            raise ValueError(kind)
        cols += [f"{d}_{k}" for k in keys]
    return cols


def make_model(seed: int = 0) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1,
                                          max_leaf_nodes=31, random_state=seed)


def _device_cols(cols: list[str], device: str) -> list[int]:
    return [i for i, c in enumerate(cols) if c.startswith(device + "_")]


def sensor_dropout(X: np.ndarray, cols: list[str], rng: np.random.Generator,
                   rate: float = DROPOUT_RATE) -> np.ndarray:
    """Augment training data: blank one random device on a share of rows,
    so the model learns to cope with a sensor that stops reporting."""
    X = X.copy()
    rows = np.flatnonzero(rng.random(len(X)) < rate)
    for r in rows:
        X[r, _device_cols(cols, rng.choice(DEVICES))] = np.nan
    return X


def cross_validate(df: pd.DataFrame, kind: str = "full", dropout: bool = True,
                   seed: int = 0) -> dict:
    """Out-of-fold predictions, plus accuracy when each sensor is missing."""
    cols = feature_columns(df, kind)
    X = df[cols].to_numpy(dtype=float)
    y = df["zone"].to_numpy()
    groups = df["bus"].to_numpy()
    rng = np.random.default_rng(seed)
    oof = np.empty(len(df), dtype=object)
    missing_hits = {d: 0 for d in DEVICES}
    for train, test in GroupKFold(n_splits=N_FOLDS).split(X, y, groups):
        Xtr = sensor_dropout(X[train], cols, rng) if dropout else X[train]
        model = make_model(seed).fit(Xtr, y[train])
        oof[test] = model.predict(X[test])
        for d in DEVICES:
            Xm = X[test].copy()
            Xm[:, _device_cols(cols, d)] = np.nan
            missing_hits[d] += int((model.predict(Xm) == y[test]).sum())
    return {
        "pred": oof,
        "accuracy": float((oof == y).mean()),
        "missing_sensor_accuracy": {d: h / len(df) for d, h in missing_hits.items()},
    }


def fit_full(df: pd.DataFrame, kind: str = "full", seed: int = 0):
    cols = feature_columns(df, kind)
    rng = np.random.default_rng(seed)
    X = sensor_dropout(df[cols].to_numpy(dtype=float), cols, rng)
    return make_model(seed).fit(X, df["zone"].to_numpy()), cols


def breakdown(df: pd.DataFrame, pred: np.ndarray, by: str) -> pd.Series:
    return pd.Series(pred == df["zone"].to_numpy(), index=df.index).groupby(df[by]).mean()
