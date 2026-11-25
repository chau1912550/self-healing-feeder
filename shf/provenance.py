"""Run provenance: every result file says which run wrote it, so no number can be typed in by hand.

Each script that writes to results/ calls `record(producer, paths)` after writing. That stores, per
file, a SHA-256 of its content, the command, the time, the git commit and whether the source code
was clean, in results/provenance/<producer>.json. The health check (harness/check.py) then fails
if a result file no longer matches the hash its run recorded: the file was edited by hand or
written outside a recorded run. Files with no record yet give a warning that says how to re-run.

Hashes ignore CRLF/LF differences in text files, so a Windows checkout does not trip the check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import config

DIR = config.RESULTS / "provenance"
TEXT = {".json", ".csv", ".md", ".jsonl", ".txt"}
SOURCE = ("shf", "scripts", "run.py", "data/feeder")    # code and inputs a run depends on
_WIN_USER_RE = re.compile(r"[A-Za-z]:\\Users\\[^\\/\s,]+(?:\\[^\s,]+)?")
_POSIX_USER_RE = re.compile(r"(?:/Users/|/home/)[^/\s,]+(?:/[^\s,]+)?")


def _sanitize_command(cmd: str) -> str:
    """Strip local user-profile paths from recorded commands so usernames never enter git."""
    def _shorten(match: re.Match[str]) -> str:
        raw = match.group(0)
        parts = [p for p in re.split(r"[\\/]+", raw) if p]
        tail = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        return f"<local>/{tail}"
    out = _WIN_USER_RE.sub(_shorten, cmd)
    out = _POSIX_USER_RE.sub(_shorten, out)
    return out


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
    raw_cmd = " ".join([Path(sys.argv[0]).name, *sys.argv[1:]]) if sys.argv and sys.argv[0] else producer
    entry = {
        "producer": producer,
        "command": _sanitize_command(raw_cmd),
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


def ledger() -> list[dict]:
    """Structured provenance ledger across all manifests in results/provenance/*.json with live SHA-256 checks."""
    rows: list[dict] = []
    for f in sorted(DIR.glob("*.json")) if DIR.exists() else []:
        e = json.loads(f.read_text(encoding="utf-8"))
        file_rows = []
        all_ok = True
        for rel, expected in sorted(e.get("files", {}).items()):
            p = config.ROOT / rel
            if not p.exists():
                status = "missing"
                all_ok = False
            elif sha256(p) != expected:
                status = "changed"
                all_ok = False
            else:
                status = "ok"
            file_rows.append({"path": rel, "sha256": expected, "status": status})
        rows.append({
            "manifest": f.relative_to(config.ROOT).as_posix(),
            "producer": e.get("producer", f.stem),
            "command": e.get("command", ""),
            "written_utc": e.get("written_utc"),
            "git_commit": e.get("git_commit"),
            "source_clean": e.get("source_clean"),
            "python": e.get("python"),
            "file_count": len(file_rows),
            "verified": all_ok,
            "files": file_rows,
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify SHA-256 provenance of all files in results/.")
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON summary")
    args = ap.parse_args(argv)
    v = verify()
    rows = ledger()
    total_files = sum(r["file_count"] for r in rows)
    ok = not (v["changed"] or v["missing"] or v["unrecorded"])
    if args.json:
        print(json.dumps({
            "ok": ok,
            "manifests": len(rows),
            "recorded_files": total_files,
            "verify": v,
            "ledger": rows,
        }, indent=2))
    else:
        print(f"SHA-256 provenance verification: {len(rows)} manifests, {total_files} recorded result files")
        print(f"  changed: {len(v['changed'])}, missing: {len(v['missing'])}, unrecorded: {len(v['unrecorded'])}")
        for k in ("changed", "missing", "unrecorded"):
            for item in v[k]:
                print(f"  [{k.upper()}] {item}")
        print("PASS: all result files match their recorded SHA-256 hashes." if ok else "FAIL: provenance mismatch detected.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
