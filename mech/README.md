# SolidWorks parts

**Tool:** SolidWorks 2026

**What goes here:** 3D models of equipment: a pole-mounted recloser with its control cabinet, or the enclosure of a test bench.

**How:** Save parts and assemblies here (`.sldprt`, `.sldasm`). Export `.glb` (for the 3D page) and `.step` to `../exports/`. Keep real-world scale (millimetres).

After exporting, register the export so the health check can tell when it goes stale:

```bash
.venv\Scripts\python scripts\register_export.py <id>
```

See [`../workflow.toml`](../workflow.toml) for the rules. Everything here supports a simulation study; none of it is field equipment or field data.
