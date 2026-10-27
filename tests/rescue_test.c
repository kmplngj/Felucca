/* SPDX-License-Identifier: GPL-3.0-only */
/* Real rescue loop, OTA protocol and hardware adapter against fake HAL/USB.
 * No normal settings, project, audio or CPU1 initialization exists in this harness. */
#include <stdint.h>
#include "../firmware/hal/fm1_lcd_contract.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define __attribute__(x)   /* (the sources' .pool sections: no Mach-O section names, as in ota_test.c) */
#include "../firmware/src/boot_policy.h"
#define FELUCCA_OTA 1
#define FELUCCA_ID "FM-1_900"
#define FELUCCA_OTA_DRYRUN 0
#define FM1_TICKS_PER_US 24u
#define FL_FAR(fn) fn
#define FL_IN(off,n,lo,hi) ((off) >= (lo) && (off) <= (hi) && (n) <= (hi)-(off))
#define T_BG 1
#define T_TEXT 2
#define T_THEME 3
static const int AF_M, AF_S;
static uint8_t nor[0x100000], frame[640], *package;
static uint32_t package_len, frame_len, frame_ready, ticks, tick_step = 12000u;
static uint32_t poll_calls, input_calls, feeds, screens, writes, erases, audio_calls, wrapper_calls;
static uint32_t chip = 0x856014u, fail_erase, fail_prog, host_silent, requests, identities, rom, commits;
static uint32_t physical_buttons;
static volatile uint32_t fm1_ms;
static uint8_t usb_rescue_mode, flash_ok;
static struct { uint8_t up, detached, ota_req, uboot_req; } usb;
static struct { uint32_t buttons; } fm1_in;
static boot_policy_guard_t bootguard;
static uint32_t fm1_ticks(void) { ticks += tick_step; return ticks; }
static void fm1_wdt_feed(void) { feeds++; }
static void fm1_delay_ms(uint32_t ms) { ticks += ms * 24000u; }
static void fm1_panel_power_on(void) {}
static void fm1_input_init(void) { fm1_in.buttons = 0; }
static void fm1_input_tick(void) { input_calls++; fm1_in.buttons = physical_buttons; }
static void usb_poll(void) { poll_calls++; }
static void usb_start(void) { usb.up = 1; fm1_delay_ms(25); }
static void usb_retry(uint32_t now) { if (!usb.up && !usb.detached && now >= 1000u) usb_start(); }
static void usb_detach(void) { usb.up = 0; usb.detached = 1; }
static void fm1_enter_uboot(void) { rom++; }
static void fm1_enter_update(const uint8_t *p) { (void)p; commits++; }
static void lcd_init(void) { screens++; }
static lcd_fill_fn lcd_fill;
static void lcd_fill(uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint16_t c)
{ (void)x; (void)y; (void)w; (void)h; (void)c; }
static void draw_text_box(uint32_t x, uint32_t y, uint32_t w, const int *font, const char *s, uint32_t c, int a)
{ (void)x; (void)y; (void)w; (void)font; (void)s; (void)c; (void)a; }
static void str_cpy(char *dst, const char *src, uint32_t n) { snprintf(dst, n, "%s", src); }
static uint32_t fl_jedec_ram(void) { return chip; }
static int fl_erase4k_ram(uint32_t off, uint32_t *took)
{
    erases++; *took = 17000u; ticks += 17000u * 24u;
    if (fail_erase) return -1;
    memset(nor + off, 255, 4096); return 0;
}
static int fl_prog_ram(uint32_t off, const void *p, uint32_t n, uint32_t *took)
{
    const uint8_t *src = p;
    uint32_t i;
    writes++; *took = 500u; ticks += 500u * 24u;
    if (fail_prog) return -1;
    for (i = 0; i < n; i++) nor[off + i] &= src[i];
    return 0;
}
static int fl_read_ram(uint32_t off, void *p, uint32_t n) { memcpy(p, nor + off, n); return 0; }
/* Normal wrappers must never run before TIMER5/audio startup. */
static void audio_silence(void) { audio_calls++; }
static int fl_erase4k(uint32_t off, uint32_t *took) { wrapper_calls++; return fl_erase4k_ram(off,took); }
static int fl_write(uint32_t off, const void *p, uint32_t n) { uint32_t t; wrapper_calls++; return fl_prog_ram(off,p,n,&t); }
static int st_read(uint32_t off, void *p, uint32_t n) { wrapper_calls++; return fl_read_ram(off,p,n); }
static int ota_frame_get(const uint8_t **p, uint32_t *n)
{ if (!frame_ready) return 0; *p = frame; *n = frame_len; return 1; }
static void ota_frame_done(void) { frame_ready = 0; }
static int ota_wire_send(const uint8_t *p, uint32_t n);
#include "../firmware/src/ota.c"
#include "../firmware/src/ota_hw.c"
#include "../firmware/src/rescue.c"

