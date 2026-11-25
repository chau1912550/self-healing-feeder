# Zero-shot fault location on active, reconfigurable distribution grids with inverter-based DER and conformal safety guarantees

Status: **Completed on 2026-11-21 on Kaggle GPU VM** (`scripts/active_grid_run.py`, `notebooks/kaggle_active_grid.ipynb`). The plan and pre-committed criteria below were fixed before the run; the "Results" section at the bottom reports the exact numbers from `results/active_grid/*.json`. Third-feeder extension on an urban underground 3-wire delta grid (IEEE 37-bus, 4.8 kV): [`research/ieee37-underground/PLAN.md`](../ieee37-underground/PLAN.md). Planned two-tier Edge HIF-Sensor → Graph FLISR extension targeting high-impedance 200–400 Ω SLG faults and 7 background disturbances: [`research/hif-fusion/PLAN.md`](../hif-fusion/PLAN.md) (pre-registered; not run yet).

## Why this next study is needed (gaps exposed by our Phase 1–3 study)

Our passive radial study (`research/gnn-transfer/PLAN.md`) showed that feeder-independent relative features transfer from IEEE 123-bus (4.16 kV) to IEEE 34-bus (24.9 kV), but exposed three limitations that prevent the passive study from solving the open challenges highlighted in recent IEEE PES literature (2024–2026):

1. **Passive radial flow was too easy for non-GNN baselines:** with unidirectional radial flow and a fixed parent-child tree, per-node GBDT matched or slightly exceeded our tree GNN (99.8% vs 99.3% zero-shot on 34-bus).
2. **Fault resistances were not scaled to feeder voltage:** `400 Ω` on 24.9 kV draws ~36 A (~78% of ~46 A nominal head load), whereas `400 Ω` on 4.16 kV draws only ~6 A (~1.2% of ~500 A head load). High-impedance faults (HIF) on 24.9 kV must extend to `1–10 kΩ` to test comparable physical signal-to-noise ratios.
   *Correction added 2026-11-21 after the run: the numbers in this item were hand estimates. Measured with OpenDSS at nominal load (`results/transfer/signal_to_load.json`), a 400 Ω fault draws a median 61.1% of the 51.8 A head current on 34-bus and 1.0% of 631.5 A on 123-bus, and even 10,000 Ω on 34-bus draws 2.9%, so the active 34-bus sweep stays easier than 400 Ω on 123-bus by this measure.*
3. **Real modern feeders break three passive assumptions simultaneously:**
   - **Inverter-based DERs (IBRs: solar PV / BESS)** limit fault current to ~1.1–1.3× rated current and inject bidirectional flow, desensitizing overcurrent protection and distorting impedance/directional signatures.
   - **Dynamic network reconfiguration (DNR) and looped (non-tree) operation** change which switches are closed and reverse power flow directions; fixed parent-child trees cannot represent closed loops or multi-source back-feeding.
   - **Operational non-fault transients** (capacitor bank switching, sudden PV cloud drops, large load steps) cause nuisance trips when protection is made sensitive enough for HIFs.
   - **Autonomous switching requires calibrated uncertainty:** utilities cannot hand breaker control to an overconfident black-box model without a finite-sample reliability guarantee.

## Research question

Can a **bidirectional, edge-aware Graph Attention Network (`ActiveGridGATv2`)** trained **only on IEEE 123-bus** (with 0–50% IBR/DER penetration, dynamic reconfiguration/looping, HIFs, and non-fault transients):
1. outperform both conventional FPI and per-node GBDT on **active, reconfigured, looped, and high-DER regimes**;
2. **transfer zero-shot** to an unseen higher-voltage feeder (**IEEE 34-bus, 24.9 kV**) with DER, reconfiguration/looping, voltage-normalized HIFs up to `10 kΩ`, and non-fault distractors; and
3. provide **finite-sample safety guarantees via Split Conformal Prediction** (separating safe autonomous single-zone switching from multi-zone operator deferral)?

## Active-grid benchmark design (fixed before running; all marked ASSUMPTION)

All simulations run in OpenDSS on **Kaggle cloud VMs** (GPU for PyTorch training, offline Linux OpenDSS wheels). Simulation only; no field data.

