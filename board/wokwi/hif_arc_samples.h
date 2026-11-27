// Deterministic C99 12-bit ADC waveform generator for the Wokwi ESP32 HIF demo.
// Generates 8-cycle (2048-sample) or 10-cycle (2560-sample, for HIF_PERSIST=3 sliding windows)
// primary-current waveforms quantized through the same CT/ADC scaling as hif_dsp.h and
// hif_sensor/hif/frontend.py (GAIN = 33/2000 V/A, VREF = 1.65 V, 12-bit 0..4095, FS = 3.3 V).
//
// Simulation only: Emanuel 2-diode arcing parameters follow the published ranges in
// hif_sensor/hif/waveforms.py (not field recordings). On-the-fly generation avoids storing
// multi-kilobyte raw PCM tables in Flash.
#pragma once

#include <math.h>
#include <stdint.h>
#include "hif_dsp.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define HIF_DEMO_WINDOW_SAMPLES (HIF_K_WINDOW * HIF_N_CYCLE)
#define HIF_DEMO_PERSIST_CYCLES (HIF_K_WINDOW + 2)
#define HIF_DEMO_STREAM_SAMPLES (HIF_DEMO_PERSIST_CYCLES * HIF_N_CYCLE)
#define HIF_DEMO_SEED 0x5A17C991u

#ifdef __cplusplus
extern "C" {
#endif

static inline float hif_lcg_unit(uint32_t *state) {
    *state = (*state) * 1664525u + 1013904223u;
    return (float)((*state) >> 8) / 16777216.0f;
}

static inline int16_t hif_amps_to_adc_code(float amps) {
    float v = amps * HIF_GAIN_V_PER_A + HIF_VREF_V;
    if (v < 0.0f) v = 0.0f;
    if (v > HIF_ADC_FS_V) v = HIF_ADC_FS_V;
    int code = (int)lroundf(v / (HIF_ADC_FS_V / HIF_ADC_MAX_CODE));
    if (code < 0) code = 0;
    if (code > 4095) code = 4095;
    return (int16_t)code;
}

// Generate n_cycles * HIF_N_CYCLE (n_cycles * 256) 12-bit ADC samples.
//   is_arc = 1: asymmetric Emanuel 2-diode HIF arc + unbalanced feeder load + ~1 LSB ADC noise.
//   is_arc = 0: steady unbalanced feeder load + ~1 LSB ADC noise (no arc, zero false alarm).
static inline void hif_gen_cycles(int16_t *codes, int n_cycles, int is_arc, uint32_t seed) {
    uint32_t st = seed;
    const float v_phase_pk = 10182.3376f;  // 12.47 kV / sqrt(3) * sqrt(2)
    const float two_pi = (float)(2.0 * M_PI);
    const float inv_n = 1.0f / (float)HIF_N_CYCLE;

    for (int c = 0; c < n_cycles; c++) {
        float u1 = hif_lcg_unit(&st);
        float u2 = hif_lcg_unit(&st);
        float u3 = hif_lcg_unit(&st);
        float u4 = hif_lcg_unit(&st);
        float u5 = hif_lcg_unit(&st);

        // Asymmetric Emanuel thresholds & path resistances with half-cycle jitter
        float vp = 1400.0f * (1.0f + 0.14f * (2.0f * u1 - 1.0f));
        float vn = 2150.0f * (1.0f + 0.14f * (2.0f * u2 - 1.0f));
        float rp = 520.0f * (1.0f + 0.14f * (2.0f * u3 - 1.0f));
        float rn = 680.0f * (1.0f + 0.14f * (2.0f * u4 - 1.0f));
        float cyc_mod = 0.72f + 0.56f * u5;

        for (int n = 0; n < HIF_N_CYCLE; n++) {
            float ph = two_pi * (float)n * inv_n;
            // Background unbalanced feeder load: 8.5 A pk fundamental + 18% 3rd + 5% 5th
            float i_base = 8.5f * sinf(ph)
                         + 1.53f * sinf(3.0f * ph + 0.25f)
                         + 0.42f * sinf(5.0f * ph - 0.15f);
            float noise_a = (hif_lcg_unit(&st) - 0.5f) * 0.08f;
            float i_arc = 0.0f;
            if (is_arc) {
                float v = v_phase_pk * sinf(ph + 0.18f);
                if (v > vp) {
                    i_arc = cyc_mod * (v - vp) / rp;
                } else if (v < -vn) {
                    i_arc = cyc_mod * (v + vn) / rn;
                }
            }
            codes[c * HIF_N_CYCLE + n] = hif_amps_to_adc_code(i_base + i_arc + noise_a);
        }
    }
}

static inline void hif_gen_arc_window(int16_t codes[HIF_DEMO_WINDOW_SAMPLES]) {
    hif_gen_cycles(codes, HIF_K_WINDOW, 1, HIF_DEMO_SEED);
}

static inline void hif_gen_normal_window(int16_t codes[HIF_DEMO_WINDOW_SAMPLES]) {
    hif_gen_cycles(codes, HIF_K_WINDOW, 0, HIF_DEMO_SEED);
}

#ifdef __cplusplus
}
#endif
