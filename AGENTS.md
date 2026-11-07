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
   **Monitor** button in the top bar is the main call to action; Explain mode is always on.

## Commands

```bash
.venv\Scripts\python run.py                          # full study, ~6 min, rebuilds the report
.venv\Scripts\python scripts\error_analysis.py       # ~1 min, after run.py
.venv\Scripts\python scripts\export_control_room.py  # ~15 s, after run.py
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
