"""The SolidWorks equipment: every part is a sensible solid list, and each exported glTF is
readable by the report's three.js view (no SolidWorks needed to run these)."""
import json
import struct

import pytest

from shf import config, mech


def _top(p):
    return p["y0"] + p["h"]


@pytest.mark.parametrize("name", list(mech.PARTS))
def test_every_part_is_a_clean_solid_list(name):
    ps = mech.prisms(name)
    assert len({p["name"] for p in ps}) == len(ps)                     # unique names (readable glTF bodies)
    assert all(p["w"] > 0 and p["d"] > 0 and p["h"] > 0 for p in ps)
    assert all(p["group"] in mech.COLORS for p in ps)
    for s in (p for p in ps if p["name"].startswith("Shed")):           # every shed sits on its bushing
        b = next(p for p in ps if p["name"] == "Bushing " + s["name"][5:].rsplit(" ", 1)[0])
        assert b["y0"] < s["y0"] and _top(s) < _top(b) and s["w"] > b["w"] and (s["x"], s["z"]) == (b["x"], b["z"])
    pole = [p for p in ps if p["group"] == "pole"]
    assert len(pole) <= 1                                               # the 3D view hides it by its colour


def test_recloser_parts_fit_together():
    ps = mech.prisms("recloser")
    by = {p["name"]: p for p in ps}
    tank, frame, pole, cab = by["Tank"], by["Frame"], by["Pole"], by["Control cabinet"]
    bushings = [p for p in ps if p["name"].startswith("Bushing")]
    n_shed = config.RECLOSER_MM["shed"][2]
    assert len(bushings) == 6 and len([p for p in ps if p["name"].startswith("Shed")]) == 6 * n_shed
    assert _top(frame) == tank["y0"]                                    # tank sits on its frame
    for b in bushings:                                                  # bushings stand on the tank lid
        assert b["y0"] == _top(tank) and abs(b["x"]) + b["w"] / 2 <= tank["w"] / 2
    assert _top(cab) < frame["y0"]                                      # cabinet hangs below the tank
    assert pole["y0"] < cab["y0"] and _top(pole) > _top(tank)           # the pole carries both
    assert abs((cab["z"] + cab["d"] / 2) - (pole["z"] - pole["w"] / 2)) < 1e-9   # cabinet back touches the pole


def test_auto_switch_has_its_radio():
    names = {p["name"] for p in mech.prisms("auto_switch")}
    assert {"Antenna mast", "Antenna radome"} <= names and "Antenna mast" not in {p["name"] for p in mech.prisms("recloser")}


@pytest.mark.parametrize("name", list(mech.PARTS))
def test_exported_glb_is_readable_by_the_3d_view(name):
    glb = mech.files(name)["glb"]
    if not glb.exists():
        pytest.skip(f"run python scripts/solidworks_build.py --part {name}")
    blob = glb.read_bytes()
    magic, version, length = struct.unpack("<4sII", blob[:12])
    assert magic == b"glTF" and version == 2 and length == len(blob)
    clen, ctype = struct.unpack("<I4s", blob[12:20])
    gltf = json.loads(blob[20:20 + clen])
    assert ctype == b"JSON" and gltf["meshes"]
    colors = {tuple(round(c, 2) for c in m["pbrMetallicRoughness"]["baseColorFactor"][:3]) for m in gltf["materials"]}
    used = {tuple(round(c, 2) for c in mech.COLORS[p["group"]]) for p in mech.prisms(name)}
    assert used <= colors                                               # appearances survived the export
    pos = [a for a in gltf["accessors"] if a.get("type") == "VEC3" and "min" in a]
    top = max(a["max"][1] for a in pos)
    assert abs(top - max(_top(p) for p in mech.prisms(name)) / 1000) < 0.01   # metres, y up


def test_page_gets_only_fresh_models(tmp_path):
    """Runs in a temporary folder: the project's own registry is not touched."""
    from shf import assets, dashboard
    for d in ("mech", "exports"):
        (tmp_path / d).mkdir()
    (tmp_path / "workflow.toml").write_text(
        '[[asset]]\nid = "mech-recloser-glb"\ntool = "SOLIDWORKS"\nsource = "mech/recloser.sldprt"\n'
        'export = "exports/recloser.glb"\nsupports = "test"\n', encoding="utf-8")
    (tmp_path / "mech" / "recloser.sldprt").write_bytes(b"part v1")
    (tmp_path / "exports" / "recloser.glb").write_bytes(b"glb v1")
    assert dashboard.publish_models(tmp_path) == {}                       # exported but not registered
    assets.register("mech-recloser-glb", tmp_path, tmp_path / "workflow.toml", tmp_path / "exports" / "registered.json")
    assert dashboard.publish_models(tmp_path) == {"recloser": "models/recloser.glb"}
    assert (tmp_path / "docs" / "models" / "recloser.glb").read_bytes() == b"glb v1"
    (tmp_path / "mech" / "recloser.sldprt").write_bytes(b"part v2")       # edited after the export
    assert dashboard.publish_models(tmp_path) == {}
    assert not (tmp_path / "docs" / "models" / "recloser.glb").exists()  # the stale copy leaves the page
