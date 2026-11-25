# Two-tier Edge HIF-Sensor → Graph FLISR for High-Impedance Faults (200–400 Ω and full range)

Status: **Completed on Kaggle GPU on 2026-11-24 — ALL 4 PRE-REGISTERED CRITERIA `H1–H4` PASSED** (executed via `notebooks/kaggle_hif_fusion.ipynb` on Kaggle CUDA GPU using the frozen `504-byte` `model_int8.npz` from `christoopherchau/ch-y-n`, SHA-256 `3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1`; results imported into `results/hif_fusion/` with `0` changed / `0` missing SHA-256 provenance). Simulation only; no field data.

Related study plans:
- Passive cross-feeder transfer (IEEE 123-bus → IEEE 34-bus) and Stage-2 bus ranking: [`research/gnn-transfer/PLAN.md`](../gnn-transfer/PLAN.md)
- Active, reconfigurable grid transfer + Split Conformal Prediction (IEEE 123-bus → IEEE 34-bus): [`research/active-grid-gnn/PLAN.md`](../active-grid-gnn/PLAN.md)
- Third unseen feeder (urban underground 3-wire delta IEEE 37-bus, 4.8 kV): [`research/ieee37-underground/PLAN.md`](../ieee37-underground/PLAN.md)

---

## 1. Motivation: why 60 Hz phasors alone hit a physical ceiling at 200–400 Ω

Across all prior phases of `self-healing-feeder`, high-impedance single-line-to-ground (SLG) faults on the 4.16 kV IEEE 123-bus feeder are the single dominant error source:

| Prior study & model (60 Hz phasors only) | Source (`results/`) | Overall acc | SLG `200 Ω` | SLG `400 Ω` | `NO_FAULT` FPR | 1 sensor offline (mean) |
|---|---|---:|---:|---:|---:|---:|
| Main study — FPI baseline | `results/metrics.json` | `56.1%` | `2.3%` | `1.0%` | — | — |
| Main study — ML full (feeder-specific GBDT) | `results/metrics.json` | `97.7%` | `93.7%` | `76.5%` | — | `89.0%` (`83.2%–95.5%`) |
| Passive 123-bus CV — `PerNodeGBDT` (21 feat) | `results/transfer/phase2_ieee123.json` | `98.3%` | `97.7%` | `78.2%` | — | `89.4%` |
| Passive 123-bus CV — `ZoneTreeGNN` (21 feat) | `results/transfer/phase2_ieee123.json` | `98.1%` | `92.7%` | `80.9%` | — | `90.2%` |
| Passive 34-bus 0-shot — `PerNodeGBDT` | `results/transfer/phase3_ieee34.json` | `99.8%` | `99.3%` | `97.8%` | — | `88.4%` |
| Passive 34-bus 0-shot — `ZoneTreeGNN` | `results/transfer/phase3_ieee34.json` | `99.3%` | `96.3%` | `95.5%` | — | `85.8%` |
| Active 123-bus CV — `ActivePerNodeGBDT` (26 feat) | `results/active_grid/phase_active_ieee123.json` | `93.9%` | `87.9%` | `72.6%` | `13.9%` | `86.1%` |
| Active 123-bus CV — `ActiveGridGATv2` (26 feat) | `results/active_grid/phase_active_ieee123.json` | `95.8%` | `90.9%` | `73.5%` | `6.5%` | `89.1%` |
| Active 34-bus 0-shot — `ActivePerNodeGBDT` | `results/active_grid/phase_active_ieee34.json` | `83.8%` | — | `84.8%` (`2.5 kΩ`: `72.3%`, `10 kΩ`: `66.5%`) | `22.1%` | `72.4%` |
| Active 34-bus 0-shot — `ActiveGridGATv2` | `results/active_grid/phase_active_ieee34.json` | `77.6%` | — | `81.8%` (`2.5 kΩ`: `68.9%`, `10 kΩ`: `52.1%`) | `25.3%` | `71.5%` |

Error analysis (`results/error_analysis/error_analysis.json`) shows that **237 of all 259 errors (91.5%)** in the main IEEE 123-bus study occur on SLG faults at `200 Ω` or `400 Ω`. OpenDSS physics (`results/transfer/signal_to_load.json`) explains why:
- On 4.16 kV IEEE 123-bus (`631.5 A` nominal head current at `Sw1`), a `400 Ω` SLG fault draws a median **`6.16 A`** (`0.97%` of head current; `min 5.87 A`, `max 6.29 A`) — sitting directly inside the `1%` CT magnitude noise floor (`6.3 A` at `1σ`).
- On active grids (`results/active_grid/phase_active_ieee123.json` and `phase_active_ieee34.json`), the same 1–5% fundamental current increment is nearly indistinguishable at 60 Hz from a `+30%–80%` spot-load step, causing `NO_FAULT` false-positive rates of `6.5%–13.9%` on 123-bus and `22.1%–25.3%` zero-shot on 34-bus (`load_step` accuracy only `34.8%` GBDT / `38.3%` GATv2 on 34-bus).

