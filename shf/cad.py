"""One-line diagram of the studied feeder as a DXF drawing, for AutoCAD.

Everything is drawn from the study's own results (results/feeder_geometry.json and
results/zones.csv), so bus names, zones, switches and loads match the report exactly.
Coordinates are the IEEE 123-bus plotting coordinates (feet, not to scale geographically).

    python scripts/export_oneline_dxf.py        # -> cad/feeder_oneline.dxf

Model space holds the feeder: one layer per switching zone (in the report's zone colours),
line weight by phase count (3-phase heavy, 1-phase light), underground cable dashed, and the
switching devices as blocks with a NAME attribute. Layout "A3 ONE-LINE" is an A3 landscape
sheet with a viewport and a title block, ready for Plot -> DWG To PDF.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path

import ezdxf
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment

from . import config

OUT = config.ROOT / "cad" / "feeder_oneline.dxf"
INPUTS = [config.RESULTS / "feeder_geometry.json", config.RESULTS / "zones.csv"]
LW = {3: 50, 2: 35, 1: 18}           # line weight (1/100 mm) by number of phases
GAP = 34                              # line gap left around a device symbol (feet)
TEXT_STYLE = "SHF"
ADJ = (420.0, 0.0)                    # offset from bus 450 to the adjacent-feeder source (off the IEEE map)
# label tidying (the "drafting" step): positions that would otherwise sit on another label
TIE_LABEL = {"Sw8": ((-30, 0), TextEntityAlignment.MIDDLE_RIGHT),
             "Sw9": ((0, -32), TextEntityAlignment.TOP_CENTER)}
REG_OFFSET = {"Reg 4": (60, -70)}
ZONE_LABEL_SHIFT = {"L61": (160, 0), "Sw3": (-60, 0)}

LAYERS = {  # name: (ACI colour, line weight, description)
    "LINE-SUBSTATION": (7, 50, "substation exit"),
    "DEV-RECLOSER": (1, 35, "feeder-head recloser"),
    "DEV-SWITCH": (7, 35, "sectionalizing switches, normally closed"),
    "DEV-TIE": (1, 25, "tie switches, normally open"),
    "DEV-REG": (4, 25, "voltage regulators"),
    "DEV-CAP": (5, 25, "capacitor banks"),
    "SOURCE": (7, 35, "substation and adjacent-feeder sources"),
    "LOADS": (8, 13, "spot loads"),
    "TEXT-BUS": (8, 13, "bus numbers"),
    "TEXT-ZONE": (7, 13, "zone names and loads"),
    "LEGEND": (7, 18, "legend"),
    "TITLE": (7, 25, "sheet border and title block (paper space)"),
}


def input_sha256() -> str:
    """Fingerprint of the result files the drawing is made from (stored in the DXF header)."""
    h = hashlib.sha256()
    for p in INPUTS:
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def drawn_from(path: Path = OUT) -> str | None:
    """The input fingerprint a DXF was drawn from, or None."""
    if not path.exists():
        return None
    doc = ezdxf.readfile(path)
    return doc.header.custom_vars.get("SHF_INPUT_SHA256")


def _rgb(hexcolor: str) -> tuple[int, int, int]:
    h = hexcolor.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _text(space, s: str, xy, height: float, layer: str, align=TextEntityAlignment.LEFT, **attrs):
    t = space.add_text(s, height=height, dxfattribs={"layer": layer, "style": TEXT_STYLE, **attrs})
    t.set_placement(xy, align=align)
    return t


def _blocks(doc) -> None:
    """Symbols drawn around (0, 0); colour BYBLOCK so each takes its layer's colour."""
    byblock = {"color": 0, "lineweight": -2}
    sq = lambda a: [(-a, -a), (a, -a), (a, a), (-a, a)]  # noqa: E731

    b = doc.blocks.new("RECLOSER")
    b.add_lwpolyline(sq(30), close=True, dxfattribs=byblock)
    _text(b, "R", (0, 0), 32, "0", TextEntityAlignment.MIDDLE_CENTER, color=0)
    b.add_attdef("NAME", dxfattribs={"height": 40, "style": TEXT_STYLE, "color": 0}).set_placement(
        (0, -48), align=TextEntityAlignment.TOP_CENTER)

    b = doc.blocks.new("SW_NC")   # normally-closed sectionalizer: filled square
    b.add_lwpolyline(sq(20), close=True, dxfattribs=byblock)
    hatch = b.add_hatch(color=0)
    hatch.paths.add_polyline_path(sq(20), is_closed=True)
    b.add_attdef("NAME", dxfattribs={"height": 36, "style": TEXT_STYLE, "color": 0}).set_placement(
        (30, 26), align=TextEntityAlignment.BOTTOM_LEFT)

    b = doc.blocks.new("SW_NO")   # normally-open tie: hollow square
    b.add_lwpolyline(sq(20), close=True, dxfattribs=byblock)
    b.add_attdef("NAME", dxfattribs={"height": 36, "style": TEXT_STYLE, "color": 0}).set_placement(
        (30, 26), align=TextEntityAlignment.BOTTOM_LEFT)

    b = doc.blocks.new("REG")     # voltage regulator
    b.add_circle((0, 0), 26, dxfattribs=byblock)
    _text(b, "VR", (0, 0), 20, "0", TextEntityAlignment.MIDDLE_CENTER, color=0)
    b.add_attdef("NAME", dxfattribs={"height": 30, "style": TEXT_STYLE, "color": 0}).set_placement(
        (34, 0), align=TextEntityAlignment.MIDDLE_LEFT)

    b = doc.blocks.new("CAP")     # shunt capacitor to ground, hanging below its bus
    for seg in [((0, 0), (0, -40)), ((-24, -40), (24, -40)), ((-24, -52), (24, -52)), ((0, -52), (0, -78)),
                ((-20, -78), (20, -78)), ((-12, -86), (12, -86)), ((-4, -94), (4, -94))]:
        b.add_line(*seg, dxfattribs=byblock)
    b.add_attdef("NAME", dxfattribs={"height": 30, "style": TEXT_STYLE, "color": 0}).set_placement(
        (32, -46), align=TextEntityAlignment.MIDDLE_LEFT)

    b = doc.blocks.new("SOURCE")  # voltage source: circle with a sine
    b.add_circle((0, 0), 48, dxfattribs=byblock)
    pts = [(-30 + 60 * i / 24, 16 * math.sin(2 * math.pi * i / 24)) for i in range(25)]
    b.add_lwpolyline(pts, dxfattribs=byblock)
    b.add_attdef("NAME", dxfattribs={"height": 40, "style": TEXT_STYLE, "color": 0}).set_placement(
        (0, 60), align=TextEntityAlignment.BOTTOM_CENTER)

    b = doc.blocks.new("LOAD")
    hatch = b.add_hatch(color=0)
    hatch.paths.add_polyline_path([(0, -10), (9, 6), (-9, 6)], is_closed=True)   # small arrow into the load


