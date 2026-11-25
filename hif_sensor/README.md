# HIF Sensor: Edge AI High-Impedance Fault Detection (Phase 0, 1 & 1.5)

Downed distribution conductors on dry ground draw only a few amps, below ground-overcurrent pickups.
This project designs a clamp-CT sensor front end and a **417-parameter (`504 B` `int8`)** Tiny MLP (`16→16→8→1`, `PERSIST = 3`) for an ESP32-S3 to recognize the arc signature (asymmetry, even harmonics, cycle-to-cycle randomness).

> **Real Data vs. Simulation Boundary:** Phase 0 uses **simulated** Emanuel arcs (5 surfaces, 7 normal disturbances) and an assumed ADC noise floor. Phase 1 and Phase 1.5 evaluate **real** 22 kV, 50 Hz vegetation-fault (`VeHIF`, 983 tests / 900 valid) and 53 real background recordings (Gomes & Ozansoy 2022, CC0) passed through a **simulated** CT/LPF/ADC sensor front end and **simulated** feeder load. Physical PCB assembly and lab bench testing remain future hardware steps; this is **not** a field test of physical hardware.

## Component & Study Status

| Part | Files | Verified Status (`results/`) |
|---|---|---|
| **Analog front end** (`60 Hz US` & `50 Hz VN/AU`) | [`circuit/front_end_ac.cir`](circuit/front_end_ac.cir), [`circuit/ltspice_results.json`](circuit/ltspice_results.json), [`hif/frontend.py`](hif/frontend.py) | LTspice 26.1.1 verified (60 Hz US, `15.36 kHz` ADC): `fc = 2,045.1 Hz`, `−46.4 dB` @ `7.68 kHz` Nyquist (`46.34 dB` Python IIR), `4.38°` lag, `1.043–2.257 V` swing on 30 A + 15% 3rd + 9 kHz. 50 Hz VN/AU (`12.8 kHz` ADC, `160.0 ms` window): `−39.99 dB` @ `6.40 kHz` Nyquist on same PCB, or **`−46.70 dB`** (`fc = 1,688.73 Hz`) with `R×1.2` (`10.5 kΩ` / `5.36 kΩ`, same PCB & capacitors). |
| **Simulator & 16-feature extractor** | [`hif/waveforms.py`](hif/waveforms.py), [`hif/features.py`](hif/features.py), [`hif/provenance.py`](hif/provenance.py) | Done (`8`-cycle window, `256` samples/cycle, `16` harmonic/asymmetry/temporal features). SHA-256 provenance tracks **23** artifacts ([`results/provenance/manifest.json`](results/provenance/manifest.json)). |
| **Phase 0 (Sim training, LOSO, baselines)** | [`train_kaggle.py`](train_kaggle.py), [`kaggle/hif_phase0.ipynb`](kaggle/hif_phase0.ipynb), [`results/metrics.json`](results/metrics.json) | **Complete on Kaggle:** `94.70%` detection (`396` HIF), `1.49%` normal FA (`404` normal), median delay `5.0` cycles (`p90 = 9.6`), `AUC = 0.9888` (`int8`), vs `51N` `0.51%` (`1.73%` FA) and 3rd harmonic `0.00%` (`0.74%` FA). Unseen-surface LOSO: `93.0%–98.5%`; unseen `arc_welder`: `17.5%` FA vs `0.0%` seen. |
| **Phase 1 (Zero-shot real 22 kV VeHIF)** | [`real_data_test.py`](real_data_test.py), [`results/real_vehif.json`](results/real_vehif.json) | **Complete on Kaggle:** Frozen Phase-0 model scores **`56.0%`** on `250` real VeHIF faults (`120 s` max window; `0–1 A`: `36.2%`, `1–2 A`: `70.0%`, `2–5 A`: `94.7%`, `5–10 A`: `85.7%`, `>10 A`: `100.0%`), **`0.0%`** on `53` real background recordings, `1.2%` control FA, vs `51N` `0.0%` and 3rd harmonic `0.4%`. |
| **Phase 1.5 (50/60 Hz, ablation, few-shot)** | [`PLAN_PHASE15.md`](PLAN_PHASE15.md), [`phase15_vehif_adaptation.py`](phase15_vehif_adaptation.py), [`results/phase15_vehif.json`](results/phase15_vehif.json) | **Complete on Kaggle:** Paired 50/60 Hz check, 5-group feature ablation, and 5-seed recording-disjoint few-shot VeHIF adaptation. Passes **`P1.5-B/C/D`**, **fails `P1.5-A`** (`+7.41 pp` in `0–2 A` vs `>= +15 pp`). |
| **C firmware & GCC parity** | [`firmware/hif_infer.c`](firmware/hif_infer.c), [`firmware/hif_model.h`](firmware/hif_model.h), [`firmware/hif_model_phase15.h`](firmware/hif_model_phase15.h), [`results/c_firmware_verify.json`](results/c_firmware_verify.json) | **Verified with GCC `13.3.0`** (`-O2 -Wall -Wextra -Werror`, `17,032 B` binary): `100%` decision & `PERSIST = 3` agreement across Phase 0 & Phase 1.5 headers, `max \|p_c - p_py\| <= 1.04e-6`, `0.54–0.61 µs/inference`. |

