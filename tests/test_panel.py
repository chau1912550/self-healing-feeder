"""The Wokwi control panel: frames, commands, Tier-1 C99 HIF parity, and board/UI checks.
No MQTT broker, browser, or Wokwi needed."""
import hashlib
import json
import re

import pytest

from shf import config, feeder, panel, topology

BOARD = config.ROOT / "board" / "wokwi"
HIF_FW = config.ROOT / "hif_sensor" / "firmware"
HIF_RESULTS = config.ROOT / "hif_sensor" / "results"
C99_MIRROR_FILES = ("hif_dsp.h", "hif_dsp.c", "hif_infer.h", "hif_infer.c", "hif_model.h")


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
    for case in ("NORMAL", "SENSOR", "STUCK", "HIF"):
        assert f"DEMO_{case}[]" in block and f"DEMO_{case}_N" in block
    assert any("STUCK" in " ".join(f["lcd"]) for f in frames) and any("offline" in " ".join(f["lcd"]) for f in frames)


def test_topic_hif_and_parse_hif_alert_validation():
    assert panel.TOPIC_HIF == f"shf/{config.PANEL_ID}/hif"

    valid_cases = [
        (
            b'{"p_hif":0.99809,"alarm":1,"persist":3,"infer_us":0.5399,"mode":"arc","r":400}',
            {"p_hif": 0.99809, "alarm": 1, "persist": 3, "infer_us": 0.5399, "mode": "arc", "r": 400},
        ),
        (
            bytearray(b'{"p_hif":0,"alarm":0,"persist":0,"infer_us":0,"mode":"normal","r":null}'),
            {"p_hif": 0.0, "alarm": 0, "persist": 0, "infer_us": 0, "mode": "normal", "r": None},
        ),
        (
            '{"p_hif":1.0,"alarm":1,"persist":10,"infer_us":12500,"mode":"arc","r":0.01}',
            {"p_hif": 1.0, "alarm": 1, "persist": 10, "infer_us": 12500, "mode": "arc", "r": 0.01},
        ),
        (
            b'{"p_hif":0.5,"alarm":0,"persist":1,"infer_us":12.5,"mode":"normal"}',
            {"p_hif": 0.5, "alarm": 0, "persist": 1, "infer_us": 12.5, "mode": "normal", "r": None},
        ),
    ]
    for payload, expected in valid_cases:
        assert panel.parse_hif_alert(payload) == expected

    invalid_cases = [
        None,
        123,
        b"\xff\xfe",
        b"not json",
        b"[1, 2, 3]",
        b"{}",
        # payload too long (> 256 bytes)
        (b'{"p_hif":0.99,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":400,"pad":"'
         + b"x" * 220 + b'"}'),
        # wrong field types (including bool where int/float expected)
        b'{"p_hif":true,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":"0.99","alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":true,"persist":3,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":1.0,"persist":3,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":false,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":3.0,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":3,"infer_us":true,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":3,"infer_us":"12","mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":3,"infer_us":1,"mode":1,"r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":true}',
        b'{"p_hif":0.99,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":"400"}',
        # out-of-bounds values
        b'{"p_hif":-0.01,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":1.01,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":NaN,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":Infinity,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":2,"persist":3,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":-1,"persist":3,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":-1,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":11,"infer_us":1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":3,"infer_us":-0.1,"mode":"arc","r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":3,"infer_us":1,"mode":"hif","r":400}',
        b'{"p_hif":0.99,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":33}',
        # unknown / misplaced field names
        b'{"unknown":1}',
        b'{"prob":0.99,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":400}',
    ]
    for bad in invalid_cases:
        assert panel.parse_hif_alert(bad) is None, f"expected None for {bad!r}"

    # An unknown extra key appended to an otherwise valid 6-key payload must never leak into output
    extra_payload = b'{"p_hif":0.99,"alarm":1,"persist":3,"infer_us":1,"mode":"arc","r":400,"evil":"x"}'
    parsed = panel.parse_hif_alert(extra_payload)
    assert parsed is None or (
        "evil" not in parsed
        and set(parsed.keys()) == {"p_hif", "alarm", "persist", "infer_us", "mode", "r"}
    )