**Physical opportunity:** A high-impedance earth fault on real surfaces (grass, sand, concrete, asphalt) does not behave like a pure 60 Hz linear resistor — it produces a **nonlinear, asymmetric, cycle-to-cycle intermittent ground arc** containing even harmonics (`h2, h4, h6`), DC offset, half-cycle peak asymmetry, 3rd-harmonic phase jitter, and interharmonics. The companion project `hif-sensor` designed an ESP32-S3 edge sensor (LTspice-verified 4th-order Butterworth anti-alias front end + 16 window features + 417-parameter / 504-byte int8 Tiny MLP) that detects this simulated Emanuel arc signature at `94.7%` detection and `1.5%` normal false alarms (`hif-sensor/results/kaggle_run_summary.txt`).

**Research question:** If each recloser/sectionalizing switch runs a frozen **Tier-1 Edge HIF-Sensor** (`504 B` int8 Tiny MLP) on local 15.36 kHz residual current and reports its compact arc score `p_hif` (and `PERSIST = 3` relay flag) as node features into **Tier-2 Graph FLISR** (`PerNodeGBDT`, `ZoneTreeGNN`, `ActivePerNodeGBDT`, `ActiveGridGATv2` + `aps_rand` 95% Conformal gate):
1. How much does adding `+Edge p_hif` improve **SLG `200–400 Ω`** zone localization on IEEE 123-bus (passive and active)?
2. Does the two-tier representation transfer **zero-shot** to unseen IEEE 34-bus (24.9 kV, including active `1–10 kΩ` HIFs)?
3. Does Graph FLISR keep `NO_FAULT` false-positive rates low across **all 7 realistic background disturbances** (including hard negatives `arc_welder`, `inrush`, and `nonlinear_fluct`)?
4. Does the fused system remain resilient when **1 sensor is offline** and preserve a non-degenerate **Split Conformal (`aps_rand` 95%)** act/defer gate?

---

## 2. Locked Two-Tier Architecture (Tier 1 Edge → Tier 2 Graph FLISR)

```
 [Local Switch / Recloser d]                                   [Substation / FLISR Coordinator]
  Residual CT (SCT-013-000, 2000:1, 33 Ω burden)
    └─> 4th-order Butterworth Sallen-Key LPF (fc = 2,045.1 Hz LTspice / 2,047.9 Hz Python)
    └─> 12-bit ADC @ 15.36 kHz (256 samples/cycle, 60 Hz)
    └─> 16 features over K = 8-cycle window (shf/hif_edge.py)
    └─> Frozen Tiny MLP int8 (16→16→8→1, 417 params, 504 bytes, model_int8.npz)
    └─> Local Tier-1 outputs: p_hif ∈ [0, 1], hif_alarm ∈ {0, 1} (PERSIST = 3)
                                                                       │
                    ┌──────────────────────────────────────────────────┘
                    ▼  (2 scalar node features alongside 60 Hz phasors)
  Graph G = (V, E):
    • Passive Tier 2: 21 → 23 node features  → PerNodeGBDT / ZoneTreeGNN
    • Active  Tier 2: 26 → 28 node features (+ diff_p_hif on edges: 4 → 5)
                      → ActivePerNodeGBDT / ActiveGridGATv2 → Split Conformal aps_rand (95%)
```

### 2.1 Tier 1 — Edge HIF-Sensor (exact parity with companion `hif-sensor`)

Reimplemented self-contained in `shf/hif_edge.py` (for clean local + Kaggle zip execution, verified by unit tests against `hif-sensor` in T-30):

| Stage | Locked specification | Exact source in `hif-sensor` |
|---|---|---|
| Clamp CT & burden | `SCT-013-000` (`2000:1`), `R_BURDEN = 33.0 Ω`, `GAIN_V_PER_A = 0.0165 V/A`, `VREF = 1.65 V`, `VDD = 3.3 V`, Schottky clamps `[-0.3 V, 3.6 V]` | `hif/frontend.py`, `circuit/ltspice_results.json` |
| Anti-alias analog filter | 4th-order Butterworth low-pass, two unity-gain Sallen-Key stages: Stage 1 `(R=8.66 kΩ, C_fb=10 nF, C_gnd=8.2 nF, Q=0.552)`, Stage 2 `(R=4.42 kΩ, C_fb=47 nF, C_gnd=6.8 nF, Q=1.314)`. LTspice verified `-3 dB` at **`2,045.1 Hz`** (`-46.4 dB` at Nyquist `7,680 Hz`, `-70.6 dB` at `15,360 Hz`, `4.38°` phase lag at `60 Hz`); Python bilinear IIR (`FS_SIM = 122,880 Hz`, `OVERSAMPLE = 8`) `-3 dB` at **`2,047.9 Hz`** | `hif/frontend.py`, `circuit/ltspice_results.json`, `results/kaggle_run_summary.txt` |
| ADC model | `F_LINE = 60.0 Hz`, `N_CYCLE = 256` samples/cycle → **`FS_ADC = 15,360 Hz` (`15.36 kHz`)**, `12-bit` (`0..4095`), assumed additive Gaussian noise `ADC_NOISE_LSB = 1.5` LSB (`1σ`); ESP32 ADC nonlinearity not modeled | `hif/frontend.py` |
| Window features (`K = 8`) | `60` cycles kept (`1.0 s`) after `WARMUP = 4` dropped cycles → `53` sliding `K = 8`-cycle windows (`133.3 ms`), each producing **`16` float32 features**: `log_I1`, `log_I3`, `h2_ratio`, `h3_ratio`, `h5_ratio`, `even_ratio`, `dc_ratio`, `peak_asym`, `I3_cv`, `I1_cv`, `ph3_jitter`, `cycle_diff`, `even_std`, `h3_trend`, `I1_trend`, `interharm` | `hif/features.py` |
| Quantized Tiny MLP | Architecture `16 → 16 → 8 → 1` (`ReLU` hidden, `sigmoid` output), `StandardScaler` folded into layer 1, symmetric per-layer `int8` weights (`392` B) + `float32` biases (`100` B) + `float32` layer scales (`12` B) = **`417` parameters / `504` bytes**; inference via `predict_q()` | `train_kaggle.py`, `results/kaggle_run_summary.txt` |
| Persistence logic & node export | Over the post-event observation windows (`ends[k] >= start_cycle`), compute the **persisted probability score**: `p_hif = max_{k: ends[k] >= start_cycle} min(p[k-2], p[k-1], p[k])` (`PERSIST = 3` consecutive windows). Note that `p_hif > thr` holds **if and only if** the `PERSIST = 3` relay timer triggers (`hif_alarm = 1.0 if p_hif > thr else 0.0`, using the frozen `thr` from `model_int8.npz`). | `train_kaggle.py:alarms()` (`PERSIST = 3`) |

