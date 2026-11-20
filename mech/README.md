# SolidWorks parts

**Tool:** SolidWorks 2026

**What goes here:** 3D models of equipment: a pole-mounted recloser with its control cabinet, or the enclosure of a test bench.

**How:** the recloser is built by a script that drives SolidWorks over its COM API (SolidWorks must be installed; it attaches to an open SolidWorks window, so do not click in it while the script runs):

```bash
.venv\Scripts\python scripts\solidworks_build.py --part all --register
```

Six generic parts, each from its size table in `config.py` (illustrative sizes, not any manufacturer's design):

| Part | Size table | Stands in for |
|---|---|---|
| `recloser` | `RECLOSER_MM` | Sw1, the feeder-head recloser |
| `auto_switch` | `AUTO_SWITCH_MM` | the five added automated switches (with a radio antenna) |
| `regulator` | `REGULATOR_MM` | each single-phase regulator (Reg 1 to Reg 4) |
| `capacitor` | `CAPACITOR_MM` | the 3-phase capacitor bank C83 |
| `transformer` | `TRANSFORMER_MM` | every pole-top distribution transformer |
| `substation` | `SUBSTATION_MM` | the 4.16 kV source transformer |

For each part the script draws one sketch and one extrusion per solid, saves `<part>.sldprt` here and exports `../exports/<part>.step`, `<part>.glb` (glTF 2.0, metres, y up) and `<part>.png`. The report copies a `.glb` to `docs/models/` only while its export is registered and fresh, and the 3D view swaps it in for the drawn stand-in. Switch and tie blades stay drawn in code, because the fault replay opens and closes them. Use `--part <name>` to rebuild one part.

After exporting, register the export so the health check can tell when it goes stale:

```bash
.venv\Scripts\python scripts\register_export.py <id>
```

See [`../workflow.toml`](../workflow.toml) for the rules. Everything here supports a simulation study; none of it is field equipment or field data.
