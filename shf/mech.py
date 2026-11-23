"""Generic equipment for the report's 3D view, built in SolidWorks over its COM API.

Each part is a list of vertical prisms (boxes and cylinders) computed from its size table in
config.py, so it is reproducible and testable without SolidWorks. `build(name)` drives
SolidWorks: one sketch on the Top Plane and one extrusion per prism (separate bodies, named
and coloured), then saves mech/<name>.sldprt and exports STEP, binary glTF (.glb, metres,
y up) for three.js, and a PNG preview.

    python scripts/solidworks_build.py --part all --register

Parts: recloser (Sw1), auto_switch (A1-A5), regulator, capacitor, transformer (pole top),
substation. Sizes are illustrative (ASSUMPTION in config.py): none is a manufacturer's design.
Pole-mounted parts carry a short pole segment for context; the 3D view hides it (brown).
"""
from __future__ import annotations

import time
from pathlib import Path

from . import config

EXPORTS = config.ROOT / "exports"
TEMPLATE = Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2026\templates\Part.PRTDOT")
SW_TYPELIB = ("{83A33D31-27C5-11CE-BFD4-00400513BB57}", 0, 34, 0)

COLORS = {  # RGB 0-1, one appearance per group
    "tank": (0.55, 0.58, 0.62), "frame": (0.62, 0.64, 0.67), "bushing": (0.80, 0.80, 0.78),
    "terminal": (0.80, 0.52, 0.22), "pole": (0.45, 0.33, 0.20), "cabinet": (0.86, 0.86, 0.82),
    "antenna": (0.20, 0.20, 0.22), "can": (0.90, 0.90, 0.88), "concrete": (0.70, 0.70, 0.68),
}
POLE_RGB = COLORS["pole"]


def _box(name, group, x, z, w, d, y0, h):
    return dict(name=name, group=group, shape="box", x=x, z=z, w=w, d=d, y0=y0, h=h)


def _cyl(name, group, x, z, dia, y0, h):
    return dict(name=name, group=group, shape="cyl", x=x, z=z, w=dia, d=dia, y0=y0, h=h)


def _bushing(out, tag, x, z, y0, bushing, shed, terminal):
    """A bushing (core + sheds + terminal stud) standing on y0."""
    bd, bh = bushing
    sd, st, sn = shed
    out.append(_cyl(f"Bushing {tag}", "bushing", x, z, bd, y0, bh))
    for s in range(sn):
        out.append(_cyl(f"Shed {tag} {s + 1}", "bushing", x, z, sd, y0 + bh * (s + 1) / (sn + 1) - st / 2, st))
    out.append(_cyl(f"Terminal {tag}", "terminal", x, z, terminal[0], y0 + bh, terminal[1]))


def _pole(out, m, top):
    pd, ph = m["pole"]
    out.append(_cyl("Pole", "pole", 0, m["pole_z"], pd, top - ph, ph))


# ---------------------------------------------------------------- the parts
def _pole_device(m: dict) -> list[dict]:
    """Recloser or automated switch: tank on a frame, 3 phases x source/load bushings, a control
    cabinet lower on the pole; an `antenna` entry adds a radio mast with a radome."""
    tw, td, th = m["tank"]
    fw, fd, fh = m["frame"]
    pd, _ = m["pole"]
    pz = m["pole_z"]
    cw, cd, ch = m["cabinet"]
    out = [
        _box("Tank", "tank", 0, 0, tw, td, 0, th),
        _box("Frame", "frame", 0, 0, fw, fd, -fh, fh),
        _box("Frame arm", "frame", 0, (fd / 2 + pz - pd / 2) / 2, 200, pz - pd / 2 - fd / 2, -fh, fh),
        _box("Control cabinet", "cabinet", 0, pz - pd / 2 - cd / 2, cw, cd, m["cabinet_top"] - ch, ch),
    ]
    _pole(out, m, 1200)
    for i, side in enumerate(("Source", "Load")):
        z = -m["bushing_row"] if i == 0 else m["bushing_row"]
        for k, phase in enumerate("ABC"):
            _bushing(out, f"{side} {phase}", (k - 1) * m["phase_spacing"], z, th, m["bushing"], m["shed"], m["terminal"])
    if "antenna" in m:
        ad, ah = m["antenna"]
        rd, rh = m["radome"]
        ax, az = tw / 2 - 60, td / 2 - 60
        out.append(_cyl("Antenna mast", "antenna", ax, az, ad, th, ah))
        out.append(_cyl("Antenna radome", "antenna", ax, az, rd, th + ah, rh))
    return out


