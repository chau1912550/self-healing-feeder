// Public C API for the HIF tiny MLP inference engine (ESP32-S3 / STM32 / host tests).
#pragma once

#ifndef HIF_MODEL_HEADER
#define HIF_MODEL_HEADER "hif_model.h"
#endif
#include HIF_MODEL_HEADER

#ifdef __cplusplus
extern "C" {
#endif

// Predict HIF probability [0, 1] from 16 window features (same order as FEATURES in hif/features.py).
float hif_predict(const float x[HIF_N_IN]);

// Call once per power cycle. Returns 1 when HIF_PERSIST consecutive windows exceed HIF_THRESHOLD.
int hif_update(const float x[HIF_N_IN]);

// Reset internal persistence counter to 0 (call between independent events or after latch reset).
void hif_reset(void);

#ifdef __cplusplus
}
#endif
