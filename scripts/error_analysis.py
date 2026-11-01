"""Error analysis for the ML fault-zone classifier: where it fails and why.

    python scripts/error_analysis.py      # needs data/generated/dataset.csv.gz (run `python run.py` first)

Replays the same grouped cross-validation as run.py (same folds, seed and
sensor dropout, so the out-of-fold accuracy matches results/metrics.json) and
also keeps the class probabilities. Writes results/error_analysis/:

- per_zone_ml.csv, per_zone_fpi.csv: one-vs-rest recall, FNR, precision, FPR per zone
- confusion_ml.csv: true zone (rows) vs predicted zone (columns)
- ml_errors.csv: every misclassified fault with its type, resistance and loading
- error_analysis.json: error types, error direction in the zone tree, and the
  accuracy/coverage trade-off when low-confidence predictions are deferred

then rebuilds the report page docs/index.html.
"""
from __future__ import annotations

import json
import re
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run from anywhere

from shf import config, dashboard, model  # noqa: E402
from shf.faults import DEVICES  # noqa: E402

OUT = config.RESULTS / "error_analysis"
THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95)


def load():
    df = pd.read_csv(config.GENERATED / "dataset.csv.gz")
    df = df[df["converged"]].reset_index(drop=True)
    df["bus"] = df["bus"].astype(str)
    zt = pd.read_csv(config.RESULTS / "zones.csv")
    parent = {z: (p if isinstance(p, str) else None) for z, p in zip(zt.zone, zt.parent_zone)}
    return df, list(zt.zone), parent


def ancestors(parent: dict, z: str) -> list[str]:
    out = []
    while parent[z]:
        z = parent[z]
        out.append(z)
    return out


def relation(parent: dict, true: str, pred: str) -> str:
    """Where the predicted zone sits relative to the true zone in the zone tree."""
    if pred == "none":
        return "no detection"
    if pred == true:
        return "correct"
    if parent[true] == pred:
        return "predicted parent (1 zone upstream)"
    if parent[pred] == true:
        return "predicted child (1 zone downstream)"
    if pred in ancestors(parent, true):
        return "further upstream"
    if true in ancestors(parent, pred):
        return "further downstream"
    if parent[pred] == parent[true]:
        return "sibling (same parent)"
    return "unrelated branch"


