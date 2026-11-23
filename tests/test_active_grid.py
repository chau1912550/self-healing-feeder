"""Tests for the Active-Grid GNN + Split Conformal Prediction study (research/active-grid-gnn/PLAN.md)."""
from __future__ import annotations

import numpy as np
import pytest
import torch

from shf import active_grid as ag, active_models as am, feeder


@pytest.mark.parametrize("name", ["ieee123", "ieee34"])
def test_all_active_topologies_converge_with_der_and_loops(name):
    """Every radial, back-fed reconfigured, and closed-loop topology converges with 40% Model=7 DER."""
    grid, der_names, caps = ag.load_active_feeder(name)
    topos = ag.TOPOLOGIES[name]
    adj, is_tie = ag.build_topology_matrices(grid, topos)
    spec = ag.DER_SPECS[name]
    assert caps and len(der_names) == len(spec["buses"])

    der_kws = np.full(len(der_names), 0.40 * spec["nominal_kw"] / len(der_names))
    ag.set_der_kw(der_names, der_kws)
    dz = {}
    for b, kw in zip(spec["buses"], der_kws):
        z = grid.bus_zone[b]
        dz[z] = dz.get(z, 0.0) + float(kw)

    for ti, topo in enumerate(topos):
        ag.set_topology(name, grid, topo)
        assert feeder.solve(controls=True), f"{name} topo {topo.name} failed to converge"
        snap = {d: feeder.device_measurement(grid.line[d]) for d in grid.devices}
        x = ag.active_node_features(grid, topo, adj[ti], snap, snap, dz)
        assert x.shape == (len(grid.devices), len(ag.ACTIVE_FEATURES))
        assert np.isfinite(x).all()
        # Closed-loop topologies must have at least N edges (a cycle) or >= 2 active sources.
        if topo.is_looped:
            n_edges = int(adj[ti].sum() // 2)
            n_src = int((x[:, ag.ACTIVE_FEATURES.index("is_source_adj")] > 0.5).sum())
            assert n_edges >= len(grid.devices) or n_src >= 2

    ag.set_der_kw(der_names, np.zeros(len(der_names)))
    ag.set_topology(name, grid, topos[0])


def _synthetic_active_data(n_nodes: int = 6, n_events: int = 120, seed: int = 0):
    rng = np.random.default_rng(seed)
    n_feat = len(ag.ACTIVE_FEATURES)
    # 2 topologies: radial line (0) and closed ring (1)
    adj = np.zeros((2, n_nodes, n_nodes), dtype=np.float32)
    is_tie = np.zeros((2, n_nodes, n_nodes), dtype=np.float32)
    for i in range(n_nodes - 1):
        adj[:, i, i + 1] = adj[:, i + 1, i] = 1.0
    adj[1, 0, n_nodes - 1] = adj[1, n_nodes - 1, 0] = 1.0
    is_tie[1, 0, n_nodes - 1] = is_tie[1, n_nodes - 1, 0] = 1.0

    X = rng.normal(0.0, 0.05, size=(n_events, n_nodes, n_feat)).astype(np.float32)
    X[:, :, 8:11] = 1.0                                      # Va, Vb, Vc ~ 1 pu
    X[:, :, 14:17] = 1.0                                     # has_a, has_b, has_c
    X[:, :, ag.ACTIVE_FEATURES.index("is_closed")] = 1.0
    X[:, 0, ag.ACTIVE_FEATURES.index("is_source_adj")] = 1.0
    topo_id = rng.integers(0, 2, size=n_events, dtype=np.int64)
    y = rng.integers(0, n_nodes + 1, size=n_events, dtype=np.int64)  # includes NO_FAULT = n_nodes
    for e in range(n_events):
        if y[e] < n_nodes:
            X[e, y[e], 0:3] += 2.0                           # dIa..dIc
            X[e, y[e], 3:6] += 2.0                           # Ia..Ic
            X[e, y[e], 11:14] -= 0.25                        # voltage drop
    return X, y, adj, is_tie, topo_id


def test_active_gatv2_permutation_equivariant_loops_variable_size_and_grads():
    X, y, adj, is_tie, topo_id = _synthetic_active_data(n_nodes=6, n_events=16, seed=1)
    net = am.ActiveGridGATv2(hidden=32, n_layers=2, n_heads=4, dropout=0.0)
    net.set_normalizer(X)
    net.eval()

    # Permutation equivariance: zone logits permute with nodes; NO_FAULT logit is permutation-invariant.
    perm = np.array([3, 0, 5, 1, 2, 4], dtype=np.int64)
    adj_b = adj[topo_id]
    tie_b = is_tie[topo_id]
    logits = net(torch.from_numpy(X), torch.from_numpy(adj_b), torch.from_numpy(tie_b))
    logits_p = net(
        torch.from_numpy(X[:, perm, :]),
        torch.from_numpy(adj_b[:, perm, :][:, :, perm]),
        torch.from_numpy(tie_b[:, perm, :][:, :, perm]),
    )
    assert logits.shape == (16, 7)
    assert torch.allclose(logits[:, perm], logits_p[:, :6], atol=1e-5)
    assert torch.allclose(logits[:, 6], logits_p[:, 6], atol=1e-5)

    # Variable graph size (4 nodes, with a loop): same weights run unchanged.
    X4, _, adj4, tie4, t4 = _synthetic_active_data(n_nodes=4, n_events=6, seed=2)
    out4 = net(torch.from_numpy(X4), torch.from_numpy(adj4[t4]), torch.from_numpy(tie4[t4]))
    assert out4.shape == (6, 5) and torch.isfinite(out4).all()

    # Finite gradients even with an offline (NaN) sensor and NO_FAULT targets.
    net.train()
    X_nan = am.blank_active_sensor(X, 2)
    loss = torch.nn.functional.cross_entropy(
        net(torch.from_numpy(X_nan), torch.from_numpy(adj_b), torch.from_numpy(tie_b)),
        torch.from_numpy(y),
    )
    loss.backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in net.parameters())


