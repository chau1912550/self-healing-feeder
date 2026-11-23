# AutoCAD drawings

**Tool:** AutoCAD 2027

**What goes here:** 2D engineering drawings: the one-line diagram of the feeder and its 10 switching zones, and later the wiring of a test bench.

**How:** Start from the DXF that Python writes from the study's data, so bus names and devices match the results:

```bash
.venv\Scripts\python scripts\export_oneline_dxf.py
```

That writes `feeder_oneline.dxf` here: one layer per zone (`ZONE-Sw1` …), devices as blocks with a `NAME` attribute, and an `A3 ONE-LINE` layout with a title block. AutoCAD can do the rest by itself, in the background (it uses `accoreconsole.exe`, the command-line AutoCAD installed with AutoCAD, and leaves any open AutoCAD window alone):

```bash
.venv\Scripts\python scripts\autocad_export.py --register
```

By hand instead: open it, tidy labels, `SAVEAS` `feeder_oneline.dwg`, then plot the `A3 ONE-LINE` layout with `DWG To PDF.pc3` to `../exports/feeder_oneline.pdf` and with `PublishToWeb PNG.pc3` to `../exports/feeder_oneline.png`. Register both: `python scripts/register_export.py oneline-pdf` and `... oneline-png`.

If the study changes, re-run the script: the health check then says the drawing is out of date, and the report hides it until you update the `.dwg` and export again.

After exporting, register the export so the health check can tell when it goes stale:

```bash
.venv\Scripts\python scripts\register_export.py <id>
```

See [`../workflow.toml`](../workflow.toml) for the rules. Everything here supports a simulation study; none of it is field equipment or field data.