*Reference standalone performance of frozen Tier 1 (from `hif-sensor/results/kaggle_run_summary.txt`, Kaggle kernel `christoopherchau/ch-y-n`, simulation only):* `94.7%` HIF detection, `1.5%` normal false alarms, median delay `5.0` cycles (`p90 = 9.6`), per-surface detection `wet_grass 95.5%`, `wet_sand 98.5%`, `concrete 97.7%`, `dry_grass 92.3%`, `dry_asphalt 90.7%`; normal false alarms by disturbance `none 0.0%`, `load_step 1.8%`, `cap_switch 0.0%`, `inrush 4.8%`, `motor_start 3.4%`, `arc_welder 0.0%`, `nonlinear_fluct 0.0%`.

### 2.2 Tier 2 — Graph FLISR (exact parity with `shf/transfer_models.py` and `shf/active_models.py`)

Both branches run a **paired ablation** on the exact same OpenDSS events, folds, topologies, and seeds:
- **Baseline (`60Hz_only`):** Existing 60 Hz phasor + structural features unchanged (`21` node features passive; `26` node features + `4` edge features active).
- **Fused (`60Hz_plus_edge`):** Appends the **2 dimensionless, feeder-independent Tier-1 features** `(p_hif, hif_alarm)` to every node's live-sensor block:
  1. **Passive branch (`shf/transfer_models.py`):**
     - Node features: `21 → 23` (`dIa..dVc, has_a..has_c, p_hif, hif_alarm` as live electrical channels `0..18`, followed by 4 structural features `depth, n_children, share_down, share_own`).
     - Models: `fpi` (60 Hz floor), `PerNodeGBDT` (frozen 123-bus config `max_iter=300, lr=0.1, max_leaf_nodes=31`; 1-hop parent/child aggregates extended to include `p_hif` and `hif_alarm`), `ZoneTreeGNN` (2 layers, `hidden=64, dropout=0.1`, `epochs=40`, `sensor_dropout=0.15`).
     - Training & eval: 5-fold `GroupKFold` by bus on IEEE 123-bus (`11,448` events, `127` buses), then frozen 123-bus models evaluated zero-shot and few-shot (`5%`, `20%` of buses, `10` splits) on unseen IEEE 34-bus (`4,104` events, `35` buses).
  2. **Active branch (`shf/active_models.py`):**
     - Node features: `26 → 28` (`dIa..dVc, has_a..has_c, cos_vi_post..power_rev, p_hif, hif_alarm` as live electrical channels `0..22`, followed by 5 grid-state features `is_closed, active_deg, share_own, der_ratio, is_source_adj`).
     - Directed edge features for `ActiveGridGATv2`: `4 → 5`, adding `diff_p_hif = p_hif(u) - p_hif(v)` (zeroed when either endpoint is offline/NaN) so graph attention directly detects where the arc signature terminates along radial, reconfigured, or looped paths.
     - Models: `active_fpi`, `ActivePerNodeGBDT` (frozen 123-bus config `max_iter=300, lr=0.05, max_leaf_nodes=63`, neighbor aggregates + graph-level `NO_FAULT` GBDT extended with `max(p_hif)`, `mean(p_hif)`, `sum(hif_alarm)`), and `ActiveGridGATv2` (2 layers, `hidden=64, heads=4, dropout=0.1, epochs=45`, joint `(N + 1)`-way readout on Kaggle GPU).
     - Split Conformal Prediction: **Randomized APS (`aps_rand`, `U_SEED = 12345`)** at `1 - α ∈ {0.90, 0.95}` (primary gate: `95%`), plus `lac` logged for comparison, following Addendum A/B1 of `research/active-grid-gnn/PLAN.md`. Evaluated under: (a) IEEE 123-bus bus-disjoint 5-fold cross-conformal; (b) IEEE 34-bus with frozen 123-bus `q̂` (explicitly carrying **no** exchangeability guarantee); and (c) IEEE 34-bus bus-disjoint recalibration (`5%` and `20%` of fault buses + matching `NO_FAULT` share, `10` repeats, zero weight retraining).
  3. **Sensor-offline behavior (`1 sensor offline`):**
     - Physically, the Edge HIF-Sensor runs inside the same IED/recloser node as the 60 Hz CT/PT telemetry. Therefore, blanking switch `d` during `1 sensor offline` (and during `15%` training sensor dropout) blanks **both** its 60 Hz electrical readings **and** its `(p_hif, hif_alarm)` channels to `NaN` simultaneously.

