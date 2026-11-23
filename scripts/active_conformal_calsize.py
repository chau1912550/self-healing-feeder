"""How many buses of a new feeder does conformal recalibration need? (research/active-grid-gnn/PLAN.md, Addendum B1)

Uses the probabilities saved by scripts/active_grid_run.py (frozen IEEE 123-bus models applied zero-shot to the
active IEEE 34-bus feeder). Randomized APS at a 95% target, recalibrated on a growing share of 34-bus fault buses
(and the same share of its NO_FAULT events), 50 random draws per share, tested on everything else.

    .venv\\Scripts\\python scripts\\active_conformal_calsize.py      # a few seconds, no retraining

Writes results/active_grid/conformal_calsize.json with a run record. Simulation only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shf import active_grid as ag, active_models as am, provenance  # noqa: E402

FRACTIONS = (0.05, 0.10, 0.20, 0.30, 0.40)
N_DRAWS = 50
ALPHA = 0.05
METHOD = "aps_rand"
U_SEED = 12345            # same uniform draws as scripts/active_conformal_posthoc.py (salt 1 = 34-bus)
CRIT_MEAN, CRIT_P10 = 0.945, 0.920


def main() -> None:
    src = ag.transfer.OUT_DIR / "active_probs.npz"
    if not src.exists():
        raise SystemExit(f"{src} not found: it comes from scripts/active_grid_run.py (Kaggle output).")
    d = np.load(src, allow_pickle=False)
    y, bus, nf = d["y34"], d["bus34"], int(d["nofault34"])
    u = np.random.default_rng(U_SEED + 1).uniform(0.0, 1.0, size=len(y))
    fault_buses = np.array(sorted(np.unique(bus[y < nf])))
    nf_idx = np.flatnonzero(y == nf)

    out = {"simulation_only": True, "plan": "research/active-grid-gnn/PLAN.md, Addendum B1 (written before this run)",
           "score": METHOD, "target": 1 - ALPHA, "draws": N_DRAWS, "fault_buses_34": int(len(fault_buses)),
           "nofault_events_34": int(len(nf_idx)),
           "criterion": {"mean_coverage_at_least": CRIT_MEAN, "p10_coverage_at_least": CRIT_P10}, "models": {}}
    for mkey, pkey in (("active_gatv2", "gat34_zs"), ("per_node_gbdt", "gbdt34_zs")):
        probs = d[pkey]
        rows, first_ok = [], None
        for frac in FRACTIONS:
            n_b = max(1, int(round(frac * len(fault_buses))))
            n_nf = max(10, int(round(frac * len(nf_idx))))
            rng = np.random.default_rng(0)
            reps = []
            for _ in range(N_DRAWS):
                cb = set(rng.choice(fault_buses, size=n_b, replace=False).tolist())
                cnf = set(rng.choice(nf_idx, size=n_nf, replace=False).tolist())
                cal = np.array([(b in cb) or (i in cnf) for i, b in enumerate(bus)])
                te = ~cal
                q = am.conformal_quantile(am.conformal_scores(probs[cal], y[cal], METHOD, u[cal]), ALPHA)
                reps.append(am.conformal_report(probs[te], y[te], am.conformal_sets(probs[te], q, METHOD, u[te]), nf))
            cov = np.array([r["coverage"] for r in reps])

            def mean(k: str) -> float | None:
                v = [r[k] for r in reps if r[k] is not None]
                return round(float(np.mean(v)), 4) if v else None
            row = {"fraction": frac, "cal_fault_buses": n_b, "cal_nofault_events": n_nf,
                   "coverage_mean": round(float(cov.mean()), 4),
                   "coverage_p10": round(float(np.percentile(cov, 10)), 4),
                   "coverage_min": round(float(cov.min()), 4),
                   "avg_set_size": mean("avg_set_size"), "singleton_share": mean("singleton_share"),
                   "singleton_accuracy": mean("singleton_accuracy"),
                   "nofault_autonomous_trip_share": mean("nofault_autonomous_trip_share")}
            row["meets_criterion"] = bool(row["coverage_mean"] >= CRIT_MEAN and row["coverage_p10"] >= CRIT_P10)
            if row["meets_criterion"] and first_ok is None:
                first_ok = frac
            rows.append(row)
            print(f"{mkey:14s} {frac:.0%} ({n_b} buses): cov mean {row['coverage_mean']:.4f} p10 {row['coverage_p10']:.4f} "
                  f"min {row['coverage_min']:.4f} size {row['avg_set_size']} single {row['singleton_share']} "
                  f"acc {row['singleton_accuracy']} trip {row['nofault_autonomous_trip_share']} ok={row['meets_criterion']}")
        out["models"][mkey] = {"by_fraction": rows, "smallest_fraction_meeting_criterion": first_ok}

    path = ag.ACTIVE_SUMMARY_DIR / "conformal_calsize.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    provenance.record("active_conformal_calsize", [path])


if __name__ == "__main__":
    main()
