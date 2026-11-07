---
description: Review the project's content and layout for errors, stale numbers and overclaims, without editing
argument-hint: "[optional: section or file to focus on]"
---

Audit the self-healing-feeder project. Focus: $ARGUMENTS

Read only; change nothing. Follow AGENTS.md.

1. Run `.venv\Scripts\python harness\check.py --tests -v`.
2. Read README.md, `shf/dashboard_text.py` and `docs/monitor/README.md`. For each number in prose, find its
   source in `results/`. List numbers that are not in `harness/facts.toml` yet (they are unchecked).
3. Look for claims beyond the evidence (deployment, field data, real-time, "proves"), EN/VI mismatches,
   assumptions used in code but missing from README "Assumptions and limitations", and stale wording
   about features that changed.
4. Check the layout of the report page against AGENTS.md rule 7 in the `report-page` preview.
5. Report in Vietnamese as a short table: problem, where (file:line), why it matters, proposed fix.
   Most serious first. End by asking which ones to fix.
