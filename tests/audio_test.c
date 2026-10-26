/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* The real audio ISR with a simulated DMA and clock: overload must free work
 * within one block without cutting another part's lead or bass. */
#ifdef C1_HOST
#include "c1_host.h"
#endif
#define main hostsim_main
#include "hostsim.c"
#undef main

#define FM1_AUDIO_HALF 0x80u
#define FM1_TICKS_PER_US 1u
static uint32_t host_clock, host_us, host_half_reads, host_dma_advanced, host_acks, host_nest;
static uint8_t host_pending;
#if FELUCCA_RENDER_STAGE
static uint32_t host_tick_reads, host_inject_read, host_copy_interrupt;
static void host_stage_barrier(void);
#undef RING_PUBLISH
#define RING_PUBLISH() host_stage_barrier()
#endif
static volatile uint32_t t5_nested_ticks;              /* audio.c's: TIMER5 nested in the render (main.c) */
static uint32_t fm1_ticks(void)
{
#if FELUCCA_RENDER_STAGE
    if (++host_tick_reads == host_inject_read) host_nest += 3u;
#endif
    t5_nested_ticks = host_nest; host_clock += host_us; return host_clock;
}
static uint8_t fm1_audio_pending(void)
{
#if FELUCCA_RENDER_STAGE
    host_tick_reads = 0;
#endif
    return host_pending;
}
static void fm1_audio_ack_aux(uint8_t p) { (void)p; }
static uint32_t fm1_audio_free_half(void) { return host_dma_advanced && host_half_reads++ > 0u; }
static void fm1_audio_ack_half(void) { host_acks++; }
static void fm1_audio_init(int32_t *b, uint32_t n, void (*isr)(void), uint32_t p)
{ (void)b; (void)n; (void)isr; (void)p; }
void isr_alnk0(void) {}
#define FELUCCA_UAC 1                                  /* audio.c taps USB audio: here into host_tap */
static int32_t host_tap[2 * 64];
static uint32_t host_tap_n;
static void uac_tap(const int32_t *out, uint32_t n) { memcpy(host_tap, out, 8u * n); host_tap_n = n; }
static int probe_isr;                                  /* isr_assert(): the stub calls a main-loop-only check from the render */
static void uac_render_start(void) { if (probe_isr) FM1_ASSERT_THREAD(); }
#include "../firmware/src/audio.c"
#if FELUCCA_RENDER_STAGE
static void host_stage_barrier(void)
{
    __asm__ volatile("" ::: "memory");
    if (host_copy_interrupt && !--host_copy_interrupt) {
        render_stage_seq += 2u;              /* a complete ALNK publication during a foreground copy */
        render_stage.halves++;
    }
}
#endif
enum { FM1_ADC_BATT = 3, FM1_ADC_MASTER = 4 };
static int32_t host_pot = 1023;                        /* the MASTER pot as the ADC reads it (-1: timeout) */
static int32_t fm1_adc_read(uint32_t ch) { return ch == FM1_ADC_MASTER ? host_pot : 620; }
#include "../firmware/src/master.c"

static int bad;
static void check(const char *what, int ok)
{
    printf("audio: %-74s %s\n", what, ok ? "ok" : "FAIL");
    bad += !ok;
}
static void fresh(void)
{
    uint32_t p;
    memset(trk, 0, sizeof trk);
    memset(&song, 0, sizeof song);
    memset(&chain, 0, sizeof chain);
    host_tracks_init();
    for (p = 0; p < NPART; p++) host_preset(&trk[p], 0, 0);
    memset(&felucca_dbg, 0, sizeof felucca_dbg);
    audio_cpu_rem = audio_halves = audio_max_us = 0;
    shed_req = 0; shed_count = 0; shed_over = 0;
    host_clock = host_us = host_half_reads = host_dma_advanced = host_acks = host_nest = 0;
    host_pending = FM1_AUDIO_HALF;
#if FELUCCA_RENDER_STAGE
    memset((void *)&render_stage, 0, sizeof render_stage);
    render_stage_seq = host_tick_reads = host_inject_read = host_copy_interrupt = 0;
    render_stage_begin();
#endif
    transport_req = panic_req = 0;
}