### 1. Inverter-Based DERs (`Generator Model=7`, current-limited)
- **ASSUMPTION:** Distributed 3-phase inverter-based DERs are modeled with OpenDSS `Generator Model=7` (current-limited inverter ceiling, `pf=1.0`, `vminpu=0.8`, `vmaxpu=1.15`).
- **IEEE 123-bus (4.16 kV, nominal load ~3,490 kW):** 4 DER buses spread across distinct zones (`48`, `65`, `76`, `105`).
- **IEEE 34-bus (24.9 kV, nominal load ~2,000 kW):** 3 DER buses spread across distinct zones (`822`/`824` → 3-phase trunk buses `828`, `844`, `840`).
- For each simulated event, feeder-wide DER penetration is sampled uniformly in `[0%, 50%]` of nominal feeder load, with per-DER random irradiance spread `N(1, 0.25)` clipped to `[0.1, 1.5]`.

### 2. Dynamic topologies (radial, reconfigured back-feed, and closed loop)
Every event carries the **live active graph** (edges between zones connected by currently closed switches; open switches have no active edge):
- **IEEE 123-bus (4 topologies):**
  1. `normal`: all 10 sectionalizers closed; ties `Sw7`, `Sw9` open.
  2. `reconfig_sw7`: `Sw2` open, `Sw7` closed (right trunk back-fed via `L45–Sw7`, reversing flow).
  3. `reconfig_sw9`: `Sw4` open, `Sw9` closed (two-source split feeder: tail back-fed from `fdr2`).
  4. `looped_sw7`: all 10 sectionalizers + `Sw7` closed (closed-loop ring — not a tree).
- **IEEE 34-bus (3 topologies, ASSUMPTION: adjacent 24.9 kV tie `Tie34` from bus `840` to `adj34`):**
  1. `normal`: all 7 devices closed; `Tie34` open.
  2. `reconfig_tie`: `D4` (`l16`) open, `Tie34` closed (two-source split feeder: tail back-fed via `Tie34`).
  3. `looped_tie`: all 7 devices + `Tie34` closed (two-source closed loop — not a tree).

### 3. Voltage-normalized fault resistances and non-fault distractors (`NO_FAULT`)
- **IEEE 123-bus (4.16 kV):** SLG `R ∈ {0.01, 1, 5, 10, 25, 50, 100, 200, 400} Ω`; phase faults `R ∈ {0.01, 0.5, 2} Ω`.
- **IEEE 34-bus (24.9 kV):** SLG `R ∈ {0.01, 5, 25, 100, 400, 1000, 2500, 5000, 10000} Ω` (spanning up to ~32 pu of `Z_base ≈ 310 Ω`, so `10 kΩ` draws ~1.44 A ≈ 3% of head load); phase faults `R ∈ {0.01, 2, 10} Ω`.
- **Non-fault operational transients (`class = NO_FAULT`, ~15% of total events on each feeder):**
  1. **Capacitor switching:** toggle an existing feeder capacitor (`c83, c88a, c90b, c92c` on 123-bus; `c844, c848` on 34-bus) ON or OFF between pre- and post-event snapshots.
  2. **PV cloud transient:** sudden 50–85% drop (or recovery) in DER output between pre and post.
  3. **Large load step:** sudden 30–80% jump in 1–4 spot loads between pre and post.

### 4. Feeder-independent graph representation (general graphs, no tree assumption)
- **Node features (26 dims per device):**
  - 14 incremental/post currents & voltages (`dIa..dIc, Ia..Ic, dI0, dI2, Va..Vc, dVa..dVc`) normalized relative to pre-fault base (no absolute A or kV).
  - 3 phase-presence flags (`has_a, has_b, has_c`).
  - 4 **directional phasor-angle features** (crucial for bidirectional DER & reconfigured flows): real-power direction `cos(∠I_post - ∠V_post)` averaged across present phases, pre-fault flow direction `cos(∠I_pre - ∠V_pre)`, fault-increment direction `cos(∠dI - ∠V_pre)` on dominant fault phase, and sign of real-power reversal `sign_change`.
  - 5 local structural/operating features (valid on general graphs with loops): `is_closed` (0/1), `active_degree` (number of incident closed zone links), `share_own` (nominal zone load fraction), `der_ratio` (local pre-fault DER kW / zone nominal load, capped), `is_source_adj` (1 if device feeds directly from an active substation/tie source).
- **Directed edge features (4 dims per active link `u → v`):**
  - `is_tie_link` (1 for tie switch connection, 0 for normal sectionalizer adjacency),
  - `same_flow_dir` (`1` if `u` and `v` carry pre-fault flow in same direction, `-1` if opposing),
  - `diff_dI_max` (`max(dI_u) - max(dI_v)`),
  - `diff_V_min` (`min(V_u) - min(V_v)`).