def test_incident_frames_with_hif_and_flow(zones):
    idle = panel.idle_frame(zones)
    assert idle["flow"] == {"upstream": sorted(zones.names), "restored_by_tie": [], "ties": []}

    s = _summary(zones, "Sw2", ties=["Sw7"], restored=["Sw4"], unserved=["L61"])
    now_plain, after_plain = panel.incident_frames(zones, s, "1", 400)
    assert all("hif" not in f and "flow" in f for f in (*now_plain, *after_plain))

    alert = {"p_hif": 0.99809, "alarm": 1, "persist": 3, "infer_us": 0.5399, "mode": "arc", "r": 400}
    now, after = panel.incident_frames(zones, s, "1", 400, hif=alert)
    assert len(now) == len(now_plain) + 1
    assert len(after) == len(after_plain) == 1

    # First frame is the Tier-1 HIF LCD banner
    first_lcd = " ".join(now[0]["lcd"])
    assert "TIER-1 HIF ALARM" in first_lcd
    assert "p_hif=0.9981" in first_lcd and "P=3" in first_lcd and "400 ohm" in first_lcd
    assert now[0]["flow"] == {"upstream": sorted(zones.names), "restored_by_tie": [], "ties": []}

    # Every frame carries normalized Tier-1 hif metadata and flow metadata
    for f in (*now, *after):
        assert f["hif"] == alert
        assert set(f["flow"].keys()) == {"upstream", "restored_by_tie", "ties"}

    # Lockout -> dark flow; re-close -> upstream only; tie close -> upstream + restored_by_tie + ties
    assert now[2]["lock"] == 1 and now[2]["flow"] == {"upstream": [], "restored_by_tie": [], "ties": []}
    assert now[-1]["wait"] == 1 and now[-1]["flow"] == {
        "upstream": sorted(s["upstream"]), "restored_by_tie": [], "ties": [],
    }
    assert after[0]["flow"] == {
        "upstream": sorted(s["upstream"]),
        "restored_by_tie": sorted(s["restored_by_tie"]),
        "ties": ["Sw7"],
    }

    # Non-alarm Tier-1 check uses CHECK header
    now_chk, _ = panel.incident_frames(zones, s, "1", 400, hif={**alert, "alarm": 0, "mode": "normal"})
    assert "TIER-1 HIF CHECK" in " ".join(now_chk[0]["lcd"])


def test_wokwi_c99_firmware_matches_hif_sensor_byte_for_byte():
    """The 5 C99 Tier-1 source/header files in board/wokwi/ must be 100% byte-identical to hif_sensor/firmware/."""
    for name in C99_MIRROR_FILES:
        src = HIF_FW / name
        dst = BOARD / name
        assert src.exists(), f"missing source {src}"
        assert dst.exists(), f"missing Wokwi mirror {dst}"
        src_b, dst_b = src.read_bytes(), dst.read_bytes()
        assert dst_b == src_b, f"byte mismatch between {dst} and {src}"
        assert hashlib.sha256(dst_b).hexdigest() == hashlib.sha256(src_b).hexdigest()

    # Cross-check verified GCC parity artifact against embedded hif_model.h & sketch.ino
    verify = json.loads((HIF_RESULTS / "c_firmware_verify.json").read_text(encoding="utf-8"))
    p0 = verify["phase0_official_6_vectors"]
    assert p0["parity_pass"] is True and p0["compiled"] is True and p0["exit_code"] == 0
    model_h = (BOARD / "hif_model.h").read_text(encoding="utf-8")
    assert f"#define HIF_PERSIST {p0['persist_windows']}" in model_h
    assert f"{p0['threshold']:.6f}f" in model_h

    arc_h = (BOARD / "hif_arc_samples.h").read_text(encoding="utf-8")
    for sym in ("HIF_DEMO_SEED", "hif_gen_cycles", "HIF_GAIN_V_PER_A", "HIF_VREF_V"):
        assert sym in arc_h

    sketch = (BOARD / "sketch.ino").read_text(encoding="utf-8")
    for inc in ('#include "hif_dsp.h"', '#include "hif_infer.h"', '#include "hif_arc_samples.h"'):
        assert inc in sketch
    stack = int(re.search(r"HIF_TASK_STACK\s*=\s*(\d+)", sketch).group(1))
    assert stack >= 24576


