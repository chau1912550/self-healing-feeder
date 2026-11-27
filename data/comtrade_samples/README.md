# COMTRADE Sample & Verification Suite (`data/comtrade_samples/`)

Short guide to the two IEEE C37.111 COMTRADE sample sets used to verify `shf/comtrade.py` and `scripts/comtrade_ingest.py`:

1. **`public/`** — 5 open-source IEEE C37.111-1999 & 2013 recordings (ASCII & BINARY, 50/60 Hz, primary & secondary CT/PT scaling) downloaded from public MIT / CC0-1.0 repositories. These come from external grids and test parser compatibility and feature conversion; they are **not** utility field events on the IEEE 123-bus feeder.
2. **`synthetic_roundtrip/`** — **simulation-only** COMTRADE files exported from our own OpenDSS IEEE 123-bus model (3 multi-device 10-switch events), LTspice waveforms (`exports/spice_fault_current.csv`, `exports/spice_hif.csv`), and the Tier-1 Emanuel arcing HIF simulator (`shf.hif_edge`). Used to prove closed-loop feature and prediction parity before any real utility records are provided.

---

## 1. Public Open-Source Samples (`public/`)

| File | Standard & Format | Freq / `fs` / Samples | Source Repository (Commit) | License | SHA-256 |
|---|---|---|---|---|---|
| `fdr2214_ag_fault.cfg` | IEEE C37.111-2013, ASCII | 50 Hz / 4800 Hz / 2400 (25 cyc) | [`sagswell/comtrade-sample-files`](https://github.com/sagswell/comtrade-sample-files/blob/3333a8cf6b523c07f28d1b9a4e88a4cc19b8e9eb/FDR-2214_AG-FAULT/FDR-2214_AG-FAULT.cfg) (`3333a8c`) | CC0-1.0 | `0e8c5d4216363dcdca8ce1cccae961b96cffb71c87c0f3ce8de70ea56caf7a54` |
| `fdr2214_ag_fault.dat` | Paired ASCII data (VA–VC, IA–IC, A-G fault) | 50 Hz / 4800 Hz / 2400 | [`sagswell/comtrade-sample-files`](https://github.com/sagswell/comtrade-sample-files/blob/3333a8cf6b523c07f28d1b9a4e88a4cc19b8e9eb/FDR-2214_AG-FAULT/FDR-2214_AG-FAULT.dat) (`3333a8c`) | CC0-1.0 | `83ba21dd85a2f96b204182d2f8a6b521f4f9f983ca18986cd294653ef7611005` |
| `wisp_relay_bin.cfg` | IEEE C37.111-1999, BINARY (`nrates=0`, 24A/64D, `S`) | 50 Hz / ~800 Hz / 1360 (85 cyc) | [`Esticonv/Wisp.Comtrade`](https://github.com/Esticonv/Wisp.Comtrade/blob/004f3f8ac35cbaea0a7be808f511d5f1ca93fe19/ComtradeTests/ExampleSet2/3.cfg) (`004f3f8`) | MIT | `12c143be3e24050c04786fd1856a0148d33ff2cdf2489684207951330bee3871` |
| `wisp_relay_bin.dat` | Paired BINARY data (`F1-IA..F7-VC`, CT 1000:1, PT 190740:57.8) | 50 Hz / ~800 Hz / 1360 | [`Esticonv/Wisp.Comtrade`](https://github.com/Esticonv/Wisp.Comtrade/blob/004f3f8ac35cbaea0a7be808f511d5f1ca93fe19/ComtradeTests/ExampleSet2/3.dat) (`004f3f8`) | MIT | `361a3d676c12dac1bf963af27a7445132fed0adea242d3c5e794b3ebb49377f9` |
| `sample_ascii.cfg` | IEEE C37.111-2013, ASCII (`S`, CT 933:1) | 60 Hz / 1200 Hz / 40 (2 cyc) | [`dparrini/python-comtrade`](https://github.com/dparrini/python-comtrade/blob/1714f3a7fad071b149012e1de474a1bcddee6c59/tests/sample_files/sample_ascii.cfg) (`1714f3a`) | MIT | `45ff4ba994bd473f99d20d4d6a10890474600b60393b770a5afe110f4c991c47` |
| `sample_ascii.dat` | Paired ASCII data (IA, IB, IC, 3I0) | 60 Hz / 1200 Hz / 40 | [`dparrini/python-comtrade`](https://github.com/dparrini/python-comtrade/blob/1714f3a7fad071b149012e1de474a1bcddee6c59/tests/sample_files/sample_ascii.dat) (`1714f3a`) | MIT | `8674c7619591861964fd0e894cbcdc7634547954636cac2eedec869ccf361743` |
| `sample_iso8859-1_bin.cfg` | IEEE C37.111-2013, BINARY (ISO-8859-1, `timemult!=1`) | 60 Hz / 1200 Hz / 40 (2 cyc) | [`dparrini/python-comtrade`](https://github.com/dparrini/python-comtrade/blob/1714f3a7fad071b149012e1de474a1bcddee6c59/tests/sample_files/sample_iso8859-1_bin.cfg) (`1714f3a`) | MIT | `e572f27f12a21ed0f244d8a76ccc5a4196723980b910e185dbd66beafe5a3db8` |
| `sample_iso8859-1_bin.dat` | Paired BINARY data (IA, IB, IC, 3I0) | 60 Hz / 1200 Hz / 40 | [`dparrini/python-comtrade`](https://github.com/dparrini/python-comtrade/blob/1714f3a7fad071b149012e1de474a1bcddee6c59/tests/sample_files/sample_iso8859-1_bin.dat) (`1714f3a`) | MIT | `ff8f1717bab510972844578b8396582428e8591a104802e35b91236c5a11ed92` |
| `sample_bin.cfg` | IEEE C37.111-1999, BINARY (`P`, short smoke sample) | 60 Hz / 15360 Hz / 5 (<1 cyc) | [`dparrini/python-comtrade`](https://github.com/dparrini/python-comtrade/blob/1714f3a7fad071b149012e1de474a1bcddee6c59/tests/sample_files/sample_bin.cfg) (`1714f3a`) | MIT | `4e94ae8d7147a8695224b5639d826a2e5cec71016247ab1996774c4beadfcc62` |
| `sample_bin.dat` | Paired BINARY data (VA, VB, VC, VN) | 60 Hz / 15360 Hz / 5 | [`dparrini/python-comtrade`](https://github.com/dparrini/python-comtrade/blob/1714f3a7fad071b149012e1de474a1bcddee6c59/tests/sample_files/sample_bin.dat) (`1714f3a`) | MIT | `b804e25150ccd63aafcda3494c45c9cc5149b65880be3b9b883107e260059131` |

---

## 2. Simulation Round-Trip Samples (`synthetic_roundtrip/`) — Simulation Only

Generated deterministically by `scripts/comtrade_ingest.py --verify-samples` (metadata & ground-truth hashes stored in `synthetic_roundtrip/manifest.json`):

| Suite | Contents | Format & Scale | Purpose |
|---|---|---|---|
| `opendss_ieee123_bus60_slg1_ascii/` | 10 devices (`Sw1..L77`) + `channel_map.json`, SLG 1 Ω at bus 60 (zone `Sw2`) | 2013 ASCII, `S` (CT 1000:1, PT 2401.8:120), 60 Hz, 3840 Hz | Multi-device folder + `channel_map.json` parity against OpenDSS (`Tier-2 rel err = 3.0e-7`, 3/3 model match) |
| `opendss_ieee123_bus18_slg25_bin/` | 10 devices (`Sw1..L77`), SLG 25 Ω at bus 18 (zone `L13`) | 1999 BINARY, `P`, 60 Hz, 3840 Hz | BINARY 16-bit multi-device parity (`Tier-2 rel err = 7.3e-6`, 3/3 model match) |
| `opendss_ieee123_bus76_3ph_bin/` | 10 devices (`Sw1..L77`), 3PH 0.01 Ω at bus 76 (zone `Sw4`) | 2013 BINARY, `S`, 60 Hz, 3840 Hz | High-current bolted 3-phase BINARY parity (`Tier-2 rel err = 1.18e-4`, 3/3 model match) |
| `ltspice_bus60_bolted_ascii.{cfg,dat}` | Export of `exports/spice_fault_current.csv` (bus 60 bolted fault) | 2013 ASCII, 60 Hz, 50 kHz, 7501 samples | Matches `results/spice/summary.json` steady fault RMS (`6119.06 A`, `0.0001%` err) |
| `ltspice_bus60_hif_arc_bin.{cfg,dat}` | Export of `exports/spice_hif.csv` (bus 60 Emanuel arc 100/400 Ω) | 1999 BINARY, 60 Hz, 50 kHz, 5001 samples | Matches `i1_arc` (`23.425 A`, `0.0000%` err) and verifies short-record guard (6 cyc < K=8) |
| `sim_hif_arc_15360hz_bin.{cfg,dat}` | Simulated Emanuel arcing HIF (`shf.hif_edge.make_event`, seed 42) | 2013 BINARY, 60 Hz, 15.36 kHz, 60 cycles | End-to-end Tier-1 16-feature (`1.1e-5` max abs err) + frozen 504 B `int8` MLP (`p_hif = 0.999998`, `0.0` err) |

---

## 3. Running on Real Utility COMTRADE Files (1 Command)

When real relay/recloser `.cfg` + `.dat` files become available, no code edits are required:

```bash
# Single relay/recloser file:
.venv\Scripts\python scripts/comtrade_ingest.py path/to/event.cfg --v-base-kv 22.0 --out-features out.json

# Multi-device event folder + custom channel map JSON:
.venv\Scripts\python scripts/comtrade_ingest.py path/to/event_folder --channel-map path/to/channel_map.json

# Re-run full sample verification + lock SHA-256 provenance:
.venv\Scripts\python scripts/comtrade_ingest.py --verify-samples
```

> **Honest limitation:** Models in `models/` were trained on simulated IEEE 123-bus (4.16 kV, 60 Hz) OpenDSS events. A single-device record populates only 15/150 Tier-2 features (135 `NaN`) and cannot reliably localize across feeder zones; field deployment requires multi-device records from the target feeder and field validation with confirmed fault locations.
