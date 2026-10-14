/* SPDX-License-Identifier: GPL-3.0-only */
/* Exact integer/state regression for #219. The reference retains the original
 * flattened L/R offsets, but in a real flat array so its accesses are defined. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define RING_PUBLISH() __asm__ volatile("" ::: "memory")
#define FELUCCA_OTA 0
#define FELUCCA_CDC 1
#define FELUCCA_UAC 1
static void fm1_delay_ms(uint32_t ms) { (void)ms; }
#pragma GCC diagnostic ignored "-Wint-to-pointer-cast"
#include "../firmware/src/usb.c"

typedef struct {
    __typeof__(rs) history;
    __typeof__(uac) stream;
    uint32_t ring[UA_N], w, r;
} Snapshot;
static unsigned checks;

static void require(int ok, const char *what)
{
    checks++;
    if (!ok) {
        fprintf(stderr, "FIR bounds/equivalence: %s (check %u)\n", what, checks);
        exit(1);
    }
}

static void save(Snapshot *s)
{
    memcpy(&s->history, &rs, sizeof rs);
    memcpy(&s->stream, &uac, sizeof uac);
    memcpy(s->ring, ua_ring, sizeof ua_ring);
    s->w = ua_w;
    s->r = ua_r;
}

static void load(const Snapshot *s)
{
    memcpy(&rs, &s->history, sizeof rs);
    memcpy(&uac, &s->stream, sizeof uac);
    memcpy(ua_ring, s->ring, sizeof ua_ring);
    ua_w = s->w;
    ua_r = s->r;
}

static void equal(const Snapshot *a, const Snapshot *b)
{
    require(!memcmp(&a->history, &b->history, sizeof rs), "complete rs state");
    require(!memcmp(&a->stream, &b->stream, sizeof uac), "complete uac state");
    require(a->w == b->w && a->r == b->r, "ring publication/consumption indices");
    require(!memcmp(a->ring, b->ring, sizeof ua_ring), "complete stereo ring, including untouched slots");
}

static void reference48(const int32_t *out, uint32_t n)
{
    int16_t flat[4u * RS_H];
    uint32_t w = ua_w, h = rs.w, ph = rs.ph, k = 0, i, j;
    if (UA_N - (w - ua_r) < n + n / 8u + 2u) {
        uac.overruns++;
        return;
    }
    memcpy(flat, rs.l, sizeof rs.l);
    memcpy(flat + 2u * RS_H, rs.r, sizeof rs.r);
    for (i = 0; i < n; i++) {
        uint32_t s = h & (RS_H - 1u);
        int16_t l = (int16_t)uac_s16(out[2u * i]);
        int16_t r = (int16_t)uac_s16(out[2u * i + 1u]);
        flat[s] = flat[s + RS_H] = l;
        flat[2u * RS_H + s] = flat[3u * RS_H + s] = r;
        h++;
        s = (h - UAC_FIR_N) & (RS_H - 1u);
        do {
            int64_t al = 0, ar = 0;
            for (j = 0; j < UAC_FIR_N; j++) {
                int32_t t = ph < UAC_FIR_L / 2u ? UAC_FIR[ph][j] :
                    UAC_FIR[UAC_FIR_L - 1u - ph][UAC_FIR_N - 1u - j];
                al += (int64_t)t * flat[s + j];
                ar += (int64_t)t * flat[s + j + 2u * RS_H];
            }
            int32_t lout = uac_s16((int32_t)((al + (1 << (UAC_FIR_Q - 1))) >> UAC_FIR_Q));
            int32_t rout = uac_s16((int32_t)((ar + (1 << (UAC_FIR_Q - 1))) >> UAC_FIR_Q));
            ua_ring[(w + k++) & (UA_N - 1u)] = (uint32_t)(uint16_t)lout | (uint32_t)(uint16_t)rout << 16;
            ph += UAC_FIR_M;
        } while (ph < UAC_FIR_L);
        ph -= UAC_FIR_L;
    }
    memcpy(rs.l, flat, sizeof rs.l);
    memcpy(rs.r, flat + 2u * RS_H, sizeof rs.r);
    rs.w = h;
    rs.ph = ph;
    RING_PUBLISH();
    ua_w = w + k;
}

static void reference(const int32_t *in, uint32_t n)
{
    if (uac.feed && uac.ring48)
        reference48(in, n);
    else
        uac_tap(in, n);  /* unchanged 44.1 kHz and disabled-feed paths */
}

