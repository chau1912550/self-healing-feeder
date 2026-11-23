"""The Wokwi control panel: frames, commands, and that the board files match the study's settings.
No MQTT broker or Wokwi needed."""
import json
import re

import pytest

from shf import config, feeder, panel, topology

BOARD = config.ROOT / "board" / "wokwi"


@pytest.fixture(scope="module")
def zones():
    feeder.load_feeder()
    return topology.find_zones()


def _summary(zones, pred, true=None, ties=(), restored=(), unserved=()):
    from shf import restoration
    islands = {z for isl in restoration.islands_after_isolation(zones, pred) for z in isl}
    return {"bus": "60", "predicted_zone": pred, "true_zone": true or pred, "confidence": 0.9,
            "fault_isolated": (true or pred) == pred, "opened": [pred] + zones.children(pred),
            "closed_ties": list(ties), "restored_by_tie": list(restored), "unserved": list(unserved),
            "area": [pred], "upstream": sorted(set(zones.names) - {pred} - islands)}


def test_lamps_follow_the_switch_states():
    assert len(panel.LAMPS) == len(config.SECTIONALIZERS) + len(config.TIES) == 12
    normal = panel.lamps(live=config.SECTIONALIZERS)
    assert normal == "G" * len(config.SECTIONALIZERS) + "R" * len(config.TIES)   # ties normally open
    dark = panel.lamps(open_devs={"Sw1"})
    assert dark[0] == "R" and set(dark[1:len(config.SECTIONALIZERS)]) == {"K"}
    assert panel.lamps(closed_ties={"Sw7"}, amber={"Sw9"})[-2:] == "GA"


def test_lcd_is_four_ascii_lines_of_twenty():
    lines = panel.lcd("a" * 45, "Điện áp")
    assert len(lines) == 4 and all(len(x) <= 20 for x in lines)
    assert all(x.isascii() for x in lines)


def test_incident_with_a_tie(zones):
    s = _summary(zones, "Sw2", ties=["Sw7"], restored=["Sw4"], unserved=["L61"])
    now, after = panel.incident_frames(zones, s, "1", 25)
    assert [f["lock"] for f in now[:4]] == [0, 1, 1, 1]          # fault, lockout, located, isolated
    assert "A" in now[2]["lamps"] and now[-1]["wait"] == 1      # waits for CLOSE TIES
    i = panel.LAMPS.index
    assert now[3]["lamps"][i("Sw2")] == "R" and now[4]["lamps"][i("Sw1")] == "G"   # re-closed
    assert len(after) == 1 and after[0]["lamps"][i("Sw7")] == "G" and after[0]["wait"] == 0
    kw = sum(zones.kw[z] for z in s["restored_by_tie"])
    assert f"{kw:g} kW" in " ".join(after[0]["lcd"])           # the number comes from the study


def test_wrong_zone_stops_before_reclosing(zones):
    now, after = panel.incident_frames(zones, _summary(zones, "Sw1", true="Sw2"), "1", 400)
    assert after == [] and now[-1]["lock"] == 1 and "Sw2" in " ".join(now[-1]["lcd"])
    assert all(f["lamps"][0] in "RA" for f in now[1:])           # Sw1 never re-closes onto the fault


def test_events_can_follow_each_other(zones):
    """The panel asks for one fault after another; the OpenDSS fault element must be reused."""
    import pickle
    from shf import scada
    path = config.MODELS / "model.pkl"
    if not path.exists():
        pytest.skip("run python run.py first")
    with open(path, "rb") as f:
        bundle = pickle.load(f)
    for bus in ("94", "60"):
        _, s = scada.simulate_event(zones, bundle, bus, f"phases=1 bus1={bus}.1 bus2={bus}.0 r=25")
        assert s["true_zone"] == zones.bus_zone[bus] and set(s["opened"]) >= {s["predicted_zone"]}


@pytest.mark.parametrize("payload, ok", [
    (b'{"cmd":"fault","r":25}', {"cmd": "fault", "r": 25, "sensor": False, "stuck": False}),
    (b'{"cmd":"fault","r":0.01,"sensor":1,"stuck":0}', {"cmd": "fault", "r": 0.01, "sensor": True, "stuck": False}),
    (b'{"cmd":"fault","r":25,"stuck":2}', None),
    (b'{"cmd":"fault","r":25,"sensor":"yes"}', None),
    (b'{"cmd":"fault","r":33}', None),            # not one of the study's resistances
    (b'{"cmd":"fault","r":true}', None),
    (b'{"cmd":"ties"}', {"cmd": "ties"}),
    (b'{"cmd":"rm -rf"}', None),
    (b'not json', None),
    (b'[1,2]', None),
    (b'{"cmd":"reset","pad":"' + b"x" * 300 + b'"}', None),
])
def test_only_known_commands_are_accepted(payload, ok):
    assert panel.parse_command(payload) == ok