def _regulator(m: dict) -> list[dict]:
    bw, bd, bh = m["base"]
    tdia, th = m["tank"]
    ldia, lh = m["lid"]
    ft, freach, fh, fn = m["fin"]
    r = tdia / 2
    out = [_box("Base", "frame", 0, 0, bw, bd, 0, bh),
           _cyl("Tank", "tank", 0, 0, tdia, bh, th),
           _cyl("Lid", "tank", 0, 0, ldia, bh + th, lh)]
    fy = bh + (th - fh) / 2
    for k in range(fn):                      # radiator fins on all four sides
        off = (k - (fn - 1) / 2) * 200
        out.append(_box(f"Fin +x {k + 1}", "tank", r + freach / 2 - 20, off, freach, ft, fy, fh))
        out.append(_box(f"Fin -x {k + 1}", "tank", -(r + freach / 2 - 20), off, freach, ft, fy, fh))
        out.append(_box(f"Fin +z {k + 1}", "tank", off, r + freach / 2 - 20, ft, freach, fy, fh))
    top = bh + th + lh
    for tag, x in zip(("S", "L", "SL"), m["bushing_x"]):
        _bushing(out, tag, x, 0, top, m["bushing"], m["shed"], m["terminal"])
    iw, idp, ih = m["indicator"]
    out.append(_box("Position indicator", "cabinet", 0, -(ldia / 2 - idp), iw, idp, top, ih))
    cw, cd, ch = m["cabinet"]
    cz = -(r + 120 + cd / 2)
    out.append(_box("Control cabinet", "cabinet", 0, cz, cw, cd, bh + 200, ch))
    out.append(_box("Cabinet bracket", "frame", 0, -(r + 60), 80, 140, bh + 200 + ch / 2, 60))
    return out


def _capacitor(m: dict) -> list[dict]:
    rw, rd, rh = m["rack"]
    cw, cd, ch = m["can"]
    pd, _ = m["pole"]
    pz = m["pole_z"]
    out = [_box("Rack", "frame", 0, 0, rw, rd, -rh, rh),
           _box("Rack arm", "frame", 0, (rd / 2 + pz - pd / 2) / 2, 200, pz - pd / 2 - rd / 2, -rh, rh)]
    _pole(out, m, 1200)
    for phase, x in zip("ABC", m["can_x"]):
        out.append(_box(f"Capacitor can {phase}", "can", x, 0, cw, cd, 0, ch))
        _bushing(out, phase, x, 0, ch, m["bushing"], m["shed"], m["terminal"])
    return out


def _transformer(m: dict) -> list[dict]:
    tdia, th = m["tank"]
    ldia, lh = m["lid"]
    out = [_cyl("Tank", "tank", 0, 0, tdia, 0, th), _cyl("Lid", "tank", 0, 0, ldia, th, lh)]
    _pole(out, m, 1500)
    for i, x in enumerate(m["hv_x"]):
        _bushing(out, f"HV {i + 1}", x, m["hv_z"], th + lh, m["hv_bushing"], m["hv_shed"], m["terminal"])
    for i, x in enumerate(m["lv_x"]):
        out.append(_cyl(f"LV bushing {i + 1}", "bushing", x, m["lv_z"], m["lv_bushing"][0], th + lh, m["lv_bushing"][1]))
    hw, hd, hh = m["hanger"]
    pd, _ = m["pole"]
    out.append(_box("Hanger", "frame", 0, (tdia / 2 + m["pole_z"] - pd / 2) / 2, hw, m["pole_z"] - pd / 2 - tdia / 2 + 50,
                    th / 2 - hh / 2, hh))
    return out


def _substation(m: dict) -> list[dict]:
    pw, pdp, ph = m["pad"]
    tw, td, th = m["tank"]
    ft, freach, fh, fn = m["radiator"]
    out = [_box("Pad", "concrete", 0, 0, pw, pdp, 0, ph), _box("Main tank", "tank", 0, 0, tw, td, ph, th)]
    fy = ph + (th - fh) / 2
    for k in range(fn):
        off = (k - (fn - 1) / 2) * (td - 300) / (fn - 1)
        out.append(_box(f"Radiator +x {k + 1}", "tank", tw / 2 + freach / 2, off, freach, ft, fy, fh))
        out.append(_box(f"Radiator -x {k + 1}", "tank", -(tw / 2 + freach / 2), off, freach, ft, fy, fh))
    top = ph + th
    for i, x in enumerate(m["hv_x"]):
        _bushing(out, f"HV {i + 1}", x, m["hv_z"], top, m["hv_bushing"], m["hv_shed"], m["terminal"])
    for i, x in enumerate(m["lv_x"]):
        _bushing(out, f"LV {i + 1}", x, m["lv_z"], top, m["lv_bushing"], m["lv_shed"], m["terminal"])
    cdia, chh = m["conservator"]
    out.append(_cyl("Conservator", "tank", tw / 2 - cdia / 2 - 50, 0, cdia, top, chh))
    cw, cd, ch = m["cabinet"]
    out.append(_box("Control cabinet", "cabinet", tw / 4, -(td / 2 + cd / 2), cw, cd, ph + 300, ch))
    return out


PARTS = {
    "recloser": lambda: _pole_device(config.RECLOSER_MM),
    "auto_switch": lambda: _pole_device(config.AUTO_SWITCH_MM),
    "regulator": lambda: _regulator(config.REGULATOR_MM),
    "capacitor": lambda: _capacitor(config.CAPACITOR_MM),
    "transformer": lambda: _transformer(config.TRANSFORMER_MM),
    "substation": lambda: _substation(config.SUBSTATION_MM),
}