/* Fake installer consumes real device messages and supplies real pack7 frames. */
static int ota_wire_send(const uint8_t *p, uint32_t n)
{
    uint8_t msg[600], decoded[64];
    uint32_t d = ota_unpack7(p + 1, n - 2, decoded, sizeof decoded), addr, len, i, sum = 0;
    if (d >= 7 && decoded[2] == 0x11) {
        if (!memcmp(decoded + 6, FELUCCA_ID, sizeof FELUCCA_ID - 1)) identities++;
        return 0;
    }
    requests++;
    if (host_silent) return 0;
    if (d != 15 || decoded[2] != 0x30) abort();
    addr = ota_rd32(decoded + 7); len = ota_rd24(decoded + 11);
    memset(msg, 0, sizeof msg); msg[1] = 0x59; msg[2] = 0x30;
    ota_wr16(msg + 3, len + 8); ota_wr32(msg + 7, addr); ota_wr32(msg + 11, len);
    if (addr == 0xE0000000u) memcpy(msg + 14, "success", 8);
    else {
        if (addr > package_len || len > package_len - addr) abort();
        memcpy(msg + 14, package + addr, len);
    }
    for (i = 6; i < 14u + len; i++) sum += msg[i];
    msg[14 + len] = (uint8_t)~sum;
    frame_len = ota_pack7(msg, len + 15, frame); frame_ready = 1;
    return 0;
}
static int fails;
#define CHECK(label, expr) do { int ok = !!(expr); printf("%-66s %s\n", label, ok ? "ok" : "FAIL"); fails += !ok; } while (0)
static void reset(void)
{
    memset(nor,255,sizeof nor); memset(&usb,0,sizeof usb);
    ticks = 0; fm1_ms = 0; erases = writes = commits = requests = identities = 0;
    fail_prog = fail_erase = host_silent = frame_ready = 0;
    audio_calls = wrapper_calls = 0; chip = 0x856014u;
    bootguard.magic = BOOTGUARD_MAGIC; bootguard.pending = BOOT_POLICY_RESCUING;
    bootguard.failed = 2;
    rescue_init();
}
int main(int argc, char **argv)
{
    uint32_t i, before, elapsed;
    if (argc != 2) return 2;
    {
        FILE *f = fopen(argv[1],"rb"); long size; uint8_t *raw;
        if (!f) return 2;
        fseek(f,0,SEEK_END); size=ftell(f); rewind(f);
        if (size < 1024) return 2;
        raw=malloc((size_t)size); package=malloc((size_t)size);
        if (!raw || !package || fread(raw,1,(size_t)size,f) != (size_t)size) return 2;
        fclose(f);
        for (i=0;i<20;i++) memcpy(package+i*47u,raw+i*48u,47);
        memcpy(package+940,raw+960,(size_t)size-960);
        package_len=(uint32_t)size-20; free(raw);
    }
    physical_buttons = 1;
    CHECK("manual decision reads physical OCT- before normal startup", rescue_boot_buttons() == 1);
    physical_buttons = 3;
    CHECK("physical both-OCT remains available to calibration", rescue_boot_buttons() == 3);
    reset();
    for (i=0;i<20000;i++) rescue_step();
    CHECK("rescue idle performs no erase/program/normal audio wrappers", !erases && !writes && !audio_calls && !wrapper_calls);
    CHECK("rescue feeds watchdog, scans input and polls USB", feeds && input_calls && poll_calls && usb_rescue_mode);
    CHECK("idle never disarms the retained rescue marker", bootguard.pending == BOOT_POLICY_RESCUING);
    ticks=UINT32_MAX-6000u; rescue_last=ticks; rescue_frac=0; before=fm1_ms;
    for (i=0;i<360000;i++) rescue_poll();
    elapsed=fm1_ms-before;
    CHECK("TIMER4 wrap and >178-second uptime retain monotonic milliseconds", elapsed == 180000u);
    usb.up=0; rescue_wait(1001);
    CHECK("late cable/controller retry remains usable after TIMER4 wrap", usb.up && fm1_ms-before >= 181001u);
    ota_reply_identity();
    CHECK("rescue reports real APPLICATION identity (installer must stage)", identities == 1);
    reset(); chip=0x123456u; rescue_init(); usb.ota_req=1; rescue_step();
    CHECK("unknown JEDEC refuses OTA request without flash mutation", !flash_ok && !requests && !writes && !erases);
    CHECK("all OTA hardware write hooks reject unknown JEDEC", ota_erase(OTA_AREA) == -8 && ota_prog(OTA_AREA,"x",1) == -8);
    reset(); host_silent=1; usb.ota_req=1; rescue_step();
    CHECK("aborted initial OTA waits on real rescue clock, no writes", requests && !erases && !writes && fm1_ms >= 15000u);
    CHECK("failed OTA returns to armed, responsive rescue", bootguard.pending == BOOT_POLICY_RESCUING && usb.up && !usb.ota_req);
    host_silent=0; before=poll_calls; rescue_step(); ota_reply_identity();
    CHECK("identity and USB still work after failed staging", identities == 1 && poll_calls > before);
    reset(); fail_erase=1; usb.ota_req=1; rescue_step();
    CHECK("actual OTA staging erase failure stays rescue, never commits", erases && !commits && bootguard.pending == BOOT_POLICY_RESCUING && !audio_calls && !wrapper_calls);
    reset(); fail_prog=1; usb.ota_req=1; rescue_step();
    CHECK("actual OTA staging program failure stays rescue, never commits", writes && !commits && bootguard.pending == BOOT_POLICY_RESCUING && !audio_calls && !wrapper_calls);
    reset(); usb.ota_req=1; rescue_step();
    CHECK("real package stages and deliberate commit clears boot escalation", commits == 1 && erases && writes && !bootguard.pending && !bootguard.failed);
    CHECK("rescue staging uses only polled HAL flash calls, never audio", !audio_calls && !wrapper_calls);
    reset(); usb.uboot_req=1; rescue_step();
    CHECK("explicit ROM request clears bootguard without any flash write", rom == 1 && !bootguard.pending && !writes && !erases);
    free(package);
    return fails != 0;
}
