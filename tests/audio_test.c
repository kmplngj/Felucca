/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* The real audio ISR with a simulated DMA and clock: overload must free work
 * within one block without cutting another part's lead or bass. */
#ifdef C1_HOST
#include "c1_host.h"
#endif
#define FELUCCA_UAC 1
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
static int32_t host_tap[2 * 64];
static uint32_t host_tap_n;
static void host_audio_tap(const int32_t *out, uint32_t n)
{
    memcpy(host_tap, out, 8u * n); host_tap_n = n;
    uac_tap(out, n);                                    /* the real producer, including its 48 kHz FIR */
}
static int probe_isr;                                  /* isr_assert(): the stub calls a main-loop-only check from the render */
static void host_render_start(void) { if (probe_isr) FM1_ASSERT_THREAD(); uac_render_start(); }
#define uac_tap host_audio_tap
#define uac_render_start host_render_start
#include "../firmware/src/audio.c"
#undef uac_tap
#undef uac_render_start
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
/* #775: matched renders, no replacement mixer or USB implementation.  The packet
 * adapter calls usb.c directly; uac_test retains the independent FIR/transport oracle.
 * Each case is 0.87 s: held chord, released voices, then FX alone. */
#define USB_BLOCKS 1200u
#define USB_WORDS (USB_BLOCKS * CTL * 2u)
#define USB_PACKETS USB_WORDS
static struct usb_capture {
    int32_t tap[USB_WORDS], dac[USB_WORDS];
    uint32_t packet[USB_PACKETS], np;
    double energy[3][2];
    uint32_t tail_voices, transport_ok;
} usb_full, usb_off, usb_on;

static void usb_fresh(uint32_t eq)
{
    fresh();
    memset(&fx, 0, sizeof fx); memset(&hl, 0, sizeof hl);
    memset(dly_buf, 0, sizeof dly_buf); memset(cho_buf, 0, sizeof cho_buf);
    memset(rev_comb, 0, sizeof rev_comb); memset(&rev_u, 0, sizeof rev_u);
    memset(&pf, 0, sizeof pf);
    pf.src = pf.next = PF_N; pf.lc = PF_TOP;
    for (uint32_t p = 0; p < NPART; p++) pf.mg[p] = 32768;
    perf_held = perf_latched = perf_act = perf_kill = perf_solo = 0;
    memset((void *)perf_k, 0, sizeof perf_k);
    lim_env = LIM_T; dc_l = dc_r = dce_l = dce_r = 0;
    lc_l1 = lc_l2 = lc_r1 = lc_r2 = 0; memset(lce, 0, sizeof lce);
    sb_lp1 = sb_lp2 = sb_lp3 = sb_lp4 = sb_env = sb_h1 = sb_h2 = sb_hl = 0;
    fx_lowcut = (uint8_t)eq;
    seq_stop(); clk_pos = CLK_START; clk_step = 0;
    memset(&clk, 0, sizeof clk);
    click_req = cin_bars = 0; click_lvl = 1;
    fm1_in.notes = kb_prev = 0; kb_boot_hold = 0;
    memset(&midi_clock, 0, sizeof midi_clock); mi_r = mi_w = 0;
    vage = 0;
    for (uint32_t p = 0; p < 2u; p++) {
        trk[p].p[P_VOICE] = V_POLY;
        trk[p].p[P_LEVEL] = 70;
        trk[p].p[P_PAN] = p ? 40 : -40;
        trk[p].p[P_ATK] = 0; trk[p].p[P_SUS] = 100; trk[p].p[P_REL] = 25;
        trk[p].p[P_DIST] = 0;
        trk[p].p[P_CHOR] = 50; trk[p].p[P_DLY] = 60; trk[p].p[P_REV] = 70;
    }
    trk_note_on(&trk[0], 43, 95); trk_note_on(&trk[1], 64, 105);
    song.g[G_BPM] = 120; song.g[G_DTIME] = 2;
    song.g[G_RSIZE] = 90;
}

