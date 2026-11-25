// Pure C99 DSP pipeline for ESP32-S3 / STM32 HIF Sensor (ADC -> FFT -> 16 arc features).
// Mirrors hif/frontend.py (codes_to_amps) and hif/features.py (window_features).
#include <math.h>
#include <stddef.h>
#include "hif_dsp.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define HIF_EPS 1e-6f

void hif_adc_to_amps(const int16_t *codes, float *amps, int n_samples) {
    const float lsb = HIF_ADC_FS_V / HIF_ADC_MAX_CODE;
    const float inv_gain = 1.0f / HIF_GAIN_V_PER_A;
    for (int i = 0; i < n_samples; i++) {
        amps[i] = ((float)codes[i] * lsb - HIF_VREF_V) * inv_gain;
    }
}

void hif_fft_radix2(float *re, float *im, int n) {
    // Bit-reversal permutation
    int j = 0;
    for (int i = 1; i < n; i++) {
        int bit = n >> 1;
        while (j & bit) {
            j ^= bit;
            bit >>= 1;
        }
        j ^= bit;
        if (i < j) {
            float tr = re[i]; re[i] = re[j]; re[j] = tr;
            float ti = im[i]; im[i] = im[j]; im[j] = ti;
        }
    }
    // Butterfly stages
    for (int len = 2; len <= n; len <<= 1) {
        double ang = -2.0 * M_PI / (double)len;
        float wlen_r = (float)cos(ang);
        float wlen_i = (float)sin(ang);
        int half = len >> 1;
        for (int i = 0; i < n; i += len) {
            float wr = 1.0f;
            float wi = 0.0f;
            for (int k = 0; k < half; k++) {
                int u = i + k;
                int v = u + half;
                float vr = re[v] * wr - im[v] * wi;
                float vi = re[v] * wi + im[v] * wr;
                re[v] = re[u] - vr;
                im[v] = im[u] - vi;
                re[u] += vr;
                im[u] += vi;
                float nwr = wr * wlen_r - wi * wlen_i;
                wi = wr * wlen_i + wi * wlen_r;
                wr = nwr;
            }
        }
    }
}

static float mean_f(const float *a, int n) {
    float s = 0.0f;
    for (int i = 0; i < n; i++) s += a[i];
    return s / (float)n;
}

static float std_pop_f(const float *a, int n, float mu) {
    float s = 0.0f;
    for (int i = 0; i < n; i++) {
        float d = a[i] - mu;
        s += d * d;
    }
    return sqrtf(s / (float)n);
}