## Models compared (all trained on IEEE 123-bus ONLY; GroupKFold by bus)

1. **Conventional FPI (`active_fpi`):** same `2.0×` phase / `0.5×` ground pickup rule; predicts `NO_FAULT` if no device flags, otherwise picks the flagged closed device with largest `dI` drop to neighbors (generalizes deepest-flagged to reconfigured/looped graphs).
2. **Per-node GBDT + Graph `NO_FAULT` (`ActivePerNodeGBDT`):** `HistGradientBoostingClassifier` on each node's 26 features + active-graph 1-hop neighbor aggregates (max, mean, min, self − max_neighbor, self − min_neighbor), plus a companion graph-level GBDT for `NO_FAULT` vs `FAULT` (producing calibrated `N + 1` probabilities for conformal sets too).
3. **Bidirectional Edge-Aware GATv2 (`ActiveGridGATv2`, plain PyTorch on Kaggle GPU):** 3-layer GATv2 with edge-feature conditioning, dual attention + max neighbor aggregation, residual + LayerNorm, and a joint `(N + 1)`-way softmax over the `N` zone nodes plus a global-pooled `NO_FAULT` node. Handles arbitrary node counts, open switches, reversed flows, and cycles/loops natively.

## Split Conformal Prediction (Step 2, built into the same pipeline)

Using **Adaptive Prediction Sets (APS)** at target coverage `1 - α ∈ {0.90, 0.95}`:
- **In-domain (IEEE 123-bus):** cross-conformal / bus-disjoint calibration split (zero bus overlap between train, calibration, and test).
- **Zero-shot (IEEE 34-bus):** threshold `q̂` frozen from IEEE 123-bus calibration, evaluated on IEEE 34-bus; also compare with **5%-bus recalibration** on IEEE 34-bus (2 buses + small sample of normal transients to recalibrate `q̂` without retraining any model weights!).
- Metrics reported: empirical coverage, average prediction set size, **autonomous share** (`|C(x)| == 1`), **accuracy on autonomous single-zone decisions**, and **False Positive Rate on `NO_FAULT`**.

## Pre-committed success criteria (fixed before any run)

1. **C1 — Problem genuinely breaks legacy protection:** On active IEEE 123-bus and 34-bus (DER + reconfig/loop + voltage-scaled HIF + `NO_FAULT`), FPI overall accuracy drops clearly below 55% or exhibits >15% false-positive rate on non-fault transients.
2. **C2 — Zero-shot transfer & GNN value:** Trained ONLY on IEEE 123-bus, `ActiveGridGATv2` transfers zero-shot to active IEEE 34-bus with:
   - overall accuracy at least **+25 points above FPI**,
   - False Positive Rate on `NO_FAULT` **≤ 5%**,
   - and **outperforms `ActivePerNodeGBDT`** on the hard regimes (reconfigured/looped topologies, high DER ≥ 30%, or high-R HIF ≥ 1 kΩ / missing sensor).
   - *Failure/honest alternative:* if `ActivePerNodeGBDT` still matches or beats `ActiveGridGATv2` across all regimes even on looped/DER grids, report that honestly as the finding.
3. **C3 — Conformal safety guarantee:** At `1 - α = 0.95`, APS achieves ≥ 93% empirical coverage on IEEE 123-bus and ≥ 94% on IEEE 34-bus after 5%-bus threshold recalibration (with zero weight retraining), while achieving higher accuracy on autonomous (`|C| = 1`) decisions than raw argmax.

## Guards against leakage

- IEEE 34-bus is never used for training or hyperparameter selection.
- All IEEE 123-bus validation and calibration splits are strictly grouped by **bus** (`NO_FAULT` events split cleanly across folds).
- Every result file in `results/active_grid/` is produced by a script on Kaggle and recorded with `shf.provenance.record()`. Never edit result files by hand.

---

## Results (run 2026-11-21 on Kaggle GPU VM, `scripts/active_grid_run.py`, simulation only)

Sources: `results/active_grid/dataset_summary.json`, `results/active_grid/phase_active_ieee123.json`, `results/active_grid/phase_active_ieee34.json`, `results/active_grid/conformal_safety.json` (provenance: `results/provenance/active_grid.json`).

