# Zero-shot fault location on a third unseen feeder: urban underground IEEE 37-bus (4.8 kV, 3-wire delta)

Status: **All phases complete: passive CPU (T-22 & T-23) and active-grid + Conformal on Kaggle GPU (T-24)** (plan pre-registered 2026-11-24 before any IEEE 37-bus run; passive results appended after execution with full provenance). Every benchmark setting, assumption, and pass/fail criterion below remained frozen from pre-registration. Simulation only; no field data.

Related study plans:
- Passive cross-feeder transfer (IEEE 123-bus → IEEE 34-bus) and Stage-2 bus ranking: [`research/gnn-transfer/PLAN.md`](../gnn-transfer/PLAN.md)
- Active, reconfigurable grid transfer + Split Conformal Prediction (IEEE 123-bus → IEEE 34-bus): [`research/active-grid-gnn/PLAN.md`](../active-grid-gnn/PLAN.md)

## Why this third feeder is needed (gaps left by the 123-bus → 34-bus pair)

Our first two studies tested cross-feeder transfer from **IEEE 123-bus (4.16 kV)** to **IEEE 34-bus (24.9 kV)** — reaching `99.8%` (Per-node GBDT) and `99.3%` (Zone-tree GNN) zero-shot in the passive radial study (`results/transfer/phase3_ieee34.json`), `87.4%` Top-3 bus ranking with zero-training 3-phase Takagi reactance (`results/transfer/phase2b_bus_location.json`), and `83.8%` (GBDT) / `77.6%` (GATv2) zero-shot on the active, reconfigurable 34-bus grid (`results/active_grid/phase_active_ieee34.json`). However, evaluating on only **one** unseen test feeder leaves three major generalization questions unanswered:

1. **Both 123-bus and 34-bus are predominantly overhead, 4-wire multigrounded wye feeders:** A model trained on one 4-wire grounded overhead feeder and tested on another 4-wire grounded overhead feeder has never been exposed to a fundamentally different earthing system or conductor medium.
2. **Voltage-level asymmetry made passive 34-bus physically easier at fixed resistance:** Measured in OpenDSS (`results/transfer/signal_to_load.json`), a `400 Ω` SLG fault draws a median `31.7 A` (`61.1%` of the `51.8 A` feeder-head current) on 24.9 kV IEEE 34-bus versus `6.2 A` (`1.0%` of `631.5 A`) on 4.16 kV IEEE 123-bus, and even `10,000 Ω` on 34-bus still draws `2.9%` of head current. A third feeder near the 4.16 kV voltage class tests transfer without that 24.9 kV signal-to-load boost.
3. **True out-of-distribution generalization requires a qualitatively different grid architecture:** Testing the **exact frozen IEEE 123-bus models** (zero retraining, zero hyperparameter tuning) on an **urban underground, 3-wire ungrounded delta** feeder — **IEEE 37-bus (4.8 kV)** — directly probes whether feeder-independent relative/directional graph features generalize across construction type, cable capacitance, load imbalance, and delta grounding, or where the physical breakdown occurs.

## 1. Physical characteristics of IEEE 37-bus (and expected physical impact)

The **IEEE 37-Node Test Feeder** (Kersting, IEEE PES Distribution System Analysis Subcommittee; OpenDSS mirror `dss-extensions/electricdss-tst`, `Version8/Distrib/IEEETestCases/37Bus`) differs physically from both IEEE 123-bus and IEEE 34-bus along five axes:

1. **Urban underground cable construction:** All primary line segments are underground 3-phase cables (IEEE underground line configurations `721`–`724`), rather than predominantly overhead lines. Underground cables exhibit substantially higher **shunt charging capacitance** per unit length, lower series `X/R` ratios, and shorter electrical distances (`ΔX1`) between adjacent buses than overhead feeders.
2. **4.8 kV line-to-line primary voltage:** The substation transformer steps `230 kV` down to `4.8 kV` LL (plus one in-line `4.8 kV / 0.48 kV` delta-delta step-down transformer). Because `4.8 kV` is close to IEEE 123-bus `4.16 kV` (`(4.8 / 4.16)² ≈ 1.33`), the voltage base sits in the same medium-voltage regime as the training feeder rather than the 6× higher `24.9 kV` of IEEE 34-bus.
3. **3-wire ungrounded delta topology (no neutral conductor):**
   - The substation `230 kV / 4.8 kV` transformer secondary is **delta-connected** with no grounded neutral point.
   - All primary cable segments are 3-phase, 3-wire (every 4.8 kV primary bus carries all three phases `{1, 2, 3}`; there are no single-phase or two-phase laterals).
   - Voltage regulation at the feeder head uses an **open-delta** step-voltage regulator (two single-phase units across phases A–B and C–B).
   - All spot loads are **delta-connected** (phase-to-phase) and **heavily unbalanced** across phase pairs (`A–B`, `B–C`, `C–A`).
   - There are **no shunt capacitor banks** in the standard IEEE 37-bus test case.