---

## Phase 1.5 Results Summary (Pre-Registered in [`PLAN_PHASE15.md`](PLAN_PHASE15.md))

### 1. 50 Hz (Vietnam / Australia 22 kV) vs. 60 Hz (US 12.47 kV)

| Variant / Evaluation | `FS_ADC` / Nyquist | `fc (-3 dB)` | Nyquist Atten | Sim Detection (FA) | Real VeHIF `250` (`90 s` max) | Real `0–2 A` (`n=188`) | Real `53` Bg FA |
|---|---|---|---|---|---|---|---|
| **60 Hz US (`8.66 / 4.42 kΩ`)** | `15,360` / `7,680 Hz` (`133.33 ms`) | `2,047.93 Hz` | `46.34 dB` | **`94.70%`** (`1.49%`, `n=800`) | **`54.4%`** (ctrl FA `1.2%`) | `43.62%` | `0.0%` |
| **50 Hz VN same PCB (`8.66 / 4.42 kΩ`)** | `12,800` / `6,400 Hz` (`160.0 ms`) | `2,047.93 Hz` | `39.99 dB` | **`94.33%`** (`1.67%`, `n=600`) | **`54.4%`** (ctrl FA `1.2%`) | `43.09%` | `0.0%` |
| **50 Hz VN retuned `R×1.2` (`10.5 / 5.36 kΩ`)** | `12,800` / `6,400 Hz` (`160.0 ms`) | `1,688.73 Hz` | `46.70 dB` | — (same PCB & capacitors) | — | — | — |

*(Note: Phase 1 [`real_vehif.json`](results/real_vehif.json) analyzed up to `120 s` per recording and scored `56.0%`; Phase 1.5 [`phase15_vehif.json`](results/phase15_vehif.json) uses a `90 s` cap per recording and scores `54.4%` at both 50 Hz native and 60 Hz resampled.)*

### 2. Zero-Shot Feature-Group Ablation (50 Hz Native, `250` VeHIF + `53` Background)

| Feature Set | `# Features` | Threshold | Sim Detection (FA) | Real VeHIF (All) | Real `0–2 A` | Control FA / Bg FA |
|---|---|---|---|---|---|---|
| `all_16` | 16 | `0.982635` | `94.70%` (`1.49%`) | `54.4%` | `43.09%` | `1.2%` / `0.0%` |
| `no_asymmetry_12` | 12 | `0.999000` | `40.15%` (`0.99%`) | `22.4%` | `22.34%` | `0.0%` / `0.0%` |
| `no_top_shift_9` | 9 | `0.912502` | `40.66%` (`3.71%`) | `13.2%` | `12.23%` | `0.0%` / `0.0%` |
| `harmonics_only_7` | 7 | `0.952244` | `86.62%` (`1.49%`) | `46.4%` | `31.38%` | `0.0%` / `0.0%` |
| `temporal_only_8` | 8 | `0.914839` | `86.11%` (`2.48%`) | **`55.6%`** | **`51.06%`** | `0.4%` / `0.0%` |

### 3. Few-Shot VeHIF Adaptation (5 Seeds, `60%` Held-Out = `179` Fault / `33` Bg, Recording-ID Disjoint)

