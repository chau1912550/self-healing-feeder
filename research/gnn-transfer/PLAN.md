# Fault location that transfers to an unseen feeder (GNN)

Status: approved by the owner on 2026-11-21. **Phases 1, 2, 2b, 3 and 4 are done** (see result sections below; Phase 4 is the write-up in report section 2c, README and `docs/vi/`). Apart from the numbers in the four result sections (`results/transfer/dataset_*.json`, `phase2_ieee123.json`, `phase2b_bus_location.json`, `phase3_ieee34.json`), nothing in this file is a result. Third-feeder extension on an urban underground 3-wire delta grid: [`research/ieee37-underground/PLAN.md`](../ieee37-underground/PLAN.md). Planned two-tier Edge HIF-Sensor → Graph FLISR extension targeting the 200–400 Ω SLG regime: [`research/hif-fusion/PLAN.md`](../hif-fusion/PLAN.md) (pre-registered; not run yet).

## Question

The current fault locator reaches 97.7% zone accuracy, but only on the IEEE 123-bus feeder it was trained on. Can a model trained on that feeder locate faults on a feeder it has **never seen** (IEEE 34-bus), with no retraining?

## Why the current model cannot do this

Every input column is tied to one named device of the 123-bus feeder: 10 devices × 15 features, for example `Sw1_Ia` or `L61_dVb` (`shf/model.py: feature_columns`). Another feeder has different devices, a different number of them, and a different voltage level, so those columns do not exist there.

The model has to see the feeder as a **graph**:

- measurement devices are nodes;
- the zone tree gives the edges;
- features are relative or per-unit quantities that mean the same thing on any feeder.

## What exists (quick search, 2026-11-21; to be checked properly before any claim)

- Generalization of GNNs for fault detection, IEEE 123: topology changes inside the same feeder; F1 drops about 12%. <https://arxiv.org/pdf/2510.03571>
- PPGN, physics-preserved graph networks: validated on 123-node and 37-node, but set up for each feeder rather than transferred. <https://arxiv.org/pdf/2107.02275>
- Robustness of spatio-temporal GNNs, partially observable grids, IEEE 123. <https://arxiv.org/pdf/2604.20403>
- GNN generalization across DER penetration, reconfigured IEEE 123. <https://arxiv.org/html/2607.29293>
- DACDFE-GNN: IEEE 34 and 123, but each feeder is trained and evaluated separately. <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12473272/>
- The review (arXiv 2101.10025) names transfer of trained GCNs to other distribution networks as an open direction.

**Gap as far as this search shows:** zero-shot transfer of a fault locator from one IEEE feeder to another. This must be confirmed with a proper literature search (OpenAlex, IEEE Xplore) before anything calls it new.

## Feeders