---

## 3. Coupling Physics, Frozen Model Rules, and Locked `ASSUMPTION`s

Every assumption below is implemented in `shf/hif_fusion.py` and `shf/hif_edge.py` with explicit `ASSUMPTION` comments and fixed before running:

### 3.1 Coupling OpenDSS 60 Hz currents to Tier-1 Emanuel arc waveforms (`ASSUMPTION`)

1. **OpenDSS per-switch residual current split:**
   - For every converged OpenDSS event (passive `shf/transfer.py` or active `shf/active_grid.py`), extract at each monitored device `d`:
     - pre-fault residual current magnitude `I_res_pre(d) = |I_a,pre + I_b,pre + I_c,pre|` (primary A RMS),
     - post-event incremental residual current magnitude `dI_res(d) = |(I_a+I_b+I_c)_post - (I_a+I_b+I_c)_pre|` (primary A RMS),
     - and fault-point current magnitude `I_fault` (primary A RMS, for fault events).
2. **Physical arcing condition (`ASSUMPTION`):**
   - A fault event is modeled as an **Emanuel arcing earth fault** if and only if:
     - `ftype == "SLG"` **AND** `R >= 100.0 Ω` **AND** `I_fault <= 45.0 A RMS`.
   - **Why this threshold is locked and physically grounded (`results/transfer/signal_to_load.json`):**
     - On 4.16 kV IEEE 123-bus, `SLG 100 Ω` draws `23.34–25.06 A` (median `24.55 A`) and `400 Ω` draws `5.87–6.29 A` (median `6.16 A`), so **`100%` of `100, 200, 400 Ω` SLG faults** on IEEE 123-bus are arcing HIFs.
     - On 24.9 kV IEEE 34-bus, `SLG 400 Ω` draws `5.47–37.62 A` (median `31.66 A`), `1,000 Ω` draws median `13.89 A`, `2,500 Ω` draws median `5.79 A`, and `10,000 Ω` draws median `1.48 A`, so **`100%` of `400–10,000 Ω` SLG faults** (plus `100 Ω` faults on the 4.16 kV lateral where `I_fault` drops to `21.06 A`) satisfy the same feeder-agnostic `< 45 A` arcing threshold, whereas high-current `100 Ω` faults on the 24.9 kV trunk (`87.78 A` median) remain non-arcing linear ground faults.
   - **Five Emanuel arc surfaces (`hif/waveforms.py:SURFACES`):** Each arcing fault event samples one surface uniformly from `{"wet_grass", "wet_sand", "concrete", "dry_grass", "dry_asphalt"}` (`Vp`, `R` ranges identical to `hif-sensor/hif/waveforms.py`), recorded in the dataset metadata for per-surface accuracy reporting.
   - **Current-division scaling at each switch `d` (`ASSUMPTION` — quasi-steady harmonic superposition):**
     - One event-level arc waveform `i_arc_raw(t)` is generated with `_arc(t, t0, rng, SURFACES[surface])` (`start_cycle ∈ [12, 40]`), normalized by its steady-state tail RMS (`last 20 cycles`), and injected into every **closed** switch `d` scaled by that switch's OpenDSS incremental residual current:
       `i_arc_d(t) = dI_res(d) * (i_arc_raw(t) / rms_tail(i_arc_raw))` (set to `0` if switch `d` is open or `dI_res(d) < 0.05 A`).
     - **No label leakage:** Switches upstream on the active fault-current path (or along closed-loop back-feed paths) receive the true OpenDSS current share `dI_res(d)`; healthy sibling branches and switches downstream of the fault receive their true near-zero `dI_res(d)`.
   - **Non-arcing faults (`3PH`, `LL`, `LLG`, and low-R `SLG` with `R < 100 Ω` or `I_fault > 45 A`):**
     - `3PH` and `LL` carry no earth-arc return (`i_arc_d(t) = 0`; switch sees base residual unbalance + any OpenDSS residual increment as a linear 60 Hz sinusoid).
     - Low-R `SLG` and `LLG` inject `dI_res(d) * sqrt(2) * sin(ωt + φ)` as a linear 60 Hz post-event residual step through `frontend.sense()` (including Schottky clamping at `[-0.3 V, 3.6 V]`, i.e., `±100 A` primary equivalent). No synthetic Emanuel arc signature is added.
