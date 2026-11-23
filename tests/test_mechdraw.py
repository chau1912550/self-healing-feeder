"""Technical drawings of the SolidWorks parts: built from the same solids, fresh, dimensioned."""
import pytest

from shf import config, mech, mechdraw


@pytest.mark.parametrize("name", list(mech.PARTS))
def test_drawing_builds_with_views_dimensions_and_title_block(name):
    doc = mechdraw.build(name)
    msp = doc.modelspace()
    assert len(msp.query("LWPOLYLINE[layer=='VISIBLE']")) > 10            # the three views
    assert len(msp.query("DIMENSION")) >= 4                              # overall W, H, D + features
    sheet = doc.layouts.get("A3 DRAWING")
    texts = " ".join(e.dxf.text for e in sheet.query("TEXT"))
    assert f"config.{mechdraw.TABLES[name]}" in texts and "not a manufacturer's design" in texts
    scale = next(e.dxf.text for e in sheet.query("TEXT") if e.dxf.text.startswith("1:"))
    assert int(scale.split()[0][2:]) in mechdraw.SCALES


@pytest.mark.parametrize("name", list(mech.PARTS))
def test_committed_drawing_matches_the_current_part(name):
    if not mechdraw.path(name).exists():
        pytest.skip("run python scripts/export_drawings.py")
    assert mechdraw.drawn_from(name) == mechdraw.input_sha256(name), \
        f"cad/drawing_{name}.dxf is stale: python scripts/export_drawings.py --part {name} --register"


def test_hidden_lines_are_removed():
    """A small box in front of a big one hides the part of the big box's outline behind it."""
    big = ("rect", (0, 0, 100, 100), 0.0, None)
    small = ("rect", (40, -10, 60, 10), 5.0, None)                      # nearer, covers part of the bottom edge
    lines = mechdraw.visible_segments([big, small], 1.0)
    bottom = [p for ln in lines for p in ln if abs(p[1]) < 1e-9 and 41 < p[0] < 59]
    assert not bottom


def test_dimensions_quote_the_size_table():
    """The tank width dimension on the recloser equals config.RECLOSER_MM."""
    doc = mechdraw.build("recloser")
    measured = sorted(round(d.get_measurement()) for d in doc.modelspace().query("DIMENSION"))
    assert config.RECLOSER_MM["tank"][0] in measured and config.RECLOSER_MM["phase_spacing"] in measured
