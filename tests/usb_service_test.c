/* SPDX-License-Identifier: GPL-3.0-only */
/* #101: actual composite service against a finite HAL-only host model.
 * This models CSR/DMA ownership, not AC791N timing, PHY races or a host driver.
 * Full poll and nested EP4 service are serialized, as TIMER5 owns both. Existing
 * uac_test owns drift/FIR accuracy; partition_test owns musical PCM/transport.
 * No USB protocol, queue or recovery implementation is replaced here. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef T_CDC
#error "compile with -DT_CDC=0 or 1"
#endif
#ifndef HALF_FRAMES
#error "use the firmware's HALF_FRAMES"
#endif
#define FELUCCA_CDC T_CDC
#define FELUCCA_UAC 1
#define FELUCCA_OTA 1
#ifndef FELUCCA_RESTART
#define FELUCCA_RESTART 1
#endif
#define RING_PUBLISH() __asm__ volatile("" ::: "memory")
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "usb service:%d: %s\n", __LINE__, #x); exit(1); } } while (0)
/* Parse the actual HAL once. Only its call sites below are substituted; the
 * production driver, including its SIE completion loops, is included intact. */
#pragma GCC diagnostic ignored "-Wint-to-pointer-cast"
#include "../firmware/hal/fm1_usb.h"
static void host_write(uint32_t r, uint32_t v);
static void host_read(uint32_t r);
static uint32_t host_data(void);
static uint32_t host_on(void);
static uint32_t host_done(void);
static uint32_t host_sof(void);
static void host_reset(void);
static void host_attach(void *p);
static void host_off(void);
static void fm1_delay_ms(uint32_t ms);
static void host_buf(uint32_t ep, void *p, int tx);
static void host_send(uint32_t ep, void *p, uint32_t n);
static void host_enable(uint32_t mask);
#define fm1_usb_reset() host_reset()
#define fm1_usb_attach(p) host_attach(p)
#define fm1_usb_off() host_off()
#define fm1_usb_sie_on() host_on()
#define fm1_usb_sie_wr_start(r, v) host_write(r, v)
#define fm1_usb_sie_rd_start(r) host_read(r)
#define fm1_usb_sie_done() host_done()
#define fm1_usb_sie_data() host_data()
#define fm1_usb_ep0_buf(p) host_buf(0, p, 0)
#define fm1_usb_ep_txbuf(ep, p) host_buf(ep, p, 1)
#define fm1_usb_ep_rxbuf(ep, p) host_buf(ep, p, 0)
#define fm1_usb_ep0_send(p, n) host_send(0, p, n)
#define fm1_usb_ep_send(ep, p, n) host_send(ep, p, n)
#define fm1_usb_ep4_txbuf(p) host_buf(4, p, 1)
#define fm1_usb_ep4_send(p, n) host_send(4, p, n)
#define fm1_usb_ep_enable(mask) host_enable(mask)
#define fm1_usb_rx_sync() ((void)0)
#define fm1_usb_sof_take() host_sof()
#include "../firmware/src/usb.c"

#define LOG_N 65536u
#define PACKETS 512u
static struct {
    uint8_t common[16], ep[5][24], selected, data;
    uint32_t on, sof_each_poll, starts, checks, data_reads, delay, missing;
    uint32_t pending_r, pending_v, pending_read, completed, polls;
    uint32_t resets, attaches, offs, delay_calls, delay_ms;
    void *rx[5], *tx[5];
    uint8_t staged[5][196];
    uint32_t staged_n[5], prepared[5], enabled, operations, max_operations;
    uint32_t sends[5], rx_acks[5], touched, common_touched, frame, stall_requested;
    uint8_t bytes[5][LOG_N];
    uint32_t lengths[5][PACKETS], nbytes[5], npackets[5];
} host;

static void host_enable(uint32_t mask) { host.enabled |= mask; }
static void host_buf(uint32_t ep, void *p, int tx)
{
    CHECK(ep < 5u);
    if (tx) host.tx[ep] = p; else host.rx[ep] = p;
}
static void host_send(uint32_t ep, void *p, uint32_t n)
{
    uint32_t cap = ep == 4u ? 196u : ep == 3u ? 63u : 64u;
    CHECK(ep < 5u && n <= cap);
    CHECK(ep == 0u || (host.enabled & (1u << ep)));
    /* A DMA preparation is not a completed host transfer. Only host_in below
     * consumes it, and only when production writes TxPktRdy. */
    CHECK(!(host.ep[ep][S_TXCSR1] & 1u) || ep == 0u);
    memcpy(host.staged[ep], p, n);
    host.staged_n[ep] = n;
    host.prepared[ep] = 1;
    host.sends[ep]++;
    host.touched |= 1u << ep;
}
static void host_apply_write(uint32_t r, uint32_t v)
{
    uint32_t ep = host.selected;
    if (r == S_INDEX) { CHECK(v < 5u); host.selected = (uint8_t)v; return; }
    if (r < 16u) { host.common_touched |= 1u << r; host.common[r] = (uint8_t)v; return; }
    host.touched |= 1u << ep;
    if (ep == 0u && r == S_CSR0) {
        uint8_t *csr = &host.ep[0][S_CSR0];
        if (v & 0x40u) *csr &= (uint8_t)~1u;     /* ServicedRxPktRdy */
        if (v & 0x80u) *csr &= (uint8_t)~0x10u;  /* ServicedSetupEnd */
        if (!v) *csr &= (uint8_t)~4u;            /* clear SentStall */
        if (v & 0x20u) host.stall_requested = 1; /* SendStall awaits a host token */
        if (v & 2u) *csr |= 2u;                 /* EP0 TxPktRdy */
    } else if (r == S_TXCSR1) {
        host.ep[ep][r] = (uint8_t)(v & 0x85u);  /* ready/underrun/sent-stall */
        if (v & 8u) {                          /* FlushFIFO */
            host.ep[ep][r] &= (uint8_t)~1u;
            host.prepared[ep] = 0;
        }
    } else if (r == S_RXCSR1 && (v & 0x10u)) {
        if (host.ep[ep][r] & 1u) host.rx_acks[ep]++;
        host.ep[ep][r] = (uint8_t)(v & ~1u);    /* service/flush RX packet */
    } else host.ep[ep][r] = (uint8_t)v;
}
static void host_apply_read(uint32_t r)
{
    if (r < 16u) {
        host.common_touched |= 1u << r;
        host.data = host.common[r];
        if (r == S_INTRUSB || r == S_INTRTX1 || r == S_INTRRX1)
            host.common[r] = 0;                /* read-to-clear interrupt latch */
    } else {
        host.touched |= 1u << host.selected;
        host.data = host.ep[host.selected][r];
    }
}
/* One command can be delayed or never complete. Effects happen only on done;
 * failed reads leave their read-clear latch and stale data register untouched.
 * The check cap is a model-operation oracle, not an AC791N time measurement. */
