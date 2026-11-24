"""Transfer study, phase 1: feeder-independent graph samples (research/gnn-transfer/PLAN.md)."""
import numpy as np
import pytest

from shf import config, feeder, transfer


@pytest.fixture(scope="module")
def grid34():
    transfer.load_feeder("ieee34")
    return transfer.placement_rule("ieee34")


@pytest.fixture(scope="module")
def grid37():
    transfer.load_feeder("ieee37")
    return transfer.placement_rule("ieee37")


def test_placement_rule_on_the_unseen_feeder(grid34):
    """The rule fixed before any result: head recloser + one switch per branch of every split
    where at least two branches carry 5% of the load."""
    assert grid34.line[grid34.devices[0]] == "l1" and grid34.parent[grid34.devices[0]] is None
    assert set(grid34.line.values()) == {"l1", "l8", "l9", "l16", "l32", "l17", "l18"}
    seen = [b for bs in grid34.members.values() for b in bs]
    assert len(seen) == len(set(seen))                                  # every bus in one zone only
    for d in grid34.devices[1:]:                                        # every zone hangs off the head
        top = d
        while grid34.parent[top]:
            top = grid34.parent[top]
        assert top == grid34.devices[0]


def test_placement_rule_on_ieee37_underground_delta(grid37):
    """Frozen BRANCH_SHARE=0.05 placement rule on the 3-wire underground delta IEEE 37-bus feeder."""
    assert transfer.BRANCH_SHARE == 0.05
    assert grid37.line[grid37.devices[0]] == "l35" and grid37.parent[grid37.devices[0]] is None
    assert set(grid37.line.values()) == {"l35", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l29", "l30"}
    assert len(grid37.devices) == 10
    seen = [b for bs in grid37.members.values() for b in bs]
    assert len(seen) == len(set(seen)) == 36
    assert abs(sum(grid37.kw.values()) - 2457.0) < 1e-6
    for d in grid37.devices[1:]:
        top = d
        while grid37.parent[top]:
            top = grid37.parent[top]
        assert top == grid37.devices[0]
    assert all(feeder.bus_phases(b) == [1, 2, 3] for b in seen)
    cases = transfer.fault_cases(grid37)
    assert len(cases) == 36 * (3 * len(config.SLG_RESISTANCES) + 7 * len(config.PHASE_RESISTANCES))
    assert {c["ftype"] for c in cases} == {"SLG", "LL", "LLG", "3PH"}


def test_ieee37_fault_physics_and_finite_features(grid37):
    """Spot-check 3PH, LL, and ungrounded-delta SLG fault physics and finite features on IEEE 37-bus."""
    import opendssdirect as dss

    transfer.load_feeder("ieee37")
    struct = transfer.structure(grid37)
    snap = lambda: {d: feeder.device_measurement(grid37.line[d]) for d in grid37.devices}
    assert feeder.solve(controls=True)
    pre = snap()

    # 1. Bolted 3-phase fault at bus 738 (zone D9): fault current follows source -> D1 -> D4 -> D6 -> D9.
    feeder.cmd("New Fault.T37 phases=3 bus1=738.1.2.3 bus2=738.0.0.0 r=0.01")
    assert feeder.solve(controls=False)
    post_3ph = snap()
    x_3ph = transfer.node_features(grid37, pre, post_3ph, struct)
    assert x_3ph.shape == (len(grid37.devices), len(transfer.FEATURES)) and np.isfinite(x_3ph).all()
    di = transfer.FEATURES.index("dIa")
    path = {"D1", "D4", "D6", "D9"}
    on = [x_3ph[i, di] for i, d in enumerate(grid37.devices) if d in path]
    off = [x_3ph[i, di] for i, d in enumerate(grid37.devices) if d not in path]
    assert min(on) > max(off)

    # 2. Bolted LL fault at bus 738: strong phase-to-phase current circulates without needing neutral.
    feeder.cmd("Edit Fault.T37 phases=1 bus1=738.1 bus2=738.2 r=0.01 enabled=yes")
    assert feeder.solve(controls=False)
    dss.Circuit.SetActiveElement("Fault.T37")
    c_ll = dss.CktElement.Currents()
    assert abs(complex(c_ll[0], c_ll[1])) > 500.0
    x_ll = transfer.node_features(grid37, pre, snap(), struct)
    assert x_ll.shape == (len(grid37.devices), len(transfer.FEATURES)) and np.isfinite(x_ll).all()

    # 3. Bolted SLG fault at bus 738: ungrounded 3-wire delta returns small capacitive current + neutral shift.
    feeder.cmd("Edit Fault.T37 phases=1 bus1=738.1 bus2=738.0 r=0.01 enabled=yes")
    assert feeder.solve(controls=False)
    dss.Circuit.SetActiveElement("Fault.T37")
    c_slg = dss.CktElement.Currents()
    i_slg = abs(complex(c_slg[0], c_slg[1]))
    assert 0.5 < i_slg < 10.0
    post_slg = snap()
    assert float(np.abs(post_slg["D1"]["v"]).max()) > 1.4
    x_slg = transfer.node_features(grid37, pre, post_slg, struct)
    assert x_slg.shape == (len(grid37.devices), len(transfer.FEATURES)) and np.isfinite(x_slg).all()

    feeder.cmd("Edit Fault.T37 enabled=no")
    assert feeder.solve(controls=True)


def test_features_are_relative_and_follow_the_fault_path(grid34):
    transfer.load_feeder("ieee34")
    struct = transfer.structure(grid34)
    snap = lambda: {d: feeder.device_measurement(grid34.line[d]) for d in grid34.devices}
    feeder.solve(controls=True)
    pre = snap()
    feeder.cmd("New Fault.T phases=3 bus1=842.1.2.3 bus2=842.0.0.0 r=0.01")
    feeder.solve(controls=False)
    post = snap()
    feeder.cmd("Edit Fault.T enabled=no")
    feeder.solve(controls=True)
    x = transfer.node_features(grid34, pre, post, struct)
    assert x.shape == (len(grid34.devices), len(transfer.FEATURES)) and np.isfinite(x).all()
    di = transfer.FEATURES.index("dIa")
    path = {"D1", "D3", "D4", "D7"}                                     # source -> zone of bus 842
    on = [x[i, di] for i, d in enumerate(grid34.devices) if d in path]
    off = [x[i, di] for i, d in enumerate(grid34.devices) if d not in path]
    assert min(on) > max(off)                                           # the fault current only flows on the path


def test_training_feeder_uses_the_study_zones():
    feeder.load_feeder()
    g = transfer.study_grid()
    assert g.devices == list(config.SECTIONALIZERS)
    from shf.topology import find_zones
    z = find_zones()
    assert all(g.members[d] == z.members[d] and g.parent[d] == z.parent[d] for d in g.devices)


# --- Phase 2: feeder-independent models (no OpenDSS needed) --------------------------------------

def _synthetic_tree_events(parent: np.ndarray, n_events: int = 80, seed: int = 0):
    """Small synthetic tree dataset where nodes on the root->target path see high fault current."""
    from shf import transfer_models as tm
    rng = np.random.default_rng(seed)
    n_nodes = len(parent)
    n_feat = len(transfer.FEATURES)
    depths = tm.tree_depths(parent)
    X = rng.normal(0.0, 0.05, size=(n_events, n_nodes, n_feat)).astype(np.float32)
    X[:, :, 8:11] = 1.0                                      # Va, Vb, Vc ~ 1 pu
    X[:, :, 14:17] = 1.0                                     # has_a, has_b, has_c
    X[:, :, 17] = depths
    y = rng.integers(0, n_nodes, size=n_events)
    for e in range(n_events):
        cur = int(y[e])
        while cur >= 0:
            X[e, cur, 0:3] += 2.0                            # dIa, dIb, dIc
            X[e, cur, 3:6] += 2.0                            # Ia, Ib, Ic (expm1(2) > 2.0)
            X[e, cur, 6] += 1.0                              # dI0
            X[e, cur, 11:14] -= 0.3                          # voltage drop
            cur = int(parent[cur])
    return X, y


def test_fpi_rule_picks_deepest_flagged_and_handles_missing_sensor():
    from shf import transfer_models as tm
    parent = np.array([-1, 0, 0, 1, 3], dtype=np.int64)      # depth: 0, 1, 1, 2, 3
    X = np.zeros((3, 5, len(transfer.FEATURES)), dtype=np.float32)
    # Event 0: fault in node 3 -> nodes 0, 1, 3 see high phase current (log1p(3.0) > log1p(2.0))
    X[0, [0, 1, 3], 3] = np.log1p(3.0)
    # Event 1: ground fault in node 2 -> nodes 0, 2 see 3*dI0 > 0.5 (dI0 = log1p(0.3))
    X[1, [0, 2], 6] = np.log1p(0.3)
    # Event 2: high-impedance fault -> no device exceeds pickup
    pred = tm.fpi_predict(X, parent)
    assert list(pred) == [3, 2, -1]
    # Blanking node 3's sensor falls back to its flagged parent (node 1) without crashing.
    pred_miss = tm.fpi_predict(tm.blank_sensor(X, 3), parent)
    assert pred_miss[0] == 1 and pred_miss[1] == 2 and pred_miss[2] == -1


def test_gnn_permutation_equivariant_variable_size_and_finite_grads():
    import torch
    from shf import transfer_models as tm

    parent = np.array([-1, 0, 0, 1, 3, 2], dtype=np.int64)
    X, y = _synthetic_tree_events(parent, n_events=12, seed=1)
    for n_layers in (2, 3):
        net = tm.ZoneTreeGNN(hidden=32, n_layers=n_layers, dropout=0.0)
        net.set_normalizer(X)
        net.eval()

        # Permutation equivariance: relabeling nodes permutes logits identically.
        perm = np.array([3, 0, 5, 1, 2, 4], dtype=np.int64)
        inv = np.argsort(perm)
        par_perm = np.array([-1 if parent[p] < 0 else inv[parent[p]] for p in perm], dtype=np.int64)
        logits = net(torch.from_numpy(X), torch.from_numpy(parent))
        logits_perm = net(torch.from_numpy(X[:, perm, :]), torch.from_numpy(par_perm))
        assert torch.allclose(logits[:, perm], logits_perm, atol=1e-5)

        # Variable graph size: the same weights run on a different tree with a different node count.
        small_parent = np.array([-1, 0, 1, 1], dtype=np.int64)
        X_small, _ = _synthetic_tree_events(small_parent, n_events=5, seed=2)
        out_small = net(torch.from_numpy(X_small), torch.from_numpy(small_parent))
        assert out_small.shape == (5, 4) and torch.isfinite(out_small).all()

        # Finite gradients even with an offline (NaN) sensor.
        net.train()
        X_nan = tm.blank_sensor(X, 2)
        loss = torch.nn.functional.cross_entropy(net(torch.from_numpy(X_nan), torch.from_numpy(parent)),
                                                 torch.from_numpy(y))
        loss.backward()
        assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in net.parameters())