def _on_segment(p, a, b, tol=1.0) -> float | None:
    """Fraction t along a->b if p lies on that segment, else None."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return None
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2
    if not 0 < t < 1:
        return None
    qx, qy = ax + t * dx, ay + t * dy
    return t if math.hypot(p[0] - qx, p[1] - qy) <= tol else None


def _gapped(a, b, centres) -> list[tuple]:
    """Pieces of segment a->b with a GAP-long break around each symbol centre on it."""
    L = math.dist(a, b)
    cuts = sorted(t for c in centres if (t := _on_segment(c, a, b)) is not None)
    pieces, s = [], 0.0
    for t in cuts:
        g = GAP / L
        if t - g > s:
            pieces.append((s, t - g))
        s = t + g
    if s < 1:
        pieces.append((s, 1.0))
    at = lambda t: (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))  # noqa: E731
    return [(at(t0), at(t1)) for t0, t1 in pieces]


def build(geo: dict, zones: list[dict]) -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2018", setup=True, units=2)   # units: feet
    doc.styles.add(TEXT_STYLE, font="arial.ttf")
    doc.header["$LWDISPLAY"] = 1
    doc.header["$LTSCALE"] = 12.0
    doc.header["$PSLTSCALE"] = 0
    for name, (aci, lw, desc) in LAYERS.items():
        lay = doc.layers.add(name, color=aci, lineweight=lw)
        lay.description = desc
    zone_rgb = {z["name"]: _rgb(z["color"]) for z in geo["zones"]}
    for z in geo["zones"]:
        lay = doc.layers.add(f"ZONE-{z['name']}", color=7, lineweight=-3)
        lay.rgb = zone_rgb[z["name"]]
        lay.description = f"lines of switching zone {z['name']}"
    _blocks(doc)
    msp = doc.modelspace()
    xy = {b: tuple(p) for b, p in geo["buses"].items()}

    # devices (sectionalizers) and ties sit on lines: break the line around each symbol
    dev = {d[0]: (d[2], d[3]) for d in geo["devices"]}
    ties = {}
    for name, u, v in geo["ties"]:
        a = xy[u]
        b = xy[v] if v else (a[0] + ADJ[0], a[1] + ADJ[1])
        ties[name] = (a, b, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    centres = list(dev.values())

    src_bus, sx, sy = geo["source"]
    src = (sx, sy)
    for u, v, zone, phases, ug in geo["edges"]:
        if u not in xy or v not in xy:
            continue
        attrs = {"layer": f"ZONE-{zone}" if zone else "LINE-SUBSTATION", "lineweight": LW.get(phases, 18)}
        if ug:
            attrs["linetype"] = "DASHED"
        for a, b in _gapped(xy[u], xy[v], centres):
            msp.add_line(a, b, dxfattribs=attrs)

    # substation: source -> regulator 1 -> recloser Sw1 -> bus 149
    first = xy["149"]
    reg1 = (src[0] + 78, src[1])
    for a, b in _gapped(src, first, [reg1, dev["Sw1"]]):
        if math.dist(a, src) < 1:
            a = (src[0] + 48, src[1])      # start at the source circle
        msp.add_line(a, b, dxfattribs={"layer": "LINE-SUBSTATION", "lineweight": 50})
    ref = msp.add_blockref("SOURCE", src, dxfattribs={"layer": "SOURCE"}).add_auto_attribs(
        {"NAME": f"Substation {src_bus} (4.16 kV)"})
    ref.get_attrib("NAME").set_placement((src[0], src[1] + 84), align=TextEntityAlignment.BOTTOM_CENTER)
    ref = msp.add_blockref("REG", reg1, dxfattribs={"layer": "DEV-REG"}).add_auto_attribs({"NAME": "Reg 1"})
    ref.get_attrib("NAME").set_placement((reg1[0], reg1[1] + 36), align=TextEntityAlignment.BOTTOM_CENTER)

    for name, kind, x, y, _zone in geo["devices"]:
        block = "RECLOSER" if kind == "recloser" else "SW_NC"
        layer = "DEV-RECLOSER" if kind == "recloser" else "DEV-SWITCH"
        label = name if kind != "added" else f"{name} (added)"
        msp.add_blockref(block, (x, y), dxfattribs={"layer": layer}).add_auto_attribs({"NAME": label})

    for name, (a, b, mid) in ties.items():
        for p, q in _gapped(a, b, [mid]):
            msp.add_line(p, q, dxfattribs={"layer": "DEV-TIE", "linetype": "PHANTOM", "lineweight": 25})
        note = {"Sw8": "Sw8 N.O. (1-ph, not used)", "Sw9": "Sw9 N.O. (added tie)"}.get(name, f"{name} N.O.")
        ref = msp.add_blockref("SW_NO", mid, dxfattribs={"layer": "DEV-TIE"}).add_auto_attribs({"NAME": note})
        if name in TIE_LABEL:   # move labels that would sit on another label
            (dx, dy), align = TIE_LABEL[name]
            ref.get_attrib("NAME").set_placement((mid[0] + dx, mid[1] + dy), align=align)
        if name == "Sw9":
            p = (b[0] + 48, b[1])
            msp.add_blockref("SOURCE", (p[0], p[1]), dxfattribs={"layer": "SOURCE"}).add_auto_attribs(
                {"NAME": "Adjacent feeder (assumed)"})

    for name, bus, x, y in geo["regs"]:
        dx, dy = REG_OFFSET.get(name, (50, 50))
        p = (x + dx, y + dy)
        msp.add_line((x, y), (p[0] - 18, p[1] - 18), dxfattribs={"layer": "DEV-REG"})
        msp.add_blockref("REG", p, dxfattribs={"layer": "DEV-REG"}).add_auto_attribs({"NAME": name})
    for name, bus, kvar, x, y in geo["caps"]:
        msp.add_blockref("CAP", (x, y), dxfattribs={"layer": "DEV-CAP"}).add_auto_attribs(
            {"NAME": f"{name} {kvar:g} kvar"})

    for bus, kw in geo["loads"].items():
        if bus in xy and kw > 0:
            msp.add_blockref("LOAD", (xy[bus][0], xy[bus][1] - 14), dxfattribs={"layer": "LOADS"})
    for bus, (x, y) in xy.items():
        _text(msp, bus, (x + 12, y + 12), 26, "TEXT-BUS")

    zrow = {z["zone"]: z for z in zones}
    for z in geo["zones"]:
        r = zrow[z["name"]]
        m = msp.add_mtext(f"ZONE {z['name']}\\P{float(r['kW']):,.0f} kW · {r['load_points']} loads",
                          dxfattribs={"layer": "TEXT-ZONE", "style": TEXT_STYLE, "char_height": 52})
        m.rgb = zone_rgb[z["name"]]
        dx, dy = ZONE_LABEL_SHIFT.get(z["name"], (0, 0))
        m.set_location((z["label"][0] + dx, z["label"][1] + dy), attachment_point=MTextEntityAlignment.MIDDLE_CENTER)

    # legend, below the feeder in model space
    xs = [p[0] for p in xy.values()] + [src[0]]
    ys = [p[1] for p in xy.values()]
    lx, ly = min(xs), min(ys) - 260
    _text(msp, "LEGEND", (lx, ly), 48, "LEGEND")
    rows = [("RECLOSER", "DEV-RECLOSER", "Feeder-head recloser (lockout)"),
            ("SW_NC", "DEV-SWITCH", "Sectionalizing switch, normally closed"),
            ("SW_NO", "DEV-TIE", "Tie switch, normally open"),
            ("REG", "DEV-REG", "Voltage regulator"), ("CAP", "DEV-CAP", "Capacitor bank"),
            ("LOAD", "LOADS", "Spot load")]
    for i, (blk, layer, text) in enumerate(rows):
        col, row = divmod(i, 3)
        x, y = lx + 40 + col * 1500, ly - 110 - row * 130
        msp.add_blockref(blk, (x, y + (40 if blk == "CAP" else 0)), dxfattribs={"layer": layer})
        _text(msp, text, (x + 90, y), 38, "LEGEND", TextEntityAlignment.MIDDLE_LEFT)
    for i, (phases, text) in enumerate([(3, "3-phase line"), (2, "2-phase line"), (1, "1-phase line")]):
        x, y = lx + 3040, ly - 110 - i * 130
        msp.add_line((x - 60, y), (x + 60, y), dxfattribs={"layer": "LEGEND", "lineweight": LW[phases]})
        _text(msp, text, (x + 90, y), 38, "LEGEND", TextEntityAlignment.MIDDLE_LEFT)
    x, y = lx + 4300, ly - 110
    msp.add_line((x - 60, y), (x + 60, y), dxfattribs={"layer": "LEGEND", "linetype": "DASHED", "lineweight": 50})
    _text(msp, "Underground cable", (x + 90, y), 38, "LEGEND", TextEntityAlignment.MIDDLE_LEFT)
    msp.add_line((x - 60, y - 130), (x + 60, y - 130), dxfattribs={"layer": "DEV-TIE", "linetype": "PHANTOM"})
    _text(msp, "Open tie path", (x + 90, y - 130), 38, "LEGEND", TextEntityAlignment.MIDDLE_LEFT)

    # labels live on their symbol's layer, so freezing a layer hides its labels too
    for ref in msp.query("INSERT"):
        for att in ref.attribs:
            att.dxf.layer = ref.dxf.layer

    # extents of what was drawn, for the layout viewport
    x0, x1 = src[0] - 120, max(xs) + ADJ[0] + 700
    y0, y1 = ly - 420, max(ys) + 160
    doc.header["$EXTMIN"] = (x0, y0, 0)
    doc.header["$EXTMAX"] = (x1, y1, 0)
    doc.set_modelspace_vport(height=(y1 - y0) * 1.05, center=((x0 + x1) / 2, (y0 + y1) / 2))
    _sheet(doc, (x0, y0, x1, y1), zones)
    doc.layouts.delete("Layout1")   # leave one paper layout: the A3 sheet
    return doc


def _sheet(doc, ext, zones) -> None:
    """A3 landscape paper-space layout: border, viewport on the feeder, title block."""
    x0, y0, x1, y1 = ext
    lay = doc.layouts.new("A3 ONE-LINE")
    lay.page_setup(size=(420, 297), margins=(0, 0, 0, 0), units="mm")
    W, H, m, tb = 420, 297, 10, 34
    lay.add_lwpolyline([(m, m), (W - m, m), (W - m, H - m), (m, H - m)], close=True,
                       dxfattribs={"layer": "TITLE", "lineweight": 50})
    vw, vh = W - 2 * m - 4, H - 2 * m - tb - 6
    vc = (W / 2, m + tb + 3 + vh / 2)
    view_h = max(y1 - y0, (x1 - x0) * vh / vw)
    lay.add_viewport(center=vc, size=(vw, vh), view_center_point=((x0 + x1) / 2, (y0 + y1) / 2), view_height=view_h)
    lay.add_line((m, m + tb), (W - m, m + tb), dxfattribs={"layer": "TITLE", "lineweight": 35})
    cols = [m, 150, 250, 330, W - m]
    for x in cols[1:-1]:
        lay.add_line((x, m), (x, m + tb), dxfattribs={"layer": "TITLE", "lineweight": 25})
    total = sum(float(z["kW"]) for z in zones)
    cells = [
        ("IEEE 123-BUS TEST FEEDER (4.16 kV)", ["One-line diagram with 10 FLISR switching zones",
                                               f"{len(zones)} zones · {total:,.0f} kW of spot load"]),
        ("PROJECT", ["Self-Healing Feeder (FLISR study)", "Simulation only, not a field drawing"]),
        ("DRAWN FROM", ["results/feeder_geometry.json", "results/zones.csv · OpenDSS model"]),
        ("SHEET", ["Scale: NTS (IEEE plot coordinates)", "Author: C. Nguyen · Sheet 1 of 1"]),
    ]
    for (title, lines), xa, xb in zip(cells, cols, cols[1:]):
        _text(lay, title, (xa + 3, m + tb - 7), 4.2 if xa == m else 3.0, "TITLE")
        for i, s in enumerate(lines):
            _text(lay, s, (xa + 3, m + tb - 16 - i * 7), 3.2 if xa == m else 2.6, "TITLE")


def export(path: Path = OUT) -> Path:
    geo = json.loads(INPUTS[0].read_text(encoding="utf-8"))
    with open(INPUTS[1], newline="", encoding="utf-8") as f:
        zones = list(csv.DictReader(f))
    doc = build(geo, zones)
    doc.header.custom_vars.append("SHF_INPUT_SHA256", input_sha256())
    doc.header.custom_vars.append("SHF_SOURCE", "scripts/export_oneline_dxf.py from results/")
    path.parent.mkdir(parents=True, exist_ok=True)
    # fixed dates and GUIDs, so the same results give the same file (clean git diffs)
    fixed = ezdxf.options.write_fixed_meta_data_for_testing
    ezdxf.options.write_fixed_meta_data_for_testing = True
    try:
        doc.saveas(path)
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = fixed
    path.write_text(_stable(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    return path


def _stable(dxf: str) -> str:
    """Drop the two things ezdxf varies between runs: its save timestamp and the order of
    the CLASS entries (taken from a hash set). Neither changes what AutoCAD draws."""
    dxf = re.sub(r"(\n  1\n)(\d+\.\d+\.\d+) @ \d{4}-\d\d-\d\dT[0-9:.+]+\n", r"\1\2\n", dxf)
    head, sep, rest = dxf.partition("  2\nCLASSES\n")
    if not sep:
        return dxf
    body, end, tail = rest.partition("  0\nENDSEC\n")
    chunks = ["  0\nCLASS\n" + c for c in body.split("  0\nCLASS\n") if c]
    chunks.sort(key=lambda c: c.split("\n")[3])   # the CLASS record name (group code 1)
    return head + sep + "".join(chunks) + end + tail