#if FELUCCA_RENDER_STAGE
static void stage_observer(void)
{
    render_stage_t s;
    uint32_t n = HALF_FRAMES / CTL, end_read = 3u + 4u * n;
    fresh();
    check("stage: boot has no samples", render_stage_read(&s) && !s.halves && !s.valid);
    host_us = 10;
    fm1_alnk0_irq();
    check("stage: real ISR publishes raw per-half mix/control/window/nested values",
          render_stage_read(&s) && s.valid && !s.error && s.halves == 1u && s.blocks == n &&
          s.mix_last == 10u * n && s.empty_last == 10u * n &&
          s.half_last == (end_read - 2u) * 10u && s.nested_last == 0);
    host_inject_read = 6u;                   /* TIMER5 inside a mix interval, not a boundary */
    host_nest = 0;
    fm1_alnk0_irq();
    check("stage: nested service remains inclusive and is reported once separately",
          render_stage_read(&s) && s.valid && s.nested_last == 3u && s.mix_last == 10u * n);
    fresh(); host_clock = UINT32_MAX - 30u; host_us = 10;
    fm1_alnk0_irq();
    check("stage: raw timer wrap preserves bounded unsigned intervals",
          render_stage_read(&s) && s.valid && !s.error && s.half_last == (end_read - 2u) * 10u);
    fresh(); host_us = 10; host_inject_read = 2u;
    fm1_alnk0_irq();
    check("stage: start-boundary preemption rejects latest sample",
          render_stage_read(&s) && !s.valid && !s.error && s.rejected == 1u && !s.halves);
    host_nest = host_inject_read = 0;
    fm1_alnk0_irq();
    check("stage: next unambiguous half recovers, retaining rejection count",
          render_stage_read(&s) && s.valid && !s.error && s.rejected == 1u && s.halves == 1u);
    host_nest = 0; host_inject_read = end_read;
    fm1_alnk0_irq();
    check("stage: end-boundary preemption rejects without refreshing history",
          render_stage_read(&s) && !s.valid && !s.error && s.rejected == 2u && s.halves == 1u);
    host_nest = host_inject_read = 0;
    fm1_alnk0_irq();
    check("stage: end-boundary rejection also recovers", render_stage_read(&s) && s.valid && s.halves == 2u);
    render_stage_seq |= 1u;
    check("stage: active writer makes snapshot unavailable", !render_stage_read(&s));
    render_stage_seq++;
    host_copy_interrupt = 2u;
    check("stage: publication after copy invalidates snapshot", !render_stage_read(&s));
    host_copy_interrupt = 1u;
    check("stage: publication before copy also invalidates snapshot", !render_stage_read(&s));
    check("stage: coherent subsequent snapshot succeeds", render_stage_read(&s));
    fresh();
    render_stage_block(RENDER_STAGE_LIMIT, 0);
    render_stage_publish(RENDER_STAGE_LIMIT, RENDER_STAGE_LIMIT, 0);
    check("stage: supported raw range reaches its upper bound",
          render_stage_read(&s) && s.valid && s.mix_last == RENDER_STAGE_LIMIT);
    render_stage_begin(); render_stage_block(1u, 0);
    render_stage_publish(10u, 11u, 0);
    check("stage: unmatched nested total fails closed", render_stage_read(&s) && !s.valid && (s.error & RENDER_STAGE_RANGE));
    render_stage_publish(10u, 0, 0);
    check("stage: range failure is sticky", render_stage_read(&s) && !s.valid && s.halves == 1u);
    fresh(); host_us = 0; fm1_alnk0_irq();
    check("stage: stopped/nonprogressing clock is unavailable", render_stage_read(&s) && !s.valid && (s.error & RENDER_STAGE_RANGE));
    fresh(); render_stage_block(0, 0); render_stage_publish(10u, 0, 0);
    check("stage: zero mix interval is unavailable even with a progressing window",
          render_stage_read(&s) && !s.valid && (s.error & RENDER_STAGE_RANGE));
    fresh(); render_stage_block(RENDER_STAGE_LIMIT + 1u, 0); render_stage_publish(RENDER_STAGE_LIMIT, 0, 0);
    check("stage: unsupported half-period interval is unavailable",
          render_stage_read(&s) && !s.valid && (s.error & RENDER_STAGE_RANGE));
    fresh(); render_stage_block(RENDER_STAGE_LIMIT, 0); render_stage_block(RENDER_STAGE_LIMIT, 0);
    render_stage_block(2u, 0); render_stage_publish(10u, 0, 0);
    check("stage: sum overflow freezes data", render_stage_read(&s) && !s.valid && (s.error & RENDER_STAGE_SUM));
    fresh(); render_stage.halves = UINT32_MAX; render_stage_block(1u, 0); render_stage_publish(10u, 0, 0);
    check("stage: half-count exhaustion cannot wrap", render_stage_read(&s) && !s.valid && s.halves == UINT32_MAX && (s.error & RENDER_STAGE_COUNT));
    fresh(); render_stage.blocks = UINT32_MAX; render_stage_block(1u, 0); render_stage_publish(10u, 0, 0);
    check("stage: block-count exhaustion cannot wrap", render_stage_read(&s) && !s.valid && s.blocks == UINT32_MAX && (s.error & RENDER_STAGE_COUNT));
    fresh(); render_stage.rejected = UINT32_MAX; render_stage_publish(0, 0, 1);
    check("stage: rejection-count exhaustion cannot wrap", render_stage_read(&s) && !s.valid && s.rejected == UINT32_MAX && (s.error & RENDER_STAGE_COUNT));
    fresh(); render_stage_seq = UINT32_MAX - 1u; host_us = 10; fm1_alnk0_irq();
    check("stage: publication sequence wraps coherently", render_stage_read(&s) && s.valid && render_stage_seq == 0);
}
#endif
static voice_t *held(track_t *t, uint32_t note)
{
    uint32_t i;
    for (i = 0; i < NVOICE; i++)
        if (t->v[i].active && t->v[i].note == note) return &t->v[i];
    return 0;
}
static void overload(void)
{
    voice_t *lead, *bass, *extra;
    uint32_t mode, i;
    int32_t out[2 * CTL];
    fresh();
    trk[0].p[P_VOICE] = V_MONO;
    trk_note_on(&trk[0], 40, 100);
    trk[1].p[P_VOICE] = V_POLY;
    trk_note_on(&trk[1], 48, 100);
    trk_note_on(&trk[1], 60, 100);
    lead = held(&trk[0], 40); bass = held(&trk[1], 48); extra = held(&trk[1], 60);
    shed_voice();
    check("overload keeps each part's MONO lead and lowest POLY note",
          lead && bass && extra && lead->gate && bass->gate && extra->stage == 4u && shed_count == 1u);
    mix_block(out, CTL);
    check("overload frees its victim within one control block", extra && !extra->active && voices_busy() == 2u);
    shed_voice();
    check("a lead alone on each part stays protected", lead->gate && bass->gate && shed_count == 1u);

    fresh();
    host_preset(&trk[0], ENGI_DRUM, 0);
    trk_note_on(&trk[0], 36, 100); trk_note_on(&trk[0], 38, 100);
    lead = held(&trk[0], 36); extra = held(&trk[0], 38);
    shed_voice(); mix_block(out, CTL);
    check("overload frees a held one-shot drum without waiting for its decay",
          lead && extra && lead->active && !extra->active && voices_busy() == 1u);

    fresh();
    trk[0].p[P_VOICE] = V_UNISON;
    trk_note_on(&trk[0], 55, 100);
    shed_voice(); mix_block(out, CTL);
    check("UNISON loses an extra voice and retains its lead", trk[0].v[0].active && trk[0].v[0].gate && voices_busy() == NVOICE - 1u);

    for (mode = V_MONO; mode <= V_LEGATO; mode++) {
        fresh(); trk[0].p[P_VOICE] = V_POLY;
        for (i = 0; i < NVOICE; i++) trk_note_on(&trk[0], 48u + 2u * i, 100);
        trk[0].p[P_VOICE] = (int16_t)mode;
        shed_voice(); mix_block(out, CTL);
        check("overload can reclaim stale POLY voices after a MONO / LEGATO change",
              shed_count == 1u && trk[0].v[0].gate && voices_busy() == NVOICE - 1u);
    }

    fresh();
    trk[0].p[P_VOICE] = V_POLY;
    trk_note_on(&trk[0], 60, 100); trk_note_on(&trk[0], 64, 100);
    lead = held(&trk[0], 60); extra = held(&trk[0], 64);
    trk_note_off(&trk[0], 60); trk_note_off(&trk[0], 64);
    lead->env = 10000; extra->env = 10;
    shed_voice();
    check("released voices shed the quieter tail first", extra->stage == 4u && lead->stage != 4u);
}
static void dma(void)
{
    uint32_t i, expected;
    fresh();
    host_pending = 0;
    fm1_alnk0_irq();
    check("an auxiliary interrupt does not render a DMA half", !host_acks && !audio_halves && !felucca_dbg.in_audio);
    host_pending = FM1_AUDIO_HALF;
    host_us = 5000;
    fm1_alnk0_irq();
    check("one slow half records elapsed load but does not shed yet", host_acks == 1u && !shed_req && felucca_dbg.last_us == 5000u && !felucca_dbg.late);
    fm1_alnk0_irq();
    check("a second slow half in a row requests shedding", host_acks == 2u && shed_req);
    shed_req = 0;
    host_half_reads = 0; host_dma_advanced = 1; host_us = 100;
    fm1_alnk0_irq();
    check("DMA advancing during a render is counted once", host_acks == 3u && felucca_dbg.late == 1u && !felucca_dbg.in_audio && !shed_req);
    fresh();
    expected = HALF_FRAMES * 1000000u / FS;            /* the half's deadline in us */
    host_us = expected * 90u / 100u; host_nest = expected * 30u / 100u;   /* the render 60 %, TIMER5 nested 30 % */
    fm1_alnk0_irq(); fm1_alnk0_irq();
    check("TIMER5 nested in the render counts toward the deadline", shed_req && felucca_dbg.last_us == host_us - host_nest);
    fresh();
    host_us = 5000;
    fm1_alnk0_irq(); host_us = 100; fm1_alnk0_irq(); host_us = 5000; fm1_alnk0_irq();
    check("slow halves that are not consecutive do not shed", !shed_req);
    fresh();
    host_us = 580;
    for (i = 0; i < 512u; i++) fm1_alnk0_irq();
    expected = host_us * 256u / (HALF_FRAMES * 1000000u / FS);
    check("steady CPU load converges without integer smoothing bias", song.cpu_q8 >= expected - 1u && song.cpu_q8 <= expected);
}
/* #428: FM1_ASSERT_THREAD fires inside the real audio ISR (fm1_alnk0_irq brackets itself with FM1_ISR_SIM_ENTER/LEAVE)
 * and stays quiet in the main loop, before and after. */
