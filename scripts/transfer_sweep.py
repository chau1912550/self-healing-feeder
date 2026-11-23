"""Fault sweep as graph samples, for the transfer study (research/gnn-transfer/PLAN.md, phase 1).

    .venv\\Scripts\\python scripts\\transfer_sweep.py                  # ieee123 (train) and ieee34 (never trained on)
    .venv\\Scripts\\python scripts\\transfer_sweep.py --feeder ieee34

Writes data/generated/transfer_<feeder>.npz (not in git) and results/transfer/dataset_<feeder>.json
(with a run record). Simulation only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run from anywhere

from shf import transfer  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feeder", choices=["ieee123", "ieee34", "all"], default="all")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    for name in (["ieee123", "ieee34"] if args.feeder == "all" else [args.feeder]):
        s = transfer.sweep(name, seed=args.seed)
        print(json.dumps({k: s[k] for k in ("feeder", "events", "converged", "runtime_s")}))
        for d in s["devices"]:
            print(f"   {d['name']:4} line {d['line']:5} parent {str(d['parent']):5} buses {d['buses']:3} "
                  f"events {d['events']}")


if __name__ == "__main__":
    main()
