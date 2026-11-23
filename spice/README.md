# LTspice circuits

**Tool:** LTspice

**What goes here:** Time-domain circuits that the phasor power flow in OpenDSS does not model: the DC offset of a fault current, an arcing high-impedance fault, the CT and filter in front of an ADC.

**How:** the schematics are written from the study, so their values always match it:

```bash
.venv\Scripts\python scripts\spice_run.py --register
```

That reads the Thevenin impedance at bus 60 and the feeder-head pre-fault load from OpenDSS, writes the three schematics below, runs LTspice in batch mode (no window), exports the waveforms to `../exports/spice_*.csv`, writes the numbers to `../results/spice/summary.json` and registers the exports.

| File | Circuit |
|---|---|
| `fault_dc_offset.asc` | Per-phase equivalent of the feeder seen from the fault bus: source, Thevenin R and L, the pre-fault load, and a behavioural fault resistor that closes at two instants (no DC offset, largest DC offset) |
| `ct_adc_frontend.asc` | The worst-case fault current through a 1000:1 CT (ideal), a burden resistor on a 1.65 V bias, an RC anti-alias filter and clamp diodes: what a 3.3 V ADC pin would see |
| `ct_secondary.pwl` | Input of the second circuit: the first circuit's worst-case current divided by the CT ratio |
| `hif_arc.asc` | A ground fault at the same bus (source impedance (2 Z1 + Z0)/3 from OpenDSS), drawn twice: on the left an arcing high-impedance fault (two-diode model of Emanuel et al. 1990: it conducts only above an arc voltage, Vp on the positive and Vn on the negative half cycle), on the right the fixed resistance the fault sweep uses. `.step` runs 100 Ω and 400 Ω; the arc resistance is chosen so both sides carry the same RMS current |

Open either `.asc` in LTspice to look at it or run it by hand. To change a circuit, edit `shf/spice.py` (the files here are regenerated). LTspice's own run files (`.raw`, `.log`, `.net`, `.db`) are not kept in git.

After exporting, register the export so the health check can tell when it goes stale:

```bash
.venv\Scripts\python scripts\register_export.py <id>
```

See [`../workflow.toml`](../workflow.toml) for the rules. Everything here supports a simulation study; none of it is field equipment or field data.
