"""Drive the Wokwi control panel (board/wokwi/) from the study, over MQTT.

    python scripts/panel_bridge.py                       # wait for the board's buttons
    python scripts/panel_bridge.py --dry-run --bus 60 --phase 1 --r 25   # print one incident's frames

FAULT on the board: a line-to-ground fault in a random zone (then a random bus in it), with the
knob's resistance, goes through the same steps as scripts/demo_event.py (OpenDSS fault, ML zone,
restoration plan); the board shows each switching step. CLOSE TIES closes the planned ties, RESET goes back to normal.
Needs models/model.pkl (run `python run.py` first). Simulation only.
"""
from __future__ import annotations

import argparse
import json
import pickle
import queue
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run from anywhere

from shf import config, faults, feeder, panel, restoration, scada, topology


def missing_accuracy() -> dict:
    """The study's fault-location accuracy with each sensor missing (results/metrics.json)."""
    m = json.loads((config.RESULTS / "metrics.json").read_text(encoding="utf-8"))
    return m["fault_location"]["ml_full"]["missing_sensor_accuracy"]


def incident(zones, bundle, bus: str, phase: str, r: float, seed: int, sensor=False, stuck=False):
    """One fault. Failure injection: `sensor` blanks the readings of one switch picked at random,
    as in the study's missing-sensor test (so the accuracy the LCD quotes fits the case shown);
    `stuck` makes the first isolating switch fail to open."""
    spec = f"phases=1 bus1={bus}.{phase} bus2={bus}.0 r={r}"
    devices = list(config.SECTIONALIZERS)
    missing = devices[int(np.random.default_rng(seed).integers(len(devices)))] if sensor else None
    _, summary = scada.simulate_event(zones, bundle, bus, spec, seed=seed, missing=missing, stuck_switch=stuck)
    return summary, *panel.incident_frames(zones, summary, phase, r, missing_accuracy())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print one incident's frames, no MQTT")
    ap.add_argument("--bus", default="60")
    ap.add_argument("--phase", default="1")
    ap.add_argument("--r", type=float, default=25.0)
    ap.add_argument("--host", default=config.PANEL_BROKER[0])
    ap.add_argument("--port", type=int, default=config.PANEL_BROKER[1])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--sensor", action="store_true", help="dry run: the faulted zone's switch sends no readings")
    ap.add_argument("--stuck", action="store_true", help="dry run: the first isolating switch fails to open")
    args = ap.parse_args()

    with open(config.MODELS / "model.pkl", "rb") as f:
        bundle = pickle.load(f)
    feeder.load_feeder()
    zones = topology.find_zones()
    restoration.reset(zones)

    if args.dry_run:
        summary, now, after = incident(zones, bundle, args.bus, args.phase, args.r, args.seed,
                                       args.sensor, args.stuck)
        print(f"true zone {summary['true_zone']}, ML zone {summary['predicted_zone']} "
              f"({summary['confidence']:.2f})")
        for f in [panel.idle_frame(zones), *now, *after]:
            print(f["lamps"], f["lock"], f["wait"], " | ".join(f["lcd"]))
        return

    import paho.mqtt.client as mqtt

    inbox: queue.Queue = queue.Queue()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"shf-bridge-{np.random.randint(1 << 30)}")

    def on_connect(c, userdata, flags, rc, props=None):
        c.subscribe(panel.TOPIC_CMD, qos=1)
        print(f"connected to {args.host}:{args.port}, listening on {panel.TOPIC_CMD}")

    def on_message(c, userdata, msg):
        cmd = panel.parse_command(msg.payload)
        if cmd:
            inbox.put(cmd)

    client.on_connect, client.on_message = on_connect, on_message
    client.connect(args.host, args.port, keepalive=30)
    client.loop_start()

    seq = 0

    def show(f: dict) -> None:
        nonlocal seq
        seq += 1
        client.publish(panel.TOPIC_STATE, json.dumps({"seq": seq, **f}, separators=(",", ":")),
                       qos=1)   # not retained: a board opened later must not see a stale frame
        print(f"  {f['lamps']} lock={f['lock']} | " + " | ".join(x for x in f["lcd"] if x))

    rng = np.random.default_rng(args.seed)
    by_zone: dict[str, list] = {}         # every zone equally likely, then a bus and phase inside it
    for c in faults.fault_cases(zones):
        if c["ftype"] == "SLG" and (c["bus"], c["phases"]) not in by_zone.setdefault(c["zone"], []):
            by_zone[c["zone"]].append((c["bus"], c["phases"]))
    idle, last, after = panel.idle_frame(zones), None, []
    show(idle)
    last = idle
    try:
        while True:
            cmd = inbox.get()
            if cmd["cmd"] == "hello":
                show(last)
            elif cmd["cmd"] == "reset":
                after = []
                restoration.reset(zones)
                last = idle
                show(idle)
            elif cmd["cmd"] == "ties" and after:
                for f in after:
                    show(f)
                last, after = after[-1], []
            elif cmd["cmd"] == "fault" and last is idle:
                pool = by_zone[sorted(by_zone)[int(rng.integers(len(by_zone)))]]
                bus, phase = pool[int(rng.integers(len(pool)))]
                print(f"fault: bus {bus} phase {phase}, {cmd['r']:g} ohm"
                      + (", sensor offline" if cmd["sensor"] else "") + (", switch stuck" if cmd["stuck"] else ""))
                try:
                    summary, now, after = incident(zones, bundle, bus, phase, cmd["r"], int(rng.integers(1 << 30)),
                                                   cmd["sensor"], cmd["stuck"])
                except Exception as ex:          # keep the panel alive; say what went wrong
                    print(f"  failed: {ex}")
                    restoration.reset(zones)
                    after, now = [], [panel.frame(idle["lamps"], panel.lcd("Study error:", str(ex)))]
                for f in now:
                    show(f)
                    time.sleep(config.PANEL_STEP_S)
                last = now[-1]
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