static void usb_run(struct usb_capture *c, uint32_t fixed, uint32_t master,
                    uint32_t click, uint32_t eq, uint32_t rate, int switching)
{
    int32_t out[2u * CTL];
    uint32_t b, i, next_ms = 1;
    usb_fresh(eq);
    memset(c, 0, sizeof *c);
    memset(&uac, 0, sizeof uac); ua_w = ua_r = 0;
    usb.config = 1; uac_rate_set(rate); uac_stream(1); uac.flowing = 1;
    fx_usb_fixed = (uint8_t)fixed; song.master_q12 = master;
    click_mode = click ? CLICK_ON : CLICK_OFF;
    transport_req = 1;                                /* empty patterns; held notes are independent */
    for (b = 0; b < USB_BLOCKS; b++) {
        if (switching) fx_usb_fixed = (uint8_t)((b / 200u) & 1u);
        if (b == 400u) {
            trk_note_off(&trk[0], 43); trk_note_off(&trk[1], 64);
        }
        if (b % (HALF_FRAMES / CTL) == 0) uac_render_start();
        audio_block(out, CTL);
        memcpy(c->tap + b * 2u * CTL, host_tap, sizeof out);
        for (i = 0; i < 2u * CTL; i++) c->dac[b * 2u * CTL + i] = out[i] / (1 << OUT_SHIFT);
        if (b == 700u) c->tail_voices = voices_busy();
        uint32_t phase = b < 400u ? 0 : b < 500u ? 1 : 2;
        for (i = 0; i < 2u * CTL; i++)
            if (b < 500u || b >= 700u)
                c->energy[phase][i & 1u] += (double)host_tap[i] * host_tap[i];
        /* Instantaneous half renders at nominal I2S cadence; drain the intervening
         * 1 ms packets as a burst. This offline adapter checks routing/ordering,
         * not ISR/service interleaving, render lateness or physical deadlines. */
        if ((b + 1u) % (HALF_FRAMES / CTL) == 0)
            while ((uint64_t)next_ms * 24000u <= (uint64_t)(b + 1u) * CTL * DAC_TICKS) {
                uint32_t packet[UA_MAXF], n = uac_packet(packet);
                if (c->np + n > USB_PACKETS) abort();
                memcpy(c->packet + c->np, packet, n * sizeof *packet); c->np += n;
                next_ms++;
            }
    }
    c->transport_ok = !uac.underruns && !uac.overruns && c->np > FS / 2u;
    /* Independent 44.1 oracle: priming silence, then every rendered stereo
     * frame once, in order. Do not read ua_ring or call the production packer. */
    if (rate == 44100u)
        for (i = 0; i < c->np; i++) {
            uint32_t want = 0;
            if (i >= UA_PRIME) {
                uint32_t at = 2u * (i - UA_PRIME);
                want = (uint16_t)c->tap[at] | (uint32_t)(uint16_t)c->tap[at + 1u] << 16;
            }
            c->transport_ok &= c->packet[i] == want;
        }
    /* The 48 kHz numerical FIR oracle remains in uac_test. Here require the
     * rendered stream's duration and both packet channels to carry music. */
    c->transport_ok &= c->np > (uint64_t)USB_BLOCKS * CTL * rate / FS * 98u / 100u &&
                       c->np < (uint64_t)USB_BLOCKS * CTL * rate / FS * 102u / 100u;
    uac_stream(0); usb.config = 0; fx_usb_fixed = fx_lowcut = click_mode = 0;
}