static uint32_t isr_hits;
static void isr_hook(const char *file, int line) { (void)file; (void)line; isr_hits++; }
static void isr_assert(void)
{
    fm1_isr_assert_hook = isr_hook;
    fresh();
    FM1_ASSERT_THREAD();
    check("FM1_ASSERT_THREAD is quiet in the main loop", isr_hits == 0 && fm1_host_isr_depth == 0);
    probe_isr = 1;
    host_pending = FM1_AUDIO_HALF; host_us = 100;
    fm1_alnk0_irq();
    probe_isr = 0;
    check("FM1_ASSERT_THREAD fires once inside the audio ISR", isr_hits == 1u);
    check("the simulated ISR context ends with the handler", fm1_host_isr_depth == 0);
    FM1_ASSERT_THREAD();
    check("FM1_ASSERT_THREAD is quiet again in the main loop", isr_hits == 1u);
    fm1_isr_assert_hook = 0;
}
/* MENU > USB LEVEL (fx.c fx_usb_fixed, audio.c audio_block): MASTER (default) as before, USB = the DAC's signal and
 * follows the knob; FIXED: USB at the full level whatever MASTER is (MASTER 0: USB still plays, the DAC is silent),
 * the DAC exactly USB scaled by MASTER */
static double block_rms(const int32_t *b, uint32_t n)
{
    double s = 0;
    uint32_t i;
    for (i = 0; i < 2u * n; i++) s += (double)b[i] * b[i];
    return sqrt(s / (2.0 * n));
}
static double usb_run(uint32_t fixed, uint32_t master, int dac_is_tap_scaled_ok[1], double *dac_rms)
{
    int32_t out[2 * 32];
    uint32_t b, i;
    double usb = 0, dac = 0;
    fresh();
    lim_env = LIM_T; dc_l = dc_r = dce_l = dce_r = 0;    /* (the master's state as at power-on: runs compare) */
    trk[0].p[P_VOICE] = V_POLY;
    trk[0].p[P_DIST] = trk[0].p[P_CHOR] = trk[0].p[P_DLY] = trk[0].p[P_REV] = 0;   /* (no tails between runs) */
    trk_note_on(&trk[0], 48, 110); trk_note_on(&trk[0], 55, 110); trk_note_on(&trk[0], 64, 110);
    fx_usb_fixed = (uint8_t)fixed;
    song.master_q12 = master;
    dac_is_tap_scaled_ok[0] = 1;
    for (b = 0; b < 400u; b++) {                       /* ~0.3 s */
        audio_block(out, 32);
        for (i = 0; i < 64u; i++) {
            int32_t want = fixed ? ((host_tap[i] * (int32_t)master) >> 12) << OUT_SHIFT : host_tap[i] << OUT_SHIFT;
            if (out[i] != want) dac_is_tap_scaled_ok[0] = 0;
        }
        if (b >= 100u) { usb += block_rms(host_tap, 32); dac += block_rms(out, 32) / (1 << OUT_SHIFT); }
    }
    fx_usb_fixed = 0;
    *dac_rms = dac / 300.0;
    return usb / 300.0;
}
static void usb_level(void)
{
    int ok_full, ok_quiet, ok_off, ok_fixed, ok_fixed0;
    double d_full, d_quiet, d_off, d_fixed, d_fixed0;
    double u_full = usb_run(0, 4096, &ok_full, &d_full), u_quiet = usb_run(0, 1024, &ok_quiet, &d_quiet);
    double u_off = usb_run(0, 0, &ok_off, &d_off), u_fixed = usb_run(1, 1024, &ok_fixed, &d_fixed);
    double u_fixed0 = usb_run(1, 0, &ok_fixed0, &d_fixed0);
    printf("audio: USB / DAC rms: MASTER full %.0f / %.0f, 1/4 %.0f / %.0f, 0 %.0f / %.0f; FIXED 1/4 %.0f / %.0f, 0 %.0f / %.0f\n",
           u_full, d_full, u_quiet, d_quiet, u_off, d_off, u_fixed, d_fixed, u_fixed0, d_fixed0);
    check("USB LEVEL MASTER (default): USB is the DAC's signal and follows the knob (0: silent)",
          ok_full && ok_quiet && ok_off && u_full > 1000.0 && u_quiet < u_full * 0.5 && u_off == 0.0);
    check("USB LEVEL FIXED: USB at the full level whatever MASTER is (within 0.1 dB), MASTER 0 too",
          fabs(20.0 * log10(u_fixed / u_full)) < 0.1 && fabs(20.0 * log10(u_fixed0 / u_full)) < 0.1);
    check("USB LEVEL FIXED: the DAC gets exactly USB scaled by MASTER (MASTER 0: silent, 1/4: -12 dB)",
          ok_fixed && ok_fixed0 && d_fixed0 == 0.0 && fabs(20.0 * log10(d_fixed / u_fixed) + 12.04) < 0.2);
}

