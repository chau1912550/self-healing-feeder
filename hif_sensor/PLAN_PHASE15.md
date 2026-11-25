# Phase 1.5 Pre-Registered Experimental Plan: VeHIF 22 kV Adaptation, Feature Ablation & 50/60 Hz Analysis

Written **before** running `phase15_vehif_adaptation.py` on Kaggle. All metrics, splits, and false-alarm budgets below are fixed in advance; any negative or mixed result will be reported verbatim.

## 1. Scientific Problem

In Phase 0 (`train_kaggle.py`, Kaggle `christoopherchau/ch-y-n`), the 417-parameter (`504 B` int8) Tiny MLP trained on simulated Emanuel downed-conductor arcs achieved **94.7%** detection at **1.5%** normal false-alarm rate (`0.5%` for 51N, `0.0%` for 3rd harmonic).
In Phase 1 (`real_data_test.py`), evaluating that frozen Phase-0 model zero-shot on **250 real 22 kV, 50 Hz vegetation fault recordings** (VeHIF; Gomes & Ozansoy 2022) through the simulated sensor + simulated feeder load dropped overall detection to **56.0%** (`36.2%` in `0–1 A`, `70.0%` in `1–2 A`, `94.7%` in `2–5 A`, `85.7%` in `5–10 A`), with `0.0%` alarms on all 53 real background recordings.

Feature-shift diagnostics (`results/real_vehif.json`) revealed the physical cause: real vegetation faults are substantially more symmetric and steadier cycle-to-cycle than simulated Emanuel ground arcs (`dc_ratio` `-0.49 IQR`, `h2_ratio` `-0.47 IQR`, `even_ratio` `-0.46 IQR`, `I3_cv` `-0.38 IQR`, `ph3_jitter` `-0.38 IQR`).

## 2. Four Pre-Registered Experiments

1. **C Firmware Bit-Parity & Latency Verification (`results/c_firmware_verify.json`)**
   - Compile `firmware/hif_infer.c` + `firmware/test_infer.c` with `gcc -O2 -Wall -Wextra -Werror -lm`.
   - Verify BOTH Phase-0 `firmware/hif_model.h` (6 official vectors + 100 extended vectors) and Phase-1.5 adapted `firmware/hif_model_phase15.h`.
   - **Pass criterion:** `max |p_c - p_py| < 1e-5`, `100%` threshold decision agreement, persistence state machine (`HIF_PERSIST = 3`) pass.

2. **50 Hz (Vietnam / Australia 22 kV) vs 60 Hz (US 12.47 kV) Front-End & Native-Rate Evaluation**
   - Compare exact analog anti-aliasing performance of the same physical `fc = 2,045 Hz` Sallen-Key PCB at `FS_ADC = 12,800 Hz` (50 Hz, Nyquist `6.40 kHz`) vs `FS_ADC = 15,360 Hz` (60 Hz, Nyquist `7.68 kHz`), plus the resistor-retuned 50 Hz BOM (`R × 1.2`).
   - Run the exact same 250 Phase-1 real VeHIF fault recordings + 53 background recordings at native 50 Hz vs resampled 60 Hz sensor rates.

3. **Zero-Shot Feature-Group Ablation (Sim → Real VeHIF)**
   - Train 5 `(len_sub, 16, 8, 1)` int8 MLPs exclusively on Phase-0 simulated data (`N = 4,000`, `seed = 42`, `<= 1.0%` val FA budget):
     - `all_16`: all 16 features (Phase 0 reference)
     - `no_asymmetry_12`: remove top-shifted asymmetry features (`dc_ratio, h2_ratio, even_ratio, even_std`)
     - `no_top_shift_9`: remove top 7 shifted features (`dc_ratio, h2_ratio, even_ratio, even_std, I3_cv, ph3_jitter, I1_cv`)
     - `harmonics_only_7`: harmonic magnitudes/ratios only (`log_I1, log_I3, h2_ratio, h3_ratio, h5_ratio, even_ratio, dc_ratio`)
     - `temporal_only_8`: cycle-to-cycle randomness & trend only (`I3_cv, I1_cv, ph3_jitter, cycle_diff, even_std, h3_trend, I1_trend, interharm`)
   - Measure zero-shot transfer on both simulated test (`800` events) and 250 real VeHIF fault recordings + 53 background recordings.

4. **Few-Shot Real-VeHIF Domain Adaptation (Strict Recording-Level Disjoint Splits, 5 Seeds)**
   - Pool: `300` valid real VeHIF fault recordings (native 50 Hz) + `53` real background recordings + `4,000` Phase-0 simulated events.
   - **Leakage prevention:** Split strictly by **recording ID** (stratified by peak fault current bin) across 5 random seeds (`0..4`):
     - `60%` (`180` fault recordings + `33` background recordings) = **Held-out Real Test Set** (never seen during training, scaling, or threshold picking).
     - `40%` (`120` fault recordings + `20` background recordings) = Adaptation pool, subsampled to **5%** (`15` recordings), **10%** (`30` recordings), and **20%** (`60` recordings).
   - **Strict false-alarm control:** Every adapted model MUST calibrate its threshold to achieve `<= 1.0%` FA on simulated validation events (all 7 disturbances) AND `<= 2.0%` FA on calibration control recordings.
   - **Methods compared (all `<= 504 B` int8 flash footprint):**
     - `zero_shot_phase0`: frozen Phase-0 int8 weights + Phase-0 threshold (`0.982635`).
     - `head_recal_int8`: frozen Layer 1–2 trunk, logistic recalibration of Layer 3 (`9` weights) on Sim + few-shot VeHIF, re-quantized to `504 B` int8.
     - `joint_mlp_int8`: end-to-end `(16, 8)` Tiny MLP trained jointly on Phase-0 simulated windows + few-shot real VeHIF active/control windows, quantized to `504 B` int8 (drop-in replacement for `firmware/hif_infer.c`).
   - **Pre-registered success criteria (reported honestly pass or fail):**
     - **P1.5-A (Low-current real VeHIF gain):** `20%` `joint_mlp_int8` improves held-out `0–2 A` VeHIF detection by at least `+15` percentage points over `zero_shot_phase0`.
     - **P1.5-B (Real background safety):** Held-out real background FA `<= 3.0%` AND real control FA `<= 3.0%`.
     - **P1.5-C (No catastrophic forgetting on simulated disturbances):** Simulated Phase-0 test detection `>= 88.0%` AND simulated test normal FA `<= 3.0%`.
     - **P1.5-D (Firmware bit-parity):** Compiled GCC binary on both Phase-0 and Phase-1.5 `504 B` int8 headers achieves `max |p_c - p_py| < 1e-5` and `100%` decision agreement.