static void usb_level(void)
{
    static const uint32_t masters[3] = {0, 1024, 4096};
    static int32_t previous_eq[USB_WORDS];
    uint32_t rate, eq, fixed, m, i, ch, phase;
    char label[150];
    for (rate = 44100; rate <= (FELUCCA_UAC_48K ? 48000u : 44100u); rate += 3900)
        for (eq = 0; eq < 3u; eq++) {
            usb_run(&usb_full, 0, 4096, 0, eq, rate, 0);
            int bounded = 1;
            uint32_t changed[2] = {0, 0};
            for (i = 0; i < USB_WORDS; i++) {
                bounded &= abs(usb_full.tap[i]) < 32000;
                changed[i & 1u] += usb_full.tap[i] != previous_eq[i];
            }
            snprintf(label, sizeof label, "%u Hz EQ %u: full reference has headroom; EQ reaches both shared output channels", rate, eq);
            check(label, bounded && (!eq || (changed[0] > 1000u && changed[1] > 1000u)));
            memcpy(previous_eq, usb_full.tap, sizeof previous_eq);
            for (fixed = 0; fixed < 2u; fixed++)
                for (m = 0; m < 3u; m++) {
                    uint32_t master = masters[m];
                    int route = 1, clean = 1, audible = 1, click_dac = 0, stereo = 0;
                    usb_run(&usb_off, fixed, master, 0, eq, rate, 0);
                    usb_run(&usb_on, fixed, master, 1, eq, rate, 0);
                    for (i = 0; i < USB_WORDS; i++) {
                        int32_t tap = usb_off.tap[i];
                        int32_t want = fixed ? (tap * (int32_t)master) >> 12 : tap;
                        route &= usb_off.dac[i] == want;
                        if (fixed || master == 4096) route &= tap == usb_full.tap[i];
                        if (!master) route &= !usb_off.dac[i] && !usb_on.dac[i] && (fixed || !tap);
                        clean &= usb_on.tap[i] == tap;
                        click_dac |= usb_on.dac[i] != usb_off.dac[i];
                        if ((i & 1u) && usb_full.tap[i] != usb_full.tap[i - 1u]) stereo = 1;
                    }
                    clean &= usb_on.np == usb_off.np && !memcmp(usb_on.packet, usb_off.packet, usb_on.np * sizeof(uint32_t));
                    if (fixed || master == 4096)
                        route &= usb_off.np == usb_full.np && !memcmp(usb_off.packet, usb_full.packet, usb_off.np * sizeof(uint32_t));
                    for (ch = 0; ch < 2u; ch++)
                        for (phase = 0; phase < 3u; phase++) {
                            double e = usb_off.energy[phase][ch], full = usb_full.energy[phase][ch];
                            audible &= full > 1000000.0;
                            if (fixed || master) audible &= e > 1000.0;
                            if (!fixed && master == 1024) audible &= e < full * 0.3;
                        }
                    for (ch = 0; ch < 2u; ch++) {
                        double packet_energy = 0;
                        for (i = 0; i < usb_off.np; i++) {
                            int16_t v = (int16_t)(usb_off.packet[i] >> (16u * ch));
                            packet_energy += (double)v * v;
                        }
                        audible &= fixed || master ? packet_energy > 1000000.0 : packet_energy == 0;
                    }
                    if (!fixed && !master)
                        for (i = 0; i < usb_off.np; i++) route &= !usb_off.packet[i];
                    snprintf(label, sizeof label, "%u Hz EQ %u %s MASTER %u: stereo held/release/FX, DAC/tap/packets, click OFF/ON",
                             rate, eq, fixed ? "FIXED" : "MASTER", master);
                    check(label, route && clean && audible && stereo && !usb_off.tail_voices &&
                          usb_off.transport_ok && usb_on.transport_ok && (master ? click_dac : !click_dac));
                }
            /* Full MASTER makes the two routing paths identical: switching while
             * sounding and during release/tails must preserve every stereo sample. */
            usb_run(&usb_on, 0, 4096, 0, eq, rate, 1);
            snprintf(label, sizeof label, "%u Hz EQ %u: MASTER <-> FIXED during held notes, release and FX tails", rate, eq);
            check(label, !memcmp(usb_on.tap, usb_full.tap, sizeof usb_full.tap) &&
                  !memcmp(usb_on.dac, usb_full.dac, sizeof usb_full.dac) && usb_on.np == usb_full.np &&
                  !memcmp(usb_on.packet, usb_full.packet, usb_on.np * sizeof(uint32_t)) && usb_on.transport_ok);
            usb_run(&usb_on, 0, 1024, 0, eq, rate, 1);
            int route = 1;
            double held_master[2] = {0, 0}, held_fixed[2] = {0, 0};
            for (i = 0; i < USB_WORDS; i++) {
                uint32_t b = i / (2u * CTL), fixed_now = (b / 200u) & 1u;
                int32_t tap = usb_on.tap[i];
                route &= usb_on.dac[i] == (fixed_now ? (tap * 1024) >> 12 : tap);
                if (b >= 100u && b < 200u) held_master[i & 1u] += (double)tap * tap;
                if (b >= 300u && b < 400u) held_fixed[i & 1u] += (double)tap * tap;
            }
            snprintf(label, sizeof label, "%u Hz EQ %u: live MASTER <-> FIXED at quarter MASTER preserves DAC scaling", rate, eq);
            check(label, route && usb_on.transport_ok && !usb_on.tail_voices &&
                  held_fixed[0] > 2.0 * held_master[0] && held_fixed[1] > 2.0 * held_master[1]);
        }
    /* Keep the following boot/overload fixtures independent of this FX history. */
    usb_fresh(0); fresh();
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
    if (fclose(f)) return 2;
#ifdef C1_HOST
    if (!c1h_taken || !c1h_blocks) {
        fputs("audio: threaded fixture dispatched no worker blocks\n", stderr);
        return 2;
    }
#endif
    return 0;
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