def test_per_node_gbdt_handles_variable_graph_sizes_and_missing_sensor():
    from shf import transfer_models as tm
    parent6 = np.array([-1, 0, 0, 1, 1, 2], dtype=np.int64)
    X6, y6 = _synthetic_tree_events(parent6, n_events=120, seed=3)
    clf = tm.PerNodeGBDT(max_iter=30, max_leaf_nodes=15, sensor_dropout=0.15, seed=0).fit(X6, y6, parent6)

    # Same model predicts on a 4-node tree with an offline sensor.
    parent4 = np.array([-1, 0, 0, 2], dtype=np.int64)
    X4, _ = _synthetic_tree_events(parent4, n_events=10, seed=4)
    scores = clf.scores(tm.blank_sensor(X4, 1), parent4)
    preds = clf.predict(tm.blank_sensor(X4, 1), parent4)
    assert scores.shape == (10, 4) and np.isfinite(scores).all()
    assert ((preds >= 0) & (preds < 4)).all()


def test_phase2_group_kfold_has_no_bus_overlap_and_result_is_ieee123_only():
    import json
    from sklearn.model_selection import GroupKFold
    from shf import transfer_models as tm

    npz = transfer.OUT_DIR / "transfer_ieee123.npz"
    if npz.exists():
        ds = tm.load_dataset("ieee123", npz)
        for tr, te in GroupKFold(n_splits=tm.N_FOLDS).split(ds.X, ds.y, ds.bus):
            assert set(ds.bus[tr]).isdisjoint(set(ds.bus[te]))

    res_path = transfer.SUMMARY_DIR / "phase2_ieee123.json"
    if res_path.exists():
        r = json.loads(res_path.read_text(encoding="utf-8"))
        assert r["feeder"] == "ieee123" and r["simulation_only"] is True
        assert r["validation"]["method"] == "GroupKFold" and r["validation"]["group_by"] == "bus"
        assert set(r["models"]) == {"fpi", "per_node_gbdt", "gnn"}
        for name, m in r["models"].items():
            assert 0.0 <= m["accuracy"] <= 1.0, name
            assert len(m["fold_accuracies"]) == tm.N_FOLDS
            assert set(m["missing_sensor_accuracy"]) == set(r["devices"])


