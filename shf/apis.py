"""Outside-service keys, read from the registry in config/apis.md and the git-ignored .env.

    from shf import apis
    apis.key("Claude")          # -> the key, or a clear error saying what to set

    python -m shf.apis          # table of registered APIs and whether each key is set
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "apis.md"
ENV_FILE = ROOT / ".env"
COLUMNS = ["Name", "Env var", "Status", "Purpose", "Used by", "Cost", "Docs"]
STATUSES = {"planned", "active", "off"}


def registry() -> list[dict]:
    """Rows of the table under '## Registry' in config/apis.md."""
    text = REGISTRY.read_text(encoding="utf-8")
    body = text.split("## Registry", 1)[1] if "## Registry" in text else ""
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|") or re.fullmatch(r"\|[\s\-|:]+\|", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells == COLUMNS:
            continue
        if len(cells) != len(COLUMNS):
            raise ValueError(f"config/apis.md: row needs {len(COLUMNS)} columns: {line}")
        rows.append(dict(zip(COLUMNS, cells)))
    return rows


def _dotenv() -> dict:
    vals = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def _value(var: str) -> str:
    return os.environ.get(var) or _dotenv().get(var, "")


def key(name: str) -> str:
    """The key for a registered API. Only `active` rows can be used."""
    row = next((r for r in registry() if r["Name"].lower() == name.lower()), None)
    if row is None:
        raise KeyError(f"'{name}' is not in config/apis.md. Add a row there first.")
    if row["Status"] != "active":
        raise PermissionError(f"'{name}' has status '{row['Status']}' in config/apis.md. "
                              "Set it to 'active' once the code that uses it is ready.")
    val = _value(row["Env var"])
    if not val:
        raise RuntimeError(f"{row['Env var']} is empty. Put it in .env (see .env.example).")
    return val


def status() -> list[dict]:
    return [{**r, "set": bool(_value(r["Env var"]))} for r in registry()]


if __name__ == "__main__":
    rows = status()
    w = max(len(r["Name"]) for r in rows) if rows else 4
    print(f"{'Name':<{w}}  {'Env var':<20} {'Status':<8} Key")
    for r in rows:
        print(f"{r['Name']:<{w}}  {r['Env var']:<20} {r['Status']:<8} {'set' if r['set'] else '-'}")
    print("\nNo API is called by the study today: run.py works fully offline.")