/* #137: keys pressed under the splash. main.c: master_boot before audio_init (the pot's level from the first block),
 * kb_boot_hold until the splash ends (seq.c keyboard_block: the keys sound nothing; one held across stays silent until
 * pressed again); the splash polls the pot (master_poll). boot 0: as before the fix */
static void boot_fresh(void)
{
    fresh();
    lim_env = LIM_T; dc_l = dc_r = dce_l = dce_r = 0;
    memset(kb_note, 0, sizeof kb_note); kb_prev = 0; kb_layer = 0;
    trk[0].p[P_VOICE] = V_POLY;
    trk[0].p[P_DIST] = trk[0].p[P_CHOR] = trk[0].p[P_DLY] = trk[0].p[P_REV] = 0;
}
static double boot_run(int32_t pot, int boot, uint32_t *splash_peak, uint32_t *first_master, uint32_t *busy)
{
    int32_t out[2 * 32];
    uint32_t b, i, peak = 0;
    double r = 0;
    boot_fresh();
    song.master_q12 = 2048;                            /* felucca_init */
    master_knob = 512 * 16;
    host_pot = pot;
    if (boot) {
        master_boot();
        kb_boot_hold = 1;
    }
    *first_master = song.master_q12;
    for (b = 0; b < 600u; b++) {                       /* the splash, ~0.43 s: keys hammered, one held at its end */
        fm1_in.notes = b >= 580u ? 1u << 12 : (b / 40u) & 1u ? (1u << 7) | (1u << 11) : 1u << 4;
        if (b % 14u == 0u && boot)
            master_poll();
        audio_block(out, 32);
        for (i = 0; i < 64u; i++)
            if ((uint32_t)abs(out[i]) > peak) peak = (uint32_t)abs(out[i]);
    }
    *splash_peak = peak;
    kb_boot_hold = 0;                                  /* the UI */
    *busy = 0;
    for (b = 0; b < 400u; b++) {                       /* the held key (silent), let go; then a chord pressed */
        fm1_in.notes = b < 40u ? 1u << 12 : b < 60u ? 0u : (1u << 0) | (1u << 4) | (1u << 7);
        audio_block(out, 32);
        if (b >= 60u) r += block_rms(out, 32);
        if (b == 39u) *busy = voices_busy();
    }
    fm1_in.notes = 0;
    return r / 340.0;
}
static void boot_keys(void)
{
    uint32_t peak, peak0, peak_old, m, m0, m_old, busy, busy0, busy_old, ref_m, b;
    double quiet, silent, old, ref = 0;
    int32_t out[2 * 32];
    quiet = boot_run(300, 1, &peak, &m, &busy);
    silent = boot_run(0, 1, &peak0, &m0, &busy0);
    old = boot_run(300, 0, &peak_old, &m_old, &busy_old);
    boot_fresh();                                      /* the reference: the chord, MASTER at the pot's level by hand */
    song.master_q12 = ref_m = master_of_pot(300);
    for (b = 0; b < 340u; b++) {
        fm1_in.notes = (1u << 0) | (1u << 4) | (1u << 7);
        audio_block(out, 32);
        ref += block_rms(out, 32);
    }
    fm1_in.notes = 0;
    ref /= 340.0;
    printf("audio: boot, pot 300 (MASTER %u): splash peak %u, then rms %.0f (by hand %.0f); before the fix: "
           "MASTER %u, splash peak %u, then rms %.0f\n", m, peak, quiet, ref, m_old, peak_old, old);
    check("#137 boot: MASTER is the pot's level before the first block (pot 300, pot 0)",
          m == ref_m && m0 == 0u && m_old == 2048u);
    check("#137 boot: keys hammered under the splash sound nothing (before the fix: they did)",
          peak == 0u && peak0 == 0u && peak_old > 0u);
    check("#137 boot: a key held across the splash's end stays silent until pressed again",
          busy == 0u && busy0 == 0u && busy_old > 0u);
    check("#137 boot: after the splash the keys play at the pot's level, as set by hand (pot 0: silent)",
          ref > 100.0 && fabs(quiet - ref) < 1e-9 && silent == 0.0);
}