4. **Expected physical impact on fault signatures (stated before any run):**
   - **SLG (Single-Line-to-Ground) faults on an ungrounded 3-wire delta feeder:** Without a grounded substation neutral, an earth fault (`bus1=b.p bus2=b.0`) cannot drive a metallic neutral return loop. Zero-sequence fault current returns solely through the **distributed shunt charging capacitance** of the healthy cable phases (and any tiny numerical/reference admittance in OpenDSS). Consequently:
     - `|ΔI|` and `3|ΔI0|` are expected to be much smaller than on grounded 4-wire feeders, and capacitive zero-sequence currents flow from healthy branches *toward* the faulted bus rather than strictly downstream from the substation head.
     - Unfaulted phase-to-ground voltages experience **neutral shift** (rising toward `√3` pu, ~1.73 pu, while line-to-line voltages stay near nominal) — a voltage regime that models trained exclusively on grounded 4-wire IEEE 123-bus have **never seen**.
     - Therefore, **SLG zero-shot accuracy and SLG Takagi reactance accuracy may degrade sharply** compared to IEEE 123-bus and 34-bus. If that happens, it is a genuine physical limitation, not a bug to hide.
   - **Phase faults (`LL`, `LLG`, `3PH`):** `LL` and `3PH` faults circulate current directly between phases through the `4.8 kV` delta source and cables without needing a neutral return. `LLG` faults (`bus1=b.p.q bus2=b.0.0 r=r`) bridge phases `p` and `q` through `2r` via node `0`, also producing strong phase-to-phase current increments (`ΔI2`). Hence phase faults remain physically observable and are tracked separately alongside overall metrics.
   - **Stage-2 Takagi reactance on underground cables:** Shorter electrical spacing (`ΔX1`), lower cable `X/R`, and cable charging current increase sensitivity to CT/PT noise (`1%` magnitude, `0.5°` angle), especially for SLG faults where distributed capacitive return breaks the standard grounded-loop Takagi equation.
5. **Measured OpenDSS circuit metrics (completed in T-22 & T-23, `results/transfer/signal_to_load.json` and `results/transfer/dataset_ieee37.json`):**
   - **Topology & placement (`PLACEMENT_RULE`, `BRANCH_SHARE = 0.05`):** `10` switching zones (`D1`–`D10` on lines `l35, l2, l3, l4, l5, l6, l7, l8, l29, l30`), `36` zone buses (all 3-phase `[1, 2, 3]`), total nominal load `2,457.0 kW`.
   - **Nominal head current & SLG signal-to-load (`results/transfer/signal_to_load.json`):** Head device `D1` (`Line.l35`) carries `369.5 A` at `2.771 kV` L-N (`4.8 kV` LL). Across `108` SLG faults per resistance (`0` non-converged), median fault current is **`2.36 A`** (`0.64%` of head current) from `0.01 Ω` through `10 Ω`, `2.35 A` (`0.64%`) at `100 Ω`, and `2.23 A` (`0.60%`) at `400 Ω` — confirming directly in OpenDSS that ungrounded 3-wire delta SLG current is capacitance-limited and virtually insensitive to fault resistance up to `400 Ω`.
   - **Active-grid locked parameters (T-22, `shf/active_grid.py`):** 3 delta-connected `Model=7` DERs on the 3 heaviest non-head zones (`738` in `D9`, `708` in `D6`, `720` in `D8`); `Tie37` at bus `741` (`D9`) fed via a 230/4.8 kV delta-delta transformer `SubXF37Adj` + `LineCode=722` cable trunk; `reconfig_tie` opens `D6` (`Line.l6`) and closes `Tie37`; `looped_tie` closes `Tie37` with all sectionalizers closed; `NO_FAULT` split 50/50 between `pv_cloud` and `load_step` (`cap_switch = 0`).

## 2. Research questions

Using models trained **strictly on IEEE 123-bus only** (frozen weights and frozen hyperparameters from our existing studies):
1. **Passive radial transfer (Stage-1 zone location):** How well do frozen `PerNodeGBDT` and `ZoneTreeGNN` transfer zero-shot to passive IEEE 37-bus compared against graph FPI, 5% and 20% few-shot adaptation, and the IEEE 37-bus 5-fold in-domain CV upper bound — both overall and broken down by fault type (`3PH / LL / LLG / SLG`), resistance, and 1-sensor-offline?
2. **Stage-2 bus ranking:** Does zero-training 3-phase Takagi reactance (`shf/bus_locator.py`) beat random-in-zone bus selection on compact underground cables, and how does it compare with zero-shot and in-domain `BusGraphGNN` on phase faults vs SLG faults?
3. **Active-grid transfer (DER 0–50% + `reconfig_tie` / `looped_tie` + `NO_FAULT`):** How do frozen `ActivePerNodeGBDT` and `ActiveGridGATv2` transfer zero-shot (and at 5%/20% few-shot) to an active, reconfigurable/looped IEEE 37-bus grid relative to `active_fpi` and in-domain 5-fold CV?
4. **Conformal safety gate (`aps_rand` at 95%):** Under randomized APS (`aps_rand`, `1 - α = 0.95`), how do frozen 123-bus `q̂` and IEEE 37-bus bus-disjoint recalibration perform on coverage, set size, singleton accuracy, and autonomous `NO_FAULT` trip rate?

## 3. Benchmark design and assumptions (fixed before running; all marked `ASSUMPTION`)

All simulations run in OpenDSS (`OpenDSSDirect.py`). Passive sweeps and evaluations run on local CPU (T-22, T-23); active-grid training/transfer runs on a Kaggle GPU VM using offline Linux OpenDSS wheels (T-24). Simulation only; no field data.