3. **Local pre-fault residual background per switch (`ASSUMPTION`):**
   - Each closed switch `d` carries a local background residual waveform `_base_d(t)` using the exact harmonic/noise structure of `hif-sensor/hif/waveforms.py:_base()` (triplen-heavy 3rd/5th/7th/9th harmonics, `0.02–0.2 A` noise, `30%` probability of `8–20 kHz` inverter switching noise), with fundamental RMS anchored to `clip(I_res_pre(d), 1.0, 20.0)` A RMS.
   - **Why clipped to `[1.0, 20.0] A` (`ASSUMPTION`):** `hif-sensor`'s SCT-013-000 clamp CT + 33 Ω burden and frozen Tier-1 MLP were calibrated for `1–20 A` RMS residual unbalance; on a heavily unbalanced 4.16 kV main trunk where `I_res_pre` exceeds `20 A`, a real deployment would adjust CT ratio per device or subtract steady fundamental unbalance. This clipping is explicitly disclosed as a modeling assumption.
   - Open switches carry `0 A` primary current (`ADC` sees bias + `1.5` LSB noise only).

### 3.2 Injection of the 7 background disturbances (`ASSUMPTION`)

Using the exact 7 disturbance waveform models from `hif-sensor/hif/waveforms.py:DISTURBANCES`:
`("none", "load_step", "cap_switch", "inrush", "motor_start", "arc_welder", "nonlinear_fluct")`.

1. **On fault events (healthy and faulted switches):**
   - Matching `hif-sensor/hif/waveforms.py:make_event()`, each switch independently receives a concurrent background disturbance with probability **`p_disturb = 0.25`** (drawn uniformly from the 6 non-`"none"` classes; `"none"` with probability `0.75`), starting at a random cycle `t1 ∈ [0, N_CYCLES)`.
   - Crucially, this injects hard-negative disturbances (`arc_welder`, `inrush`, `motor_start`, `nonlinear_fluct`) onto **healthy switches** during fault events, forcing Tier-2 Graph FLISR to fuse `p_hif` with 60 Hz phasors and graph neighbors rather than blindly trusting any single switch's `p_hif`.
2. **On `NO_FAULT` events in the active-grid datasets:**
   - Every `NO_FAULT` event carries **no arc** (`i_arc_d(t) = 0` at all switches) and maps its OpenDSS transient kind to time-domain disturbances across the active switches so **all 7 disturbance classes are explicitly tested**:
     - OpenDSS `cap_switch` → waveform disturbance `cap_switch` (plus balanced subset with `none` for baseline check).
     - OpenDSS `pv_cloud` → split 50/50 between `none` (with `8–20 kHz` inverter switching noise active) and `nonlinear_fluct`.
     - OpenDSS `load_step` → split evenly across the 5 load/magnetizing/arcing-load distractors: `load_step`, `inrush`, `motor_start`, `arc_welder`, `nonlinear_fluct`.
   - Each `NO_FAULT` event records its exact `edge_disturbance ∈ DISTURBANCES` label in the `.npz` dataset so `scripts/hif_fusion_run.py` reports **per-disturbance `NO_FAULT` FPR for all 7 classes** (`none`, `load_step`, `cap_switch`, `inrush`, `motor_start`, `arc_welder`, `nonlinear_fluct`) on both IEEE 123-bus and unseen IEEE 34-bus.

### 3.3 Frozen `model_int8.npz` loading and zero-leakage protocol

1. **Primary source (preferred):** Load the frozen `model_int8.npz` produced by Kaggle notebook `christoopherchau/ch-y-n` (`--model-npz <path>`, or auto-detected in `/kaggle/input/*/results/model_int8.npz` or `/kaggle/input/*/model_int8.npz`). Record its exact file path, SHA-256 checksum, parameter count (`417`), byte size (`504`), and threshold `thr` in `results/hif_fusion/dataset_summary.json` and provenance.
2. **Deterministic fallback (only if `model_int8.npz` is unavailable):** Re-train Tier-1 Tiny MLP int8 strictly with the exact `hif-sensor/train_kaggle.py` specification (`SEED = 42`, `N_EVENTS = 4000`, `60/20/20` event split, `HIDDEN = (16, 8)`, `alpha = 1e-3`, `max_iter = 400`, `early_stopping = True`, `n_iter_no_change = 15`, `PERSIST = 3`, `MAX_FALSE_ALARM = 0.01`, folded StandardScaler + per-layer int8 quantization) on **standalone `make_event()` waveforms only** (zero OpenDSS data). Save to `data/generated/hif_model_int8_seed42.npz`, log `"model_source": "retrained_seed42_fallback"` alongside its standalone test detection/FPR and SHA-256 hash, and freeze all weights and `thr` immediately.
3. **Strict leakage firewall:**
   - Tier-1 `model_int8.npz` weights and threshold `thr` are **frozen** before scoring any OpenDSS event; they are **never** updated using IEEE 123-bus or IEEE 34-bus labels.
   - All Tier-2 models (`PerNodeGBDT`, `ZoneTreeGNN`, `ActivePerNodeGBDT`, `ActiveGridGATv2`) are trained **strictly on IEEE 123-bus** using 5-fold `GroupKFold` grouped by physical **fault bus** (`NO_FAULT` events split disjointly).
   - Hyperparameters are kept **frozen** from our prior IEEE 123-bus studies (`phase2_ieee123.json` and `phase_active_ieee123.json`) — no post-hoc tuning on IEEE 34-bus or on the fused test metrics.
   - IEEE 34-bus is touched **only once** at evaluation time for zero-shot transfer, few-shot (`5%`/`20%` bus-disjoint) checks, and bus-disjoint conformal recalibration.