def test_board_files_match_the_study():
    sketch = (BOARD / "sketch.ino").read_text(encoding="utf-8")
    assert f'#define PANEL_ID "{config.PANEL_ID}"' in sketch
    assert f'#define BROKER "{config.PANEL_BROKER[0]}"' in sketch
    assert f"#define N_LAMPS {len(panel.LAMPS)}" in sketch
    assert " ".join(panel.LAMPS) in sketch                         # the lamp order is written down
    for lib in ("PubSubClient", "ArduinoJson", "Adafruit NeoPixel", "LiquidCrystal I2C"):
        assert lib in (BOARD / "libraries.txt").read_text(encoding="utf-8")
    d = json.loads((BOARD / "diagram.json").read_text(encoding="utf-8"))
    ids = {p["id"]: p for p in d["parts"]}
    conns = {(a, b) for a, b, *_ in d["connections"]}
    pin = re.search(r"PIN_LAMPS = (\d+)", sketch).group(1)
    nxt = f"esp:{pin}"
    for i, name in enumerate(panel.LAMPS):                        # one chain, in LAMPS order
        assert (nxt, f"lamp{i}:DIN") in conns and ids[f"label{i}"]["attrs"]["text"].startswith(name + " ")
        nxt = f"lamp{i}:DOUT"
    for key, pin in (("sensor", re.search(r"PIN_SENSOR = (\d+)", sketch).group(1)),
                     ("stuck", re.search(r"PIN_STUCK = (\d+)", sketch).group(1))):
        assert (f"sw_{key}:2", f"esp:{pin}") in conns                 # failure switches wired as coded
    for cmd, pin in zip(("fault", "ties", "reset"), re.search(r"PIN_BTN\[3\] = \{(\d+), (\d+), (\d+)\}",
                                                               sketch).groups()):
        assert (f"btn_{cmd}:1.l", f"esp:{pin}") in conns


def test_stuck_switch_widens_the_isolated_area(zones):
    """Failure injection: the device feeding the zone does not open, so the parent zone is
    isolated too. With no stuck device the plan is the study's plan."""
    from shf import restoration
    zf = "L61"
    normal = restoration.plan_restoration(zones, zf)
    restoration.reset(zones)
    stuck = restoration.first_device(zones, zf)
    plan = restoration.plan_restoration(zones, zf, stuck)
    restoration.reset(zones)
    parent = zones.parent[zf]
    assert normal.area == {zf} and stuck == zf
    assert plan.area == {zf, parent} and plan.stuck == zf and zf not in plan.opened and parent in plan.opened
    assert plan.checks[-1]["ok"] and plan.checks[-1]["radial"]          # still within limits and radial
    assert not (plan.energized & plan.area)                             # nothing isolated is re-energized
    assert len(plan.energized) <= len(normal.energized)                 # a stuck switch never helps
    assert restoration.first_device(zones, "Sw1") in zones.children("Sw1")   # Sw1 itself is already open


def test_failure_frames(zones):
    s = _summary(zones, "Sw2", ties=["Sw7"], restored=["Sw4"], unserved=["L61"])
    s.update(missing="Sw2")
    now, _ = panel.incident_frames(zones, s, "1", 25, {"Sw2": 0.88})
    i = panel.LAMPS.index
    assert now[0]["lamps"][i("Sw2")] == "P" and "88%" in " ".join(now[2]["lcd"])
    s = _summary(zones, "L61")
    s.update(stuck="L61", area=["L61", "Sw2"], opened=["Sw2", "Sw4"],
             upstream=sorted(set(zones.names) - {"Sw2", "L61", "Sw4", "L68", "Sw5", "L77"}))
    now, _ = panel.incident_frames(zones, s, "1", 25)
    stuck_frame = next(f for f in now if "STUCK" in " ".join(f["lcd"]))
    assert stuck_frame["lamps"][i("L61")] == "S" and all(f["lamps"][i("L61")] == "S" for f in now[now.index(stuck_frame):])


def test_demo_frames_in_the_sketch_are_valid():
    """The board replays these when no study answers (shared link); they come from scripts/wokwi_demo.py."""
    sketch = (BOARD / "sketch.ino").read_text(encoding="utf-8")
    block = sketch[sketch.index("// BEGIN DEMO"):sketch.index("// END DEMO")]
    frames = [json.loads(bytes(s, "utf-8").decode("unicode_escape")) for s in re.findall(r'"((?:[^"\\]|\\.)*)"', block)
              if s.startswith("{")]
    assert len(frames) >= 10 and all(len(f["lamps"]) == len(panel.LAMPS) and len(f["lcd"]) == 4 for f in frames)
    for case in ("NORMAL", "SENSOR", "STUCK"):
        assert f"DEMO_{case}[]" in block and f"DEMO_{case}_N" in block
    assert any("STUCK" in " ".join(f["lcd"]) for f in frames) and any("offline" in " ".join(f["lcd"]) for f in frames)
