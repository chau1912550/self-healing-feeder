"""Record that an app export is fresh: run it right after exporting a drawing, part, circuit or scene.

    .venv\\Scripts\\python scripts\\register_export.py <id>     # id from workflow.toml
    .venv\\Scripts\\python scripts\\register_export.py --list   # every asset and whether it is up to date

Writes the fingerprints of the source and the export to exports/registered.json. The health check
(harness/check.py) compares them with the files on disk, so an export can't silently go stale.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shf import assets  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("id", nargs="?", help="asset id from workflow.toml")
    ap.add_argument("--list", action="store_true", help="list assets and their status")
    args = ap.parse_args()
    if args.list or not args.id:
        items = assets.load()
        if not items:
            print("workflow.toml lists no assets yet.")
        for a in items:
            ok, msg = assets.status(a)
            print(("OK   " if ok else "PLAN " if ok is None else "TODO ") + msg)
        return
    r = assets.register(args.id)
    print(f"registered {args.id}: source {r['source_sha256'][:12]}…, export {r['export_sha256'][:12]}…")


if __name__ == "__main__":
    main()
