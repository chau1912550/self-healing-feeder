# API registry

Every outside service the project may call. The project calls **none** of them today: the
whole study runs offline, so re-running it costs nothing. Add a row here **before** any code
uses a new service; `harness/check.py` fails if code reads a key that is not in this table.

**Keys never go in this file or in git.** Put them in `.env` at the repo root (git-ignored),
copied from `.env.example`. Code reads them with `shf.apis.key("<Name>")`.

## How to add an API

1. Add a row to the table below. `Status`: `planned` (not used yet), `active` (code uses it), `off` (keep the row, block use).
2. Add the variable to `.env.example` with an empty value, and the real key to your own `.env`.
3. In code: `from shf import apis` then `apis.key("Name")`. It refuses `planned` and `off` rows, so a service can't be used by accident.
4. Run `python -m shf.apis` to see which keys are set (it never prints them), then `python harness/check.py`.

## Registry

| Name | Env var | Status | Purpose | Used by | Cost | Docs |
|---|---|---|---|---|---|---|
| Claude | ANTHROPIC_API_KEY | planned | Rewrite the report text in bulk after new documents are added to `inputs/` (today this is done interactively with Claude Code, `/refresh`) | – | Paid per token | https://docs.claude.com |
| EIA Open Data | EIA_API_KEY | planned | Real utility reliability data (SAIDI/SAIFI from EIA-861) to compare with the simulated outage minutes | – | Free key | https://www.eia.gov/opendata/ |
