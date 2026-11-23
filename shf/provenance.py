"""Run provenance: every result file says which run wrote it, so no number can be typed in by hand.

Each script that writes to results/ calls `record(producer, paths)` after writing. That stores, per
file, a SHA-256 of its content, the command, the time, the git commit and whether the source code
was clean, in results/provenance/<producer>.json. The health check (harness/check.py) then fails
if a result file no longer matches the hash its run recorded: the file was edited by hand or
written outside a recorded run. Files with no record yet give a warning that says how to re-run.

Hashes ignore CRLF/LF differences in text files, so a Windows checkout does not trip the check.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import config

DIR = config.RESULTS / "provenance"
TEXT = {".json", ".csv", ".md", ".jsonl", ".txt"}
SOURCE = ("shf", "scripts", "run.py", "data/feeder")    # code and inputs a run depends on


def sha256(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=config.ROOT, capture_output=True, text=True, timeout=20)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def record(producer: str, paths: Iterable[Path]) -> Path:
    """Record the files a run just wrote. Call it after the files are written, in the same run."""
    commit = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain", "--", *SOURCE)
    files = {}
    for p in sorted({Path(p) for p in paths}):
        if not p.exists():
            raise FileNotFoundError(f"{p} was not written by this run")
        files[p.relative_to(config.ROOT).as_posix()] = sha256(p)
    entry = {
        "producer": producer,
        "command": " ".join([Path(sys.argv[0]).name, *sys.argv[1:]]) if sys.argv and sys.argv[0] else producer,
        "written_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git_commit": commit,
        "source_clean": None if dirty is None else dirty == "",
        "python": platform.python_version(),
        "files": files,
    }
    DIR.mkdir(parents=True, exist_ok=True)
    out = DIR / f"{producer}.json"
    out.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    return out


def recorded() -> dict[str, tuple[str, str]]:
    """{result file: (sha256 recorded, producer)} over every provenance record."""
    out = {}
    for f in sorted(DIR.glob("*.json")) if DIR.exists() else []:
        e = json.loads(f.read_text(encoding="utf-8"))
        for rel, h in e["files"].items():
            out[rel] = (h, e["producer"])
    return out


def verify() -> dict[str, list[str]]:
    """{'changed': files whose content differs from their run's record,
        'missing': recorded files that are gone,
        'unrecorded': result files no run has recorded yet}."""
    rec = recorded()
    changed, missing = [], []
    for rel, (h, _) in rec.items():
        p = config.ROOT / rel
        if not p.exists():
            missing.append(rel)
        elif sha256(p) != h:
            changed.append(rel)
    files = [p.relative_to(config.ROOT).as_posix() for p in config.RESULTS.rglob("*")
             if p.is_file() and DIR not in p.parents]
    unrecorded = sorted(f for f in files if f not in rec)
    return {"changed": sorted(changed), "missing": sorted(missing), "unrecorded": unrecorded}
