// Pure C99 DSP front-end for ESP32-S3 / STM32 HIF Sensor:
// converts 12-bit ADC codes -> primary amps -> 256-pt & 1024-pt Radix-2 FFT -> 16 FEATURES.
// Matches hif/frontend.py and hif/features.py without any external DSP library dependency.
#pragma once

#include <stdint.h>

#define HIF_N_CYCLE 256
#define HIF_K_WINDOW 8
#define HIF_N_FEATURES 16

// Hardware constants matching circuit/front_end_ac.cir and hif/frontend.py
#define HIF_ADC_BITS 12
#define HIF_ADC_MAX_CODE 4095.0f
#define HIF_ADC_FS_V 3.3f
#define HIF_VREF_V 1.65f
#define HIF_GAIN_V_PER_A (33.0f / 2000.0f)

#ifdef __cplusplus
extern "C" {
#endif

// Convert raw 12-bit ADC samples [0..4095] to primary current in amps.
void hif_adc_to_amps(const int16_t *codes, float *amps, int n_samples);

// In-place iterative Cooley-Tukey Radix-2 FFT (n must be a power of 2, e.g. 256 or 1024).
void hif_fft_radix2(float *re, float *im, int n);

// Extract the 16 features of an 8-cycle window (2048 amps samples = HIF_K_WINDOW * HIF_N_CYCLE).
// Optional prev_cycle (256 samples immediately before window_amps[0]) computes cycle_diff[0];
// pass NULL to set cycle_diff[0] = 0.0f (matching hif/features.py on the very first window).
void hif_extract_features(const float *window_amps, const float *prev_cycle,
                          float out_features[HIF_N_FEATURES]);

#ifdef __cplusplus
}
#endif
