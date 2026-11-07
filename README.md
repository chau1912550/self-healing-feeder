# Self-Healing Feeder: ML Fault Location and Automated Restoration

A student-scale version of the **FLISR** (Fault Location, Isolation and Service Restoration) systems that utilities such as EPB Chattanooga and Duke Energy run on their distribution grids, built on the **IEEE 123-bus test feeder** in **OpenDSS**.

When the feeder-head recloser locks out, a crew without fault location has to patrol the whole feeder. This project asks two questions:

1. Using only measurements that reclosers and automated switches already record, can a model tell **which switching zone** the fault is in, including high-impedance faults that conventional fault indicators miss?
2. Once the zone is known, can we **isolate it and restore every other zone** automatically, closing a tie switch only when a power flow shows voltages and currents stay within limits?

## 🌐 [chau1912550.github.io/self-healing-feeder](https://chau1912550.github.io/self-healing-feeder/)

**👉 Open it: [English](https://chau1912550.github.io/self-healing-feeder/?lang=en) · [Tiếng Việt](https://chau1912550.github.io/self-healing-feeder/?lang=vi)** — one page with every result of the latest run: a clickable 3D model of the feeder, 15 questions & answers, a glossary, and the full dataset with its formulas and reasoning. Nothing to install; it works on a phone.

**🕹️ [Monitor demo](https://chau1912550.github.io/self-healing-feeder/monitor/)**: work a simulated fault as the dispatcher, field crew, engineer or manager, each with its own view and steps ([how it works](docs/monitor/README.md)).

[![Run report: headline numbers and run checks](docs/images/report-overview.png)](https://chau1912550.github.io/self-healing-feeder/)

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
| **Explain guide** | On by default: click any card, chart or table (or its **?**) and a small guide flies there, circles it and says what it is, how to read it and why it matters. **← / →** walk through every part, **Esc** closes, the button at the bottom left turns it off, and `?explain=heat` in a link opens the guide on one part. |
| **3D feeder model** | The whole feeder in 3D, built from the study's data: wooden poles with crossarms and insulators, one wire per phase, pole-top transformers, load columns sized by kW, recloser, switches (added ones carry a radio antenna), open ties with raised red blades, regulators, capacitor banks and the substation yard. Drag to rotate; click a zone or part and it lifts out while the guide explains it; **Tour the zones** walks through all 10; label layers (zones, equipment, bus numbers) and a **2D map** view. three.js loads only when the section comes on screen. |
| **Model errors** layer | Shows *where* the model goes wrong: a red column on every bus where faults get misplaced (taller = more, redder = higher rate), a green dot where none are, and arrows from each true zone to the zone it is mistaken for (Sw2 → Sw1: 41 faults…). Click a column or arrow for the numbers, including how conventional fault indicators do on the same bus. |
| **Fault replay** layer | Click anywhere on the feeder (or pick "a missed fault") and the model replays it in 6 steps: the fault flashes, Sw1 locks out and the feeder goes dark, the model names a zone (an orange arrow if it is wrong, with why), switches open to isolate, Sw1 re-closes, and ties close to restore what the power flow allows. Every switch has a lamp: green closed, red open. |
| **Data & method** | Download the full simulated dataset (11,448 faults × 158 columns, plus a 300-row sample) and every result file from [`docs/data/`](docs/data/), with a column dictionary, the formulas behind each number, and the nine-step reasoning from the question to the result. |
| **EN / VI** button | Switches every text, chart label and tooltip between English and Vietnamese. Add `?lang=vi` or `?lang=en` to a link to share it in one language. |
| **Run checks** | Pass / Watch / Fail summary of the run, so you know whether to trust the numbers before reading on. |
| **In short** boxes | One plain-language sentence at the top of each section. |
| Dotted-underlined words | Hover or tap for a one-line definition (FLISR, FNR, pu, radial…); all of them are also listed in the **Glossary**. |
| Hover / tap on charts | Exact numbers for every point, bar and matrix cell; “Show as table” gives the same data as a table. |
| **Questions & answers** | 15 questions a reviewer or interviewer is likely to ask, answered with this run's numbers. Search (Vietnamese with or without accents), filter by topic, open all, or copy a link to one question. |
| Top bar | Jumps to any section and highlights where you are; ◐ switches auto / light / dark theme (`?theme=light` works in links too). |
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
- **Where the model fails:** errors cluster in the zones near the substation (Sw1, Sw2, Sw4, L13). Device load currents there are 240–630 A, so 1% measurement noise (2–6 A) is comparable to a 400 Ω fault current (~6 A). See [`results/figures/confusion_ml.png`](results/figures/confusion_ml.png) and the [error analysis](#error-analysis) below.
- **Why the conventional method misses bolted ground faults (30% correct):** a solid phase-to-ground fault collapses that phase's voltage, and single-phase loads beyond the fault drop out. Devices downstream then see a large residual current and raise false ground flags, so the "deepest flagged device" rule points past the real fault. Real schemes add directional elements for this.
- **Patrol length:** after a feeder lockout, a crew without fault location patrols the whole feeder (39.0 kft of line). With the ML zone, the average patrol drops to 5.1 kft (−87%). If the zone is wrong, the model is charged a full patrol.

### Error analysis

Accuracy alone hides which faults are missed and where the wrong answers point, so [`scripts/error_analysis.py`](scripts/error_analysis.py) replays the same grouped cross-validation and breaks down all 259 errors (2.3% of 11,448 faults). Output: [`results/error_analysis/`](results/error_analysis/).

Because the model always names one of 10 zones, false negatives and false positives are counted **per zone, one-vs-rest**: FNR = faults in zone X placed elsewhere, FPR = faults elsewhere placed in X.

| Zone | Faults | FNR | FPR | Precision |
|---|---|---|---|---|
| Sw1 (feeder head) | 1,125 | **5.4%** | **0.9%** | 92.0% |
| Sw2 | 1,494 | 4.5% | 0.6% | 96.2% |
| L13 | 1,557 | 2.8% | 0.5% | 97.0% |
| Sw4 | 1,971 | 2.6% | 0.5% | 97.8% |
| Sw3 | 981 | 1.7% | 0.1% | 98.8% |
| L45, L61, L68, Sw5, L77 (laterals) | 4,320 | ≤ 0.8% | ≤ 0.05% | ≥ 99.4% |

- **What is missed:** 253 of 259 errors are line-to-ground faults, and **237 (92%) are at 200 Ω or more**. The SLG error rate is 0% up to 5 Ω, 0.1% at 10–50 Ω, 1.6% at 100 Ω, 6.3% at 200 Ω and 23.5% at 400 Ω. No three-phase fault was misplaced.
- **Why:** a 400 Ω fault on a 2.4 kV phase draws about 6 A, while trunk devices carry hundreds of amps of load, so the fault is about 1% of the signal. Loading confirms it: the error rate is 0.9% in the lightest third of load scenarios and 4.1% in the heaviest third.
- **Where the wrong answers point:** 64% of errors are off by exactly one zone and 86% stay on the same path from the substation. The largest pairs are Sw2→Sw1 (41), Sw1→Sw2 (24) and L13→Sw1 (23). The model leans **upstream** (51% of errors): when a fault is too small for downstream devices to see, only the feeder-head device still shows a change.
- **Checked and rejected:** faults close to a zone boundary are *not* clearly harder (error rate 1.8–2.7% at every distance from the nearest switch).
- **Deferring low-confidence answers:** wrong answers have a median class probability of 0.90 vs 1.00 for correct ones. Sending predictions below 0.95 to a manual patrol defers 2.8% of faults, raises accuracy on the rest to 99.1% and cuts errors from 259 to 97 (−63%).
- **For comparison, conventional FPI** raises no flag at all on 25.8% of faults (true missed detections) and over-flags Sw5 (FPR 12.6%, precision 38.8%).
- **Not measured:** the dataset holds only faulted cases, so false alarms on a healthy feeder are not tested, and the switching consequences of a wrong zone (for example re-energizing onto the fault) are not simulated.

**Lesson from the first version:** an early dataset used only three fixed load levels, and the model scored 99.9% even on magnitude-only features. With so few pre-fault states it could memorize "normal" current. Randomizing the feeder-wide and per-load demand removed the leak and gave the realistic gap shown above.

**Isolation and restoration** — every one of the 10 zones was faulted in turn ([`results/restoration.csv`](results/restoration.csv), switching orders in [`results/switching_orders.md`](results/switching_orders.md)):

- Every final configuration converged, stayed radial, kept all energized nodes within 0.95–1.05 pu, and had no line above its emergency rating.
- **Constraint checks matter.** The algorithm rejected 22 candidate pickups. Most failed on undervoltage (down to 0.85 pu); two failed on *overvoltage* (1.053 and 1.056 pu), caused by the feeder-head regulator's line-drop compensation. No candidate failed on ampacity: on this 4.16 kV feeder, voltage is the binding constraint.
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

## Project structure

```
self-healing-feeder/
├── run.py                 # full study: python run.py
├── shf/                   # source package (feeder model, zones, faults, baseline, ML, restoration, SCADA, report page)
├── scripts/
│   ├── demo_event.py      # replay one fault as SCADA messages
│   └── error_analysis.py  # per-zone FNR/FPR, confusion pairs, confidence threshold
├── tests/                 # pytest suite (15 tests)
├── data/
│   ├── feeder/            # IEEE 123-bus OpenDSS model (input)
│   └── generated/         # simulated fault dataset, created by run.py (not in git)
├── models/                # trained classifier, created by run.py (not in git)
├── results/               # metrics.json, tables, figures/, error_analysis/
├── notebooks/             # Kaggle notebook to run everything in the cloud
├── scada/                 # optional MQTT + TimescaleDB setup
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
| SCADA replay | `shf/scada.py`, `scripts/demo_event.py`, `scada/` | Replays one fault as device messages over MQTT into TimescaleDB (or to a JSON-lines file) |

## Run it

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt     # Windows; use .venv/bin/python on Linux/macOS
.venv\Scripts\python run.py                                 # full study, writes data/generated, models, results (~6-8 min)
.venv\Scripts\python scripts/error_analysis.py              # error breakdown, writes results/error_analysis (~1 min)
.venv\Scripts\python -m shf.dashboard                       # rebuild docs/index.html from results/ (~1 s)
.venv\Scripts\python -m shf.report                          # redraw only the feeder map + its 3D geometry (~10 s)
.venv\Scripts\python -m pytest                              # 15 tests
.venv\Scripts\python scripts/demo_event.py --bus 60 --type SLG --r 50
```

**Run in the cloud instead (nothing installed locally):** import [`notebooks/kaggle_run.ipynb`](notebooks/kaggle_run.ipynb) into Kaggle. Then set *Internet: On* and *Accelerator: None*, put your repo URL in the second cell, and run *Save & Run All*. Download `results.zip` from the Output tab. Step-by-step guide (Vietnamese): [`docs/vi/github-kaggle-guide.md`](docs/vi/github-kaggle-guide.md).

Optional MQTT + TimescaleDB (requires Docker):

```bash
docker compose -f scada/docker-compose.yml up -d
pip install "psycopg[binary]"
python scada/ingest.py --mqtt localhost --db postgresql://postgres:postgres@localhost:5432/shf
python scripts/demo_event.py --bus 60 --mqtt localhost
```

## Assumptions and limitations

Everything not in the IEEE test case is marked `ASSUMPTION` in `shf/config.py`:

- **Added devices:** five automated switches on lines L13, L45, L61, L68, L77, and tie Sw9 from bus 450 to an adjacent feeder (4.16 kV source at 1.03 pu behind 4,000 ft of 336 ACSR, its own load not modeled). IEEE Sw8 is single-phase and is not used for restoration.
- **Ampacities** (not given in the test case): 336,400 ACSR 530 A, 1/0 ACSR 230 A, 1/0 AA cable 200 A, switches 600 A; emergency rating 125% of normal.
- **Faults are linear resistances** in steady-state phasor power flow. Real high-impedance faults arc and change over time, so accuracy at 200–400 Ω is an upper bound. The source is very stiff (as in the test case), so bolted-fault currents are high.
- **The model is trained and tested on simulation only.** A real deployment would need field event records for validation.
- **Timing for kW-minutes** (automated 1 min, manual 90 min, repair 240 min) is an assumption that drives the size of that metric.
- **Conventional FPI baseline** has no directional element; real schemes add directional or timing logic that would reduce some of its false ground flags.
- **MQTT/TimescaleDB path** has not been run end-to-end on the development machine (no Docker). The JSON-lines replay is tested.

## References

- IEEE PES Distribution Test Feeders — https://cmte.ieee.org/pes-testfeeders/resources/
- OpenDSS (EPRI) and IEEE 123-bus model files — https://sourceforge.net/projects/electricdss/ (mirrored at https://github.com/dss-extensions/electricdss-tst)
- J. Glass, A. Melin, M. Starke, B. Ollis, *Chattanooga Electric Power Board Case Study: Distribution Automation*, ORNL/LTR-2015/444, 2016 — https://www.osti.gov/biblio/1329733
- K. Chen et al., "Fault Location in Power Distribution Systems via Deep Graph Convolutional Networks," IEEE JSAC, 2019 — https://arxiv.org/abs/1812.09464
- ANSI C84.1, *Electric Power Systems and Equipment — Voltage Ratings (60 Hz)*, Range A service voltage 114–126 V.

## License

Code: MIT (see [`LICENSE`](LICENSE)). The IEEE 123-bus model files in `data/feeder/` come from the EPRI OpenDSS distribution and keep their original license.

---

Built with AI-assisted development (Claude Code). Vietnamese walkthrough of every module: [`docs/vi/module-guide.md`](docs/vi/module-guide.md).
