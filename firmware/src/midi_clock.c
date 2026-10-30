/* SPDX-License-Identifier: GPL-3.0-only
 * Adapted from MIDI clock contributions by ChanceTheMaker and keremimo (2026).
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Audio ISR state. Input timestamps keep USB/TRS jitter outside the render loop.
 * pos/rendered use fixed musical units (GRID per quarter), independent of BPM.
 * Sequencers/ARPs convert those units with fractional carries; tempo changes
 * cannot change the clock's accumulated musical phase. */
static struct {
    uint32_t pos, rendered, last_ms, start_ms, interval_ms;
    uint32_t pulse_units, interp_q8, tempo_ms;
    uint16_t spp;                                  /* #281: the last Song Position Pointer (MIDI beats, 1/16) */
    uint8_t mode, have_pulse, tempo_valid, tempo_n;
    uint8_t spp_set;                               /* spp received stopped, for the next Continue */
    uint8_t song;                                  /* a SONG the master stopped (or that ended): Start / Continue resume it */
} midi_clock;

/* #281, Song Position Pointer. The selected source's F2 is stored while stopped (playing: ignored, as MIDI 1.0 sends
 * it stopped) and resolved once, by the Continue that follows (events_block, the block boundary): every track's step
 * as if it had played from PLAY (modulo its own LEN and DIV, polymeter and swing included), the SONG section and its
 * repeat, the metronome's and the ARP LED's beat. A step that started before the position does not sound; one that
 * starts exactly there plays now. Start always starts from zero (a stored position is dropped). */
#define MIDI_SPP_UNITS (MIDI_CLOCK_GRID / 4u)     /* one MIDI beat (a 1/16) in grid units */

/* one loop of len steps of DIV div with SWING swing (0..SWING_MAX) in grid units, exact: *step its straight step,
 * *sw the swing's lengthening of the even ones (an odd LEN ends on a long one: core.h swing_step_len) */
static uint32_t midi_loop_units(uint32_t len, uint32_t div, uint32_t swing, uint32_t *step, uint32_t *sw)
{
    *step = div < 6u ? MIDI_CLOCK_GRID / DIV_DEN[div] : MIDI_CLOCK_GRID << (div - 5u);
    *sw = swing * *step / 250u;                   /* (step * 100 <= 38.4e6; 96 * swing / DEN: no remainder) */
    return len * *step + (len & 1u) * *sw;
}

/* grid units -> samples at the tempo the sequencer counts in (midi_grid_advance), the remainder into g */
static uint32_t midi_units_samples(uint32_t units, uint32_t div, midi_grid_t *g)
{
    uint32_t quarter = beat_samples();
    uint64_t s;
    if (div < 6u) quarter = quarter / DIV_DEN[div] * DIV_DEN[div];
    s = (uint64_t)units * quarter;
    g->remainder = (uint32_t)(s % MIDI_CLOCK_GRID);
    return (uint32_t)(s / MIDI_CLOCK_GRID);
}

/* track t at `at` grid units after its step 1 started (PLAY, or the section's start): its step, the samples into it
 * and its loop count (CONDITION) */
static __attribute__((noinline)) void midi_track_locate(track_t *t, uint32_t at)
{
    uint32_t div = (uint32_t)t->p[P_SDIV], len = t->p[P_SLEN] > 0 ? (uint32_t)t->p[P_SLEN] : 1u, step, sw;
    uint32_t loop = midi_loop_units(len, div, (uint32_t)track_swing(t), &step, &sw);
    uint32_t loops = at / loop, in = at - loops * loop, idx = in / (2u * step) * 2u;
    midi_grid_t *g = &midi_seq_grid[trk_index(t)];
    in -= idx * step;
    if (in >= step + sw) {
        in -= step + sw;
        idx++;
    }
    t->rskip_n = t->rh_n = 0;
    t->rat_left = 0;
    t->nd_late = t->nd_early = ND_NONE;
    t->nd_fired = 0;
    g->remainder = 0;
    if (!at) {                                     /* the top: as PLAY (a section: chain_apply) */
        t->seq_idx = (uint16_t)(len - 1u);
        t->seq_pos = 0x7FFFFFFFu;
    } else if (!in) {                              /* step idx starts here: the end of the one before (it plays) */
        uint32_t prev = (idx + len - 1u) % len;
        t->seq_idx = (uint16_t)prev;
        t->seq_pos = step_samples(t, div_samples(div), prev);
        t->cond_loop = (uint8_t)((loops % COND_LOOPS + COND_LOOPS - (idx ? 0u : 1u)) % COND_LOOPS);   /* (seq_enter adds one) */
    } else {
        t->seq_idx = (uint16_t)idx;
        t->seq_pos = midi_units_samples(in, div, g);
        t->cond_loop = (uint8_t)(loops % COND_LOOPS);
    }
}

/* the SONG (just started: chain_start) at *at grid units from its top: the section and repeat there, *at its offset
 * into that section (where every track starts from its step 1). 0: past the song's end (it stays stopped) */