# --- Phase 3 & Phase 2b tests --------------------------------------------------------------------

def test_few_shot_finetuning_runs_on_synthetic_trees():
    from shf import transfer_models as tm
    parent6 = np.array([-1, 0, 0, 1, 1, 2], dtype=np.int64)
    X6, y6 = _synthetic_tree_events(parent6, n_events=100, seed=10)
    gbdt = tm.PerNodeGBDT(max_iter=20, max_leaf_nodes=15, seed=0).fit(X6, y6, parent6)
    gnn = tm.train_gnn(X6, y6, parent6, hidden=32, n_layers=2, epochs=4, batch_size=32, seed=0)

    parent4 = np.array([-1, 0, 0, 2], dtype=np.int64)
    X4, y4 = _synthetic_tree_events(parent4, n_events=40, seed=11)
    gbdt_ft = tm.finetune_gbdt(gbdt, X4[:20], y4[:20], parent4, extra_iter=10, seed=0)
    gnn_ft = tm.finetune_gnn(gnn, X4[:20], y4[:20], parent4, epochs=3, batch_size=16, seed=0)
    p_gbdt = gbdt_ft.predict(X4[20:], parent4)
    p_gnn = tm.predict_gnn(gnn_ft, X4[20:], parent4)
    assert p_gbdt.shape == (20,) and ((p_gbdt >= 0) & (p_gbdt < 4)).all()
    assert p_gnn.shape == (20,) and ((p_gnn >= 0) & (p_gnn < 4)).all()