def test_active_gbdt_and_fpi_handle_nofault_loops_and_missing_sensor():
    X, y, adj, _, topo_id = _synthetic_active_data(n_nodes=6, n_events=140, seed=3)
    p_fpi = am.active_fpi_predict(X, adj, topo_id)
    assert p_fpi.shape == (140,) and ((p_fpi >= 0) & (p_fpi <= 6)).all()

    clf = am.ActivePerNodeGBDT(max_iter=25, max_leaf_nodes=15, seed=0).fit(X, y, adj, topo_id)
    X4, _, adj4, _, t4 = _synthetic_active_data(n_nodes=4, n_events=12, seed=4)
    probs = clf.predict_proba(am.blank_active_sensor(X4, 1), adj4, t4)
    assert probs.shape == (12, 5) and np.isfinite(probs).all()
    assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-6)


def test_split_conformal_aps_satisfies_finite_sample_coverage():
    """On exchangeable synthetic probabilities, APS coverage meets >= 1 - alpha with non-empty sets."""
    rng = np.random.default_rng(7)
    n_cal, n_test, n_cls = 500, 1000, 8
    logits = rng.normal(0.0, 1.5, size=(n_cal + n_test, n_cls))
    probs = am._softmax_np(logits)
    # Sample ground-truth labels from the true categorical distribution so cal & test are exchangeable.
    u = rng.random(n_cal + n_test)[:, None]
    y = (np.cumsum(probs, axis=1) >= u).argmax(axis=1)

    q95 = am.conformal_calibrate(probs[:n_cal], y[:n_cal], alpha=0.05)
    ev = am.evaluate_conformal(probs[n_cal:], y[n_cal:], q95, nofault_class=n_cls - 1)
    assert ev["empirical_coverage"] >= 0.93
    assert ev["avg_set_size"] >= 1.0
    if ev["autonomous_accuracy"] is not None:
        assert ev["autonomous_accuracy"] >= ev["raw_argmax_accuracy"]


