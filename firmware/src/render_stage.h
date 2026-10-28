/* SPDX-License-Identifier: GPL-3.0-only */
/* Development observer: CPU0's inclusive mix_block wall time, summed per DMA
 * half. TIMER5 preemption and CPU1 work/wait overlap are INCLUDED. Raw TIMER4
 * ticks only: no frequency/cycle, exclusive-work or percentile inference.
 *
 * ALNK0 is the sole writer; neither TIMER5 nor CPU1 touches these objects.
 * BSS resets them at application startup. Reading never resets history.
 * A bounded foreground copy uses the same compiler publication barrier as the
 * rings; IRQs remain enabled. A preempted copy is unavailable, without retry.
 */
#ifndef FELUCCA_RENDER_STAGE_H
#define FELUCCA_RENDER_STAGE_H
#ifndef FELUCCA_RENDER_STAGE
#define FELUCCA_RENDER_STAGE 0
#endif
#if FELUCCA_RENDER_STAGE

#define RENDER_STAGE_RANGE 1u
#define RENDER_STAGE_SUM 2u
#define RENDER_STAGE_COUNT 4u
#define RENDER_STAGE_LIMIT 0x7fffffffu

typedef struct {
    uint32_t error, halves, blocks, rejected, valid;
    uint32_t mix_last, mix_max, empty_last, empty_max;
    uint32_t half_last, half_max, nested_last, nested_max;
} render_stage_t;
static volatile uint32_t render_stage_seq;
static volatile render_stage_t render_stage;
static struct { uint32_t mix, empty, blocks, error; } render_stage_half;

static void render_stage_begin(void)
{
    render_stage_half.mix = render_stage_half.empty = 0;
    render_stage_half.blocks = render_stage_half.error = 0;
}

/* Every interval must progress and fit within half the uint32 timer period.
 * Unsigned subtraction tolerates one timer wrap, not an unbounded stall.
 * Empty adjacent reads may quantize to zero. No empty cost is subtracted. */
static void render_stage_block(uint32_t mix, uint32_t empty)
{
    if (!mix || mix > RENDER_STAGE_LIMIT || empty > RENDER_STAGE_LIMIT)
        render_stage_half.error |= RENDER_STAGE_RANGE;
    if (UINT32_MAX - render_stage_half.mix < mix || UINT32_MAX - render_stage_half.empty < empty)
        render_stage_half.error |= RENDER_STAGE_SUM;
    else {
        render_stage_half.mix += mix;
        render_stage_half.empty += empty;
    }
    if (render_stage_half.blocks == UINT32_MAX)
        render_stage_half.error |= RENDER_STAGE_COUNT;
    else
        render_stage_half.blocks++;
}

/* half is the separate observer window after the legacy nested-counter reset,
 * ending at the legacy meter's ending read. Bracket both boundary reads with
 * nested-counter reads: a mismatch rejects this half and can recover next half.
 * Publication and subsequent ISR bookkeeping lie outside the measured window. */
static void render_stage_publish(uint32_t half, uint32_t nested, uint32_t ambiguous)
{
    uint32_t error = render_stage_half.error;
    if (!ambiguous && (!half || half > RENDER_STAGE_LIMIT || nested > half || !render_stage_half.blocks ||
                      render_stage_half.mix > half || render_stage_half.empty > half))
        error |= RENDER_STAGE_RANGE;
    if ((!ambiguous && (render_stage.halves == UINT32_MAX ||
         UINT32_MAX - render_stage.blocks < render_stage_half.blocks)) ||
        (ambiguous && render_stage.rejected == UINT32_MAX))
        error |= RENDER_STAGE_COUNT;
    render_stage_seq++;
    RING_PUBLISH();
    render_stage.error |= error;
    render_stage.valid = 0;
    /* Fail closed on the first range/arithmetic/count failure. Counts and
     * history freeze instead of wrapping or exposing stale values as current. */
    if (!render_stage.error && ambiguous)
        render_stage.rejected++;
    if (!render_stage.error && !ambiguous) {
        render_stage.valid = 1;
        render_stage.halves++;
        render_stage.blocks += render_stage_half.blocks;
        render_stage.mix_last = render_stage_half.mix;
        if (render_stage_half.mix > render_stage.mix_max)
            render_stage.mix_max = render_stage_half.mix;
        render_stage.empty_last = render_stage_half.empty;
        if (render_stage_half.empty > render_stage.empty_max)
            render_stage.empty_max = render_stage_half.empty;
        render_stage.half_last = half;
        if (half > render_stage.half_max)
            render_stage.half_max = half;
        render_stage.nested_last = nested;
        if (nested > render_stage.nested_max)
            render_stage.nested_max = nested;
    }
    RING_PUBLISH();
    render_stage_seq++;
}

static int render_stage_read(render_stage_t *copy)
{
    uint32_t seq = render_stage_seq;
    if (seq & 1u)
        return 0;
    RING_PUBLISH();
    *copy = render_stage;
    RING_PUBLISH();
    return seq == render_stage_seq;
}
#endif
#endif
