"""Post-hoc conformal analysis (research/active-grid-gnn/PLAN.md, Addendum A).

The pre-registered deterministic APS score saturates at 1.0, so its 95% sets keep almost every label.
This script compares three nonconformity scores on exactly the probabilities and splits the
pre-registered analysis used:

    aps_det   pre-registered deterministic APS (must reproduce results/active_grid/conformal_safety.json)
    lac       least-ambiguous classifier, S = 1 - p_y (Sadinle, Lei & Wasserman 2019)
    aps_rand  randomized APS, S = sum_{p_j > p_y} p_j + U * p_y (Romano, Sesia & Candes 2020)

    python -u scripts/active_conformal_posthoc.py        # after scripts/active_grid_run.py in the same run

Reads data/generated/active_probs.npz (written by active_grid_run.py), writes
results/active_grid/conformal_posthoc.json with a run record. This is a deviation from the
pre-registered plan and is labelled as post-hoc. Simulation only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shf import active_grid as ag, active_models as am, provenance  # noqa: E402

ALPHAS = (0.10, 0.05)
N_RECAL_REPEATS = 10
U_SEED = 12345            # one uniform draw per event for aps_rand, fixed before the run


def _key(alpha: float) -> str:
    return f"target_{int(round(100 * (1 - alpha)))}"


def _u(n: int, salt: int) -> np.ndarray:
    return np.random.default_rng(U_SEED + salt).uniform(0.0, 1.0, size=n)


def _cross_conformal_123(probs: np.ndarray, y: np.ndarray, fold_id: np.ndarray, nf: int,
                         method: str, alpha: float) -> tuple[dict, np.ndarray]:
    """Bus-disjoint cross-conformal on IEEE 123-bus: calibrate on 4 folds, predict sets on the 5th."""
    u = _u(len(y), 0)
    sets = np.zeros_like(probs, dtype=bool)
    q_hats = []
    for f in sorted(set(fold_id.tolist())):
        te = fold_id == f
        tr = ~te
        q = am.conformal_quantile(am.conformal_scores(probs[tr], y[tr], method, u[tr]), alpha)
        q_hats.append(q)
        sets[te] = am.conformal_sets(probs[te], q, method, u[te])
    rep = am.conformal_report(probs, y, sets, nf)
    rep["q_hat_mean"] = round(float(np.mean(q_hats)), 5)
    return rep, sets


def _zero_shot_34(probs123: np.ndarray, y123: np.ndarray, probs34: np.ndarray, y34: np.ndarray, nf34: int,
                  method: str, alpha: float) -> tuple[dict, np.ndarray]:
    """q_hat from all IEEE 123-bus OOF scores applied to IEEE 34-bus. No exchangeability, so no guarantee."""
    q = am.conformal_quantile(am.conformal_scores(probs123, y123, method, _u(len(y123), 0)), alpha)
    sets = am.conformal_sets(probs34, q, method, _u(len(y34), 1))
    rep = am.conformal_report(probs34, y34, sets, nf34)
    rep["q_hat"] = round(float(q), 5)
    return rep, sets


def _recal_34(probs34: np.ndarray, y34: np.ndarray, bus34: np.ndarray, nf34: int,
              method: str, alpha: float, seed: int = 0) -> dict:
    """Recalibrate on 5% of IEEE 34-bus fault buses + 5% of NO_FAULT events (same draws as active_grid_run.py)."""
    fault_buses = np.array(sorted(np.unique(bus34[y34 < nf34])))
    nf_idx = np.flatnonzero(y34 == nf34)
    n_cal_b = max(1, int(round(0.05 * len(fault_buses))))
    n_cal_nf = max(10, int(round(0.05 * len(nf_idx))))
    u = _u(len(y34), 1)
    rng = np.random.default_rng(seed)
    reps = []
    for _ in range(N_RECAL_REPEATS):
        cb = set(rng.choice(fault_buses, size=n_cal_b, replace=False).tolist())
        cnf = set(rng.choice(nf_idx, size=n_cal_nf, replace=False).tolist())
        cal = np.array([(b in cb) or (i in cnf) for i, b in enumerate(bus34)])
        te = ~cal
        q = am.conformal_quantile(am.conformal_scores(probs34[cal], y34[cal], method, u[cal]), alpha)
        r = am.conformal_report(probs34[te], y34[te], am.conformal_sets(probs34[te], q, method, u[te]), nf34)
        r["q_hat"] = q
        reps.append(r)

    def stats(k: str) -> dict:
        v = [r[k] for r in reps if r[k] is not None]
        if not v:
            return {"mean": None, "std": None, "min": None, "max": None}
        return {"mean": round(float(np.mean(v)), 4), "std": round(float(np.std(v)), 4),
                "min": round(float(np.min(v)), 4), "max": round(float(np.max(v)), 4)}

    keys = ("coverage", "coverage_fault", "coverage_nofault", "avg_set_size", "empty_share",
            "singleton_share", "singleton_accuracy", "raw_argmax_accuracy",
            "nofault_autonomous_trip_share", "fault_autonomous_correct_share", "q_hat")
    return {"cal_fault_buses": n_cal_b, "cal_nofault_events": n_cal_nf, "n_repeats": N_RECAL_REPEATS,
            **{k: stats(k) for k in keys}}


def main() -> None:
    src = ag.transfer.OUT_DIR / "active_probs.npz"
    if not src.exists():
        raise SystemExit(f"{src} not found: run scripts/active_grid_run.py first (same run).")
    d = np.load(src, allow_pickle=False)
    y123, fold123, nf123 = d["y123"], d["fold_id123"], int(d["nofault123"])
    y34, bus34, nf34 = d["y34"], d["bus34"], int(d["nofault34"])
    models = {"per_node_gbdt": (d["gbdt123_oof"], d["gbdt34_zs"]),
              "active_gatv2": (d["gat123_oof"], d["gat34_zs"])}

    out: dict = {
        "phase": "active_conformal_posthoc",
        "simulation_only": True,
        "post_hoc": True,
        "plan": "research/active-grid-gnn/PLAN.md, Addendum A (written before this run)",
        "methods": {
            "aps_det": "pre-registered deterministic APS, S = sum_{p_j >= p_y} p_j; never empty",
            "lac": "least-ambiguous classifier, S = 1 - p_y; set {y: p_y >= 1 - q}; may be empty",
            "aps_rand": "randomized APS, S = sum_{p_j > p_y} p_j + U*p_y, U ~ Uniform(0,1); may be empty",
        },
        "aps_rand_uniform_seed": U_SEED,
        "events": {"ieee123": int(len(y123)), "ieee34": int(len(y34))},
        "labels": {"ieee123": int(nf123 + 1), "ieee34": int(nf34 + 1)},
        "results": {},
    }

    pre = json.loads((ag.ACTIVE_SUMMARY_DIR / "conformal_safety.json").read_text(encoding="utf-8"))
    repro_ok = True
    for mname, (p123, p34) in models.items():
        res_m: dict = {}
        for method in am.CONFORMAL_METHODS:
            res_k: dict = {}
            sets_123_by_alpha = {}
            for alpha in ALPHAS:
                k = _key(alpha)
                r123, s123 = _cross_conformal_123(p123, y123, fold123, nf123, method, alpha)
                rzs, _ = _zero_shot_34(p123, y123, p34, y34, nf34, method, alpha)
                rrc = _recal_34(p34, y34, bus34, nf34, method, alpha)
                sets_123_by_alpha[k] = s123
                res_k[k] = {"ieee123_cross_conformal": r123, "ieee34_zero_shot_q_from_123": rzs,
                            "ieee34_recal_5pct_buses": rrc}
                if method == "aps_det":
                    pre123 = pre["ieee123_bus_disjoint_cv"][mname][k]
                    pre34 = pre["ieee34_transfer"][mname]["zero_shot_q_from_123"][k]
                    same = (abs(r123["coverage"] - pre123["empirical_coverage"]) < 1e-9
                            and abs(r123["avg_set_size"] - pre123["avg_set_size"]) < 1e-9
                            and abs(r123["singleton_share"] - pre123["autonomous_share"]) < 1e-9
                            and abs(rzs["coverage"] - pre34["empirical_coverage"]) < 1e-9
                            and abs(rzs["singleton_share"] - pre34["autonomous_share"]) < 1e-9)
                    res_k[k]["reproduces_preregistered"] = bool(same)
                    repro_ok &= same
            # Pre-stated reading rule: non-degenerate if 90% and 95% sets differ and 123-bus coverage is
            # within 3 points of each target.
            differ = bool((sets_123_by_alpha["target_90"] != sets_123_by_alpha["target_95"]).any())
            within = all(abs(res_k[_key(a)]["ieee123_cross_conformal"]["coverage"] - (1 - a)) <= 0.03
                         for a in ALPHAS)
            res_k["reading_rule"] = {"sets_90_and_95_differ": differ, "ieee123_coverage_within_3pts": bool(within),
                                     "non_degenerate": bool(differ and within)}
            res_m[method] = res_k
        out["results"][mname] = res_m
    out["aps_det_reproduces_preregistered"] = bool(repro_ok)

    ag.ACTIVE_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    path = ag.ACTIVE_SUMMARY_DIR / "conformal_posthoc.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    provenance.record("active_conformal_posthoc", [path])

    for mname in models:
        for method in am.CONFORMAL_METHODS:
            r = out["results"][mname][method]
            for alpha in ALPHAS:
                k = _key(alpha)
                a, z, c = (r[k]["ieee123_cross_conformal"], r[k]["ieee34_zero_shot_q_from_123"],
                           r[k]["ieee34_recal_5pct_buses"])
                print(f"{mname:14s} {method:8s} {k}: 123 cov={a['coverage']:.4f} size={a['avg_set_size']:.2f} "
                      f"single={a['singleton_share']:.4f} | 34zs cov={z['coverage']:.4f} "
                      f"single={z['singleton_share']:.4f} | 34rc cov={c['coverage']['mean']} "
                      f"(min {c['coverage']['min']})")
            print(f"{'':14s} {method:8s} reading rule: {r['reading_rule']}")
    print("aps_det reproduces pre-registered:", repro_ok)


if __name__ == "__main__":
    main()
