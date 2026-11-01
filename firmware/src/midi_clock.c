/* SPDX-License-Identifier: GPL-3.0-only
 * Adapted from MIDI clock contributions by ChanceTheMaker and keremimo (2026).
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Audio ISR state. Input timestamps keep USB/TRS jitter outside the render loop.
 * pos/rendered use fixed musical units (GRID per quarter), independent of BPM.
 * Sequencers/ARPs convert those units with fractional carries; tempo changes
 * cannot change the clock's accumulated musical phase. */
static struct {
    uint32_t pos, rendered, last_ms, start_ms, interval_ms;
    uint32_t pulse_units, interp_q8, tempo_ms, tempo_dt;
    uint8_t mode, selected, have_pulse, tempo_valid, tempo_n, tempo_count;
} midi_clock;

static __attribute__((noinline)) void midi_clock_transport(uint32_t status, uint32_t ms)
{
    if (status == 0xFAu || status == 0xFBu)
        cin_cancel();                             /* master transport supersedes any local count-in/pickup */
    if (status == 0xFAu) {                         /* Start: step zero */
        midi_clock.pos = midi_clock.rendered = 0;
        midi_clock.have_pulse = midi_clock.tempo_valid = 0;
        midi_clock.interval_ms = 0;
        midi_clock.start_ms = ms;
        seq_start();
    } else if (status == 0xFBu) {                  /* Continue: preserve the step */
        midi_clock.pos = midi_clock.rendered;
        midi_clock.have_pulse = midi_clock.tempo_valid = 0;
        midi_clock.interval_ms = 0;
        midi_clock.start_ms = ms;
        if (!song.playing)
            motion_begin();
        song.playing = 1;
    } else if (status == 0xFCu) {
        seq_stop();
    }
}

static uint32_t midi_clock_scale(uint32_t value, uint32_t new_period, uint32_t old_period)
{
    return (uint32_t)(((uint64_t)value * new_period + old_period / 2u) / old_period);
}

static uint32_t midi_clock_period(uint32_t quarter, uint32_t div)
{
    return div < 6u ? quarter / DIV_DEN[div] : div < 10u ? quarter << (div - 5u) : quarter / DIV_DEN[div % 6u];
}

static uint32_t midi_clock_scale_phase(uint32_t value, uint32_t new_period, uint32_t old_period, midi_grid_t *grid)
{
    uint64_t phase = (uint64_t)value * MIDI_CLOCK_GRID + grid->remainder;
    phase = (phase * new_period + old_period / 2u) / old_period;
    grid->remainder = (uint32_t)(phase % MIDI_CLOCK_GRID);
    return (uint32_t)(phase / MIDI_CLOCK_GRID);
}

/* Period-aware phase rescaling is shared by measured tempo and clock handoffs. */
static void midi_clock_rescale(uint32_t old_beat, uint32_t new_beat)
{
    if (new_beat != old_beat) {
        uint32_t i;
        /* Preserve each track's fractional step phase when the master
         * changes tempo. The next pulse then lands on its new boundary. */
        for (i = 0; i < NTRK; i++) {
            uint32_t div = (uint32_t)trk[i].p[P_SDIV];
            uint32_t old_period = midi_clock_period(old_beat, div), new_period = midi_clock_period(new_beat, div);
            if (trk[i].seq_pos < 0x7FFFFFFFu)
                trk[i].seq_pos = midi_clock_scale_phase(trk[i].seq_pos, new_period, old_period, &midi_seq_grid[i]);
            if (trk[i].seq_off)
                trk[i].seq_off = midi_clock_scale(trk[i].seq_off, new_period, old_period);
            if (trk[i].nd_late)            /* (NUDGE: the latched plays, seq_pos + 1, with the step) */
                trk[i].nd_late = midi_clock_scale(trk[i].nd_late - 1u, new_period, old_period) + 1u;
            if (trk[i].nd_early)
                trk[i].nd_early = midi_clock_scale(trk[i].nd_early - 1u, new_period, old_period) + 1u;
            div = (uint32_t)trk[i].p[P_ARATE];
            old_period = midi_clock_period(old_beat, div); new_period = midi_clock_period(new_beat, div);
            if (trk[i].arp_pos < 0xFFFFFFFu)
                trk[i].arp_pos = midi_clock_scale_phase(trk[i].arp_pos, new_period, old_period, &midi_arp_grid[i]);
            if (trk[i].arp_off)
                trk[i].arp_off = midi_clock_scale(trk[i].arp_off, new_period, old_period);
        }
        if (clk_pos != CLK_START)          /* (the metronome's beat as the steps) */
            clk_pos = midi_clock_scale_phase(clk_pos, new_beat / 4u, old_beat / 4u, &midi_click_grid);
        beat_pos = midi_clock_scale_phase(beat_pos, new_beat, old_beat, &midi_beat_grid);
    }
}

static void midi_clock_mode(uint32_t mode)
{
    uint32_t old_beat = beat_samples();
    if (!mode) midi_beat_samples = 0;
    midi_sync_active = (uint8_t)mode;
    midi_clock_rescale(old_beat, beat_samples());
    midi_clock.mode = (uint8_t)mode;
}