static __attribute__((noinline)) int midi_chain_locate(uint32_t *at)
{
    uint32_t r;
    for (r = 0; r < chain.config.count; r++) {
        const chain_row_t *row = &chain.config.row[r];
        uint32_t k = chain_clock(row), s = row->slot[k], len = CHAIN_SIL_LEN, div = CHAIN_SIL_DIV, step, sw, loop;
        int32_t swing = 0;
        if (s < 4u) {
            len = (uint32_t)chain.source[s].timing[k][0];
            div = (uint32_t)chain.source[s].timing[k][1];
            swing = chain.source[s].timing[k][2];
        }
        swing = clamp(swing + song.g[G_SWING], 0, SWING_MAX);    /* (track_swing, as chain_apply sets the track) */
        loop = midi_loop_units(len ? len : 1u, div, (uint32_t)swing, &step, &sw);
        if (*at < loop * row->repeat) {
            uint32_t done = *at / loop;
            /* on a loop's boundary the clock track ends the loop before (chain_tick): one more to count */
            chain.remaining = (uint8_t)(row->repeat - done + (done && *at % loop == 0u));
            chain.carry = 0;
            if (r != chain.row) {
                chain.row = (uint8_t)r;
                chain_apply();
            }
            return 1;
        }
        *at -= loop * row->repeat;
    }
    return 0;
}

/* Continue at `at` grid units from the top (the SONG's, or the patterns'). 0: past the song's end */
static __attribute__((noinline)) int midi_clock_locate(uint32_t at)
{
    uint32_t i, sect = at;
    if (midi_clock.song) {
        chain.armed = 1;
        chain_start();
        if (!midi_chain_locate(&sect)) {
            chain_stop();
            return 0;                              /* (midi_clock.song kept: a locate back plays it) */
        }
        midi_clock.song = 0;
    }
    for (i = 0; i < NTRK; i++)
        midi_track_locate(&trk[i], sect);
    if (!at) {
        clk_pos = CLK_START;
    } else if (at % MIDI_SPP_UNITS) {
        clk_step = at / MIDI_SPP_UNITS & 15u;
        clk_pos = midi_units_samples(at % MIDI_SPP_UNITS, 2u, &midi_click_grid);
    } else {                                       /* (click_tick: this 1/16 starts, its click sounds) */
        clk_step = (at / MIDI_SPP_UNITS - 1u) & 15u;
        clk_pos = div_samples(2u);
        midi_click_grid.remainder = 0;
    }
    beat_n = at / MIDI_CLOCK_GRID & 3u;
    beat_pos = midi_units_samples(at % MIDI_CLOCK_GRID, 0u, &midi_beat_grid);
    return 1;
}

/* the master's Stop, or its clock lost: a SONG playing then resumes on its Start / Continue */
static void midi_clock_stop(void)
{
    if (chain.running)
        midi_clock.song = 1;
    seq_stop();
}

static void midi_clock_spp(uint32_t beats)
{
    if (song.playing)
        return;
    midi_clock.spp = (uint16_t)beats;
    midi_clock.spp_set = 1;
}

static __attribute__((noinline)) void midi_clock_transport(uint32_t status, uint32_t ms)
{
    if (status == 0xFAu) {                         /* Start: step zero */
        midi_clock.pos = midi_clock.rendered = 0;
        midi_clock.have_pulse = midi_clock.tempo_valid = 0;
        midi_clock.interval_ms = 0;
        midi_clock.start_ms = ms;
        midi_clock.spp_set = 0;
        if (midi_clock.song)
            chain.armed = 1;                       /* (the song from its first section) */
        midi_clock.song = 0;
        seq_start();
    } else if (status == 0xFBu) {                  /* Continue: preserve the step, or locate (SPP, a SONG) */
        uint32_t at = midi_clock.spp_set ? (uint32_t)midi_clock.spp * MIDI_SPP_UNITS : midi_clock.rendered;
        uint32_t locate = !song.playing && (midi_clock.spp_set || midi_clock.song);
        midi_clock.spp_set = 0;
        midi_clock.pos = midi_clock.rendered = locate ? at : midi_clock.rendered;
        midi_clock.have_pulse = midi_clock.tempo_valid = 0;
        midi_clock.interval_ms = 0;
        midi_clock.start_ms = ms;
        if (!song.playing) {
            motion_begin();
            if (locate && !midi_clock_locate(at)) {
                motion_end();
                return;
            }
        }
        song.playing = 1;
    } else if (status == 0xFCu) {
        midi_clock_stop();
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

static __attribute__((noinline)) void midi_clock_pulse(uint32_t ms)
{
    if (!midi_clock.tempo_valid) {
        midi_clock.tempo_valid = 1;
        midi_clock.tempo_ms = ms;
        midi_clock.tempo_n = 0;
    } else if (++midi_clock.tempo_n == 6u) {
        uint32_t dt = ms - midi_clock.tempo_ms;
        midi_clock.tempo_ms = ms;
        midi_clock.tempo_n = 0;
        /* Six clocks are a quarter of a beat. Reject gaps and corrupt bursts. */
        if (dt >= 62u && dt <= 375u) {
            uint32_t old_beat = beat_samples(), new_beat = (uint32_t)FS * dt / 250u;
            if (song.playing && new_beat != old_beat) {
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
            midi_beat_samples = new_beat;
            song.g[G_BPM] = (int16_t)clamp((int32_t)((15000u + dt / 2u) / dt), 40, 240);
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
            if (interval >= 8u && interval <= 80u)
                midi_clock.interval_ms = interval;
            midi_clock.pos += MIDI_CLOCK_GRID / 24u;
        }
        midi_clock.have_pulse = 1;
    }
    midi_clock.pulse_units = MIDI_CLOCK_GRID / 24u;
    if (!midi_clock.interval_ms)
        midi_clock.interval_ms = beat_samples() * 1000u / ((uint32_t)FS * 24u);
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