### 1. Active-grid datasets generated in OpenDSS

| Feeder | Topologies | DER buses (`Model=7`, 0–50%) | SLG resistance range | Converged events (share) | Fault events | `NO_FAULT` transients (cap / PV cloud / load step) |
|---|---|---|---|---|---|---|
| IEEE 123-bus (4.16 kV, train) | `normal`, `reconfig_sw7`, `reconfig_sw9`, `looped_sw7` | `48, 65, 76, 105` | `0.01–400 Ω` | 17,847 / 17,956 (99.39%) | 15,155 | 2,692 (900 / 896 / 896) |
| IEEE 34-bus (24.9 kV, unseen test) | `normal`, `reconfig_tie`, `looped_tie` | `828, 844, 840` | `0.01–10,000 Ω` | 9,491 / 9,657 (98.28%) | 8,042 | 1,449 (483 / 483 / 483) |

### 2. Active IEEE 123-bus (5-fold GroupKFold by bus, in-domain training & selection)

| Model | Selected config | Overall acc (fold std) | Fault-zone acc | `NO_FAULT` FPR (nuisance trip) | Reconfig + loop acc | Closed-loop acc (`looped_sw7`) | High DER (30–50%) fault acc | 1 sensor offline (mean / min) |
|---|---|---|---|---|---|---|---|---|
| FPI (`active_fpi`) | phase > 2.0×, 3\|dI0\| > 0.5× | 40.7% (1.05%) | 33.9% | 21.2% | 37.3% | 29.5% | 33.0% | 39.0% / 36.9% |
| `ActivePerNodeGBDT` | `max_iter=300, lr=0.05, leaves=63` | 93.9% (1.26%) | 95.3% | 13.9% | 93.0% | 92.9% | 95.7% | 86.1% / 83.6% |
| **`ActiveGridGATv2` (GPU)** | 2 layers, `hidden=64, heads=4` (62,786 params) | **95.8%** (1.00%) | **96.2%** | **6.5%** | **94.9%** | **94.7%** | **96.7%** | **89.1% / 87.0%** |

All configs evaluated on IEEE 123-bus 5-fold GroupKFold (frozen before IEEE 34-bus evaluation):
- `ActivePerNodeGBDT`: `L63_lr0.05_i300` 93.93% (FPR 13.89%, miss 86.07%), `L31_lr0.10_i300` 93.91% (FPR 13.63%, miss 85.89%).
- `ActiveGridGATv2`: `2L_h64` 95.78% (FPR 6.46%, loop 94.72%, miss 89.14%), `3L_h96` 95.76% (FPR 6.54%, loop 94.68%, miss 89.76%), `3L_h64` 95.69% (FPR 6.58%, loop 95.01%, miss 89.48%).

### 3. Unseen Active IEEE 34-bus transfer test (24.9 kV, DER 0–50%, `reconfig_tie` & `looped_tie`, SLG up to `10,000 Ω`)

| Setting & model | Overall acc | Fault-zone acc | `NO_FAULT` FPR | Closed-loop (`looped_tie`) | SLG 400 Ω / 2.5 kΩ / 10 kΩ | 1 sensor offline (mean / min) |
|---|---|---|---|---|---|---|
| FPI baseline (`active_fpi`) | 47.6% | 40.0% | 10.2% | 31.5% | 63.7% / 22.5% / 1.9% | 44.2% / 39.4% |
| **Zero-shot `ActivePerNodeGBDT`** (123 → 34) | **83.8%** | **84.9%** | 22.1% | **74.1%** | 84.8% / 72.3% / 66.5% | **72.4%** / 56.9% |
| **Zero-shot `ActiveGridGATv2`** (123 → 34) | 77.6% | 78.2% | 25.3% | 66.5% | 81.8% / 68.9% / 52.1% | 71.5% / **63.9%** |
| Few-shot 5% (2 buses + 72 non-faults, 5 splits) GBDT | 79.5% ± 3.1% | — | 15.5% | — | — | 68.4% / — |
| Few-shot 5% (2 buses + 72 non-faults, 5 splits) GATv2 | 77.0% ± 6.2% | — | **12.6%** | — | — | **68.9%** / — |
| **Few-shot 20% (7 buses + 290 non-faults, 5 splits) GBDT** | 83.1% ± 5.1% | — | 13.9% | — | — | 73.4% / — |
| **Few-shot 20% (7 buses + 290 non-faults, 5 splits) GATv2** | **89.1% ± 2.0%** | — | **11.0%** | — | — | **80.4%** / — |
| In-domain upper bound GBDT (34-bus 5-fold CV) | 91.8% (std 2.17%) | 94.1% | 20.9% | 88.9% | 93.5% / 87.3% / 72.1% | 83.6% / 71.8% |
| **In-domain upper bound GATv2 (34-bus 5-fold CV)** | **93.1% (std 1.93%)** | **94.2%** | **13.3%** | **90.0%** | **94.4% / 87.8% / 68.7%** | **86.3% / 77.0%** |