/* A selected but silent master must not make local PLAY wait for its timeout.
 * Transport messages reclaim external timing; clock pulses alone cannot. */
static uint32_t midi_clock_local_start(uint32_t ms)
{
    if (!midi_clock.mode) return 0;
    if (midi_clock.tempo_valid && ms - midi_clock.last_ms <= 500u) return 1;
    midi_clock_mode(0);
    return 0;
}

static __attribute__((noinline)) void midi_clock_pulse(uint32_t ms)
{
    if (!midi_clock.tempo_valid || ms - midi_clock.last_ms > 500u) {
        midi_clock.tempo_valid = 1;
        midi_clock.tempo_ms = ms;
        midi_clock.tempo_n = 0;
        midi_clock.tempo_dt = 0;
        midi_clock.tempo_count = 0;
    } else if (++midi_clock.tempo_n == 6u) {
        uint32_t dt = ms - midi_clock.tempo_ms;
        midi_clock.tempo_ms = ms;
        midi_clock.tempo_n = 0;
        /* Six clocks acquire quickly; smooth their endpoint jitter over about
         * two beats. A change above 6.25% locks immediately. Q8-ms precision
         * retains fractional BPM with the firmware's millisecond input stamps.
         * Adapted from Tessera 87d0b3783c52e814435cad13e77611df1ef94160
         * (Melodee's 6eca57d contribution). */
        if (dt >= 60u && dt <= 377u) {
            uint32_t first = !midi_clock.tempo_dt;
            int32_t delta = (int32_t)(dt * 256u) - (int32_t)midi_clock.tempo_dt;
            uint32_t change = (uint32_t)(delta < 0 ? -delta : delta);
            if (first || change > midi_clock.tempo_dt / 16u) {
                midi_clock.tempo_dt = dt * 256u;
                midi_clock.tempo_count = 1;
            } else {
                if (midi_clock.tempo_count < 8u) midi_clock.tempo_count++;
                midi_clock.tempo_dt = (uint32_t)((int32_t)midi_clock.tempo_dt + delta / midi_clock.tempo_count);
            }
            /* FS=44100, dt<=377ms: FS*tempo_dt <= 4256179200, fits uint32_t. */
            uint32_t old_beat = beat_samples(), new_beat = (uint32_t)FS * midi_clock.tempo_dt / 64000u;
            if (song.playing) midi_clock_rescale(old_beat, new_beat);
            midi_beat_samples = new_beat;
            /* +/- 0.875 BPM hysteresis holds fractional-master rounding edges. */
            int32_t bpm = (int32_t)((15000u * 256u * 256u + midi_clock.tempo_dt / 2u) / midi_clock.tempo_dt);
            int32_t shown = (int32_t)song.g[G_BPM] * 256;
            if (first || bpm > shown + 224 || bpm < shown - 224)
                song.g[G_BPM] = (int16_t)clamp((bpm + 128) / 256, 40, 240);
        }
    }
    if (song.playing) {
        if (!midi_clock.have_pulse) {
            /* Enter a fresh start before later clocks in the same queue are
             * consumed; the start sentinel must not discard their progress. */
            for (uint32_t i = 0; i < NTRK; i++) {
                seq_tick(&trk[i], 0);
                if (trk[i].arp_pos == 0xFFFFFFFu) arp_step(&trk[i], 0, 0);
            }
        }
        if (midi_clock.have_pulse) {
            uint32_t interval = ms - midi_clock.last_ms;
            if (!midi_clock.tempo_dt && interval >= 8u && interval <= 80u)
                midi_clock.interval_ms = interval;
            midi_clock.pos += MIDI_CLOCK_GRID / 24u;
        }
        midi_clock.have_pulse = 1;
    }
    midi_clock.pulse_units = MIDI_CLOCK_GRID / 24u;
    if (!midi_clock.interval_ms)
        midi_clock.interval_ms = beat_samples() * 1000u / ((uint32_t)FS * 24u);
    if (midi_clock.tempo_dt) {
        midi_clock.interval_ms = (midi_clock.tempo_dt + 1535u) / 1536u;
        midi_clock.interp_q8 = midi_clock.pulse_units * 256u * 1536u / midi_clock.tempo_dt;
    } else
        midi_clock.interp_q8 = midi_clock.pulse_units * 256u / midi_clock.interval_ms;
    midi_clock.last_ms = ms;
}

static uint32_t midi_clock_advance(uint32_t now)
{
    uint32_t target, elapsed, offset, n;
    if (!midi_clock.have_pulse)
        return 0;
    elapsed = now - midi_clock.last_ms;
    /* Interpolate to the next pulse, never across it before it arrives. */
    if (elapsed > midi_clock.interval_ms)
        elapsed = midi_clock.interval_ms;
    offset = elapsed * midi_clock.interp_q8 >> 8;
    if (offset >= midi_clock.pulse_units)
        offset = midi_clock.pulse_units - 1u;
    target = midi_clock.pos + offset;
    n = (int32_t)(target - midi_clock.rendered) > 0 ? target - midi_clock.rendered : 0u;
    if (n > MIDI_CLOCK_GRID / 2u)
        n = MIDI_CLOCK_GRID / 2u;
    midi_clock.rendered += n;
    return n;
}