---

## 4. Pre-Committed Pass / Fail Criteria (fixed before any run)

Every criterion compares the **fused model (`60Hz + Edge p_hif, hif_alarm`)** against its **paired `60Hz_only` baseline** run on the exact same events, folds, and seeds. Failing any criterion is reported as a failure with its full breakdown — never hidden or patched by tuning thresholds after seeing results.

### H1 — IEEE 123-bus HIF Localization Gain (SLG `200–400 Ω`, 5-fold GroupKFold by bus)
- **Pass (Passive branch — `PerNodeGBDT` and `ZoneTreeGNN`):**
  - At least one model improves **SLG `400 Ω`** accuracy by **≥ +10.0 percentage points** AND improves **combined SLG `200–400 Ω`** accuracy by **≥ +5.0 percentage points** over its paired `60Hz_only` baseline; AND
  - Neither model degrades low-resistance (`0.01–100 Ω`) SLG or phase-fault (`3PH/LL/LLG`) accuracy by more than **0.5 percentage points**.
- **Pass (Active branch — `ActivePerNodeGBDT` and `ActiveGridGATv2`):**
  - At least one model improves **SLG `400 Ω`** accuracy by **≥ +10.0 percentage points** AND improves **combined SLG `200–400 Ω`** accuracy by **≥ +5.0 percentage points** over its paired `60Hz_only` baseline, without regressing overall accuracy or degrading phase/low-R faults by more than **0.5 percentage points**.
- **Partial:** Gain on SLG `400 Ω` is positive (`+3.0` to `< +10.0` pts) without phase/low-R regression.
- **Fail:** SLG `400 Ω` gain `< +3.0` pts, or low-R/phase-fault accuracy regresses by `> 0.5` pts.
- *Required diagnostic:* Report accuracy across all **5 Emanuel surfaces** (`wet_grass`, `wet_sand`, `concrete`, `dry_grass`, `dry_asphalt`).

### H2 — Zero-Shot Transfer to Unseen IEEE 34-bus (24.9 kV)
- **Pass (Passive branch):** Zero-shot overall accuracy with `+Edge` stays within **0.5 percentage points** of (or exceeds) the paired `60Hz_only` baseline (since passive 34-bus is already near ceiling at 24.9 kV) and does not regress SLG `200–400 Ω`.
- **Pass (Active branch):** For at least one model (`ActivePerNodeGBDT` or `ActiveGridGATv2`), zero-shot `+Edge` improves **voltage-scaled HIF SLG (`1,000–10,000 Ω` combined)** accuracy by **≥ +5.0 percentage points** AND improves zero-shot **overall accuracy** by **≥ +2.0 percentage points** over its paired `60Hz_only` baseline.
- **Partial:** Active zero-shot improves HIF SLG (`1,000–10,000 Ω`) by `+2.0` to `< +5.0` pts or overall by `+0.5` to `< +2.0` pts without degrading clean low-R/phase accuracy.
- **Fail:** `+Edge` degrades zero-shot overall accuracy or HIF SLG accuracy on IEEE 34-bus relative to `60Hz_only`. Report honestly why (e.g., 24.9 kV current-scale shift or disturbance sensitivity).

### H3 — `NO_FAULT` Nuisance-Trip Control across all 7 Background Disturbances (Active Grid)
- **Pass (IEEE 123-bus 5-fold CV):** At least one `+Edge` model achieves overall `NO_FAULT` FPR **≤ 5.0%** (improving on `60Hz_only`) AND keeps `NO_FAULT` FPR **≤ 10.0%** on **every single one of the 7 disturbances** (`none`, `load_step`, `cap_switch`, `inrush`, `motor_start`, `arc_welder`, `nonlinear_fluct`).
- **Pass (IEEE 34-bus zero-shot):** At least one `+Edge` model reduces overall zero-shot `NO_FAULT` FPR by **≥ 5.0 percentage points** relative to its paired `60Hz_only` baseline (target `≤ 10.0%`), with full per-disturbance breakdown across all 7 classes.
- **Partial:** Overall `NO_FAULT` FPR strictly improves over `60Hz_only`, but one or more hard-negative disturbances (e.g., `arc_welder` or `inrush`) exceeds `10.0%` FPR.
- **Fail:** Overall `NO_FAULT` FPR increases relative to `60Hz_only` on either feeder (indicating edge false alarms leak into Graph FLISR).