### 4. Split Conformal Prediction (APS at 95% target coverage, `α = 0.05`)

| Feeder & calibration regime | Model | Empirical coverage | Avg set size `\|C\|` | Autonomous share (`\|C\|=1`) | **Autonomous accuracy** (vs raw argmax) | **Autonomous `NO_FAULT` FPR** (vs raw FPR) |
|---|---|---|---|---|---|---|
| IEEE 123-bus (bus-disjoint 5-fold CV) | `ActivePerNodeGBDT` | 100.0% | 4.26 | 6.3% | **100.0%** (vs 93.9%) | **0.0%** (vs 13.9%) |
| IEEE 123-bus (bus-disjoint 5-fold CV) | **`ActiveGridGATv2`** | **100.0%** | 6.37 | **22.6%** | **100.0%** (vs 95.8%) | **0.0%** (vs 6.5%) |
| IEEE 34-bus (zero-shot `q̂` from 123-bus) | `ActivePerNodeGBDT` | 99.9% | 4.17 | 21.8% | **100.0%** (vs 83.8%) | **0.0%** (vs 22.1%) |
| IEEE 34-bus (zero-shot `q̂` from 123-bus) | **`ActiveGridGATv2`** | **99.9%** | 5.53 | 18.6% | **99.7%** (vs 77.6%) | **0.0%** (vs 25.3%) |
| IEEE 34-bus (5%-bus `q̂` recal, no weight retrain) | `ActivePerNodeGBDT` | 100.0% | 4.64 | 4.4% | **100.0%** (vs 83.8%) | **0.0%** (vs 22.1%) |
| IEEE 34-bus (5%-bus `q̂` recal, no weight retrain) | **`ActiveGridGATv2`** | **99.9%** | 5.53 | **18.6%** | **99.7%** (vs 77.6%) | **0.0%** (vs 25.3%) |

### 5. Honest verdict against pre-committed criteria (`C1`, `C2`, `C3`)

1. **C1 (Active grid breaks legacy FPI) — MET:** FPI drops to **40.7%** on active 123-bus (`29.5%` on closed loops, `21.2%` false-trip rate on non-faults) and **47.6%** on active 34-bus (`31.5%` on closed loops, `1.9%` at 10 kΩ SLG).
2. **C2 (Zero-shot transfer & GNN vs GBDT) — PARTIALLY MET (reported with full breakdown):**
   - `ActiveGridGATv2` beats FPI by **+30.1 points** zero-shot on active 34-bus (`77.6%` vs `47.6%`, meeting the `≥ +25 points` criterion).
   - **Where `ActiveGridGATv2` beats `ActivePerNodeGBDT`:** in-domain on active 123-bus (`95.8% vs 93.9%`, cuts false trips in half `6.5% vs 13.9%`, `+3.1` points with a missing sensor), in-domain on active 34-bus (`93.1% vs 91.8%`, `13.3% vs 20.9%` FPR, `+2.8` points with a missing sensor), and at **20% few-shot on active 34-bus (`89.1% ± 2.0%` vs `83.1% ± 5.1%`, `+7.0` points with a missing sensor)**.
   - **Where `ActiveGridGATv2` falls short of C2 in pure 0-shot:** in pure 0-shot on 34-bus, `ActivePerNodeGBDT` scores higher (`83.8%` vs `77.6%`, looped `74.1%` vs `66.5%`), and both models exceed the `≤ 5%` zero-shot `NO_FAULT` FPR target (`22.1%` GBDT, `25.3%` GATv2). The error breakdown shows why: both models reject capacitor switching (`99.6%` GBDT / `99.4%` GATv2) and PV cloud drops (`99.4%` / `86.3%`), but confuse sudden **+30–80% spot-load steps** (`34.8%` / `38.3%` correct) with `2.5–10 kΩ` HIFs because both produce a ~1–5% incremental current change.