def oof_predictions(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Out-of-fold predicted zone and its probability, mirroring model.cross_validate."""
    cols = model.feature_columns(df, "full")
    X = df[cols].to_numpy(dtype=float)
    y = df["zone"].to_numpy()
    rng = np.random.default_rng(0)
    pred = np.empty(len(df), dtype=object)
    conf = np.zeros(len(df))
    for train, test in GroupKFold(n_splits=model.N_FOLDS).split(X, y, df["bus"].to_numpy()):
        m = model.make_model(0).fit(model.sensor_dropout(X[train], cols, rng), y[train])
        proba = m.predict_proba(X[test])
        pred[test] = m.classes_[proba.argmax(1)]
        conf[test] = proba.max(1)
    return pred, conf


def fpi_predictions(df: pd.DataFrame, parent: dict) -> np.ndarray:
    """Conventional FPI (same rule as shf/baseline.py) with the pickups saved in metrics.json."""
    met = json.loads((config.RESULTS / "metrics.json").read_text())
    pick = met["fault_location"]["fpi_baseline"]["pickups_A"]
    pred = np.full(len(df), "none", dtype=object)
    for d in sorted(DEVICES, key=lambda d: len(ancestors(parent, d))):   # deeper devices overwrite
        imax = df[[f"{d}_Ia", f"{d}_Ib", f"{d}_Ic"]].max(axis=1)
        pred[((imax > pick[d][0]) | (3 * df[f"{d}_I0"] > pick[d][1])).to_numpy()] = d
    return pred


def hops_to_boundary(buses) -> dict[str, float]:
    """Line hops from each fault bus to the nearest switching device (zone boundary)."""
    adj: dict[str, set] = {}
    for f in config.FEEDER_MASTER.parent.glob("*.dss"):
        for ln in f.read_text(errors="ignore").splitlines():
            m = re.match(r"\s*New\s+Line\.\S+.*?Bus1=(\S+)\s+Bus2=(\S+)", ln, re.I)
            if m:
                a, b = (s.split(".")[0].lower() for s in m.groups())
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
    for b in list(adj):   # regulator / transformer secondaries (9r, 61s, ...) join their primary bus
        if b[-1] in "rs" and b[:-1] in adj:
            adj[b].add(b[:-1])
            adj[b[:-1]].add(b)
    bound = set()
    for desc in config.SECTIONALIZERS.values():
        m = re.search(r"(\w+)-(\w+)$", desc.rstrip(")"))
        bound |= {m.group(1).lower(), m.group(2).lower()}

    def bfs(src: str) -> float:
        seen, q = {src: 0}, deque([src])
        while q:
            u = q.popleft()
            if u in bound:
                return seen[u]
            for v in adj.get(u, ()):
                if v not in seen:
                    seen[v] = seen[u] + 1
                    q.append(v)
        return np.nan

    return {b: bfs(b.lower()) for b in buses}


def per_zone(y: np.ndarray, pred: np.ndarray, zones: list[str]) -> pd.DataFrame:
    rows = []
    for z in zones:
        t, p = y == z, pred == z
        tp, fn, fp, tn = (int(v.sum()) for v in (t & p, t & ~p, ~t & p, ~t & ~p))
        rows.append({"zone": z, "n": int(t.sum()), "recall": tp / (tp + fn), "FNR": fn / (tp + fn),
                     "precision": tp / (tp + fp) if tp + fp else np.nan, "FPR": fp / (fp + tn),
                     "FN": fn, "FP": fp})
    return pd.DataFrame(rows).round(4)


def main() -> None:
    df, zones, parent = load()
    y = df["zone"].to_numpy()
    pred, conf = oof_predictions(df)
    fpi = fpi_predictions(df, parent)
    wrong = pred != y
    hops = df["bus"].map(hops_to_boundary(df["bus"].unique()))

    errors = df.loc[wrong, ["bus", "zone", "ftype", "phases", "r", "scenario", "load_mult"]].copy()
    errors["pred"] = pred[wrong]
    errors["confidence"] = conf[wrong].round(4)
    errors["relation"] = [relation(parent, t, p) for t, p in zip(errors.zone, errors.pred)]
    fpi_rel = pd.Series([relation(parent, t, p) for t, p in zip(y[fpi != y], fpi[fpi != y])])
    slg = (df.ftype == "SLG").to_numpy()
    err = pd.Series(wrong)

    res = {
        "faults": len(df),
        "ml_accuracy": round(float((~wrong).mean()), 4),
        "ml_errors": int(wrong.sum()),
        "ml_error_rate_by_type": err.groupby(df.ftype).mean().round(4).to_dict(),
        "ml_slg_error_rate_by_resistance": err[slg].groupby(df.r[slg]).mean().round(4).to_dict(),
        "ml_errors_slg_200_ohm_or_more": int(((errors.ftype == "SLG") & (errors.r >= 200)).sum()),
        "ml_error_rate_by_load_tercile": err.groupby(pd.qcut(df.load_mult, 3, labels=["low", "mid", "high"]),
                                                     observed=True).mean().round(4).to_dict(),
        "ml_error_rate_by_hops_to_boundary": err.groupby(hops.clip(upper=4)).mean().round(4).to_dict(),
        "ml_error_direction": errors.relation.value_counts().to_dict(),
        "ml_top_confusions": {f"{t} -> {p}": int(n) for (t, p), n in
                              errors.groupby(["zone", "pred"]).size().nlargest(8).items()},
        "ml_median_confidence": {"correct": round(float(np.median(conf[~wrong])), 4),
                                 "wrong": round(float(np.median(conf[wrong])), 4)},
        "defer_low_confidence": [
            {"threshold": th, "coverage": round(float((conf >= th).mean()), 4),
             "accuracy_on_kept": round(float((~wrong[conf >= th]).mean()), 4),
             "errors_kept": int(wrong[conf >= th].sum())} for th in THRESHOLDS],
        "fpi_no_detection_share": round(float((fpi == "none").mean()), 4),
        "fpi_error_direction": fpi_rel.value_counts().to_dict(),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    per_zone(y, pred, zones).to_csv(OUT / "per_zone_ml.csv", index=False)
    per_zone(y, fpi, zones).to_csv(OUT / "per_zone_fpi.csv", index=False)
    pd.crosstab(pd.Series(y, name="true"), pd.Series(pred, name="pred")).to_csv(OUT / "confusion_ml.csv")
    errors.to_csv(OUT / "ml_errors.csv", index=False)
    (OUT / "error_analysis.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))
    dashboard.build()


if __name__ == "__main__":
    main()
