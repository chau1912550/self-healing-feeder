"""Wokwi control panel: the study drives a simulated ESP32 board over MQTT.

The board (board/wokwi/) has one RGB lamp per switch, a lockout lamp, a yellow HIF ALARM lamp,
a 20x4 LCD, four buttons (FAULT, CLOSE TIES, RESET, HIF ARC), a knob that picks the fault
resistance, and two failure-injection slide switches (SENSOR OFFLINE, SWITCH STUCK). This module
turns one simulated incident (scada.simulate_event: OpenDSS fault, ML zone, restoration plan) into
the frames the board shows, and checks the commands and Tier-1 HIF alerts the board sends.
Simulation only: the board is a Wokwi simulation using a public demo MQTT broker, not field
equipment.

Frame (study -> board & Monitor, JSON on shf/<PANEL_ID>/state):
  lamps  one letter per lamp in LAMPS order: G closed with power, K closed without power,
         R open, A amber blink (located zone, or a tie waiting for the operator),
         P purple (that switch's sensor sends nothing), S red blink (switch stuck, did not open)
  lock   1 = lockout lamp on (Sw1 locked out)
  wait   1 = waiting for CLOSE TIES
  idle   1 = ready for a new fault (the board writes the knob's resistance on LCD line 2)
  lcd    four lines of at most 20 ASCII characters
  rs     (idle frames) the fault resistances the knob steps through, ohms
  flow   power-supply metadata for Monitor animation:
         {"upstream": [...], "restored_by_tie": [...], "ties": [...]}
  hif    (optional, present on Tier-1 HIF incidents) validated Tier-1 C99 HIF alert payload:
         {"p_hif", "alarm", "persist", "infer_us", "mode", "r"}
Command (board -> study, JSON on shf/<PANEL_ID>/cmd):
  {"cmd": "fault", "r": <ohms>, "sensor": 0|1, "stuck": 0|1},
  {"cmd": "ties"}, {"cmd": "reset"}, {"cmd": "hello"}.
HIF alert (board -> study, JSON on shf/<PANEL_ID>/hif):
  {"p_hif": [0..1], "alarm": 0|1, "persist": 0..10, "infer_us": >=0,
   "mode": "arc"|"normal", "r": <SLG_RESISTANCES>|null}.
"""
from __future__ import annotations

import json
import math
import textwrap

from . import config
from .topology import Zones

LAMPS = list(config.SECTIONALIZERS) + list(config.TIES)   # order of the lamps on the board
TOPIC_STATE = f"shf/{config.PANEL_ID}/state"
TOPIC_CMD = f"shf/{config.PANEL_ID}/cmd"
TOPIC_HIF = f"shf/{config.PANEL_ID}/hif"
COMMANDS = ("fault", "ties", "reset", "hello")
HIF_MODES = ("arc", "normal")
HIF_PERSIST_MAX = 10
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


def _flow(upstream=(), restored_by_tie=(), ties=()) -> dict:
    return {
        "upstream": sorted(upstream),
        "restored_by_tie": sorted(restored_by_tie),
        "ties": list(ties),
    }


def _hif_meta(hif: dict, r: float) -> dict:
    infer = hif.get("infer_us", 0)
    return {
        "p_hif": round(float(hif.get("p_hif", 0.0)), 6),
        "alarm": int(hif.get("alarm", 0)),
        "persist": int(hif.get("persist", 0)),
        "infer_us": infer if isinstance(infer, int) and not isinstance(infer, bool) else round(float(infer), 4),
        "mode": str(hif.get("mode", "arc")),
        "r": hif.get("r", r),
    }


def frame(lamp: str, lines: list[str], lock: bool = False, wait: bool = False, idle: bool = False,
          hif: dict | None = None, flow: dict | None = None) -> dict:
    f: dict = {"lamps": lamp, "lock": int(lock), "wait": int(wait), "idle": int(idle), "lcd": lines}
    if idle:
        f["rs"] = list(config.SLG_RESISTANCES)
    if hif is not None:
        f["hif"] = hif
    if flow is not None:
        f["flow"] = flow
    return f


def idle_frame(zones: Zones) -> dict:
    return frame(lamps(live=zones.names), lcd("SELF-HEALING FEEDER", "", "FAULT: new fault", "simulation only"),
                 idle=True, flow=_flow(upstream=zones.names))