3. **C3 (Conformal safety guarantee) — MET as written, but degenerate (see Addendum A and its results below):** Split Conformal APS at `1 - α = 0.95` achieves **100.0%** coverage on 123-bus and **99.9%** coverage on 34-bus (both zero-shot and 5%-bus recalibrated). Crucially, restricting autonomous breaker action to `|C(x)| = 1` lifts 34-bus zero-shot accuracy from **77.6% → 99.7%** (GATv2) and **83.8% → 100.0%** (GBDT) while driving **autonomous false-positive trips on `NO_FAULT` transients to `0.0%`** on both feeders. Simulation only; no field data.

---

## Addendum A (written 2026-11-21, BEFORE the post-hoc run): the pre-registered APS result is degenerate

**What an audit of `results/active_grid/conformal_safety.json` shows (no new run needed):**

- The calibrated APS threshold is `q̂ = 1.0` for `ActiveGridGATv2` and `q̂ ≈ 0.9998` for `ActivePerNodeGBDT`.
- Average set size is 6.37 of 11 labels (123-bus, GATv2) and 5.53 of 8 labels (34-bus, GATv2); 77–96% of events get a set with two or more labels and are deferred.
- For GATv2 the 90% and 95% targets give *identical* sets, and coverage (99.9–100%) sits far above either target.

**Why:** the pre-registered score is the deterministic APS score `S(x, y) = Σ_{j: p_j ≥ p_y} p_j`. For a correct, confident prediction that score equals `p_max`, which the softmax saturates at ≈ 1.0. Because more than 95% of calibration events are classified correctly, the 95% (and 90%) quantile of the scores is ≈ 1.0, so the set keeps every label until the cumulative probability reaches 1. A singleton set then happens only when `p_max` rounds to 1.0, so "act when `|C| = 1`" behaves like a "probability ≈ 1" gate, not like a calibrated 95% set. C3 is still met *as written* (coverage ≥ 93/94% and higher autonomous accuracy), but the coverage number is close to trivial and must not be presented as a strong guarantee.

**Pre-stated post-hoc analysis (deviation from the plan, reported as such):**

1. Re-run `scripts/active_grid_run.py` unchanged on the Kaggle GPU VM, except that it also saves the out-of-fold IEEE 123-bus probabilities and the zero-shot IEEE 34-bus probabilities to `data/generated/active_probs.npz` (git-ignored). GPU training is not bit-reproducible, so the main tables may move in the last digit; all prose will be re-read from the new results.
2. `scripts/active_conformal_posthoc.py` reads those probabilities and compares three nonconformity scores on exactly the same splits as the pre-registered analysis:
   - `aps_det`: the pre-registered deterministic APS (reproduces `conformal_safety.json`);
   - `lac`: least-ambiguous classifier, `S = 1 − p_y`, set `{y : p_y ≥ 1 − q̂}` (Sadinle, Lei & Wasserman 2019);
   - `aps_rand`: randomized APS, `S = Σ_{p_j > p_y} p_j + U·p_y`, `U ~ Uniform(0, 1)` (Romano, Sesia & Candès 2020, the original form).
3. For each score, target `1 − α ∈ {0.90, 0.95}`, model and regime (123-bus bus-disjoint cross-conformal; 34-bus with `q̂` from 123-bus; 34-bus recalibrated on 5% of buses, 10 repeats), report: coverage overall, coverage on fault events and on `NO_FAULT` events, average set size, share of empty sets, share of singletons, accuracy on singletons, and the share of **all** `NO_FAULT` events that would cause an autonomous trip (singleton with a fault label).
4. **Pre-stated reading rules:**
   - A score is "non-degenerate" if its 90% and 95% sets differ and its 123-bus coverage is within 3 points of the target.
   - The 34-bus zero-shot `q̂` carries **no** guarantee (123-bus calibration data are not exchangeable with 34-bus test data); only the recalibrated regime is read against the target, and with only 2 calibration fault buses its coverage is expected to vary.
   - Whichever score wins, the claim stays: simulation only, a decision-support gate, not a protection guarantee.

## Addendum A results (post-hoc run, 2026-11-21, Kaggle GPU, simulation only)

Run: `notebooks/kaggle_active_grid.ipynb` version 2 (`scripts/active_grid_run.py` unchanged except that it now saves `data/generated/active_probs.npz`, then `scripts/active_conformal_posthoc.py`). Files: `results/active_grid/conformal_posthoc.json`, run records `results/provenance/active_grid.json` and `active_conformal_posthoc.json`.

