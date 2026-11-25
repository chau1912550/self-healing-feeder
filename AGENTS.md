# Agent guide: self-healing-feeder

Read this before changing anything. It says what the project is, where every piece of content
comes from, the rules that keep the content correct, and how to check your work.

## What the project is (and is not)

A student-scale **FLISR** study (Fault Location, Isolation and Service Restoration) on the
**IEEE 123-bus test feeder** (4.16 kV) in **OpenDSS**, by Chau Nguyen (EE student).

1. **Fault location:** given the currents and voltages that 10 reclosers/switches record, which of
   10 switching zones holds the fault? Gradient-boosted trees vs. a conventional fault-passage-indicator
   (FPI) baseline, validated with GroupKFold by fault bus (always tested on unseen buses).
2. **Restoration:** isolate the zone, re-close upstream, then close tie switches only when a power flow
   keeps voltage within ANSI C84.1 Range A (0.95–1.05 pu), lines within 125% emergency rating, and the
   feeder radial.

It is **simulation only** for the OpenDSS/LTspice feeder models and Wokwi panel, and **offline recording evaluation** for the bundled **Tier-1 Edge HIF Sensor** (`hif_sensor/`, which passes real 22 kV, 50 Hz VeHIF vegetation-fault & 53 background recordings through a simulated CT/LPF/ADC front end and simulated feeder load). No energized physical hardware test, no deployment at a utility, no real SCADA connection (MQTT has run end to end only with the simulated Wokwi panel; the TimescaleDB path has not been run). Every text must keep that clear.

The GitHub Pages site (`docs/`) is a unified **3-tab** hub built by `python -m shf.dashboard` (which also invokes `hif_sensor/scripts/build_dashboard.py`):
- `docs/index.html` — **Tier 2 · Feeder FLISR** (IEEE 123/34/37 + GNN + Restoration)
- `docs/hif-sensor/index.html` — **Tier 1 · Edge HIF Sensor (ESP32)** (LTspice CT/LPF, 50/60 Hz, VeHIF 22 kV, Phase 0/1/1.5, GCC C parity)
- `docs/monitor/` — **Interactive Monitor** (40 replay incidents)

## Map

