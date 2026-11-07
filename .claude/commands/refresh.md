---
description: Update the study, the report and the Monitor from new documents in inputs/, then verify every number
argument-hint: "[optional: file in inputs/ or what to focus on]"
---

Refresh the self-healing-feeder project. Focus: $ARGUMENTS

Follow AGENTS.md. Work in this order and keep the owner's task list current:

1. **Read the ground rules.** AGENTS.md (content rules, map), `harness/facts.toml`, README "Assumptions and limitations".
2. **Baseline.** Run `.venv\Scripts\python harness\check.py --tests` and note anything already failing.
3. **New material.** Read `inputs/INDEX.md` and every file with status `new` (or the file named in the focus).
   For each, decide and write in the index:
   - what it is and which claim or section it supports;
   - whether it **changes the study** (a new assumption, device, method or data source) or **only the text**;
   - if it contradicts the project, say so in the index and to the owner; do not hide it.
4. **Plan, then ask.** Before editing, tell the owner in Vietnamese, in a few lines: what will change in
   the study, the report and the Monitor, and what stays. Wait for a yes if the study itself changes.
5. **Study changes** (only if step 3 says so): edit `shf/config.py` (mark `ASSUMPTION`) or the step module,
   then run `run.py`, `scripts/error_analysis.py`, `scripts/export_control_room.py` in that order.
6. **Text changes:** README, `shf/dashboard_text.py` (EN and VI together), `docs/vi/module-guide.md`,
   `docs/monitor/README.md`. Every number read from `results/`; every new number added to `harness/facts.toml`;
   every outside fact cited under README "References". Then `python -m shf.dashboard`.
7. **Verify.** `harness\check.py --tests` must show 0 failed. Open the `report-page` preview: click a card,
   open Monitor, switch EN/VI. Fix what breaks and re-check.
8. **Report** in Vietnamese: what changed, which numbers moved (old → new), what was not done.
   Mark the `inputs/INDEX.md` rows `used` or `skipped`. Do not commit unless the owner asks.