def prisms(name: str = "recloser") -> list[dict]:
    """Every solid of a part as a vertical prism: {name, group, shape, x, z, w, d, y0, h} in mm
    ('box' uses w x d, 'cyl' uses w as the diameter). y is up."""
    return PARTS[name]()


def files(name: str) -> dict[str, Path]:
    return {"sldprt": config.MECH_DIR / f"{name}.sldprt", "step": EXPORTS / f"{name}.step",
            "glb": EXPORTS / f"{name}.glb", "png": EXPORTS / f"{name}.png"}


GLB = files("recloser")["glb"]   # kept for the recloser tests


# ---------------------------------------------------------------- SolidWorks
def connect():
    """Attach to the running SolidWorks (or start it) with typed COM wrappers."""
    import pythoncom
    import win32com.client
    from win32com.client import gencache
    mod = gencache.EnsureModule(*SW_TYPELIB)
    pythoncom.CoInitialize()
    raw = win32com.client.Dispatch("SldWorks.Application")
    sw = mod.ISldWorks(raw._oleobj_)
    sw.Visible = True
    return mod, sw


def _variant_doubles(values):
    import pythoncom
    import win32com.client
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(v) for v in values])


def build(name: str = "recloser", log=print) -> dict:
    """Build one part in SolidWorks and write SLDPRT, STEP, GLB and PNG. Returns a summary."""
    mod, sw = connect()
    log(f"SolidWorks {sw.RevisionNumber()}: building {name}")
    sw.CloseDoc(files(name)["sldprt"].name)          # a copy left open by an earlier run would lock the file
    doc = sw.NewDocument(str(TEMPLATE), 0, 0, 0)
    if doc is None:
        raise RuntimeError(f"SolidWorks could not open the part template {TEMPLATE}")
    part = mod.IModelDoc2(doc._oleobj_)
    ext = mod.IModelDocExtension(part.Extension._oleobj_)
    skm = mod.ISketchManager(part.SketchManager._oleobj_)
    fm = mod.IFeatureManager(part.FeatureManager._oleobj_)
    skm.AddToDB = True                  # draw exactly the numbers given, no snapping
    made = []
    for p in prisms(name):
        part.ClearSelection2(True)
        if not ext.SelectByID2("Top Plane", "PLANE", 0, 0, 0, False, 0, None, 0):
            raise RuntimeError("could not select the Top Plane")
        skm.InsertSketch(True)
        x, y = p["x"] / 1000, -p["z"] / 1000          # Top Plane sketch: x = X, y = -Z
        if p["shape"] == "box":
            seg = skm.CreateCenterRectangle(x, y, 0, x + p["w"] / 2000, y + p["d"] / 2000, 0)
        else:
            seg = skm.CreateCircleByRadius(x, y, 0, p["w"] / 2000)
        if seg is None:
            raise RuntimeError(f"sketch failed for {p['name']}")
        skm.InsertSketch(True)                        # close the sketch (it stays selected)
        y0 = p["y0"] / 1000
        feat = fm.FeatureExtrusion3(
            True, False, False,                       # one direction, no flip, no 2nd direction
            0, 0, p["h"] / 1000, 0,                   # blind, depth
            False, False, False, False, 0, 0,         # no draft
            False, False, False, False,               # offsets / translate surface
            False, True, True,                        # merge = False (separate bodies), feature scope, auto-select
            3 if y0 else 0, abs(y0), y0 < 0)          # start at an offset from the plane
        if feat is None:
            raise RuntimeError(f"extrusion failed for {p['name']}")
        feat = mod.IFeature(feat._oleobj_)
        feat.Name = p["name"]
        r, g, b = COLORS[p["group"]]
        feat.SetMaterialPropertyValues2(_variant_doubles([r, g, b, 1, 1, 0.5, 0.4, 0, 0]), 2, None)
        made.append(p["name"])
    part.ClearSelection2(True)
    bodies = mod.IPartDoc(doc._oleobj_).GetBodies2(0, False) or []
    for body, bname in zip(bodies, made):     # readable body names
        try:
            mod.IBody2(body._oleobj_).Name = bname
        except Exception:  # noqa: BLE001  (a body name is cosmetic)
            pass
    part.ShowNamedView2("*Isometric", 7)
    part.ViewZoomtofit2()
    part.ForceRebuild3(False)
    out = {}
    for kind, path in files(name).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        err = part.SaveAs3(str(path), 0, 1)          # silent
        time.sleep(0.5)
        out[path.name] = {"error": err, "exists": path.exists(), "bytes": path.stat().st_size if path.exists() else 0}
    sw.CloseDoc(part.GetTitle())                      # leave the user's SolidWorks tidy
    return {"part": name, "solids": len(made), "bodies": len(bodies), "files": out}
