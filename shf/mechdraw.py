"""Dimensioned technical drawings of the SolidWorks equipment (A3, third-angle projection).

Each part is drawn from the same prisms SolidWorks extrudes (shf.mech.prisms), so a drawing
always matches its 3D model: front, right-side and top views with hidden lines removed, the key
dimensions from the part's size table in config.py, a spec table and a title block.

    python scripts/export_drawings.py --register     # DXF -> AutoCAD -> DWG, PDF, PNG

Writes cad/drawing_<part>.dxf. Sizes are illustrative (ASSUMPTION in config.py): generic
equipment for a simulation study, not a manufacturer's design. The DXF header stores a
fingerprint of the size table, so the health check can tell when a drawing is stale.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

from . import config, mech

CAD = config.ROOT / "cad"
SCALES = (5, 10, 15, 20, 25, 30, 40, 50)          # 1:n
SHEET_W, SHEET_H, MARGIN = 420.0, 297.0, 10.0
AREA_W, AREA_H = 290.0, 277.0                     # drawing area on the left (paper mm); spec + title on the right
TEXT = "SHF"
TITLES = {
    "recloser": "Pole-mounted 3-phase recloser",
    "auto_switch": "Automated sectionalizing switch with radio",
    "regulator": "Single-phase step voltage regulator",
    "capacitor": "Pole-mounted 3-phase capacitor bank",
    "transformer": "Single-phase pole-top distribution transformer",
    "substation": "4.16 kV source transformer on pad",
}
TABLES = {"recloser": "RECLOSER_MM", "auto_switch": "AUTO_SWITCH_MM", "regulator": "REGULATOR_MM",
          "capacitor": "CAPACITOR_MM", "transformer": "TRANSFORMER_MM", "substation": "SUBSTATION_MM"}
LAYERS = {"VISIBLE": (7, 35), "REFERENCE": (8, 25), "CENTER": (1, 13), "DIM": (3, 13),
          "LABEL": (7, 18), "TITLE": (7, 25)}


def path(name: str) -> Path:
    return CAD / f"drawing_{name}.dxf"


def input_sha256(name: str) -> str:
    """Fingerprint of what the drawing is made from: the size table and the prism list."""
    data = {"table": getattr(config, TABLES[name]), "prisms": mech.prisms(name)}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=list).encode()).hexdigest()


def drawn_from(name: str) -> str | None:
    p = path(name)
    if not p.exists():
        return None
    return ezdxf.readfile(p).header.custom_vars.get("SHF_INPUT_SHA256")


# ---------------------------------------------------------------- projection
def _views(ps: list[dict]) -> dict:
    """Shapes per view in view-local 2D (u right, v up) with a depth key (larger = nearer).
    Front looks from +z (u = x, v = y); right side from +x (u = -z, v = y); top from +y
    (u = x, v = -z, placed above the front view as in third-angle projection)."""
    out = {"front": [], "side": [], "top": []}
    for p in ps:
        x0, x1 = p["x"] - p["w"] / 2, p["x"] + p["w"] / 2
        z0, z1 = p["z"] - p["d"] / 2, p["z"] + p["d"] / 2
        y0, y1 = p["y0"], p["y0"] + p["h"]
        out["front"].append(("rect", (x0, y0, x1, y1), z1, p))
        out["side"].append(("rect", (-z1, y0, -z0, y1), x1, p))
        if p["shape"] == "cyl":
            out["top"].append(("circle", (p["x"], -p["z"], p["w"] / 2), y1, p))
        else:
            out["top"].append(("rect", (x0, -z1, x1, -z0), y1, p))
    return out


def _inside(shape, u, v, eps) -> bool:
    kind, g = shape[0], shape[1]
    if kind == "rect":
        return g[0] + eps < u < g[2] - eps and g[1] + eps < v < g[3] - eps
    return (u - g[0]) ** 2 + (v - g[1]) ** 2 < (g[2] - eps) ** 2


def _outline(shape, step) -> list[list[tuple]]:
    kind, g = shape[0], shape[1]
    if kind == "circle":
        n = max(48, int(2 * math.pi * g[2] / step))
        pts = [(g[0] + g[2] * math.cos(2 * math.pi * k / n), g[1] + g[2] * math.sin(2 * math.pi * k / n))
               for k in range(n + 1)]
        return [pts]
    a, b, c, d = g
    edges = [((a, b), (c, b)), ((c, b), (c, d)), ((c, d), (a, d)), ((a, d), (a, b))]
    out = []
    for (pu, pv), (qu, qv) in edges:
        n = max(1, int(math.hypot(qu - pu, qv - pv) / step))
        out.append([(pu + (qu - pu) * k / n, pv + (qv - pv) * k / n) for k in range(n + 1)])
    return out


def visible_segments(shapes, step) -> list[list[tuple]]:
    """Hidden-line removal for axis-aligned prisms: a piece of an outline is drawn unless it lies
    inside a nearer shape of the same view."""
    lines = []
    eps = step * 0.25
    for i, s in enumerate(shapes):
        nearer = [t for j, t in enumerate(shapes) if j != i and t[2] > s[2] + 1e-6]
        for poly in _outline(s, step):
            run = [poly[0]]
            for a, b in zip(poly, poly[1:]):
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                if any(_inside(t, *mid, eps) for t in nearer):
                    if len(run) > 1:
                        lines.append(run)
                    run = [b]
                else:
                    run.append(b)
            if len(run) > 1:
                lines.append(run)
    return lines


# ---------------------------------------------------------------- dimensions per part
def _get(ps, name):
    return next(p for p in ps if p["name"] == name)


def _top(p):
    return p["y0"] + p["h"]


def _dims(name: str, ps: list[dict], m: dict) -> list[tuple]:
    """(view, 'h'|'v', a, b, at): 'h' measures u from a to b on a line at v = at;
    'v' measures v from a to b on a line at u = at (view-local model mm)."""
    body = [p for p in ps if p["group"] != "pole"]
    xmin = min(p["x"] - p["w"] / 2 for p in body)
    xmax = max(p["x"] + p["w"] / 2 for p in body)
    ymin, ymax = min(p["y0"] for p in body), max(_top(p) for p in body)
    zmin = min(p["z"] - p["d"] / 2 for p in body)
    zmax = max(p["z"] + p["d"] / 2 for p in body)
    k = (ymax - ymin) / 14                       # spacing between stacked dimension lines
    d = [("front", "v", ymin, ymax, xmin - 2.6 * k),            # overall height
         ("front", "h", xmin, xmax, ymin - 2.4 * k),            # overall width
         ("side", "h", -zmax, -zmin, ymin - 2.4 * k)]           # overall depth
    if name in ("recloser", "auto_switch"):
        tank, cab = _get(ps, "Tank"), _get(ps, "Control cabinet")
        ba, bb, bc = _get(ps, "Bushing Source A"), _get(ps, "Bushing Source B"), _get(ps, "Bushing Source C")
        tt = _get(ps, "Terminal Source A")
        d += [("front", "h", tank["x"] - tank["w"] / 2, tank["x"] + tank["w"] / 2, tank["y0"] + 0.35 * tank["h"]),
              ("front", "v", tank["y0"], _top(tank), tank["x"] + tank["w"] / 2 + 1.2 * k),
              ("front", "h", ba["x"], bb["x"], _top(tt) + 1.2 * k),
              ("front", "v", _top(tank), _top(ba), bc["x"] + 1.1 * k),
              ("front", "v", cab["y0"], _top(cab), cab["x"] - cab["w"] / 2 - 1.2 * k),
              ("side", "h", -m["bushing_row"], m["bushing_row"], _top(tt) + 1.2 * k),
              ("side", "h", -m["pole_z"], 0, ymin - 1.2 * k)]
        if name == "auto_switch":
            rad = _get(ps, "Antenna radome")
            d.append(("front", "v", _top(tank), _top(rad), rad["x"] + rad["w"] / 2 + 1.2 * k))
    elif name == "regulator":
        tank, base = _get(ps, "Tank"), _get(ps, "Base")
        bs, bl = _get(ps, "Bushing S"), _get(ps, "Bushing L")
        tt = _get(ps, "Terminal S")
        d += [("front", "h", -tank["w"] / 2, tank["w"] / 2, tank["y0"] + 0.25 * tank["h"]),
              ("front", "v", tank["y0"], _top(tank), xmax + 1.2 * k),
              ("front", "h", bs["x"], bl["x"], _top(tt) + 1.2 * k),
              ("front", "h", -base["w"] / 2, base["w"] / 2, base["y0"] - 1.2 * k)]
    elif name == "capacitor":
        ca, cb = _get(ps, "Capacitor can A"), _get(ps, "Capacitor can B")
        rack = _get(ps, "Rack")
        tt = _get(ps, "Terminal A")
        d += [("front", "h", ca["x"], cb["x"], _top(tt) + 1.2 * k),
              ("front", "h", ca["x"] - ca["w"] / 2, ca["x"] + ca["w"] / 2, ca["y0"] + 0.4 * ca["h"]),
              ("front", "v", ca["y0"], _top(ca), xmax + 1.2 * k),
              ("front", "h", -rack["w"] / 2, rack["w"] / 2, rack["y0"] - 1.2 * k),
              ("side", "h", -m["pole_z"], 0, ymin - 1.2 * k)]
    elif name == "transformer":
        tank = _get(ps, "Tank")
        h1, h2 = _get(ps, "Bushing HV 1"), _get(ps, "Bushing HV 2")
        tt = _get(ps, "Terminal HV 1")
        d += [("front", "h", -tank["w"] / 2, tank["w"] / 2, tank["y0"] + 0.3 * tank["h"]),
              ("front", "v", tank["y0"], _top(tank), xmax + 1.2 * k),
              ("front", "h", h1["x"], h2["x"], _top(tt) + 1.2 * k),
              ("side", "h", -m["pole_z"], 0, ymin - 1.2 * k)]
    elif name == "substation":
        tank, pad = _get(ps, "Main tank"), _get(ps, "Pad")
        h1, h2 = _get(ps, "Bushing HV 1"), _get(ps, "Bushing HV 2")
        tt = _get(ps, "Terminal HV 1")
        d += [("front", "h", -tank["w"] / 2, tank["w"] / 2, tank["y0"] + 0.3 * tank["h"]),
              ("front", "v", tank["y0"], _top(tank), xmax + 1.2 * k),
              ("front", "v", pad["y0"], _top(pad), xmin - 1.2 * k),
              ("front", "h", h1["x"], h2["x"], _top(tt) + 1.2 * k),
              ("side", "h", -tank["d"] / 2, tank["d"] / 2, tank["y0"] + 0.3 * tank["h"])]
    return d


# ---------------------------------------------------------------- spec table
def _spec(name: str, ps: list[dict], m: dict, geo: dict) -> list[tuple[str, str]]:
    body = [p for p in ps if p["group"] != "pole"]
    W = max(p["x"] + p["w"] / 2 for p in body) - min(p["x"] - p["w"] / 2 for p in body)
    D = max(p["z"] + p["d"] / 2 for p in body) - min(p["z"] - p["d"] / 2 for p in body)
    H = max(_top(p) for p in body) - min(p["y0"] for p in body)
    rows = [("Overall W x D x H", f"{W:,.0f} x {D:,.0f} x {H:,.0f} mm"),
            ("Solids in the model", f"{len(ps)} (SolidWorks bodies)")]
    added = [n for n in config.SECTIONALIZERS if n.startswith("L")]
    if name in ("recloser", "auto_switch"):
        tw, td, th = m["tank"]
        bd, bh = m["bushing"]
        rows = [("Used for", "Sw1, feeder head" if name == "recloser" else ", ".join(added) + " (added)"),
                ("System", "4.16 kV, 3-phase (IEEE 123-bus)"),
                ("Continuous rating", f"{config.SWITCH_AMPACITY:.0f} A (ASSUMPTION)"),
                ("Tank W x D x H", f"{tw} x {td} x {th} mm"),
                ("Bushings", f"6, dia {bd} x {bh} mm, {m['shed'][2]} sheds"),
                ("Phase spacing", f"{m['phase_spacing']} mm"),
                ("Control cabinet", " x ".join(str(v) for v in m["cabinet"]) + " mm")] + rows
        if "antenna" in m:
            rows.insert(-2, ("Radio antenna", f"mast dia {m['antenna'][0]} x {m['antenna'][1]} mm"))
    elif name == "regulator":
        regs = [r[0] for r in geo["regs"]]
        rows = [("Used for", "Reg 1 (3 units, substation), " + ", ".join(regs)),
                ("System", "4.16 kV feeder, one unit per phase"),
                ("Tank", f"dia {m['tank'][0]} x {m['tank'][1]} mm"),
                ("Bushings", f"3 (S, L, SL), dia {m['bushing'][0]} x {m['bushing'][1]} mm"),
                ("Radiator fins", f"{m['fin'][3]} per side, {m['fin'][1]} mm reach")] + rows
    elif name == "capacitor":
        big = [c for c in geo["caps"] if c[2] >= 300]
        rows = [("Used for", ", ".join(f"{c[0]} ({c[2]:.0f} kvar, bus {c[1]})" for c in big)),
                ("System", "4.16 kV, 3-phase, fixed (as in the IEEE case)"),
                ("Cans", f"3, {m['can'][0]} x {m['can'][1]} x {m['can'][2]} mm"),
                ("Bushings", f"3, dia {m['bushing'][0]} x {m['bushing'][1]} mm")] + rows
    elif name == "transformer":
        loads = geo["loads"]
        rows = [("Used for", f"every load bus ({len(loads)} spot loads, "
                             f"{min(loads.values()):.0f}-{max(loads.values()):.0f} kW each)"),
                ("Primary", "4.16 kV feeder, single phase"),
                ("Tank", f"dia {m['tank'][0]} x {m['tank'][1]} mm"),
                ("HV / LV bushings", f"{len(m['hv_x'])} / {len(m['lv_x'])}")] + rows
    elif name == "substation":
        rows = [("Used for", "source of the IEEE 123-bus feeder (bus 150)"),
                ("Secondary", "4.16 kV"),
                ("Main tank W x D x H", " x ".join(str(v) for v in m["tank"]) + " mm"),
                ("Radiators", f"{m['radiator'][3]} per side, {m['radiator'][1]} mm reach"),
                ("HV / LV bushings", f"{len(m['hv_x'])} / {len(m['lv_x'])}"),
                ("Pad", " x ".join(str(v) for v in m["pad"]) + " mm")] + rows
    if any(p["group"] == "pole" for p in ps):
        rows.append(("Pole", f"dia {m['pole'][0]} mm, reference only"))
    rows.append(("Size table", f"config.{TABLES[name]}"))
    return rows


# ---------------------------------------------------------------- the sheet
def _text(space, s, xy, h, layer="LABEL", align=TextEntityAlignment.LEFT):
    t = space.add_text(s, height=h, dxfattribs={"layer": layer, "style": TEXT})
    t.set_placement(xy, align=align)
    return t


def build(name: str, sheet_no: int = 1, sheets: int = 6) -> ezdxf.document.Drawing:
    ps = mech.prisms(name)
    m = getattr(config, TABLES[name])
    geo = json.loads((config.RESULTS / "feeder_geometry.json").read_text(encoding="utf-8"))
    body = [p for p in ps if p["group"] != "pole"]
    xmin = min(p["x"] - p["w"] / 2 for p in body)
    xmax = max(p["x"] + p["w"] / 2 for p in body)
    ymin, ymax = min(p["y0"] for p in body), max(_top(p) for p in body)
    zmin = min(p["z"] - p["d"] / 2 for p in body)
    zmax = max(p["z"] + p["d"] / 2 for p in body)
    W, H, D = xmax - xmin, ymax - ymin, zmax - zmin
    need = max((W + D) / (AREA_W - 90), (H + D) / (AREA_H - 90))
    s = next((n for n in SCALES if n >= need), SCALES[-1])
    gap = 45 * s                                   # paper mm between views, room for dimensions
    side_off, top_off = xmax + gap + zmax, ymax + gap - zmin   # side view u = -z + side_off; top v = -z + top_off

    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.MM
    doc.styles.new(TEXT, dxfattribs={"font": "arial.ttf"})
    for lay, (color, lw) in LAYERS.items():
        doc.layers.add(lay, color=color, lineweight=lw)
    doc.layers.get("REFERENCE").dxf.linetype = "PHANTOM" if "PHANTOM" in doc.linetypes else "DASHED"
    doc.header["$LTSCALE"] = 1.0
    doc.header["$PSLTSCALE"] = 1          # linetype dashes scale with the viewport (same look at any 1:s)
    doc.layers.get("CENTER").dxf.linetype = "CENTER" if "CENTER" in doc.linetypes else "DASHDOT"
    dim = doc.dimstyles.new("SHF")
    for k, v in {"dimtxt": 2.5, "dimasz": 2.5, "dimexe": 1.2, "dimexo": 1.0, "dimgap": 0.8,
                 "dimdec": 0, "dimtad": 1, "dimscale": s, "dimtxsty": TEXT, "dimclrd": 3, "dimclre": 3,
                 "dimclrt": 7}.items():
        dim.dxf.set(k, v)
    msp = doc.modelspace()
    place = {"front": lambda u, v: (u, v), "side": lambda u, v: (u + side_off, v),
             "top": lambda u, v: (u, v + top_off)}
    views = _views([p for p in ps if p["group"] != "pole"])
    step = max(W, H, D) / 600
    for view, shapes in views.items():
        for line in visible_segments(shapes, step):
            msp.add_lwpolyline([place[view](*q) for q in line], dxfattribs={"layer": "VISIBLE"})
    # pole: reference outline (phantom), only over the height of the equipment
    pole = next((p for p in ps if p["group"] == "pole"), None)
    if pole:
        r, lo, hi = pole["w"] / 2, ymin - 0.08 * H, ymax + 0.04 * H
        for view, (c, sign) in (("front", (pole["x"], 1)), ("side", (-pole["z"], 1))):
            for u in (c - r, c + r):
                msp.add_line(place[view](u, lo), place[view](u, hi), dxfattribs={"layer": "REFERENCE"})
        msp.add_circle(place["top"](pole["x"], -pole["z"]), r, dxfattribs={"layer": "REFERENCE"})
    # centre lines through the main axis in each view
    for view, (u0, u1, v0, v1) in (("front", (0, 0, ymin - 0.05 * H, ymax + 0.05 * H)),
                                   ("top", (xmin - 0.05 * W, xmax + 0.05 * W, 0, 0))):
        msp.add_line(place[view](u0, v0), place[view](u1, v1), dxfattribs={"layer": "CENTER"})
    # dimensions
    for view, kind, a, b, at in _dims(name, ps, m):
        if kind == "h":
            p1, p2, base = place[view](a, at), place[view](b, at), place[view](a, at)
            msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=0, dimstyle="SHF",
                               dxfattribs={"layer": "DIM"}).render()
        else:
            p1, p2, base = place[view](at, a), place[view](at, b), place[view](at, a)
            msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=90, dimstyle="SHF",
                               dxfattribs={"layer": "DIM"}).render()
    # view labels
    for view, (u, v) in (("front", ((xmin + xmax) / 2, ymin - 2.4 * (H / 14) - 9 * s)),
                         ("side", ((-zmax - zmin) / 2, ymin - 2.4 * (H / 14) - 9 * s)),
                         ("top", ((xmin + xmax) / 2, -zmin + 12 * s))):
        label = {"front": "FRONT VIEW", "side": "RIGHT SIDE VIEW", "top": "TOP VIEW"}[view]
        _text(msp, label, place[view](u, v), 3.5 * s, align=TextEntityAlignment.TOP_CENTER)

    # extents and the A3 sheet
    x0 = xmin - 3.6 * (H / 14) - 10 * s
    x1 = side_off - zmin + 3 * (H / 14) + 10 * s
    y0 = ymin - 2.4 * (H / 14) - 18 * s
    y1 = top_off - zmin + 22 * s
    doc.header["$EXTMIN"], doc.header["$EXTMAX"] = (x0, y0, 0), (x1, y1, 0)
    doc.set_modelspace_vport(height=(y1 - y0) * 1.05, center=((x0 + x1) / 2, (y0 + y1) / 2))
    _sheet(doc, name, s, (x0, y0, x1, y1), _spec(name, ps, m, geo), sheet_no, sheets)
    doc.layouts.delete("Layout1")
    return doc


def _sheet(doc, name, s, ext, spec, sheet_no, sheets) -> None:
    lay = doc.layouts.new("A3 DRAWING")
    lay.page_setup(size=(SHEET_W, SHEET_H), margins=(0, 0, 0, 0), units="mm")
    M = MARGIN
    lay.add_lwpolyline([(M, M), (SHEET_W - M, M), (SHEET_W - M, SHEET_H - M), (M, SHEET_H - M)], close=True,
                       dxfattribs={"layer": "TITLE", "lineweight": 50})
    xr = M + AREA_W                                     # right column
    lay.add_line((xr, M), (xr, SHEET_H - M), dxfattribs={"layer": "TITLE", "lineweight": 35})
    # viewport: model at 1:s, centred in the drawing area
    x0, y0, x1, y1 = ext
    vw, vh = AREA_W - 6, SHEET_H - 2 * M - 6
    view_h = max(y1 - y0, (x1 - x0) * vh / vw)
    view_h = max(view_h, vh * s)                         # never larger than 1:s
    vp = lay.add_viewport(center=(M + 3 + vw / 2, M + 3 + vh / 2), size=(vw, vh),
                          view_center_point=((x0 + x1) / 2, (y0 + y1) / 2), view_height=vh * s)
    vp.dxf.status = 1
    # spec table
    cw = SHEET_W - M - xr
    y = SHEET_H - M - 8
    _text(lay, "SPECIFICATIONS", (xr + 3, y), 3.6, "TITLE")
    y -= 4
    lay.add_line((xr, y), (SHEET_W - M, y), dxfattribs={"layer": "TITLE"})
    for key, val in spec:
        y -= 6
        _text(lay, key, (xr + 3, y), 2.3, "TITLE")
        lines = _wrap(val, 34)
        for i, ln in enumerate(lines):
            _text(lay, ln, (xr + 44, y - i * 3.6), 2.3, "TITLE")
        y -= 3.6 * (len(lines) - 1)
        lay.add_line((xr, y - 2.2), (SHEET_W - M, y - 2.2), dxfattribs={"layer": "TITLE", "lineweight": 13})
    # notes
    y -= 9
    _text(lay, "NOTES", (xr + 3, y), 3.0, "TITLE")
    notes = ["1. Dimensions in mm. Third-angle projection.",
             "2. Generic, illustrative sizes for a simulation study;",
             "   not a manufacturer's design. No calculation uses them.",
             "3. Drawn from the same solids as the SolidWorks part",
             f"   mech/{name}.sldprt (shf/mech.py, shf/mechdraw.py).",
             "4. Hidden lines omitted. Pole shown as reference (phantom)."]
    for i, n in enumerate(notes):
        _text(lay, n, (xr + 3, y - 5 - i * 3.6), 2.2, "TITLE")
    # title block
    tb = 58
    lay.add_line((xr, M + tb), (SHEET_W - M, M + tb), dxfattribs={"layer": "TITLE", "lineweight": 35})
    rows = [("PROJECT", "Self-Healing Feeder (FLISR study)"),
            ("TITLE", TITLES[name]),
            ("DRAWING NO.", f"SHF-M-{sheet_no:02d}    SHEET {sheet_no} OF {sheets}"),
            ("SCALE", f"1:{s}    UNITS: mm    A3"),
            ("SOURCE", f"config.{TABLES[name]}"),
            ("DRAWN", "C. Nguyen (generated)    REV A")]
    rh = tb / len(rows)
    for i, (k, v) in enumerate(rows):
        yy = M + tb - (i + 1) * rh
        if i:
            lay.add_line((xr, yy + rh), (SHEET_W - M, yy + rh), dxfattribs={"layer": "TITLE", "lineweight": 13})
        _text(lay, k, (xr + 3, yy + 2.6), 2.0, "TITLE")
        _text(lay, v, (xr + 25, yy + 2.4), 2.9 if k == "TITLE" else 2.5, "TITLE")
    # third-angle symbol
    sx, sy = xr - 30, M + 6
    lay.add_circle((sx, sy + 5), 4, dxfattribs={"layer": "TITLE"})
    lay.add_circle((sx, sy + 5), 1.8, dxfattribs={"layer": "TITLE"})
    lay.add_lwpolyline([(sx - 16, sy + 1), (sx - 7, sy + 3), (sx - 7, sy + 7), (sx - 16, sy + 9)], close=True,
                       dxfattribs={"layer": "TITLE"})
    _text(lay, "THIRD ANGLE", (sx - 12, sy - 2.5), 1.8, "TITLE", TextEntityAlignment.TOP_CENTER)


def _wrap(s: str, n: int) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > n:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + [cur] if cur else lines


def export(name: str, sheet_no: int = 1, sheets: int = 6) -> Path:
    from .cad import _stable
    doc = build(name, sheet_no, sheets)
    doc.header.custom_vars.append("SHF_INPUT_SHA256", input_sha256(name))
    doc.header.custom_vars.append("SHF_SOURCE", f"scripts/export_drawings.py from config.{TABLES[name]}")
    p = path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    fixed = ezdxf.options.write_fixed_meta_data_for_testing
    ezdxf.options.write_fixed_meta_data_for_testing = True
    try:
        doc.saveas(p)
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = fixed
    p.write_text(_stable(p.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    return p


def scale_of(name: str) -> int:
    t = ezdxf.readfile(path(name)).layouts.get("A3 DRAWING")
    for e in t:
        if e.dxftype() == "TEXT" and re.match(r"1:\d+ ", e.dxf.text):
            return int(e.dxf.text.split()[0][2:])
    raise ValueError("no scale in title block")