static void host_command(uint32_t r, uint32_t v, uint32_t read)
{
    CHECK(host.on && r < 24u && ++host.operations <= 128u);
    host.starts++;
    host.pending_r = r; host.pending_v = v; host.pending_read = read;
    host.polls = host.completed = 0;
}
static void host_write(uint32_t r, uint32_t v) { host_command(r, v, 0); }
static void host_read(uint32_t r) { host_command(r, 0, 1); }
static uint32_t host_on(void) { return host.on; }
static uint32_t host_done(void)
{
    CHECK(host.starts && ++host.polls <= 20000u);
    host.checks++;
    if (host.missing || host.polls <= host.delay) return 0;
    if (!host.completed) {
        if (host.pending_read) host_apply_read(host.pending_r);
        else host_apply_write(host.pending_r, host.pending_v);
        host.completed = 1;
    }
    return 1;
}
static uint32_t host_data(void)
{
    CHECK(host.completed && host.pending_read);
    host.data_reads++;
    return host.data;
}
/* The script supplies one SOF event per poll unless that input is disabled. */
static uint32_t host_sof(void) { return host.sof_each_poll; }
static void host_reset(void)
{
    host.resets++;
    host.on = host.enabled = host.completed = 0;
    memset(host.common, 0, sizeof host.common); memset(host.ep, 0, sizeof host.ep);
    memset(host.prepared, 0, sizeof host.prepared);
    memset(host.rx, 0, sizeof host.rx); memset(host.tx, 0, sizeof host.tx);
}
static void fm1_delay_ms(uint32_t ms)
{
    CHECK(!host.on && host.resets == host.attaches + 1u && ms == 25u);
    host.delay_calls++; host.delay_ms += ms;
}
static void host_attach(void *p)
{
    CHECK(!host.on && host.resets == host.attaches + 1u && host.delay_calls == host.resets);
    host.attaches++; host.on = 1;
    host_buf(0, p, 0);
}
static void host_off(void)
{
    host.offs++; host.on = 0;
}
static void bounds(void)
{
    CHECK(mi_w - mi_r <= MQ && mo_w - mo_r <= MQ);
    CHECK(so_w - so_r <= SXQ && ua_w - ua_r <= UA_N);
#if T_CDC
    CHECK(ci_w - ci_r <= CI_N && co_w - co_r <= CO_N);
#endif
}
static void service(int nested)
{
    host.operations = host.touched = host.common_touched = 0;
    host.common[S_FRAME1] = (uint8_t)host.frame;
    host.common[S_FRAME2] = (uint8_t)((host.frame >> 8) & 7u);
    if (nested) {
        uac_service();
        CHECK(!(host.touched & ~(1u << 4)) && !host.common_touched);
    } else usb_poll();
    if (host.operations > host.max_operations) host.max_operations = host.operations;
    bounds();
}
static int host_in(uint32_t ep)
{
    uint32_t n, k, ready = ep == 0u ? 2u : 1u;
    if (!(host.ep[ep][S_TXCSR1] & ready)) return 0;
    CHECK(host.prepared[ep]);
    n = host.staged_n[ep]; k = host.npackets[ep];
    CHECK(k < PACKETS && host.nbytes[ep] + n <= LOG_N);
    memcpy(host.bytes[ep] + host.nbytes[ep], host.staged[ep], n);
    host.lengths[ep][k] = n;
    host.nbytes[ep] += n; host.npackets[ep]++;
    host.ep[ep][S_TXCSR1] &= (uint8_t)~ready;
    host.prepared[ep] = 0;
    return 1;
}
static void host_out(uint32_t ep, const uint8_t *p, uint32_t n)
{
    CHECK((ep == 0u || ep == 1u || ep == 3u) && n <= 64u);
    CHECK(!(host.ep[ep][S_RXCSR1] & 1u) || ep == 0u);
    CHECK(host.rx[ep]);
    memcpy(host.rx[ep], p, n);
    if (ep == 0u) {
        CHECK(!(host.ep[0][S_CSR0] & 1u));
        host.ep[0][S_CSR0] |= 1u;
        host.common[S_INTRTX1] |= 1u;
    } else {
        host.ep[ep][S_RXCSR1] |= 1u;
        host.common[S_INTRRX1] |= (uint8_t)(1u << ep);
    }
    host.ep[ep][S_RXCOUNT1] = (uint8_t)n;
    host.ep[ep][S_RXCOUNT2] = 0;
}
static void setup(uint32_t request, uint32_t value, uint32_t index, uint32_t length)
{
    uint8_t s[8] = {(uint8_t)(request >> 8), (uint8_t)request,
                    (uint8_t)value, (uint8_t)(value >> 8), (uint8_t)index,
                    (uint8_t)(index >> 8), (uint8_t)length, (uint8_t)(length >> 8)};
    host_out(0, s, sizeof s);
    service(0);
}
static void configure(uint32_t hz)
{
    uint8_t rate[3] = {(uint8_t)hz, (uint8_t)(hz >> 8), (uint8_t)(hz >> 16)};
    setup(0x0009, 1, 0, 0);
    CHECK(usb.config == 1u);
#if T_CDC
    setup(0x2122, 1, CDC_IF_CDC, 0);
    CHECK(cdc.dtr);
#endif
    setup(0x2201, 0x0100, 0x84, 3);
    CHECK(uac.e0_rx);
    host_out(0, rate, sizeof rate); service(0);
    CHECK(!uac.e0_rx && uac.r48 == (hz == 48000u));
    setup(0x010B, 1, UAC_AS_IF, 0);
    CHECK(uac.alt && !uac.go);
}
static void reset_model(void)
{
    memset(&host, 0, sizeof host); memset(&usb, 0, sizeof usb);
    memset(&uac, 0, sizeof uac); memset(&rs, 0, sizeof rs);
#if T_CDC
    memset(&cdc, 0, sizeof cdc); ci_r = ci_w = co_r = co_w = 0;
#endif
    mi_r = mi_w = mo_r = mo_w = so_r = so_w = ua_r = ua_w = 0;
    sx_ready = sx_collect = sx_busy = midi_in_overflow = 0;
    so_done = so_flight = 0;
    usb_rescue_mode = 0; usb.up = 1;
    host.on = host.sof_each_poll = 1;
    host_buf(0, ep0buf, 0);
}
static void reset_fixture(uint32_t hz)
{
    reset_model();
    configure(hz);
}
static uint32_t ota_now_ms(void) { return fm1_ms; }
static void ota_idle(void) { CHECK(0); }         /* finite fixtures never block a main-loop send */