def test_board_hif_gpio_and_legacy_pins_intact():
    """New HIF ALARM LED + HIF ARC button match between diagram.json and sketch.ino without breaking legacy wiring."""
    sketch = (BOARD / "sketch.ino").read_text(encoding="utf-8")
    d = json.loads((BOARD / "diagram.json").read_text(encoding="utf-8"))
    parts = {p["id"]: p for p in d["parts"]}
    conns = {(a, b) for a, b, *_ in d["connections"]}

    # Legacy 12 lamps + LOCKOUT LED + I2C LCD + knob + 3 buttons + 2 failure switches remain intact
    pin_lamps = re.search(r"PIN_LAMPS = (\d+)", sketch).group(1)
    pin_lock = re.search(r"PIN_LOCK = (\d+)", sketch).group(1)
    pin_knob = re.search(r"PIN_KNOB = (\d+)", sketch).group(1)
    pin_sensor = re.search(r"PIN_SENSOR = (\d+)", sketch).group(1)
    pin_stuck = re.search(r"PIN_STUCK = (\d+)", sketch).group(1)
    btn_pins = re.search(r"PIN_BTN\[3\] = \{(\d+), (\d+), (\d+)\}", sketch).groups()
    assert len([p for p in parts if re.fullmatch(r"lamp\d+", p)]) == len(panel.LAMPS) == 12
    assert (f"esp:{pin_lock}", "rlock:2") in conns and ("rlock:1", "lock:A") in conns
    assert ("lcd:SDA", "esp:21") in conns and ("lcd:SCL", "esp:22") in conns
    assert ("knob:SIG", f"esp:{pin_knob}") in conns
    assert (f"sw_sensor:2", f"esp:{pin_sensor}") in conns and (f"sw_stuck:2", f"esp:{pin_stuck}") in conns
    for cmd, p in zip(("fault", "ties", "reset"), btn_pins):
        assert (f"btn_{cmd}:1.l", f"esp:{p}") in conns

    # New Tier-1 HIF ALARM LED (yellow + 220 ohm resistor) & HIF ARC pushbutton
    pin_hif_led = re.search(r"PIN_HIF_LED = (\d+)", sketch).group(1)
    pin_btn_hif = re.search(r"PIN_BTN_HIF = (\d+)", sketch).group(1)
    assert parts["hif_led"]["type"] == "wokwi-led" and parts["hif_led"]["attrs"]["color"] == "yellow"
    assert parts["rhif"]["type"] == "wokwi-resistor" and parts["rhif"]["attrs"]["value"] == "220"
    assert (f"esp:{pin_hif_led}", "rhif:2") in conns
    assert ("rhif:1", "hif_led:A") in conns and ("hif_led:C", "esp:GND.1") in conns

    assert parts["btn_hif"]["type"] == "wokwi-pushbutton" and parts["btn_hif"]["attrs"]["color"] == "yellow"
    assert (f"btn_hif:1.l", f"esp:{pin_btn_hif}") in conns and ("btn_hif:2.l", "esp:GND.1") in conns

    # All assigned ESP32 GPIOs are distinct (no pin clash)
    used_pins = [pin_lamps, pin_lock, pin_knob, pin_sensor, pin_stuck, *btn_pins, pin_hif_led, pin_btn_hif, "21", "22"]
    assert len(used_pins) == len(set(used_pins)), f"duplicate GPIO pins: {used_pins}"

    # Sketch wires pinMode and TOPIC_HIF consistently with shf/panel.py
    assert "pinMode(PIN_HIF_LED, OUTPUT);" in sketch
    assert "pinMode(PIN_BTN_HIF, INPUT_PULLUP);" in sketch
    assert 'const char* TOPIC_HIF = "shf/" PANEL_ID "/hif";' in sketch


