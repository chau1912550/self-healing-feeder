"""Zone-level A3 one-line DXF drawings for the 11 other test feeders (AutoCAD).

Drawn directly from results/feeders/feeder_maps.json (built by scripts/export_feeder_maps.py
from the official OpenDSS test circuits), so every zone name, parent link, load kW, bus count,
switch line and voltage matches the report and technical paper verbatim.

    python scripts/export_feeder_onelines.py --dxf-only    # -> cad/oneline_<feeder>.dxf (11 files)
    python scripts/export_feeder_onelines.py --register    # -> + AutoCAD .dwg & exports/*.pdf, registered

IEEE 123-bus already has its bus-level one-line diagram in shf/cad.py (cad/feeder_oneline.dxf).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

from . import cad, config

MAPS_JSON = config.RESULTS / "feeders" / "feeder_maps.json"
OUT_DIR = config.ROOT / "cad"

# The 11 official test feeders outside IEEE 123-bus (which has bus-level cad/feeder_oneline.dxf).
OTHER_FEEDERS: tuple[str, ...] = (
    "ieee34",
    "ieee37",
    "ieee13",
    "eu_lv",
    "ieee8500",
    "epri_ckt5",
    "epri_ckt7",
    "epri_ckt24",
    "epri_j1",
    "epri_k1",
    "epri_m1",
)

# Same categorical palette as docs/study/feeders.js for visual consistency across web and CAD.
PALETTE = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
    "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#393b79", "#ad494a",
    "#637939", "#8c6d31", "#7b4173", "#3182bd", "#e6550d", "#31a354",
)

TEXT_STYLE = cad.TEXT_STYLE


def input_sha256(maps_path: Path = MAPS_JSON) -> str:
    """Fingerprint of results/feeders/feeder_maps.json (stored in each DXF header)."""
    h = hashlib.sha256()
    h.update(maps_path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def dxf_path(feeder_id: str, out_dir: Path = OUT_DIR) -> Path:
    return out_dir / f"oneline_{feeder_id}.dxf"


def asset_id(feeder_id: str) -> str:
    return f"oneline-{feeder_id.replace('_', '-')}-pdf"


def drawn_from(feeder_id: str, out_dir: Path = OUT_DIR) -> str | None:
    p = dxf_path(feeder_id, out_dir)
    if not p.exists():
        return None
    doc = ezdxf.readfile(p)
    return doc.header.custom_vars.get("SHF_INPUT_SHA256")


def _text(space, s: str, xy, height: float, layer: str, align=TextEntityAlignment.LEFT, **attrs):
    t = space.add_text(s, height=height, dxfattribs={"layer": layer, "style": TEXT_STYLE, **attrs})
    t.set_placement(xy, align=align)
    return t


def _add_blocks(doc) -> None:
    byblock = {"color": 0, "lineweight": -2}
    sq = lambda a: [(-a, -a), (a, -a), (a, a), (-a, a)]  # noqa: E731

    b = doc.blocks.new("SOURCE")
    b.add_circle((0, 0), 5.0, dxfattribs=byblock)
    pts = [(-3.0 + 6.0 * i / 20, 1.8 * math.sin(2 * math.pi * i / 20)) for i in range(21)]
    b.add_lwpolyline(pts, dxfattribs=byblock)

    b = doc.blocks.new("RECLOSER")
    b.add_lwpolyline(sq(3.2), close=True, dxfattribs=byblock)
    _text(b, "R", (0, 0), 3.6, "0", TextEntityAlignment.MIDDLE_CENTER, color=0)

    b = doc.blocks.new("SW_NC")
    b.add_lwpolyline(sq(2.6), close=True, dxfattribs=byblock)
    hatch = b.add_hatch(color=0)
    hatch.paths.add_polyline_path(sq(2.6), is_closed=True)


def _fmt_kv(kv: float) -> str:
    if kv < 1:
        return f"{kv:.3f}"
    if float(kv).is_integer():
        return f"{int(kv)}"
    return f"{kv:.2f}".rstrip("0").rstrip(".")


def build_feeder_oneline(feeder_id: str, fdata: dict) -> ezdxf.document.Drawing:
    """Build a deterministic A3 landscape zone-level one-line diagram DXF (units: mm)."""
    doc = ezdxf.new("R2018", setup=True, units=4)   # units: millimetres
    doc.styles.add(TEXT_STYLE, font="arial.ttf")
    doc.header["$LWDISPLAY"] = 1
    doc.header["$LTSCALE"] = 1.0
    doc.header["$PSLTSCALE"] = 0

    base_layers = {
        "BUS-TRUNK": (7, 40, "zone-tree orthogonal trunk connections"),
        "SOURCE": (1, 35, "feeder source / substation"),
        "DEV-RECLOSER": (1, 35, "feeder-head recloser"),
        "DEV-SWITCH": (7, 30, "automated sectionalizing switches"),
        "TEXT-MAIN": (7, 18, "primary labels and zone names"),
        "TEXT-SUB": (8, 13, "secondary metadata (kW, buses, line)"),
        "TABLE": (7, 20, "zone schedule table and legend"),
        "TITLE": (7, 25, "A3 sheet border and title block (paper space)"),
    }
    for name, (aci, lw, desc) in base_layers.items():
        lay = doc.layers.add(name, color=aci, lineweight=lw)
        lay.description = desc

    zones: list[dict] = list(fdata["zones"])
    z_index = {z["name"]: i for i, z in enumerate(zones)}
    zone_rgb = {}
    for i, z in enumerate(zones):
        rgb = cad._rgb(PALETTE[i % len(PALETTE)])
        zone_rgb[z["name"]] = rgb
        lay = doc.layers.add(f"ZONE-{z['name']}", color=7, lineweight=35)
        lay.rgb = rgb
        lay.description = f"zone {z['name']} busbar and symbol"

    _add_blocks(doc)
    msp = doc.modelspace()

    # Depth-first radial order matching docs/study/feeders.js drawOneLine()
    kids: dict[str, list[str]] = {}
    for z in zones:
        par = z.get("parent") or "__src"
        kids.setdefault(par, []).append(z["name"])
    order: list[str] = []
    depth_of: dict[str, int] = {}

    def walk(node: str, d: int) -> None:
        order.append(node)
        depth_of[node] = d
        for ch in kids.get(node, []):
            walk(ch, d + 1)

    walk("__src", 0)
    # Append any orphan zone defensively (never drop a zone)
    for z in zones:
        if z["name"] not in depth_of:
            order.append(z["name"])
            depth_of[z["name"]] = 1

    n_rows = len(order)
    row_h = 14.0 if n_rows <= 12 else (11.5 if n_rows <= 16 else 10.0)
    indent = 14.0
    x0, y_top = 18.0, n_rows * row_h + 26.0
    y_of = {node: y_top - idx * row_h for idx, node in enumerate(order)}
    x_of = {node: x0 + depth_of[node] * indent for node in order}

    # Section heading above tree
    label = str(fdata["label"])
    root_bus = str(fdata["root"])
    kv_s = _fmt_kv(float(fdata["root_kv_ll"]))
    hz_s = f"{int(round(float(fdata['hz'])))}"
    total_kw = sum(float(z["kw"]) for z in zones)
    total_buses = int(fdata.get("buses_drawn", len(fdata.get("buses", []))))

    _text(msp, f"{label.upper()} — ZONE-LEVEL ONE-LINE DIAGRAM",
          (x0 - 4.0, y_top + 14.0), 4.6, "TEXT-MAIN")
    _text(msp, f"Source bus {root_bus} · {kv_s} kV L-L · {hz_s} Hz · {len(zones)} zones · {total_kw:,.0f} kW · {total_buses:,} buses (OpenDSS official model, simulation only)",
          (x0 - 4.0, y_top + 7.5), 2.7, "TEXT-SUB")

    # Source symbol at top of tree
    sx, sy = x_of["__src"], y_of["__src"]
    msp.add_blockref("SOURCE", (sx, sy), dxfattribs={"layer": "SOURCE"})
    _text(msp, f"SOURCE  {root_bus}  ({kv_s} kV · {hz_s} Hz)",
          (sx + 8.5, sy), 3.4, "TEXT-MAIN", TextEntityAlignment.MIDDLE_LEFT)

    # Orthogonal tree wires & zone nodes
    max_tree_x = sx + 95.0
    for node in order[1:]:
        z = zones[z_index[node]]
        par = z.get("parent") or "__src"
        if par not in x_of:
            par = "__src"
        px = x_of[par]
        py = y_of[par] - (5.0 if par == "__src" else 3.0)
        cx, cy = x_of[node], y_of[node]
        lay = f"ZONE-{node}"
        # Vertical trunk drop from parent to child row, then horizontal feed to switch symbol
        msp.add_line((px, py), (px, cy), dxfattribs={"layer": "BUS-TRUNK", "lineweight": 35})
        msp.add_line((px, cy), (cx - 3.2, cy), dxfattribs={"layer": lay, "lineweight": 40})
        # Switch symbol (RECLOSER for head zone attached directly to source, SW_NC otherwise)
        blk = "RECLOSER" if par == "__src" and node == zones[0]["name"] else "SW_NC"
        msp.add_blockref(blk, (cx, cy), dxfattribs={"layer": lay})
        # Short feeder busbar stub extending right of switch
        stub_x = cx + 10.0
        msp.add_line((cx + 3.2, cy), (stub_x, cy), dxfattribs={"layer": lay, "lineweight": 50})
        # Primary zone name + concise engineering specs
        z_kv = _fmt_kv(float(z.get("kv_ll", fdata["root_kv_ll"])))
        z_kw = float(z["kw"])
        z_bus = int(z["buses"])
        z_line = str(z.get("line", ""))
        _text(msp, node, (stub_x + 2.5, cy), 3.4, lay, TextEntityAlignment.MIDDLE_LEFT)
        spec = f"{z_kw:,.0f} kW · {z_bus:,} buses · {z_kv} kV" + (f" · {z_line}" if z_line else "")
        _text(msp, spec, (stub_x + 15.5, cy), 2.5, "TEXT-SUB", TextEntityAlignment.MIDDLE_LEFT)
        max_tree_x = max(max_tree_x, stub_x + 15.5 + len(spec) * 1.65)

    # Zone schedule table to the right of the radial tree
    tx = max(max_tree_x + 14.0, x0 + 148.0)
    col_w = [18.0, 18.0, 34.0, 22.0, 16.0, 16.0]
    headers = ["ZONE", "UPSTREAM", "SWITCH LINE", "LOAD (kW)", "BUSES", "kV"]
    tw = sum(col_w)
    tr_h = 7.2 if len(zones) <= 13 else 6.0
    t_top = y_top + 4.0
    _text(msp, "ZONE SCHEDULE (5%-LOAD PLACEMENT RULE)", (tx, t_top + 4.0), 3.0, "TABLE")

    # Table header row
    msp.add_lwpolyline(
        [(tx, t_top), (tx + tw, t_top), (tx + tw, t_top - tr_h), (tx, t_top - tr_h)],
        close=True, dxfattribs={"layer": "TABLE", "lineweight": 30},
    )
    cx_col = tx
    for h_txt, w in zip(headers, col_w):
        _text(msp, h_txt, (cx_col + 2.0, t_top - tr_h / 2), 2.2, "TABLE", TextEntityAlignment.MIDDLE_LEFT)
        cx_col += w

    # Table body rows
    for idx, z in enumerate(zones):
        ry0 = t_top - (idx + 1) * tr_h
        ry1 = ry0 - tr_h
        msp.add_line((tx, ry1), (tx + tw, ry1), dxfattribs={"layer": "TABLE", "lineweight": 13})
        vals = [
            z["name"],
            z.get("parent") or "Source",
            str(z.get("line", "-"))[:18],
            f"{float(z['kw']):,.0f}",
            f"{int(z['buses']):,}",
            _fmt_kv(float(z.get("kv_ll", fdata["root_kv_ll"]))),
        ]
        cx_col = tx
        for j, (val, w) in enumerate(zip(vals, col_w)):
            align = TextEntityAlignment.MIDDLE_RIGHT if j >= 3 else TextEntityAlignment.MIDDLE_LEFT
            px_t = cx_col + w - 2.0 if j >= 3 else cx_col + 2.0
            lay_t = f"ZONE-{z['name']}" if j == 0 else "TEXT-MAIN"
            _text(msp, val, (px_t, (ry0 + ry1) / 2), 2.2, lay_t, align)
            cx_col += w

    # Table total row & vertical gridlines
    t_bot = t_top - (len(zones) + 1) * tr_h
    tot_bot = t_bot - tr_h
    msp.add_lwpolyline(
        [(tx, t_top), (tx + tw, t_top), (tx + tw, tot_bot), (tx, tot_bot)],
        close=True, dxfattribs={"layer": "TABLE", "lineweight": 25},
    )
    cx_col = tx
    for w in col_w[:-1]:
        cx_col += w
        msp.add_line((cx_col, t_top), (cx_col, tot_bot), dxfattribs={"layer": "TABLE", "lineweight": 13})
    _text(msp, "TOTAL", (tx + 2.0, (t_bot + tot_bot) / 2), 2.3, "TABLE", TextEntityAlignment.MIDDLE_LEFT)
    _text(msp, f"{len(zones)} zones", (tx + col_w[0] + 2.0, (t_bot + tot_bot) / 2), 2.2, "TEXT-SUB", TextEntityAlignment.MIDDLE_LEFT)
    _text(msp, f"{total_kw:,.0f}", (tx + sum(col_w[:4]) - 2.0, (t_bot + tot_bot) / 2), 2.3, "TABLE", TextEntityAlignment.MIDDLE_RIGHT)
    _text(msp, f"{total_buses:,}", (tx + sum(col_w[:5]) - 2.0, (t_bot + tot_bot) / 2), 2.3, "TABLE", TextEntityAlignment.MIDDLE_RIGHT)

    # Compact legend under the zone schedule table
    ly = tot_bot - 9.0
    _text(msp, "LEGEND", (tx, ly), 2.8, "TABLE")
    msp.add_blockref("SOURCE", (tx + 5.5, ly - 8.5), dxfattribs={"layer": "SOURCE"})
    _text(msp, "Substation / feeder source", (tx + 14.0, ly - 8.5), 2.3, "TEXT-SUB", TextEntityAlignment.MIDDLE_LEFT)
    msp.add_blockref("RECLOSER", (tx + 5.5, ly - 18.0), dxfattribs={"layer": "DEV-RECLOSER"})
    _text(msp, "Feeder-head recloser (zone D1)", (tx + 14.0, ly - 18.0), 2.3, "TEXT-SUB", TextEntityAlignment.MIDDLE_LEFT)
    msp.add_blockref("SW_NC", (tx + 5.5, ly - 26.5), dxfattribs={"layer": "DEV-SWITCH"})
    _text(msp, "Automated switch (5%-load placement rule)", (tx + 14.0, ly - 26.5), 2.3, "TEXT-SUB", TextEntityAlignment.MIDDLE_LEFT)

    # Model-space extents & paper-space A3 ONE-LINE layout
    x_min = x0 - 10.0
    x_max = tx + tw + 10.0
    y_min = min(y_of[order[-1]] - 12.0, ly - 34.0)
    y_max = y_top + 22.0
    doc.header["$EXTMIN"] = (x_min, y_min, 0)
    doc.header["$EXTMAX"] = (x_max, y_max, 0)
    doc.set_modelspace_vport(height=(y_max - y_min) * 1.05, center=((x_min + x_max) / 2, (y_min + y_max) / 2))
    _sheet(doc, (x_min, y_min, x_max, y_max), feeder_id, fdata, total_kw, total_buses)
    if "Layout1" in doc.layouts.names():
        doc.layouts.delete("Layout1")
    return doc


def _sheet(doc, ext: tuple[float, float, float, float], feeder_id: str, fdata: dict,
           total_kw: float, total_buses: int) -> None:
    """A3 landscape paper-space layout matching shf/cad.py ('A3 ONE-LINE', 420 x 297 mm)."""
    x0, y0, x1, y1 = ext
    lay = doc.layouts.new("A3 ONE-LINE")
    lay.page_setup(size=(420, 297), margins=(0, 0, 0, 0), units="mm")
    W, H, m, tb = 420.0, 297.0, 10.0, 34.0
    lay.add_lwpolyline([(m, m), (W - m, m), (W - m, H - m), (m, H - m)], close=True,
                       dxfattribs={"layer": "TITLE", "lineweight": 50})
    vw, vh = W - 2 * m - 4.0, H - 2 * m - tb - 6.0
    vc = (W / 2, m + tb + 3.0 + vh / 2)
    view_h = max(y1 - y0, (x1 - x0) * vh / vw) * 1.04
    lay.add_viewport(center=vc, size=(vw, vh), view_center_point=((x0 + x1) / 2, (y0 + y1) / 2), view_height=view_h)
    lay.add_line((m, m + tb), (W - m, m + tb), dxfattribs={"layer": "TITLE", "lineweight": 35})
    cols = [m, 155.0, 255.0, 335.0, W - m]
    for x in cols[1:-1]:
        lay.add_line((x, m), (x, m + tb), dxfattribs={"layer": "TITLE", "lineweight": 25})
    kv_s = _fmt_kv(float(fdata["root_kv_ll"]))
    hz_s = f"{int(round(float(fdata['hz'])))}"
    cells = [
        (f"{str(fdata['label']).upper()} ({kv_s} kV · {hz_s} Hz)",
         [f"Zone-level one-line diagram ({len(fdata['zones'])} FLISR zones)",
          f"{total_kw:,.0f} kW total load · {total_buses:,} buses drawn"]),
        ("PROJECT", ["Self-Healing Feeder (FLISR study)", "Simulation only, not a field drawing"]),
        ("DRAWN FROM", ["results/feeders/feeder_maps.json", f"OpenDSS official circuit ({feeder_id})"]),
        ("SHEET", ["Scale: NTS (zone-tree schematic)", "Author: C. Nguyen · Sheet 1 of 1"]),
    ]
    for (title, lines), xa, _xb in zip(cells, cols, cols[1:]):
        _text(lay, title, (xa + 3.0, m + tb - 7.0), 4.0 if xa == m else 3.0, "TITLE")
        for i, s in enumerate(lines):
            _text(lay, s, (xa + 3.0, m + tb - 16.0 - i * 7.0), 3.1 if xa == m else 2.5, "TITLE")


def export_one(feeder_id: str, out_path: Path | None = None, maps_path: Path = MAPS_JSON) -> Path:
    data = json.loads(maps_path.read_text(encoding="utf-8"))
    if feeder_id not in data["feeders"]:
        raise KeyError(f"feeder {feeder_id!r} not in {maps_path}")
    doc = build_feeder_oneline(feeder_id, data["feeders"][feeder_id])
    doc.header.custom_vars.append("SHF_INPUT_SHA256", input_sha256(maps_path))
    doc.header.custom_vars.append("SHF_SOURCE", "scripts/export_feeder_onelines.py from results/feeders/feeder_maps.json")
    path = out_path or dxf_path(feeder_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fixed = ezdxf.options.write_fixed_meta_data_for_testing
    ezdxf.options.write_fixed_meta_data_for_testing = True
    try:
        doc.saveas(path)
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = fixed
    path.write_text(cad._stable(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    return path


def export_all(out_dir: Path = OUT_DIR, maps_path: Path = MAPS_JSON) -> dict[str, Path]:
    return {fid: export_one(fid, dxf_path(fid, out_dir), maps_path) for fid in OTHER_FEEDERS}
