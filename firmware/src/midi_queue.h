/* SPDX-License-Identifier: GPL-3.0-only */
/* Default-off consumer observation. Audio alone writes ordinary BSS; producers
 * and CPU1 never touch it. Foreground copies once, with interrupts enabled.
 * Units, lifetime, range limits and window exclusions: docs/midi-queue-evidence.md. */
#ifndef MIDI_QUEUE_EVIDENCE_H
#define MIDI_QUEUE_EVIDENCE_H
#ifndef FELUCCA_MIDI_QUEUE
#define FELUCCA_MIDI_QUEUE 0
#endif
#if FELUCCA_MIDI_QUEUE
#define MIDI_QUEUE_RANGE 1u
#define MIDI_QUEUE_COUNT 2u
#define MIDI_QUEUE_LIMIT 0x7fffffffu
typedef struct {
    uint32_t error, calls, events, recoveries, flushed, entry_peak, events_peak;
    uint32_t entry, arrivals, dispatched, flush, residual, drain_last, drain_max;
    uint32_t age_seen, age_max[10]; /* USB then TRS: on, release, CC, realtime, other */
} midi_queue_t;
static volatile midi_queue_t midi_queue;
static volatile uint32_t midi_queue_seq;

static void midi_queue_add(volatile uint32_t *value, uint32_t n)
{
    if (n > 0xffffffffu - *value)
        midi_queue.error |= MIDI_QUEUE_COUNT;
    else
        *value += n;
}

static void midi_queue_age(uint32_t source, uint32_t status, uint32_t velocity, uint32_t age)
{
    uint32_t kind = status >= 0xF8u ? 3u : (status & 0xF0u) == 0xB0u ? 2u :
        (status & 0xF0u) == 0x80u || ((status & 0xF0u) == 0x90u && !velocity) ? 1u :
        (status & 0xF0u) == 0x90u ? 0u : 4u;
    uint32_t at;
    if (source < 1u || source > 2u || age > MIDI_QUEUE_LIMIT) {
        midi_queue.error |= MIDI_QUEUE_RANGE;
        return;
    }
    at = (source - 1u) * 5u + kind;
    midi_queue.age_seen |= 1u << at;
    if (age > midi_queue.age_max[at])
        midi_queue.age_max[at] = age;
}

static void midi_queue_finish(uint32_t entry, uint32_t arrivals, uint32_t dispatched,
                              uint32_t flushed, uint32_t residual, uint32_t ticks, uint32_t recovery)
{
    midi_queue.entry = entry;
    midi_queue.arrivals = arrivals;
    midi_queue.dispatched = dispatched;
    midi_queue.flush = flushed;
    midi_queue.residual = residual;
    if (entry > MQ || residual > MQ || arrivals > MIDI_QUEUE_LIMIT ||
        dispatched > MIDI_QUEUE_LIMIT || flushed > MQ || ticks > MIDI_QUEUE_LIMIT ||
        entry + arrivals != dispatched + flushed + residual)
        midi_queue.error |= MIDI_QUEUE_RANGE;
    midi_queue_add(&midi_queue.calls, 1u);
    midi_queue_add(&midi_queue.events, dispatched);
    midi_queue_add(&midi_queue.flushed, flushed);
    midi_queue_add(&midi_queue.recoveries, recovery);
    if (entry > midi_queue.entry_peak) midi_queue.entry_peak = entry;
    if (dispatched > midi_queue.events_peak) midi_queue.events_peak = dispatched;
    midi_queue.drain_last = ticks;
    if (ticks > midi_queue.drain_max) midi_queue.drain_max = ticks;
    RING_PUBLISH();
    midi_queue_seq++;
}

static int midi_queue_read(midi_queue_t *copy)
{
    uint32_t before = midi_queue_seq;
    if (before & 1u) return 0;
    RING_PUBLISH();
    *copy = midi_queue;
    RING_PUBLISH();
    return before == midi_queue_seq;
}
#endif
#endif
