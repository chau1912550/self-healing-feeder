"""Conformal score comparison (research/active-grid-gnn/PLAN.md Addendum A &
research/ieee37-underground/PLAN.md Sections 3.8 & 4.4).

The pre-registered deterministic APS score saturates at 1.0, so its 95% sets keep almost every label.
This script compares three nonconformity scores on exactly the probabilities and splits the
active-grid run used:

    aps_det   deterministic APS (must reproduce conformal_safety.json)
    lac       least-ambiguous classifier, S = 1 - p_y (Sadinle, Lei & Wasserman 2019)
    aps_rand  randomized APS, S = sum_{p_j > p_y} p_j + U * p_y (Romano, Sesia & Candes 2020)

    python -u scripts/active_conformal_posthoc.py                         # ieee34 -> results/active_grid/conformal_posthoc.json
    python -u scripts/active_conformal_posthoc.py --test-feeder ieee37    # ieee37 -> results/active_grid_ieee37/conformal_posthoc.json

Reads data/generated/active_probs.npz (ieee34) or data/generated/active_grid_ieee37_probs.npz (ieee37)
and writes conformal_posthoc.json with a run record. Simulation only.
"""
from __future__ import annotations

import argparse
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-feeder", choices=["ieee34", "ieee37"], default="ieee34")
    args = ap.parse_args()
    tf = args.test_feeder
    tag = "34" if tf == "ieee34" else "37"
    if tf == "ieee34":
        src = ag.transfer.OUT_DIR / "active_probs.npz"
        summary_dir = ag.ACTIVE_SUMMARY_DIR
        producer = "active_conformal_posthoc"
        is_post_hoc = True
        plan_ref = "research/active-grid-gnn/PLAN.md, Addendum A (written before this run)"
    else:
        src = ag.transfer.OUT_DIR / "active_grid_ieee37_probs.npz"
        summary_dir = ag.config.RESULTS / "active_grid_ieee37"
        producer = "active_conformal_posthoc_ieee37"
        is_post_hoc = False
        plan_ref = "research/ieee37-underground/PLAN.md, Sections 3.8 & 4.4 (aps_rand at 95% pre-registered)"

    if not src.exists():
        raise SystemExit(f"{src} not found: run scripts/active_grid_run.py first (same run).")
    d = np.load(src, allow_pickle=False)
    y123, fold123, nf123 = d["y123"], d["fold_id123"], int(d["nofault123"])
    y_te, bus_te, nf_te = d[f"y{tag}"], d[f"bus{tag}"], int(d[f"nofault{tag}"])
    models = {"per_node_gbdt": (d["gbdt123_oof"], d[f"gbdt{tag}_zs"]),
              "active_gatv2": (d["gat123_oof"], d[f"gat{tag}_zs"])}

    out: dict = {
        "phase": "active_conformal_posthoc" if tf == "ieee34" else "active_conformal_ieee37",
        "simulation_only": True,
        "post_hoc": is_post_hoc,
        "test_feeder": tf,
        "plan": plan_ref,
        "methods": {
            "aps_det": "deterministic APS, S = sum_{p_j >= p_y} p_j; never empty",
            "lac": "least-ambiguous classifier, S = 1 - p_y; set {y: p_y >= 1 - q}; may be empty",
            "aps_rand": "randomized APS, S = sum_{p_j > p_y} p_j + U*p_y, U ~ Uniform(0,1); may be empty",
        },
        "aps_rand_uniform_seed": U_SEED,
        "events": {"ieee123": int(len(y123)), tf: int(len(y_te))},
        "labels": {"ieee123": int(nf123 + 1), tf: int(nf_te + 1)},
        "results": {},
    }

    pre = json.loads((summary_dir / "conformal_safety.json").read_text(encoding="utf-8"))
    repro_ok = True
    zs_key = f"{tf}_zero_shot_q_from_123"
    rc_key = f"{tf}_recal_5pct_buses"
    pre_tr_key = f"{tf}_transfer"
    for mname, (p123, p_te) in models.items():
        res_m: dict = {}
        for method in am.CONFORMAL_METHODS:
            res_k: dict = {}
            sets_123_by_alpha = {}
            for alpha in ALPHAS:
                k = _key(alpha)
                r123, s123 = _cross_conformal_123(p123, y123, fold123, nf123, method, alpha)
                rzs, _ = _zero_shot_34(p123, y123, p_te, y_te, nf_te, method, alpha)
                rrc = _recal_34(p_te, y_te, bus_te, nf_te, method, alpha)
                sets_123_by_alpha[k] = s123
                res_k[k] = {"ieee123_cross_conformal": r123, zs_key: rzs, rc_key: rrc}
                if method == "aps_det":
                    pre123 = pre["ieee123_bus_disjoint_cv"][mname][k]
                    pre_te = pre[pre_tr_key][mname]["zero_shot_q_from_123"][k]
                    same = (abs(r123["coverage"] - pre123["empirical_coverage"]) < 1e-9
                            and abs(r123["avg_set_size"] - pre123["avg_set_size"]) < 1e-9
                            and abs(r123["singleton_share"] - pre123["autonomous_share"]) < 1e-9
                            and abs(rzs["coverage"] - pre_te["empirical_coverage"]) < 1e-9
                            and abs(rzs["singleton_share"] - pre_te["autonomous_share"]) < 1e-9)
                    res_k[k]["reproduces_preregistered"] = bool(same)
                    repro_ok &= same
            # Reading rule: non-degenerate if 90% and 95% sets differ and 123-bus coverage is
            # within 3 points of each target.
            differ = bool((sets_123_by_alpha["target_90"] != sets_123_by_alpha["target_95"]).any())
            within = all(abs(res_k[_key(a)]["ieee123_cross_conformal"]["coverage"] - (1 - a)) <= 0.03
                         for a in ALPHAS)
            res_k["reading_rule"] = {"sets_90_and_95_differ": differ, "ieee123_coverage_within_3pts": bool(within),
                                     "non_degenerate": bool(differ and within)}
            res_m[method] = res_k
        out["results"][mname] = res_m
    out["aps_det_reproduces_preregistered"] = bool(repro_ok)

    summary_dir.mkdir(parents=True, exist_ok=True)
    path = summary_dir / "conformal_posthoc.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    provenance.record(producer, [path])

    for mname in models:
        for method in am.CONFORMAL_METHODS:
            r = out["results"][mname][method]
            for alpha in ALPHAS:
                k = _key(alpha)
                a, z, c = r[k]["ieee123_cross_conformal"], r[k][zs_key], r[k][rc_key]
                print(f"{mname:14s} {method:8s} {k}: 123 cov={a['coverage']:.4f} size={a['avg_set_size']:.2f} "
                      f"single={a['singleton_share']:.4f} | {tag}zs cov={z['coverage']:.4f} "
                      f"single={z['singleton_share']:.4f} | {tag}rc cov={c['coverage']['mean']} "
                      f"(min {c['coverage']['min']})")
            print(f"{'':14s} {method:8s} reading rule: {r['reading_rule']}")
    print("aps_det reproduces pre-registered:", repro_ok)


if __name__ == "__main__":
    main()