static void render(uint32_t *source_frame)
{
    int32_t block[64];
    uac_render_start();
    for (uint32_t b = 0; b < HALF_FRAMES / 32u; b++) {
        for (uint32_t j = 0; j < 32u; j++, (*source_frame)++) {
            block[2u * j] = (int32_t)((*source_frame * 73u) % 24001u) - 12000;
            block[2u * j + 1u] = 9000 - (int32_t)((*source_frame * 31u) % 18001u);
        }
        uac_tap(block, 32);
    }
}
static uint32_t midi_packet(uint32_t i) { return 0x00400009u | (0x90u << 8) | ((i & 63u) << 16); }
static void fill_output(void)
{
    static const uint8_t sysex[] = {0xF0, 0x7D, 1, 2, 3, 4, 5, 0xF7};
    CHECK(!ota_wire_send(sysex, sizeof sysex));
    for (uint32_t i = 0; i < MQ; i++) midi_out_event(midi_packet(i));
#if T_CDC
    for (uint32_t i = 0; i < CO_N; i++) cdc_out[co_w++ % CO_N] = (uint8_t)(i * 13u + 7u);
#endif
}
static int output_ok(void)
{
    static const uint8_t sx[] = {4, 0xF0, 0x7D, 1, 4, 2, 3, 4, 6, 5, 0xF7, 0};
    if (host.nbytes[1] != sizeof sx + MQ * 4u || memcmp(host.bytes[1], sx, sizeof sx)) return 0;
    for (uint32_t i = 0; i < MQ; i++) {
        uint32_t k = sizeof sx + i * 4u, got = 0;
        for (uint32_t j = 0; j < 4u; j++) got |= (uint32_t)host.bytes[1][k + j] << (8u * j);
        if (got != midi_packet(i)) return 0;
    }
#if T_CDC
    if (host.nbytes[3] != CO_N) return 0;
    for (uint32_t i = 0; i < CO_N; i++) if (host.bytes[3][i] != (uint8_t)(i * 13u + 7u)) return 0;
#endif
    return 1;
}
/* Two snapshots compare actual host packet boundaries/bytes and final audio
 * state under the SAME producer/IN-token schedule, with/without bulk/control.
 * This is not an independent FIR accuracy oracle or a physical DAC comparison. */
