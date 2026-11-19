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

It is **simulation only**. No field data, no deployment at a utility, no real SCADA connection
(the MQTT/TimescaleDB path exists but has not been run end to end). Every text must keep that clear.

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
| `shf/cad.py`, `scripts/export_oneline_dxf.py`, `scripts/autocad_export.py` | One-line diagram DXF for AutoCAD, drawn from `results/` → `cad/feeder_oneline.dxf` (the health check fails if it is older than the results) | Code yes; the DXF is generated |
| `shf/spice.py`, `scripts/spice_run.py` | LTspice circuits written from the OpenDSS model (fault DC offset, CT/ADC front end, arcing high-impedance fault), run in batch, waveforms → `exports/spice_*.csv`, numbers → `results/spice/summary.json` | Code yes; the `.asc` files are generated |
| `workflow.toml`, `cad/`, `mech/`, `spice/`, `hmi/`, `exports/` | Files made in AutoCAD, SolidWorks, LTspice and Factory IO, and their exports; `scripts/register_export.py` records a fresh export | Sources yes; `exports/registered.json` only through the script |
| `results/` | **Source of truth for every number.** `metrics.json` first | **No**, generated |
| `shf/dashboard.py` | Builds `docs/index.html` (layout, charts, checks, numbers) | Yes |
| `shf/dashboard_text.py` | All report prose: Q&A (`FAQ`), `GLOSSARY`, guide texts (`EXPLAIN`, `MODEL`), EN + VI | Yes |
| `docs/index.html` | The report page on GitHub Pages | **No**, built by `python -m shf.dashboard` |
| `docs/data/` | Published copies of result files | **No**, copied by the dashboard build |
| `docs/monitor/` | Role-based outage demo (dispatcher, crew, engineer, manager); `index.html` is hand-written, `data.json` generated | `index.html` yes |
| `README.md`, `docs/vi/*.md` | Prose with numbers in it, checked by `harness/facts.toml` | Yes |
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
4. **No claim beyond the evidence.** Not "deployed", not "field-validated", not "real-time SCADA".
   Results on unseen buses are not results on a real feeder. The list of banned phrases is in `harness/facts.toml`.
5. **English and Vietnamese stay in step.** Every `T(en, vi)` / `TB(en, vi)` / FAQ entry has both. When
   README changes in a way a reader of `docs/vi/` would notice, update `docs/vi/module-guide.md` too.
6. **Sources.** A fact from an outside document (paper, standard, utility report) gets a reference in
   README "References" with a link. Don't quote long passages.
7. **Page layout.** The report keeps this order: header and guide → headline tiles → Run checks →
   sections (3D model, fault location, errors, restoration, zones, Q&A, glossary, data). The orange
   **Monitor** button in the top bar and the Monitor card under the tour (what it is, 3 steps, a note that
   it is a demo) are the main call to action; Explain mode is always on.

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
.venv\Scripts\python scripts\register_export.py <id> # after exporting from AutoCAD/SolidWorks/LTspice/Factory IO
.venv\Scripts\python -m shf.dashboard                # ~1 s, rebuild the page from results/
.venv\Scripts\python harness\check.py --tests        # health check + pytest: must end with 0 failed
.venv\Scripts\python -m shf.apis                     # which API keys are set (never prints them)
```

Nothing above calls an outside API, so re-running costs nothing.

## Definition of done

- `python harness/check.py --tests` ends with **0 failed**.
- The page opens and works: run the `report-page` preview (or open `docs/index.html`), click a card,
  open Monitor, switch EN/VI.
- Prose says what changed in the results, not what you hoped they would show.
- Nothing from `.env`, `data/generated/`, `models/` or `inputs/private/` is committed.
- Commit only when the owner asks. Author: the owner's GitHub no-reply address (see `git log`).

## Adding new documents

The owner drops files in `inputs/` and lists them in `inputs/INDEX.md`. To use one:
read it, write in the index what it is and which claim or section it supports, decide whether it
changes the study (then change code/config and re-run) or only the text (then edit prose and
`facts.toml`), and run the check. In Claude Code the whole routine is `/refresh`; `/audit` only reviews.
