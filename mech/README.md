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

## Technical drawings

Each part also has a dimensioned A3 drawing, sheets SHF-M-01 to SHF-M-06:

- front, right-side and top views, third-angle projection, hidden lines removed;
- the key dimensions from its size table;
- a spec table (what it is used for in the study, system voltage, the assumed rating, main sizes);
- notes and a title block.

`python scripts/export_drawings.py --register` draws `../cad/drawing_<part>.dxf` from the same solids SolidWorks extrudes (`shf/mechdraw.py`). AutoCAD's command-line engine then saves `../cad/drawing_<part>.dwg` and plots `../exports/drawing_<part>.pdf` and `.png`.

The report links the PDFs under its 3D view. A test fails if a drawing no longer matches its size table.

| Sheet | Part | PDF |
|---|---|---|
| SHF-M-01 | Pole-mounted 3-phase recloser | [drawing_recloser.pdf](../exports/drawing_recloser.pdf) |
| SHF-M-02 | Automated sectionalizing switch with radio | [drawing_auto_switch.pdf](../exports/drawing_auto_switch.pdf) |
| SHF-M-03 | Single-phase step voltage regulator | [drawing_regulator.pdf](../exports/drawing_regulator.pdf) |
| SHF-M-04 | Pole-mounted 3-phase capacitor bank | [drawing_capacitor.pdf](../exports/drawing_capacitor.pdf) |
| SHF-M-05 | Single-phase pole-top distribution transformer | [drawing_transformer.pdf](../exports/drawing_transformer.pdf) |
| SHF-M-06 | 4.16 kV source transformer on pad | [drawing_substation.pdf](../exports/drawing_substation.pdf) |
