"""Wokwi control panel: the study drives a simulated ESP32 board over MQTT.

The board (board/wokwi/) has one RGB lamp per switch, a lockout lamp, a 20x4 LCD, three buttons
(FAULT, CLOSE TIES, RESET), a knob that picks the fault resistance, and two failure-injection slide
switches (SENSOR OFFLINE, SWITCH STUCK). This module turns one simulated incident
(scada.simulate_event: OpenDSS fault, ML zone, restoration plan) into the frames the board shows,
and checks the commands the board sends. Simulation only: the board is a Wokwi simulation, not
field equipment.

Frame (study -> board, JSON):
  lamps  one letter per lamp in LAMPS order: G closed with power, K closed without power,
         R open, A amber blink (located zone, or a tie waiting for the operator),
         P purple (that switch's sensor sends nothing), S red blink (switch stuck, did not open)
  lock   1 = lockout lamp on (Sw1 locked out)
  wait   1 = waiting for CLOSE TIES
  idle   1 = ready for a new fault (the board writes the knob's resistance on LCD line 2)
  lcd    four lines of at most 20 ASCII characters
  rs     (idle frames) the fault resistances the knob steps through, ohms
Command (board -> study, JSON): {"cmd": "fault", "r": <ohms>, "sensor": 0|1, "stuck": 0|1},
  {"cmd": "ties"}, {"cmd": "reset"}, {"cmd": "hello"}.
"""
from __future__ import annotations

import json
import textwrap

from . import config
from .topology import Zones

LAMPS = list(config.SECTIONALIZERS) + list(config.TIES)   # order of the lamps on the board
TOPIC_STATE = f"shf/{config.PANEL_ID}/state"
TOPIC_CMD = f"shf/{config.PANEL_ID}/cmd"
COMMANDS = ("fault", "ties", "reset", "hello")
WIDTH, ROWS = 20, 4


def lcd(*lines: str) -> list[str]:
    """Up to four lines for the 20x4 LCD; long text wraps onto the next lines."""
    out: list[str] = []
    for line in lines:
        text = line.encode("ascii", "replace").decode()
        out += textwrap.wrap(text, WIDTH) or [""]
    out = (out + [""] * ROWS)[:ROWS]
    return out


def lamps(open_devs=(), closed_ties=(), live=(), amber=(), missing=None, stuck=None) -> str:
    """Lamp letters. A switch's lamp is green while its own zone (named after it) has power."""
    out = []
    for name in LAMPS:
        if name == stuck:
            out.append("S")
        elif name in amber:
            out.append("A")
        elif name == missing:
            out.append("P")
        elif name in config.TIES:
            out.append("G" if name in closed_ties else "R")
        elif name in open_devs:
            out.append("R")
        else:
            out.append("G" if name in live else "K")
    return "".join(out)


def _ohm(r: float) -> str:
    return f"{r:g} ohm"


def frame(lamp: str, lines: list[str], lock: bool = False, wait: bool = False, idle: bool = False) -> dict:
    f = {"lamps": lamp, "lock": int(lock), "wait": int(wait), "idle": int(idle), "lcd": lines}
    if idle:
        f["rs"] = list(config.SLG_RESISTANCES)
    return f


def idle_frame(zones: Zones) -> dict:
    return frame(lamps(live=zones.names), lcd("SELF-HEALING FEEDER", "", "FAULT: new fault", "simulation only"),
                 idle=True)