def test_active_grid_results_match_frozen_hyperparams_and_criteria():
    import json
    p123 = ag.ACTIVE_SUMMARY_DIR / "phase_active_ieee123.json"
    p34 = ag.ACTIVE_SUMMARY_DIR / "phase_active_ieee34.json"
    pconf = ag.ACTIVE_SUMMARY_DIR / "conformal_safety.json"
    if not (p123.exists() and p34.exists() and pconf.exists()):
        pytest.skip("Active-grid result JSONs not present yet")
    d123 = json.loads(p123.read_text(encoding="utf-8"))
    d34 = json.loads(p34.read_text(encoding="utf-8"))
    dconf = json.loads(pconf.read_text(encoding="utf-8"))
    assert d123["simulation_only"] is True and d34["simulation_only"] is True and dconf["simulation_only"] is True
    assert d34["frozen_hyperparameters_from_123"] == d123["frozen_for_ieee34"]
    # The stored verdicts must follow from the stored numbers and the thresholds fixed in PLAN.md
    # (this checks consistency, not which way the result came out).
    c1 = d34["pre_committed_criteria"]["C1_breaks_legacy_fpi"]
    assert c1["met"] == ((c1["fpi_123_acc"] < 0.55 or c1["fpi_123_fpr"] > 0.15)
                         and (c1["fpi_34_acc"] < 0.55 or c1["fpi_34_fpr"] > 0.15))
    c3 = d34["pre_committed_criteria"]["C3_conformal_safety_95"]
    assert c3["met"] == (c3["ieee123_coverage_95"] >= 0.93 and c3["ieee34_recal5pct_coverage_95"] >= 0.94
                         and c3["ieee34_recal5pct_auto_acc"] >= c3["ieee34_recal5pct_raw_acc"])
    assert dconf["criteria_c3"] == c3


def _calibrated_synthetic(n: int, n_cls: int, seed: int):
    """Probabilities whose labels are drawn from themselves, so they are calibrated and exchangeable."""
    rng = np.random.default_rng(seed)
    probs = am._softmax_np(rng.normal(0.0, 2.0, size=(n, n_cls)))
    y = (np.cumsum(probs, axis=1) >= rng.random(n)[:, None]).argmax(axis=1)
    return probs, y


@pytest.mark.parametrize("method", am.CONFORMAL_METHODS)
def test_posthoc_conformal_scores_reach_target_coverage(method):
    """Each post-hoc score covers >= 1 - alpha on exchangeable data; lac and aps_rand stay near the target."""
    probs, y = _calibrated_synthetic(6000, 8, seed=11)
    cal, te = slice(0, 3000), slice(3000, None)
    u = np.random.default_rng(3).uniform(size=len(y))
    for alpha in (0.10, 0.05):
        q = am.conformal_quantile(am.conformal_scores(probs[cal], y[cal], method, u[cal]), alpha)
        sets = am.conformal_sets(probs[te], q, method, u[te])
        rep = am.conformal_report(probs[te], y[te], sets, nofault_class=7)
        assert rep["coverage"] >= 1 - alpha - 0.02, (method, alpha, rep["coverage"])
        if method != "aps_det":                       # the randomized / LAC sets are not conservative
            assert rep["coverage"] <= 1 - alpha + 0.03, (method, alpha, rep["coverage"])
        if method == "aps_det":
            assert rep["empty_share"] == 0.0


def test_aps_det_matches_preregistered_functions():
    probs, y = _calibrated_synthetic(800, 6, seed=5)
    q_old = am.conformal_calibrate(probs[:400], y[:400], alpha=0.05)
    q_new = am.conformal_quantile(am.conformal_scores(probs[:400], y[:400], "aps_det"), 0.05)
    assert q_old == q_new
    assert (am.conformal_sets(probs[400:], q_new, "aps_det") == am.conformal_predict_sets(probs[400:], q_old)).all()


def test_conformal_posthoc_result_is_labelled_and_reproduces_preregistered():
    import json
    p = ag.ACTIVE_SUMMARY_DIR / "conformal_posthoc.json"
    if not p.exists():
        pytest.skip("scripts/active_conformal_posthoc.py has not been run yet")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["simulation_only"] is True and d["post_hoc"] is True
    assert d["aps_det_reproduces_preregistered"] is True
    assert set(d["results"]) == {"per_node_gbdt", "active_gatv2"}
    for m in d["results"].values():
        assert set(m) == set(am.CONFORMAL_METHODS)