void hif_extract_features(const float *window_amps, const float *prev_cycle,
                          float out_features[HIF_N_FEATURES]) {
    float re256[HIF_N_CYCLE], im256[HIF_N_CYCLE];
    float i1[HIF_K_WINDOW], i3[HIF_K_WINDOW];
    float h2_r[HIF_K_WINDOW], h3_r[HIF_K_WINDOW], h5_r[HIF_K_WINDOW];
    float even_r[HIF_K_WINDOW], dc_r[HIF_K_WINDOW], asym[HIF_K_WINDOW];
    float cdiff[HIF_K_WINDOW];
    float ph_cos_sum = 0.0f, ph_sin_sum = 0.0f;
    const float norm = 2.0f / (float)HIF_N_CYCLE;

    for (int c = 0; c < HIF_K_WINDOW; c++) {
        const float *cyc = window_amps + c * HIF_N_CYCLE;
        float cmin = cyc[0], cmax = cyc[0], energy = 0.0f;
        for (int n = 0; n < HIF_N_CYCLE; n++) {
            float v = cyc[n];
            re256[n] = v;
            im256[n] = 0.0f;
            if (v < cmin) cmin = v;
            if (v > cmax) cmax = v;
            energy += v * v;
        }
        energy += HIF_EPS;
        hif_fft_radix2(re256, im256, HIF_N_CYCLE);

        float m0 = fabsf(re256[0] * norm * 0.5f);
        float m1 = hypotf(re256[1], im256[1]) * norm;
        float m2 = hypotf(re256[2], im256[2]) * norm;
        float m3 = hypotf(re256[3], im256[3]) * norm;
        float m4 = hypotf(re256[4], im256[4]) * norm;
        float m5 = hypotf(re256[5], im256[5]) * norm;
        float m6 = hypotf(re256[6], im256[6]) * norm;

        float v_i1 = m1 + HIF_EPS;
        float v_i3 = m3 + HIF_EPS;
        float v_even = m2 + m4 + m6;

        i1[c] = v_i1;
        i3[c] = v_i3;
        h2_r[c] = m2 / v_i1;
        h3_r[c] = v_i3 / v_i1;
        h5_r[c] = m5 / v_i1;
        even_r[c] = v_even / v_i1;
        dc_r[c] = m0 / v_i1;
        asym[c] = (cmax + cmin) / (cmax - cmin + HIF_EPS);

        float a1 = atan2f(im256[1], re256[1]);
        float a3 = atan2f(im256[3], re256[3]);
        float dph = a3 - 3.0f * a1;
        ph_cos_sum += cosf(dph);
        ph_sin_sum += sinf(dph);

        const float *ref = (c > 0) ? (window_amps + (c - 1) * HIF_N_CYCLE) : prev_cycle;
        if (ref != NULL) {
            float ds = 0.0f;
            for (int n = 0; n < HIF_N_CYCLE; n++) {
                float d = cyc[n] - ref[n];
                ds += d * d;
            }
            cdiff[c] = ds / energy;
        } else {
            cdiff[c] = 0.0f;
        }
    }

    // 4-cycle (1024-pt) interharmonic energy ratio (matches P = |rfft(c[-4:])|^2)
    float re1024[4 * HIF_N_CYCLE], im1024[4 * HIF_N_CYCLE];
    const float *last4 = window_amps + (HIF_K_WINDOW - 4) * HIF_N_CYCLE;
    for (int n = 0; n < 4 * HIF_N_CYCLE; n++) {
        re1024[n] = last4[n];
        im1024[n] = 0.0f;
    }
    hif_fft_radix2(re1024, im1024, 4 * HIF_N_CYCLE);
    double p_total = 0.0, p_harm = 0.0;
    const int n_rfft = 2 * HIF_N_CYCLE + 1;  // 513 one-sided bins [0..512]
    for (int k = 0; k < n_rfft; k++) {
        double pk = (double)re1024[k] * (double)re1024[k] + (double)im1024[k] * (double)im1024[k];
        p_total += pk;
        if ((k & 3) == 0) p_harm += pk;
    }

    const int h = HIF_K_WINDOW / 2;
    float mu_i1 = mean_f(i1, HIF_K_WINDOW);
    float mu_i3 = mean_f(i3, HIF_K_WINDOW);
    float mu_ev = mean_f(even_r, HIF_K_WINDOW);
    float R = hypotf(ph_cos_sum / (float)HIF_K_WINDOW, ph_sin_sum / (float)HIF_K_WINDOW);
    if (R < HIF_EPS) R = HIF_EPS;
    if (R > 1.0f) R = 1.0f;

    float h3_first = mean_f(h3_r, h);
    float h3_second = mean_f(h3_r + h, h);
    float i1_first = mean_f(i1, h);
    float i1_second = mean_f(i1 + h, h);

    out_features[0] = log10f(mu_i1);
    out_features[1] = log10f(mu_i3);
    out_features[2] = mean_f(h2_r, HIF_K_WINDOW);
    out_features[3] = mean_f(h3_r, HIF_K_WINDOW);
    out_features[4] = mean_f(h5_r, HIF_K_WINDOW);
    out_features[5] = mu_ev;
    out_features[6] = mean_f(dc_r, HIF_K_WINDOW);
    out_features[7] = mean_f(asym, HIF_K_WINDOW);
    out_features[8] = std_pop_f(i3, HIF_K_WINDOW, mu_i3) / mu_i3;
    out_features[9] = std_pop_f(i1, HIF_K_WINDOW, mu_i1) / mu_i1;
    out_features[10] = sqrtf(-2.0f * logf(R));
    out_features[11] = mean_f(cdiff, HIF_K_WINDOW);
    out_features[12] = std_pop_f(even_r, HIF_K_WINDOW, mu_ev);
    out_features[13] = h3_second - h3_first;
    out_features[14] = log10f(i1_second / i1_first);
    out_features[15] = (float)(1.0 - p_harm / (p_total + (double)HIF_EPS));
}