def incident_frames(zones: Zones, summary: dict, phase: str, r: float,
                    missing_acc: dict | None = None,
                    hif: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Frames for one incident: (shown one after another, shown after CLOSE TIES).
    The second list is empty when no tie is used or the fault is not isolated.
    missing_acc: the study's accuracy with each sensor missing (results/metrics.json).
    hif: optional Tier-1 HIF alert payload; when present, prepends a Tier-1 HIF LCD frame and
    attaches `hif` to every state frame of the incident."""
    names = set(zones.names)
    bus, pred, true = summary["bus"], summary["predicted_zone"], summary["true_zone"]
    miss, stuck = summary.get("missing"), summary.get("stuck")
    area = set(summary.get("area") or [pred])
    opened = set(summary["opened"])
    upstream = set(summary["upstream"])
    top = next(z for z in area if zones.parent[z] not in area)
    ties = summary["closed_ties"]
    dark0 = {"Sw1"}                                         # after lockout only Sw1 is open
    hif_meta = _hif_meta(hif, r) if hif is not None else None
    flow_all = _flow(upstream=names)
    flow_dark = _flow()
    flow_up = _flow(upstream=upstream)

    out: list[dict] = []
    if hif_meta is not None:
        hdr = "TIER-1 HIF ALARM" if hif_meta["alarm"] else "TIER-1 HIF CHECK"
        out.append(frame(
            lamps(live=names, missing=miss),
            lcd(hdr,
                f"p_hif={hif_meta['p_hif']:.4f} P={hif_meta['persist']}",
                f"mode={hif_meta['mode']} {hif_meta['infer_us']:g}us",
                f"Edge->FLISR {_ohm(r)}"),
            hif=hif_meta, flow=flow_all,
        ))
    out += [
        frame(lamps(live=names, missing=miss), lcd(f"FAULT bus {bus} ph {phase}", f"line-ground {_ohm(r)}",
                                                   "fault current flows"),
              hif=hif_meta, flow=flow_all),
        frame(lamps(open_devs=dark0, missing=miss), lcd("Sw1 trips and", "LOCKS OUT:", "whole feeder dark"),
              lock=True, hif=hif_meta, flow=flow_dark),
    ]
    if miss:
        acc = (missing_acc or {}).get(miss)          # study: share of all faults right with this sensor missing
        out.append(frame(lamps(open_devs=dark0, missing=miss),
                         lcd(f"Sensor {miss} offline:", "model uses other 9.",
                             *((f"Study, {miss} missing:", f"{acc:.0%} of faults right") if acc is not None else ())),
                         lock=True, hif=hif_meta, flow=flow_dark))
    out.append(frame(lamps(open_devs=dark0, amber={pred}, missing=miss),
                     lcd(f"ML locates zone {pred}", f"confidence {summary['confidence']:.0%}",
                         "from the switch", "readings"),
                     lock=True, hif=hif_meta, flow=flow_dark))
    if stuck:
        out.append(frame(lamps(open_devs=dark0, stuck=stuck),
                         lcd(f"Open {stuck}: STUCK,", "it did not open.", "Back-up: isolate",
                             "the next zone too"),
                         lock=True, hif=hif_meta, flow=flow_dark))
    zl = " ".join(sorted(area))
    out.append(frame(lamps(open_devs=dark0 | opened, stuck=stuck),
                     lcd(f"Isolate {'+'.join(sorted(area))}:", "open " + " ".join(sorted(opened))),
                     lock=True, hif=hif_meta, flow=flow_dark))
    if not summary["fault_isolated"]:
        out.append(frame(lamps(open_devs=dark0 | opened, stuck=stuck),
                         lcd("Wrong zone: fault", f"is in {true}, still", "connected. Stop:", "crew patrols"),
                         lock=True, hif=hif_meta, flow=flow_dark))
        return out, []
    lock = top == "Sw1"
    if not lock:
        out.append(frame(lamps(open_devs=opened, live=upstream, stuck=stuck),
                         lcd("Re-close Sw1:", "power back to " + " ".join(sorted(upstream))),
                         hif=hif_meta, flow=flow_up))
    else:
        out.append(frame(lamps(open_devs=opened, live=upstream, stuck=stuck),
                         lcd("Zone Sw1 isolated:", "Sw1 stays open"),
                         lock=True, hif=hif_meta, flow=flow_up))
    dark = " ".join(summary["unserved"]) or "none"
    islands = names - area - upstream
    if not ties:
        many = len(area) > 1
        text = (lcd("All other zones", "have power. Zone" + ("s" if many else ""),
                    f"{zl} wait{'' if many else 's'} for", "the repair") if not islands else
                lcd("No tie can pick up", "the rest in limits.", f"Dark: {dark}"))
        out.append(frame(lamps(open_devs=opened, live=upstream, stuck=stuck), text,
                         lock=lock, hif=hif_meta, flow=flow_up))
        return out, []
    kw = sum(zones.kw[z] for z in summary["restored_by_tie"])
    out.append(frame(lamps(open_devs=opened, live=upstream, amber=set(ties), stuck=stuck),
                     lcd("Tie ready: " + " ".join(ties), f"picks up {kw:g} kW", "press CLOSE TIES"),
                     lock=lock, wait=True, hif=hif_meta, flow=flow_up))
    after = [frame(lamps(open_devs=opened, closed_ties=ties, live=upstream | set(summary["restored_by_tie"]),
                         stuck=stuck),
                   lcd("Closed " + " ".join(ties), f"+{kw:g} kW restored", f"Dark until repair: {dark}"),
                   lock=lock, hif=hif_meta,
                   flow=_flow(upstream=upstream, restored_by_tie=summary["restored_by_tie"], ties=ties))]
    return out, after


def _flag(v) -> bool | None:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    return None


def _match_slg_r(r) -> float | None:
    if not isinstance(r, (int, float)) or isinstance(r, bool) or not math.isfinite(r):
        return None
    match = [x for x in config.SLG_RESISTANCES if abs(x - r) <= 1e-6 * max(1.0, x)]
    return match[0] if match else None


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
        r = _match_slg_r(msg.get("r"))
        sensor, stuck = _flag(msg.get("sensor")), _flag(msg.get("stuck"))
        if r is None or sensor is None or stuck is None:
            return None
        return {"cmd": "fault", "r": r, "sensor": sensor, "stuck": stuck}
    return {"cmd": msg["cmd"]}


def parse_hif_alert(payload: bytes | bytearray | str) -> dict | None:
    """Validate a Tier-1 HIF alert from shf/<PANEL_ID>/hif, or return None.

    The topic is public, so every field is checked strictly:
      p_hif    finite number in [0, 1]
      alarm    int in {0, 1} (not bool)
      persist  int in 0..10 (not bool)
      infer_us finite number >= 0 (not bool)
      mode     "arc" or "normal"
      r        value in config.SLG_RESISTANCES or null
    """
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    else:
        return None
    if len(raw) > 256:
        return None
    try:
        msg = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(msg, dict):
        return None

    p_hif = msg.get("p_hif")
    if not isinstance(p_hif, (int, float)) or isinstance(p_hif, bool) or not math.isfinite(p_hif):
        return None
    if not (0.0 <= float(p_hif) <= 1.0):
        return None

    alarm = msg.get("alarm")
    if not isinstance(alarm, int) or isinstance(alarm, bool) or alarm not in (0, 1):
        return None

    persist = msg.get("persist")
    if not isinstance(persist, int) or isinstance(persist, bool) or not (0 <= persist <= HIF_PERSIST_MAX):
        return None

    infer_us = msg.get("infer_us")
    if not isinstance(infer_us, (int, float)) or isinstance(infer_us, bool) or not math.isfinite(infer_us):
        return None
    if float(infer_us) < 0.0:
        return None

    mode = msg.get("mode")
    if not isinstance(mode, str) or mode not in HIF_MODES:
        return None

    r_raw = msg.get("r")
    if r_raw is None:
        r_val = None
    else:
        r_val = _match_slg_r(r_raw)
        if r_val is None:
            return None

    return {
        "p_hif": float(p_hif),
        "alarm": alarm,
        "persist": persist,
        "infer_us": infer_us if isinstance(infer_us, int) else float(infer_us),
        "mode": mode,
        "r": r_val,
    }
