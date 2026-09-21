/*
 * ============================================================================
 *  mfcc_lite.h — Lightweight MFCC Feature Extraction for ESP32
 * ============================================================================
 *
 *  Self-contained, header-only implementation.  No external DSP libraries
 *  required — pure C/C++ with float arithmetic only.
 *
 *  Pipeline:  PCM → Pre-emphasis → Framing + Hamming → FFT → Power Spectrum
 *             → Mel Filterbank → Log Compression → DCT-II → MFCCs
 *
 *  ── USAGE EXAMPLE (from echosense.ino) ─────────────────────────────────
 *
 *    #include "mfcc_lite.h"
 *
 *    // After recording 3 seconds of 16 kHz audio into audioBuffer:
 *    //   - 48 000 samples
 *    //   - frame_len = 400 (25 ms), hop = 160 (10 ms)
 *    //   - n_frames  = (48000 - 400) / 160 + 1 = 298
 *    //   - n_mfcc    = 13
 *
 *    const int n_frames = MFCC_NUM_FRAMES(48000, 16000);  // → 298
 *    const int n_mfcc   = 13;
 *
 *    float* mfcc = (float*)malloc(n_frames * n_mfcc * sizeof(float));
 *    if (mfcc) {
 *        compute_mfcc(audioBuffer, 48000, 16000, mfcc, n_mfcc, n_frames);
 *        print_mfcc(mfcc, 5, n_mfcc);   // print first 5 frames for debug
 *        free(mfcc);
 *    }
 *
 * ============================================================================
 */

#ifndef MFCC_LITE_H
#define MFCC_LITE_H

#include <math.h>
#include <string.h>
#include <stdint.h>

#ifdef ARDUINO
#include <Arduino.h>   // for Serial in print_mfcc()
#endif

/* ═══════════════════════════════════════════════════════════════════════════
 *  COMPILE-TIME CONSTANTS
 * ═══════════════════════════════════════════════════════════════════════════ */

#define MFCC_FRAME_MS        25       /* Frame length in milliseconds        */
#define MFCC_HOP_MS          10       /* Hop (stride) in milliseconds        */
#define MFCC_FFT_SIZE        512      /* Radix-2 FFT length (must be 2^N)    */
#define MFCC_N_MEL_FILTERS   13       /* Number of triangular mel filters    */
#define MFCC_PRE_EMPH_COEFF  0.97f    /* Pre-emphasis coefficient            */
#define MFCC_LOG_FLOOR       1e-6f    /* Floor value to avoid log(0)         */

#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif

/* ── Helper macro to compute number of frames from sample count ────────── */
#define MFCC_FRAME_LEN(sr)            ((sr) * MFCC_FRAME_MS / 1000)
#define MFCC_HOP_LEN(sr)              ((sr) * MFCC_HOP_MS   / 1000)
#define MFCC_NUM_FRAMES(n_samples, sr) \
    (((n_samples) - MFCC_FRAME_LEN(sr)) / MFCC_HOP_LEN(sr) + 1)

/* ═══════════════════════════════════════════════════════════════════════════
 *  MEL SCALE CONVERSION
 *  mel  = 2595 · log₁₀(1 + f / 700)        (O'Shaughnessy)
 *  f    = 700 · (10^(mel / 2595) − 1)
 * ═══════════════════════════════════════════════════════════════════════════ */

static inline float _mfcc_hz_to_mel(float hz) {
    return 2595.0f * log10f(1.0f + hz / 700.0f);
}