typedef struct {
    uint8_t bytes[LOG_N]; uint32_t lengths[PACKETS], nbytes, npackets, r, w;
    uint32_t underruns, overruns, missed, stalls;
} audio_trace_t;
static audio_trace_t reference;
static void audio_snapshot(audio_trace_t *out)
{
    memcpy(out->bytes, host.bytes[4], host.nbytes[4]);
    memcpy(out->lengths, host.lengths[4], host.npackets[4] * sizeof(uint32_t));
    out->nbytes = host.nbytes[4]; out->npackets = host.npackets[4]; out->r = ua_r; out->w = ua_w;
    out->underruns = uac.underruns; out->overruns = uac.overruns; out->missed = uac.missed; out->stalls = uac.stalls;
}
static int same_audio(const audio_trace_t *a, const audio_trace_t *b)
{
    return a->nbytes == b->nbytes && a->npackets == b->npackets && a->r == b->r && a->w == b->w &&
        a->underruns == b->underruns && a->overruns == b->overruns && a->missed == b->missed && a->stalls == b->stalls &&
        !memcmp(a->bytes, b->bytes, a->nbytes) && !memcmp(a->lengths, b->lengths, a->npackets * sizeof(uint32_t));
}
static void composite(uint32_t hz, int loaded)
{
    uint32_t source_frame = 0, next_half = 0, before_mi = 0;
    uint8_t midi[64], serial[64];
    static audio_trace_t result;
    reset_fixture(hz);
    for (uint32_t i = 0; i < 16u; i++) {
        uint32_t p = midi_packet(i);
        for (uint32_t j = 0; j < 4u; j++) midi[i * 4u + j] = (uint8_t)(p >> (8u * j));
    }
    for (uint32_t i = 0; i < sizeof serial; i++) serial[i] = (uint8_t)(i ^ 0x5Au);
    if (loaded) {
        /* Reserve fewer than the complete EP1 packet+TRS headroom and one
         * byte fewer than the complete CDC packet. No partial acceptance. */
        for (uint32_t i = 0; i < MQ - EP1_ROOM + 1u; i++) CHECK(midi_enqueue(midi_packet(i), 2));
        before_mi = mi_w;
        host_out(1, midi, sizeof midi);
#if T_CDC
        ci_w = CI_N - 63u;
        memset(cdc_in, 0xA5, sizeof cdc_in);
        host_out(3, serial, sizeof serial);
#endif
        fill_output();
        /* Existing host-owned busy IN packets may not be overwritten. */
        host.ep[1][S_TXCSR1] |= 1u;
#if T_CDC
        host.ep[3][S_TXCSR1] |= 1u;
#endif
    }
    for (uint32_t step = 0; step < 240u; step++) {
        /* Logical half-ms steps only. A 128-frame render every ~2.90 ms;
         * real block/IRQ scheduling is deliberately outside this model. */
        uint32_t us = step * 500u;
        host.frame = step / 2u;
        if (us >= next_half) { render(&source_frame); next_half += 2901u; }
        if (!(step & 1u)) (void)host_in(4);
        if (loaded && step == 4u) {
            /* EP0 progresses even while bulk directions are blocked. */
            setup(0x8008, 0, 0, 1);
            CHECK(host_in(0));
            CHECK(host.nbytes[0] == 1u && host.bytes[0][0] == 1u);
        }
        if (loaded && step < 8u) {
            service(0);
            CHECK(mi_w == before_mi && usb.rx_pend && !host.rx_acks[1]);
            CHECK(!mo_r && !so_r && !host.sends[1]);
#if T_CDC
            CHECK(ci_w == CI_N - 63u && cdc.rx_pend && !host.rx_acks[3]);
            CHECK(!co_r && !host.sends[3]);
            for (uint32_t i = 0; i < CI_N; i++) CHECK(cdc_in[i] == 0xA5u);
#endif
        } else {
            if (loaded && step == 8u) {
                mi_r = mi_w;                  /* audio consumer releases capacity */
                host.ep[1][S_TXCSR1] &= (uint8_t)~1u;
#if T_CDC
                ci_r = ci_w;                  /* main-loop consumer releases capacity */
                host.ep[3][S_TXCSR1] &= (uint8_t)~1u;
#endif
            }
            if (loaded && step > 8u) {
                (void)host_in(1);
#if T_CDC
                (void)host_in(3);
#endif
            }
            service(0);
        }
        if (loaded && step == 8u) {
            CHECK(!usb.rx_pend && host.rx_acks[1] == 1u && mi_w - mi_r == 16u);
            for (uint32_t i = 0; i < 16u; i++) {
                CHECK(midi_in_q[(mi_r + i) % MQ] == midi_packet(i));
                CHECK(midi_in_source[(mi_r + i) % MQ] == 1u);
            }
#if T_CDC
            CHECK(!cdc.rx_pend && host.rx_acks[3] == 1u && ci_w - ci_r == sizeof serial);
            for (uint32_t i = 0; i < sizeof serial; i++) CHECK(cdc_in[(ci_r + i) % CI_N] == serial[i]);
#endif
        }
    }
    audio_snapshot(&result);
    CHECK(result.npackets > 100u && result.nbytes > 16000u && source_frame > 4000u);
    CHECK(uac.go && uac.flowing && !result.underruns && !result.overruns && !result.missed && !result.stalls);
    {
        uint32_t nonzero = 0;
        for (uint32_t i = 0; i < result.nbytes; i++) nonzero += result.bytes[i] != 0;
        CHECK(nonzero > result.nbytes / 2u);     /* equality of two silent streams cannot pass */
    }
    if (!loaded) reference = result;
    else {
        CHECK(output_ok());
        CHECK(same_audio(&reference, &result));
        /* Independent transcript oracle must reject corruption and loss. */
        result.bytes[result.nbytes / 2u] ^= 1u; CHECK(!same_audio(&reference, &result));
        result.bytes[result.nbytes / 2u] ^= 1u; result.npackets--; CHECK(!same_audio(&reference, &result));
        host.bytes[1][12] ^= 1u; CHECK(!output_ok()); host.bytes[1][12] ^= 1u;
        CHECK(host.max_operations <= 128u);
        printf("CDC %u %u Hz: composite byte/order/recovery pass; max %u SIE operations/poll\n", T_CDC, hz, host.max_operations);
    }
}
static void stream_transitions(uint32_t hz)
{
    uint32_t frames = 0, before, old_n, other = hz == 44100u ? 48000u : 44100u;
    uint8_t old[196], rate[3] = {(uint8_t)other, (uint8_t)(other >> 8), (uint8_t)(other >> 16)};
    reset_fixture(hz);
    CHECK(host_in(4)); service(0); (void)host_in(4); render(&frames); service(0);
    CHECK(uac.go && host.ep[4][S_TXCSR1] & 1u);
    before = host.sends[4];
    setup(0x010B, 0, UAC_AS_IF, 0);
    CHECK(!uac.alt && !uac.go && !uac.queued && !(host.ep[4][S_TXCSR1] & 1u) && !host.prepared[4]);
    render(&frames); service(0); CHECK(host.sends[4] == before && !host_in(4));
    setup(0x010B, 1, UAC_AS_IF, 0);
    CHECK(uac.alt && !uac.go && host.sends[4] == before + 1u && host_in(4));
    service(0);                               /* observe completion before the producer primes */
    render(&frames); service(0);
    CHECK(uac.go && uac.ring48 == (hz == 48000u));

    /* SET_CUR may leave the single already-queued old-rate packet available.
     * Accept that lifecycle boundary, then require silence and re-priming at
     * the new rate. Do not promise bit-exact uninterrupted audio across it. */
    old_n = host.staged_n[4]; memcpy(old, host.staged[4], old_n);
    before = host.sends[4];
    setup(0x2201, 0x0100, 0x84, 3);
    host_out(0, rate, sizeof rate); service(0);
    CHECK(uac.r48 == (other == 48000u) && !uac.go && host.sends[4] == before);
    CHECK(host.staged_n[4] == old_n && !memcmp(old, host.staged[4], old_n));
    CHECK(host_in(4)); service(0);
    CHECK(host.sends[4] == before + 1u);
    CHECK(host.staged_n[4] == (other == 48000u ? 48u : 44u) * 4u);
    for (uint32_t i = 0; i < host.staged_n[4]; i++) CHECK(!host.staged[4][i]);
    CHECK(host_in(4)); render(&frames); service(0);
    CHECK(uac.go && uac.ring48 == (other == 48000u));
    CHECK(host_in(4) && !uac.underruns && !uac.overruns && !uac.missed);
    puts("queued EP4: alt stop/start flush and streaming rate re-prime passed");
}
static void control_recovery(uint32_t hz)
{
    uint32_t before, mi_before, bulk[6];
    uint8_t saved_usb[sizeof usb];
#if T_CDC
    uint8_t saved_cdc[sizeof cdc];
    uint32_t cdc_indices[4];
#endif
    uint8_t marker[4] = {9, 0x90, 67, 91};
    reset_fixture(hz);
    /* A superseding SETUP must not become the abandoned rate data stage. */
    setup(0x2201, 0x0100, 0x84, 3); CHECK(uac.e0_rx);
    host.ep[0][S_CSR0] |= 0x10u;
    setup(0x8008, 0, 0, 1);
    CHECK(!uac.e0_rx && !(host.ep[0][S_CSR0] & 0x10u));
    CHECK(host_in(0) && host.bytes[0][0] == 1u);
#if T_CDC
    setup(0x2120, 0, CDC_IF_CDC, 7); CHECK(cdc.e0_rx);
    host.ep[0][S_CSR0] |= 0x10u;
    setup(0x8008, 0, 0, 1);
    CHECK(!cdc.e0_rx && !(host.ep[0][S_CSR0] & 0x10u) && host_in(0));
#endif
    setup(0xFFFF, 0, 0, 0);
    CHECK(host.stall_requested && !(host.ep[0][S_CSR0] & 4u));
    host.stall_requested = 0;                  /* explicit host token observes STALL */
    host.ep[0][S_CSR0] |= 4u;
    host.common[S_INTRTX1] |= 1u; service(0);
    CHECK(!(host.ep[0][S_CSR0] & 4u) && !usb.e0_tx);
    setup(0x8008, 0, 0, 1); CHECK(host_in(0));

    /* Actual nested service owns EP4 only, even with bulk traffic waiting. */
    host_out(1, marker, sizeof marker); fill_output();
    bulk[0] = mi_w; bulk[1] = mi_r; bulk[2] = mo_w; bulk[3] = mo_r; bulk[4] = so_w; bulk[5] = so_r;
    memcpy(saved_usb, &usb, sizeof usb);
#if T_CDC
    memcpy(saved_cdc, &cdc, sizeof cdc);
    cdc_indices[0] = ci_w; cdc_indices[1] = ci_r; cdc_indices[2] = co_w; cdc_indices[3] = co_r;
#endif
    (void)host_in(4);
    before = host.sends[4]; service(1);
    CHECK(host.sends[4] == before + 1u && host.ep[4][S_TXCSR1] & 1u);
    CHECK(mi_w == bulk[0] && mi_r == bulk[1] && mo_w == bulk[2] && mo_r == bulk[3] && so_w == bulk[4] && so_r == bulk[5]);
    CHECK(!memcmp(saved_usb, &usb, sizeof usb));
#if T_CDC
    CHECK(!memcmp(saved_cdc, &cdc, sizeof cdc));
    CHECK(ci_w == cdc_indices[0] && ci_r == cdc_indices[1] && co_w == cdc_indices[2] && co_r == cdc_indices[3]);
#endif
    before = host.sends[4];
    service(1); CHECK(host.sends[4] == before);    /* no new host IN: no overwrite/rearm */
    CHECK(host_in(4)); service(1); CHECK(host.sends[4] == before + 1u);
    /* Withholding a host completion must not fabricate transmitted packets. */
    before = host.npackets[4]; service(1); CHECK(host.npackets[4] == before);

    service(0);                               /* accepted input has an application lifetime */
    CHECK(mi_w == 1u && midi_in_q[0] == 0x5B439009u && host.rx_acks[1] == 1u);
    #if T_CDC
    setup(0x2120, 0, CDC_IF_CDC, 7); CHECK(cdc.e0_rx);
#else
    setup(0x2201, 0x0100, 0x84, 3); CHECK(uac.e0_rx);
#endif
    mi_before = mi_w; before = usb.resets;
    host.common[S_INTRUSB] |= 4u;
    service(0);
    CHECK(usb.resets == before + 1u && !usb.config && !usb.rx_pend);
    CHECK(mo_r == mo_w && so_r == so_w && !sx_collect && !usb.e0_tx && !usb.has_pend_addr);
    CHECK(!uac.alt && !uac.r48 && !uac.e0_rx && !uac.go);
    CHECK(mi_w == mi_before);                   /* reset does not erase accepted input */
#if T_CDC
    CHECK(!cdc.dtr && !cdc.e0_rx && !cdc.rx_pend);
    /* Console rings have application lifetimes, not a reset-clears-all promise. */
    co_r = co_w; ci_r = ci_w;
#endif
    /* Model the host's bus reset discarding pending endpoint transactions.
     * Production SET_CONFIGURATION below must then arm their real DMA/CSRs. */
    memset(host.ep, 0, sizeof host.ep); memset(host.prepared, 0, sizeof host.prepared);
    host.enabled = 0;
    configure(hz);
    CHECK(host.rx[1] == ep1rx && host.tx[1] == ep1tx && host.tx[4] == ep4tx);
    host_out(1, marker, sizeof marker);
    midi_out_event(0x5B439009u);
#if T_CDC
    {   static const uint8_t text[4] = {'N', 'E', 'W', '!'};
        host_out(3, text, sizeof text);
        for (uint32_t i = 0; i < sizeof text; i++) cdc_out[co_w++ % CO_N] = text[i];
    }
#endif
    service(0);
    CHECK(host_in(1) && host.nbytes[1] == sizeof marker && !memcmp(host.bytes[1], marker, sizeof marker));
#if T_CDC
    CHECK(host_in(3) && host.nbytes[3] == 4u && !memcmp(host.bytes[3], "NEW!", 4));
    CHECK(ci_w - ci_r == 4u);
    for (uint32_t i = 0; i < 4u; i++) CHECK(cdc_in[(ci_r + i) % CI_N] == (uint8_t)"NEW!"[i]);
#endif
    CHECK(mi_w == mi_before + 1u && midi_in_q[mi_before % MQ] == 0x5B439009u);
    CHECK(!usb.rx_pend && host_in(4));
    puts("control abort/stall, nested EP4 ownership and bus-reset/reconfigure passed");
}
/* Distinct, nonzero application data survives controller-only transitions.
 * Accepted MIDI/CDC input is not an endpoint buffer or a reset-clears-all queue. */
