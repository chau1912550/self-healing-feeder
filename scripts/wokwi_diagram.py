"""Write board/wokwi/diagram.json: the Wokwi wiring of the control panel.

    python scripts/wokwi_diagram.py

The 12 RGB lamps are laid out as a mimic of the feeder's zone tree (depth to the right, one row per
branch), drawn from the study's topology, and chained in shf.panel.LAMPS order on one data pin.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run from anywhere

from shf import config, feeder, panel, topology

OUT = config.ROOT / "board" / "wokwi" / "diagram.json"
CELL_W, CELL_H, X0, Y0 = 110, 70, 30, 40
PIN_LAMPS, PIN_LOCK, PIN_KNOB, PIN_SDA, PIN_SCL = "13", "4", "34", "21", "22"
PIN_HIF_LED, PIN_BTN_HIF = "5", "14"
FAILURES = [("sensor", "SENSOR OFFLINE", "32"), ("stuck", "SWITCH STUCK", "33")]   # slide right = on
BUTTONS = [("fault", "FAULT", "red", "25"), ("ties", "CLOSE TIES", "green", "26"),
           ("reset", "RESET", "blue", "27"), ("hif", "HIF ARC", "yellow", PIN_BTN_HIF)]
GND, V5, V3 = "esp:GND.1", "esp:5V", "esp:3V3"


def mimic(zones) -> dict[str, tuple[float, float]]:
    """(column, row) of every lamp: switches by depth in the zone tree, ties in the last column."""
    children = {z: [c for c in zones.names if zones.parent[c] == z] for z in zones.names}
    root = next(z for z in zones.names if not zones.parent[z])
    pos, row = {}, [0]

    def place(z, depth):
        pos[z] = (depth, row[0])
        kids = children[z]
        for i, c in enumerate(kids):
            if i:
                row[0] += 1
            place(c, depth + 1)

    place(root, 0)
    last = max(c for c, _ in pos.values()) + 1
    for i, tie in enumerate(config.TIES):
        rows = [pos[zones.bus_zone[b]][1] for b in zones.tie_ends[tie] if b in zones.bus_zone]
        pos[tie] = (last, sum(rows) / len(rows) + 0.5 * i)
    return pos


def build(zones) -> dict:
    pos = mimic(zones)
    parts = [{"type": "board-esp32-devkit-c-v4", "id": "esp", "top": 40, "left": X0 + 7 * CELL_W, "attrs": {}},
             {"type": "wokwi-text", "id": "title", "top": 0, "left": X0,
              "attrs": {"text": "Self-healing feeder panel - Wokwi simulation (lamp: green closed, red open, "
                                "grey no power, amber located / tie ready, purple no sensor data, "
                                "red blink stuck)"}}]
    conns = [["esp:TX", "$serialMonitor:RX", "", []], ["esp:RX", "$serialMonitor:TX", "", []]]
    prev = f"esp:{PIN_LAMPS}"
    for i, name in enumerate(panel.LAMPS):
        col, row = pos[name]
        left, top = X0 + col * CELL_W, Y0 + row * CELL_H
        what = "tie" if name in config.TIES else ("recloser" if name == "Sw1" else "switch")
        parts += [{"type": "wokwi-neopixel", "id": f"lamp{i}", "top": top, "left": left, "attrs": {}},
                  {"type": "wokwi-text", "id": f"label{i}", "top": top + 26, "left": left - 12,
                   "attrs": {"text": f"{name} {what}"}}]
        conns += [[prev, f"lamp{i}:DIN", "green", []], [f"lamp{i}:VDD", V5, "red", []],
                  [f"lamp{i}:VSS", GND, "black", []]]
        prev = f"lamp{i}:DOUT"
    below = Y0 + (max(r for _, r in pos.values()) + 1) * CELL_H + 20
    parts += [{"type": "wokwi-led", "id": "lock", "top": below, "left": X0, "attrs": {"color": "red"}},
              {"type": "wokwi-resistor", "id": "rlock", "top": below + 60, "left": X0 - 20, "attrs": {"value": "220"}},
              {"type": "wokwi-text", "id": "locklabel", "top": below + 10, "left": X0 + 30,
               "attrs": {"text": "LOCKOUT (Sw1 locked out)"}},
              {"type": "wokwi-led", "id": "hif_led", "top": below, "left": X0 + 280, "attrs": {"color": "yellow"}},
              {"type": "wokwi-resistor", "id": "rhif", "top": below + 60, "left": X0 + 260, "attrs": {"value": "220"}},
              {"type": "wokwi-text", "id": "hiflabel", "top": below + 10, "left": X0 + 310,
               "attrs": {"text": "HIF ALARM (Tier-1 C99)"}},
              {"type": "wokwi-lcd2004", "id": "lcd", "top": below + 100, "left": X0, "attrs": {"pins": "i2c"}}]
    conns += [[f"esp:{PIN_LOCK}", "rlock:2", "orange", []], ["rlock:1", "lock:A", "orange", []],
              ["lock:C", GND, "black", []],
              [f"esp:{PIN_HIF_LED}", "rhif:2", "yellow", []], ["rhif:1", "hif_led:A", "yellow", []],
              ["hif_led:C", GND, "black", []],
              ["lcd:GND", GND, "black", []], ["lcd:VCC", V5, "red", []],
              ["lcd:SDA", f"esp:{PIN_SDA}", "blue", []], ["lcd:SCL", f"esp:{PIN_SCL}", "purple", []]]
    knobs = below + 330
    for i, (cmd, label, color, pin) in enumerate(BUTTONS):
        left = X0 + i * 120
        wire = "yellow" if cmd == "hif" else "green"
        parts += [{"type": "wokwi-pushbutton", "id": f"btn_{cmd}", "top": knobs, "left": left,
                   "attrs": {"color": color}},
                  {"type": "wokwi-text", "id": f"btnlabel_{cmd}", "top": knobs + 50, "left": left,
                   "attrs": {"text": label}}]
        conns += [[f"btn_{cmd}:1.l", f"esp:{pin}", wire, []], [f"btn_{cmd}:2.l", GND, "black", []]]
    parts += [{"type": "wokwi-potentiometer", "id": "knob", "top": knobs - 20, "left": X0 + 500, "attrs": {}},
              {"type": "wokwi-text", "id": "knoblabel", "top": knobs + 60, "left": X0 + 490,
               "attrs": {"text": "fault resistance"}}]
    conns += [["knob:GND", GND, "black", []], ["knob:VCC", V3, "red", []], ["knob:SIG", f"esp:{PIN_KNOB}", "green", []]]
    parts.append({"type": "wokwi-text", "id": "faillabel", "top": knobs - 40, "left": X0 + 660,
                  "attrs": {"text": "Failure injection (slide right = on)"}})
    for i, (key, label, pin) in enumerate(FAILURES):   # common pin to the ESP32, right side to GND
        left = X0 + 680 + i * 180
        parts += [{"type": "wokwi-slide-switch", "id": f"sw_{key}", "top": knobs, "left": left, "attrs": {}},
                  {"type": "wokwi-text", "id": f"swlabel_{key}", "top": knobs + 40, "left": left - 30,
                   "attrs": {"text": label}}]
        conns += [[f"sw_{key}:2", f"esp:{pin}", "orange", []], [f"sw_{key}:3", GND, "black", []]]
    return {"version": 1, "author": "self-healing-feeder (generated by scripts/wokwi_diagram.py)",
            "editor": "wokwi", "parts": parts, "connections": conns, "dependencies": {}}


def main() -> None:
    feeder.load_feeder()
    zones = topology.find_zones()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(zones), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(config.ROOT)} ({len(panel.LAMPS)} lamps)")


if __name__ == "__main__":
    main()