static inline float _mfcc_mel_to_hz(float mel) {
    return 700.0f * (powf(10.0f, mel / 2595.0f) - 1.0f);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  RADIX-2 COOLEY-TUKEY FFT  (in-place, decimation-in-time)
 *
 *  Operates on separate real / imaginary arrays of length `n`.
 *  `n` MUST be a power of two.
 * ═══════════════════════════════════════════════════════════════════════════ */

static void _mfcc_fft(float* re, float* im, int n) {

    /* ── Step 1: bit-reversal permutation ──────────────────────────────── */
    for (int i = 1, j = 0; i < n; i++) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1)
            j ^= bit;
        j ^= bit;
        if (i < j) {
            float tmp;
            tmp = re[i]; re[i] = re[j]; re[j] = tmp;
            tmp = im[i]; im[i] = im[j]; im[j] = tmp;
        }
    }

    /* ── Step 2: butterfly stages ──────────────────────────────────────── */
    for (int len = 2; len <= n; len <<= 1) {
        float angle = -2.0f * (float)M_PI / (float)len;
        float w_re  = cosf(angle);
        float w_im  = sinf(angle);

        for (int i = 0; i < n; i += len) {
            float cur_re = 1.0f;
            float cur_im = 0.0f;

            for (int j = 0; j < len / 2; j++) {
                int u = i + j;
                int v = u + len / 2;

                /* Twiddle multiplication:  t = W · X[v] */
                float t_re = re[v] * cur_re - im[v] * cur_im;
                float t_im = re[v] * cur_im + im[v] * cur_re;

                /* Butterfly */
                re[v] = re[u] - t_re;
                im[v] = im[u] - t_im;
                re[u] += t_re;
                im[u] += t_im;

                /* Advance twiddle factor */
                float next_re = cur_re * w_re - cur_im * w_im;
                cur_im        = cur_re * w_im + cur_im * w_re;
                cur_re        = next_re;
            }
        }
    }
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  MAIN ENTRY POINT
 *
 *  void compute_mfcc(
 *      const int16_t* pcm,       // raw 16-bit PCM samples
 *      int            n_samples,  // total number of samples
 *      int            sample_rate,// e.g. 16000
 *      float*         out_mfcc,   // output buffer [n_frames × n_mfcc]
 *      int            n_mfcc,     // MFCCs per frame (≤ MFCC_N_MEL_FILTERS)
 *      int            n_frames    // number of frames to compute
 *  );
 *
 *  Memory strategy:  all intermediate buffers are declared `static` so they
 *  live in .bss rather than on the 8 KB task stack.  This makes the function
 *  non-reentrant, which is perfectly safe for single-threaded firmware.
 * ═══════════════════════════════════════════════════════════════════════════ */