def test_demo_hif_block_is_valid():
    """DEMO_HIF and DEMO_HIF_TIES in sketch.ino match their declared lengths and panel frame schema."""
    sketch = (BOARD / "sketch.ino").read_text(encoding="utf-8")
    block = sketch[sketch.index("// BEGIN DEMO"):sketch.index("// END DEMO")]

    def _extract_array(name: str) -> list[dict]:
        m = re.search(rf"const char\* {name}\[\] = \{{(.+?)\}};", block, re.S)
        assert m, f"missing {name}[]"
        return [json.loads(bytes(s, "utf-8").decode("unicode_escape"))
                for s in re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))]

    hif_frames = _extract_array("DEMO_HIF")
    tie_frames = _extract_array("DEMO_HIF_TIES")
    n_hif = int(re.search(r"DEMO_HIF_N = (\d+)", block).group(1))
    n_ties = int(re.search(r"DEMO_HIF_TIES_N = (\d+)", block).group(1))
    assert len(hif_frames) == n_hif >= 5
    assert len(tie_frames) == n_ties >= 1

    valid_codes = set("GKRAPS")
    for f in (*hif_frames, *tie_frames):
        assert len(f["lamps"]) == len(panel.LAMPS) and set(f["lamps"]) <= valid_codes
        assert len(f["lcd"]) == 4 and all(line.isascii() and len(line) <= 20 for line in f["lcd"])
        assert f["lock"] in (0, 1) and f["wait"] in (0, 1) and f["idle"] in (0, 1)

    assert "400 ohm" in " ".join(hif_frames[0]["lcd"])
    assert hif_frames[-1]["wait"] == 1
    assert tie_frames[-1]["wait"] == 0 and "restored" in " ".join(tie_frames[-1]["lcd"]).lower()


def test_monitor_and_report_two_tier_demo_markup():
    """Static check: Monitor and report expose 10s demo, reversed flow, optional WSS MQTT, and honest simulation labels."""
    monitor_html = (config.ROOT / "docs" / "monitor" / "index.html").read_text(encoding="utf-8")
    for marker in (
        'id="login-demo-btn"',
        'id="demo-10s"',
        "10s Two-Tier Demo",
        "startTwoTierDemo",
        "computeFlow",
        "renderFlow",
        "flow-fwd",
        "flow-rev",
        "Reversed back-feed via tie",
        "Dòng cấp ngược qua dao liên lạc",
        "prefers-reduced-motion",
        'id="mqtt-toggle"',
        "wss://broker.hivemq.com:8884/mqtt",
        f"shf/{config.PANEL_ID}/hif",
        f"shf/{config.PANEL_ID}/state",
        "class MiniMqttWs",
        "validateHifPayload",
        "validateStatePayload",
        "not field hardware",
        "không phải phần cứng",
    ):
        assert marker in monitor_html, f"missing {marker!r} in docs/monitor/index.html"

    report_html = (config.ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    for marker in (
        'id="m3d-hif-demo"',
        'id="m3d-hif-hud"',
        '"hif_demo"',
        "flowFwd",
        "flowRev",
        "updateFlowPulses",
        "reversed back-feed",
        "dòng đổi hướng",
        "monitor/",
        "simulation only",
        "mô phỏng",
    ):
        assert marker in report_html, f"missing {marker!r} in docs/index.html"
