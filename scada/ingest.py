"""Subscribe to shf/# and store device readings in TimescaleDB.

    pip install "psycopg[binary]"
    python scada/ingest.py --mqtt localhost --db "postgresql://postgres:postgres@localhost:5432/shf"
"""
from __future__ import annotations

import argparse
import json

import paho.mqtt.client as mqtt

INSERT_READING = """
INSERT INTO device_readings (time, event_id, feeder, device, status, ia, ib, ic, va_pu, vb_pu, vc_pu)
VALUES (%(ts)s, %(event_id)s, %(feeder)s, %(device)s, %(status)s,
        %(ia)s, %(ib)s, %(ic)s, %(va_pu)s, %(vb_pu)s, %(vc_pu)s)
"""
INSERT_EVENT = """
INSERT INTO flisr_events (time, event_id, feeder, source, status, payload)
VALUES (%(ts)s, %(event_id)s, %(feeder)s, %(device)s, %(status)s, %(payload)s)
"""


def main() -> None:
    import psycopg

    ap = argparse.ArgumentParser()
    ap.add_argument("--mqtt", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--db", default="postgresql://postgres:postgres@localhost:5432/shf")
    args = ap.parse_args()
    conn = psycopg.connect(args.db, autocommit=True)

    def on_message(_client, _userdata, msg):
        m = json.loads(msg.payload)
        with conn.cursor() as cur:
            if "ia" in m:
                cur.execute(INSERT_READING, m)
            else:
                cur.execute(INSERT_EVENT, {**m, "payload": json.dumps(m)})

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="shf-ingest")
    client.on_message = on_message
    client.connect(args.mqtt, args.port)
    client.subscribe("shf/#", qos=1)
    print("listening on shf/# ...")
    client.loop_forever()


if __name__ == "__main__":
    main()