def test_phase3_result_matches_frozen_phase2_hyperparams():
    import json
    p2_path = transfer.SUMMARY_DIR / "phase2_ieee123.json"
    p3_path = transfer.SUMMARY_DIR / "phase3_ieee34.json"
    if not (p2_path.exists() and p3_path.exists()):
        pytest.skip("Phase 2/3 result JSONs not generated yet")
    p2 = json.loads(p2_path.read_text(encoding="utf-8"))
    p3 = json.loads(p3_path.read_text(encoding="utf-8"))
    assert p3["simulation_only"] is True
    assert p3["train_feeder"] == "ieee123" and p3["test_feeder"] == "ieee34"
    assert p3["frozen_hyperparameters_from_phase2"] == p2["frozen_for_phase3"]
    assert set(p3["zero_shot"]) == {"per_node_gbdt", "gnn"}
    assert set(p3["few_shot"]) >= {"pct_5", "pct_20"}


def test_phase3_ieee37_and_phase2b_ieee37_schemas_match_frozen_hyperparams():
    import json
    p2_path = transfer.SUMMARY_DIR / "phase2_ieee123.json"
    p37_path = transfer.SUMMARY_DIR / "phase3_ieee37.json"
    if p2_path.exists() and p37_path.exists():
        p2 = json.loads(p2_path.read_text(encoding="utf-8"))
        p37 = json.loads(p37_path.read_text(encoding="utf-8"))
        assert p37["simulation_only"] is True
        assert p37["train_feeder"] == "ieee123" and p37["test_feeder"] == "ieee37"
        assert p37["frozen_hyperparameters_from_phase2"] == p2["frozen_for_phase3"]
        assert set(p37["zero_shot"]) == {"per_node_gbdt", "gnn"}
        assert set(p37["few_shot"]) >= {"pct_5", "pct_20"}
        assert set(p37["pre_committed_criteria"]) == {"per_node_gbdt", "gnn"}

    p2b37_path = transfer.SUMMARY_DIR / "phase2b_bus_ieee37.json"
    if p2b37_path.exists():
        r = json.loads(p2b37_path.read_text(encoding="utf-8"))
        assert r["simulation_only"] is True and r["test_feeder"] == "ieee37"
        sec = r["ieee37"]
        for key in ("random_in_zone", "reactance_takagi", "bus_graph_gnn_zero_shot"):
            assert 0.0 <= sec[key]["top1"] <= sec[key]["top3"] <= 1.0
        assert len(sec["reactance_takagi"]["top_confused_bus_pairs"]) > 0
        assert set(r["pre_committed_criteria"]) == {"stage1_predicted_zone", "oracle_zone"}


