# Self-Healing Feeder + Edge HIF Sensor (2-Tier FLISR)

> **End-to-end 2-tier distribution protection & restoration** — coupling a **504-byte int8 ESP32-S3 high-impedance fault (HIF) sensor** (`hif_sensor/`) with **graph-based FLISR & power-flow restoration** (`shf/`) across **15 official IEEE/EPRI feeders**, **real 22 kV vegetation-fault recordings (VeHIF)**, and **8,760 real utility load hours (PJM AEP)**.

| 🌐 Tier 2 · Feeder FLISR Report | 🔌 Tier 1 · Edge HIF Sensor (ESP32) | 🕹️ Interactive Demos & Paper |
|---|---|---|
| **[Open Report (EN)](https://chau1912550.github.io/self-healing-feeder/?lang=en)** · **[Tiếng Việt](https://chau1912550.github.io/self-healing-feeder/?lang=vi)** | **[Open Sensor Report (EN / VI)](https://chau1912550.github.io/self-healing-feeder/hif-sensor/)** | **[Monitor Demo](https://chau1912550.github.io/self-healing-feeder/monitor/)** · **[Technical Paper](https://chau1912550.github.io/self-healing-feeder/study/)** ([VI](https://chau1912550.github.io/self-healing-feeder/study/?lang=vi)) |
| 3D feeder, quick-scan cards, 17 Q&A, SHA-256 ledger | LTspice CT/LPF, 50/60 Hz, VeHIF 22 kV, C firmware | 40 replay faults · Wokwi ESP32 panel · Study guide |

---

## Evaluated on Real-World Public Datasets & Industry Feeders

> **Transparent boundary (Real Data vs. Simulation):** Every real-world dataset below is cited verbatim with its exact boundary. OpenDSS fault sweeps, power-flow restoration, LTspice circuits, and the analog sensor stage are **simulation only** (no live utility SCADA connection, no utility deployment, and no energized field hardware test yet).

| Real Dataset / Industry Benchmark | Scope & Source | What Is Real vs. Simulated | Verified Headline Result |
|---|---|---|---|
| **Real 22 kV, 50 Hz Vegetation Faults ([VeHIF](https://www.kaggle.com/datasets/dougpsg/highimpedance-vegetation-fault-data-set))** | **983** staged real-feeder tests (**900** valid) + **53** real background recordings (Gomes & Ozansoy, *IEEE TPWRD* 2022, CC0) | **REAL:** 22 kV fault current & background waveforms.<br>**SIM:** LTspice-verified CT/LPF/ADC sensor & feeder load. | Phase 1 zero-shot: **56.0%** on 250 real faults (**0.0%** FA on 53 real background recordings; 51N **0.0%**). Phase 1.5 20% few-shot `joint_mlp_int8`: **53.30% → 60.22%** overall (**42.52% → 49.93%** / **+7.41 pp** at 0–2 A; bg FA **1.82%**, ctrl FA **0.67%**, sim **93.84%**; `P1.5-A: false` vs ≥ +15 pp, `P1.5-B/C/D: true`) in [`hif_sensor/`](hif_sensor/). |
| **Real Utility Hourly Load ([PJM AEP 2017](https://www.kaggle.com/datasets/robikscube/hourly-energy-consumption))** | **8,760 real hourly MW measurements** across a full calendar year (CC0) | **REAL:** 8,760-hour regional load profile.<br>**SIM:** IEEE 123-bus OpenDSS tie-switch power flow. | Year-average healthy load restored rises from **37.2%** (peak-only assumption) to **44.0%** (**42.1%** held 6 h; summer 03:00 **50.0%** vs 17:00 **36.7%**). |
| **15 Official IEEE & EPRI Utility Circuits** | IEEE 13, 34, 37, 123, 8500-Node, **50 Hz European LV**, EPRI Ckt5/7/24/J1/K1/M1 (up to **6,058 buses / 34.5 kV**) | **STANDARD MODELS:** Official IEEE/EPRI feeder specs.<br>**SIM:** OpenDSS fault sweeps & DER/loop scenarios. | Frozen IEEE 123-bus models pass **10 of 11** unseen feeders zero-shot (IEEE 8500 **99.8%**, EU-LV 50 Hz **93.3%**, EPRI Ckt24 **99.7%**); ungrounded delta IEEE 37-bus SLG fails cleanly (`P1-Fail`). |

---

## System Architecture & Headline Numbers

```mermaid
flowchart LR
  subgraph T1["Tier 1 · Edge HIF Sensor (hif_sensor/ · ESP32-S3)"]
    A["Clamp CT SCT-013 (2000:1)<br/>33 Ω burden · 16.5 mV/A"] --> B["4th-Order Butterworth LPF<br/>fc = 2,045 Hz (LTspice)<br/>15.36 kHz (60 Hz) / 12.8 kHz (50 Hz)"]
    B --> C["16 FFT / Arc Features<br/>504 B int8 Tiny MLP (417 params)<br/>3-window relay persistence"]
  end
  subgraph T2["Tier 2 · Feeder-Level Graph FLISR (shf/ · OpenDSS)"]
    D["10 Reclosers & Auto Switches<br/>Pre/Post Phasors + Edge p_hif"] --> E["Per-Node GBDT / ZoneTreeGNN /<br/>ActiveGridGATv2 + Split Conformal"]
    E --> F["Isolate Zone → Power-Flow Check<br/>(0.95–1.05 pu · ≤125% · Radial)<br/>Close Ties → Restore Healthy Load"]
  end
  C -->|"p_hif, hif_alarm"| D
```

| Layer & Question | Headline Verified Result (`results/`) | Primary Evidence |
|---|---|---|
| **Tier 1 · Edge HIF Sensor (Sim + LTspice + C)** | **94.7%** simulated HIF detected (FA **1.5%**) vs 51N **0.5%**; LTspice −3 dB **2,045.1 Hz**, −46.4 dB @ Nyquist; 50 Hz VN retuned `R×1.2`: **1,688.73 Hz**, **−46.70 dB** @ 6.4 kHz, sim **94.33%**; **504 B** int8 (`417` params); GCC C parity **≤ 1.04e-6** (**0.54–0.61 µs/inf**, 100% agreement) | [`hif_sensor/results/metrics.json`](hif_sensor/results/metrics.json), [`c_firmware_verify.json`](hif_sensor/results/c_firmware_verify.json) |
| **Tier 1 · Real 22 kV VeHIF Recordings** | Phase 1: **56.0%** zero-shot on 250 real vegetation faults (**0.0%** on 53 bg; 51N **0.0%**). Phase 1.5: **53.30% → 60.22%** (0–2 A **42.52% → 49.93%** / **+7.41 pp**, bg FA **1.82%**, ctrl FA **0.67%**; `P1.5-A: false`, `P1.5-B/C/D: true`); temporal-only ablation **55.6%** | [`hif_sensor/results/real_vehif.json`](hif_sensor/results/real_vehif.json), [`phase15_vehif.json`](hif_sensor/results/phase15_vehif.json) |
| **Tier 2 · Main IEEE 123-Bus FLISR** | **97.7%** zone accuracy vs **56.1%** FPI (11,448 faults, unseen buses); patrol **39.0 → 5.1 kft** (−87%); ties restore **2,670 / 7,175 kW**; kW-min **−51%** | [`results/metrics.json`](results/metrics.json) |
| **Tier 1 + Tier 2 · HIF-Fusion (4/4 H1–H4 PASS)** | Passive 123-bus `400 Ω` SLG **78.1% → 97.7%** (GBDT); Active 123-bus `400 Ω` GATv2 **73.5% → 87.5%** while cutting `NO_FAULT` FPR **6.5% → 1.2%** | [`results/hif_fusion/dataset_summary.json`](results/hif_fusion/dataset_summary.json) |
| **Active DER (0–50%) + Loops + Conformal** | Active 123-bus GATv2 **95.8%** (FPR **6.5%**); 95% `aps_rand` singleton share **89.2% → 93.0%** (+Edge); honest fail on 0-shot cross-feeder conformal | [`results/active_grid/phase_active_ieee34.json`](results/active_grid/phase_active_ieee34.json) |
| **Cryptographic Audit & Tests** | **23** SHA-256 manifests (**51** files, **0** tampered) + Tier-1 [`hif_sensor/`](hif_sensor/results/provenance/manifest.json) manifest (**23** files, **0** tampered) + **154 unit tests** (**144** Tier-2 + **10** Tier-1 `pytest`, plus **235** `harness/check.py` checks) | [`results/provenance/`](results/provenance/) |

[![Unified Report Page: Tier-2 FLISR, Tier-1 Edge HIF Sensor, and Monitor](docs/images/report-overview.png)](https://chau1912550.github.io/self-healing-feeder/)

---

## Independent Verification in 2 Commands (For Lecturers & Reviewers)

Every number in this repository is computed programmatically from [`results/`](results/) and checked by [`harness/facts.toml`](harness/facts.toml). Verify every SHA-256 hash, prose number, link, secret guard, and unit test locally:

```bash
python -m shf.provenance          # verifies all 23 SHA-256 manifests / 51 result files (0 changed, 0 missing, 0 unrecorded)
python harness/check.py --tests   # recomputes every prose number from results/, checks links, secrets, provenance & pytest
```

*(On Windows with the local venv, replace `python` with `.venv\Scripts\python`; on Linux/macOS use `.venv/bin/python`. To verify the bundled Tier-1 sensor manifest and tests directly: `pushd hif_sensor && ..\.venv\Scripts\python -m hif.provenance --verify && ..\.venv\Scripts\python -m pytest -v tests/test_hif.py && popd` — **23** files verified, **10 passed**.)*

---

## Detailed Technical Sections (Click to Expand)

<details>
<summary><b>1. Verification Ledger, 5 Pre-Registered Plans, Honest Pass/Fail Summary &amp; Security Policy</b></summary>

<br>

### Cryptographic Provenance Ledger & 5 Pre-Registered Plans

- **SHA-256 Provenance (`results/provenance/` + `hif_sensor/results/provenance/`):** Tier 2 maintains **23** run manifests covering **51** recorded result files (**0 changed / 0 missing / 0 unrecorded** via [`shf/provenance.py`](shf/provenance.py)); Tier 1 maintains [`hif_sensor/results/provenance/manifest.json`](hif_sensor/results/provenance/manifest.json) covering **23** files (**0 changed / 0 missing** via [`hif_sensor/hif/provenance.py`](hif_sensor/hif/provenance.py)). Each manifest logs the exact producer command, UTC timestamp, git commit (when run locally), and 64-character SHA-256 digest of every generated file.
- **Tier-1 Edge HIF-Sensor artifacts:** Frozen Phase-0 `model_int8.npz` (`417` parameters, `504` bytes, threshold `0.982635`, Kaggle kernel `christoopherchau/ch-y-n`), SHA-256 `3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1` (logged in [`results/hif_fusion/dataset_summary.json`](results/hif_fusion/dataset_summary.json)), plus Phase 1.5 few-shot adapted [`hif_sensor/results/model_phase15_int8.npz`](hif_sensor/results/model_phase15_int8.npz) / [`hif_sensor/firmware/hif_model_phase15.h`](hif_sensor/firmware/hif_model_phase15.h) (`417` parameters, `504` bytes, seed-0 20% `joint_mlp_int8` export threshold `0.924894`).
- **All 5 pre-registered research plans (hypotheses, assumptions, and pass/fail criteria locked before running):**
  1. [`research/gnn-transfer/PLAN.md`](research/gnn-transfer/PLAN.md) — Passive cross-feeder zero-shot transfer (IEEE 123-bus → 34-bus) & Stage-2 bus ranking.
  2. [`research/active-grid-gnn/PLAN.md`](research/active-grid-gnn/PLAN.md) — Active DER (0–50%), reconfigured/closed-loop topologies, 10 kΩ HIF, `NO_FAULT` transients & Split Conformal Prediction (incl. Addendum A/B1 post-hoc audits).
  3. [`research/ieee37-underground/PLAN.md`](research/ieee37-underground/PLAN.md) — Third unseen feeder: urban underground 4.8 kV 3-wire ungrounded delta IEEE 37-bus (passive & active).
  4. [`research/multi-feeder-benchmark/PLAN.md`](research/multi-feeder-benchmark/PLAN.md) — 15-feeder cross-feeder zero-shot benchmark across official IEEE/EPRI OpenDSS circuits (3 parallel Kaggle VMs).
  5. [`research/hif-fusion/PLAN.md`](research/hif-fusion/PLAN.md) — Two-tier Edge HIF-Sensor (`504 B` int8) → Graph FLISR paired ablation across 5 Emanuel arc surfaces and 7 background disturbances.

### Honest summary: Passing Evidence vs. Failures & Physical Limits (Simulation Only)

| Experiment / Study | Run Env | Key Verified Results (`results/`) | Pre-Registered Verdict | Primary Result File |
|---|---|---|---|---|
| **Main FLISR (IEEE 123-bus, 4.16 kV)** | Local CPU | `11,448` faults: ML **97.7%** vs FPI **56.1%** (`100 Ω`: **98.4%** vs 8.4%; `400 Ω`: **76.5%** vs 1.0%); `259` errors (`237` at ≥ 200 Ω); patrol **39.0 → 5.1 kft** (−87%); ties restore **2,670 / 7,175 kW**; kW-min **−51%** | **PASS** (sim; linear R, stiff source) | [`results/metrics.json`](results/metrics.json) |
| **Hourly Restoration (PJM AEP 2017)** | Kaggle / Local | `8,760` hours: **44.0%** year mean (**42.1%** 6 h-held) vs **37.2%** peak; summer 03:00 **50.0%** vs 17:00 **36.7%**; caveat: `74 of 8,760 hours` reach `1.0508 pu` | **PASS** (sim; regional load shape) | [`results/hourly/hourly.json`](results/hourly/hourly.json) |
| **LTspice Transient & Arcing HIF** | Local LTspice | Bus 60 bolted fault `6,119 A RMS`, peak `10,067 A` (`4.9 ms` τ); `400 Ω` Emanuel arc `6.00 A` (`97.8%` 60 Hz, `18.8%` 3rd harmonic, `3 counts` of 12-bit ADC) | **PASS** (sim; single-phase Thevenin) | [`results/spice/summary.json`](results/spice/summary.json) |
| **Passive Transfer (123 → 34-bus) + Stage-2** | Local CPU | Stage 1 zero-shot (`4,104` faults): GBDT **99.8%**, GNN **99.3%** vs FPI **55.5%**. Stage 2 (`top-1 / top-3`): zero-training Takagi **46.9% / 69.0%** (123) & **57.5% / 87.4%** (34) beats `BusGraphGNN` (**17.8% / 38.5%** CV on 123; **50.8% / 85.8%** 0-shot on 34) | **PASS** (Stage 1) · **FAIL** (`BusGraphGNN` loses to Takagi physics) | [`results/transfer/phase3_ieee34.json`](results/transfer/phase3_ieee34.json) |
| **15-Feeder Zero-Shot Benchmark** | Kaggle 3-VM | **10 of 11** unseen evaluated feeders pass (9/9 new IEEE/EPRI incl. 50 Hz EU-LV **93.3%**, IEEE 8500 **99.8%**, 34.5 kV EPRI Ckt24 **99.7%**; on 18-zone Ckt7 1-sensor-offline, GNN **94.3%** > GBDT **90.5%**). **3 honest out-of-scope:** IEEE 342-Node (71 cycles), IEEE 9500-Node (non-converged base flow), CIGRE MV (absent in repo) | **PASS** (10/11 unseen) · **3 out-of-scope disclosed** | [`results/transfer/multi_feeder_benchmark.json`](results/transfer/multi_feeder_benchmark.json) |
| **Underground Delta IEEE 37-bus (4.8 kV)** | Local CPU + Kaggle GPU | Passive (`5,184` faults): zero-shot GBDT **56.4%**, GNN **46.7%** vs FPI **43.0%** — SLG collapses (**22.4% / 5.6%**, FPI **0.0%**) due to `2.36 A` (`0.64%`) bolted capacitive SLG return & `√3` pu neutral shift (phase faults stay **100.0% / 99.7%**; in-domain CV **91.4% / 88.0%**). Active (`6,097` events): zero-shot GBDT **55.4%**, GATv2 **46.2%** → **76.2%** at 20% few-shot | **FAIL (`P1-Fail` SLG)** · **PARTIAL (`P2-Partial`, `A2-Partial`, GBDT `A2-Fail`)** | [`results/transfer/phase3_ieee37.json`](results/transfer/phase3_ieee37.json), [`results/active_grid_ieee37/phase_active_ieee37.json`](results/active_grid_ieee37/phase_active_ieee37.json) |
| **Active DER + Loops + Conformal (123 → 34)** | Kaggle GPU + Local | Active 123 CV (`17,847`): GATv2 **95.8%** (FPR **6.5%**) vs GBDT **93.9%** (13.9%) & FPI **40.7%**. Active 34 0-shot (`9,491`): GBDT **83.8%** > GATv2 **77.6%** (20% few-shot GATv2 **89.1%** > GBDT **83.1%**), but both miss ≤ 5% 0-shot FPR (`22.1% / 25.3%`). Pre-registered `aps_det` is degenerate (`6.37` labels); post-hoc `aps_rand` 95% hits **95.0%** in-domain (`1.09` labels) but **fails** cross-feeder zero-shot (**81.4% / 91.1%**) | **PASS (`C1`)** · **PARTIAL (`C2`, `C3` post-hoc)** · **FAIL (0-shot conformal transfer)** | [`results/active_grid/phase_active_ieee34.json`](results/active_grid/phase_active_ieee34.json) |
| **Two-Tier Edge HIF-Sensor → Graph FLISR** | Kaggle GPU | Paired ablation (`60Hz_only → +Edge`, 5 Emanuel surfaces, 7 disturbances): passive 123 SLG `400 Ω` **78.1% → 97.7%** (GBDT) / **79.6% → 96.0%** (GNN); active 123 `NO_FAULT` FPR **6.5% → 1.2%** (GATv2); active 34 0-shot FPR **22.1% → 5.8%** (GBDT) / **25.3% → 9.7%** (GATv2); `aps_rand` 95% singleton share **89.2% → 93.0%**. **Honest real-arc gap:** standalone Tier-1 drops **94.7% → 56.0%** on real 22 kV VeHIF vegetation recordings without retraining (cited from [`research/hif-fusion/PLAN.md`](research/hif-fusion/PLAN.md)) | **PASS (`H1–H4` 4/4, sim only)** · **Real-arc VeHIF gap & ≥ 15.36 kHz hardware limit disclosed** | [`results/hif_fusion/dataset_summary.json`](results/hif_fusion/dataset_summary.json) |

### Security & Repository Hygiene Policy

- **What is published in Git:** Open-source code (`shf/`, `scripts/`, `tests/`, `harness/`, `board/`, `scada/`, `notebooks/`), pre-registered research plans (`research/*/PLAN.md`), verified simulation outputs (`results/`, `docs/data/`), CAD/3D/LTspice source drawings and exports (`cad/`, `mech/`, `spice/`, `exports/`, `docs/models/`, `docs/drawings/`), and the static GitHub Pages site (`docs/`).
- **What is strictly kept out of Git** (enforced by [`.gitignore`](.gitignore), local `.git/info/exclude`, and the automated secret scanner in [`harness/check.py`](harness/check.py)):
  - All credentials, API keys, and tokens (`.env`, `.env.*`, `.kaggle/`, `kaggle.json`; the study calls **0** outside APIs today — see [`config/apis.md`](config/apis.md)).
  - Internal local workspace files and private notes (`ops/`, `CLAUDE.local.md`, `HANDOFF.md`, `inputs/private/`, `docs/RESUME_BULLETS.md`).
  - Regenerable large datasets, trained pickle/checkpoint weights, and raw third-party downloads (`data/generated/`, `models/`, `data/external/`, `dist/`).
- **Static GitHub Pages guarantee:** [`docs/index.html`](docs/index.html) and [`docs/monitor/`](docs/monitor/README.md) are 100% static client-side HTML/CSS/JS — **no backend server, no analytics or user tracking, no embedded API keys or credentials**.

</details>

<details>
<summary><b>2. Tier 1 · Edge HIF Sensor (<code>hif_sensor/</code>): LTspice 50/60 Hz, Phase 0/1/1.5 VeHIF &amp; C Firmware</b></summary>

<br>

The standalone ESP32-S3 high-impedance fault sensor lives in [`hif_sensor/`](hif_sensor/) and publishes directly to the unified report tab [`docs/hif-sensor/index.html`](docs/hif-sensor/index.html) ([live](https://chau1912550.github.io/self-healing-feeder/hif-sensor/)):

- **Analog front end (`hif_sensor/circuit/`):** SCT-013-000 clamp CT (2000:1) → 33 Ω burden (`16.5 mV/A`) → 1.65 V VREF bias → 4th-order Butterworth Sallen-Key LPF (`fc = 2,045.1 Hz` in LTspice 26.1.1, `−46.4 dB` at 60 Hz Nyquist `7.68 kHz`, `4.38°` lag at 60 Hz). Also includes explicit **50 Hz Vietnam/Australia** analysis (`FS_ADC = 12.8 kHz`, Nyquist `6.4 kHz`: `−40.0 dB` on the same PCB, or `−46.7 dB` by scaling two resistors ×1.2 with zero PCB layout change).
- **Phase 0 (4,000 simulated Emanuel arcs, 5 surfaces, 7 disturbances):** 417-parameter (`504 B` int8) Tiny MLP (`16→16→8→1`) detects **94.7%** at **1.5%** normal FA (median delay `5` cycles) vs 51N **0.5%** and 3rd harmonic **0.0%**; leave-one-surface-out stays **93.0–98.5%**; withholding `arc_welder` honestly exposes **17.5%** FA vs **0.0%** when seen ([`hif_sensor/results/metrics.json`](hif_sensor/results/metrics.json)).
- **Phase 1 (250 real 22 kV 50 Hz VeHIF vegetation-fault recordings + 53 real background recordings):** Frozen Phase-0 model scores **56.0%** overall (`36.2%` in `0–1 A`, `70.0%` in `1–2 A`, `94.7%` in `2–5 A`, `85.7%` in `5–10 A`) with **0.0%** false alarms on all 53 real background recordings (51N **0.0%**, 3rd harmonic **0.4%**). Feature-shift diagnostics show real vegetation arcs are far more symmetric (`dc_ratio −0.49 IQR`, `h2_ratio −0.47 IQR`, `even_ratio −0.46 IQR`) ([`hif_sensor/results/real_vehif.json`](hif_sensor/results/real_vehif.json)).
- **Phase 1.5 (completed on Kaggle; pre-registered in [`hif_sensor/PLAN_PHASE15.md`](hif_sensor/PLAN_PHASE15.md)):**
  - **C firmware GCC `13.3.0` parity ([`hif_sensor/results/c_firmware_verify.json`](hif_sensor/results/c_firmware_verify.json)):** `hif_sensor/firmware/hif_infer.c` + `test_infer.c` compiled with `-O2 -Wall -Wextra -Werror` (`17,032 B` binary, `417` params, `504 B` int8 weights + float biases) achieves **100%** decision agreement and `PERSIST = 3` state-machine pass across Phase-0 6 official vectors (`hif_model.h`, `thr=0.982635`, `max |p_c - p_py| = 4.77e-7`, `mean = 7.95e-8`, `0.540 µs/inf`), Phase-0 100 extended vectors (`max = 8.34e-7`, `mean = 4.34e-8`, `0.611 µs/inf`), and Phase-1.5 100 adapted vectors (`hif_model_phase15.h`, `thr=0.924894`, `max = 1.04e-6`, `mean = 1.22e-7`, `0.569 µs/inf`) → **`P1.5-D: true`**.
  - **50 Hz (VN/AU 22 kV) vs 60 Hz (US 12.47 kV) ([`hif_sensor/results/phase15_vehif.json`](hif_sensor/results/phase15_vehif.json)):** Running `256` samples/cycle at 50 Hz (`12.8 kHz` ADC, `6.40 kHz` Nyquist, `160.0 ms` 8-cycle window) on the same PCB gives `−39.99 dB` @ Nyquist vs `−46.34 dB` at 60 Hz (`15.36 kHz` ADC, `7.68 kHz` Nyquist, `133.33 ms`); scaling resistors `R×1.2` (`10.5 kΩ` / `5.36 kΩ`, same PCB and capacitors) gives `fc = 1,688.73 Hz`, `−46.70 dB` @ `6.40 kHz` Nyquist (`4.412°` lag at 50 Hz). Simulated test accuracy holds steady (**94.33%** / `1.67%` FA on 600 50 Hz events vs **94.70%** / `1.49%` FA on 800 60 Hz events). On the 250 VeHIF recordings (`90 s` max window vs `120 s` in Phase 1), zero-shot detection is **54.4%** at both 50 Hz native (`0–2 A` **43.09%**, `0–1 A` `31.9%`, `1–2 A` `74.0%`, `2–5 A` `94.7%`, `5–10 A` `85.7%`, `>10 A` `100.0%`) and 60 Hz resampled (`0–2 A` **43.62%**), with **0.0%** FA on 53 bg (`1.2%` control FA).
  - **Zero-shot feature-group ablation (50 Hz native, 250 VeHIF + 53 bg):** `all_16` (**94.7%** sim / **54.4%** real, `0–2 A` **43.1%**), `no_asymmetry_12` (**40.2%** / **22.4%**, `0–2 A` **22.3%**), `no_top_shift_9` (**40.7%** / **13.2%**, `0–2 A` **12.2%**), `harmonics_only_7` (**86.6%** / **46.4%**, `0–2 A` **31.4%**), and `temporal_only_8` (**86.1%** sim at `2.5%` FA / **55.6%** real, `0–2 A` **51.1%**, `0.4%` ctrl FA, `0.0%` bg FA).
  - **Few-shot VeHIF adaptation (5 seeds, `60%` held-out = `179` fault / `33` bg, recording-ID disjoint):** `zero_shot_phase0` scores **53.30%** overall (**42.52%** `0–2 A`, `1.12%` ctrl FA, `0.0%` bg FA). Recalibrating only the output head (`head_recal_int8`) degrades to **46.59% / 46.03% / 44.80%** (`0–2 A` **38.67% / 38.37% / 37.19%**) at `5% / 10% / 20%`, whereas joint fine-tuning (`joint_mlp_int8`, same `504 B` int8 footprint) climbs to **49.50% / 56.42% / 60.22%** overall and **40.15% / 46.81% / 49.93%** in `0–2 A` (`+7.41 pp` at `20%`, `0–1 A` `31.02% → 41.63%`, `1.82%` real bg FA, `0.67%` ctrl FA, `93.84%` sim retention, `1.53%` sim FA).
  - **Honest pre-registered criteria verdict:** **`P1.5-A: false`** (`+7.41 pp` fell short of the `>= +15 pp` bar in `0–2 A`), **`P1.5-B: true`** (`1.82%` bg FA & `0.67%` ctrl FA `<= 3.0%`), **`P1.5-C: true`** (`93.84%` sim `>= 88.0%` & `1.53%` FA `<= 3.0%`), **`P1.5-D: true`**.

</details>

<details>
<summary><b>3. Tier 2 · Full FLISR Results: 123-Bus, Error Analysis, LTspice, IEEE 34/37 Transfer, 15 Feeders, Active DER, Conformal &amp; HIF-Fusion</b></summary>

<br>

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
| Active DER + loops + `NO_FAULT` · FPI | 44.5% (FPR 0.0%) | 79.4% | 0.0% | – | – | 41.6% |
| Active DER + loops + `NO_FAULT` · Per-node GBDT | **55.4%** (FPR **3.4%**) | **93.1%** | **13.2%** | 45.3% / 62.0% | **88.3%** / **78.6%** | **49.6%** |
| Active DER + loops + `NO_FAULT` · ActiveGridGATv2 | 46.2% (FPR 11.8%) | 88.4% | 0.2% | **55.3%** / **76.2%** | 85.7% / 72.9% | 44.3% |

- **Why passive 34-bus scores higher at 400 Ω:** the fault current is large next to the load. At nominal load (OpenDSS, [`scripts/signal_to_load.py`](scripts/signal_to_load.py)), a 400 Ω ground fault on the 24.9 kV 34-bus draws a median 31.7 A, 61.1% of the 51.8 A feeder-head current; on the 4.16 kV 123-bus it draws 6.2 A, 1.0% of 631.5 A. On a passive radial tree, per-node GBDT transfers at least as well as the GNN.
- **Why passive zero-shot drops on underground delta IEEE 37-bus (`P1-Fail`, [`research/ieee37-underground/PLAN.md`](research/ieee37-underground/PLAN.md)):** IEEE 37-bus has no grounded substation neutral, so an SLG fault returns only through healthy-phase underground cable charging capacitance. At nominal load (`369.5 A` at head device `D1`), median SLG fault current is just **2.36 A** (**0.64%** of head current) even bolted at `0.01 Ω`, and **2.23 A** (**0.60%**) at `400 Ω`, while unfaulted phase-to-ground voltages shift toward `√3` pu — a physical regime absent from 4-wire grounded IEEE 123-bus training data. Both frozen models therefore fail the pre-committed `P1-Main` criterion (`56.4%` GBDT, `46.7%` GNN vs `43.0%` FPI): SLG accuracy collapses to `22.4%` (GBDT) and `5.6%` (GNN; FPI detects `0.0%`). By contrast, phase faults (`3PH/LL/LLG`, which circulate directly phase-to-phase) generalize almost perfectly (**100.0%** GBDT, **99.7%** GNN vs **98.2%** FPI), and 5-fold in-domain CV on IEEE 37-bus reaches **91.4%** / **88.0%** overall (**85.0%** / **79.6%** on SLG), showing the 21 features carry localizable delta signatures once trained on ungrounded-delta data. With 20% few-shot (7 buses), `ZoneTreeGNN` rises to **66.0%** without forgetting phase faults, while warm-start GBDT regresses to **55.1%** (overfitting the sampled zones).
- **Where graph attention earns its complexity:** adding 0–50% current-limited inverter DERs (`Generator Model=7`), back-fed reconfigurations, closed-loop operation, SLG faults up to 10,000 Ω on 24.9 kV (2.9% of the head current at nominal load; still easier than 400 Ω on 4.16 kV), and ~15% non-fault operational transients (`NO_FAULT`: capacitor switching, PV cloud drops, load steps) drops FPI to 40.7% on 123-bus and 47.6% on 34-bus. Here the bidirectional edge-aware **ActiveGridGATv2** beats per-node GBDT on active 123-bus (**95.8%** vs 93.9%, cutting `NO_FAULT` false trips in half from 13.9% to **6.5%**), at 20% few-shot on 34-bus (**89.1%** vs 83.1%), and in-domain on 34-bus (**93.1%** vs 91.8%), while GBDT is higher in pure zero-shot (**83.8%** vs 77.6%) where sudden +30–80% load steps on 34-bus mimic 2.5–10 kΩ HIFs. On the active underground delta IEEE 37-bus (Kaggle GPU run of `notebooks/kaggle_active_ieee37.ipynb`, [`results/active_grid_ieee37/`](results/active_grid_ieee37/), 6,097 events), the same SLG physics dominates: FPI reaches 44.5%, zero-shot GBDT 55.4% and ActiveGridGATv2 46.2% (pre-committed verdict `A2-Partial`: GBDT fails, GATv2 passes only through adaptation). With 20% of the buses (7) for fine-tuning, ActiveGridGATv2 climbs to **76.2%** (GBDT 62.0%), against 85.7% / 88.3% in-domain.
- **Multi-feeder zero-shot evidence across 15 official OpenDSS circuits ([`results/transfer/multi_feeder_benchmark.json`](results/transfer/multi_feeder_benchmark.json), [`multi_feeder_benchmark.csv`](results/transfer/multi_feeder_benchmark.csv), [`research/multi-feeder-benchmark/PLAN.md`](research/multi-feeder-benchmark/PLAN.md)):** running the exact frozen IEEE 123-bus models unchanged across 9 additional official IEEE/EPRI OpenDSS feeders (3 parallel Kaggle VMs, 0.416–34.5 kV, 50 Hz & 60 Hz, up to 6,058 buses and 18 zones) passes **10 of 11 total unseen feeders**: IEEE 13-bus (95.5% GBDT / 89.0% GNN vs 50.9% FPI), **50 Hz IEEE European LV** (93.3% / 91.3% vs 60.3% FPI), **IEEE 8500-Node** (99.8% / 99.0% vs 44.1% FPI), and all six utility-scale EPRI feeders (Ckt5 98.0%/97.6%, 18-zone Ckt7 98.7%/99.2%, 34.5 kV Ckt24 99.7%/98.6%, J1 99.2%/99.3%, K1 99.7%/99.6%, M1 99.6%/88.3%). On all six large EPRI feeders, `ZoneTreeGNN` beats per-node GBDT whenever one sensor is offline (e.g., **94.3%** vs **90.5%** on 18-zone EPRI Ckt7). Heavily meshed IEEE 342-Node (71 closed cycles), non-converged IEEE 9500-Node (in OpenDSSDirect 0.9.4), and absent CIGRE MV are logged transparently as out-of-scope.
- **Stage 2 (bus ranking inside the predicted zone):** 3-phase Takagi reactance using OpenDSS 3×3 line impedance matrices (zero training) reaches **46.9% top-1 / 69.0% top-3** on 123-bus and **57.5% top-1 / 87.4% top-3** on 34-bus (vs 8.8% / 26.4% and 19.3% / 50.8% random; 17.8% / 38.5% and 50.8% / 85.8% for a bus-graph GNN). The top confused bus pairs (`61→61s`, `160→160r`, `832→888`) have `ΔX1 = 0.000 Ω`: parallel laterals at the same electrical distance cannot be separated without extra sensors. On underground delta IEEE 37-bus ([`results/transfer/phase2b_bus_ieee37.json`](results/transfer/phase2b_bus_ieee37.json), pre-committed verdict `P2-Partial`), overall accuracy drops to **38.4% top-1 / 53.4% top-3** for Takagi and **37.2% / 53.9%** for zero-shot `BusGraphGNN` (vs **17.0% / 42.1%** random-in-zone) because ungrounded-delta SLG capacitive return breaks the grounded-loop Takagi equation and compact underground cables have tiny adjacent-bus reactances (`701→702`, `ΔX1 = 0.0599 Ω`; `728→729`, `ΔX1 = 0.0077 Ω`); on phase faults (`3PH/LL/LLG`), Takagi still reaches **94.4%** top-3 and zero-shot `BusGraphGNN` **95.2%** (vs **69.4%** random).
- **Split Conformal Prediction (pre-registered, then checked post-hoc):** the pre-registered deterministic APS score saturates. At a 95% target its sets hold 6.37 of 11 labels on average and cover 100.0% of active 123-bus events, so the rule "act only on a one-label set" acts on just 22.6% of events (ActiveGridGATv2). Criterion C3 is met as written, but that coverage is close to trivial. A post-hoc check on the same probabilities and splits with randomized APS (Romano et al. 2020; [`scripts/active_conformal_posthoc.py`](scripts/active_conformal_posthoc.py), Addendum A in [`research/active-grid-gnn/PLAN.md`](research/active-grid-gnn/PLAN.md)) hits the target on the training feeder: 95.0% coverage with 1.09 labels per set; one-label sets cover 89.2% of events, are right 99.1% of the time, and 1.1% of non-fault events would trip. It does **not** carry over to the unseen 34-bus feeder: the 123-bus threshold covers 81.4% (ActiveGridGATv2) and 91.1% (GBDT) against the 95% target, and recalibrating on 2 of its fault buses reaches 92.0% and 94.2% on average (worst of 10 draws 81.5% and 91.3%). The guarantee needs calibration data from the feeder it is used on; here it is a decision-support gate in simulation, not a protection guarantee. On active IEEE 37-bus, where randomized APS was pre-registered, the 123-bus threshold covers only 47.4% (ActiveGridGATv2) and 81.1% (GBDT); recalibrating on 2 of its fault buses reaches 94.1% and 93.9% on average (worst of 10 draws 86.2% and 88.9%). In the pre-registered calibration-size sweep (50 draws), 5% of the buses gives a mean of 93.1% (GATv2) and 92.8% (GBDT), short of the bar; 20% (7 fault buses) gives 94.8% mean / 92.6% 10th percentile (GATv2) and 94.6% / 92.0% (GBDT), so criterion `A3-Recal` is met from 20% of the buses, not from 5%.

**Two-tier Edge HIF-Sensor → Graph FLISR for 200–400 Ω and active HIFs (report section 2d, pre-registered plan [`research/hif-fusion/PLAN.md`](research/hif-fusion/PLAN.md)):** on the 4.16 kV IEEE 123-bus feeder, a 400 Ω SLG fault draws a median 6.2 A (1.0% of the 631.5 A head current), sitting inside the 1% 60 Hz CT noise floor and causing 92% of all main-study errors (SLG 400 Ω accuracy 76.5% at 60 Hz). To address this physical ceiling without changing any published results in sections 2a–2c, the two-tier architecture couples a local **Tier-1 Edge ESP32-S3 HIF-Sensor** ([`shf/hif_edge.py`](shf/hif_edge.py): residual clamp CT `SCT-013-000` 2000:1 + 33 Ω burden, LTspice-verified 4th-order Butterworth Sallen-Key low-pass filter at `-3 dB = 2,045.1 Hz` / Python bilinear IIR `2,047.9 Hz`, 12-bit ADC at `15.36 kHz` / 256 samples per 60 Hz cycle, 16 harmonic/asymmetry/cycle-volatility features over an 8-cycle window, and a frozen quantized int8 Tiny MLP `16→16→8→1` with 417 parameters / 504 bytes and `PERSIST = 3` relay persistence) at every recloser/switch into **Tier-2 Graph FLISR** ([`shf/hif_fusion.py`](shf/hif_fusion.py), [`scripts/hif_fusion_run.py`](scripts/hif_fusion_run.py)):

- **Paired ablation (`60Hz_only` vs `60Hz_plus_edge`, Kaggle GPU run of [`notebooks/kaggle_hif_fusion.ipynb`](notebooks/kaggle_hif_fusion.ipynb) with frozen `model_int8.npz` from `christoopherchau/ch-y-n`, [`results/hif_fusion/`](results/hif_fusion/)):** appends `(p_hif, hif_alarm)` to each node's live-sensor block (`21 → 23` passive; `26 → 28` active plus 5th directed edge feature `diff_p_hif`) on identical OpenDSS events, folds, and seeds across 5 Emanuel arc surfaces and 7 background disturbances. All four pre-registered criteria **`H1–H4` PASS** (simulation only; no field data):
  - **Passive IEEE 123-bus (5-fold bus CV, 11,448 events):** `PerNodeGBDT` rises from 98.2% to **99.7%** overall (**87.5% → 98.0%** on SLG 200–400 Ω, **78.1% → 97.7%** at 400 Ω, 1-sensor-offline **89.0% → 90.3%**); `ZoneTreeGNN` rises from 98.0% to **99.5%** (**86.4% → 97.0%** on SLG 200–400 Ω, **79.6% → 96.0%** at 400 Ω, 1-sensor-offline **90.0% → 91.5%**). On unseen passive IEEE 34-bus zero-shot (4,104 events), both stay at ceiling (`99.8% → 99.8%` GBDT, SLG 200–400 Ω `98.5% → 98.7%`; `99.4% → 99.4%` GNN, SLG 200–400 Ω `95.9% → 97.6%`).
  - **Active IEEE 123-bus (0–50% DER, reconfigured/looped, 17,847 events):** `ActivePerNodeGBDT` rises `93.9% → 96.8%` overall (`80.2% → 90.3%` SLG 200–400 Ω, `72.5% → 86.8%` at 400 Ω, `NO_FAULT` FPR `13.9% → 3.3%`, 1-sensor-offline `86.1% → 88.7%`); `ActiveGridGATv2` rises `95.8% → 97.6%` overall (**82.2% → 90.8%** SLG 200–400 Ω, **73.5% → 87.5%** at 400 Ω, `NO_FAULT` FPR **`6.5% → 1.2%`** with every one of the 7 disturbances ≤ 6.7%, 1-sensor-offline `89.1% → 91.3%`).
  - **Active unseen IEEE 34-bus zero-shot (24.9 kV, 9,491 events):** `ActivePerNodeGBDT` rises `83.8% → 87.5%` overall (`71.8% → 77.8%` on 1–10 kΩ HIF SLG, `NO_FAULT` FPR `22.1% → 5.8%`, 1-sensor-offline `72.4% → 75.6%`); `ActiveGridGATv2` rises `77.6% → 83.3%` overall (`65.3% → 70.0%` on 1–10 kΩ, `NO_FAULT` FPR `25.3% → 9.7%`, 1-sensor-offline `71.5% → 74.5%`).
  - **Split Conformal (`aps_rand`, 95% target, `ActiveGridGATv2`):** IEEE 123-bus coverage stays at **95.0%** (`95.0%` at 60 Hz) while autonomous one-label sets jump from `89.2%` to **93.0%** (**98.9%** right, only **0.5%** autonomous `NO_FAULT` trip share). On unseen 34-bus, frozen 123-bus `q̂` rises `81.4% → 84.9%` (still carrying no cross-feeder guarantee) and 5%-bus recalibration averages `92.0%` (min `85.4%`). Deployment requires ≥ 15.36 kHz edge sensing behind a ~2 kHz anti-alias filter at each switch — legacy 60 Hz SCADA cannot supply `p_hif`, and simulated Emanuel arcs do not prove field performance.

</details>

<details>
<summary><b>4. Isolation, Tie-Switch Restoration &amp; 8,760-Hour PJM AEP Seasonal Study</b></summary>

<br>

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

</details>

<details>
<summary><b>5. Interactive Website Guide &amp; Screenshots</b></summary>

<br>

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

[![Run report: headline numbers and run checks](docs/images/report-headline.png)](https://chau1912550.github.io/self-healing-feeder/#health)

![The 3D feeder model: zones, one wire per phase, poles, transformers, switches, regulators and the substation](docs/images/report-3d.png)

![The 3D error map: red columns where faults get misplaced, arrows from the true zone to the wrong guess](docs/images/report-3d-errors.png)

</details>

<details>
<summary><b>6. Project Structure, How It Works &amp; Run Commands</b></summary>

<br>

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
├── tests/                 # pytest suite
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
├── hif_sensor/           # Tier-1 Edge HIF Sensor (LTspice CT/LPF, 504 B int8 MLP, VeHIF 22 kV, C firmware)
├── exports/               # what the report reads from those apps (PDF, SVG, GLB, CSV)
└── docs/
    ├── index.html         # Tier-2 Feeder FLISR report (GitHub Pages), built by shf/dashboard.py
    ├── hif-sensor/        # Tier-1 Edge HIF Sensor report tab (LTspice, 50/60 Hz, VeHIF 22 kV, C parity)
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
| Active DER grids & Conformal sets | `shf/active_grid.py`, `shf/active_models.py`, `scripts/active_grid_run.py`, `scripts/active_conformal_posthoc.py`, `notebooks/kaggle_active_grid.ipynb`, `notebooks/kaggle_active_ieee37.ipynb` | 0–50% current-limited inverter DER (`Model=7`), reconfigured/closed-loop topologies, SLG faults up to 10,000 Ω on 24.9 kV, non-fault operational transients (`NO_FAULT`), bidirectional edge-aware `ActiveGridGATv2`, and Split Conformal Prediction (90%/95% Adaptive Prediction Sets) |
| Two-tier Edge HIF-Sensor → Graph FLISR | `shf/hif_edge.py`, `shf/hif_fusion.py`, `scripts/hif_fusion_run.py`, `notebooks/kaggle_hif_fusion.ipynb` | Couples a simulated Tier-1 Edge HIF-Sensor (4th-order Butterworth LPF at 2,045.1 Hz, 12-bit 15.36 kHz ADC, 16 features, frozen 417-param / 504 B int8 Tiny MLP) into Tier-2 `PerNodeGBDT` / `ZoneTreeGNN` / `ActiveGridGATv2` + `aps_rand` 95% across 5 Emanuel arc surfaces and 7 background disturbances (`results/hif_fusion/`, report section 2d; completed on Kaggle GPU) |
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
.venv\Scripts\python -m pytest                              # full Tier-2 test suite (144 tests)
pushd hif_sensor && ..\.venv\Scripts\python -m hif.provenance --verify && ..\.venv\Scripts\python -m pytest -v tests/test_hif.py && popd  # Tier-1 provenance (23 files) + tests (10 tests)
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
.venv\Scripts\python scripts/hif_fusion_run.py --quick       # two-tier Edge HIF-Sensor -> Graph FLISR smoke test (full run via notebooks/kaggle_hif_fusion.ipynb)
.venv\Scripts\python scripts/signal_to_load.py             # ~1 s, fault current vs feeder-head current -> results/transfer/
.venv\Scripts\python scripts/demo_event.py --bus 60 --type SLG --r 50
.venv\Scripts\python scripts/panel_bridge.py             # drives the Wokwi ESP32 panel over MQTT (see board/README.md)
```

**Run in the cloud instead (nothing installed locally):** import [`notebooks/kaggle_run.ipynb`](notebooks/kaggle_run.ipynb) into Kaggle. Then set *Internet: On* and *Accelerator: None*, put your repo URL in the second cell, and run *Save & Run All*. Download `results.zip` from the Output tab. Step-by-step guide (Vietnamese): [`docs/vi/github-kaggle-guide.md`](docs/vi/github-kaggle-guide.md). The hourly study has its own notebook, [`notebooks/kaggle_hourly.ipynb`](notebooks/kaggle_hourly.ipynb): add the code bundle and the Kaggle dataset *Hourly Energy Consumption* as inputs, run all, and download `hourly.zip`. The active-grid GNN + Split Conformal study runs on a Kaggle GPU VM via [`notebooks/kaggle_active_grid.ipynb`](notebooks/kaggle_active_grid.ipynb) (IEEE 34-bus) and [`notebooks/kaggle_active_ieee37.ipynb`](notebooks/kaggle_active_ieee37.ipynb) (IEEE 37-bus). The two-tier Edge HIF-Sensor → Graph FLISR experiment runs on a Kaggle GPU VM via [`notebooks/kaggle_hif_fusion.ipynb`](notebooks/kaggle_hif_fusion.ipynb) with frozen `model_int8.npz` attached (completed on Kaggle GPU; results in [`results/hif_fusion/`](results/hif_fusion/)).

Optional MQTT + TimescaleDB (requires Docker):

```bash
docker compose -f scada/docker-compose.yml up -d
pip install "psycopg[binary]"
python scada/ingest.py --mqtt localhost --db postgresql://postgres:postgres@localhost:5432/shf
python scripts/demo_event.py --bus 60 --mqtt localhost
```

## Keeping it correct

Numbers in the prose are read from `results/` and listed in `harness/facts.toml`; the only typed numbers are assumptions from `shf/config.py` and IEEE test-case data. Every file in `results/` carries a run record in `results/provenance/` (23 manifests covering 51 result files: command, UTC time, git commit and a 64-character SHA-256 of each file; [`shf/provenance.py`](shf/provenance.py)). The health check fails if any result file no longer matches the run that wrote it.

The key numbers in this README (accuracies, patrol lengths, error counts, restored kW…) are listed in [`harness/facts.toml`](harness/facts.toml) with the result it comes from. [`harness/check.py`](harness/check.py) recomputes them from `results/` and fails if any text, published copy or link is out of date, or if any secret/credential file is tracked by git:

```bash
.venv\Scripts\python -m shf.provenance
.venv\Scripts\python harness/check.py --tests
```

[`AGENTS.md`](AGENTS.md) is the guide for AI coding agents (and people): project map, data flow, content rules and the definition of done. New source documents go in [`inputs/`](inputs/INDEX.md).

Work done in other apps has one folder each: AutoCAD drawings in [`cad/`](cad/README.md), SolidWorks parts in [`mech/`](mech/README.md), LTspice circuits in [`spice/`](spice/README.md), Factory IO scenes in [`hmi/`](hmi/README.md) and the ESP32 panel (Wokwi) in [`board/`](board/README.md), with their exports in [`exports/`](exports/README.md). Each file is listed in [`workflow.toml`](workflow.toml). The one-line diagram starts from `python scripts/export_oneline_dxf.py`, which draws [`cad/feeder_oneline.dxf`](cad/feeder_oneline.dxf) from `results/` (one layer per zone, switches as blocks, an A3 sheet with a title block); `python scripts/autocad_export.py --register` then has AutoCAD's command-line engine save the `.dwg` and plot the PDF and PNG, and the report shows the drawing in section 5. After an export, `python scripts/register_export.py <id>` records it, and the health check fails if the source later changes without a new export. The study calls no outside API; any future one is registered in [`config/apis.md`](config/apis.md), with keys in a git-ignored `.env`.

</details>

<details>
<summary><b>7. Assumptions, Limitations &amp; References</b></summary>

<br>

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
- **Urban underground 3-wire delta IEEE 37-bus (`results/transfer/*ieee37*`, [`research/ieee37-underground/PLAN.md`](research/ieee37-underground/PLAN.md)):** unmodified 4.8 kV 3-wire ungrounded delta underground cable feeder (`data/feeder/ieee37/`, IEEE underground line codes `721`–`724`, delta-delta substation transformer, open-delta head regulator, unbalanced delta spot loads, no shunt capacitor banks). **ASSUMPTION:** no artificial earthing/zig-zag transformer is added, so SLG faults return purely through healthy-phase cable charging capacitance (`2.36 A` / `0.64%` at `0.01 Ω` and `2.23 A` / `0.60%` at `400 Ω` vs `369.5 A` head current) and shift unfaulted phase-to-ground voltages toward `√3` pu. Applying the frozen 5%-load `PLACEMENT_RULE` yields 10 switching zones (`D1`–`D10`) across 36 3-phase buses (`2,457 kW` nominal load). For the active-grid IEEE 37-bus stage (completed on Kaggle GPU; results in [`results/active_grid_ieee37/`](results/active_grid_ieee37/)), 3 delta-connected `Generator Model=7` DERs are placed at `738`, `708`, and `720` (0–50% penetration), an adjacent 230/4.8 kV delta-delta tie `Tie37` connects to bus `741` (`D9`) for `reconfig_tie` (`D6` open) and `looped_tie`, SLG resistances span `0.01–400 Ω`, and `NO_FAULT` events split 50/50 between `pv_cloud` and `load_step` (`cap_switch = 0` because the feeder has no capacitor banks). Pure steady-state OpenDSS phasor simulation; no EMT cable transients, no CT saturation, and no field data.
- **Active DER grids & Split Conformal Prediction (`results/active_grid/`):** inverter-interfaced DERs are modeled in OpenDSS as `Generator Model=7` (current-limited to ~1.1–1.2 pu at unity power factor) across 0%, 25%, and 50% penetration at pre-registered candidate buses (`ACTIVE_DER_BUSES_123` and `ACTIVE_DER_BUSES_34`, marked `ASSUMPTION` in `shf/active_grid.py`). Topologies include radial normal, tie-reconfigured back-feed, and weakly meshed closed-loop states (`Sw7` closed on 123-bus; an assumed 10 kft tie `828–832` on 34-bus). The 24.9 kV 34-bus active sweep extends SLG fault resistance up to 10,000 Ω to move toward the 4.16 kV signal-to-load ratio, but does not reach it: at nominal load a 10,000 Ω fault on 34-bus draws a median 2.9% of the feeder-head current, against 1.0% for 400 Ω on 123-bus (`results/transfer/signal_to_load.json`). Non-fault operational transients (`NO_FAULT`) are steady-state phasor snapshots of capacitor bank switching, 70–90% PV cloud drops, and +30–80% load steps, not EMT sub-cycle waveforms.
- **Two-tier Edge HIF-Sensor → Graph FLISR (`research/hif-fusion/PLAN.md`, `shf/hif_edge.py`, `shf/hif_fusion.py`, report section 2d):** both tiers are **simulation only** (no utility field recordings). Emanuel two-diode arc waveforms across 5 surfaces (`wet_grass`, `wet_sand`, `concrete`, `dry_grass`, `dry_asphalt`) and 7 background load/switching disturbances (`none`, `load_step`, `cap_switch`, `inrush`, `motor_start`, `arc_welder`, `nonlinear_fluct`) are synthesized via quasi-steady harmonic superposition scaled by OpenDSS per-switch incremental residual current (`dI_res`), omitting EMTP electromagnetic transients, frequency-dependent line/cable impedance, CT core saturation, and ESP32 ADC nonlinearity. Locked coupling assumptions (`ASSUMPTION` in `shf/hif_fusion.py`): arcing applies when SLG has `R ≥ 100 Ω` and `I_fault ≤ 45 A` RMS; local pre-fault residual unbalance is clipped to `[1.0, 20.0] A` RMS (calibration range of the SCT-013-000 + 33 Ω front end); healthy switches experience concurrent background disturbances with probability `0.25`. **Hardware requirement:** practical operation cannot use legacy 60 Hz SCADA/RTU polling — it requires edge IEDs or ESP32-S3-class sensor nodes sampling residual current at **≥ 15.36 kHz** (60 Hz) or **≥ 12.8 kHz** (50 Hz VN/AU, optionally scaling the Sallen-Key resistors `R×1.2` to `10.5 kΩ` / `5.36 kΩ` for `−46.70 dB` Nyquist attenuation on the same PCB) behind an analog anti-aliasing filter (`fc ≈ 2 kHz`) at every monitored recloser/switch. **Real-vs-simulated arc gap:** in the companion `hif-sensor` project, evaluating the frozen Phase-0 int8 model on real 22 kV vegetation-fault recordings dropped from `94.7%` simulated to `56.0%` zero-shot (`120 s` window), and Phase 1.5 20% few-shot `joint_mlp_int8` improved `0–2 A` detection by `+7.41 pp` (`42.52% → 49.93%`, `53.30% → 60.22%` overall), passing `P1.5-B/C/D` but falling short of the pre-registered `>= +15 pp` bar (`P1.5-A: false`) — confirming that simulated fusion gains do not substitute for field oscillogram validation or physical PCB bench testing.

## References

- IEEE PES Distribution Test Feeders — https://cmte.ieee.org/pes-testfeeders/resources/
- OpenDSS (EPRI) and IEEE 123-bus, 34-bus, and 37-bus model files — https://sourceforge.net/projects/electricdss/ (mirrored at https://github.com/dss-extensions/electricdss-tst; IEEE 37-bus: https://github.com/dss-extensions/electricdss-tst/tree/master/Version8/Distrib/IEEETestCases/37Bus)
- W. H. Kersting, "Radial distribution test feeders," *IEEE Trans. Power Systems*, vol. 6, no. 3, pp. 975–985, 1991 — https://doi.org/10.1109/59.119237
- J. Glass, A. Melin, M. Starke, B. Ollis, *Chattanooga Electric Power Board Case Study: Distribution Automation*, ORNL/LTR-2015/444, 2016 — https://www.osti.gov/biblio/1329733
- K. Chen et al., "Fault Location in Power Distribution Systems via Deep Graph Convolutional Networks," IEEE JSAC, 2019 — https://arxiv.org/abs/1812.09464
- S. Brody, U. Alon, E. Yahav, "How Attentive are Graph Attention Networks?" (GATv2), *ICLR*, 2022 — https://arxiv.org/abs/2105.14491
- T. Takagi, Y. Yamakoshi, M. Yamaura, R. Kondow, T. Matsushima, "Development of a New Type Fault Locator Using the One-Terminal Voltage and Current Data," *IEEE Trans. Power Apparatus and Systems*, vol. PAS-101, no. 8, pp. 2892–2898, 1982 — https://doi.org/10.1109/TPAS.1982.317615
- Y. Romano, M. Sesia, E. Candès, "Classification with Valid and Adaptive Coverage," *Advances in Neural Information Processing Systems (NeurIPS)*, 2020 — https://arxiv.org/abs/2006.02544
- R. Mulla, *Hourly Energy Consumption* (PJM hourly load in MW, file `AEP_hourly.csv`), Kaggle, CC0 — https://www.kaggle.com/datasets/robikscube/hourly-energy-consumption
- ANSI C84.1, *Electric Power Systems and Equipment — Voltage Ratings (60 Hz)*, Range A service voltage 114–126 V.
- A. E. Emanuel, D. Cyganski, J. A. Orr, S. Shiller, E. M. Gulachenski, "High impedance fault arcing on sandy soil in 15 kV distribution feeders: contributions to the evaluation of the low frequency spectrum," *IEEE Trans. Power Delivery*, vol. 5, no. 2, pp. 676–686, 1990 (two-diode arc model) — https://doi.org/10.1109/61.53070
- A. Ghaderi, H. L. Ginn, H. A. Mohammadpour, "High impedance fault detection: A review," *Electric Power Systems Research*, vol. 143, pp. 376–388, 2017 — https://doi.org/10.1016/j.epsr.2016.10.021
- R. P. Sallen and E. L. Key, "A Practical Method of Designing RC Active Filters," *IRE Trans. Circuit Theory*, vol. CT-2, no. 1, pp. 74–85, 1955 (4th-order Butterworth Sallen-Key anti-alias front end) — https://doi.org/10.1109/TCT.1955.6500159

- D. P. S. Gomes and C. Ozansoy, "High-Impedance Vegetation Fault Data Set" (VeHIF, 22 kV 50 Hz staged field tests, CC0), *IEEE Trans. Power Delivery*, vol. 37, no. 6, 2022 — https://arxiv.org/abs/2112.03651 · https://www.kaggle.com/datasets/dougpsg/highimpedance-vegetation-fault-data-set

## License

Code: MIT (see [`LICENSE`](LICENSE)). The IEEE 123-bus model files in `data/feeder/` come from the EPRI OpenDSS distribution and keep their original license.

---

Built with AI-assisted development (Claude Code). Vietnamese walkthrough of every module: [`docs/vi/module-guide.md`](docs/vi/module-guide.md).

</details>
