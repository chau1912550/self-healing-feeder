# Self-Healing Feeder: ML Fault Location and Automated Restoration

A student-scale version of the **FLISR** (Fault Location, Isolation and Service Restoration) systems that utilities such as EPB Chattanooga and Duke Energy run on their distribution grids, built on the **IEEE 123-bus test feeder** in **OpenDSS**.

When the feeder-head recloser locks out, a crew without fault location has to patrol the whole feeder. This project asks two questions:

1. Using only measurements that reclosers and automated switches already record, can a model tell **which switching zone** the fault is in, including high-impedance faults that conventional fault indicators miss?
2. Once the zone is known, can we **isolate it and restore every other zone** automatically, closing a tie switch only when a power flow shows voltages and currents stay within limits?

## 🌐 [chau1912550.github.io/self-healing-feeder](https://chau1912550.github.io/self-healing-feeder/)

**👉 Open it: [English](https://chau1912550.github.io/self-healing-feeder/?lang=en) · [Tiếng Việt](https://chau1912550.github.io/self-healing-feeder/?lang=vi)** — one page with every result of the latest run: a clickable 3D model of the feeder, 17 questions & answers, a glossary, and the full dataset with its formulas and reasoning. Nothing to install; it works on a phone.

**🕹️ [Monitor demo](https://chau1912550.github.io/self-healing-feeder/monitor/)**: work a simulated fault as the dispatcher, field crew, engineer or manager, each with its own view and steps ([how it works](docs/monitor/README.md)).

**📄 [Technical study](https://chau1912550.github.io/self-healing-feeder/study/)** ([Tiếng Việt](https://chau1912550.github.io/self-healing-feeder/study/?lang=vi)): for readers with a technical background. The same study written like a paper: problem, hypotheses, test system, method, validation, results, error analysis, restoration, limits and how to reproduce it, with a 3D feeder and a step-by-step fault replay. Every number on it is filled from `results/` by [`scripts/build_study_site.py`](scripts/build_study_site.py). Vietnamese study guide with worked examples: [`docs/vi/study-guide.md`](docs/vi/study-guide.md).

[![Run report: the Monitor button, the 30-second tour of what the project does, and the order to read the page](docs/images/report-overview.png)](https://chau1912550.github.io/self-healing-feeder/)

[![Run report: headline numbers and run checks](docs/images/report-headline.png)](https://chau1912550.github.io/self-healing-feeder/#health)

<details>
<summary><b>More screenshots</b>: explain guide, fault location, error analysis, restoration, questions &amp; answers</summary>

![The 3D feeder model: zones, one wire per phase, poles, transformers, switches, regulators and the substation](docs/images/report-3d.png)

![The 3D error map: red columns where faults get misplaced, arrows from the true zone to the wrong guess](docs/images/report-3d-errors.png)

![The explain guide circling the accuracy card and explaining it](docs/images/report-explain.png)

![Accuracy vs fault resistance for the three methods](docs/images/report-fault-location.png)

![Per-zone miss and false-blame rates and the confusion matrix](docs/images/report-error-analysis.png)

![Isolation and restoration result for each fault zone](docs/images/report-restoration.png)

![Searchable questions and answers with one answer open](docs/images/report-faq.png)

</details>

### How to open it

| You want to… | Do this |
|---|---|
| Just look at the results | Click the link above. Hover (or tap) a chart point or matrix cell to see the exact number; the links under the title jump to each section. |
| Open it from your own copy | After `git clone`, double-click [`docs/index.html`](docs/index.html). It is one self-contained file, so it opens in any browser with no server and no internet. |
| Refresh it after changing the study | `python run.py` rebuilds the page at the end. To rebuild from the existing `results/` only, run `python -m shf.dashboard` (about 1 second). |
| Publish your own copy | Fork the repo, then **Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main`, folder `/docs` → Save**. After about a minute the page is live at `https://<your-username>.github.io/self-healing-feeder/`. |

### What the page gives you

| Feature | What it does |
|---|---|
| **30-second tour** | First thing on the page: a sketch of a feeder plays the project in five steps (a fault, the blackout, the model naming the zone, isolate and restore, the crew going straight there) with this run's numbers, then lists what to read next and in what order. Pause, replay, or click a step. |
| **Monitor card** | Right under the tour: what the Monitor is, how to use it in three steps (pick a role, open a fault, follow *How to handle*) and a note that it replays this run's faults and is not connected to real equipment. |
| **Explain guide** | Always on: click any card, chart or table (or its **?**) and a small guide flies there, circles it and says what it is, how to read it and why it matters. **← / →** walk through every part, **Esc** closes, and `?explain=heat` in a link opens the guide on one part. |
| **3D feeder model** | The whole feeder in 3D, built from the study's data: wooden poles with crossarms and insulators, one wire per phase, pole-top transformers, load columns sized by kW, recloser, switches (added ones carry a radio antenna), open ties with raised red blades, regulators, capacitor banks and the substation yard. Drag to rotate; click a zone or part and it lifts out while the guide explains it; **Tour the zones** walks through all 10; label layers (zones, equipment, bus numbers) and a **2D map** view. three.js loads only when the section comes on screen. |
| **Model errors** layer | Shows *where* the model goes wrong: a red column on every bus where faults get misplaced (taller = more, redder = higher rate), a green dot where none are, and arrows from each true zone to the zone it is mistaken for (Sw2 → Sw1: 41 faults…). Click a column or arrow for the numbers, including how conventional fault indicators do on the same bus. |
| **Fault replay** layer | Click anywhere on the feeder (or pick "a missed fault") and the model replays it in 6 steps: the fault flashes, Sw1 locks out and the feeder goes dark, the model names a zone (an orange arrow if it is wrong, with why), switches open to isolate, Sw1 re-closes, and ties close to restore what the power flow allows. Every switch has a lamp: green closed, red open. |
| **Data & method** | Download the full simulated dataset (11,448 faults × 158 columns, plus a 300-row sample) and every result file from [`docs/data/`](docs/data/), with a column dictionary, the formulas behind each number, and the nine-step reasoning from the question to the result. |
| **EN / VI** button | Switches every text, chart label and tooltip between English and Vietnamese. Add `?lang=vi` or `?lang=en` to a link to share it in one language. |
| **Run checks** | Pass / Watch / Fail summary of the run, so you know whether to trust the numbers before reading on. |
| **In short** boxes | One plain-language sentence at the top of each section. |
| Dotted-underlined words | Hover or tap for a one-line definition (FLISR, FNR, pu, radial…); all of them are also listed in the **Glossary**. |
| Hover / tap on charts | Exact numbers for every point, bar and matrix cell; “Show as table” gives the same data as a table. |
| **Questions & answers** | 17 questions a reviewer or interviewer is likely to ask, answered with this run's numbers. Search (Vietnamese with or without accents), filter by topic, open all, or copy a link to one question. |
| Top bar | The orange square **Monitor** button (note under it: *Try handling a fault*) opens the role-based outage demo; the links jump to any section and highlight where you are; ◐ switches auto / light / dark theme (`?theme=light` works in links too). |
| Print | Prints cleanly with every answer expanded. |

### How to read it

- **Run checks** tell you whether to trust the run: **✓ Pass** = the result meets its limit, **! Watch** = a known weak spot, **✕ Fail** = fix before using the numbers. A stale error analysis (built from an older run) shows up here too.
- **Fault location** compares the three methods as ground-fault resistance rises; “Show as table” lists the same numbers.
- **Error analysis** shows, for each zone, how often its faults are missed (FNR) and how often it is wrongly blamed (FPR); in the confusion matrix, rows are the true zone and darker blue cells mean more mistakes.
- **Restoration** lists, for each faulted zone, which ties closed, how much load came back and whether every voltage stayed within 0.95–1.05 pu.

![Switching zones](results/figures/feeder_zones.png)

## Results

All numbers come from `python run.py` and are saved in [`results/metrics.json`](results/metrics.json).

**Fault location** — 11,448 simulated faults (all converged), every fault with its own random load scenario and 1% / 0.5° measurement noise. Validation is grouped by fault bus, so the model is always tested on buses it never saw during training.

| Method | All faults | Line-to-ground, 100 Ω | Line-to-ground, 400 Ω |
|---|---|---|---|
| Conventional fault passage indication (2× peak-load pickup) | 56.1% | 8.4% | 1.0% |
| ML, instantaneous magnitudes only (basic SCADA poll) | 87.5% | 70.8% | 22.4% |
| **ML, magnitudes + pre/post-fault change (device event records)** | **97.7%** | **98.4%** | **76.5%** |

![Accuracy vs fault resistance](results/figures/accuracy_vs_resistance.png)

- **Missing sensor:** with any one of the 10 devices offline, the full model still identifies the zone in 83–96% of faults (worst case: Sw4 offline).
- **Where the model fails:** errors cluster in the zones near the substation (Sw1, Sw2, Sw4, L13). Devices there carry hundreds of amps of load (631.5 A at the feeder head at nominal load), so 1% measurement noise is about as large as the current a 400 Ω fault draws (6.2 A, [`results/transfer/signal_to_load.json`](results/transfer/signal_to_load.json)). See [`results/figures/confusion_ml.png`](results/figures/confusion_ml.png) and the [error analysis](#error-analysis) below.
- **Why the conventional method misses bolted ground faults (30% correct):** a solid phase-to-ground fault collapses that phase's voltage, and single-phase loads beyond the fault drop out. Devices downstream then see a large residual current and raise false ground flags, so the "deepest flagged device" rule points past the real fault. Real schemes add directional elements for this.
- **Patrol length:** after a feeder lockout, a crew without fault location patrols the whole feeder (39.0 kft of line). With the ML zone, the average patrol drops to 5.1 kft (−87%). If the zone is wrong, the model is charged a full patrol.

### Error analysis

Accuracy alone hides which faults are missed and where the wrong answers point, so [`scripts/error_analysis.py`](scripts/error_analysis.py) replays the same grouped cross-validation and breaks down all 259 errors (2.3% of 11,448 faults). Output: [`results/error_analysis/`](results/error_analysis/).

Because the model always names one of 10 zones, false negatives and false positives are counted **per zone, one-vs-rest**: FNR = faults in zone X placed elsewhere, FPR = faults elsewhere placed in X.

| Zone | Faults | FNR | FPR | Precision |
|---|---|---|---|---|
| Sw1 (feeder head) | 1,125 | **5.4%** | **0.90%** | 92.0% |
| Sw2 | 1,494 | 4.5% | 0.57% | 96.2% |
| L13 | 1,557 | 2.8% | 0.48% | 97.0% |
| Sw4 | 1,971 | 2.6% | 0.45% | 97.8% |
| Sw3 | 981 | 1.7% | 0.11% | 98.8% |
| L45, L61, L68, Sw5, L77 (laterals) | 4,320 | ≤ 0.8% | ≤ 0.05% | ≥ 99.4% |

- **What is missed:** 253 of 259 errors are line-to-ground faults, and **237 (92%) are at 200 Ω or more**. The SLG error rate is 0% up to 5 Ω, 0.1% at 10–50 Ω, 1.6% at 100 Ω, 6.3% at 200 Ω and 23.5% at 400 Ω. No three-phase fault was misplaced.
- **Why:** at nominal load a 400 Ω fault on a 2.4 kV phase draws 6.2 A (median over the feeder's buses, OpenDSS), 1.0% of the feeder-head current, so the fault is about the size of the measurement noise. Loading confirms it: the error rate is 0.9% in the lightest third of load scenarios and 4.1% in the heaviest third.
- **Where the wrong answers point:** 64% of errors are off by exactly one zone and 86% stay on the same path from the substation. The largest pairs are Sw2→Sw1 (41), Sw1→Sw2 (24) and L13→Sw1 (23). The model leans **upstream** (51% of errors): when a fault is too small for downstream devices to see, only the feeder-head device still shows a change.
- **Checked and rejected:** faults close to a zone boundary are *not* clearly harder (error rate 1.8–2.7% at every distance from the nearest switch).
- **Deferring low-confidence answers:** wrong answers have a median class probability of 0.90 vs 1.00 for correct ones. Sending predictions below 0.95 to a manual patrol defers 2.8% of faults, raises accuracy on the rest to 99.1% and cuts errors from 259 to 97 (−63%).
- **For comparison, conventional FPI** raises no flag at all on 25.8% of faults (true missed detections) and over-flags Sw5 (FPR 12.6%, precision 38.8%).
- **Not measured:** the dataset holds only faulted cases, so false alarms on a healthy feeder are not tested, and the switching consequences of a wrong zone (for example re-energizing onto the fault) are not simulated.

**Lesson from the first version:** an early dataset used only three fixed load levels, and the model scored almost perfectly even on magnitude-only features (that run's result files were not kept, so no number is quoted). With so few pre-fault states it could memorize "normal" current. Randomizing the feeder-wide and per-load demand removed the leak and gave the realistic gap shown above.

**Time domain (LTspice)** — the study solves 60 Hz phasors, so [`scripts/spice_run.py`](scripts/spice_run.py) writes three LTspice circuits from the same OpenDSS model at bus 60 and runs them ([`results/spice/summary.json`](results/spice/summary.json), report section 2b):

- **DC offset:** a bolted fault carries 6,119 A RMS once it settles, but if it starts at the worst instant its first peak is 10,067 A instead of 8,753 A. The offset decays with a time constant of 4.9 ms.
- **Arcing high-impedance fault:** tuned to the same RMS current as the fixed 400 Ω fault (6.00 A), a two-diode arc carries 97.8% as much 60 Hz current as the fixed resistance, plus an 18.8% 3rd harmonic that the fixed-resistance fault sweep does not contain. Either way the current is only 1.2% of the 515 A the feeder head carries before the fault and spans 3 counts of the 12-bit ADC, which matches the 400 Ω weak spot above. The arc voltages are illustrative assumptions (see below).

**Cross-feeder transfer, bus-level ranking, and active DER grids** — the flat 120-column classifier above is tied to the 10 named devices of the IEEE 123-bus feeder. Representing each event as a graph of dimensionless quantities (relative current change, per-unit voltages, phasor flow directions, and zone connectivity) lets models trained **only on IEEE 123-bus (4.16 kV, 10 zones)** run unchanged on two unseen test feeders: overhead **IEEE 34-bus (24.9 kV, 7 switches)** and urban underground **IEEE 37-bus (4.8 kV, 3-wire ungrounded delta, 10 switches)**, both zoned by the same pre-registered 5%-load branch rule ([`results/transfer/`](results/transfer/), [`results/active_grid/`](results/active_grid/), report section 2c; full plans in [`research/gnn-transfer/PLAN.md`](research/gnn-transfer/PLAN.md), [`research/active-grid-gnn/PLAN.md`](research/active-grid-gnn/PLAN.md), and [`research/ieee37-underground/PLAN.md`](research/ieee37-underground/PLAN.md); pure OpenDSS simulation):

| Benchmark & model | IEEE 123-bus (5-fold CV) | Unseen IEEE 34-bus (zero-shot) | IEEE 34-bus 20% few-shot / in-domain | 1 sensor offline (123 / 34 zero-shot) |
|---|---|---|---|---|
| Passive radial (0.01–400 Ω) · FPI rule | 55.5% | 55.5% | – | 50.7% / 49.0% |
| Passive radial · Per-node GBDT (node, parent and child features) | **98.3%** | **99.8%** | 96.4% / 99.2% | 89.4% / 88.4% |
| Passive radial · Zone-tree GNN (2L, h=64) | 98.1% | 99.3% | **98.7%** / 98.3% | **90.2%** / 85.8% |
| Active DER + loops + 10 kΩ + NO_FAULT · FPI | 40.7% (FPR 21.2%) | 47.6% (FPR 10.2%) | – | 39.0% / 44.2% |
| Active DER + loops + 10 kΩ + NO_FAULT · Per-node GBDT | 93.9% (FPR 13.9%) | **83.8%** | 83.1% / 91.8% | 86.1% / **72.4%** |
| Active DER + loops + 10 kΩ + NO_FAULT · **ActiveGridGATv2** | **95.8%** (FPR **6.5%**) | 77.6% | **89.1%** / **93.1%** | **89.1%** / 71.5% |

**Third unseen feeder: urban underground IEEE 37-bus (4.8 kV, 3-wire ungrounded delta; 5,184 passive events across 36 buses and 10 zones, [`results/transfer/phase3_ieee37.json`](results/transfer/phase3_ieee37.json)):**

| Benchmark & model (frozen IEEE 123-bus weights) | Overall (zero-shot) | Phase faults (`3PH/LL/LLG`) | `SLG` (`0.01–400 Ω`) | 5% / 20% few-shot | In-domain 5-fold CV (all / `SLG`) | 1 sensor offline (zero-shot) |
|---|---|---|---|---|---|---|
| Passive radial · FPI rule | 43.0% | 98.2% | 0.0% | – | – | 38.7% |
| Passive radial · Per-node GBDT | **56.4%** | **100.0%** | **22.4%** | 45.2% / 55.1% | **91.4%** / **85.0%** | **48.7%** |
| Passive radial · Zone-tree GNN (2L, h=64) | 46.7% | 99.7% | 5.6% | **51.4%** / **66.0%** | 88.0% / 79.6% | 44.2% |
| Active DER + loops + `NO_FAULT` (`--test-feeder ieee37`) | *Not run yet (pending Kaggle GPU run)* | – | – | – | – | – |

- **Why passive 34-bus scores higher at 400 Ω:** the fault current is large next to the load. At nominal load (OpenDSS, [`scripts/signal_to_load.py`](scripts/signal_to_load.py)), a 400 Ω ground fault on the 24.9 kV 34-bus draws a median 31.7 A, 61.1% of the 51.8 A feeder-head current; on the 4.16 kV 123-bus it draws 6.2 A, 1.0% of 631.5 A. On a passive radial tree, per-node GBDT transfers at least as well as the GNN.
- **Why passive zero-shot drops on underground delta IEEE 37-bus (`P1-Fail`, [`research/ieee37-underground/PLAN.md`](research/ieee37-underground/PLAN.md)):** IEEE 37-bus has no grounded substation neutral, so an SLG fault returns only through healthy-phase underground cable charging capacitance. At nominal load (`369.5 A` at head device `D1`), median SLG fault current is just **2.36 A** (**0.64%** of head current) even bolted at `0.01 Ω`, and **2.23 A** (**0.60%**) at `400 Ω`, while unfaulted phase-to-ground voltages shift toward `√3` pu — a physical regime absent from 4-wire grounded IEEE 123-bus training data. Both frozen models therefore fail the pre-committed `P1-Main` criterion (`56.4%` GBDT, `46.7%` GNN vs `43.0%` FPI): SLG accuracy collapses to `22.4%` (GBDT) and `5.6%` (GNN; FPI detects `0.0%`). By contrast, phase faults (`3PH/LL/LLG`, which circulate directly phase-to-phase) generalize almost perfectly (**100.0%** GBDT, **99.7%** GNN vs **98.2%** FPI), and 5-fold in-domain CV on IEEE 37-bus reaches **91.4%** / **88.0%** overall (**85.0%** / **79.6%** on SLG), showing the 21 features carry localizable delta signatures once trained on ungrounded-delta data. With 20% few-shot (7 buses), `ZoneTreeGNN` rises to **66.0%** without forgetting phase faults, while warm-start GBDT regresses to **55.1%** (overfitting the sampled zones).
- **Where graph attention earns its complexity:** adding 0–50% current-limited inverter DERs (`Generator Model=7`), back-fed reconfigurations, closed-loop operation, SLG faults up to 10,000 Ω on 24.9 kV (2.9% of the head current at nominal load; still easier than 400 Ω on 4.16 kV), and ~15% non-fault operational transients (`NO_FAULT`: capacitor switching, PV cloud drops, load steps) drops FPI to 40.7% on 123-bus and 47.6% on 34-bus. Here the bidirectional edge-aware **ActiveGridGATv2** beats per-node GBDT on active 123-bus (**95.8%** vs 93.9%, cutting `NO_FAULT` false trips in half from 13.9% to **6.5%**), at 20% few-shot on 34-bus (**89.1%** vs 83.1%), and in-domain on 34-bus (**93.1%** vs 91.8%), while GBDT is higher in pure zero-shot (**83.8%** vs 77.6%) where sudden +30–80% load steps on 34-bus mimic 2.5–10 kΩ HIFs. The active-grid IEEE 37-bus experiment (`notebooks/kaggle_active_ieee37.ipynb`) has **not been run yet (pending Kaggle GPU run)**.
- **Stage 2 (bus ranking inside the predicted zone):** 3-phase Takagi reactance using OpenDSS 3×3 line impedance matrices (zero training) reaches **46.9% top-1 / 69.0% top-3** on 123-bus and **57.5% top-1 / 87.4% top-3** on 34-bus (vs 8.8% / 26.4% and 19.3% / 50.8% random; 17.8% / 38.5% and 50.8% / 85.8% for a bus-graph GNN). The top confused bus pairs (`61→61s`, `160→160r`, `832→888`) have `ΔX1 = 0.000 Ω`: parallel laterals at the same electrical distance cannot be separated without extra sensors. On underground delta IEEE 37-bus ([`results/transfer/phase2b_bus_ieee37.json`](results/transfer/phase2b_bus_ieee37.json), pre-committed verdict `P2-Partial`), overall accuracy drops to **38.4% top-1 / 53.4% top-3** for Takagi and **37.2% / 53.9%** for zero-shot `BusGraphGNN` (vs **17.0% / 42.1%** random-in-zone) because ungrounded-delta SLG capacitive return breaks the grounded-loop Takagi equation and compact underground cables have tiny adjacent-bus reactances (`701→702`, `ΔX1 = 0.0599 Ω`; `728→729`, `ΔX1 = 0.0077 Ω`); on phase faults (`3PH/LL/LLG`), Takagi still reaches **94.4%** top-3 and zero-shot `BusGraphGNN` **95.2%** (vs **69.4%** random).
- **Split Conformal Prediction (pre-registered, then checked post-hoc):** the pre-registered deterministic APS score saturates. At a 95% target its sets hold 6.37 of 11 labels on average and cover 100.0% of active 123-bus events, so the rule "act only on a one-label set" acts on just 22.6% of events (ActiveGridGATv2). Criterion C3 is met as written, but that coverage is close to trivial. A post-hoc check on the same probabilities and splits with randomized APS (Romano et al. 2020; [`scripts/active_conformal_posthoc.py`](scripts/active_conformal_posthoc.py), Addendum A in [`research/active-grid-gnn/PLAN.md`](research/active-grid-gnn/PLAN.md)) hits the target on the training feeder: 95.0% coverage with 1.09 labels per set; one-label sets cover 89.2% of events, are right 99.1% of the time, and 1.1% of non-fault events would trip. It does **not** carry over to the unseen 34-bus feeder: the 123-bus threshold covers 81.4% (ActiveGridGATv2) and 91.1% (GBDT) against the 95% target, and recalibrating on 2 of its fault buses reaches 92.0% and 94.2% on average (worst of 10 draws 81.5% and 91.3%). The guarantee needs calibration data from the feeder it is used on; here it is a decision-support gate in simulation, not a protection guarantee. Pre-registered randomized APS on active IEEE 37-bus has **not been run yet (pending Kaggle GPU run)**.

**Isolation and restoration** — every one of the 10 zones was faulted in turn ([`results/restoration.csv`](results/restoration.csv), switching orders in [`results/switching_orders.md`](results/switching_orders.md)):

- Every final configuration converged, stayed radial, kept all energized nodes within 0.95–1.05 pu, and had no line above its emergency rating.
- **Constraint checks matter.** The algorithm rejected 22 candidate pickups: 20 on undervoltage, 2 on *overvoltage* (caused by the feeder-head regulator's line-drop compensation) and none on line current (peak-load rows of [`results/hourly/by_level.csv`](results/hourly/by_level.csv)). The voltages of rejected candidates are not saved, so they are not quoted. No candidate failed on ampacity: on this 4.16 kV feeder, voltage is the binding constraint.
- Across the 10 cases, tie switches restored 2,670 kW of the 7,175 kW of healthy load left dark downstream of the fault (37%). The rest could not be carried within voltage limits.
- Interrupted kW-minutes fell by 51% on average, weighting each zone by line length (faults per mile assumed uniform). The range is 9% (fault in the head zone) to 88% (fault in zone L68). This metric depends directly on the assumed times (automated 1 min, manual 90 min, repair 240 min).

| Fault zone | Ties closed | Zones restored through ties | Healthy zones still dark |
|---|---|---|---|
| Sw1 (head) | Sw9, Sw7 | L45, L68, Sw5 | L13, Sw2, Sw3, L61, Sw4, L77 |
| L13 | Sw7 | L45 | Sw3 |
| Sw2 | Sw7 | L68, Sw5 | L61, Sw4, L77 |
| Sw3 | – | – | L45 (pickup would exceed 1.05 pu) |
| Sw4 | Sw7 | L68, Sw5 | L77 |
| L68 | Sw7 | Sw5 | – |
| L45, L61, Sw5, L77 | – | nothing downstream | – |

**Restoration by hour of day** — the table above assumes every fault happens at peak load. [`scripts/hourly_restoration.py`](scripts/hourly_restoration.py) re-runs restoration for every fault zone at every feeder load level, then maps each of the 8,760 hours of 2017 PJM AEP load (shape only, divided by its peak) onto those levels ([`results/hourly/`](results/hourly/), report section 4b):

- Averaged over the year, the ties restore **44.0%** of the healthy load left dark at the fault hour, against 37.2% when every fault is assumed to happen at peak load. If the plan must also hold for the 6 h until the repair ends, the average is **42.1%**; that stricter plan restores less in 30.3% of the hours.
- **Night faults get more back.** On a typical summer day the share is 50.0% for a fault at 03:00 but 36.7% at 17:00; on a typical winter day it is 46.0% at 02:00 and 39.3% at 08:00.
- Every rejected check fails on voltage (too low far along a tie path, or too high near the regulator). No check fails on line current or convergence at any hour.
- **Two caveats.** The tie decisions for L13 and Sw3 sit within about one regulator tap of 1.05 pu, so they switch on and off between neighbouring load levels instead of falling smoothly with load. And 74 of 8,760 hours fall on load levels where a state reaches 1.0508 pu, just above the limit.

## Project structure

```
self-healing-feeder/
├── run.py                 # full study: python run.py
├── shf/                   # source package (feeder model, zones, faults, baseline, ML, restoration, SCADA, report page)
├── scripts/
│   ├── demo_event.py      # replay one fault as SCADA messages
│   ├── error_analysis.py  # per-zone FNR/FPR, confusion pairs, confidence threshold
│   ├── load_shape.py      # hourly load shape from PJM AEP data (hourly study)
│   ├── hourly_restoration.py  # restoration at every load level and hour -> results/hourly/
│   └── export_control_room.py  # 40 replay incidents for the Monitor (docs/monitor/data.json)
├── tests/                 # pytest suite (35 tests)
├── harness/               # check.py + facts.toml: key stated numbers vs. results/
├── config/apis.md         # registry of outside APIs (none used today)
├── inputs/                # new source documents + INDEX.md
├── data/
│   ├── feeder/            # IEEE 123-bus OpenDSS model (input)
│   └── generated/         # simulated fault dataset, created by run.py (not in git)
├── models/                # trained classifier, created by run.py (not in git)
├── results/               # metrics.json, tables, figures/, error_analysis/
├── notebooks/             # Kaggle notebooks: full study, hourly restoration study
├── scada/                 # optional MQTT + TimescaleDB setup
├── workflow.toml          # files made in other apps and their exports (see below)
├── cad/ mech/ spice/ hmi/ # AutoCAD, SolidWorks, LTspice, Factory IO sources
├── board/                # ESP32 control panel: firmware + Wokwi simulation
├── exports/               # what the report reads from those apps (PDF, SVG, GLB, CSV)
└── docs/
    ├── index.html         # run report page (GitHub Pages), built by shf/dashboard.py
    └── vi/                # Vietnamese walkthrough of every module
```

## How it works

| Step | File | What it does |
|---|---|---|
| Feeder model | `shf/feeder.py` | Loads the IEEE 123-bus case (OpenDSS via OpenDSSDirect.py), adds automated switches, a tie to an adjacent feeder and conductor ampacities; reads device currents/voltages |
| Zones | `shf/topology.py` | Builds the bus graph, splits it into 10 zones at the switching devices, builds the zone tree, checks radiality |
| Fault sweep | `shf/faults.py` | SLG/LL/LLG/3-phase faults at every bus, 0.01–400 Ω, random load scenario per fault, 1% / 0.5° measurement noise; regulator taps frozen during the fault |
| Baseline | `shf/baseline.py` | Conventional fault passage indication: phase pickup 2× peak load, ground pickup on residual current; zone = deepest flagged device |
| ML | `shf/model.py` | Gradient-boosted trees, GroupKFold by fault bus (always tested on unseen buses), sensor-dropout training, missing-sensor test |
| Restoration | `shf/restoration.py` | Isolate the zone, re-close upstream, then greedily close the tie that restores the most kW subject to ANSI C84.1 Range A (0.95–1.05 pu), emergency ampacity and radiality |
| Hourly restoration | `shf/hourly.py`, `scripts/load_shape.py`, `scripts/hourly_restoration.py` | Re-runs restoration for every fault zone at every feeder load level, labels why each rejected check failed (undervoltage, overvoltage, overload, no convergence), then maps each hour of one year of PJM AEP load onto those levels; shown in report section 4b |
| Cross-feeder transfer & bus ranking | `shf/transfer.py`, `shf/transfer_models.py`, `shf/bus_locator.py`, `scripts/transfer_train.py`, `scripts/transfer_eval34.py`, `scripts/transfer_eval37.py`, `scripts/transfer_bus_stage.py`, `scripts/signal_to_load.py` | Feeder-agnostic 21-feature zone-node graph representation, per-node GBDT and 2-layer `ZoneTreeGNN` trained on IEEE 123-bus and transferred zero-shot/few-shot to unseen IEEE 34-bus and urban underground delta IEEE 37-bus, plus Stage-2 3-phase Takagi reactance vs `BusGraphGNN` bus ranking inside the predicted zone |
| Active DER grids & Conformal sets | `shf/active_grid.py`, `shf/active_models.py`, `scripts/active_grid_run.py`, `scripts/active_conformal_posthoc.py`, `notebooks/kaggle_active_grid.ipynb`, `notebooks/kaggle_active_ieee37.ipynb` | 0–50% current-limited inverter DER (`Model=7`), reconfigured/closed-loop topologies, SLG faults up to 10,000 Ω on 24.9 kV, non-fault operational transients (`NO_FAULT`), bidirectional edge-aware `ActiveGridGATv2`, and Split Conformal Prediction (90%/95% Adaptive Prediction Sets); IEEE 37-bus active run pending Kaggle GPU |
| SCADA replay | `shf/scada.py`, `scripts/demo_event.py`, `scada/` | Replays one fault as device messages over MQTT into TimescaleDB (or to a JSON-lines file) |
| Control panel | `shf/panel.py`, `scripts/panel_bridge.py`, [`board/`](board/README.md), [live in Wokwi](https://wokwi.com/projects/481240462876979201) | A simulated ESP32 panel in Wokwi: one lamp per switch, a lockout lamp, an LCD, FAULT / CLOSE TIES / RESET buttons, a fault-resistance knob and two failure switches (a sensor that sends nothing, a switch that does not open); the study drives it over MQTT, one fault at a time |

## Run it

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt     # Windows; use .venv/bin/python on Linux/macOS
.venv\Scripts\python run.py                                 # full study, writes data/generated, models, results (~6-8 min)
.venv\Scripts\python scripts/error_analysis.py              # error breakdown, writes results/error_analysis (~1 min)
.venv\Scripts\python -m shf.dashboard                       # rebuild docs/index.html from results/ (~1 s)
.venv\Scripts\python -m shf.report                          # redraw only the feeder map + its 3D geometry (~10 s)
.venv\Scripts\python -m pytest                              # 85 tests
.venv\Scripts\python scripts/export_oneline_dxf.py         # one-line diagram for AutoCAD: cad/feeder_oneline.dxf
.venv\Scripts\python scripts/autocad_export.py --register  # AutoCAD saves the .dwg and plots PDF + PNG (needs AutoCAD)
.venv\Scripts\python scripts/spice_run.py --register      # LTspice: fault DC offset, CT/ADC front end, arcing HIF (needs LTspice)
.venv\Scripts\python scripts/export_drawings.py --register   # dimensioned A3 drawings of the 3D equipment (needs AutoCAD)
.venv\Scripts\python scripts/solidworks_build.py --part all --register  # SolidWorks builds the 3D equipment, exports GLB/STEP/PNG (needs SolidWorks)
.venv\Scripts\python scripts/load_shape.py                 # hourly study: needs data/external/pjm/AEP_hourly.csv
.venv\Scripts\python scripts/hourly_restoration.py         # hourly study: writes results/hourly/
.venv\Scripts\python scripts/transfer_train.py             # Phase 2: 5-fold GroupKFold on IEEE 123-bus -> results/transfer/
.venv\Scripts\python scripts/transfer_eval34.py            # Phase 3: zero-shot / few-shot on IEEE 34-bus -> results/transfer/
.venv\Scripts\python scripts/transfer_eval37.py            # Phase 3: zero-shot / few-shot on underground delta IEEE 37-bus -> results/transfer/
.venv\Scripts\python scripts/transfer_bus_stage.py         # Phase 2b: Stage-2 bus ranking inside zone (add --feeder ieee37 for 37-bus) -> results/transfer/
.venv\Scripts\python scripts/active_grid_run.py            # Active DER + looped grid + Conformal study (add --test-feeder ieee37 for 37-bus)
.venv\Scripts\python scripts/active_conformal_posthoc.py   # post-hoc: deterministic APS vs LAC vs randomized APS (same run)
.venv\Scripts\python scripts/signal_to_load.py             # ~1 s, fault current vs feeder-head current -> results/transfer/
.venv\Scripts\python scripts/demo_event.py --bus 60 --type SLG --r 50
.venv\Scripts\python scripts/panel_bridge.py             # drives the Wokwi ESP32 panel over MQTT (see board/README.md)
```

**Run in the cloud instead (nothing installed locally):** import [`notebooks/kaggle_run.ipynb`](notebooks/kaggle_run.ipynb) into Kaggle. Then set *Internet: On* and *Accelerator: None*, put your repo URL in the second cell, and run *Save & Run All*. Download `results.zip` from the Output tab. Step-by-step guide (Vietnamese): [`docs/vi/github-kaggle-guide.md`](docs/vi/github-kaggle-guide.md). The hourly study has its own notebook, [`notebooks/kaggle_hourly.ipynb`](notebooks/kaggle_hourly.ipynb): add the code bundle and the Kaggle dataset *Hourly Energy Consumption* as inputs, run all, and download `hourly.zip`. The active-grid GNN + Split Conformal study runs on a Kaggle GPU VM via [`notebooks/kaggle_active_grid.ipynb`](notebooks/kaggle_active_grid.ipynb) (IEEE 34-bus) and [`notebooks/kaggle_active_ieee37.ipynb`](notebooks/kaggle_active_ieee37.ipynb) (IEEE 37-bus, pending run).

Optional MQTT + TimescaleDB (requires Docker):

```bash
docker compose -f scada/docker-compose.yml up -d
pip install "psycopg[binary]"
python scada/ingest.py --mqtt localhost --db postgresql://postgres:postgres@localhost:5432/shf
python scripts/demo_event.py --bus 60 --mqtt localhost
```

## Keeping it correct

Numbers in the prose are read from `results/` and listed in `harness/facts.toml`; the only typed numbers are assumptions from `shf/config.py` and IEEE test-case data. Every file in `results/` carries a run record in `results/provenance/` (the command, time, git commit and a SHA-256 of the file; `shf/provenance.py`). The health check fails if a result file no longer matches the run that wrote it.

The key numbers in this README (accuracies, patrol lengths, error counts, restored kW…) are listed in [`harness/facts.toml`](harness/facts.toml) with the result it comes from. [`harness/check.py`](harness/check.py) recomputes them from `results/` and fails if any text, published copy or link is out of date, or if a key is tracked by git:

```bash
.venv\Scripts\python harness/check.py --tests
```

[`AGENTS.md`](AGENTS.md) is the guide for AI coding agents (and people): project map, data flow, content rules and the definition of done. New source documents go in [`inputs/`](inputs/INDEX.md).

Work done in other apps has one folder each: AutoCAD drawings in [`cad/`](cad/README.md), SolidWorks parts in [`mech/`](mech/README.md), LTspice circuits in [`spice/`](spice/README.md), Factory IO scenes in [`hmi/`](hmi/README.md) and the ESP32 panel (Wokwi) in [`board/`](board/README.md), with their exports in [`exports/`](exports/README.md). Each file is listed in [`workflow.toml`](workflow.toml). The one-line diagram starts from `python scripts/export_oneline_dxf.py`, which draws [`cad/feeder_oneline.dxf`](cad/feeder_oneline.dxf) from `results/` (one layer per zone, switches as blocks, an A3 sheet with a title block); `python scripts/autocad_export.py --register` then has AutoCAD's command-line engine save the `.dwg` and plot the PDF and PNG, and the report shows the drawing in section 5. After an export, `python scripts/register_export.py <id>` records it, and the health check fails if the source later changes without a new export. The study calls no outside API; any future one is registered in [`config/apis.md`](config/apis.md), with keys in a git-ignored `.env`.

## Assumptions and limitations

Everything not in the IEEE test case is marked `ASSUMPTION` in `shf/config.py`:

- **Added devices:** five automated switches on lines L13, L45, L61, L68, L77, and tie Sw9 from bus 450 to an adjacent feeder (4.16 kV source at 1.03 pu behind 4,000 ft of 336 ACSR, its own load not modeled). IEEE Sw8 is single-phase and is not used for restoration.
- **Ampacities** (not given in the test case): 336,400 ACSR 530 A, 1/0 ACSR 230 A, 1/0 AA cable 200 A, switches 600 A; emergency rating 125% of normal.
- **Faults are linear resistances** in steady-state phasor power flow. Real high-impedance faults arc and change over time, so accuracy at 200–400 Ω is an upper bound. The source is very stiff (as in the test case), so bolted-fault currents are high.
- **The model is trained and tested on simulation only.** A real deployment would need field event records for validation.
- **Timing for kW-minutes** (automated 1 min, manual 90 min, repair 240 min) is an assumption that drives the size of that metric.
- **Measurement noise:** every device reading gets 1% magnitude and 0.5° angle error (1 sigma), standing in for CT/PT and electronics error. Real instrument error depends on the device and is not modeled further.
- **Conventional FPI baseline:** phase pickup is 2× the device's peak-load current, ground pickup 0.5× that current but at least 1.2× the natural residual current (common rules of thumb, not a utility's settings). It has no directional element; real schemes add directional or timing logic that would reduce some of its false ground flags.
- **SolidWorks equipment** ([`mech/`](mech/README.md)): generic recloser, automated switch, regulator, capacitor bank, pole-top transformer and substation transformer with illustrative sizes (the `*_MM` tables in `config.py`), drawn for the 3D view, each with a dimensioned A3 technical drawing ([`mech/`](mech/README.md#technical-drawings)). None is a manufacturer's design and no calculation uses them.
- **LTspice circuits** ([`spice/`](spice/README.md)): a per-phase Thevenin equivalent at one bus, so mutual coupling and unbalance are left out; an ideal 1000:1 CT (no saturation); a 12-bit, 3.3 V ADC sampling 32 times per cycle; a one-cycle DFT as the phasor estimator. The arcing high-impedance fault uses the two-diode arc model (Emanuel et al., 1990) with arc voltages of 30% (positive half cycle) and 33% (negative half cycle) of the phase peak voltage; those two numbers are illustrative assumptions, not measurements, and the arc resistance is set so the arc has the same RMS current as the fixed 100 Ω or 400 Ω fault it is compared with. They show waveform effects next to the study, not a protection design.
- **Hourly restoration study:** every spot load follows one regional hourly shape (PJM AEP region, which is smoother than a single feeder); the IEEE nominal loads are taken as the annual peak; capacitors stay fixed as in the IEEE case; the adjacent feeder behind Sw9 still has no load of its own. A tie must stay within limits for the whole outage window (manual + repair time), not only at the fault hour.
- **Wokwi control panel** ([`board/`](board/README.md)): the ESP32 is a Wokwi simulation, not a real board. The free simulator reaches only the internet, so the panel and the study meet on a public test broker; the messages are simulated panel states, and the bridge accepts only the commands it knows. When the model picks the wrong zone, the panel says so and stops, because the study does not model what a real scheme would do next. Its stuck-switch test uses a simple back-up rule (the zone behind the stuck switch is isolated too), with no timers.
- **MQTT/TimescaleDB path:** MQTT has run end to end with the Wokwi panel (public broker). The TimescaleDB part has not been run on the development machine (no Docker). The JSON-lines replay is tested.
- **Cross-feeder transfer & bus ranking (`results/transfer/`):** the IEEE 34-bus test feeder has no sectionalizing switches in the IEEE PES distribution, so 7 switches (`Sw1_34` at source plus 6 trunk/lateral switches placed at branches carrying ≥ 5% of feeder kW, marked `ASSUMPTION` in `shf/transfer.py`) are pre-registered in [`research/gnn-transfer/PLAN.md`](research/gnn-transfer/PLAN.md). Stage-2 bus ranking uses OpenDSS 3×3 line impedance matrices and assumes only the zone-head device records the event.
- **Urban underground 3-wire delta IEEE 37-bus (`results/transfer/*ieee37*`, [`research/ieee37-underground/PLAN.md`](research/ieee37-underground/PLAN.md)):** unmodified 4.8 kV 3-wire ungrounded delta underground cable feeder (`data/feeder/ieee37/`, IEEE underground line codes `721`–`724`, delta-delta substation transformer, open-delta head regulator, unbalanced delta spot loads, no shunt capacitor banks). **ASSUMPTION:** no artificial earthing/zig-zag transformer is added, so SLG faults return purely through healthy-phase cable charging capacitance (`2.36 A` / `0.64%` at `0.01 Ω` and `2.23 A` / `0.60%` at `400 Ω` vs `369.5 A` head current) and shift unfaulted phase-to-ground voltages toward `√3` pu. Applying the frozen 5%-load `PLACEMENT_RULE` yields 10 switching zones (`D1`–`D10`) across 36 3-phase buses (`2,457 kW` nominal load). For the active-grid IEEE 37-bus stage (locked in `shf/active_grid.py`, **pending Kaggle GPU run**), 3 delta-connected `Generator Model=7` DERs are placed at `738`, `708`, and `720` (0–50% penetration), an adjacent 230/4.8 kV delta-delta tie `Tie37` connects to bus `741` (`D9`) for `reconfig_tie` (`D6` open) and `looped_tie`, SLG resistances span `0.01–400 Ω`, and `NO_FAULT` events split 50/50 between `pv_cloud` and `load_step` (`cap_switch = 0` because the feeder has no capacitor banks). Pure steady-state OpenDSS phasor simulation; no EMT cable transients, no CT saturation, and no field data.
- **Active DER grids & Split Conformal Prediction (`results/active_grid/`):** inverter-interfaced DERs are modeled in OpenDSS as `Generator Model=7` (current-limited to ~1.1–1.2 pu at unity power factor) across 0%, 25%, and 50% penetration at pre-registered candidate buses (`ACTIVE_DER_BUSES_123` and `ACTIVE_DER_BUSES_34`, marked `ASSUMPTION` in `shf/active_grid.py`). Topologies include radial normal, tie-reconfigured back-feed, and weakly meshed closed-loop states (`Sw7` closed on 123-bus; an assumed 10 kft tie `828–832` on 34-bus). The 24.9 kV 34-bus active sweep extends SLG fault resistance up to 10,000 Ω to move toward the 4.16 kV signal-to-load ratio, but does not reach it: at nominal load a 10,000 Ω fault on 34-bus draws a median 2.9% of the feeder-head current, against 1.0% for 400 Ω on 123-bus (`results/transfer/signal_to_load.json`). Non-fault operational transients (`NO_FAULT`) are steady-state phasor snapshots of capacitor bank switching, 70–90% PV cloud drops, and +30–80% load steps, not EMT sub-cycle waveforms.

## References

- IEEE PES Distribution Test Feeders — https://cmte.ieee.org/pes-testfeeders/resources/
- OpenDSS (EPRI) and IEEE 123-bus, 34-bus, and 37-bus model files — https://sourceforge.net/projects/electricdss/ (mirrored at https://github.com/dss-extensions/electricdss-tst; IEEE 37-bus: https://github.com/dss-extensions/electricdss-tst/tree/master/Version8/Distrib/IEEETestCases/37Bus)
- W. H. Kersting, "Radial distribution test feeders," *IEEE Trans. Power Systems*, vol. 6, no. 3, pp. 975–985, 1991 — https://doi.org/10.1109/59.119237
- J. Glass, A. Melin, M. Starke, B. Ollis, *Chattanooga Electric Power Board Case Study: Distribution Automation*, ORNL/LTR-2015/444, 2016 — https://www.osti.gov/biblio/1329733
- K. Chen et al., "Fault Location in Power Distribution Systems via Deep Graph Convolutional Networks," IEEE JSAC, 2019 — https://arxiv.org/abs/1812.09464
- T. Takagi, Y. Yamakoshi, M. Yamaura, R. Kondow, T. Matsushima, "Development of a New Type Fault Locator Using the One-Terminal Voltage and Current Data," *IEEE Trans. Power Apparatus and Systems*, vol. PAS-101, no. 8, pp. 2892–2898, 1982 — https://doi.org/10.1109/TPAS.1982.317615
- Y. Romano, M. Sesia, E. Candès, "Classification with Valid and Adaptive Coverage," *Advances in Neural Information Processing Systems (NeurIPS)*, 2020 — https://arxiv.org/abs/2006.02544
- R. Mulla, *Hourly Energy Consumption* (PJM hourly load in MW, file `AEP_hourly.csv`), Kaggle, CC0 — https://www.kaggle.com/datasets/robikscube/hourly-energy-consumption
- ANSI C84.1, *Electric Power Systems and Equipment — Voltage Ratings (60 Hz)*, Range A service voltage 114–126 V.
- A. E. Emanuel, D. Cyganski, J. A. Orr, S. Shiller, E. M. Gulachenski, "High impedance fault arcing on sandy soil in 15 kV distribution feeders: contributions to the evaluation of the low frequency spectrum," *IEEE Trans. Power Delivery*, vol. 5, no. 2, pp. 676–686, 1990 (two-diode arc model) — https://doi.org/10.1109/61.53070

## License

Code: MIT (see [`LICENSE`](LICENSE)). The IEEE 123-bus model files in `data/feeder/` come from the EPRI OpenDSS distribution and keep their original license.

---

Built with AI-assisted development (Claude Code). Vietnamese walkthrough of every module: [`docs/vi/module-guide.md`](docs/vi/module-guide.md).