### H4 — Missing-Sensor Resilience (`1 sensor offline`) & Conformal Safety Gate (`aps_rand` at 95%)
- **Missing-sensor pass:** Blanking 1 sensor (both 60 Hz phasors and Edge `p_hif`/`hif_alarm` set to `NaN`) reduces `+Edge` 1-sensor-offline mean accuracy by **≤ 1.0 percentage point** relative to `60Hz_only` on both IEEE 123-bus and IEEE 34-bus (ideally improving mean accuracy on SLG `200–400 Ω`).
- **Conformal pass (`aps_rand`, `1 - α = 0.95`, `U_SEED = 12345`):**
  1. **Non-degeneracy prerequisite:** `90%` and `95%` prediction sets must differ, and IEEE 123-bus cross-conformal coverage must lie within **`92.0%–98.0%`**.
  2. On IEEE 123-bus, `+Edge` maintains or increases autonomous singleton (`|C| = 1`) share relative to `60Hz_only`, with singleton accuracy **≥ 98.5%** and autonomous `NO_FAULT` trip share **≤ 1.5%**.
  3. On IEEE 34-bus, report both frozen 123-bus `q̂` (explicitly noting **no exchangeability guarantee**) and bus-disjoint recalibrated `q̂` (`5%` and `20%` of fault buses, `10` draws, zero weight retraining).

---

## 5. Output Isolation & Provenance Plan

To guarantee zero contamination of any existing published result (`results/metrics.json`, `results/error_analysis/`, `results/transfer/`, `results/active_grid/`, `results/active_grid_ieee37/`, `results/hourly/`, `results/spice/`):

| Artifact | Isolated path | Notes |
|---|---|---|
| Self-contained Edge + Fusion modules | `shf/hif_edge.py`, `shf/hif_fusion.py` | Unit-tested in `tests/test_hif_fusion.py` (T-30) |
| Experiment runner & Kaggle notebook | `scripts/hif_fusion_run.py`, `notebooks/kaggle_hif_fusion.ipynb` | `--model-npz`, `--quick` smoke test (cleaned after test), full Kaggle GPU run (T-31, T-32) |
| Generated fused datasets | `data/generated/hif_fusion_*.npz` | Git-ignored |
| Isolated JSON results | `results/hif_fusion/dataset_summary.json`, `passive_ieee123.json`, `passive_ieee34.json`, `active_ieee123.json`, `active_ieee34.json`, `conformal_hif.json` | Written only by `scripts/hif_fusion_run.py`; never edited by hand |
| Provenance records | `results/provenance/hif_fusion*.json` | Recorded via `shf.provenance.record()`, verified by `harness/check.py --tests` |
| Report & docs integration | Section `2d` in `shf/dashboard.py`, `shf/dashboard_text.py`, `README.md`, `docs/vi/*.md`, `harness/facts.toml` | Additive only (T-33, T-34); Sections `2a`/`2b`/`2c` numbers remain untouched |

---

## 6. Honesty & Physical-Limit Commitments

1. **Simulation only — both tiers:** Neither OpenDSS steady-state phasors nor the Emanuel arc / 7-disturbance waveforms are field recordings. Quasi-steady harmonic superposition omits EMTP electromagnetic transients, traveling waves, frequency-dependent cable/line impedance, CT core saturation, and ESP32 ADC nonlinearity.
2. **Known real-vs-simulated arc domain gap:** In `hif-sensor` Phase 1 (`hif-sensor/results/kaggle_run_summary.txt`), running the exact same frozen Phase-0 `model_int8.npz` without retraining on real 22 kV 50 Hz VeHIF vegetation-fault recordings (through the simulated sensor + simulated load) dropped detection from **`94.7%`** (simulated Emanuel arcs) to **`56.0%`** (`36.2%` at `0–1 A`, `70.0%` at `1–2 A`, `94.7%` at `2–5 A`, `85.7%` at `5–10 A`; background alarm rate `0.0%`), because real vegetation arcs were steadier and less asymmetric (`dc_ratio -0.49`, `h2_ratio -0.47`, `even_ratio -0.46` IQR shift). Therefore, strong gains on simulated Emanuel arcs **do not prove field performance** without real utility fault oscillograms.
3. **Hardware deployment requirement:** Unlike the 60 Hz-only study, deploying this two-tier architecture in practice requires **edge IEDs or ESP32-S3-class sensor nodes sampling residual current at `≥ 15.36 kHz`** behind an anti-aliasing analog front end (`fc ≈ 2 kHz`) at every monitored recloser/switch — legacy 60 Hz SCADA/RTU polling cannot supply `p_hif`.
4. **Bounded conformal claim:** Even if `H4` passes, `aps_rand` provides a simulated **decision-support act/defer gate** on the calibrated feeder, not a protection guarantee and not an automatic cross-feeder safety guarantee.
5. **No invented numbers:** Until T-32 finishes on Kaggle GPU and provenance SHA-256 checks pass, every downstream page, README, and status line must state explicitly **"not run yet (pending Kaggle GPU run)"**.

---

## 7. Results (Kaggle GPU run, 2026-11-24, `results/hif_fusion/*.json`)

Executed on Kaggle GPU (`torch 2.11.0+cu130`, `runtime_s = 3,985.4 s`) using the exact frozen Tier-1 `model_int8.npz` from `christoopherchau/ch-y-n` (`417` params, `504` bytes, `thr = 0.982635`, SHA-256 `3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1`). Provenance verified (`results/provenance/hif_fusion.json`). Simulation only; no field data.

### 7.1 Pre-committed criteria verdict (`H1–H4`: 4/4 `PASS`)