| Method & Adaptation Fraction | Real Overall | Real `0–2 A` | Real Bg FA | Real Control FA | Sim Retention (FA) |
|---|---|---|---|---|---|
| `zero_shot_phase0` (`0` recs) | `53.30% ± 1.68%` | `42.52% ± 1.97%` | `0.00%` | `1.12%` | `94.70%` (`1.49%`) |
| `head_recal_int8` (`5%` / `15` recs) | `46.59% ± 3.51%` | `38.67% ± 3.58%` | `0.00%` | `1.23%` | `94.39%` (`1.73%`) |
| `head_recal_int8` (`10%` / `30` recs) | `46.03% ± 0.76%` | `38.37% ± 1.27%` | `0.00%` | `1.23%` | `94.65%` (`1.49%`) |
| `head_recal_int8` (`20%` / `60` recs) | `44.80% ± 1.95%` | `37.19% ± 1.58%` | `0.00%` | `1.23%` | `94.39%` (`1.58%`) |
| `joint_mlp_int8` (`5%` / `15` recs) | `49.50% ± 9.18%` | `40.15% ± 8.12%` | `1.82%` | `0.45%` | `92.12%` (`1.63%`) |
| `joint_mlp_int8` (`10%` / `30` recs) | `56.42% ± 5.25%` | `46.81% ± 6.40%` | `1.21%` | `0.89%` | `93.94%` (`1.88%`) |
| **`joint_mlp_int8` (`20%` / `60` recs)** | **`60.22% ± 10.47%`** | **`49.93% ± 11.87%`** | **`1.82%`** | **`0.67%`** | **`93.84%`** (`1.53%`) |

**Pre-registered Criteria Verdict (`results/phase15_vehif.json`):**
- **`P1.5-A` (Low-current `0–2 A` gain `>= +15 pp`):** **FAIL (`pass: false`)** — `joint_mlp_int8` (`20%`) improved `0–2 A` by **`+7.41 pp`** (`42.52% → 49.93%`; `0–1 A`: `31.02% → 41.63%`), falling short of the `+15 pp` bar.
- **`P1.5-B` (Real background & control FA `<= 3.0%`):** **PASS (`pass: true`)** — `1.82%` bg FA, `0.67%` control FA.
- **`P1.5-C` (No catastrophic forgetting on simulation: `>= 88%` det, `<= 3%` FA):** **PASS (`pass: true`)** — `93.84%` sim detection, `1.53%` sim FA.
- **`P1.5-D` (C firmware bit-parity `max \|p_c - p_py\| < 1e-5`, `100%` agreement):** **PASS (`pass: true`)**.

### 4. GCC `13.3.0` `-O2 -Wall -Wextra -Werror` C Firmware Parity ([`results/c_firmware_verify.json`](results/c_firmware_verify.json))

| Suite | Header (`504 B`, `417` params) | Vectors | `max \|p_c - p_py\|` | `mean \|p_c - p_py\|` | Decision & `PERSIST = 3` | Latency (`100k` iters) |
|---|---|---|---|---|---|---|
| `phase0_official_6_vectors` | `hif_model.h` (`thr=0.982635`) | 6 | `4.77e-7` | `7.95e-8` | `100%` (`6/6`, pass) | `0.5399 µs/inf` |
| `phase0_extended_100_vectors` | `hif_model.h` (`thr=0.982635`) | 100 | `8.34e-7` | `4.34e-8` | `100%` (`100/100`, pass) | `0.6107 µs/inf` |
| `phase15_adapted_100_vectors` | `hif_model_phase15.h` (`thr=0.924894`) | 100 | `1.04e-6` | `1.22e-7` | `100%` (`100/100`, pass) | `0.5685 µs/inf` |

Compiled ELF binary size: `17,032 B` (`exit_code = 0`).

---

## Local Verification & Reproduction

Run these from inside the `hif_sensor/` directory (or standalone `hif-sensor/`):

```bash
python -m hif.provenance --verify    # verifies 23 tracked artifacts & figures (0 changed, 0 missing)
python -m pytest -v tests/test_hif.py # runs all 10 unit/parity/artifact tests
```

*(If running inside `self-healing-feeder/hif_sensor/`, invoke the parent venv Python so root `pytest.ini` does not hijack `testpaths`: `..\.venv\Scripts\python -m hif.provenance --verify && ..\.venv\Scripts\python -m pytest -v tests/test_hif.py`.)*

- Vietnamese walkthrough: [`HUONG_DAN.md`](HUONG_DAN.md)
- Rebuild Kaggle Phase 0/1 notebook after code edits: `python scripts/build_notebook.py`
- Build standalone HTML dashboard: `python scripts/build_dashboard.py` (when inside `self-healing-feeder`, `python -m shf.dashboard` builds both `docs/index.html` and `docs/hif-sensor/index.html`).