static const uint8_t recovery_sx[12] = {4, 0xF0, 0x7D, 1, 4, 2, 3, 4, 6, 5, 0xF7, 0};
static void seed_application(void)
{
    static const uint8_t sx[8] = {0xF0, 0x7D, 1, 2, 3, 4, 5, 0xF7};
    CHECK(midi_enqueue(0x5B439009u, 2));
    midi_out_event(0x5A409009u);
    CHECK(!ota_wire_send(sx, sizeof sx));
#if T_CDC
    cdc_in[0] = 'I'; cdc_in[1] = 'N'; ci_w = 2;
    cdc_out[0] = 'O'; cdc_out[1] = 'K'; co_w = 2;
#endif
}
static void application_pending(void)
{
    CHECK(!mi_r && mi_w == 1u && midi_in_q[0] == 0x5B439009u && midi_in_source[0] == 2u);
    CHECK(!mo_r && mo_w == 1u && midi_out_q[0] == 0x5A409009u);
    CHECK(!so_r && so_w == 3u);
    for (uint32_t i = 0; i < 3u; i++) {
        uint32_t want = 0;
        for (uint32_t j = 0; j < 4u; j++) want |= (uint32_t)recovery_sx[4u * i + j] << (8u * j);
        CHECK(sx_out_q[i] == want);
    }
#if T_CDC
    CHECK(!ci_r && ci_w == 2u && cdc_in[0] == 'I' && cdc_in[1] == 'N');
    CHECK(!co_r && co_w == 2u && cdc_out[0] == 'O' && cdc_out[1] == 'K');
#endif
}
static void application_delivered(void)
{
    CHECK(host_in(1) && host.nbytes[1] == 16u && !memcmp(host.bytes[1], recovery_sx, sizeof recovery_sx));
    CHECK(!memcmp(host.bytes[1] + 12, "\x09\x90\x40\x5A", 4));
    CHECK(so_r == so_w && mo_r == mo_w && !mi_r && mi_w == 1u && midi_in_q[0] == 0x5B439009u);
#if T_CDC
    CHECK(host_in(3) && host.nbytes[3] == 2u && !memcmp(host.bytes[3], "OK", 2));
    CHECK(co_r == co_w && !ci_r && ci_w == 2u && !memcmp(cdc_in, "IN", 2));
#endif
}
static void sie_failures(void)
{
    uint32_t before, checks, value;
    reset_model();
    usb.config = 1; seed_application(); usb.config = 0; /* accepted before the controller fault */
    host.on = 0;
    usb.timeouts = 7;
    value = sie_rd(S_POWER);
    sie_wr(S_POWER, 0x5A);
    CHECK(!value && !host.starts && !host.checks && !host.data_reads && usb.timeouts == 7u);

    host.on = 1; host.delay = 3; host.common[S_POWER] = 0xA6;
    value = sie_rd(S_POWER);
    CHECK(value == 0xA6u && host.polls == 4u && !usb.timeouts && host.data_reads == 1u);
    sie_wr(S_POWER, 0x5A);
    CHECK(host.common[S_POWER] == 0x5Au && host.polls == 4u && !usb.timeouts);
    /* Last permitted completion: one fewer failed poll than the timeout cap. */
    host.delay = 19999;
    value = sie_rd(S_POWER);
    CHECK(value == 0x5Au && host.polls == 20000u && !usb.timeouts);
    sie_wr(S_POWER, 0xA7);
    CHECK(host.common[S_POWER] == 0xA7u && host.polls == 20000u && !usb.timeouts);

    for (uint32_t write = 0; write < 2u; write++) {
        host.delay = 0; host.missing = 1; usb.up = 1; usb.timeouts = 0;
        host.common[S_INTRUSB] = 2;                    /* read-clear latch must survive a failed read */
        before = host.data_reads;
        for (uint32_t i = 1; i <= 50u; i++) {
            host.operations = 0;
            checks = host.checks;
            if (write) sie_wr(S_POWER, 0xCC);
            else { value = sie_rd(S_INTRUSB); CHECK(!value); }
            CHECK(host.polls == 20000u && host.checks - checks == 20000u);
            CHECK(usb.up && usb.timeouts == i && !host.completed);
            CHECK(host.common[S_POWER] == 0xA7u && host.common[S_INTRUSB] == 2u && host.data_reads == before);
        }
        /* A success resets CONSECUTIVE failures for both accessor paths. */
        host.missing = 0;
        if (write) sie_wr(S_POWER, 0xA7);
        else { value = sie_rd(S_POWER); CHECK(value == 0xA7u); }
        CHECK(usb.up && !usb.timeouts);
        host.missing = 1;
        for (uint32_t i = 1; i <= 51u; i++) {
            host.operations = 0;
            if (write) sie_wr(S_POWER, 0xCC);
            else { value = sie_rd(S_INTRUSB); CHECK(!value); }
            CHECK(usb.timeouts == i && usb.up == (i <= 50u));
        }
        before = host.starts; checks = host.checks;
        usb.config = 1; uac.alt = 1;                   /* both service guards must suppress real pending work */
        service(0); service(1);
        CHECK(host.starts == before && host.checks == checks && !host.operations);
        usb.config = 0; uac.alt = 0;
        application_pending();
    }
    puts("SIE: delayed/bounded completion, no stale reads, consecutive failures and poll shutoff passed");
}
static void retry_lifecycle(void)
{
    uint32_t before;
    /* Called only once: usb_retry's function-local last-attempt time starts at zero. */
    reset_model();
    usb.config = 1; seed_application(); usb.config = 0;
    usb.up = 0; host.missing = 1;
    usb_start();
    CHECK(!usb.up && usb.timeouts == 6u && host.resets == 1u && host.attaches == 1u);
    CHECK(host.delay_calls == 1u && host.delay_ms == 25u && host.enabled == 0x1Fu && host.rx[0] == ep0buf);
    application_pending();
    usb_retry(999u); CHECK(!usb.retries && host.resets == 1u);
    usb_retry(1000u); CHECK(usb.retries == 1u && host.resets == 2u && !usb.up);
    usb_retry(1000u); usb_retry(1999u); CHECK(usb.retries == 1u && host.resets == 2u);
    usb_retry(2000u); CHECK(usb.retries == 2u && host.resets == 3u && !usb.up);
    host.missing = 0; host.delay = 2;
    usb_retry(2999u); CHECK(usb.retries == 2u && !usb.up);
    usb_retry(3000u); CHECK(usb.retries == 3u && host.resets == 4u && usb.up && !usb.timeouts);
    CHECK(host.common[S_POWER] == 0x60u && host.common[S_INTRUSBE] == 7u && host.common[S_INTRTX1E] == 1u);
    CHECK(!host.common[S_INTRTX2E] && !host.common[S_INTRRX1E] && !host.common[S_INTRRX2E]);
    before = host.starts;
    usb_retry(4000u); CHECK(usb.retries == 3u && host.starts == before);
    application_pending();

    usb.up = 0; host.missing = 1;
    usb_retry(UINT32_MAX - 499u);
    CHECK(usb.retries == 4u && host.resets == 5u && !usb.up);
    usb_retry(499u); CHECK(usb.retries == 4u && host.resets == 5u); /* 999 ms across wrap */
    host.missing = 0;
    usb_retry(500u); CHECK(usb.retries == 5u && host.resets == 6u && usb.up); /* exactly 1000 */
    CHECK(host.delay_calls == 6u && host.delay_ms == 150u);
    application_pending();
    configure(44100u);
    CHECK(usb.config == 1u && host.rx[1] == ep1rx && host.tx[1] == ep1tx && host.tx[4] == ep4tx);
    application_delivered();
    usb_detach(); CHECK(!usb.up && usb.detached && !host.on && host.offs == 1u);
    before = host.starts;
    usb_retry(1500u); usb_retry(UINT32_MAX);
    CHECK(usb.retries == 5u && host.resets == 6u && host.starts == before && host.offs == 1u);
    CHECK(!mi_r && mi_w == 1u && mo_r == mo_w && so_r == so_w);
    puts("USB lifecycle: actual startup, failed/healthy retry, interval/wrap and intentional detach passed");
}
/* A local SIE reset is not a host bus-reset event. Restart from a genuinely
 * configured session; unlike retry_lifecycle, do not force config=0 in the fixture. */