| Path | What it is | Edit by hand? |
|---|---|---|
| `shf/config.py` | Every assumption (added switches, ampacities, noise, pickups, timing), each marked `ASSUMPTION` | Yes, then re-run |
| `shf/feeder.py`, `topology.py`, `faults.py`, `baseline.py`, `model.py`, `restoration.py` | The study, one step each (see README "How it works") | Yes, then re-run |
| `run.py` | Runs the whole study, writes `results/`, rebuilds the report | Yes |
| `scripts/error_analysis.py` | Per-zone FNR/FPR, confusion pairs, confidence threshold → `results/error_analysis/` | Yes |
| `scripts/export_control_room.py` | 40 replay incidents for the Monitor → `docs/monitor/data.json` | Yes |
| `shf/hourly.py`, `scripts/load_shape.py`, `scripts/hourly_restoration.py` | Hourly restoration study: restoration at every load level, mapped onto a year of PJM AEP load → `results/hourly/` (report section 4b) | Yes, then re-run |
| `notebooks/kaggle_hourly.ipynb` | Runs the hourly study on Kaggle with the PJM dataset attached; the raw CSV stays out of git (`data/external/`) | Yes |
| `shf/transfer.py`, `shf/transfer_models.py`, `shf/bus_locator.py`, `scripts/transfer_train.py`, `scripts/transfer_eval34.py`, `scripts/transfer_bus_stage.py`, `scripts/signal_to_load.py` | Cross-feeder transfer study (`research/gnn-transfer/PLAN.md`): feeder-agnostic 21-feature zone-node graphs, per-node GBDT vs 2-layer `ZoneTreeGNN` trained on IEEE 123-bus and transferred zero-shot/few-shot to unseen IEEE 34-bus, plus Stage-2 3-phase Takagi reactance vs `BusGraphGNN` bus ranking → `results/transfer/` (report section 2c) | Yes, then re-run |
| `shf/active_grid.py`, `shf/active_models.py`, `scripts/active_grid_run.py`, `scripts/active_conformal_posthoc.py`, `notebooks/kaggle_active_grid.ipynb` | Active-grid GNN + Split Conformal Prediction study (`research/active-grid-gnn/PLAN.md`): 0–50% current-limited inverter DER (`Model=7`), reconfigured/closed-loop operation, SLG up to 10,000 Ω on 24.9 kV, non-fault transients (`NO_FAULT`), bidirectional edge-aware `ActiveGridGATv2`, and 90%/95% Adaptive Prediction Sets → `results/active_grid/` (report section 2c) | Yes, then re-run |
| `shf/hif_edge.py`, `shf/hif_fusion.py`, `scripts/hif_fusion_run.py`, `notebooks/kaggle_hif_fusion.ipynb` | Two-tier Edge HIF-Sensor → Graph FLISR coupling (`research/hif-fusion/PLAN.md`): feeds `(p_hif, hif_alarm)` from the frozen 504 B `int8` Tier-1 MLP into Tier-2 `PerNodeGBDT` / `ZoneTreeGNN` / `ActiveGridGATv2` + `aps_rand` → `results/hif_fusion/` (report section 2d) | Yes, then re-run |
| `hif_sensor/` (`hif/`, `circuit/`, `firmware/`, `phase15_vehif_adaptation.py`, `PLAN_PHASE15.md`, `scripts/build_dashboard.py`, `results/`, `tests/test_hif.py`) | Bundled Tier-1 Edge HIF Sensor subproject (LTspice 50/60 Hz + `R×1.2` BOM, 417-param / 504 B `int8` Tiny MLP, Phase 0 sim, Phase 1/1.5 real 22 kV VeHIF adaptation & feature ablation, GCC `13.3.0` C firmware parity, 23-file SHA-256 manifest in `hif_sensor/results/provenance/manifest.json`) | Yes, then verify |
| `shf/cad.py`, `scripts/export_oneline_dxf.py`, `scripts/autocad_export.py` | One-line diagram DXF for AutoCAD, drawn from `results/` → `cad/feeder_oneline.dxf` (the health check fails if it is older than the results) | Code yes; the DXF is generated |
| `shf/spice.py`, `scripts/spice_run.py` | LTspice circuits written from the OpenDSS model (fault DC offset, CT/ADC front end, arcing high-impedance fault), run in batch, waveforms → `exports/spice_*.csv`, numbers → `results/spice/summary.json` | Code yes; the `.asc` files are generated |
| `shf/panel.py`, `scripts/panel_bridge.py`, `scripts/wokwi_diagram.py`, `board/` | ESP32 control panel simulated in Wokwi (lamps per switch, lockout lamp, LCD, buttons, knob, sensor-offline and switch-stuck failure switches; `restoration.plan_restoration(stuck=None)` keeps the study's plan unchanged); the study drives it over MQTT on a public test broker; `board/wokwi/diagram.json` is generated, `sketch.ino` is hand-written | Code yes; the diagram is generated |
| `shf/mechdraw.py`, `scripts/export_drawings.py` | Dimensioned A3 drawings of the six SolidWorks parts (three views, spec table, title block) drawn from the same solids → `cad/drawing_<part>.dxf`, AutoCAD → `.dwg`, `exports/drawing_<part>.pdf/.png`; fresh PDFs are copied to `docs/drawings/` and linked from the 3D view | Code yes; the drawings are generated |
| `shf/mech.py`, `scripts/solidworks_build.py` | Six generic equipment parts (recloser, auto switch, regulator, capacitor bank, pole-top transformer, substation transformer) built in SolidWorks over COM from the `*_MM` tables in `config.py` → `mech/<part>.sldprt`, `exports/<part>.glb/.step/.png`; fresh `.glb` files are copied to `docs/models/` for the 3D view | Code yes; the parts are generated |
| `workflow.toml`, `cad/`, `mech/`, `spice/`, `hmi/`, `exports/` | Files made in AutoCAD, SolidWorks, LTspice and Factory IO, and their exports; `scripts/register_export.py` records a fresh export | Sources yes; `exports/registered.json` only through the script |
| `results/` | **Source of truth for every number.** `metrics.json` first | **No**, generated |
| `shf/dashboard.py` | Builds `docs/index.html` (layout, charts, checks, numbers) | Yes |
| `shf/dashboard_text.py` | All report prose: Q&A (`FAQ`), `GLOSSARY`, guide texts (`EXPLAIN`, `MODEL`), EN + VI | Yes |
| `docs/index.html` | The Tier-2 Feeder FLISR report page on GitHub Pages | **No**, built by `python -m shf.dashboard` |
| `docs/hif-sensor/` | Published Tier-1 Edge HIF Sensor tab (`index.html`, `figures/`, `data/`), built automatically by `python -m shf.dashboard` calling `hif_sensor/scripts/build_dashboard.py` | **No**, generated |
| `docs/data/` | Published copies of result files | **No**, copied by the dashboard build |
| `docs/monitor/` | Role-based outage demo (dispatcher, crew, engineer, manager); `index.html` is hand-written, `data.json` generated | `index.html` yes |
| `README.md`, `docs/vi/*.md`, `hif_sensor/{README.md, HUONG_DAN.md}` | Prose with numbers in it (`README.md` & `docs/**/*.md` checked by `harness/facts.toml`; `hif_sensor/README.md` & `HUONG_DAN.md` kept aligned with `hif_sensor/results/` and synced with the sibling `hif-sensor/` repo) | Yes |
| `harness/` | `check.py` (health check), `facts.toml` (every stated number and its source) | Yes |
| `config/apis.md` | Registry of outside APIs (none used today); keys live in `.env` | Yes |
| `inputs/` | New source documents the owner adds; `inputs/INDEX.md` tracks them | Index yes |

Data flow: `config.py` → `run.py` (feeder → zones → fault sweep → FPI + ML → restoration) →
`results/` → `scripts/error_analysis.py` → `results/error_analysis/` → `scripts/export_control_room.py`
→ `docs/monitor/data.json` → `python -m shf.dashboard` → `docs/index.html` + `docs/data/`.
Hourly study: `data/external/pjm/AEP_hourly.csv` (or the Kaggle input) → `scripts/load_shape.py` →
`scripts/hourly_restoration.py` → `results/hourly/` → `python -m shf.dashboard`.

## Content rules

1. **Every number comes from `results/`.** Never type a number you did not read from a result file
   or compute from one. When you add a number to prose, add it to `harness/facts.toml` too.
2. **Re-run, then rewrite.** After a code or assumption change, run the pipeline before touching prose.
   Change the text to match the results; never tune code to match the text.
3. **Say what is simulated and what is assumed.** New assumptions go in `config.py` with `ASSUMPTION`
   and in README "Assumptions and limitations".
4. **No claim beyond the evidence.** Never claim utility deployment, field validation, or live SCADA integration.
   Results on unseen buses are not results on a real feeder. The list of banned phrases is in `harness/facts.toml`.
5. **English and Vietnamese stay in step.** Every `T(en, vi)` / `TB(en, vi)` / FAQ entry has both. When
   README changes in a way a reader of `docs/vi/` would notice, update `docs/vi/module-guide.md` too. Keep
   `hif_sensor/README.md` and `hif_sensor/HUONG_DAN.md` in step with `hif_sensor/results/` (and synced with
   the sibling `hif-sensor/` repo).
6. **Sources.** A fact from an outside document (paper, standard, utility report) gets a reference in
   README "References" with a link. Don't quote long passages.
7. **Page layout.** The unified 3-tab hub (`Tier 2 · Feeder FLISR`, `Tier 1 · Edge HIF Sensor (ESP32)`,
   `Interactive Monitor`) shares `system-ui`, `#f9f9f7` warm-paper CSS, EN/VI (`shf-lang`), and theme
   (`shf-theme`). `python -m shf.dashboard` builds both `docs/index.html` and `docs/hif-sensor/index.html`.
   The Tier-2 report keeps this order: header and guide → headline tiles → Run checks → sections (3D model,
   fault location, errors, restoration, zones, Q&A, glossary, data). The orange **Monitor** button in the
   top bar and the Monitor card under the tour (what it is, 3 steps, a note that it is a demo) are the main
   call to action; Explain mode is always on.

## Commands

```bash
.venv\Scripts\python run.py                          # full study, ~6 min, rebuilds the report
.venv\Scripts\python scripts\error_analysis.py       # ~1 min, after run.py
.venv\Scripts\python scripts\export_control_room.py  # ~15 s, after run.py
.venv\Scripts\python scripts\load_shape.py           # hourly study: needs AEP_hourly.csv (see notebooks/kaggle_hourly.ipynb)
.venv\Scripts\python scripts\hourly_restoration.py   # ~20 s, after run.py and load_shape.py
.venv\Scripts\python scripts\export_oneline_dxf.py   # ~2 s, one-line DXF for AutoCAD from results/
.venv\Scripts\python scripts\autocad_export.py --register  # ~5 s, AutoCAD saves the DWG and plots PDF + PNG (needs AutoCAD)
.venv\Scripts\python scripts\spice_run.py --register  # ~5 s, LTspice circuits from OpenDSS values -> exports/, results/spice/ (needs LTspice)
.venv\Scripts\python scripts\panel_bridge.py         # drives the Wokwi ESP32 panel over MQTT (board/README.md); --dry-run prints one incident
.venv\Scripts\python scripts\wokwi_diagram.py        # ~2 s, writes board/wokwi/diagram.json from the zone tree
.venv\Scripts\python scripts\wokwi_demo.py           # ~10 s, writes the recorded demo incidents into sketch.ino (then update the shared Wokwi project)
.venv\Scripts\python scripts\export_drawings.py --register  # ~30 s, dimensioned A3 drawings of the six parts (needs AutoCAD; --dxf-only without)
.venv\Scripts\python scripts\solidworks_build.py --part all --register  # ~8 min, SolidWorks builds the six parts, exports GLB/STEP/PNG (needs SolidWorks)
.venv\Scripts\python scripts\register_export.py <id> # after exporting from AutoCAD/SolidWorks/LTspice/Factory IO
.venv\Scripts\python -m shf.dashboard                # ~2 s, rebuild docs/index.html AND docs/hif-sensor/index.html from results/
.venv\Scripts\python -m shf.provenance               # verifies 23 Tier-2 manifests / 51 result files
.venv\Scripts\python harness\check.py --tests        # health check + 144 Tier-2 pytest tests: must end with 0 failed
pushd hif_sensor && ..\.venv\Scripts\python -m hif.provenance --verify && ..\.venv\Scripts\python -m pytest -v tests/test_hif.py && popd  # Tier-1 23-file provenance + 10 pytest tests (cwd=hif_sensor required because root pytest.ini sets testpaths=tests)
.venv\Scripts\python -m shf.apis                     # which API keys are set (never prints them)
```

Nothing above calls an outside API, so re-running costs nothing.

## Definition of done

- `.venv\Scripts\python -m shf.provenance` passes (`23` manifests, `51` files).
- `.venv\Scripts\python harness\check.py --tests` ends with **0 failed, 0 warnings** (`144` Tier-2 unit tests + `235` health checks).
- Inside `hif_sensor/`, `..\.venv\Scripts\python -m hif.provenance --verify` passes (`23` files) and `..\.venv\Scripts\python -m pytest -v tests/test_hif.py` passes (`10 passed`).
- The page opens and works: check `docs/index.html`, `docs/hif-sensor/index.html`, and `docs/monitor/`, click a card, switch EN/VI.
- Prose says what changed in the results, not what you hoped they would show.
- Nothing from `.env`, `data/generated/`, `models/` or `inputs/private/` is committed.
- Commit only when the owner asks. Author: the owner's GitHub no-reply address (see `git log`).

## Adding new documents

The owner drops files in `inputs/` and lists them in `inputs/INDEX.md`. To use one:
read it, write in the index what it is and which claim or section it supports, decide whether it
changes the study (then change code/config and re-run) or only the text (then edit prose and
`facts.toml`), and run the check. In Claude Code the whole routine is `/refresh`; `/audit` only reviews.
