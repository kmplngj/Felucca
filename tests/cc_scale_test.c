/* SPDX-License-Identifier: GPL-3.0-only
 * Issue #164: exact MIDI CC scaling without a target divide (host-only preparation).
 *
 * midi_cc_set (firmware/src/midi_control.c) computes  min + (value * (max - min) + 63) / 127.
 * This test proves, against the real descriptor tables (param_desc_of, every engine and every parameter id a CC can
 * reach: the standard map, CC74 / CC71 and any learned target, ml_id() < P_COUNT), the bounds of that expression, and
 * that the candidate  min + ((value * span + 63) * 33027 >> 22)  with unsigned 32-bit arithmetic equals it for every
 * value 0..127 and every span 0..255 (twice the largest reachable span). It does not change the firmware. */
#define UI_TEST_NO_MAIN 1
#include "ui_test.c"

#define CC_SPAN_MAX 255u                        /* the proven domain of the candidate: 2 x the reachable maximum */
#define CC_MUL 33027u                           /* ceil(2^22 / 127) */
#define CC_SHIFT 22u
/* x * CC_MUL must stay inside 32 bits at the domain's largest numerator */
typedef char cc_mul_fits[(127ull * CC_SPAN_MAX + 63ull) * CC_MUL < 0x100000000ull ? 1 : -1];

/* the reference: midi_cc_set's expression, as written there */
static int32_t cc_ref(int32_t min, int32_t max, uint32_t value)
{
    return min + ((int32_t)value * (max - min) + 63) / 127;
}
/* the candidate: the numerator is never negative once max > min (the caller has returned for max <= min) */
static int32_t cc_cand(int32_t min, int32_t max, uint32_t value)
{
    uint32_t x = value * (uint32_t)(max - min) + 63u;
    return min + (int32_t)((x * CC_MUL) >> CC_SHIFT);
}
/* midi_cc_set's observable result for a current parameter value cur: the new value, or cur when it returns early */
static int32_t cc_ref_apply(const param_desc_t *d, uint32_t value, int32_t cur)
{
    int32_t v = cc_ref(d->min, d->max, value);
    return d->max <= d->min || cur == v ? cur : v;
}
static int32_t cc_cand_apply(const param_desc_t *d, uint32_t value, int32_t cur)
{
    int32_t v;
    if (d->max <= d->min)
        return cur;
    v = cc_cand(d->min, d->max, value);
    return cur == v ? cur : v;
}

static int cc_scale_test(void)
{
    int bad = 0;
    int32_t span_max = 0, span_min = 0, lo = 0, hi = 0, num_max = 0, num_min = 0;
    uint32_t e, id, value, span, n = 0, degenerate = 0, mismatch = 0;
    int32_t min;

    /* 1. bounds over every descriptor midi_cc_set can be given */
    for (e = 0; e < NENGINES; e++)
        for (id = 0; id < P_COUNT; id++) {
            const param_desc_t *d = param_desc_of(e, id);
            int32_t s = d->max - d->min, a = 127 * s + 63;
            if (!n || s > span_max) span_max = s;
            if (!n || s < span_min) span_min = s;
            if (!n || d->min < lo) lo = d->min;
            if (!n || d->max > hi) hi = d->max;
            if (!n || a > num_max) num_max = a;
            if (!n || a < num_min) num_min = a;
            degenerate += s <= 0;
            n++;
            for (value = 0; value < 128; value++) {
                /* Out-of-range current values exercise changes; the reference result exercises no change.
                 * A fixed count also handles max <= min without a range-dependent loop step. */
                int32_t current[] = {d->min - 1, d->max + 1, cc_ref(d->min, d->max, value)};
                for (uint32_t i = 0; i < NELEM(current); i++)
                    mismatch += cc_ref_apply(d, value, current[i]) != cc_cand_apply(d, value, current[i]);
            }
            for (value = 0; value < 128; value++)
                if (d->max > d->min) mismatch += cc_ref(d->min, d->max, value) != cc_cand(d->min, d->max, value);
        }
    printf("cc scale: %u descriptors (%u engines x %u ids), min %d, max %d, span %d..%d, numerator %d..%d, %u with max <= min\n",
           n, (unsigned)NENGINES, (unsigned)P_COUNT, lo, hi, span_min, span_max, num_min, num_max, degenerate);
    bad += check("every reachable span fits the candidate's domain (<= 255)", span_max >= 0 && (uint32_t)span_max <= CC_SPAN_MAX);
    bad += check("the candidate equals midi_cc_set's result for every reachable descriptor and value, changed and unchanged", !mismatch);

    /* 2. exhaustive: every value, every span of the domain, every minimum -300..300 */
    mismatch = 0;
    for (span = 1; span <= CC_SPAN_MAX; span++)
        for (value = 0; value < 128; value++)
            for (min = -300; min <= 300; min++) {
                if (cc_ref(min, min + (int32_t)span, value) != cc_cand(min, min + (int32_t)span, value)) mismatch++;
                if (cc_ref(min, min + (int32_t)span, value) < min || cc_ref(min, min + (int32_t)span, value) > min + (int32_t)span)
                    mismatch++;                  /* and it stays inside the range */
            }
    bad += check("every value 0..127 x every span 1..255 x signed minimum: candidate == reference, inside the range", !mismatch);

    /* 3. the division alone: every numerator the domain can produce */
    mismatch = 0;
    for (uint32_t x = 0; x <= 127u * CC_SPAN_MAX + 63u; x++)
        mismatch += (x * CC_MUL >> CC_SHIFT) != x / 127u;
    bad += check("x * 33027 >> 22 == x / 127 for every x in 0..32448", !mismatch);
    /* the endpoints: 0 -> min, 127 -> max */
    mismatch = 0;
    for (span = 1; span <= CC_SPAN_MAX; span++)
        mismatch += cc_cand(-64, -64 + (int32_t)span, 0) != -64 || cc_cand(-64, -64 + (int32_t)span, 127) != -64 + (int32_t)span;
    bad += check("CC 0 is the minimum and CC 127 the maximum for every span", !mismatch);
    return bad;
}

int main(void)
{
    int bad = cc_scale_test();
    printf("%s\n", bad ? "CC SCALING TEST FAILED" : "CC scaling candidate tests passed");
    return bad != 0;
}