/* Byte-for-byte matched observer OFF/ON output/state, independent of host clock
 * call count. Only the synthetic timing differs; both remain below shedding. */
static int stage_equivalence(const char *path)
{
    uint32_t b, p;
    FILE *f = fopen(path, "wb");
    if (!f) return 2;
    fresh();
    song.master_q12 = 4096;
    host_us = 1;
    trk_note_on(&trk[0], 48, 100);
    trk_note_on(&trk[0], 55, 90);
    for (b = 0; b < 80u; b++) {
        if (b == 24u) trk_note_off(&trk[0], 48);
        if (b == 40u) trk_note_off(&trk[0], 55);
        fm1_alnk0_irq();
        if (fwrite(abuf, sizeof abuf[0], HALF_WORDS, f) != HALF_WORDS) return 2;
        for (p = 0; p < NPART; p++)
            if (fwrite(trk[p].v, sizeof trk[p].v, 1, f) != 1) return 2;
    }
    return fclose(f) != 0;
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    if (getenv("STAGE_EQUIVALENCE")) return stage_equivalence(getenv("STAGE_EQUIVALENCE"));
    usb_level();
    boot_keys();
    overload();
#if FELUCCA_RENDER_STAGE
    stage_observer();             /* dma()'s two-read synthetic clock is specific to the OFF build */
#else
    dma();
#endif
    isr_assert();
    printf(bad ? "audio: %d FAILED\n" : "audio: all passed\n", bad);
    return bad != 0;
}