- **The re-run reproduced the first run exactly:** every number in `dataset_summary.json`, `phase_active_ieee123.json`, `phase_active_ieee34.json` and `conformal_safety.json` is identical; only run times differ (total 1409.0 s vs 1320.7 s). `aps_det` in the post-hoc script reproduces the pre-registered numbers (`aps_det_reproduces_preregistered: true`).
- Table: 95% target. 123-bus = bus-disjoint cross-conformal; 34-bus "123 q" = threshold from 123-bus applied to 34-bus (no guarantee); 34-bus recal = threshold from 2 fault buses + 72 `NO_FAULT` events of 34-bus, 10 draws, mean (min–max).

| Model | Score | Non-degenerate (pre-stated rule) | 123 coverage | Labels per set | One-label sets | Right on one-label sets | `NO_FAULT` events that would trip | 34 coverage, 123 q | 34 coverage, recal |
|---|---|---|---|---|---|---|---|---|---|
| ActiveGridGATv2 | `aps_det` | no | 100.0% | 6.37 | 22.6% | 100.0% | 0.0% | 99.9% | 99.9% (99.9%–99.9%) |
| ActiveGridGATv2 | `lac` | yes | 95.0% | 0.98 | 98.0% | 96.9% | 4.6% | 76.2% | 91.2% (77.6%–98.5%) |
| ActiveGridGATv2 | `aps_rand` | yes | 95.0% | 1.09 | 89.2% | 99.1% | 1.1% | 81.4% | 92.0% (81.5%–98.5%) |
| Per-node GBDT | `aps_det` | no | 100.0% | 4.26 | 6.3% | 100.0% | 0.0% | 99.9% | 100.0% (100.0%–100.0%) |
| Per-node GBDT | `lac` | yes | 95.0% | 1.03 | 96.5% | 95.5% | 10.7% | 86.3% | 92.2% (86.1%–97.9%) |
| Per-node GBDT | `aps_rand` | yes | 95.0% | 1.28 | 82.2% | 99.2% | 0.9% | 91.1% | 94.2% (91.3%–97.4%) |

**Reading (by the rules stated before the run):**

1. `aps_det` is degenerate for both models, as Addendum A expected. `lac` and `aps_rand` are non-degenerate: on 123-bus they land on the target (94.97–95.02% at 95%) with about one label per set.
2. Between the two, `aps_rand` is the safer gate: its one-label sets are right 99.1% (GATv2) / 99.2% (GBDT) of the time and 1.1% / 0.9% of non-fault events would trip, against 96.9% / 95.5% and 4.6% / 10.7% for `lac`.
3. **On the unseen 34-bus feeder no score keeps the 95% target.** With the 123-bus threshold, `aps_rand` covers 81.4% (GATv2) and 91.1% (GBDT); `lac` 76.2% and 86.3%. Recalibrating on 2 fault buses brings `aps_rand` to 92.0% and 94.2% on average, with single draws as low as 81.5% and 91.3%. The conformal guarantee assumes calibration and test data are exchangeable; across feeders they are not, and 2 buses are too few to recalibrate reliably.
4. Claim that survives: on the feeder it is calibrated on, a randomized-APS set gives a usable "act / defer" gate in simulation (95.0% coverage, one label for 89.2% of events). It is not a transferable safety guarantee, and nothing here is a protection guarantee.

---

## Addendum B (written 2026-11-21 evening, BEFORE any of these runs): two follow-up questions

Both follow from the Addendum A results and the signal-to-load measurement (`results/transfer/signal_to_load.json`). Simulation only.

### B1. How many buses of a new feeder does conformal recalibration need?

- **Data:** the saved probabilities `data/generated/active_probs.npz` from the Kaggle run (frozen 123-bus models applied zero-shot to active 34-bus). No retraining; runs locally in seconds (`scripts/active_conformal_calsize.py` → `results/active_grid/conformal_calsize.json`).
- **Score:** randomized APS (`aps_rand`, chosen in Addendum A because its one-label sets were the most accurate), same uniform seed. Models: ActiveGridGATv2 and Per-node GBDT. Target 95%.
- **Calibration sizes:** 5%, 10%, 20%, 30%, 40% of the 34-bus fault buses (and the same share of its `NO_FAULT` events); 50 random draws per size (seed 0); test on everything else.
- **Reported:** coverage mean, 10th percentile and minimum over draws; set size; one-label share and accuracy; share of `NO_FAULT` events that would trip.
- **Pre-stated criterion:** the smallest size whose mean coverage is ≥ 94.5% **and** whose 10th-percentile coverage is ≥ 92.0%. If no size meets it, report that recalibration on up to 40% of buses is not enough.