/* h++ then mask gives every s in 0..31, even at uint32_t wrap. Every
 * history dereference is s+j <= 31+23=54 < 64; the final increment is <=55.
 * Forward coefficients visit 0..23 then one-past 24. Reverse starts one-past
 * 24, predecrements to 23..0, and never forms a pointer before the row. */
static void bounds(void)
{
    uint32_t h, ph, j;
    for (h = 0; h < RS_H; h++) {
        uint32_t s = (h + 1u - UAC_FIR_N) & (RS_H - 1u);
        for (ph = 0; ph < UAC_FIR_L; ph++) {
            const int16_t *x = rs.l + s, *y = rs.r + s;
            const int32_t *row = UAC_FIR[ph < UAC_FIR_L / 2u ? ph : UAC_FIR_L - 1u - ph];
            const int32_t *c = row + (ph < UAC_FIR_L / 2u ? 0 : UAC_FIR_N);
            for (j = 0; j < UAC_FIR_N; j++, x++, y++) {
                require(x == rs.l + s + j && x < rs.l + 2u * RS_H, "left read bounds");
                require(y == rs.r + s + j && y < rs.r + 2u * RS_H, "right read bounds");
                if (ph >= UAC_FIR_L / 2u)
                    --c;
                require(c >= row && c < row + UAC_FIR_N, "coefficient read bounds");
                if (ph < UAC_FIR_L / 2u)
                    ++c;
            }
            require(x <= rs.l + 2u * RS_H && y <= rs.r + 2u * RS_H, "final history increment bounds");
            require(c >= row && c <= row + UAC_FIR_N, "final coefficient pointer bounds");
        }
    }
}

static uint32_t rng = 0x219;
static int32_t noise(void)
{
    rng = rng * 1664525u + 1013904223u;
    return (int32_t)(rng >> 16) - 32768;
}

/* 64 single-channel impulses (each history position), independent noise,
 * asymmetric ramps, DC corners and alternating corners, including input clips. */
static int32_t sample(uint32_t pattern, uint32_t channel, uint32_t pos)
{
    if (pattern < 2u * RS_H)
        return channel == pattern / RS_H && pos % RS_H == pattern % RS_H ? 32767 : 0;
    switch (pattern - 2u * RS_H) {
    case 0: return noise();
    case 1: return channel ? 12000 - (int32_t)(pos % RS_H) * 1031 : (int32_t)(pos % RS_H) * 511 - 14000;
    case 2: return 32767;
    case 3: return -32768;
    case 4: return channel ? -32768 : 32767;
    case 5: return channel ? 32767 : -32768;
    case 6: return (pos + channel) & 1u ? -32768 : 32767;
    default: return channel ? INT32_MIN : INT32_MAX;
    }
}

static void initial(uint32_t h, uint32_t ph, uint32_t pattern)
{
    uint32_t i;
    memset(&rs, 0, sizeof rs);
    memset(&uac, 0, sizeof uac);
    for (i = 0; i < RS_H; i++) {
        rs.l[i] = rs.l[i + RS_H] = (int16_t)uac_s16(sample(pattern, 0, i));
        rs.r[i] = rs.r[i + RS_H] = (int16_t)uac_s16(sample(pattern, 1, i));
    }
    for (i = 0; i < UA_N; i++)
        ua_ring[i] = 0xabcdef00u + i;
    rs.w = h;
    rs.ph = ph;
    ua_w = ua_r = UINT32_MAX - 1u; /* output ring and counter wrap */
    uac.feed = uac.go = uac.ring48 = uac.r48 = 1;
    usb.config = 1;
}

static void compare_block(Snapshot *actual, Snapshot *expected, const int32_t *in, uint32_t n)
{
    load(expected);
    reference(in, n);
    save(expected);
    load(actual);
    uac_tap(in, n);
    save(actual);
    equal(actual, expected);
}

