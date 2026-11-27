"""The one-line DXF for AutoCAD: drawn from results/, complete, valid and reproducible (no OpenDSS needed)."""
import csv
import json

import ezdxf
from ezdxf import recover

from shf import assets, cad, config


def _results():
    geo = json.loads((config.RESULTS / "feeder_geometry.json").read_text(encoding="utf-8"))
    with open(config.RESULTS / "zones.csv", newline="", encoding="utf-8") as f:
        return geo, list(csv.DictReader(f))


def test_oneline_has_every_zone_device_and_tie(tmp_path):
    geo, zones = _results()
    path = cad.export(tmp_path / "oneline.dxf")
    doc, auditor = recover.readfile(path)
    assert not auditor.errors
    msp = doc.modelspace()
    for z in zones:   # every zone has its own layer with lines on it
        assert doc.layers.has_entry(f"ZONE-{z['zone']}")
        assert len(msp.query(f'LINE[layer=="ZONE-{z["zone"]}"]')) > 0, z["zone"]
    names = {r.get_attrib_text("NAME") for r in msp.query("INSERT") if r.has_attrib("NAME")}
    for name, kind, *_ in geo["devices"]:
        assert (name if kind != "added" else f"{name} (added)") in names
    ties = [r for r in msp.query('INSERT[name=="SW_NO"]') if r.has_attrib("NAME")]
    assert len(ties) == len(geo["ties"])
    assert len(msp.query('INSERT[name=="RECLOSER"]')) >= 1
    assert "A3 ONE-LINE" in doc.layouts.names()
    assert doc.header.custom_vars.get("SHF_INPUT_SHA256") == cad.input_sha256()


def test_oneline_export_is_byte_stable(tmp_path):
    a = cad.export(tmp_path / "a.dxf").read_bytes()
    b = cad.export(tmp_path / "b.dxf").read_bytes()
    assert a == b


def test_committed_oneline_matches_results():
    assert cad.drawn_from() == cad.input_sha256(), "re-run python scripts/export_oneline_dxf.py"


def test_planned_asset_waits_then_tracks_its_generated_input(tmp_path):
    for d in ("cad", "exports"):
        (tmp_path / d).mkdir()
    gen, src, exp = tmp_path / "cad" / "x.dxf", tmp_path / "cad" / "x.dwg", tmp_path / "exports" / "x.pdf"
    gen.write_text("dxf v1", encoding="utf-8")
    manifest, reg = tmp_path / "workflow.toml", tmp_path / "exports" / "registered.json"
    manifest.write_text('[[asset]]\nid = "x"\ntool = "AutoCAD"\nfrom = "cad/x.dxf"\nsource = "cad/x.dwg"\n'
                        'export = "exports/x.pdf"\nsupports = "test"\nplanned = true\n', encoding="utf-8")
    a = assets.load(manifest)[0]
    assert assets.status(a, tmp_path, {})[0] is None          # not made yet: a reminder, not a failure
    src.write_bytes(b"dwg")
    exp.write_bytes(b"pdf")
    assets.register("x", tmp_path, manifest, reg)
    assert assets.status(a, tmp_path, assets.registered(reg))[0] is True
    gen.write_text("dxf v2", encoding="utf-8")                  # the study changed and the DXF was regenerated
    ok, msg = assets.status(a, tmp_path, assets.registered(reg))
    assert ok is False and "regenerated" in msg
    assert ezdxf.__version__


def test_report_shows_the_autocad_drawing_only_when_its_export_is_fresh(tmp_path):
    """Runs in a temporary folder: the project's own workflow.toml and registry are not touched."""
    from shf import dashboard
    for d in ("cad", "exports", "docs/images"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "workflow.toml").write_text(
        '[[asset]]\nid = "oneline-png"\ntool = "AutoCAD"\nfrom = "cad/o.dxf"\nsource = "cad/o.dwg"\n'
        'export = "exports/o.png"\nsupports = "test"\nplanned = true\n', encoding="utf-8")
    (tmp_path / "cad" / "o.dxf").write_text("dxf", encoding="utf-8")
    assert dashboard.oneline_figure(tmp_path) == ""                      # planned: nothing on the page
    (tmp_path / "cad" / "o.dwg").write_bytes(b"dwg")
    (tmp_path / "exports" / "o.png").write_bytes(b"png")
    assert dashboard.oneline_figure(tmp_path) == ""                      # exported but not registered
    assets.register("oneline-png", tmp_path, tmp_path / "workflow.toml", tmp_path / "exports" / "registered.json")
    html = dashboard.oneline_figure(tmp_path)
    assert "images/feeder-oneline.png" in html and "data/feeder_oneline.pdf" not in html
    assert (tmp_path / "docs" / "images" / "feeder-oneline.png").read_bytes() == b"png"
    (tmp_path / "cad" / "o.dxf").write_text("dxf v2", encoding="utf-8")   # study changed: hide the stale drawing
    assert dashboard.oneline_figure(tmp_path) == ""


def test_autocad_plot_commands_keep_names_with_spaces_intact():
    """The AutoLISP -PLOT call quotes every answer, so 'A3 ONE-LINE' and paper names survive."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("autocad_export", config.ROOT / "scripts" / "autocad_export.py")
    ax = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ax)
    vec = ax.plot("DWG To PDF.pc3", "ISO full bleed A3 (420.00 x 297.00 MM)", config.ROOT / "x.pdf", raster=False)
    ras = ax.plot("PublishToWeb PNG.pc3", "QHD (2560.00 x 1440.00 Pixels)", config.ROOT / "x.png", raster=True)
    assert '"A3 ONE-LINE"' in vec and '"ISO full bleed A3 (420.00 x 297.00 MM)"' in vec and '"1:1"' in vec
    assert '"_M"' in vec and '"_M"' not in ras                      # raster plots have no paper-units prompt
    assert '"_E" "_Fit" "_C"' in ras                                # fit the extents, centred
    assert "\\" not in vec and vec.count('"') % 2 == 0            # forward slashes, balanced quotes


def test_other_11_feeder_oneline_dxfs_are_valid_and_stable(tmp_path):
    from shf import feeder_cad
    assert len(feeder_cad.OTHER_FEEDERS) == 11
    maps = json.loads(feeder_cad.MAPS_JSON.read_text(encoding="utf-8"))["feeders"]
    fp = feeder_cad.input_sha256()
    for fid in feeder_cad.OTHER_FEEDERS:
        p = feeder_cad.export_one(fid, tmp_path / f"oneline_{fid}.dxf")
        doc, auditor = recover.readfile(p)
        assert not auditor.errors, f"{fid}: {auditor.errors}"
        assert "A3 ONE-LINE" in doc.layouts.names()
        assert doc.header.custom_vars.get("SHF_INPUT_SHA256") == fp
        for z in maps[fid]["zones"]:
            assert doc.layers.has_entry(f"ZONE-{z['name']}"), (fid, z["name"])
    # Byte-stability check on one multi-branch utility circuit
    a = feeder_cad.export_one("epri_ckt7", tmp_path / "a.dxf").read_bytes()
    b = feeder_cad.export_one("epri_ckt7", tmp_path / "b.dxf").read_bytes()
    assert a == b
    # Committed DXFs match current feeder_maps.json
    for fid in feeder_cad.OTHER_FEEDERS:
        assert feeder_cad.drawn_from(fid) == fp, f"re-run python scripts/export_feeder_onelines.py ({fid})"