| Role | Feeder | Files | Checked |
|---|---|---|---|
| Train | IEEE 123-bus, 4.16 kV | `data/feeder/ieee123/` (existing) | used by the whole study |
| Test, never trained on | IEEE 34-bus, 24.9 kV | `data/feeder/ieee34/` from the OpenDSS mirror [dss-extensions/electricdss-tst](https://github.com/dss-extensions/electricdss-tst) (`Version8/Distrib/IEEETestCases/34Bus`) | 2026-11-21: compiles, converges, 37 buses, 32 lines, 68 loads, about 2 MW, 6 regulators, 2 capacitors |
| Second unseen test (planned) | IEEE 37-bus, 4.8 kV (urban underground, 3-wire delta) | `data/feeder/ieee37/` (same mirror, `37Bus`); pre-registered plan in [`research/ieee37-underground/PLAN.md`](../ieee37-underground/PLAN.md) | not run yet |
| Optional third test | IEEE 8500-node | same mirror | not yet |

## Plan

### Phase 1: feeder-independent data

1. A feeder adapter. For each feeder, one config entry: master file, voltage bases, switch locations, ties.
2. Place sectionalizing switches on the 34-bus with the same rule used on 123-bus (written down before looking at any result). The rule is: one at the head, one at each main branch point.
3. Run the existing fault sweep on the 34-bus: same fault types, resistances, load scenarios and noise.
4. Store every event as a graph:
   - nodes = devices;
   - edges = zone tree;
   - label = the device whose zone holds the fault.
5. Node features:
   - fault/pre-fault current ratio per phase;
   - residual and negative-sequence ratios;
   - voltage in pu and voltage drop;
   - structural features: depth in the tree, share of downstream load.
   
   No absolute amperes and no device names.

### Phase 1 result (run 2026-11-21, `scripts/transfer_sweep.py`)

| Feeder | Devices | Fault events | Converged | Buses in zones | Buses with faults |
|---|---|---|---|---|---|
| IEEE 123 (train) | 10, the study's own | 11,448 (same count as the main study) | 11,448 | 127 | 127 |
| IEEE 34 (never trained on) | 7, from the placement rule | 4,104 | 4,104 | 35 | 35 |

The placement rule, written in `shf/transfer.py` before any model was trained, gave these switches on the 34-bus: head recloser l1, then l8 and l9 (split at 816), l32 (past the 24.9/4.16 kV transformer) and l16 (split at 832), and l17 and l18 (split at 834).

A spot check of one bolted 3-phase fault at bus 842 matched the physics: the incremental current is large on the devices along the source-to-fault path and small elsewhere (`tests/test_transfer.py`).

### Phase 2: models (all trained on 123-bus only)

- **FPI rule** (existing baseline). It transfers trivially and sets the floor.
- **Per-node gradient boosting** on the same node features plus parent/child aggregates. A strong non-GNN baseline: if it transfers as well as the GNN, the GNN is not needed.
- **GNN:** two or three message-passing layers over the zone tree, then a softmax over nodes. Plain PyTorch, CPU is enough (graphs of about 10 nodes).
- Validation: GroupKFold by fault bus on 123-bus, as now. Hyperparameters are chosen on 123-bus only.

### Phase 2 result (run 2026-11-21, `scripts/transfer_train.py`, IEEE 123-bus only, simulation only)

Source: `results/transfer/phase2_ieee123.json` (11,448 simulated fault events, 127 buses, 5-fold GroupKFold by bus, 15% random sensor dropout during training; IEEE 34-bus data was not touched).

| Model | Selected config (IEEE 123 CV) | Overall acc (fold std) | 3PH / LL / LLG / SLG | SLG 100 Ω / 200 Ω / 400 Ω | 1 sensor offline (mean / min) |
|---|---|---|---|---|---|
| FPI rule (graph relative pickup) | phase > 2.0×, 3\|dI0\| > 0.5× (no flag: 25.7%) | 55.5% (2.32%) | 87.4% / 95.2% / 47.9% / 44.6% | 18.4% / 2.5% / 0.0% | 50.7% / 48.3% |
| Per-node GBDT (`PerNodeGBDT`) | `max_iter=300, lr=0.1, max_leaf_nodes=31` | 98.3% (0.45%) | 100.0% / 100.0% / 100.0% / 97.3% | 99.6% / 97.7% / 78.2% | 89.4% / 84.4% |
| Zone-tree GNN (`ZoneTreeGNN`, CPU) | 2 layers, `hidden=64`, `dropout=0.1` (49,473 params) | 98.1% (0.41%) | 100.0% / 100.0% / 100.0% / 96.9% | 98.9% / 92.7% / 80.9% | 90.2% / 84.4% |

All configs tried on IEEE 123-bus GroupKFold (frozen before Phase 3):
- Per-node GBDT: `L31_lr0.10_i300` 98.31%, `L63_lr0.05_i300` 98.27%, `L31_lr0.05_i400` 98.26%.
- Zone-tree GNN: `2layer_h64` 98.09%, `3layer_h64` 98.05%, `3layer_h96` 98.03%, `2layer_h96` 97.97%.

Notes:
- The graph FPI rule uses the same `2.0` phase and `0.5` ground factors from `shf/config.py` on the relative graph features (`|I_post|/base` and `3*|dI0|/base`), so the exact same function runs on any unseen feeder in Phase 3 without raw amperes; its overall accuracy on IEEE 123-bus (55.5%) is close to the main study's fixed-pickup FPI (56.1% in `results/metrics.json`).
- On IEEE 123-bus itself, both feeder-independent models match the main study's feeder-specific classifier (97.7% in `results/metrics.json`). Per-node GBDT leads slightly overall (98.3% vs 98.1%) and at 200 Ω SLG (97.7% vs 92.7%); the 2-layer GNN leads at 400 Ω SLG (80.9% vs 78.2%) and with one sensor offline (90.2% vs 89.4% mean). Whether either transfers to the unseen IEEE 34-bus is unknown until Phase 3.
- Final models fit on all 11,448 IEEE 123-bus events with the frozen hyperparameters are saved locally in `models/transfer/` (git-ignored).

### Phase 2b: from zone to bus ("works for every bus")

The models above name the **zone**. Every bus already has faults in the data, and GroupKFold tests on buses the model never saw. The owner asked, on 2026-11-21, for the model to work for every bus, so a second stage names the **bus**:

1. Inside the predicted zone, rank its buses by how well each one explains the measurements at the zone's upstream device.
   - Apparent impedance V/I gives the reactance method.
   - Compare it with each bus's line impedance from that device, taken from the OpenDSS model of that feeder.
   - Also try a small graph model on the bus graph, with measurements only at devices.
2. Report top-1 and top-3 **bus** accuracy on both feeders, against the baseline of picking a bus of the zone at random.
3. **Expected limit, stated before any run:** with sensors only at zone boundaries, two buses at the same electrical distance on different laterals look the same. Top-3 is then the honest number to quote, and the error table shows which buses get confused.

### Phase 2b result (run 2026-11-21, `scripts/transfer_bus_stage.py`, both feeders, simulation only)

Source: `results/transfer/phase2b_bus_location.json`. Stage 1 provides the predicted zone (`PerNodeGBDT` 5-fold OOF on IEEE 123-bus: 98.3%; zero-shot from 123-bus on IEEE 34-bus: 99.8%). Stage 2 ranks buses inside that zone.

| Feeder (Stage-1 zone acc) | Stage-2 bus ranker | Top-1 bus acc | Top-3 bus acc | 3PH / LL / LLG / SLG (top-3) | SLG 0.01 / 1 / 100 / 400 Ω (top-3) |
|---|---|---|---|---|---|
| IEEE 123-bus (98.3% OOF) | Random bus in zone | 8.8% | 26.4% | 28.4% / 28.2% / 28.2% / 25.4% | 26.0% / 26.0% / 25.9% / 21.0% |
| IEEE 123-bus (98.3% OOF) | **Takagi reactance (OpenDSS 3×3 Z, zero training)** | **46.9%** | **69.0%** | 94.5% / 99.5% / 94.6% / 52.5% | 99.6% / 98.0% / 36.1% / 29.2% |
| IEEE 123-bus (98.3% OOF) | Bus-graph GNN (5-fold GroupKFold by bus) | 17.8% | 38.5% | 65.7% / 76.0% / 64.8% / 19.8% | 90.4% / 59.3% / 3.1% / 2.6% |
| IEEE 34-bus (99.8% zero-shot) | Random bus in zone | 19.3% | 50.8% | 49.9% / 49.9% / 49.9% / 51.5% | 51.6% / 51.6% / 51.6% / 50.7% |
| IEEE 34-bus (99.8% zero-shot) | **Takagi reactance (OpenDSS 3×3 Z, zero training)** | **57.5%** | **87.4%** | 92.6% / 92.6% / 93.7% / 83.4% | 93.3% / 93.3% / 73.0% / 62.2% |
| IEEE 34-bus (99.8% zero-shot) | Bus-graph GNN (zero-shot from 123-bus) | 50.8% | 85.8% | 88.9% / 87.4% / 88.9% / 84.1% | 91.0% / 91.0% / 78.3% / 67.4% |
| IEEE 34-bus (99.8% zero-shot) | Bus-graph GNN (in-domain 5-fold CV) | 14.8% | 59.2% | 72.8% / 70.1% / 71.6% / 50.8% | 79.4% / 79.4% / 33.3% / 24.7% |

Top confused bus pairs under Takagi reactance (confirming the pre-stated electrical-distance limit):
- **IEEE 123-bus:** `61→61s` (113, `ΔX1 = 0.000 Ω`), `160→160r` (67, `ΔX1 = 0.000 Ω`), `60→61s` (48, `0.065 Ω`), `82→83` (43, `0.030 Ω`), `51→151` (43, `0.059 Ω`).
- **IEEE 34-bus:** `852r→888` (115, `ΔX1 = 0.002 Ω`), `832→888` (112, `ΔX1 = 0.000 Ω`), `850→816` (108, `0.049 Ω`), `852→888` (104, `0.002 Ω`), `814→816` (100, `0.051 Ω`).

Notes:
- **Physics beats ML for Stage 2:** the 3-phase Takagi reactance method needs zero training, transfers directly to any feeder with an OpenDSS model, and reaches **69.0%** top-3 on IEEE 123-bus (vs 26.4% random; **94.5–99.5%** on multi-phase and bolted/1 Ω SLG) and **87.4%** top-3 on IEEE 34-bus (vs 50.8% random). Oracle-zone top-3 is nearly identical (69.5% on 123-bus, 87.6% on 34-bus), showing Stage-1 errors barely affect Stage 2.
- **Why `BusGraphGNN` underperforms under GroupKFold by bus (reported honestly as a failure to beat physics):** in GroupKFold by bus, held-out test buses appear in every training event as negative nodes and never as positive labels, so the network learns to suppress held-out bus positions (17.8% top-1 on 123-bus; 14.8% on 34-bus). When trained on all 127 buses of 123-bus and tested zero-shot on 34-bus (no held-out-bus bias), it reaches 50.8% top-1 / 85.8% top-3—still below pure Takagi reactance overall (57.5% / 87.4%), though slightly higher on 100–400 Ω SLG top-3 (78.3%/71.5%/67.4% vs 73.0%/68.2%/62.2%).
- On 4.16 kV IEEE 123-bus, Takagi reactance degrades sharply on SLG faults at `R >= 5 Ω` (top-3 drops from 98.0% at 1 Ω to 56.9% at 5 Ω and 29.2% at 400 Ω) because 1% magnitude / 0.5° angle CT/PT noise dominates the small reactive drop `X_line` compared to `R_f`. Simulation only; no field data.

### Phase 3: the transfer test

On the 34-bus, compare:

- zero-shot (trained on 123 only), against FPI;
- an in-domain upper bound (the same model trained on 34-bus with GroupKFold);
- few-shot: fine-tune on 5% and 20% of 34-bus buses, test on the others.

Report by fault type and resistance (0.01–400 Ω), and with one sensor missing.

### Phase 3 result (run 2026-11-21, `scripts/transfer_eval34.py`, IEEE 34-bus, simulation only)

Source: `results/transfer/phase3_ieee34.json` (4,104 simulated fault events, 35 buses, 7 devices `D1`–`D7` from `PLACEMENT_RULE`; hyperparameters frozen from `results/transfer/phase2_ieee123.json`).

| Setting & model | Zone acc | 3PH / LL / LLG / SLG | SLG 100 Ω / 200 Ω / 400 Ω | 1 sensor offline (mean / min) |
|---|---|---|---|---|
| FPI baseline (graph relative pickup) | 55.5% (no flag: 1.6%) | 72.8% / 81.9% / 33.5% / 52.4% | 57.7% / 91.8% / 93.3% | 49.0% / 40.8% |
| **Zero-shot Per-node GBDT** (123 → 34) | **99.8%** | 100.0% / 100.0% / 100.0% / 99.7% | 100.0% / 99.3% / 97.8% | 88.4% / 77.0% |
| **Zero-shot Zone-tree GNN** (123 → 34) | **99.3%** | 100.0% / 100.0% / 99.3% / 99.0% | 99.6% / 96.3% / 95.5% | 85.8% / 74.5% |
| In-domain upper bound GBDT (34-bus 5-fold CV) | 99.2% (std 0.97%) | 100.0% / 100.0% / 100.0% / 98.6% | 98.9% / 94.8% / 93.6% | 89.8% / 82.0% |
| In-domain upper bound GNN (34-bus 5-fold CV) | 98.3% (std 1.98%) | 100.0% / 100.0% / 100.0% / 97.1% | 93.3% / 93.3% / 93.3% | 91.5% / 86.0% |
| Few-shot 5% (2 train / 33 test buses, 10 splits) GBDT | 93.6% ± 10.0% | 92.7% / 93.5% / 94.0% / 93.7% | 96.3% / 95.5% / 93.0% | 78.6% / 64.1% |
| Few-shot 5% (2 train / 33 test buses, 10 splits) GNN | 98.9% ± 0.3% | 100.0% / 100.0% / 99.6% / 98.3% | 98.1% / 94.4% / 92.6% | 85.3% / 70.6% |
| Few-shot 20% (7 train / 28 test buses, 10 splits) GBDT | 96.4% ± 4.5% | 95.8% / 97.9% / 98.0% / 95.6% | 96.5% / 94.4% / 92.4% | 84.3% / 70.8% |
| Few-shot 20% (7 train / 28 test buses, 10 splits) GNN | 98.7% ± 0.8% | 100.0% / 100.0% / 100.0% / 97.9% | 96.7% / 93.3% / 92.0% | 88.3% / 71.0% |

Verdict against the pre-committed success criteria (below):
- **Main criterion met** for both models: zero-shot exceeds FPI by +44.4 points (GBDT: 99.8% vs 55.5%) and +43.9 points (GNN: 99.3% vs 55.5%), and even exceeds the 5-fold in-domain 34-bus CV (99.2% GBDT / 98.3% GNN), largely because 123-bus has 127 training buses vs 28 per fold on 34-bus (in-domain 34-bus CV struggles on 2-bus zone `D5`: 89.6% GBDT / 72.9% GNN vs 99.3% / 97.2% zero-shot).
- **Important physical caveat on why 99.8% / 99.3% is higher than on 123-bus (not leakage):** IEEE 34-bus runs at **24.9 kV**, IEEE 123-bus at **4.16 kV**. Measured with OpenDSS at nominal load (`scripts/signal_to_load.py` → `results/transfer/signal_to_load.json`, added 2026-11-21 to replace hand estimates that were here before): a 400 Ω ground fault draws a median 31.7 A on 34-bus, 61.1% of the 51.8 A feeder-head current, but 6.2 A on 123-bus, 1.0% of 631.5 A (near the 1% CT noise floor). That physical difference is directly visible in FPI itself: `no_device_flagged` drops from 25.7% on 123-bus to 1.6% on 34-bus, and FPI accuracy on 400 Ω SLG jumps from 0.0% to 93.3% (FPI still averages 55.5% overall because low-resistance faults trigger false flags on sibling/downstream devices).
- **Per-node GBDT vs GNN (answering the Phase 2 question):** for zero-shot zone classification on 34-bus, **Per-node GBDT transfers at least as well as the GNN** (99.8% vs 99.3% clean; 88.4% vs 85.8% with one sensor offline), so a GNN is not strictly required for clean zero-shot zone transfer here. With tiny few-shot fine-tuning (2–7 buses), warm-start GBDT overfits the few sampled zones (dropping to 93.6% ± 10.0% at 5%), whereas GNN fine-tuning remains stable (98.9% ± 0.3% at 5%, and improves missing-sensor mean from 85.8% to 88.3% at 20%). Simulation only; no field data.

### Phase 4: write-up

- A report section and README results. Every number goes in `harness/facts.toml`.
- The limits are stated plainly: two or three IEEE feeders, simulation only, no field data.

## What counts as success (fixed now, before any result)

1. **Main:** zero-shot zone accuracy on 34-bus is clearly above FPI on 34-bus, and within 10 points of the in-domain upper bound.
2. **Weaker but still useful:** zero-shot is above FPI, and few-shot with 5% of buses closes most of the gap.
3. **Failure, reported as such:** zero-shot is not above FPI. Then the finding is "per-unit features alone do not transfer", with the error breakdown.

## Guards against the old 99.9% leakage

- No 34-bus data in training or tuning for the zero-shot result.
- Hyperparameters are frozen before the 34-bus test runs once.
- The 34-bus switch placement follows the written rule and is not adjusted after seeing results.

## Needs

- PyTorch, CPU build (`torch==2.15.0+cpu`, installed in `.venv` and listed in `requirements.txt`).
- Running the 34-bus sweep: done in Phase 1 (`data/generated/transfer_ieee34.npz`, untouched in Phase 2).
- Simulation only. Nothing here touches a real feeder.