static void exhaustive(void)
{
    uint32_t h, ph, p;
    Snapshot actual, expected;
    for (h = 0; h < RS_H; h++)
        for (ph = 0; ph < UAC_FIR_L; ph++)
            for (p = 0; p < 2u * RS_H + 8u; p++) {
                int32_t in[2] = {sample(p, 0, h), sample(p, 1, h)};
                initial(UINT32_MAX - (RS_H - 1u) + h, ph, p);
                save(&actual);
                memcpy(&expected, &actual, sizeof expected);
                compare_block(&actual, &expected, in, 1);
            }
}

enum { INPUT_N = 2048, OUTPUT_N = 2304 };
static int32_t input[2 * INPUT_N];
static uint32_t output[OUTPUT_N], output_n;
static Snapshot actual, expected, partition_final;

static void drain(void)
{
    while (ua_r != ua_w) {
        require(output_n < OUTPUT_N, "output capture capacity");
        output[output_n++] = ua_ring[ua_r++ & (UA_N - 1u)];
    }
    save(&actual);
    expected.r = actual.r;
}

static void partitions(void)
{
    static const uint32_t sizes[] = {1, 7, 32, 127, 19, 2, 63};
    uint32_t baseline[OUTPUT_N], count = 0, mode, i, at;
    for (i = 0; i < 2u * INPUT_N; i++)
        input[i] = sample(2u * RS_H + (i / 64u) % 8u, i & 1u, i / 2u);
    for (mode = 0; mode < 3; mode++) {
        initial(0, 0, 0);
        save(&actual);
        memcpy(&expected, &actual, sizeof expected);
        output_n = 0;
        for (at = i = 0; at < INPUT_N; i++) {
            uint32_t n = mode == 0 ? 1 : mode == 1 ? 32 : sizes[i % (sizeof sizes / sizeof sizes[0])];
            if (n > INPUT_N - at)
                n = INPUT_N - at;
            compare_block(&actual, &expected, input + 2u * at, n);
            drain();
            at += n;
        }
        if (!mode) {
            count = output_n;
            memcpy(baseline, output, count * sizeof *output);
            memcpy(&partition_final, &actual, sizeof partition_final);
        } else {
            require(count == output_n && !memcmp(baseline, output, count * sizeof *output), "all stereo output across block partitions");
            equal(&actual, &partition_final);
        }
    }
}

static void lifecycle(uint32_t op)
{
    switch (op) {
    case 0: uac_rate_set(44100); break;
    case 1: uac_rate_set(48000); break;
    case 2: uac_stream(0); break;
    case 3: uac_stream(1); uac.flowing = 1; break;
    case 4: ua_w = ua_r + UA_N; break; /* full: drop without changing history */
    case 5: ua_r = ua_w; break;
    }
    uac_render_start();
}

static void resets(void)
{
    static const uint32_t ops[] = {3, 0, 1, 1, 2, 3, 4, 5, 0, 2, 3, 1};
    uint32_t i;
    initial(UINT32_MAX, 159, 2u * RS_H);
    save(&actual);
    memcpy(&expected, &actual, sizeof expected);
    for (i = 0; i < sizeof ops / sizeof ops[0]; i++) {
        load(&expected);
        lifecycle(ops[i]);
        save(&expected);
        load(&actual);
        lifecycle(ops[i]);
        save(&actual);
        equal(&actual, &expected);
        if (ops[i] == 1 || ops[i] == 3) {
            if (uac.ring48 && actual.history.w == 0) {
                __typeof__(rs) zero = {0};
                require(!memcmp(&zero, &actual.history, sizeof rs), "48 kHz re-prime clears all history and phase");
            }
        }
        compare_block(&actual, &expected, input, 0);
        compare_block(&actual, &expected, input, 32);
        drain();
    }
    require(actual.stream.overruns > 0, "overrun path exercised");
}

int main(void)
{
    bounds();
    exhaustive();
    partitions();
    output_n = 0;
    resets();
    printf("FIR bounds/exact PCM/state: %u checks passed (160 phases x 32 history positions x 72 patterns, partitions, resets/rates/overrun)\n", checks);
    return 0;
}