static void compute_mfcc(const int16_t* pcm, int n_samples, int sample_rate,
                         float* out_mfcc, int n_mfcc, int n_frames) {

    const int frame_len = sample_rate * MFCC_FRAME_MS / 1000;  /* 400 @ 16 kHz */
    const int hop_len   = sample_rate * MFCC_HOP_MS   / 1000;  /* 160 @ 16 kHz */
    const int fft_size  = MFCC_FFT_SIZE;                        /* 512          */
    const int n_bins    = fft_size / 2 + 1;                     /* 257          */

    /* ── Precompute Hamming window ─────────────────────────────────────
     *  w[n] = 0.54 − 0.46 · cos(2π n / (N−1))    for n ∈ [0, frame_len)
     *  Positions beyond frame_len are zero (zero-pad zone).                 */
    static float hamming[MFCC_FFT_SIZE];
    for (int i = 0; i < frame_len; i++) {
        hamming[i] = 0.54f - 0.46f * cosf(2.0f * (float)M_PI * (float)i
                                           / (float)(frame_len - 1));
    }
    for (int i = frame_len; i < fft_size; i++) {
        hamming[i] = 0.0f;
    }

    /* ── Precompute mel filterbank centre bins ─────────────────────────
     *  13 triangular filters need 15 boundary points (low, centres, high)
     *  evenly spaced on the mel scale between 0 Hz and Nyquist.             */
    const int n_filter_points = MFCC_N_MEL_FILTERS + 2;  /* 15 */
    float mel_low  = _mfcc_hz_to_mel(0.0f);
    float mel_high = _mfcc_hz_to_mel((float)sample_rate / 2.0f);

    static float hz_points[MFCC_N_MEL_FILTERS + 2];
    static int   bin_points[MFCC_N_MEL_FILTERS + 2];

    for (int i = 0; i < n_filter_points; i++) {
        float mel = mel_low + (mel_high - mel_low) * (float)i
                    / (float)(n_filter_points - 1);
        hz_points[i]  = _mfcc_mel_to_hz(mel);
        bin_points[i] = (int)floorf(((float)fft_size + 1.0f)
                                    * hz_points[i] / (float)sample_rate);
        /* Clamp to valid FFT bin range */
        if (bin_points[i] < 0)       bin_points[i] = 0;
        if (bin_points[i] >= n_bins) bin_points[i] = n_bins - 1;
    }

    /* ── Working buffers (static → .bss, not stack) ────────────────── */
    static float fft_re[MFCC_FFT_SIZE];
    static float fft_im[MFCC_FFT_SIZE];
    static float power_spec[MFCC_FFT_SIZE / 2 + 1];
    static float mel_energies[MFCC_N_MEL_FILTERS];

    /* ═════════════════════════════════════════════════════════════════
     *  FRAME PROCESSING LOOP
     * ═════════════════════════════════════════════════════════════════ */
    for (int f = 0; f < n_frames; f++) {
        int frame_start = f * hop_len;

        /* ── 1. Pre-emphasis + Hamming window ────────────────────────
         *  y[n] = x[n] − 0.97 · x[n−1]
         *  Pre-emphasis is computed on-the-fly from the original PCM
         *  to avoid allocating a full float copy of the signal.
         *  The Hamming window is applied simultaneously.               */
        for (int i = 0; i < fft_size; i++) {
            int idx = frame_start + i;
            float sample = 0.0f;

            if (i < frame_len && idx < n_samples) {
                float x_n    = (float)pcm[idx];
                float x_prev = (idx > 0) ? (float)pcm[idx - 1] : 0.0f;
                sample = x_n - MFCC_PRE_EMPH_COEFF * x_prev;
            }
            /* Zero-pad region (i >= frame_len) stays 0.0 */

            fft_re[i] = sample * hamming[i];
            fft_im[i] = 0.0f;
        }

        /* ── 2. FFT ──────────────────────────────────────────────── */
        _mfcc_fft(fft_re, fft_im, fft_size);

        /* ── 3. Power spectrum:  |X[k]|² / N ────────────────────── */
        for (int k = 0; k < n_bins; k++) {
            power_spec[k] = (fft_re[k] * fft_re[k]
                           + fft_im[k] * fft_im[k]) / (float)fft_size;
        }

        /* ── 4. Mel filterbank ───────────────────────────────────────
         *  Each filter m is a triangle spanning bins
         *    [bin_points[m], bin_points[m+1], bin_points[m+2]]
         *
         *         /\            Rising slope:  (k − start) / (centre − start)
         *        /  \           Falling slope: (end − k)   / (end − centre)
         *       /    \
         *  ----/------\----
         *  start centre end                                                   */
        for (int m = 0; m < MFCC_N_MEL_FILTERS; m++) {
            mel_energies[m] = 0.0f;

            int f_start  = bin_points[m];
            int f_centre = bin_points[m + 1];
            int f_end    = bin_points[m + 2];

            /* Rising slope: start → centre */
            int denom_rise = f_centre - f_start;
            if (denom_rise > 0) {
                for (int k = f_start; k <= f_centre && k < n_bins; k++) {
                    float weight = (float)(k - f_start) / (float)denom_rise;
                    mel_energies[m] += power_spec[k] * weight;
                }
            }

            /* Falling slope: centre → end */
            int denom_fall = f_end - f_centre;
            if (denom_fall > 0) {
                for (int k = f_centre + 1; k <= f_end && k < n_bins; k++) {
                    float weight = (float)(f_end - k) / (float)denom_fall;
                    mel_energies[m] += power_spec[k] * weight;
                }
            }
        }

        /* ── 5. Log compression ──────────────────────────────────── */
        for (int m = 0; m < MFCC_N_MEL_FILTERS; m++) {
            mel_energies[m] = logf(mel_energies[m] + MFCC_LOG_FLOOR);
        }

        /* ── 6. DCT Type-II → MFCCs ─────────────────────────────────
         *  C[k] = Σ_{n=0}^{N-1} x[n] · cos( π/N · (n + 0.5) · k )
         *
         *  We compute only the first n_mfcc coefficients.              */
        int n_out = (n_mfcc <= MFCC_N_MEL_FILTERS) ? n_mfcc
                                                    : MFCC_N_MEL_FILTERS;
        float* row = &out_mfcc[f * n_mfcc];

        for (int k = 0; k < n_out; k++) {
            float sum = 0.0f;
            for (int n = 0; n < MFCC_N_MEL_FILTERS; n++) {
                sum += mel_energies[n]
                     * cosf((float)M_PI / (float)MFCC_N_MEL_FILTERS
                            * ((float)n + 0.5f) * (float)k);
            }
            row[k] = sum;
        }

        /* Zero-fill any extra coefficients if n_mfcc > N_MEL_FILTERS */
        for (int k = n_out; k < n_mfcc; k++) {
            row[k] = 0.0f;
        }
    }
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  DELTA AND DELTA-DELTA COEFFICIENTS
 *
 *  Delta (velocity):  delta[t] = (x[t+1] - x[t-1]) / 2
 *  Delta-delta (acceleration): delta2[t] = (delta[t+1] - delta[t-1]) / 2
 *
 *  These capture temporal dynamics of spectral features, useful for
 *  improved classification accuracy.
 * ═══════════════════════════════════════════════════════════════════════════ */

static void compute_delta(const float* mfcc, float* delta, int n_frames, int n_mfcc) {
    for (int t = 0; t < n_frames; t++) {
        for (int c = 0; c < n_mfcc; c++) {
            if (t == 0) {
                /* First frame: use forward difference */
                delta[t * n_mfcc + c] = mfcc[(t + 1) * n_mfcc + c] - mfcc[t * n_mfcc + c];
            } else if (t == n_frames - 1) {
                /* Last frame: use backward difference */
                delta[t * n_mfcc + c] = mfcc[t * n_mfcc + c] - mfcc[(t - 1) * n_mfcc + c];
            } else {
                /* Middle frames: central difference */
                delta[t * n_mfcc + c] = (mfcc[(t + 1) * n_mfcc + c] - mfcc[(t - 1) * n_mfcc + c]) / 2.0f;
            }
        }
    }
}

static void compute_delta_delta(const float* mfcc, const float* delta, float* delta2, int n_frames, int n_mfcc) {
    for (int t = 0; t < n_frames; t++) {
        for (int c = 0; c < n_mfcc; c++) {
            if (t == 0) {
                /* First frame: use forward difference of delta */
                delta2[t * n_mfcc + c] = delta[(t + 1) * n_mfcc + c] - delta[t * n_mfcc + c];
            } else if (t == n_frames - 1) {
                /* Last frame: use backward difference of delta */
                delta2[t * n_mfcc + c] = delta[t * n_mfcc + c] - delta[(t - 1) * n_mfcc + c];
            } else {
                /* Middle frames: central difference of delta */
                delta2[t * n_mfcc + c] = (delta[(t + 1) * n_mfcc + c] - delta[(t - 1) * n_mfcc + c]) / 2.0f;
            }
        }
    }
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  DEBUG PRINTER
 *
 *  Prints the MFCC matrix over Serial in a tabular format.
 *  Call with a subset of frames (e.g. first 5) to avoid flooding the
 *  serial monitor.
 * ═══════════════════════════════════════════════════════════════════════════ */

#ifdef ARDUINO
static void print_mfcc(const float* mfcc, int n_frames, int n_mfcc) {
    Serial.println("┌──────────────────────────────────────────────────────┐");
    Serial.printf( "│  MFCC Matrix  [%d frames × %d coefficients]         │\n",
                   n_frames, n_mfcc);
    Serial.println("├──────────────────────────────────────────────────────┤");

    /* Column headers */
    Serial.print("│ Frame ");
    for (int c = 0; c < n_mfcc; c++) {
        Serial.printf("  C%-4d", c);
    }
    Serial.println();
    Serial.println("├───────────────────────────────────────────────────────");

    /* Data rows */
    for (int f = 0; f < n_frames; f++) {
        Serial.printf("│ %5d ", f);
        for (int c = 0; c < n_mfcc; c++) {
            Serial.printf("%7.2f", mfcc[f * n_mfcc + c]);
        }
        Serial.println();
    }

    Serial.println("└──────────────────────────────────────────────────────┘");
}
#else
/* Non-Arduino fallback using printf */
#include <stdio.h>
static void print_mfcc(const float* mfcc, int n_frames, int n_mfcc) {
    printf("MFCC Matrix [%d frames x %d coefficients]\n", n_frames, n_mfcc);
    for (int f = 0; f < n_frames; f++) {
        printf("Frame %3d: ", f);
        for (int c = 0; c < n_mfcc; c++) {
            printf("%8.3f ", mfcc[f * n_mfcc + c]);
        }
        printf("\n");
    }
}
#endif

#endif /* MFCC_LITE_H */
