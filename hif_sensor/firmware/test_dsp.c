// End-to-end C99 verification: raw ADC codes -> hif_adc_to_amps -> hif_extract_features -> hif_predict.
// Compile: gcc -O2 -Wall -Wextra -Werror -I firmware firmware/hif_dsp.c firmware/hif_infer.c firmware/test_dsp.c -lm -o build/test_dsp
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include "hif_dsp.h"
#include "hif_infer.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static int16_t amps_to_code(float a) {
    float v = a * HIF_GAIN_V_PER_A + HIF_VREF_V;
    if (v < 0.0f) v = 0.0f;
    if (v > HIF_ADC_FS_V) v = HIF_ADC_FS_V;
    int code = (int)lroundf(v / (HIF_ADC_FS_V / HIF_ADC_MAX_CODE));
    if (code < 0) code = 0;
    if (code > 4095) code = 4095;
    return (int16_t)code;
}

int main(void) {
    const int n_total = HIF_K_WINDOW * HIF_N_CYCLE;
    int16_t codes_norm[HIF_K_WINDOW * HIF_N_CYCLE];
    int16_t codes_arc[HIF_K_WINDOW * HIF_N_CYCLE];
    float amps_norm[HIF_K_WINDOW * HIF_N_CYCLE];
    float amps_arc[HIF_K_WINDOW * HIF_N_CYCLE];
    float feat_norm[HIF_N_FEATURES], feat_arc[HIF_N_FEATURES];

    // 1. Clean 10 A peak fundamental + 20% 3rd harmonic (normal steady feeder load)
    for (int i = 0; i < n_total; i++) {
        double ph = 2.0 * M_PI * (double)(i % HIF_N_CYCLE) / (double)HIF_N_CYCLE;
        float y = (float)(10.0 * sin(ph) + 2.0 * sin(3.0 * ph));
        codes_norm[i] = amps_to_code(y);
    }

    // 2. Asymmetric, jittering arc-like waveform (strong even/DC + cycle-to-cycle change)
    for (int c = 0; c < HIF_K_WINDOW; c++) {
        double scale = 1.0 + 0.18 * ((c % 2 == 0) ? 1.0 : -1.0);
        for (int n = 0; n < HIF_N_CYCLE; n++) {
            double ph = 2.0 * M_PI * (double)n / (double)HIF_N_CYCLE;
            double s = sin(ph);
            double arc = (s > 0.35) ? (4.0 * scale * (s - 0.35))
                       : ((s < -0.55) ? (2.5 * scale * (s + 0.55)) : 0.0);
            codes_arc[c * HIF_N_CYCLE + n] = amps_to_code((float)(6.0 * s + arc));
        }
    }

    hif_adc_to_amps(codes_norm, amps_norm, n_total);
    hif_adc_to_amps(codes_arc, amps_arc, n_total);
    hif_extract_features(amps_norm, NULL, feat_norm);
    hif_extract_features(amps_arc, NULL, feat_arc);

    int ok = 1;
    for (int f = 0; f < HIF_N_FEATURES; f++) {
        if (!isfinite(feat_norm[f]) || !isfinite(feat_arc[f])) ok = 0;
    }
    // Clean sine check: log10(10) ~ 1.0, h3_ratio ~ 0.20, h2_ratio < 0.01, interharm < 0.01
    if (fabsf(feat_norm[0] - 1.0f) > 0.02f) ok = 0;
    if (fabsf(feat_norm[3] - 0.20f) > 0.02f) ok = 0;
    if (feat_norm[2] > 0.01f || feat_norm[15] > 0.01f) ok = 0;
    // Arc check: stronger even harmonics & cycle_diff than normal
    if (!(feat_arc[5] > feat_norm[5] + 0.02f)) ok = 0;
    if (!(feat_arc[11] > feat_norm[11] + 0.005f)) ok = 0;

    float p_norm = hif_predict(feat_norm);
    float p_arc = hif_predict(feat_arc);
    if (!isfinite(p_norm) || !isfinite(p_arc) || !(p_arc > p_norm)) ok = 0;

    printf("{\"dsp_pipeline_pass\": %s, \"norm_logI1\": %.4f, \"norm_h3\": %.4f, "
           "\"arc_even\": %.4f, \"p_norm\": %.6f, \"p_arc\": %.6f}\n",
           ok ? "true" : "false", feat_norm[0], feat_norm[3], feat_arc[5], p_norm, p_arc);
    return ok ? 0 : 1;
}
