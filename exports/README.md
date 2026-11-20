# Exports

**Tool:** all apps

**What goes here:** What the report and other tools read: PDF, SVG, DXF, GLB, STEP and CSV files exported from the apps.

**How:** Every file here belongs to an `[[asset]]` in `../workflow.toml`. `registered.json` holds the fingerprints written by `scripts/register_export.py`; do not edit it by hand.

After exporting, register the export so the health check can tell when it goes stale:

```bash
.venv\Scripts\python scripts\register_export.py <id>
```

See [`../workflow.toml`](../workflow.toml) for the rules. Everything here supports a simulation study; none of it is field equipment or field data.