static void configured_retry(uint32_t hz)
{
    static uint32_t retry_at = 1500u;               /* prior lifecycle's final attempt was at 500 */
    static const uint8_t complete[] = {4, 0xF0, 0x7D, 0x12, 6, 0x34, 0xF7, 0};
    static const uint8_t partial[] = {4, 0xF0, 0x7D, 0x56};
    uint32_t source_frame, before[5], rate_sets, retry_count;
    const uint8_t *frame;
    uint32_t frame_len;
    /* Rate data, descriptor continuation and pending address are independent
     * EP0 owners. CDC adds its own line-coding data stage. */
    for (uint32_t stage = 0; stage < 3u + T_CDC; stage++) {
        reset_fixture(hz);
        source_frame = 0;
        CHECK(host_in(4)); service(0); CHECK(host_in(4)); render(&source_frame); service(0);
        CHECK(uac.alt && uac.go && uac.flowing);
        if (!stage) {
            host_out(1, complete, sizeof complete); service(0);
            CHECK(ota_frame_get(&frame, &frame_len) && frame_len == 3u && !memcmp(frame, "\x7D\x12\x34", 3));
        }
        host_out(1, partial, sizeof partial); service(0);
        CHECK(usb.sx_on && (stage ? sx_collect : sx_ready));
        if (!stage) {
            setup(0x2201, 0x0100, 0x84, 3); CHECK(uac.e0_rx);
        } else if (stage == 1u) {
            setup(0x8006, 0x0200, 0, 0xFFFF); CHECK(usb.e0_tx);
        } else if (stage == 2u) {
            setup(0x0005, 37, 0, 0); CHECK(usb.has_pend_addr);
#if T_CDC
        } else {
            setup(0x2120, 0, CDC_IF_CDC, 7); CHECK(cdc.e0_rx);
#endif
        }
        seed_application();                       /* accepted queues; no poll may drain them before failure */
        rate_sets = uac.rate_sets; retry_count = usb.retries;
        host.missing = 1;
        for (uint32_t i = 0; i < 51u; i++) {
            host.operations = 0;
            (void)sie_rd(S_POWER);
        }
        CHECK(!usb.up && usb.config == 1u && usb.timeouts == 51u);
        host.missing = 0;
        usb_retry(retry_at); retry_at += 1000u;
        CHECK(usb.up && !usb.timeouts && usb.retries == retry_count + 1u && host.resets == 1u);
        for (uint32_t ep = 0; ep < 5u; ep++) before[ep] = host.sends[ep];
        service(0); service(1);
        /* No host bus reset or SET_CONFIGURATION has happened since local
         * restart. Stale bulk/audio state must not consume accepted queues. */
        if (usb.config)
            fprintf(stderr, "configured retry CDC%u %uHz stage%u: config=%u sends1=%u sends4=%u mo=%u/%u so=%u/%u\n",
                    T_CDC, hz, stage, usb.config, host.sends[1] - before[1], host.sends[4] - before[4],
                    mo_r, mo_w, so_r, so_w);
        CHECK(host.sends[1] == before[1] && host.sends[4] == before[4]);
#if T_CDC
        CHECK(host.sends[3] == before[3] && !cdc.dtr && !cdc.e0_rx && !cdc.rx_pend);
#endif
        CHECK(!usb.config && !usb.e0_tx && !usb.has_pend_addr && !usb.rx_pend && !usb.sx_on && !sx_collect);
        CHECK(!uac.alt && !uac.go && !uac.r48 && !uac.e0_rx && !uac.queued && !uac.flowing);
        application_pending();
        if (!stage) CHECK(ota_frame_get(&frame, &frame_len) && frame_len == 3u && !memcmp(frame, "\x7D\x12\x34", 3));
        else CHECK(!sx_ready);
        /* The first new SETUP must not become old rate/line data or continue
         * an abandoned descriptor. Nor may an old SET_ADDRESS be applied. */
        setup(0x8006, 0x0100, 0, 18);
        CHECK(host_in(0) && host.lengths[0][host.npackets[0] - 1u] == 18u);
        CHECK(!memcmp(host.bytes[0] + host.nbytes[0] - 18u, DEV_DESC, 18));
        CHECK(!host.common[S_FADDR] && uac.rate_sets == rate_sets);
        configure(hz);
        CHECK(usb.config == 1u && host.rx[1] == ep1rx && host.tx[1] == ep1tx && host.tx[4] == ep4tx);
        application_delivered();
        CHECK(host_in(4)); service(0); render(&source_frame); service(0);
        CHECK(uac.go && uac.ring48 == (hz == 48000u) && !uac.underruns && !uac.overruns && !uac.missed);
        if (!stage) ota_frame_done();
    }
    puts("configured SIE restart: queues/frames preserved, stale control/audio state aborted and fresh configuration rearmed");
}

