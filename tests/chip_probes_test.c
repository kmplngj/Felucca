/* SPDX-License-Identifier: GPL-3.0-only */
/* Exercise the real bounded run and quiet guards; fake ticks are not chip timing. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define FELUCCA_CHIP_PROBES 1
#define FELUCCA_UAC 1
#define FELUCCA_CPU2 1
#define FELUCCA_OTA 1
#define FELUCCA_SCREEN_CAPTURE 1
#define FS 44100u
#define HALF_FRAMES 128u
#define NPART 4u
#define NVOICE 8u
static struct { uint8_t playing; } song;
static struct { uint32_t notes, buttons; } fm1_in;
static struct { uint32_t uboot_req; } usb;
static struct { uint8_t alt; } uac;
static struct { struct { uint8_t active; } v[NVOICE]; } trk[NPART];
static uint32_t mi_w, mi_r, sx_busy, sx_ready, sx_collect, fm1_c1_on;
static int screen_live, supported = 1;
static int scap_live(void) { return screen_live; }
static uint32_t tick, tick_step = 1, feeds, mul_calls, div_calls, bad_mul;
static uint32_t changed_at;
static uint32_t fm1_ticks(void) { tick += tick_step; return tick; }
static int fm1_probe_ready(void) { return supported; }
static void fm1_probe_barrier(void) { __asm__ volatile("" ::: "memory"); }
static uint32_t fm1_probe_mul(uint32_t a, uint32_t b) { mul_calls++; return a * b ^ bad_mul; }
static uint32_t fm1_probe_div(uint32_t a, uint32_t b) { div_calls++; if (!b) abort(); return a / b; }
static void fm1_wdt_feed(void) { if (++feeds == changed_at) song.playing = 1; }
#include "../firmware/src/chip_probes.c"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "%d: %s\n", __LINE__, #x); exit(1); } } while (0)

static void reset(void)
{
    memset(&song, 0, sizeof song); memset(&fm1_in, 0, sizeof fm1_in);
    memset(trk, 0, sizeof trk); memset(&usb, 0, sizeof usb); memset(&uac, 0, sizeof uac);
    mi_w = mi_r = sx_busy = sx_ready = sx_collect = fm1_c1_on = screen_live = 0;
    supported = 1; tick = feeds = mul_calls = div_calls = bad_mul = changed_at = 0; tick_step = 1;
}
int main(void)
{
    uint32_t i, p, v;
    reset(); CHECK(cp_run() == 0);
    CHECK(cp_done == CP_KINDS * CP_PASSES);
    CHECK(feeds == CP_KINDS * CP_PASSES);
    CHECK(mul_calls == CP_REPS * CP_PASSES && div_calls == mul_calls);
    for (i = 0; i < CP_KINDS * CP_PASSES; i++) {
        CHECK(cp_result[i].ticks == 1u);
        CHECK(cp_result[i].checksum == cp_result[i].reference);
        printf("%u %08X\n", i, cp_result[i].checksum);
    }
    /* Each refusal leaves the caller's state intact and runs no kernel. */
    reset(); song.playing = 1; CHECK(cp_run() == 2 && song.playing == 1 && !feeds);
    reset(); fm1_in.notes = 1; CHECK(cp_run() == 2 && fm1_in.notes == 1 && !feeds);
    reset(); fm1_in.buttons = 1; CHECK(cp_run() == 2 && fm1_in.buttons == 1 && !feeds);
    reset(); mi_w = 1; CHECK(cp_run() == 2 && mi_w == 1 && mi_r == 0 && !feeds);
    reset(); usb.uboot_req = 1; CHECK(cp_run() == 2 && usb.uboot_req == 1 && !feeds);
    reset(); fm1_c1_on = 1; CHECK(cp_run() == 2 && fm1_c1_on == 1 && !feeds);
    reset(); uac.alt = 1; CHECK(cp_run() == 2 && uac.alt == 1 && !feeds);
    reset(); sx_busy = 1; CHECK(cp_run() == 2 && sx_busy == 1 && !feeds);
    reset(); sx_ready = 1; CHECK(cp_run() == 2 && sx_ready == 1 && !feeds);
    reset(); sx_collect = 1; CHECK(cp_run() == 2 && sx_collect == 1 && !feeds);
    reset(); screen_live = 1; CHECK(cp_run() == 2 && screen_live == 1 && !feeds);
    for (p = 0; p < NPART; p++) for (v = 0; v < NVOICE; v++) {
        reset(); trk[p].v[v].active = 1;
        CHECK(cp_run() == 2 && trk[p].v[v].active == 1 && !feeds);
    }
    reset(); supported = 0; CHECK(cp_run() == 1 && !feeds && !cp_done);
    reset(); tick_step = CP_LIMIT; CHECK(cp_run() == 3 && !feeds && !cp_done);
    reset(); tick_step = CP_LIMIT / 5u; CHECK(cp_run() == 3 && feeds == 2 && cp_done == 2);
    reset(); tick = UINT32_MAX - 5u; CHECK(cp_run() == 0);  /* native unsigned wrap */
    reset(); changed_at = 3; CHECK(cp_run() == 2 && feeds == 3 && !mul_calls && song.playing);
    reset(); bad_mul = UINT32_MAX; CHECK(cp_run() == 4 && feeds == 5 && cp_done == 5);
    CHECK(cp_result[4].checksum != cp_result[4].reference);
    reset(); CHECK(cp_run() == 0);                  /* refusal/mismatch requires no cleanup state */
    return 0;
}