### B2. Does zero-shot transfer survive a 34-bus sweep as hard as 400 Ω on 123-bus?

- **Step 1 (physics, not a model result):** extend `scripts/signal_to_load.py` to 20, 25, 30 and 40 kΩ on 34-bus. Pre-stated rule: `R*` is the smallest of these whose median fault current share of the head current is ≤ the 123-bus 400 Ω share (1.0%, `results/transfer/signal_to_load.json`).
- **Step 2 (Kaggle GPU):** re-run the full active study with the 34-bus SLG resistances extended by 20 kΩ and `R*` (all other settings, seeds, hyperparameter grids and selection rules unchanged). Outputs go to a separate folder `results/active_grid_hard34/` with its own run record, so the main results stay as they are.
- **Reported:** zero-shot, 20% few-shot and in-domain accuracy for FPI, Per-node GBDT and ActiveGridGATv2 on the harder 34-bus set; accuracy per SLG resistance; `NO_FAULT` false-trip rate.
- **Pre-stated reading:** (a) compare zero-shot accuracy on SLG faults at `R*` with the 123-bus cross-validated accuracy at 400 Ω for the same model; "transfer survives" if the gap is ≤ 10 points, "degrades" if 10–25 points, "fails" if > 25 points. (b) Report whether GATv2 or GBDT is higher in zero-shot, whichever way it comes out.

### Addendum B1 results (2026-11-21, local, from the saved Kaggle probabilities)

File: `results/active_grid/conformal_calsize.json` (run record `results/provenance/active_conformal_calsize.json`). Randomized APS, 95% target, 50 draws per share, IEEE 34-bus has 35 fault buses.

| Model | Calibration share of 34-bus | Coverage mean | 10th percentile | Worst draw | Labels per set | One-label sets | Right on one-label sets | Meets criterion |
|---|---|---|---|---|---|---|---|---|
| ActiveGridGATv2 | 5% (2 buses) | 89.3% | 81.2% | 78.8% | 1.92 | 62.4% | 93.7% | no |
| ActiveGridGATv2 | 10% (4 buses) | 93.5% | 84.7% | 80.3% | 2.23 | 57.2% | 95.7% | no |
| ActiveGridGATv2 | 20% (7 buses) | 94.2% | 87.2% | 84.3% | 2.23 | 57.3% | 96.0% | no |
| ActiveGridGATv2 | 30% (10 buses) | 93.2% | 86.1% | 83.8% | 2.15 | 58.1% | 95.4% | no |
| ActiveGridGATv2 | 40% (14 buses) | 94.5% | 90.1% | 87.5% | 2.24 | 56.3% | 96.1% | no |
| Per-node GBDT | 5% (2 buses) | 93.0% | 89.5% | 88.9% | 1.69 | 65.9% | 97.7% | no |
| Per-node GBDT | 10% (4 buses) | 95.0% | 91.0% | 89.3% | 1.82 | 64.1% | 98.4% | no |
| Per-node GBDT | 20% (7 buses) | 95.1% | 91.7% | 90.6% | 1.80 | 64.5% | 98.5% | no |
| Per-node GBDT | 30% (10 buses) | 94.5% | 92.4% | 89.0% | 1.75 | 65.1% | 98.2% | yes |
| Per-node GBDT | 40% (14 buses) | 95.2% | 92.6% | 91.6% | 1.77 | 65.0% | 98.5% | yes |

**Reading (pre-stated criterion: mean ≥ 94.5% and 10th percentile ≥ 92.0%):** Per-node GBDT first meets it at 30% of the 34-bus fault buses. ActiveGridGATv2 does **not** meet it at any share up to 40%: its mean reaches 94.5% at 40% (just under 94.5% before rounding), but one draw in ten still falls below 90.1%. Coverage varies a lot between draws because events from the same bus are alike, so which buses land in the calibration set matters. In this simulation a conformal guarantee on a new feeder needs labelled faults from roughly a third of its buses, which is the field data this project does not have.