static void frame_progress(uint32_t frame)
{
    uint32_t polls = 0;
    CHECK(frame != usb.frame);
    host.frame = frame;
    do { service(0); CHECK(++polls <= 20u); } while (usb.frame != frame);
    CHECK(!usb.suspended && !usb.frame_same);
}
static void suspend_lifecycle(uint32_t hz)
{
    uint32_t base_resets, before;
    reset_fixture(hz); seed_application();
    /* Hold existing IN slots busy; suspend/resume must not discard the pending
     * application messages. No host-completion token is fabricated here. */
    host.ep[1][S_TXCSR1] |= 1u;
#if T_CDC
    host.ep[3][S_TXCSR1] |= 1u;
#endif
    base_resets = usb.resets;
    host.common[S_INTRUSB] = 1;
    service(0); CHECK(usb.suspends == 1u && usb.suspended && usb.config == 1u);
    host.common[S_INTRUSB] = 2;
    service(0); CHECK(usb.suspends == 1u && !usb.suspended && usb.config == 1u);
    application_pending();

    host.sof_each_poll = 0;
    for (uint32_t i = 0; i < 5u; i++) service(0);
    CHECK(usb.no_sof == 5u && usb.max_gap == 5u);
    host.sof_each_poll = 1;
    service(0); CHECK(!usb.no_sof && usb.max_gap == 5u);
    frame_progress(77u);                     /* align the actual function-local 20-poll divider */
    before = usb.frame_stalls;
    for (uint32_t i = 0; i < 199u; i++) service(0);
    CHECK(!usb.suspended && usb.frame_same == 9u && usb.frame_stalls == before);
    service(0);
    CHECK(usb.suspended && usb.frame_same == 10u && usb.frame_stalls == before + 1u);
    for (uint32_t i = 0; i < 200u; i++) service(0);
    CHECK(usb.suspended && usb.frame_stalls == before + 1u && !usb.no_sof);
    frame_progress(78u);
    CHECK(usb.frame_stalls == before + 1u);
    for (uint32_t i = 0; i < 200u; i++) service(0);
    CHECK(usb.suspended && usb.frame_stalls == before + 2u);
    frame_progress(79u);
    CHECK(usb.frame_stalls == before + 2u && usb.resets == base_resets && usb.config == 1u && !usb.retries);
    application_pending();

    host.ep[1][S_TXCSR1] &= (uint8_t)~1u;
#if T_CDC
    host.ep[3][S_TXCSR1] &= (uint8_t)~1u;
#endif
    service(0);
    application_delivered();
    puts("suspend/resume, missing SOF, repeated frame-freeze episodes and pending application data passed");
}
#if FELUCCA_RESTART
static void control_fences(void)
{
    const uint8_t ack[] = {0xF0, 0x7D, 0x46, 0x4C, 84, 1, 0, 1, 0, 0, 0, 0, 7, 0, 0, 0, 0, 0xF7};
    uint32_t end, epoch;
    reset_fixture(44100u);
    CHECK(!ota_wire_control(ack, sizeof ack, &end, &epoch));
    CHECK(so_done != end);
    service(0);
    CHECK(so_r == so_w && so_flight && so_done != end && so_epoch == epoch);
    service(0);
    CHECK(so_done != end);                    /* DMA pending, no host IN token */
    CHECK(host_in(1));
    CHECK(so_done != end);                    /* only TIMER5 publishes a completed fence */
    service(0);
    CHECK(so_done == end && !so_flight && so_epoch == epoch);
    CHECK(!ota_wire_control(ack, sizeof ack, &end, &epoch));
    service(0);
    host.missing = 1; host.operations = 0;
    ep1_tx();
    CHECK(so_epoch != epoch && so_done != end && !so_flight);
    reset_fixture(44100u);
    CHECK(!ota_wire_control(ack, sizeof ack, &end, &epoch)); service(0);
    CHECK(host_in(1));
    host.missing = 1; host.operations = 0;
    (void)sie_rd(S_INTRUSB);                /* unrelated poll failure before a successful EP1 call */
    CHECK(so_epoch != epoch && !so_flight);
    host.missing = 0; host.operations = 0; ep1_tx();
    CHECK(so_done != end);                  /* the later successful CSR read must not resurrect it */
    reset_fixture(44100u);
    CHECK(!ota_wire_control(ack, sizeof ack, &end, &epoch));
    service(0);
    setup(0x0201, 0, 0x81, 0);              /* CLEAR_FEATURE cannot fabricate completion */
    CHECK(so_epoch != epoch && !so_flight && so_done != end);
    reset_fixture(44100u);
    CHECK(!ota_wire_control(ack, sizeof ack, &end, &epoch));
    service(0);
    host.common[S_INTRUSB] = 4;
    service(0);
    CHECK(so_epoch != epoch && !so_flight && so_done != end);
    reset_fixture(44100u);
    so_r = so_w = UINT32_MAX - 2u; so_done = so_r;
    CHECK(!ota_wire_control(ack, sizeof ack, &end, &epoch));
    CHECK(end < 64u);
    service(0); CHECK(so_done != end && host_in(1)); service(0);
    CHECK(so_done == end && so_epoch == epoch);
    reset_fixture(44100u);
    so_w = so_r + SXQ;
    CHECK(ota_wire_control(ack, sizeof ack, &end, &epoch) == -1 && so_w - so_r == SXQ);
    puts("control fences: real EP1 completion, fault/reset/halt cancellation, wrap and atomic-full passed");
}
#endif
int main(void)
{
#if FELUCCA_RESTART
    control_fences();
#endif
    sie_failures(); retry_lifecycle();
    for (uint32_t hz = 44100u; hz <= 48000u; hz += 3900u) {
        composite(hz, 0); composite(hz, 1); stream_transitions(hz); control_recovery(hz);
        suspend_lifecycle(hz); configured_retry(hz);
    }
    puts("USB service model: all finite contracts passed (no physical timing claim)");
    return 0;
}
