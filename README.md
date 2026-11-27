# Self-Healing Feeder + Edge HIF Sensor (2-Tier FLISR)

> **End-to-end 2-tier distribution protection & restoration** — coupling a **504-byte int8 ESP32-S3 high-impedance fault (HIF) sensor** (`hif_sensor/`) with **graph-based FLISR & power-flow restoration** (`shf/`) across **15 official IEEE/EPRI feeders**, **real 22 kV vegetation-fault recordings (VeHIF)**, and **8,760 real utility load hours (PJM AEP)**.

| 🌐 Tier 2 · Feeder FLISR Report | 🔌 Tier 1 · Edge HIF Sensor (ESP32) | 🕹️ Interactive Demos & Paper |
|---|---|---|
| **[Open Report (EN)](https://chau1912550.github.io/self-healing-feeder/?lang=en)** · **[Tiếng Việt](https://chau1912550.github.io/self-healing-feeder/?lang=vi)** | **[Open Sensor Report (EN / VI)](https://chau1912550.github.io/self-healing-feeder/hif-sensor/)** | **[Monitor Demo](https://chau1912550.github.io/self-healing-feeder/monitor/)** · **[Technical Paper](https://chau1912550.github.io/self-healing-feeder/study/)** ([VI](https://chau1912550.github.io/self-healing-feeder/study/?lang=vi)) |
| 3D feeder, quick-scan cards, 18 Q&A, SHA-256 ledger | LTspice CT/LPF, 50/60 Hz, VeHIF 22 kV, C99 DSP + MLP | 40 replay faults + 10s Wokwi ↔ Monitor demo · [16 Defense Q&A (VI)](docs/vi/defense-qa.md) · [GitHub Actions CI](.github/workflows/verify.yml) |

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
| **Tier 2 · Main IEEE 123-Bus FLISR** | **91.5%** zone accuracy vs **52.5%** FPI (11,448 faults, unseen buses; arcing HIF ≥ 100 Ω, per-zone load + drift, CT/PT bias & floor); patrol **39.0 → 7.3 kft** (−81%); ties restore **2,670 / 7,175 kW**; kW-min **−51%** | [`results/metrics.json`](results/metrics.json) |
| **Tier 1 + Tier 2 · HIF-Fusion (4/4 H1–H4 PASS)** | Passive 123-bus `400 Ω` SLG **78.1% → 97.7%** (GBDT); Active 123-bus `400 Ω` GATv2 **73.5% → 87.5%** while cutting `NO_FAULT` FPR **6.5% → 1.2%** | [`results/hif_fusion/dataset_summary.json`](results/hif_fusion/dataset_summary.json) |
| **Active DER (0–50%) + Loops + Conformal** | Active 123-bus GATv2 **95.8%** (FPR **6.5%**); 95% `aps_rand` singleton share **89.2% → 93.0%** (+Edge); honest fail on 0-shot cross-feeder conformal | [`results/active_grid/phase_active_ieee34.json`](results/active_grid/phase_active_ieee34.json) |
| **Cryptographic Audit & Tests** | **24** SHA-256 manifests (**58** files, **0** tampered) + Tier-1 [`hif_sensor/`](hif_sensor/results/provenance/manifest.json) manifest (**23** files, **0** tampered) + **154 unit tests** (**144** Tier-2 + **10** Tier-1 `pytest`, plus `harness/check.py` checks) | [`results/provenance/`](results/provenance/) |

[![Unified Report Page: Tier-2 FLISR, Tier-1 Edge HIF Sensor, and Monitor](docs/images/report-overview.png)](https://chau1912550.github.io/self-healing-feeder/)

---

## Independent Verification in 2 Commands (For Lecturers & Reviewers)

Every number in this repository is computed programmatically from [`results/`](results/) and checked by [`harness/facts.toml`](harness/facts.toml). Verify every SHA-256 hash, prose number, link, secret guard, and unit test locally:

```bash
python -m shf.provenance          # verifies all 24 SHA-256 manifests / 58 result files (0 changed, 0 missing, 0 unrecorded)
python harness/check.py --tests   # recomputes every prose number from results/, checks links, secrets, provenance & pytest
```

*(On Windows with the local venv, replace `python` with `.venv\Scripts\python`; on Linux/macOS use `.venv/bin/python`. To verify the bundled Tier-1 sensor manifest and tests directly: `pushd hif_sensor && ..\.venv\Scripts\python -m hif.provenance --verify && ..\.venv\Scripts\python -m pytest -v tests/test_hif.py && popd` — **23** files verified, **10 passed**.)*

---

## COMTRADE Fault-Record Ingest (Ready for Real Relay/Recloser Files)

- **What is COMTRADE?** IEEE C37.111 (`*.cfg` + `*.dat`, or single-file `*.cff`) is the standard fault-recording format saved by protection relays and reclosers.
- **Waveform → model features ([`shf/comtrade.py`](shf/comtrade.py)):** reads 1999 & 2013 files (`ASCII`, `BINARY`, `BINARY32`, `FLOAT32`, `.cff`, 50/60 Hz, primary/secondary CT/PT scaling), extracts pre- and post-fault phasors via full-cycle DFT, and builds the exact schemas expected by the bundled models: **15** features/device (`150` total for Tier-2 GBDT, missing devices filled with `NaN`), **21** (`shf/transfer.py`) and **26** (`shf/active_grid.py`) graph node features, plus **16** Tier-1 HIF residual features when sampling rate and duration (≥ 8 cycles) are sufficient.
- **Run in 1 command when real utility files arrive** (no code edits needed; guide & sample list in [`data/comtrade_samples/README.md`](data/comtrade_samples/README.md)):

```bash
# Single relay/recloser recording (set nominal line-to-line kV if needed):
.venv\Scripts\python scripts/comtrade_ingest.py path/to/event.cfg --v-base-kv 22.0 --out-features out.json

# Multi-device event folder (+ optional channel/device map JSON):
.venv\Scripts\python scripts/comtrade_ingest.py path/to/event_folder --channel-map path/to/channel_map.json

# Verify all bundled public + simulation round-trip samples -> results/comtrade/summary.json:
.venv\Scripts\python scripts/comtrade_ingest.py --verify-samples
```

- **Sample verification ([`results/comtrade/summary.json`](results/comtrade/summary.json)):** **11/11** pass — **5/5** public open-source IEEE C37.111 recordings (MIT / CC0-1.0 from external grids) and **6/6** simulation round-trip records: **3/3** 10-device OpenDSS events match direct OpenDSS predictions on all 3 models (Tier-2 GBDT, Transfer GBDT, Transfer GNN; max Tier-2 relative feature error `0.012%`), **2/2** LTspice exports match steady RMS within `0.0001%` and `100 Ω` arc `I1` within `0.0%`, and **1/1** Tier-1 HIF binary record matches `p_hif` with `0.0` error (`1.1e-05` max feature error).
- **Honest limitation:** No real utility field fault dataset on IEEE 123-bus has been evaluated; all bundled models are simulation-trained only (IEEE 123-bus, 4.16 kV, 60 Hz). A single-device file fills only **15/150** Tier-2 features (`135 NaN`) and cannot reliably locate the zone across a feeder (in the demo, 1 device mispredicts `L77` at `42.05%` confidence while all 10 devices recover true zone `Sw2` at `99.86%`). Real feeder use requires multi-device event folders from the target grid and field validation with confirmed fault locations.

---

## Detailed Technical Sections (Click to Expand)

<details>
<summary><b>1. Verification Ledger, 7 Pre-Registered Plans, Honest Pass/Fail Summary &amp; Security Policy</b></summary>

<br>

### Cryptographic Provenance Ledger & 7 Pre-Registered Plans

- **SHA-256 Provenance (`results/provenance/` + `hif_sensor/results/provenance/`):** Tier 2 maintains **24** run manifests covering **58** recorded result files (**0 changed / 0 missing / 0 unrecorded** via [`shf/provenance.py`](shf/provenance.py)); Tier 1 maintains [`hif_sensor/results/provenance/manifest.json`](hif_sensor/results/provenance/manifest.json) covering **23** files (**0 changed / 0 missing** via [`hif_sensor/hif/provenance.py`](hif_sensor/hif/provenance.py)). Each manifest logs the exact producer command, UTC timestamp, git commit (when run locally), and 64-character SHA-256 digest of every generated file.
- **Tier-1 Edge HIF-Sensor artifacts:** Frozen Phase-0 `model_int8.npz` (`417` parameters, `504` bytes, threshold `0.982635`, Kaggle kernel `christoopherchau/ch-y-n`), SHA-256 `3ba5bd23685d7964a6cea0c94064c1e65a8bf3129d83ac129215d110218397c1` (logged in [`results/hif_fusion/dataset_summary.json`](results/hif_fusion/dataset_summary.json)), plus Phase 1.5 few-shot adapted [`hif_sensor/results/model_phase15_int8.npz`](hif_sensor/results/model_phase15_int8.npz) / [`hif_sensor/firmware/hif_model_phase15.h`](hif_sensor/firmware/hif_model_phase15.h) (`417` parameters, `504` bytes, seed-0 20% `joint_mlp_int8` export threshold `0.924894`).
- **All 7 pre-registered research plans (hypotheses, assumptions, and pass/fail criteria locked before running):**
  1. [`research/gnn-transfer/PLAN.md`](research/gnn-transfer/PLAN.md) — Passive cross-feeder zero-shot transfer (IEEE 123-bus → 34-bus) & Stage-2 bus ranking.
  2. [`research/active-grid-gnn/PLAN.md`](research/active-grid-gnn/PLAN.md) — Active DER (0–50%), reconfigured/closed-loop topologies, 10 kΩ HIF, `NO_FAULT` transients & Split Conformal Prediction (incl. Addendum A/B1 post-hoc audits).
  3. [`research/ieee37-underground/PLAN.md`](research/ieee37-underground/PLAN.md) — Third unseen feeder: urban underground 4.8 kV 3-wire ungrounded delta IEEE 37-bus (passive & active).
  4. [`research/multi-feeder-benchmark/PLAN.md`](research/multi-feeder-benchmark/PLAN.md) — 15-feeder cross-feeder zero-shot benchmark across official IEEE/EPRI OpenDSS circuits (3 parallel Kaggle VMs).
  5. [`research/hif-fusion/PLAN.md`](research/hif-fusion/PLAN.md) — Two-tier Edge HIF-Sensor (`504 B` int8) → Graph FLISR paired ablation across 5 Emanuel arc surfaces and 7 background disturbances (legacy clean-60 Hz baseline).
  6. [`research/realistic-hif-sim/PLAN.md`](research/realistic-hif-sim/PLAN.md) — Realistic main-feeder fault simulation upgrade (intermittent Emanuel arcing HIF at SLG ≥ 100 Ω, independent per-zone load & pre/post load drift, CT/PT systematic bias + additive noise floor).
  7. [`research/hif-fusion-realistic/PLAN.md`](research/hif-fusion-realistic/PLAN.md) — Branch-10 Realistic Two-Tier HIF-Fusion: re-running the frozen `504 B` int8 (`15.36 kHz`) Edge HIF-Sensor → Graph FLISR paired ablation directly under Branch-10 intermittent arcing (`r_eff`, synchronized `arc_duty`), zone load drift, and CT/PT noise (pre-registered criteria `R1–R4`).

### Honest summary: Passing Evidence vs. Failures & Physical Limits (Simulation Only)

| Experiment / Study | Run Env | Key Verified Results (`results/`) | Pre-Registered Verdict | Primary Result File |
|---|---|---|---|---|
| **Main FLISR (IEEE 123-bus, 4.16 kV)** | Local CPU | `11,448` faults: ML **91.5%** vs FPI **52.5%** (`100 Ω`: **84.8%** vs 4.5%; `400 Ω`: **31.3%** vs 1.6%); `969` errors (`844` at ≥ 200 Ω); patrol **39.0 → 7.3 kft** (−81%); ties restore **2,670 / 7,175 kW**; kW-min **−51%** | **PASS** (sim; arcing HIF ≥ 100 Ω, zone load + drift, CT/PT bias/floor) | [`results/metrics.json`](results/metrics.json) |
| **Hourly Restoration (PJM AEP 2017)** | Kaggle / Local | `8,760` hours: **44.0%** year mean (**42.1%** 6 h-held) vs **37.2%** peak; summer 03:00 **50.0%** vs 17:00 **36.7%**; caveat: `74 of 8,760 hours` reach `1.0508 pu` | **PASS** (sim; regional load shape) | [`results/hourly/hourly.json`](results/hourly/hourly.json) |
| **LTspice Transient & Arcing HIF** | Local LTspice | Bus 60 bolted fault `6,119 A RMS`, peak `10,067 A` (`4.9 ms` τ); `400 Ω` Emanuel arc `6.00 A` (`97.8%` 60 Hz, `18.8%` 3rd harmonic, `3 counts` of 12-bit ADC) | **PASS** (sim; single-phase Thevenin) | [`results/spice/summary.json`](results/spice/summary.json) |
| **Passive Transfer (123 → 34-bus) + Stage-2** | Local CPU | Stage 1 zero-shot (`4,104` faults): GBDT **99.8%**, GNN **99.3%** vs FPI **55.5%**. Stage 2 (`top-1 / top-3`): zero-training Takagi **46.9% / 69.0%** (123) & **57.5% / 87.4%** (34) beats `BusGraphGNN` (**17.8% / 38.5%** CV on 123; **50.8% / 85.8%** 0-shot on 34) | **PASS** (Stage 1) · **FAIL** (`BusGraphGNN` loses to Takagi physics) | [`results/transfer/phase3_ieee34.json`](results/transfer/phase3_ieee34.json) |
| **15-Feeder Zero-Shot Benchmark** | Kaggle 3-VM | **10 of 11** unseen evaluated feeders pass (9/9 new IEEE/EPRI incl. 50 Hz EU-LV **93.3%**, IEEE 8500 **99.8%**, 34.5 kV EPRI Ckt24 **99.7%**; on 18-zone Ckt7 1-sensor-offline, GNN **94.3%** > GBDT **90.5%**). **3 honest out-of-scope:** IEEE 342-Node (71 cycles), IEEE 9500-Node (non-converged base flow), CIGRE MV (absent in repo) | **PASS** (10/11 unseen) · **3 out-of-scope disclosed** | [`results/transfer/multi_feeder_benchmark.json`](results/transfer/multi_feeder_benchmark.json) |
| **Underground Delta IEEE 37-bus (4.8 kV)** | Local CPU + Kaggle GPU | Passive (`5,184` faults): zero-shot GBDT **56.4%**, GNN **46.7%** vs FPI **43.0%** — SLG collapses (**22.4% / 5.6%**, FPI **0.0%**) due to `2.36 A` (`0.64%`) bolted capacitive SLG return & `√3` pu neutral shift (phase faults stay **100.0% / 99.7%**; in-domain CV **91.4% / 88.0%**). Active (`6,097` events): zero-shot GBDT **55.4%**, GATv2 **46.2%** → **76.2%** at 20% few-shot | **FAIL (`P1-Fail` SLG)** · **PARTIAL (`P2-Partial`, `A2-Partial`, GBDT `A2-Fail`)** | [`results/transfer/phase3_ieee37.json`](results/transfer/phase3_ieee37.json), [`results/active_grid_ieee37/phase_active_ieee37.json`](results/active_grid_ieee37/phase_active_ieee37.json) |
| **Active DER + Loops + Conformal (123 → 34)** | Kaggle GPU + Local | Active 123 CV (`17,847`): GATv2 **95.8%** (FPR **6.5%**) vs GBDT **93.9%** (13.9%) & FPI **40.7%**. Active 34 0-shot (`9,491`): GBDT **83.8%** > GATv2 **77.6%** (20% few-shot GATv2 **89.1%** > GBDT **83.1%**), but both miss ≤ 5% 0-shot FPR (`22.1% / 25.3%`). Pre-registered `aps_det` is degenerate (`6.37` labels); post-hoc `aps_rand` 95% hits **95.0%** in-domain (`1.09` labels) but **fails** cross-feeder zero-shot (**81.4% / 91.1%**) | **PASS (`C1`)** · **PARTIAL (`C2`, `C3` post-hoc)** · **FAIL (0-shot conformal transfer)** | [`results/active_grid/phase_active_ieee34.json`](results/active_grid/phase_active_ieee34.json) |
| **Two-Tier Edge HIF-Sensor → Graph FLISR (Legacy Clean 60 Hz)** | Kaggle GPU | Paired ablation (`60Hz_only → +Edge`, 5 Emanuel surfaces, 7 disturbances): passive 123 SLG `400 Ω` **78.1% → 97.7%** (GBDT) / **79.6% → 96.0%** (GNN); active 123 `NO_FAULT` FPR **6.5% → 1.2%** (GATv2); active 34 0-shot FPR **22.1% → 5.8%** (GBDT) / **25.3% → 9.7%** (GATv2); `aps_rand` 95% singleton share **89.2% → 93.0%**. **Honest real-arc gap:** standalone Tier-1 drops **94.7% → 56.0%** on real 22 kV VeHIF vegetation recordings without retraining (cited from [`research/hif-fusion/PLAN.md`](research/hif-fusion/PLAN.md)) | **PASS (`H1–H4` 4/4, sim only)** · **Real-arc VeHIF gap & ≥ 15.36 kHz hardware limit disclosed** | [`results/hif_fusion/dataset_summary.json`](results/hif_fusion/dataset_summary.json) |
| **Branch-10 Realistic HIF-Fusion (Edge 15.36 kHz → Graph FLISR)** | Kaggle GPU (`1,950.8 s`) | Paired ablation directly on the harsh Branch-10 regime (genuinely `r_eff`-attenuated fault current + synchronized `arc_duty`, linear 60 Hz load drift, CT/PT bias + `0.5 A` floor): Passive 123 SLG `400 Ω` jumps **35.0% → 90.2%** (`ml_full`), **35.6% → 90.3%** (GBDT), **36.9% → 90.6%** (GNN), intermittent arcs **+41.2 to +44.3 pp**, all 5 surfaces **92.5%–95.6%**; Active 123 SLG `400 Ω` **41.5% → 75.6%** & FPR **10.8% → 2.8%** (GATv2, `motor_start` **15.1%** > 12% cap); Active 34 0-shot `1–10 kΩ` **27.3% → 54.7%** (GBDT) / **29.8% → 50.9%** (GATv2); `aps_rand` 95% singleton **82.3% → 90.8%**. **Honest fails:** Passive 34 0-shot regresses **98.4% → 97.4%** / **95.8% → 93.1%** (`R3a FAIL`) and pulls 1-sensor-offline below `-1.0 pp` (`R4 FAIL`, though all 7 other pairs gain **+3.9 to +7.4 pp**) | **`R1` PASS · `R2` PASS · `R3a` FAIL · `R3b` PARTIAL (`R3` FAIL) · `R4` FAIL** (sim only) | [`results/hif_fusion_realistic/summary.json`](results/hif_fusion_realistic/summary.json) |

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

**Fault location** — 11,448 simulated faults (all converged), every fault with its own 3-tier random load scenario (feeder, independent per-zone, and spot load) plus pre/post load drift, intermittent Emanuel arcing HIF modeling for `SLG ≥ 100 Ω`, systematic CT/PT channel bias, 1% / 0.5° random noise, and 0.5 A / 0.001 pu additive floor ([`research/realistic-hif-sim/PLAN.md`](research/realistic-hif-sim/PLAN.md)). Validation is grouped by fault bus, so the model is always tested on buses it never saw during training.

| Method | All faults | Line-to-ground, 100 Ω | Line-to-ground, 400 Ω |
|---|---|---|---|
| Conventional fault passage indication (2× peak-load pickup) | 52.5% | 4.5% | 1.6% |
| ML, instantaneous magnitudes only (basic SCADA poll) | 80.2% | 22.3% | 13.3% |
| **ML, magnitudes + pre/post-fault change (device event records)** | **91.5%** | **84.8%** | **31.3%** |

![Accuracy vs fault resistance](results/figures/accuracy_vs_resistance.png)

- **Missing sensor:** with any one of the 10 devices offline, the full model still identifies the zone in 78–88% of faults (mean 83.2%; worst case: Sw4 offline at 78.0%).
- **Where the model fails:** errors cluster in the trunk zones near the substation (Sw1, Sw2, Sw4, L13). Devices there carry hundreds of amps of load (631.5 A at the feeder head at nominal load), so systematic CT/PT bias, 1% random noise, 0.5 A floor, and 0.8% / 1.5% pre/post load drift swamp the attenuated 60 Hz current of an intermittent arcing 100–400 Ω fault (even a linear 400 Ω fault draws only 6.2 A at nominal load, [`results/transfer/signal_to_load.json`](results/transfer/signal_to_load.json), and arcing lifts median effective 60 Hz resistance to 841.6 Ω). See [`results/figures/confusion_ml.png`](results/figures/confusion_ml.png) and the [error analysis](#error-analysis) below.
- **Why the conventional method misses bolted ground faults (30% correct):** a solid phase-to-ground fault collapses that phase's voltage, and single-phase loads beyond the fault drop out. Devices downstream then see a large residual current and raise false ground flags, so the "deepest flagged device" rule points past the real fault. Real schemes add directional elements for this.
- **Patrol length:** after a feeder lockout, a crew without fault location patrols the whole feeder (39.0 kft of line). With conventional FPI it drops to 20.7 kft; with the ML zone, the average patrol drops to 7.3 kft (−81%). If the zone is wrong, the model is charged a full patrol.

### Error analysis

Accuracy alone hides which faults are missed and where the wrong answers point, so [`scripts/error_analysis.py`](scripts/error_analysis.py) replays the same grouped cross-validation and breaks down all 969 errors (8.5% of 11,448 faults). Output: [`results/error_analysis/`](results/error_analysis/).

Because the model always names one of 10 zones, false negatives and false positives are counted **per zone, one-vs-rest**: FNR = faults in zone X placed elsewhere, FPR = faults elsewhere placed in X.

| Zone | Faults | FNR | FPR | Precision |
|---|---|---|---|---|
| Sw1 (feeder head) | 1,125 | **14.6%** | **2.21%** | 80.8% |
| Sw2 | 1,494 | 13.5% | 1.59% | 89.1% |
| L13 | 1,557 | 8.4% | 1.73% | 89.3% |
| Sw4 | 1,971 | 7.1% | 2.40% | 89.0% |
| Sw3 | 981 | 9.6% | 0.54% | 94.1% |
| L45, L61, L68, Sw5, L77 (laterals) | 4,320 | ≤ 8.1% | ≤ 0.35% | ≥ 95.9% |

- **What is missed:** 967 of 969 errors are line-to-ground faults, and **844 (87%) are at 200 Ω or more** (965 / 99.6% fall in the `SLG ≥ 100 Ω` intermittent-arcing HIF regime). The SLG error rate is 0% up to 25 Ω, 0.3% at 50 Ω, 15.2% at 100 Ω, 37.5% at 200 Ω and 68.7% at 400 Ω. Only 2 three-phase faults (0.3%) and no LL or LLG faults were misplaced.
- **Why:** at nominal load a linear 400 Ω fault on a 2.4 kV phase draws 6.2 A (median over the feeder's buses, OpenDSS), 1.0% of the feeder-head current; adding intermittent Emanuel arcing raises median effective 60 Hz resistance to 204.9 / 407.8 / 841.6 Ω at nominal 100 / 200 / 400 Ω, pushing the fault signal into the pre/post load drift (0.8% zone / 1.5% spot) and CT/PT noise floor (1% + 0.5 A). Loading confirms it: the error rate is 6.2% in the lightest third of load scenarios and 10.6% in the heaviest third (8.6% in the middle third).
- **Where the wrong answers point:** 42% of errors are off by exactly one zone and 71% stay on the same path from the substation. The largest pairs are Sw2→Sw4 (72), Sw2→Sw1 (61) and Sw4→Sw1 (49). The model still leans **upstream** (40% of errors vs 31% downstream), while 21% land on an unrelated branch when natural pre/post load drift exceeds a faint arcing HIF current.
- **Checked and rejected:** faults close to a zone boundary are *not* clearly harder (error rate 7.9–8.9% at every distance from the nearest switch).
- **Deferring low-confidence answers:** wrong answers have a median class probability of 0.74 vs 1.00 for correct ones. Sending predictions below 0.95 to a manual patrol defers 10.3% of faults, raises accuracy on the rest to 98.4% and cuts errors from 969 to 165 (−83%).
- **For comparison, conventional FPI** raises no flag at all on 23.1% of faults (true missed detections) and over-flags Sw5 (FPR 15.0%, precision 34.3%).
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

**Two-tier Edge HIF-Sensor → Graph FLISR for 200–400 Ω and active HIFs (report section 2d, pre-registered plan [`research/hif-fusion/PLAN.md`](research/hif-fusion/PLAN.md)):** on the 4.16 kV IEEE 123-bus feeder, a nominal 400 Ω SLG fault draws a median 6.2 A (1.0% of the 631.5 A head current), sitting inside the 60 Hz CT noise floor and causing 87% of all main-study errors at ≥ 200 Ω (and 99.6% at ≥ 100 Ω; SLG 400 Ω accuracy drops to 31.3% at 60 Hz under intermittent arcing, load drift, and CT/PT noise). To address this physical ceiling without changing any published results in sections 2b–2c, the two-tier architecture couples a local **Tier-1 Edge ESP32-S3 HIF-Sensor** ([`shf/hif_edge.py`](shf/hif_edge.py): residual clamp CT `SCT-013-000` 2000:1 + 33 Ω burden, LTspice-verified 4th-order Butterworth Sallen-Key low-pass filter at `-3 dB = 2,045.1 Hz` / Python bilinear IIR `2,047.9 Hz`, 12-bit ADC at `15.36 kHz` / 256 samples per 60 Hz cycle, 16 harmonic/asymmetry/cycle-volatility features over an 8-cycle window, and a frozen quantized int8 Tiny MLP `16→16→8→1` with 417 parameters / 504 bytes and `PERSIST = 3` relay persistence) at every recloser/switch into **Tier-2 Graph FLISR** ([`shf/hif_fusion.py`](shf/hif_fusion.py), [`scripts/hif_fusion_run.py`](scripts/hif_fusion_run.py)):

- **Paired ablation (`60Hz_only` vs `60Hz_plus_edge`, Kaggle GPU run of [`notebooks/kaggle_hif_fusion.ipynb`](notebooks/kaggle_hif_fusion.ipynb) with frozen `model_int8.npz` from `christoopherchau/ch-y-n`, [`results/hif_fusion/`](results/hif_fusion/)):** appends `(p_hif, hif_alarm)` to each node's live-sensor block (`21 → 23` passive; `26 → 28` active plus 5th directed edge feature `diff_p_hif`) on identical OpenDSS events, folds, and seeds across 5 Emanuel arc surfaces and 7 background disturbances. All four pre-registered criteria **`H1–H4` PASS** (simulation only; no field data):
  - **Passive IEEE 123-bus (5-fold bus CV, 11,448 events):** `PerNodeGBDT` rises from 98.2% to **99.7%** overall (**87.5% → 98.0%** on SLG 200–400 Ω, **78.1% → 97.7%** at 400 Ω, 1-sensor-offline **89.0% → 90.3%**); `ZoneTreeGNN` rises from 98.0% to **99.5%** (**86.4% → 97.0%** on SLG 200–400 Ω, **79.6% → 96.0%** at 400 Ω, 1-sensor-offline **90.0% → 91.5%**). On unseen passive IEEE 34-bus zero-shot (4,104 events), both stay at ceiling (`99.8% → 99.8%` GBDT, SLG 200–400 Ω `98.5% → 98.7%`; `99.4% → 99.4%` GNN, SLG 200–400 Ω `95.9% → 97.6%`).
  - **Active IEEE 123-bus (0–50% DER, reconfigured/looped, 17,847 events):** `ActivePerNodeGBDT` rises `93.9% → 96.8%` overall (`80.2% → 90.3%` SLG 200–400 Ω, `72.5% → 86.8%` at 400 Ω, `NO_FAULT` FPR `13.9% → 3.3%`, 1-sensor-offline `86.1% → 88.7%`); `ActiveGridGATv2` rises `95.8% → 97.6%` overall (**82.2% → 90.8%** SLG 200–400 Ω, **73.5% → 87.5%** at 400 Ω, `NO_FAULT` FPR **`6.5% → 1.2%`** with every one of the 7 disturbances ≤ 6.7%, 1-sensor-offline `89.1% → 91.3%`).
  - **Active unseen IEEE 34-bus zero-shot (24.9 kV, 9,491 events):** `ActivePerNodeGBDT` rises `83.8% → 87.5%` overall (`71.8% → 77.8%` on 1–10 kΩ HIF SLG, `NO_FAULT` FPR `22.1% → 5.8%`, 1-sensor-offline `72.4% → 75.6%`); `ActiveGridGATv2` rises `77.6% → 83.3%` overall (`65.3% → 70.0%` on 1–10 kΩ, `NO_FAULT` FPR `25.3% → 9.7%`, 1-sensor-offline `71.5% → 74.5%`).
  - **Split Conformal (`aps_rand`, 95% target, `ActiveGridGATv2`):** IEEE 123-bus coverage stays at **95.0%** (`95.0%` at 60 Hz) while autonomous one-label sets jump from `89.2%` to **93.0%** (**98.9%** right, only **0.5%** autonomous `NO_FAULT` trip share). On unseen 34-bus, frozen 123-bus `q̂` rises `81.4% → 84.9%` (still carrying no cross-feeder guarantee) and 5%-bus recalibration averages `92.0%` (min `85.4%`). Deployment requires ≥ 15.36 kHz edge sensing behind a ~2 kHz anti-alias filter at each switch — legacy 60 Hz SCADA cannot supply `p_hif`, and simulated Emanuel arcs do not prove field performance.

- **Before / After on Branch-10 realistic intermittent arcing & CT/PT noise (Kaggle GPU run `christoopherchau/shf-hif-fusion-realistic-t66-gpu` v2, `quick_mode=false`, `2,001.6 s`; pre-registered plan [`research/hif-fusion-realistic/PLAN.md`](research/hif-fusion-realistic/PLAN.md), criteria `R1–R4`, isolated outputs [`results/hif_fusion_realistic/`](results/hif_fusion_realistic/) verified in [`results/provenance/hif_fusion_realistic.json`](results/provenance/hif_fusion_realistic.json) — legacy `results/hif_fusion/` table above kept untouched):** directly tests whether the frozen `504 B` `int8` (`15.36 kHz`) Edge HIF-Sensor rescues the harsh Branch-10 regime where pure 60 Hz FLISR collapses to **31.3%** at SLG `400 Ω` (`ml_full` overall **91.5%**, `fpi_baseline` **52.5%** overall / **1.6%** at `400 Ω` in [`results/metrics.json`](results/metrics.json)). Unlike the legacy clean-60 Hz study, Tier 1 here receives genuinely `r_eff`-attenuated fault residual current (`post_clean − post_drift_clean`, ~1–4 A at `400 Ω`) with restrike probability synchronized to `arc_duty` (`p_off = clip(1 − d_cond, 0, 0.65)`), while natural pre/post load drift stays strictly linear 60 Hz. Two physical modeling fixes (v2) enforce **Kirchhoff arc-path harmonic current division** (only closed switches on an actual substation-to-fault current path receive Emanuel arc injection; healthy non-path switches whose `0.06–0.65 A` shift comes from 60 Hz voltage-sag load response stay strictly linear) and an **IEEE C37.2 52a open-switch interlock** (open tie switches report `p_hif = 0.0, hif_alarm = 0.0` instead of scoring `1.5 LSB` ADC noise through the energized-current Tier-1 MLP):

  | Branch & Tier-2 model | SLG `400 Ω` · Clean 60 Hz (old 2d) | SLG `400 Ω` · Realistic 60 Hz (B10) | SLG `400 Ω` · Realistic + Edge (`504 B`) | SLG `200–400 Ω` (or `1–10 kΩ`) Real. 60 Hz → `+Edge` | Overall (Real. 60 Hz → `+Edge`) | `NO_FAULT` FPR (Real. 60 Hz → `+Edge`) | 1 sensor offline (Real. 60 Hz → `+Edge`) |
  |---|---|---|---|---|---|---|---|
  | Main study 60 Hz ref · `fpi_baseline` ([`results/metrics.json`](results/metrics.json)) | — | `1.6%` | — (60 Hz floor) | — | `52.5%` | — | — |
  | Main study 60 Hz ref · `ml_full` (150 feat, [`results/metrics.json`](results/metrics.json)) | — | **`31.3%`** | — (see paired row below) | — | `91.5%` | — | `83.2%` (`78–88%`) |
  | Passive 123 · `ml_full` (`150 → 170` feat, `11,448`) | — (not in old 2d) | `35.0%` | **`91.5%`** (`+56.5 pp`) | `48.0% → 94.0%` | `91.7% → 98.9%` | — | `83.4% → 90.3%` |
  | Passive 123 · `PerNodeGBDT` (`21 → 23`, `11,448`) | `78.1%` (old `+Edge`: `97.7%`) | `35.6%` | **`91.3%`** (`+55.7 pp`) | `48.7% → 94.0%` | `92.1% → 99.1%` | — | `83.1% → 89.6%` |
  | Passive 123 · `ZoneTreeGNN` (2L, `11,448`) | `79.6%` (old `+Edge`: `96.0%`) | `36.9%` | **`90.8%`** (`+54.0 pp`) | `50.3% → 93.3%` | `92.2% → 98.9%` | — | `84.5% → 90.6%` |
  | Passive 34 (0-shot) · `PerNodeGBDT` (`4,104`) | `97.4%` (old `+Edge`: `97.8%`) | `86.5%` | **`96.2%`** (`+9.7 pp`) | **`90.6% → 97.8%`** | **`98.4% → 99.6%`** | — | **`87.3% → 88.2%`** |
  | Passive 34 (0-shot) · `ZoneTreeGNN` (`4,104`) | `94.4%` (old `+Edge`: `97.4%`) | `74.5%` | `64.0%` (`−10.5 pp`) | `78.6% → 69.1%` | `95.8% → 93.8%` | — | `83.2% → 82.2%` |
  | Active 123 · `ActivePerNodeGBDT` (`17,862`) | `72.5%` (old `+Edge`: `86.8%`) | `36.3%` | **`69.2%`** (`+32.8 pp`) | `46.6% → 76.3%` | `87.6% → 93.6%` | `18.5% → 8.5%` | `79.9% → 85.0%` |
  | Active 123 · `ActiveGridGATv2` (`17,862`) | `73.5%` (old `+Edge`: `87.5%`) | `41.5%` | **`72.8%`** (`+31.3 pp`) | `52.7% → 79.3%` | `90.6% → 94.9%` | `10.8% → 5.1%` | `84.2% → 88.5%` |
  | Active 34 (0-shot) · `ActivePerNodeGBDT` (`9,487`; `1–10 kΩ`) | `71.8%` (old `+Edge`: `77.8%`) | `72.9%` | **`85.4%`** (`+12.5 pp`) | **`27.3% → 57.5%`** | `69.6% → 78.2%` | `29.7% → 22.6%` | `60.8% → 67.2%` |
  | Active 34 (0-shot) · `ActiveGridGATv2` (`9,487`; `1–10 kΩ`) | `65.3%` (old `+Edge`: `70.0%`) | `70.0%` | **`77.3%`** (`+7.3 pp`) | **`29.8% → 54.9%`** | `70.7% → 77.6%` | `17.3% → 17.4%` | `64.0% → 68.6%` |

  - **Split Conformal (`aps_rand`, 95% target, `ActiveGridGATv2`, [`results/hif_fusion_realistic/conformal_hif.json`](results/hif_fusion_realistic/conformal_hif.json)):** on realistic active IEEE 123-bus, cross-conformal coverage holds at **95.0%** (`95.0%` at 60 Hz) while autonomous one-label sets rise from **82.3%** to **89.7%** (`+7.4 pp`, avg set size `1.58 → 1.10`) with **98.3%** singleton accuracy and only **1.0%** autonomous `NO_FAULT` trip share (`ActivePerNodeGBDT`: coverage `95.0%`, singleton `70.3% → 79.6%`, accuracy `99.2%`, `NO_FAULT` auto-trip `0.3%`). On unseen active IEEE 34-bus, frozen 123-bus `q̂` (no exchangeability guarantee) covers `80.3%` (`60Hz_only`) / `81.4%` (`+Edge`), rising to `92.8%` mean (`82.7%` min) with 5%-bus recalibration and `94.0%` mean (`87.3%` min) with 20%-bus recalibration.
  - **Pre-registered criteria verdict (`R1–R4`, [`results/hif_fusion_realistic/summary.json`](results/hif_fusion_realistic/summary.json)):**
    - **`R1` (`PASS`):** on passive 123-bus, all three models jump `+54.0` to `+56.5 pp` at SLG `400 Ω` (`91.5% / 91.3% / 90.8%`) and `+43.0` to `+45.9 pp` at SLG `200–400 Ω`, with zero regression > `0.5 pp` on phase faults or low-R SLG (`0.01–50 Ω`).
    - **`R2` (`PASS`):** intermittent arcing (`arc_duty < 1.0`) jumps `+42.7` to `+46.3 pp` across all three models (`ml_full` `48.9% → 95.2%`, GBDT `51.4% → 95.9%`, GNN `52.4% → 95.1%`), and every Emanuel surface stays `93.5%–97.6%` (`≥ 75.0%` bar).
    - **`R3` (`PARTIAL` — `R3a: PASS`, `R3b: PARTIAL`):** enforcing Kirchhoff arc-path current division flips `R3a` to **`PASS`**: on unseen passive 34-bus zero-shot, `PerNodeGBDT` jumps `98.4% → 99.6%` overall (`+1.2 pp`), `90.6% → 97.8%` on SLG `200–400 Ω` (`+7.1 pp`), and `86.5% → 96.2%` at `400 Ω` (`+9.7 pp`); `ZoneTreeGNN` still dips zero-shot (`95.8% → 93.8%`) because its 4.16 kV message-passing weights over-rely on `(p_hif, hif_alarm)`, but 20% few-shot fine-tuning lifts it to `98.6%` vs `97.7%` 60 Hz (`93.2%` vs `88.2%` on `200–400 Ω`). `R3b` stays **`PARTIAL`**: active 123-bus SLG `400 Ω` jumps `+32.8 / +31.3 pp` with overall FPR cut `18.5% → 8.5%` / `10.8% → 5.1%`, active 34-bus 0-shot passes (`+30.3 / +25.1 pp` on `1–10 kΩ`), and Conformal `aps_rand` 95% passes (bounding autonomous `NO_FAULT` trip to `0.3%–1.0%`), but removing open-switch and downstream-arc simulator shortcuts surfaces the true overlap between large unmonitored `load_step`/`motor_start` surges and `1–3 A` intermittent HIF (`ActiveGridGATv2`: `motor_start 21.2%`, `load_step 20.6%`; `ActivePerNodeGBDT`: `load_step 27.8%`, `motor_start 24.0%`, `arc_welder 22.9%`, above the `12.0%` raw-argmax cap).
    - **`R4` (`FAIL` — `8/9` pairs PASS):** 8 of 9 model/feeder pairs pass with one sensor offline — including passive 123-bus (`+6.1` to `+6.9 pp` overall and `+39.0` to `+43.2 pp` on SLG `200–400 Ω`), passive 34-bus `PerNodeGBDT` (`87.3% → 88.2%`, `+0.9 pp`, SLG `200–400 Ω` `+9.5 pp`), and all four active 123/34 pairs (`+4.2` to `+6.4 pp`); only `passive_34_gnn` misses the strict `≥ −1.00 pp` cutoff by `0.02 pp` (`83.2% → 82.2%`, `−1.02 pp`).
  - **Honest simulation & limitation note:** Both the Emanuel two-diode arcing waveforms (5 surfaces, synchronized `arc_duty`) and the superimposed background loads (7 disturbances), zone load drift, and CT/PT errors remain **100% simulation** — not utility field oscillograms and not EMTP transients. As measured in [`hif_sensor/results/real_vehif.json`](hif_sensor/results/real_vehif.json), the same frozen `504 B` `int8` detector drops from **94.7%** (simulated Emanuel) to **56.0%** zero-shot on 250 real `22 kV, 50 Hz` VeHIF vegetation recordings (**0.0%** FA on 53 real background recordings), so simulated fusion gains do not prove field accuracy without real utility data.

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
| **Monitor card** | Right under the tour: what the Monitor is, how to use it in three steps (pick a role, open a fault, follow *How to handle*), plus its one-click **10s Two-Tier Demo** (`HIF Arc → ESP32 → FLISR`), **Live Wokwi MQTT** listener over WSS (`wss://broker.hivemq.com:8884/mqtt`), and reversed tie back-feed flow animation — with a note that it replays simulated faults and is not connected to real equipment. |
| **Explain guide** | Always on: click any card, chart or table (or its **?**) and a small guide flies there, circles it and says what it is, how to read it and why it matters. **← / →** walk through every part, **Esc** closes, and `?explain=heat` in a link opens the guide on one part. |
| **3D feeder model** | The whole feeder in 3D, built from the study's data: wooden poles with crossarms and insulators, one wire per phase, pole-top transformers, load columns sized by kW, recloser, switches (added ones carry a radio antenna), open ties with raised red blades, regulators, capacitor banks and the substation yard. Drag to rotate; click a zone or part and it lifts out while the guide explains it; **Tour the zones** walks through all 10; label layers (zones, equipment, bus numbers) and a **2D map** view. three.js loads only when the section comes on screen. |
| **Model errors** layer | Shows *where* the model goes wrong: a red column on every bus where faults get misplaced (taller = more, redder = higher rate), a green dot where none are, and arrows from each true zone to the zone it is mistaken for (Sw2 → Sw4: 72 faults…). Click a column or arrow for the numbers, including how conventional fault indicators do on the same bus. |
| **Fault replay** layer | Click anywhere on the feeder (or pick "a missed fault" or the quick **10s HIF → FLISR** demo button) and the model replays it in 6 steps: the fault flashes, Sw1 locks out and the feeder goes dark, the model names a zone (an orange arrow if it is wrong, with why), switches open to isolate, Sw1 re-closes, and ties close to restore what the power flow allows, with 3D directional power-flow pulses reversing from closed ties (`Sw7`/`Sw9`) into back-fed zones. Every switch has a lamp: green closed, red open. |
| **Data & method** | Download the full simulated dataset (11,448 faults × 162 columns, plus a 300-row sample) and every result file from [`docs/data/`](docs/data/), with a column dictionary, the formulas behind each number, and the nine-step reasoning from the question to the result. |
| **EN / VI** button | Switches every text, chart label and tooltip between English and Vietnamese. Add `?lang=vi` or `?lang=en` to a link to share it in one language. |
| **Run checks** | Pass / Watch / Fail summary of the run, so you know whether to trust the numbers before reading on. |
| **In short** boxes | One plain-language sentence at the top of each section. |
| Dotted-underlined words | Hover or tap for a one-line definition (FLISR, FNR, pu, radial…); all of them are also listed in the **Glossary**. |
| Hover / tap on charts | Exact numbers for every point, bar and matrix cell; “Show as table” gives the same data as a table. |
| **Questions & answers** | 18 questions a reviewer or interviewer is likely to ask, answered with this run's numbers. Search (Vietnamese with or without accents), filter by topic, open all, or copy a link to one question. |
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
| Fault sweep | `shf/faults.py` | SLG/LL/LLG/3-phase faults at every bus, 0.01–400 Ω, intermittent Emanuel arcing HIF model for SLG ≥ 100 Ω, 3-tier feeder/zone/spot load + pre/post load drift, systematic CT/PT bias + 1% / 0.5° noise + 0.5 A / 0.001 pu floor; regulator taps frozen during the fault |
| Baseline | `shf/baseline.py` | Conventional fault passage indication: phase pickup 2× peak load, ground pickup on residual current; zone = deepest flagged device |
| ML | `shf/model.py` | Gradient-boosted trees, GroupKFold by fault bus (always tested on unseen buses), sensor-dropout training, missing-sensor test |
| Restoration | `shf/restoration.py` | Isolate the zone, re-close upstream, then greedily close the tie that restores the most kW subject to ANSI C84.1 Range A (0.95–1.05 pu), emergency ampacity and radiality |
| Hourly restoration | `shf/hourly.py`, `scripts/load_shape.py`, `scripts/hourly_restoration.py` | Re-runs restoration for every fault zone at every feeder load level, labels why each rejected check failed (undervoltage, overvoltage, overload, no convergence), then maps each hour of one year of PJM AEP load onto those levels; shown in report section 4b |
| Cross-feeder transfer & bus ranking | `shf/transfer.py`, `shf/transfer_models.py`, `shf/bus_locator.py`, `scripts/transfer_train.py`, `scripts/transfer_eval34.py`, `scripts/transfer_eval37.py`, `scripts/transfer_bus_stage.py`, `scripts/signal_to_load.py` | Feeder-agnostic 21-feature zone-node graph representation, per-node GBDT and 2-layer `ZoneTreeGNN` trained on IEEE 123-bus and transferred zero-shot/few-shot to unseen IEEE 34-bus and urban underground delta IEEE 37-bus, plus Stage-2 3-phase Takagi reactance vs `BusGraphGNN` bus ranking inside the predicted zone |
| Active DER grids & Conformal sets | `shf/active_grid.py`, `shf/active_models.py`, `scripts/active_grid_run.py`, `scripts/active_conformal_posthoc.py`, `notebooks/kaggle_active_grid.ipynb`, `notebooks/kaggle_active_ieee37.ipynb` | 0–50% current-limited inverter DER (`Model=7`), reconfigured/closed-loop topologies, SLG faults up to 10,000 Ω on 24.9 kV, non-fault operational transients (`NO_FAULT`), bidirectional edge-aware `ActiveGridGATv2`, and Split Conformal Prediction (90%/95% Adaptive Prediction Sets) |
| Two-tier Edge HIF-Sensor → Graph FLISR | `shf/hif_edge.py`, `shf/hif_fusion.py`, `scripts/hif_fusion_run.py`, `scripts/hif_fusion_realistic_run.py`, `notebooks/kaggle_hif_fusion.ipynb`, `notebooks/kaggle_hif_fusion_realistic.ipynb` | Couples a simulated Tier-1 Edge HIF-Sensor (4th-order Butterworth LPF at 2,045.1 Hz, 12-bit 15.36 kHz ADC, 16 features, frozen 417-param / 504 B int8 Tiny MLP) into Tier-2 `PerNodeGBDT` / `ZoneTreeGNN` / `ActiveGridGATv2` + `aps_rand` 95% across 5 Emanuel arc surfaces and 7 background disturbances — both legacy clean-60 Hz (`results/hif_fusion/`, completed on Kaggle GPU) and Branch-10 realistic arcing/noise (`results/hif_fusion_realistic/`, completed on Kaggle GPU; `R1–R2 PASS`, `R3a/R4 FAIL`, `R3b PARTIAL`) |
| SCADA replay | `shf/scada.py`, `scripts/demo_event.py`, `scada/` | Replays one fault as device messages over MQTT into TimescaleDB (or to a JSON-lines file) |
| COMTRADE ingest | `shf/comtrade.py`, `scripts/comtrade_ingest.py`, [`data/comtrade_samples/`](data/comtrade_samples/README.md) | Reads IEEE C37.111-1999/2013 relay/recloser records (`.cfg`/`.dat`/`.cff`), extracts pre/post DFT phasors into Tier-2 (`15/device`), Transfer (`21`), Active-Grid (`26`), and optional Tier-1 HIF (`16`) features, and verifies 5 public + 6 simulation round-trip samples → [`results/comtrade/summary.json`](results/comtrade/summary.json) |
| Control panel | `shf/panel.py`, `scripts/panel_bridge.py`, [`board/`](board/README.md), [live in Wokwi](https://wokwi.com/projects/481240462876979201) | A simulated ESP32 panel in Wokwi embedding the verified C99 Tier-1 HIF chain (`hif_dsp.c` + `hif_infer.c` + `504 B` `int8` `hif_model.h` in a `24 KB` FreeRTOS task): one lamp per switch, a lockout lamp, a yellow `HIF ALARM` LED (`GPIO 5`), an LCD, `FAULT` / `CLOSE TIES` / `RESET` / `HIF ARC` (`GPIO 14`) buttons, a fault-resistance knob and two failure switches; publishes Tier-1 alerts to `shf/shf123-demo/hif` and syncs live with `panel_bridge.py` and the browser [Monitor](docs/monitor/README.md) over MQTT (`broker.hivemq.com`) |

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
.venv\Scripts\python scripts/hif_fusion_realistic_run.py --model-npz hif_sensor/results/model_int8.npz --workers 16  # Branch-10 realistic HIF-Fusion (or notebooks/kaggle_hif_fusion_realistic.ipynb)
.venv\Scripts\python scripts/signal_to_load.py             # ~1 s, fault current vs feeder-head current -> results/transfer/
.venv\Scripts\python scripts/demo_event.py --bus 60 --type SLG --r 50
.venv\Scripts\python scripts/comtrade_ingest.py --verify-samples  # verify 5 public + 6 sim COMTRADE records -> results/comtrade/summary.json
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

Numbers in the prose are read from `results/` and listed in `harness/facts.toml`; the only typed numbers are assumptions from `shf/config.py` and IEEE test-case data. Every file in `results/` carries a run record in `results/provenance/` (24 manifests covering 58 result files: command, UTC time, git commit and a 64-character SHA-256 of each file; [`shf/provenance.py`](shf/provenance.py)). The health check fails if any result file no longer matches the run that wrote it.

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
- **Realistic fault & arcing HIF model (still 100% OpenDSS steady-state 60 Hz phasor simulation; [`research/realistic-hif-sim/PLAN.md`](research/realistic-hif-sim/PLAN.md)):** low/medium-impedance and phase faults (`3PH/LL/LLG`, `SLG < 100 Ω`) use linear resistances in steady-state phasor power flow. For `SLG ≥ 100 Ω` (`HIF_ARC_MIN_R = 100.0`), an equivalent 60 Hz arcing resistance `R_eff` combines (i) the Emanuel 2-diode describing-function fundamental factor (`Vp/Vpk ~ U(0.15, 0.45)`, negative/positive asymmetry `U(1.00, 1.20)`, `Vn/Vpk ≤ 0.55`), (ii) intermittent conduction duty `d_cond ~ U(0.35, 0.85)` with probability `0.45` (`1.0` otherwise), and (iii) log-normal contact-path jitter (`σ = 0.25`, clipped `[0.60, 1.80]`), capped at `R_eff ≤ 2,500 Ω` (median `R_eff`: `204.9 / 407.8 / 841.6 Ω` at nominal `100 / 200 / 400 Ω`). This captures 60 Hz attenuation and intermittency dispersion, but **does not** model EMTP electromagnetic transients, traveling waves, CT core saturation under DC-offset faults, or real-time harmonics (high-frequency arc harmonics are studied separately in Tier 1 `hif_sensor/` and section 2d HIF-fusion), and a real-vs-simulated arc domain gap still exists (as shown on real 22 kV VeHIF recordings in `hif_sensor/`). The source is very stiff (as in the IEEE test case), so bolted-fault currents are high.
- **Per-zone loading and pre/post load drift:** each simulated fault draws a 3-tier load profile — feeder-wide `U(0.3, 1.1)`, independent per-zone `N(1, 0.30)` clipped `[0.45, 1.65]` (`ZONE_LOAD_SPREAD`), and per-spot `N(1, 0.20)` clipped `[0.30, 1.70]` (combined `[0.25, 2.00]`) — plus natural pre-to-post load drift (`0.8%` correlated per-zone `LOAD_DRIFT_ZONE` and `1.5%` per-spot `LOAD_DRIFT_SPOT`, clipped `[0.90, 1.10]`) while regulator taps stay frozen post-fault. The main 123-bus dataset contains faulted events only (`NO_FAULT` switching transients are evaluated separately in Active-Grid and HIF-Fusion).
- **The model is trained and tested on simulation only.** A real deployment would need field event records for validation.
- **Timing for kW-minutes** (automated 1 min, manual 90 min, repair 240 min) is an assumption that drives the size of that metric.
- **Measurement noise and CT/PT bias:** every device channel gets a systematic per-event CT/PT bias held constant from pre-fault to post-fault and re-sampled across events (IEEE C57.13 Class 1.2-inspired: CT `1.5%` mag / `0.8°` angle, clipped `±4.5% / ±2.5°`; PT `0.8%` mag / `0.4°` angle, clipped `±2.5% / ±1.5°`), independent per-snapshot random noise (`1%` magnitude, `0.5°` angle), and an additive low-signal complex floor (`0.5 A RMS`, `0.001 pu`) applied to energized phases only. Real instrument error depends on the specific CT/PT/IED hardware and saturation behavior, which are not modeled further.
- **Conventional FPI baseline:** phase pickup is 2× the device's peak-load current, ground pickup 0.5× that current but at least 1.2× the natural residual current (common rules of thumb, not a utility's settings). It has no directional element; real schemes add directional or timing logic that would reduce some of its false ground flags.
- **SolidWorks equipment** ([`mech/`](mech/README.md)): generic recloser, automated switch, regulator, capacitor bank, pole-top transformer and substation transformer with illustrative sizes (the `*_MM` tables in `config.py`), drawn for the 3D view, each with a dimensioned A3 technical drawing ([`mech/`](mech/README.md#technical-drawings)). None is a manufacturer's design and no calculation uses them.
- **LTspice circuits** ([`spice/`](spice/README.md)): a per-phase Thevenin equivalent at one bus, so mutual coupling and unbalance are left out; an ideal 1000:1 CT (no saturation); a 12-bit, 3.3 V ADC sampling 32 times per cycle; a one-cycle DFT as the phasor estimator. The arcing high-impedance fault uses the two-diode arc model (Emanuel et al., 1990) with arc voltages of 30% (positive half cycle) and 33% (negative half cycle) of the phase peak voltage; those two numbers are illustrative assumptions, not measurements, and the arc resistance is set so the arc has the same RMS current as the fixed 100 Ω or 400 Ω fault it is compared with. They show waveform effects next to the study, not a protection design.
- **Hourly restoration study:** every spot load follows one regional hourly shape (PJM AEP region, which is smoother than a single feeder); the IEEE nominal loads are taken as the annual peak; capacitors stay fixed as in the IEEE case; the adjacent feeder behind Sw9 still has no load of its own. A tie must stay within limits for the whole outage window (manual + repair time), not only at the fault hour.
- **Wokwi control panel & Monitor live MQTT** ([`board/`](board/README.md), [`docs/monitor/`](docs/monitor/README.md)): the ESP32 is a browser Wokwi simulation (running the byte-identical C99 `hif_dsp.c` + `hif_infer.c` + `504 B` `int8` `hif_model.h` chain on deterministic synthetic 12-bit waveforms from `hif_arc_samples.h`), **not** energized physical hardware in the field. The free simulator reaches only the internet, so the panel, `panel_bridge.py` (TCP `1883`), and the optional Monitor WSS listener (`wss://broker.hivemq.com:8884/mqtt`) meet on a public test broker (`broker.hivemq.com`) using `shf/shf123-demo/{state,cmd,hif}`; all messages are simulated states/alerts, and the bridge accepts only strictly validated commands and HIF payloads (`parse_command`, `parse_hif_alert`). When the model picks the wrong zone, the panel says so and stops, because the study does not model what a real scheme would do next. Its stuck-switch test uses a simple back-up rule (the zone behind the stuck switch is isolated too), with no timers.
- **MQTT/TimescaleDB path:** MQTT has run end to end with the Wokwi panel (public broker). The TimescaleDB part has not been run on the development machine (no Docker). The JSON-lines replay is tested.
- **Cross-feeder transfer & bus ranking (`results/transfer/`):** the IEEE 34-bus test feeder has no sectionalizing switches in the IEEE PES distribution, so 7 switches (`Sw1_34` at source plus 6 trunk/lateral switches placed at branches carrying ≥ 5% of feeder kW, marked `ASSUMPTION` in `shf/transfer.py`) are pre-registered in [`research/gnn-transfer/PLAN.md`](research/gnn-transfer/PLAN.md). Stage-2 bus ranking uses OpenDSS 3×3 line impedance matrices and assumes only the zone-head device records the event.
- **Urban underground 3-wire delta IEEE 37-bus (`results/transfer/*ieee37*`, [`research/ieee37-underground/PLAN.md`](research/ieee37-underground/PLAN.md)):** unmodified 4.8 kV 3-wire ungrounded delta underground cable feeder (`data/feeder/ieee37/`, IEEE underground line codes `721`–`724`, delta-delta substation transformer, open-delta head regulator, unbalanced delta spot loads, no shunt capacitor banks). **ASSUMPTION:** no artificial earthing/zig-zag transformer is added, so SLG faults return purely through healthy-phase cable charging capacitance (`2.36 A` / `0.64%` at `0.01 Ω` and `2.23 A` / `0.60%` at `400 Ω` vs `369.5 A` head current) and shift unfaulted phase-to-ground voltages toward `√3` pu. Applying the frozen 5%-load `PLACEMENT_RULE` yields 10 switching zones (`D1`–`D10`) across 36 3-phase buses (`2,457 kW` nominal load). For the active-grid IEEE 37-bus stage (completed on Kaggle GPU; results in [`results/active_grid_ieee37/`](results/active_grid_ieee37/)), 3 delta-connected `Generator Model=7` DERs are placed at `738`, `708`, and `720` (0–50% penetration), an adjacent 230/4.8 kV delta-delta tie `Tie37` connects to bus `741` (`D9`) for `reconfig_tie` (`D6` open) and `looped_tie`, SLG resistances span `0.01–400 Ω`, and `NO_FAULT` events split 50/50 between `pv_cloud` and `load_step` (`cap_switch = 0` because the feeder has no capacitor banks). Pure steady-state OpenDSS phasor simulation; no EMT cable transients, no CT saturation, and no field data.
- **Active DER grids & Split Conformal Prediction (`results/active_grid/`):** inverter-interfaced DERs are modeled in OpenDSS as `Generator Model=7` (current-limited to ~1.1–1.2 pu at unity power factor) across 0%, 25%, and 50% penetration at pre-registered candidate buses (`ACTIVE_DER_BUSES_123` and `ACTIVE_DER_BUSES_34`, marked `ASSUMPTION` in `shf/active_grid.py`). Topologies include radial normal, tie-reconfigured back-feed, and weakly meshed closed-loop states (`Sw7` closed on 123-bus; an assumed 10 kft tie `828–832` on 34-bus). The 24.9 kV 34-bus active sweep extends SLG fault resistance up to 10,000 Ω to move toward the 4.16 kV signal-to-load ratio, but does not reach it: at nominal load a 10,000 Ω fault on 34-bus draws a median 2.9% of the feeder-head current, against 1.0% for 400 Ω on 123-bus (`results/transfer/signal_to_load.json`). Non-fault operational transients (`NO_FAULT`) are steady-state phasor snapshots of capacitor bank switching, 70–90% PV cloud drops, and +30–80% load steps, not EMT sub-cycle waveforms.
- **Two-tier Edge HIF-Sensor → Graph FLISR (`research/hif-fusion/PLAN.md`, `research/hif-fusion-realistic/PLAN.md`, `shf/hif_edge.py`, `shf/hif_fusion.py`, report section 2d):** both tiers are **simulation only** (no utility field recordings). Emanuel two-diode arc waveforms across 5 surfaces (`wet_grass`, `wet_sand`, `concrete`, `dry_grass`, `dry_asphalt`) and 7 background load/switching disturbances (`none`, `load_step`, `cap_switch`, `inrush`, `motor_start`, `arc_welder`, `nonlinear_fluct`) are synthesized via quasi-steady harmonic superposition scaled by OpenDSS per-switch incremental residual current (`dI_res`), omitting EMTP electromagnetic transients, frequency-dependent line/cable impedance, CT core saturation, and ESP32 ADC nonlinearity. Locked coupling assumptions (`ASSUMPTION` in `shf/hif_fusion.py`): arcing applies when SLG has `R ≥ 100 Ω` and `I_fault ≤ 45 A` RMS; local pre-fault residual unbalance is clipped to `[1.0, 20.0] A` RMS (calibration range of the SCT-013-000 + 33 Ω front end); healthy switches experience concurrent background disturbances with probability `0.25`. In Branch-10 realistic mode (`realistic=True`, [`research/hif-fusion-realistic/PLAN.md`](research/hif-fusion-realistic/PLAN.md)), OpenDSS separates `post_drift_clean` from `post_clean` so Tier 1 receives only genuinely `r_eff`-attenuated fault residual current (`|I_res(post) − I_res(post_drift)|`) with intermittent restrike probability synchronized to `p_off = clip(1 − arc_duty, 0, 0.65)`, while natural pre/post load drift (`|I_res(post_drift) − I_res(pre)|`) is injected strictly as linear 60 Hz; on 24.9 kV active 34-bus, the `r_eff` ceiling scales proportionally (`max(2,500 Ω, 6.25 × r_nom)`); and single-sensor outage tests simultaneously blank both 60 Hz and `(p_hif, hif_alarm)` channels. **Hardware requirement:** practical operation cannot use legacy 60 Hz SCADA/RTU polling — it requires edge IEDs or ESP32-S3-class sensor nodes sampling residual current at **≥ 15.36 kHz** (60 Hz) or **≥ 12.8 kHz** (50 Hz VN/AU, optionally scaling the Sallen-Key resistors `R×1.2` to `10.5 kΩ` / `5.36 kΩ` for `−46.70 dB` Nyquist attenuation on the same PCB) behind an analog anti-aliasing filter (`fc ≈ 2 kHz`) at every monitored recloser/switch. **Real-vs-simulated arc gap:** in the companion `hif-sensor` project, evaluating the frozen Phase-0 int8 model on real 22 kV vegetation-fault recordings dropped from `94.7%` simulated to `56.0%` zero-shot (`120 s` window), and Phase 1.5 20% few-shot `joint_mlp_int8` improved `0–2 A` detection by `+7.41 pp` (`42.52% → 49.93%`, `53.30% → 60.22%` overall), passing `P1.5-B/C/D` but falling short of the pre-registered `>= +15 pp` bar (`P1.5-A: false`) — confirming that simulated fusion gains do not substitute for field oscillogram validation or physical PCB bench testing.
- **COMTRADE ingest (`shf/comtrade.py`, `scripts/comtrade_ingest.py`, [`results/comtrade/summary.json`](results/comtrade/summary.json)):** verified on **5/5** public open-source IEEE C37.111 recordings (MIT / CC0-1.0 from external grids) and **6/6** simulation round-trip records (OpenDSS, LTspice, Emanuel HIF) — no utility field fault dataset on IEEE 123-bus has been evaluated. Single-device recordings populate only `15/150` Tier-2 features (`135 NaN`) and cannot localize across a whole feeder; real use requires multi-device event folders from the target grid and field validation with confirmed fault locations.

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