def test_bus_locator_takagi_ranks_bolted_fault_bus_first_on_ieee34():
    from shf import bus_locator as bl
    fbm = bl.build_feeder_bus_model("ieee34")
    # Bolted 3-phase fault at bus 816 (inside zone D1): noiseless Takagi should rank 816 #1.
    zi = fbm.bus_zone_idx[fbm.bus_index["816"]]
    d = fbm.grid.devices[zi]
    feeder.solve(controls=True)
    pre = feeder.device_measurement(fbm.grid.line[d])
    feeder.cmd("New Fault.BusT phases=3 bus1=816.1.2.3 bus2=816.0.0.0 r=0.01")
    feeder.solve(controls=False)
    post = feeder.device_measurement(fbm.grid.line[d])
    feeder.cmd("Edit Fault.BusT enabled=no")
    feeder.solve(controls=True)

    n_dev = len(fbm.grid.devices)
    V_post = np.zeros((1, n_dev, 3), dtype=np.complex64)
    I_post = np.zeros((1, n_dev, 3), dtype=np.complex64)
    dI = np.zeros((1, n_dev, 3), dtype=np.complex64)
    V_post[0, zi] = post["v"] * (fbm.dev_kv_ln[zi] * 1000.0)
    I_post[0, zi] = post["i"]
    dI[0, zi] = post["i"] - pre["i"]

    z_arr = np.array([zi], dtype=np.int64)
    xerr, rest, compat = bl.takagi_bus_residuals(fbm, V_post, I_post, dI, z_arr)
    scores = bl.reactance_scores(fbm, xerr, rest, compat, z_arr)
    top1 = int(np.argmax(scores[0]))
    assert fbm.buses[top1] == "816"


def test_bus_graph_gnn_variable_size_and_zone_mask():
    import torch
    from shf import bus_locator as bl
    net = bl.BusGraphGNN(in_features=28, hidden=24, n_layers=2, dropout=0.0)
    for n_bus in (6, 12):
        par = np.array([-1] + list(range(n_bus - 1)), dtype=np.int64)
        X = np.random.default_rng(n_bus).normal(size=(4, n_bus, 28)).astype(np.float32)
        mask = np.zeros((4, n_bus), dtype=bool)
        mask[:, :3] = True
        logits = net(torch.from_numpy(X), torch.from_numpy(par), torch.from_numpy(mask))
        assert logits.shape == (4, n_bus)
        assert (logits[:, 3:] <= -1e8).all()
        assert torch.isfinite(logits[:, :3]).all()


def test_phase2b_result_schema():
    import json
    p = transfer.SUMMARY_DIR / "phase2b_bus_location.json"
    if not p.exists():
        pytest.skip("Phase 2b result JSON not generated yet")
    r = json.loads(p.read_text(encoding="utf-8"))
    assert r["simulation_only"] is True
    for name in ("ieee123", "ieee34"):
        sec = r[name]
        for key in ("random_in_zone", "reactance_takagi"):
            assert 0.0 <= sec[key]["top1"] <= sec[key]["top3"] <= 1.0
        assert len(sec["reactance_takagi"]["top_confused_bus_pairs"]) > 0


def test_dashboard_section_2c_and_published_files():
    from shf import config
    html = (config.ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'id="cross-feeder"' in html
    for xid in ("table-transfer", "table-bus-stage", "table-conformal"):
        assert f'data-x="{xid}"' in html
        assert f'"{xid}":' in html
    for fn in (
        "phase2_ieee123.json",
        "phase2b_bus_location.json",
        "phase3_ieee34.json",
        "phase_active_ieee123.json",
        "phase_active_ieee34.json",
        "conformal_safety.json",
    ):
        assert (config.ROOT / "docs" / "data" / fn).exists(), f"Missing docs/data/{fn}"
    for part in ("recloser", "auto_switch", "regulator", "capacitor", "transformer", "substation"):
        assert f'href="drawings/{part}.pdf"' in html
        assert (config.ROOT / "docs" / "drawings" / f"{part}.pdf").exists()


def test_signal_to_load_result_is_consistent():
    """results/transfer/signal_to_load.json: shares are fault current / head current, every fault converged."""
    import json
    p = transfer.SUMMARY_DIR / "signal_to_load.json"
    if not p.exists():
        pytest.skip("scripts/signal_to_load.py has not been run yet")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["simulation_only"] is True
    assert {"ieee123", "ieee34", "ieee37"} <= set(d["feeders"])
    for f in d["feeders"].values():
        for r in f["by_resistance"].values():
            assert r["not_converged"] == 0 and r["faults"] > 0
            assert abs(r["share_of_head_current"]["median"]
                       - r["fault_current_a"]["median"] / f["head_current_a"]) < 1e-3
        # A larger fault resistance never draws more current.
        meds = [f["by_resistance"][k]["fault_current_a"]["median"] for k in sorted(f["by_resistance"], key=float)]
        assert meds == sorted(meds, reverse=True)
