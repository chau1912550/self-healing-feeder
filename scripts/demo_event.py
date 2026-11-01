"""Replay one simulated fault as SCADA messages.

    python scripts/demo_event.py --bus 60 --type SLG --phase 1 --r 50
    python scripts/demo_event.py --bus 60 --mqtt localhost     # publish to a broker

Needs models/model.pkl (run `python run.py` first).
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run from anywhere

from shf import config, feeder, scada, topology

SPECS = {
    "SLG": "phases=1 bus1={b}.{p} bus2={b}.0 r={r}",
    "LL": "phases=1 bus1={b}.1 bus2={b}.2 r={r}",
    "3PH": "phases=3 bus1={b}.1.2.3 bus2={b}.0.0.0 r={r}",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bus", default="60")
    ap.add_argument("--type", default="SLG", choices=list(SPECS))
    ap.add_argument("--phase", default="1")
    ap.add_argument("--r", type=float, default=50.0)
    ap.add_argument("--mqtt", help="MQTT broker host; omit to write results/demo_event.jsonl")
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()

    with open(config.MODELS / "model.pkl", "rb") as f:
        bundle = pickle.load(f)
    feeder.load_feeder()
    zones = topology.find_zones()
    spec = SPECS[args.type].format(b=args.bus, p=args.phase, r=args.r)
    msgs, summary = scada.simulate_event(zones, bundle, args.bus, spec)

    print(f"Fault: {args.type} at bus {args.bus}, {args.r} ohm  (true zone {summary['true_zone']})")
    print(f"ML says zone {summary['predicted_zone']} "
          f"(confidence {summary['confidence']:.2f}); fault isolated: {summary['fault_isolated']}")
    for i, s in enumerate(summary["steps"], 1):
        print(f"  {i}. {s}")
    if args.mqtt:
        scada.publish_mqtt(msgs, args.mqtt, args.port)
        print(f"published {len(msgs)} messages to {args.mqtt}:{args.port} (topics shf/ieee123/#)")
    else:
        path = config.RESULTS / "demo_event.jsonl"
        scada.write_jsonl(msgs, path)
        print(f"wrote {len(msgs)} messages to {path}")


if __name__ == "__main__":
    main()