| Criterion | Verdict | Measured evidence (`results/hif_fusion/`) |
|---|---|---|
| **H1 — IEEE 123-bus HIF gain** | **PASS** | Passive SLG 400 Ω: GBDT `78.1% → 97.7%` (`+19.6 pts`), GNN `79.6% → 96.0%` (`+16.4 pts`); Passive SLG 200–400 Ω: `87.5% → 98.0%` / `86.4% → 97.0%`. Active SLG 400 Ω: GBDT `72.5% → 86.8%` (`+14.2 pts`), GATv2 `73.5% → 87.5%` (`+14.1 pts`); Active SLG 200–400 Ω: `80.2% → 90.3%` / `82.2% → 90.8%`. Zero phase or low-R regression > `0.5 pts`. |
| **H2 — Unseen IEEE 34-bus zero-shot** | **PASS** | Passive holds ceiling: GBDT `99.8% → 99.8%` (SLG 200–400 Ω `98.5% → 98.7%`), GNN `99.4% → 99.4%` (`95.9% → 97.6%`). Active zero-shot improves both models: GBDT `83.8% → 87.5%` overall (`71.8% → 77.8%` on 1–10 kΩ HIF SLG), GATv2 `77.6% → 83.3%` overall (`65.3% → 70.0%` on 1–10 kΩ). |
| **H3 — `NO_FAULT` FPR across 7 disturbances** | **PASS** | Active 123-bus FPR drops `13.9% → 3.3%` (GBDT) and `6.5% → 1.2%` (GATv2, max disturbance `inrush 6.7% ≤ 10.0%`). Active 34-bus zero-shot FPR drops `22.1% → 5.8%` (GBDT, `-16.3 pts`) and `25.3% → 9.7%` (GATv2, `-15.6 pts`). |
| **H4 — Missing-sensor & Conformal (`aps_rand` 95%)** | **PASS** | 1-sensor-offline improves on 6/8 model-feeder pairs and stays within `0.24 pts` on passive 34-bus: passive 123 `89.0% → 90.3%` (GBDT) / `90.0% → 91.5%` (GNN); active 123 `86.1% → 88.7%` / `89.1% → 91.3%`; active 34 `72.4% → 75.6%` / `71.5% → 74.5%`. Conformal (`ActiveGridGATv2`, `aps_rand` 95%): 123-bus coverage `95.0%` vs `95.0%`, singleton share `89.2% → 93.0%` (`98.9%` singleton accuracy, `0.5%` autonomous `NO_FAULT` trip share); unseen 34-bus frozen `q̂` `81.4% → 84.9%` (no exchangeability guarantee), 5%-bus recal mean `92.0%` / min `85.4%`. |

### 7.2 Paired ablation summary (`60Hz_only` → `60Hz_plus_edge`)

| Branch & feeder | Model | Overall | SLG 200–400 Ω (or 1–10 kΩ) | SLG 400 Ω | `NO_FAULT` FPR | 1 sensor offline |
|---|---|---:|---:|---:|---:|---:|
| Passive 123-bus (CV) | `PerNodeGBDT` | `98.2% → 99.7%` | `87.5% → 98.0%` | `78.1% → 97.7%` | — | `89.0% → 90.3%` |
| Passive 123-bus (CV) | `ZoneTreeGNN` | `98.0% → 99.5%` | `86.4% → 97.0%` | `79.6% → 96.0%` | — | `90.0% → 91.5%` |
| Passive 34-bus (0-shot) | `PerNodeGBDT` | `99.8% → 99.8%` | `98.5% → 98.7%` | `97.4% → 97.8%` | — | `88.1% → 88.0%` |
| Passive 34-bus (0-shot) | `ZoneTreeGNN` | `99.4% → 99.4%` | `95.9% → 97.6%` | `94.4% → 97.4%` | — | `86.1% → 85.9%` |
| Active 123-bus (CV) | `ActivePerNodeGBDT` | `93.9% → 96.8%` | `80.2% → 90.3%` | `72.5% → 86.8%` | `13.9% → 3.3%` | `86.1% → 88.7%` |
| Active 123-bus (CV) | `ActiveGridGATv2` | `95.8% → 97.6%` | `82.2% → 90.8%` | `73.5% → 87.5%` | `6.5% → 1.2%` | `89.1% → 91.3%` |
| Active 34-bus (0-shot) | `ActivePerNodeGBDT` | `83.8% → 87.5%` | `71.8% → 77.8%` | `84.8% → 86.3%` | `22.1% → 5.8%` | `72.4% → 75.6%` |
| Active 34-bus (0-shot) | `ActiveGridGATv2` | `77.6% → 83.3%` | `65.3% → 70.0%` | `81.8% → 86.7%` | `25.3% → 9.7%` | `71.5% → 74.5%` |

### 7.3 Active IEEE 123-bus breakdown (`ActiveGridGATv2`, `60Hz_plus_edge`)

- **5 Emanuel arc surfaces (zone accuracy):** `wet_grass 93.4%`, `wet_sand 95.1%`, `concrete 92.4%`, `dry_grass 92.1%`, `dry_asphalt 90.0%`.
- **7 `NO_FAULT` background disturbances (FPR):** `none 0.1%`, `load_step 1.7%`, `cap_switch 0.3%`, `inrush 6.7%`, `motor_start 2.2%`, `arc_welder 2.2%`, `nonlinear_fluct 0.8%`.