def incident_frames(zones: Zones, summary: dict, phase: str, r: float,
                    missing_acc: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Frames for one incident: (shown one after another, shown after CLOSE TIES).
    The second list is empty when no tie is used or the fault is not isolated.
    missing_acc: the study's accuracy with each sensor missing (results/metrics.json)."""
    names = set(zones.names)
    bus, pred, true = summary["bus"], summary["predicted_zone"], summary["true_zone"]
    miss, stuck = summary.get("missing"), summary.get("stuck")
    area = set(summary.get("area") or [pred])
    opened = set(summary["opened"])
    upstream = set(summary["upstream"])
    top = next(z for z in area if zones.parent[z] not in area)
    ties = summary["closed_ties"]
    dark0 = {"Sw1"}                                         # after lockout only Sw1 is open
    out = [
        frame(lamps(live=names, missing=miss), lcd(f"FAULT bus {bus} ph {phase}", f"line-ground {_ohm(r)}",
                                                   "fault current flows")),
        frame(lamps(open_devs=dark0, missing=miss), lcd("Sw1 trips and", "LOCKS OUT:", "whole feeder dark"),
              lock=True),
    ]
    if miss:
        acc = (missing_acc or {}).get(miss)          # study: share of all faults right with this sensor missing
        out.append(frame(lamps(open_devs=dark0, missing=miss),
                         lcd(f"Sensor {miss} offline:", "model uses other 9.",
                             *((f"Study, {miss} missing:", f"{acc:.0%} of faults right") if acc is not None else ())),
                         lock=True))
    out.append(frame(lamps(open_devs=dark0, amber={pred}, missing=miss),
                     lcd(f"ML locates zone {pred}", f"confidence {summary['confidence']:.0%}",
                         "from the switch", "readings"), lock=True))
    if stuck:
        out.append(frame(lamps(open_devs=dark0, stuck=stuck),
                         lcd(f"Open {stuck}: STUCK,", "it did not open.", "Back-up: isolate",
                             "the next zone too"), lock=True))
    zl = " ".join(sorted(area))
    out.append(frame(lamps(open_devs=dark0 | opened, stuck=stuck),
                     lcd(f"Isolate {'+'.join(sorted(area))}:", "open " + " ".join(sorted(opened))),
                     lock=True))
    if not summary["fault_isolated"]:
        out.append(frame(lamps(open_devs=dark0 | opened, stuck=stuck),
                         lcd("Wrong zone: fault", f"is in {true}, still", "connected. Stop:", "crew patrols"),
                         lock=True))
        return out, []
    lock = top == "Sw1"
    if not lock:
        out.append(frame(lamps(open_devs=opened, live=upstream, stuck=stuck),
                         lcd("Re-close Sw1:", "power back to " + " ".join(sorted(upstream)))))
    else:
        out.append(frame(lamps(open_devs=opened, live=upstream, stuck=stuck),
                         lcd("Zone Sw1 isolated:", "Sw1 stays open"), lock=True))
    dark = " ".join(summary["unserved"]) or "none"
    islands = names - area - upstream
    if not ties:
        many = len(area) > 1
        text = (lcd("All other zones", "have power. Zone" + ("s" if many else ""),
                    f"{zl} wait{'' if many else 's'} for", "the repair") if not islands else
                lcd("No tie can pick up", "the rest in limits.", f"Dark: {dark}"))
        out.append(frame(lamps(open_devs=opened, live=upstream, stuck=stuck), text, lock=lock))
        return out, []
    kw = sum(zones.kw[z] for z in summary["restored_by_tie"])
    out.append(frame(lamps(open_devs=opened, live=upstream, amber=set(ties), stuck=stuck),
                     lcd("Tie ready: " + " ".join(ties), f"picks up {kw:g} kW", "press CLOSE TIES"),
                     lock=lock, wait=True))
    after = [frame(lamps(open_devs=opened, closed_ties=ties, live=upstream | set(summary["restored_by_tie"]),
                         stuck=stuck),
                   lcd("Closed " + " ".join(ties), f"+{kw:g} kW restored", f"Dark until repair: {dark}"),
                   lock=lock)]
    return out, after


def _flag(v) -> bool | None:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    return None


def parse_command(payload: bytes) -> dict | None:
    """A command from the board, or None. The topic is public: accept only what we know."""
    if len(payload) > 256:
        return None
    try:
        msg = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(msg, dict) or msg.get("cmd") not in COMMANDS:
        return None
    if msg["cmd"] == "fault":
        r = msg.get("r")
        if not isinstance(r, (int, float)) or isinstance(r, bool):
            return None
        match = [x for x in config.SLG_RESISTANCES if abs(x - r) <= 1e-6 * max(1.0, x)]
        sensor, stuck = _flag(msg.get("sensor")), _flag(msg.get("stuck"))
        if not match or sensor is None or stuck is None:
            return None
        return {"cmd": "fault", "r": match[0], "sensor": sensor, "stuck": stuck}
    return {"cmd": msg["cmd"]}