### 3.1 Feeder source and compilation
- **Source:** Unmodified IEEE 37-bus OpenDSS test case from [`dss-extensions/electricdss-tst`](https://github.com/dss-extensions/electricdss-tst) (`Version8/Distrib/IEEETestCases/37Bus`), placed in `data/feeder/ieee37/`.
- **Voltage bases:** `voltage_bases = [230, 4.8, 0.48]` (kV LL), compiled with `CalcVoltageBases` and solved with `controls=True` in `shf/transfer.py:FEEDERS["ieee37"]`.
- **Root bus:** The substation source bus defined by the OpenDSS master file (`sourcebus` / `799`, verified when compiling in T-22).

### 3.2 Sectionalizer placement (`ASSUMPTION`)
- **Rule (frozen, unchanged from `shf/transfer.py`):** Apply the exact existing `PLACEMENT_RULE` with `BRANCH_SHARE = 0.05`:
  > one recloser on the first line leaving the substation bus; then at every bus where the feeder splits into two or more branches that each carry at least `5%` (`BRANCH_SHARE = 0.05`) of the feeder's nominal load, a switch on the first line of each of those branches (after a transformer, the first line beyond it).
- **Non-negotiable freeze:** `BRANCH_SHARE = 0.05` and the placement algorithm are **never adjusted after viewing any IEEE 37-bus model result**. The resulting device list `D1..Dk` and zone membership are deterministic outputs of `placement_rule("ieee37")` recorded in `results/transfer/dataset_ieee37.json` (not run yet).
- **In-line step-down transformer (`4.8 kV / 0.48 kV`):** If a dead-end `0.48 kV` secondary bus (e.g., behind the in-line transformer) has no downstream line and carries `< 5%` load, it naturally stays inside its upstream zone without triggering `first_line`; if its presence causes non-convergence or invalid primary-fault behavior in OpenDSS, any handling must be documented transparently in T-22 before model evaluation.

### 3.3 Fault simulation on a 3-wire ungrounded delta grid (`ASSUMPTION`)
- **Fault types & OpenDSS specs:** Retain the exact four fault types and OpenDSS `Fault` commands from `shf/faults.py` and `shf/active_grid.py`:
  - `SLG`: `phases=1 bus1=<bus>.<p> bus2=<bus>.0 r=<r>` for each phase `p ∈ bus_phases(bus)`.
  - `LL`: `phases=1 bus1=<bus>.<p> bus2=<bus>.<q> r=<r>` for each phase pair `(p, q) ∈ {(1,2), (2,3), (3,1)}`.
  - `LLG`: `phases=2 bus1=<bus>.<p>.<q> bus2=<bus>.0.0 r=<r>` for each phase pair `(p, q)`.
  - `3PH`: `phases=3 bus1=<bus>.1.2.3 bus2=<bus>.0.0.0 r=<r>` when `bus_phases(bus) == [1, 2, 3]`.
- **No artificial grounding added:** **ASSUMPTION:** Do **not** add an artificial zig-zag or wye-grounded substation earthing transformer to force IEEE 37-bus to behave like a 4-wire grounded feeder. Preserving the unmodified 3-wire ungrounded delta grounding is essential so the test genuinely measures cross-grounding generalization (and reveals SLG failure honestly if it occurs).
- **Operating point & measurement noise (unchanged from `shf/config.py`):**
  - Load multiplier `LoadMult ~ Uniform(0.3, 1.1)`; per-spot-load spread `N(1.0, 0.20)` clipped to `[0.3, 1.7]`.
  - Passive sweep: `SCENARIOS_PER_CASE = 3`, `seed = 0`. Active sweep: `scenarios_per_topo = 1`, `seed = 0`.
  - Regulator taps free pre-fault (`controls=True`), frozen during the fault (`controls=False`).
  - Instrument-transformer noise: `1%` magnitude and `0.5°` angle (`1σ`, independent per sample).
  - Non-converged OpenDSS snapshots are excluded from training/evaluation and their exact count and share are reported in the dataset summary JSON.

### 3.4 Voltage-normalized resistance range for 4.8 kV (`ASSUMPTION`)
- **Passive transfer study (`shf/transfer.py`):** Uses the exact `shf/config.py` resistances:
  - `SLG_RESISTANCES = [0.01, 1, 5, 10, 25, 50, 100, 200, 400] Ω`
  - `PHASE_RESISTANCES = [0.01, 0.5, 2] Ω`
- **Active-grid study (`shf/active_grid.py`):** Because `4.8 kV` is close in voltage base to IEEE 123-bus `4.16 kV` (`(4.8 / 4.16)² = 1.331×`, unlike `24.9 kV` at `35.8×`), **ASSUMPTION:** use the same 4 kV-class resistance grid on IEEE 37-bus:
  - `SLG_R_BY_FEEDER["ieee37"] = [0.01, 1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 200.0, 400.0] Ω`
  - `PHASE_R_BY_FEEDER["ieee37"] = [0.01, 0.5, 2.0] Ω`
- **Physics verification before modeling (T-22):** Extend `scripts/signal_to_load.py` to measure IEEE 37-bus feeder-head current and SLG fault current at `0.01, 1.0, 10.0, 100.0, 400.0 Ω` (recorded in `results/transfer/signal_to_load.json` with provenance) so the exact capacitive-return signal-to-load ratio is documented from OpenDSS rather than estimated.

### 3.5 Inverter-based DERs (`ASSUMPTION`, `Generator Model=7`, 0–50% penetration)
- **Model:** 3-phase current-limited inverter-based DERs modeled with OpenDSS `Generator Model=7`, `kv=4.8`, `pf=1.0`, `vminpu=0.80`, `vmaxpu=1.15`, `conn=delta` (delta-connected so DERs do not introduce an artificial neutral-ground path onto the 3-wire ungrounded feeder).
- **Placement rule (fixed before T-22):** Place **3 DER units** on 3 distinct 4.8 kV zones produced by `placement_rule("ieee37")`:
  - Select 3 distinct non-head zones with the largest nominal load (falling back to the head zone away from the substation bus only if fewer than 3 non-head zones exist).
  - Within each selected zone, pick one 3-phase 4.8 kV primary bus near the zone's electrical midpoint / main trunk.
  - Lock the 3 chosen bus names and OpenDSS nominal feeder kW in `shf/active_grid.py:DER_SPECS["ieee37"]` during T-22 **before** any model is evaluated, and never change them afterward.
- **Penetration sampling:** Identical to IEEE 123-bus and 34-bus: feeder-wide DER penetration `Uniform(0%, 50%)` of OpenDSS nominal feeder load, with per-DER irradiance spread `N(1, 0.25)` clipped to `[0.1, 1.5]` and normalized.

### 3.6 Dynamic topologies and adjacent tie `Tie37` (`ASSUMPTION`)
- **Adjacent feeder tie (`IEEE37_ADJACENT_DSS`):** Mirroring `Sw9` on IEEE 123-bus and `Tie34` on IEEE 34-bus, add a normally-open 4.8 kV 3-phase adjacent feeder tie `Line.Tie37` (`switch=yes`, `r1=1e-3`, `r0=1e-3`, `x1=0`, `x0=0`, `c1=0`, `c0=0`, `length=0.001`) backed by a `4.8 kV` adjacent source (`pu=1.02`) through an adjacent 4.8 kV underground cable trunk, connected to a 3-phase 4.8 kV tail bus in the electrically deepest downstream zone `D_tail` of `placement_rule("ieee37")`.
  - **Delta-grounding note (`ASSUMPTION`):** Configure the adjacent source / tie interface (`conn=delta` transformer or matching ungrounded/high-Z0 source impedance so it does not act as a solidly grounded neutral source when `Tie37` closes), or document the exact OpenDSS `Vsource` grounding behavior in T-22 so any difference between `normal` and `reconfig_tie`/`looped_tie` SLG behavior is physically transparent.
- **Three topologies (mirroring IEEE 34-bus):**
  1. `normal`: all sectionalizers `D1..Dk` closed; `Tie37` open.
  2. `reconfig_tie`: one mid-trunk sectionalizer `D_mid` (upstream on the path from `D1` to `D_tail`) open, `Tie37` closed (two-source split feeder with reversed back-feed through `Tie37`).
  3. `looped_tie`: all sectionalizers `D1..Dk` closed + `Tie37` closed (two-source closed loop — non-tree).
- Exact `D_mid`, `D_tail`, and tie attachment bus are locked in `shf/active_grid.py:TOPOLOGIES["ieee37"]` during T-22 before any model runs.

### 3.7 Non-fault operational transients (`ASSUMPTION`, `class = NO_FAULT`, ~15% share)
- **Target share:** `nofault_share = 0.15` (same as IEEE 123-bus and 34-bus).
- **No artificial capacitor banks:** Because the standard IEEE 37-bus test feeder contains **no shunt capacitor banks**, we do **not** add synthetic capacitors and we do **not** mislabel `load_step` events as `cap_switch`. Instead, `NO_FAULT` events on IEEE 37-bus are split **50% / 50%** between:
  1. `pv_cloud`: sudden 50–85% drop in DER output (enforcing pre-event penetration `≥ 10%`, sampled in `[15%, 50%]` if lower, identical to `shf/active_grid.py`), and
  2. `load_step`: sudden `+30%` to `+80%` jump on 1–4 random spot loads (identical to `shf/active_grid.py`).
- `nofault_breakdown["cap_switch"]` is explicitly `0`.

### 3.8 Models, features, and conformal setup (frozen from IEEE 123-bus)
- **Passive Stage-1 (`shf/transfer.py`, `shf/transfer_models.py`):** Exact 21 relative/structural node features; evaluate frozen IEEE 123-bus `PerNodeGBDT` and `ZoneTreeGNN` (`models/transfer/`, hyperparameters frozen in `results/transfer/phase2_ieee123.json`), graph FPI baseline, 5-fold GroupKFold in-domain CV on IEEE 37-bus, and few-shot fine-tuning at **5%** and **20%** of IEEE 37-bus buses (10 random bus splits, same protocol as `scripts/transfer_eval34.py`).
- **Passive Stage-2 (`shf/bus_locator.py`):** Random-in-zone analytical baseline, zero-training 3-phase Takagi reactance using OpenDSS 3×3 `Z_path`, and `BusGraphGNN` (zero-shot from 123-bus and in-domain 5-fold CV), evaluated on top of Stage-1 predicted zones and oracle zones.
- **Active-grid (`shf/active_grid.py`, `shf/active_models.py`, Kaggle GPU):** Exact 26 relative/directional/state node features and 4 directed edge features; train `ActivePerNodeGBDT` and `ActiveGridGATv2` **strictly on active IEEE 123-bus** (same 5-fold GroupKFold hyperparameter selection on 123-bus only), then evaluate on active IEEE 37-bus: `active_fpi`, zero-shot, few-shot **5%** and **20%** (5 repeats), and in-domain 5-fold GroupKFold CV.
- **Split Conformal Prediction (`scripts/active_conformal_posthoc.py`, `aps_rand` at 95%):**
  - Primary pre-registered score: **randomized APS (`aps_rand`)** at `1 - α = 0.95` (`U_SEED = 12345`), selected based on Addendum A of `research/active-grid-gnn/PLAN.md` (where `aps_det` was shown to be degenerate). Also log `lac` and `aps_det` (and `1 - α = 0.90`) to verify non-degeneracy (`90%` vs `95%` sets differ).
  - Regimes: (a) frozen `q̂` from IEEE 123-bus OOF applied zero-shot to IEEE 37-bus (carries **no** exchangeability guarantee, reported transparently); (b) recalibrated `q̂` on **5%** of IEEE 37-bus fault buses + 5% of `NO_FAULT` events (10 repeats, zero weight retraining); and (c) calibration-size sweep (**5%, 10%, 20%, 30%, 40%** of IEEE 37-bus fault buses + matching `NO_FAULT` share, 50 random draws, seed 0, mirroring Addendum B1).
- **Output isolation:** All IEEE 37-bus outputs are written to dedicated files/folders (`results/transfer/dataset_ieee37.json`, `phase3_ieee37.json`, `phase2b_bus_ieee37.json`, `results/active_grid_ieee37/*.json`, and `data/generated/active_grid_ieee37_probs.npz`) with `shf.provenance.record()`, never overwriting existing IEEE 123-bus / 34-bus results.

## 4. Pre-committed success criteria (fixed before any run)

Every criterion below is evaluated strictly once on the real run outputs. Failing a criterion is reported as a failure with its physical explanation — never hidden or patched by tuning on IEEE 37-bus.

### 4.1 Passive transfer — Stage-1 zone location (`results/transfer/phase3_ieee37.json`)
1. **P1-Main (Zero-shot overall):** Zero-shot zone accuracy on IEEE 37-bus exceeds FPI by **≥ +15.0 percentage points** AND sits within **10.0 percentage points** of the IEEE 37-bus 5-fold in-domain CV upper bound for the same model.
2. **P1-Partial (Physics-bounded delta transfer):** If P1-Main fails *solely because of ungrounded-delta SLG degradation*, classify as **physics-bounded partial transfer** if on **phase faults (`LL`, `LLG`, `3PH` combined)** zero-shot exceeds FPI by **≥ +15.0 points** AND stays within **10.0 points** of the phase-fault in-domain upper bound.
3. **P1-FewShot (Adaptation at 5% and 20% of buses):** Few-shot fine-tuning (5% or 20% of IEEE 37-bus buses, mean over 10 bus splits) is judged **effective** if it closes **≥ 50%** of the gap between zero-shot and the IEEE 37-bus in-domain upper bound without regressing missing-sensor mean accuracy below zero-shot by more than 5 points.
4. **P1-Fail:** Zero-shot fails to exceed FPI by `+15.0` points both overall and on phase faults (`LL/LLG/3PH`), OR 20% few-shot closes `< 50%` of the gap to in-domain CV. Report honestly as failure of passive transfer to an underground delta feeder, with the full `3PH / LL / LLG / SLG`, resistance, and 1-sensor-offline breakdown.

### 4.2 Passive transfer — Stage-2 bus ranking (`results/transfer/phase2b_bus_ieee37.json`)
1. **P2-Main (Overall Takagi):** Zero-training 3-phase Takagi reactance (`shf/bus_locator.py`) exceeds the analytical random-in-zone baseline by **≥ +15.0 percentage points on Top-3 bus accuracy** overall.
2. **P2-Partial (Phase-fault Takagi):** If ungrounded-delta SLG breaks the grounded-loop reactance formula, classify as **phase-fault-only success** if Takagi exceeds random-in-zone by **≥ +20.0 percentage points on Top-3 bus accuracy on phase faults (`3PH / LL / LLG`)**.
3. **P2-Fail:** Takagi clears neither margin (e.g., short underground cable `ΔX1`, low `X/R`, or capacitive distortion dominates). Report exact Top-1/Top-3 overall, by fault type, by SLG resistance, and top confused bus pairs (`ΔX1`) alongside `BusGraphGNN`.

### 4.3 Active-grid transfer (`results/active_grid_ieee37/`)
1. **A1 (Legacy FPI stress check):** On active IEEE 37-bus, `active_fpi` overall accuracy drops **below 55.0%** OR its `NO_FAULT` FPR exceeds **15.0%** (verifying that active underground delta operation breaks legacy overcurrent FPI).
2. **A2-Main (Zero-shot active transfer):** Trained ONLY on active IEEE 123-bus, at least one model (`ActiveGridGATv2` or `ActivePerNodeGBDT`) achieves zero-shot overall accuracy **≥ +25.0 percentage points above `active_fpi`** AND `NO_FAULT` FPR **≤ 5.0%** on active IEEE 37-bus. Whichever of `ActiveGridGATv2` vs `ActivePerNodeGBDT` leads (overall, on `looped_tie`, high DER `30–50%`, `NO_FAULT` FPR, and 1 sensor offline) is reported as the finding.
3. **A2-Partial (Adaptation / delta-bounded):** Zero-shot beats `active_fpi` by **≥ +15.0 points** overall (or **≥ +25.0 points** on `LL/LLG/3PH`), OR **20% few-shot** closes **≥ 50%** of the gap to the IEEE 37-bus in-domain 5-fold CV upper bound while lowering `NO_FAULT` FPR relative to zero-shot.
4. **A2-Fail:** Zero-shot fails to clear `+15.0` points over `active_fpi` both overall and on phase faults. Report honestly with breakdown by topology (`normal`, `reconfig_tie`, `looped_tie`), DER penetration, fault type, and `NO_FAULT` kind (`pv_cloud` vs `load_step`).

### 4.4 Split Conformal Prediction (`aps_rand` at 95%, `α = 0.05`)
1. **Non-degeneracy gate (prerequisite):** `90%` and `95%` prediction sets must differ, and on the calibration feeder (IEEE 123-bus cross-conformal) coverage must lie within `±3.0` points of the target (`92.0%–98.0%`).
2. **A3-ZeroShot (`q̂` frozen from 123-bus):** Reported without claiming a formal guarantee (calibration and test feeders are not exchangeable).
3. **A3-Recal (Recalibrated on IEEE 37-bus, zero weight retraining):**
   - **Pass:** Recalibrated `aps_rand` at `1 - α = 0.95` achieves **mean empirical coverage ≥ 94.5%** AND **10th-percentile coverage ≥ 92.0%** across random bus draws, while **singleton (`|C| = 1`) accuracy strictly exceeds raw argmax accuracy** and **autonomous `NO_FAULT` trip share is strictly below raw `NO_FAULT` FPR**.
   - Report the smallest calibration share in `{5%, 10%, 20%, 30%, 40%}` (50 draws, seed 0) that satisfies both coverage bars; if **no** share up to `40%` meets the criterion, report that recalibration on up to 40% of IEEE 37-bus buses is insufficient.
   - Regardless of outcome, the claim stays strictly bounded: a **simulated decision-support act/defer gate**, not a protection guarantee.

## 5. Guards against leakage and honesty commitments

1. **Strict zero-leakage firewall:**
   - IEEE 37-bus data is **never** used to train IEEE 123-bus models, design features, select architectures, or tune hyperparameters.
   - `PLACEMENT_RULE` (`BRANCH_SHARE = 0.05`), resistance grids, DER placement rule, `Tie37` topology rule, and `NO_FAULT` setup are locked before viewing any IEEE 37-bus ML result.
   - Every in-domain CV, few-shot fine-tuning, and conformal recalibration split on IEEE 37-bus is strictly **grouped by fault bus** (zero bus overlap between train/calibration and test; `NO_FAULT` events split disjointly).
2. **Simulation-only boundary:**
   - Pure steady-state phasor OpenDSS simulation on a standard IEEE test case — no field recordings, no utility deployment, no EMTP electromagnetic transients, no CT saturation, no live SCADA loop.
3. **No invented numbers & full provenance:**
   - Every result file in `results/transfer/` and `results/active_grid_ieee37/` must be generated by a script and logged via `shf.provenance.record()`. Never edit result JSONs by hand or write placeholder/estimated numbers.
   - Before each stage runs, prose and dashboards must state explicitly **"not run yet"** (or **"pending Kaggle GPU run"** for the active-grid stage).
4. **Keep worse results intact and explain the physics:**
   - If IEEE 37-bus results are substantially lower than IEEE 123-bus or IEEE 34-bus, **keep the exact measured numbers unmodified** and explain the physical mechanisms (ungrounded 3-wire delta capacitive SLG return, `√3` pu neutral shift, compact underground cable `ΔX1` and low `X/R`, unbalanced delta loads, and `load_step` vs HIF ambiguity).

---

## 6. Results (Simulation only; no field data)

### 6.1 OpenDSS integration & signal-to-load measurement (T-22 — completed)
- **Files:** `results/transfer/signal_to_load.json` (provenance `signal_to_load.json`), `results/transfer/dataset_ieee37.json` (provenance `transfer_sweep_ieee37.json`).
- **Passive sweep:** `5,184` fault events (`3` scenarios × `1,728` cases across `36` buses and `10` zones `D1`–`D10`), **`5,184 / 5,184` (`100.0%`) converged** in `35.5 s`.
- **SLG capacitive return confirmed:** At nominal load (`369.5 A` at `D1`/`l35`), bolted `0.01 Ω` SLG fault current has median **`2.36 A` (`0.64%` of head current)**, and `400 Ω` SLG has median **`2.23 A` (`0.60%` of head current)**, accompanied by neutral-voltage rise (`> 1.4 pu` on unfaulted phases) while `LL`/`3PH` faults draw `> 500 A`.

### 6.2 Passive transfer — Stage-1 zone location on CPU (T-23 — completed)
- **File:** `results/transfer/phase3_ieee37.json` (provenance `transfer_phase3_ieee37.json`). Frozen IEEE 123-bus models (`models/transfer/`) evaluated unchanged on `5,184` IEEE 37-bus events (`2,268` phase faults `3PH/LL/LLG` + `2,916` `SLG` faults).

| Model / regime | Overall acc | Phase faults (`3PH/LL/LLG`) | `SLG` (`0.01–400 Ω`) | Missing-sensor mean |
|---|---:|---:|---:|---:|
| Graph FPI baseline (`no_flagged = 57.04%`) | `42.96%` | `98.19%` | `0.00%` | `38.66%` |
| **Zero-shot `PerNodeGBDT`** (frozen 123-bus) | `56.37%` | **`100.00%`** | `22.43%` (`20.4%–25.6%`) | `48.70%` |
| **Zero-shot `ZoneTreeGNN`** (frozen 123-bus) | `46.72%` | **`99.65%`** | `5.56%` (flat `5.56%`) | `44.21%` |
| Few-shot 5% (`2` train / `34` test buses, 10 splits) — GBDT | `45.21% ± 12.18%` | `~74%` (`75.2/75.2/72.4%`) | `22.82%` | `39.76%` (`-8.94` pts) |
| Few-shot 5% (`2` train / `34` test buses, 10 splits) — GNN | `51.44% ± 3.50%` | `>99.0%` (`99.0/99.5/99.0%`) | `14.28%` | `46.97%` (`+2.76` pts) |
| Few-shot 20% (`7` train / `29` test buses, 10 splits) — GBDT | `55.14% ± 5.33%` | `~86%` (`85.6/88.0/85.1%`) | `30.81%` | `49.20%` (`+0.49` pts) |
| Few-shot 20% (`7` train / `29` test buses, 10 splits) — GNN | `66.00% ± 3.71%` | `>99.2%` (`99.2/99.2/99.4%`) | `40.12%` | `59.62%` (`+15.41` pts) |
| In-domain 5-fold GroupKFold CV (IEEE 37-bus) — GBDT | `91.44%` (`std 4.10%`) | `99.65%` | `85.05%` | `83.52%` |
| In-domain 5-fold GroupKFold CV (IEEE 37-bus) — GNN | `87.98%` (`std 6.86%`) | `98.72%` | `79.63%` | `81.81%` |

- **Pre-committed Stage-1 verdict (Section 4.1): `P1-Fail` for both `PerNodeGBDT` and `ZoneTreeGNN`.**
  - **`P1-Main` failed:** Zero-shot overall accuracy reaches `56.37%` (`+13.41` pts over FPI, `-35.07` pts vs in-domain `91.44%`) for `PerNodeGBDT` and `46.72%` (`+3.76` pts over FPI, `-41.26` pts vs in-domain `87.98%`) for `ZoneTreeGNN` — both miss the `+15.0` pt margin over FPI and the `≤ 10.0` pt gap to in-domain CV.
  - **Physical cause (ungrounded 3-wire delta SLG breakdown):** As predicted in Section 1.4 before running, `SLG` faults (`56.25%` of all events) drive the entire collapse. Because ungrounded delta cables return only `~2.3 A` (`~0.6%` of head current) capacitively from healthy branches while shifting unfaulted phase-to-ground voltages toward `√3 pu`, legacy FPI detects **`0.0%`** of SLG faults, frozen `ZoneTreeGNN` collapses to predicting `D1` (`5.56% = 2/36` buses), and frozen `PerNodeGBDT` achieves only `22.43%`. Yet in-domain 5-fold CV reaches `85.05%` (GBDT) / `79.63%` (GNN) on SLG, proving the 21 relative features *do* contain localizable neutral-shift / capacitive signatures once a model has seen ungrounded-delta training data.
  - **Phase faults generalize nearly perfectly (why strict `P1-Partial` still reads `false`):** On phase faults (`3PH/LL/LLG`), frozen 123-bus `PerNodeGBDT` achieves **`100.00%`** (`0` errors in `2,268` events) and `ZoneTreeGNN` achieves **`99.65%`** (exceeding its own 37-bus in-domain CV of `98.72%`). Strict `P1-Partial` reads `false` solely because legacy FPI already achieves `98.19%` on 4.8 kV low-resistance radial phase faults, leaving only `+1.81` pts of mathematical headroom against the pre-committed `+15.0` pt bar.
  - **Few-shot contrast (`P1-FewShot`):** `ZoneTreeGNN` adapts cleanly without catastrophic forgetting, keeping `>99%` phase-fault accuracy while climbing from `46.72%` → `51.44%` (5%) → `66.00%` (20%, closing `46.73%` of the gap — just below the `50.0%` threshold — and improving missing-sensor mean by `+15.41` pts). By contrast, warm-start `PerNodeGBDT` *regresses* on 5% (`45.21%`) and 20% (`55.14%`) because `2` or `7` sampled buses span only a subset of the 10 zones and binary node-level boosted trees overfit the sampled zones, damaging phase-fault accuracy (`100%` → `~74%` at 5%, `~86%` at 20%).

### 6.3 Passive transfer — Stage-2 bus ranking on CPU (T-23 — completed)
- **File:** `results/transfer/phase2b_bus_ieee37.json` (provenance `transfer_phase2b_ieee37.json`). Evaluated on `5,184` IEEE 37-bus events (`36` buses across `10` zones; `BusGraphGNN` trained on IEEE 123-bus only).

| Stage-2 method | Overall Top-1 | Overall Top-3 | Phase faults (`3PH/LL/LLG`) Top-1 / Top-3 | `SLG` Top-1 / Top-3 |
|---|---:|---:|---:|---:|
| Random-in-zone (Stage-1 predicted zone, `56.37%` zone acc) | `16.97%` | `42.08%` | `27.78%` / `69.44%` | `8.57%` / `20.79%` |
| **3-phase Takagi reactance** (zero training, Stage-1 pred zone) | `38.41%` | `53.38%` (`+11.30` pts) | **`75.04%` / `94.36%`** (`+24.92` pts) | `9.91%` / `21.50%` |
| **Zero-shot `BusGraphGNN`** (123-bus only, Stage-1 pred zone) | `37.19%` | `53.88%` (`+11.80` pts) | **`72.84%` / `95.24%`** (`+25.80` pts) | `9.47%` / `21.71%` |
| In-domain 5-fold CV `BusGraphGNN` (37-bus, Stage-1 pred zone) | `19.81%` | `48.51%` | `43.08%` / `83.82%` | `1.71%` / `21.06%` |
| *Diagnostic — Oracle zone:* Random-in-zone | `27.78%` | `69.44%` | `27.78%` / `69.44%` | `27.78%` / `69.44%` |
| *Diagnostic — Oracle zone:* 3-phase Takagi reactance | `50.96%` | `81.54%` (`+12.09` pts) | `75.04%` / `94.36%` (`+24.92` pts) | `32.24%` / `71.57%` |
| *Diagnostic — Oracle zone:* Zero-shot `BusGraphGNN` | `48.73%` | `81.48%` (`+12.04` pts) | `72.84%` / `95.24%` (`+25.80` pts) | `29.97%` / `70.78%` |

- **Pre-committed Stage-2 verdict (Section 4.2): `P2-Partial` (phase-fault-only success).**
  - Zero-training 3-phase Takagi reactance exceeds random-in-zone by **`+24.92` percentage points** on phase-fault Top-3 (`94.36%` vs `69.44%`, clearing the `+20.0` pt `P2-Partial` threshold on both Stage-1 predicted zones and oracle zones), and zero-shot `BusGraphGNN` reaches **`95.24%`** Top-3 (`+25.80` pts).
  - Overall Top-3 margin (`+11.30` pts on Stage-1 predicted zones; `+12.09` pts on oracle zones) falls short of the `+15.0` pt `P2-Main` bar because ungrounded-delta SLG capacitive return violates the grounded-loop Takagi equation (even with oracle zones, SLG Top-3 is `71.57%` vs `69.44%` random) and compact underground cables have very small adjacent-bus reactances (top oracle confusions: `775↔734` `ΔX1 = 0.1061 Ω`, `701↔702` `ΔX1 = 0.0599 Ω`, `728↔729` `ΔX1 = 0.0077 Ω`).
  - Note on small-feeder CV: In-domain 5-fold GroupKFold `BusGraphGNN` (`48.51%` Top-3) underperforms zero-shot `BusGraphGNN` (`53.88%` Top-3) because splitting only `36` buses across `10` zones leaves very few in-zone training buses per fold.

### 6.4 Active-grid transfer & `aps_rand` conformal analysis on Kaggle GPU (T-24 — completed)
- **Files:** `results/active_grid_ieee37/{dataset_summary, phase_active_ieee123, phase_active_ieee37, conformal_safety, conformal_posthoc, conformal_calsize}.json` (provenance `active_grid_ieee37.json`, `active_conformal_posthoc_ieee37.json`, `active_conformal_calsize_ieee37.json`; SHA-256 verified locally with `shf.provenance.verify()`: 0 changed, 0 missing, 0 unrecorded). Kaggle kernel `christoopherchau/self-healing-feeder-active-ieee37`, CUDA, `runtime_s = 1452.8`.
- **Dataset:** `6,099` active IEEE 37-bus events, `6,097` converged (`99.97%`): `5,182` faults + `915` `NO_FAULT` (`459` `pv_cloud`, `456` `load_step`, `0` `cap_switch`).
- **Hyperparameters frozen from active IEEE 123-bus only:** GBDT `L63, lr 0.05, 300 iter`; GATv2 `2 layers, h=64, 4 heads`.

| Model / regime (active IEEE 37-bus) | Overall | `NO_FAULT` FPR | Phase faults | `SLG` | 1 sensor offline |
|---|---:|---:|---:|---:|---:|
| `active_fpi` | `44.5%` | `0.0%` | `79.4%` | `0.0%` | `41.6%` |
| Zero-shot `ActivePerNodeGBDT` | `55.4%` | `3.4%` | `93.1%` | `13.2%` | `49.6%` |
| Zero-shot `ActiveGridGATv2` | `46.2%` | `11.8%` | `88.4%` | `0.2%` | `44.3%` |
| Few-shot 5% / 20% — GBDT (5 repeats) | `45.3%` / `62.0%` | `23.2%` / `14.3%` | – | – | – |
| Few-shot 5% / 20% — GATv2 (5 repeats) | `55.3%` / `76.2%` | `5.0%` / `1.4%` | – | – | – |
| In-domain 5-fold CV — GBDT | `88.3%` | `1.5%` | `96.6%` | `78.6%` | `81.3%` |
| In-domain 5-fold CV — GATv2 | `85.7%` | `3.3%` | `97.6%` | `72.9%` | `80.8%` |

- **Pre-committed verdicts (Section 4.3):**
  - **A1 met:** `active_fpi` overall `44.5%` `< 55.0%`.
  - **A2-Partial (overall):** `ActivePerNodeGBDT` is `A2-Fail` (`+10.9` pts over FPI overall, `+13.6` pts on phase faults; 20% few-shot closes only `19.9%` of the gap). `ActiveGridGATv2` is `A2-Partial`: zero-shot is only `+1.7` pts over FPI, but **20% few-shot closes `76.0%` of the gap** to in-domain CV while cutting `NO_FAULT` FPR from `11.8%` to `1.4%`.
  - **Physics:** the same ungrounded-delta capacitive SLG return as in 6.2 drives the zero-shot collapse (`SLG` `13.2%` GBDT, `0.2%` GATv2, `0.0%` FPI), while in-domain CV reaches `78.6%` / `72.9%` on SLG.

- **Split Conformal (Section 4.4, `aps_rand` at 95%):**
  - **Non-degeneracy gate passed** for both models (90% and 95% sets differ; 123-bus cross-conformal coverage `95.0%` GBDT and `95.0%` GATv2). `aps_det` again saturates (GATv2 sets `6.37` labels on 123-bus, `8.01` on 37-bus), as in Addendum A of `research/active-grid-gnn/PLAN.md`.
  - **A3-ZeroShot (no guarantee):** the frozen 123-bus `q̂` covers `47.4%` (GATv2) and `81.1%` (GBDT) on active IEEE 37-bus.
  - **5% recalibration (2 fault buses, 10 repeats):** mean coverage `94.1%` (GATv2) and `93.9%` (GBDT); worst draw `86.2%` and `88.9%`.
  - **A3-Recal calibration-size sweep (50 draws):** 5% of buses gives mean `93.1%` (GATv2) / `92.8%` (GBDT) — fails. **Smallest share meeting both bars is 20% (7 fault buses) for both models:** `94.8%` mean / `92.6%` 10th percentile (GATv2) and `94.6%` / `92.0%` (GBDT). At 20%, singleton accuracy (`98.2%` GATv2, `99.4%` GBDT) exceeds raw argmax (`46.2%`, `55.4%`) and autonomous `NO_FAULT` trip share (`0.85%`, `0.0%`) is below raw FPR (`11.8%`, `3.4%`). **A3-Recal: Pass at 20%.**
  - Claim stays bounded: a simulated decision-support act/defer gate, not a protection guarantee.
