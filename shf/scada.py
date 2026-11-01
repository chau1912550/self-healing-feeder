"""Simulated SCADA event: replay one fault as the messages devices would send.

Timeline (simulated seconds):
  t=0    normal readings from every device
  t=1    fault: devices report fault currents
  t=1.5  feeder-head recloser Sw1 locks out
  t=2    ML model names the faulted zone from the t=0 / t=1 event records
  t=5    isolation switches open, Sw1 re-closes, ties close (restoration plan)

Messages go to MQTT (topic shf/<feeder>/<device> and shf/<feeder>/events) or
to a JSON-lines file when no broker is given.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np

from . import faults, feeder, restoration
from .topology import Zones

FEEDER_ID = "ieee123"


def _reading(event_id: str, t: datetime, device: str, status: str, m: dict | None) -> dict:
    i = np.abs(m["i"]) if m else np.zeros(3)
    v = np.abs(m["v"]) if m else np.zeros(3)
    return {"ts": t.isoformat(), "event_id": event_id, "feeder": FEEDER_ID, "device": device,
            "status": status, "ia": round(float(i[0]), 2), "ib": round(float(i[1]), 2),
            "ic": round(float(i[2]), 2), "va_pu": round(float(v[0]), 4),
            "vb_pu": round(float(v[1]), 4), "vc_pu": round(float(v[2]), 4)}


def simulate_event(zones: Zones, model_bundle: dict, bus: str, spec: str,
                   seed: int = 1) -> tuple[list[dict], dict]:
    rng = np.random.default_rng(seed)
    t0 = datetime.now(timezone.utc).replace(microsecond=0)
    event_id = f"{FEEDER_ID}-{t0:%Y%m%dT%H%M%S}"
    msgs: list[dict] = []
    devices = faults.DEVICES

    feeder.set_normal_configuration()
    feeder.solve(controls=True)
    pre = faults.snapshot(rng)
    msgs += [_reading(event_id, t0, d, "closed", pre[d]) for d in devices]

    feeder.cmd(f"New Fault.Demo {spec} enabled=yes")
    feeder.solve(controls=False)
    post = faults.snapshot(rng)
    t1 = t0 + timedelta(seconds=1)
    msgs += [_reading(event_id, t1, d, "closed", post[d]) for d in devices]

    t2 = t0 + timedelta(seconds=1.5)
    msgs += [_reading(event_id, t2, d, "open-lockout" if d == "Sw1" else "closed", None)
             for d in devices]

    row = faults.features(post, pre)
    x = np.array([[row[c] for c in model_bundle["columns"]]], dtype=float)
    clf = model_bundle["model"]
    proba = clf.predict_proba(x)[0]
    pred = str(clf.classes_[int(np.argmax(proba))])
    true_zone = zones.bus_zone[bus]
    msgs.append({"ts": (t0 + timedelta(seconds=2)).isoformat(), "event_id": event_id,
                 "feeder": FEEDER_ID, "device": "fault-locator", "status": "zone-identified",
                 "predicted_zone": pred, "confidence": round(float(proba.max()), 3),
                 "true_zone": true_zone, "fault_spec": spec})

    feeder.cmd("Edit Fault.Demo enabled=no")
    plan = restoration.plan_restoration(zones, pred)
    fault_isolated = true_zone == pred
    t5 = t0 + timedelta(seconds=5)
    for d in devices:
        status = "open" if not feeder.is_closed(d) else "closed"
        msgs.append(_reading(event_id, t5, d, status, feeder.device_measurement(d)))
    for tie in zones.tie_ends:
        msgs.append(_reading(event_id, t5, tie, "closed" if tie in plan.closed_ties else "open",
                             feeder.device_measurement(tie)))
    restoration.reset(zones)
    summary = {"event_id": event_id, "bus": bus, "true_zone": true_zone, "predicted_zone": pred,
               "confidence": float(proba.max()), "fault_isolated": fault_isolated,
               "steps": plan.steps, "unserved": sorted(plan.unserved)}
    msgs.append({"ts": t5.isoformat(), "event_id": event_id, "feeder": FEEDER_ID,
                 "device": "flisr", "status": "restoration-complete", **{
                     k: summary[k] for k in ("fault_isolated", "unserved", "steps")}})
    return msgs, summary


def write_jsonl(msgs: list[dict], path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m) + "\n")


def topic_for(msg: dict) -> str:
    kind = "events" if msg["device"] in ("fault-locator", "flisr") else msg["device"]
    return f"shf/{msg['feeder']}/{kind}"


def publish_mqtt(msgs: list[dict], host: str, port: int = 1883) -> None:
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="shf-replay")
    client.connect(host, port)
    client.loop_start()
    for m in msgs:
        client.publish(topic_for(m), json.dumps(m), qos=1).wait_for_publish()
    client.loop_stop()
    client.disconnect()
