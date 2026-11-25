// Bit-parity verification & latency benchmark for firmware/hif_infer.c against Python test_vectors.json.
// Compile: gcc -O2 -Wall -Wextra -Werror -I firmware firmware/hif_infer.c firmware/test_infer.c -lm -o build/test_infer
// Run:     ./build/test_infer results/test_vectors.json
#define _POSIX_C_SOURCE 199309L
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "hif_infer.h"

#define MAX_VECTORS 512

typedef struct {
    float features[HIF_N_IN];
    double expected_prob;
    int is_hif;
} TestVec;

static int parse_vectors(const char *path, TestVec *out, int max_n) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "error: cannot open %s\n", path);
        return -1;
    }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = (char *)malloc((size_t)sz + 1);
    if (!buf) {
        fclose(f);
        return -1;
    }
    size_t nread = fread(buf, 1, (size_t)sz, f);
    buf[nread] = '\0';
    fclose(f);

    int count = 0;
    const char *p = buf;
    while (count < max_n && (p = strstr(p, "\"features\"")) != NULL) {
        const char *lb = strchr(p, '[');
        if (!lb) break;
        const char *q = lb + 1;
        int ok = 1;
        for (int i = 0; i < HIF_N_IN; i++) {
            char *endp = NULL;
            double v = strtod(q, &endp);
            if (endp == q) {
                ok = 0;
                break;
            }
            out[count].features[i] = (float)v;
            q = endp;
            while (*q == ' ' || *q == '\t' || *q == '\r' || *q == '\n' || *q == ',') q++;
        }
        const char *pp = strstr(q, "\"prob\"");
        if (!ok || !pp) break;
        const char *colon = strchr(pp, ':');
        if (!colon) break;
        char *endp = NULL;
        out[count].expected_prob = strtod(colon + 1, &endp);
        const char *ph = strstr(endp, "\"is_hif\"");
        out[count].is_hif = (ph && strstr(ph, "true") && (!strstr(ph, "false") || strstr(ph, "true") < strstr(ph, "false"))) ? 1 : 0;
        count++;
        p = endp;
    }
    free(buf);
    return count;
}

static double now_sec(void) {
#if defined(CLOCK_MONOTONIC)
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
#else
    return (double)clock() / (double)CLOCKS_PER_SEC;
#endif
}

int main(int argc, char **argv) {
    const char *vec_path = (argc > 1) ? argv[1] : "results/test_vectors.json";
    TestVec vecs[MAX_VECTORS];
    int n = parse_vectors(vec_path, vecs, MAX_VECTORS);
    if (n <= 0) {
        fprintf(stderr, "error: parsed %d vectors from %s\n", n, vec_path);
        return 2;
    }

    double max_abs_err = 0.0;
    double mean_abs_err = 0.0;
    int decision_matches = 0;
    int pos_idx = -1, neg_idx = -1;

    for (int k = 0; k < n; k++) {
        float got = hif_predict(vecs[k].features);
        double err = fabs((double)got - vecs[k].expected_prob);
        if (err > max_abs_err) max_abs_err = err;
        mean_abs_err += err;
        int c_dec = (got > HIF_THRESHOLD) ? 1 : 0;
        int py_dec = (vecs[k].expected_prob > (double)HIF_THRESHOLD) ? 1 : 0;
        if (c_dec == py_dec) decision_matches++;
        if (c_dec == 1 && pos_idx < 0) pos_idx = k;
        if (c_dec == 0 && neg_idx < 0) neg_idx = k;
    }
    mean_abs_err /= (double)n;

    // Verify persistence state machine (HIF_PERSIST consecutive alarms required, reset clears)
    int persist_ok = 1;
    if (pos_idx >= 0 && neg_idx >= 0) {
        hif_reset();
        for (int s = 0; s < HIF_PERSIST - 1; s++) {
            if (hif_update(vecs[pos_idx].features) != 0) persist_ok = 0;
        }
        if (hif_update(vecs[neg_idx].features) != 0) persist_ok = 0;  // reset on normal window
        for (int s = 0; s < HIF_PERSIST - 1; s++) {
            if (hif_update(vecs[pos_idx].features) != 0) persist_ok = 0;
        }
        if (hif_update(vecs[pos_idx].features) != 1) persist_ok = 0;  // triggers on HIF_PERSIST-th
        hif_reset();
        if (hif_update(vecs[pos_idx].features) != 0) persist_ok = 0;
    } else {
        persist_ok = -1;
    }

    // Latency benchmark (100,000 inferences)
    const int iters = 100000;
    volatile float sink = 0.0f;
    double t0 = now_sec();
    for (int it = 0; it < iters; it++) {
        sink += hif_predict(vecs[it % n].features);
    }
    double dt = now_sec() - t0;
    double us_per_inf = (dt * 1e6) / (double)iters;
    (void)sink;

    int params = HIF_L1_OUT * HIF_L1_IN + HIF_L1_OUT + HIF_L2_OUT * HIF_L2_IN + HIF_L2_OUT + HIF_L3_OUT * HIF_L3_IN + HIF_L3_OUT;
    int model_bytes = HIF_L1_OUT * HIF_L1_IN + 4 * HIF_L1_OUT + 4 +
                      HIF_L2_OUT * HIF_L2_IN + 4 * HIF_L2_OUT + 4 +
                      HIF_L3_OUT * HIF_L3_IN + 4 * HIF_L3_OUT + 4;
    int parity_pass = (max_abs_err < 1e-5 && decision_matches == n && persist_ok == 1);

    printf("{\n");
    printf("  \"vectors_path\": \"%s\",\n", vec_path);
    printf("  \"vectors_tested\": %d,\n", n);
    printf("  \"threshold\": %.6f,\n", (double)HIF_THRESHOLD);
    printf("  \"persist_windows\": %d,\n", HIF_PERSIST);
    printf("  \"params\": %d,\n", params);
    printf("  \"model_bytes_int8_weights_float_bias\": %d,\n", model_bytes);
    printf("  \"max_abs_prob_error\": %.9e,\n", max_abs_err);
    printf("  \"mean_abs_prob_error\": %.9e,\n", mean_abs_err);
    printf("  \"decision_matches\": %d,\n", decision_matches);
    printf("  \"decision_agreement\": %.6f,\n", (double)decision_matches / (double)n);
    printf("  \"persistence_state_machine_pass\": %s,\n", (persist_ok == 1) ? "true" : "false");
    printf("  \"benchmark_iterations\": %d,\n", iters);
    printf("  \"host_latency_us_per_inference\": %.4f,\n", us_per_inf);
    printf("  \"parity_pass\": %s\n", parity_pass ? "true" : "false");
    printf("}\n");

    return parity_pass ? 0 : 1;
}
