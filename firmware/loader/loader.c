/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Felucca update loader (device side). Runs from RAM, started by the SPL from
 * an update record, with interrupts off: USB is polled from the main loop.
 * It is a USB-MIDI device "Felucca Update" (1209:0002) that answers the
 * M-UPGRADE update protocol as "ota-FM-1_900" (hosts look for "ota-"), and
 * writes the app area only (ldr_core.c). The UBOOT soft key works here too.
 * Single compilation unit. */
#include <stdint.h>
#define FELUCCA_LOADER 1
#define FELUCCA_ISR_ASSERT 0        /* no interrupt handlers here (src/isr_assert.h) */
#define FELUCCA_CDC 0
#define FELUCCA_OTA 1
#define FELUCCA_OTA_DRYRUN 0
#define FELUCCA_USB_PID 0x0002
#include "fm1_cc.h"
#if BOARD_SMK37
#define FELUCCA_ID "ota-" SMK_MODEL "_900"
#else
#define FELUCCA_ID "ota-FM-1_900"
#endif
#define RING_PUBLISH() __asm__ volatile("" ::: "memory")
#include "fm1_time.h"
#include "fm1_sys.h"
#include "fm1_lcd_hw.h"
/* the loader may write the app area and erase update records; never the head, nor Felucca's store
 * [0x97000, 0xE0000), the autosave and the FM6 voice bank [0xE5000, 0xE8000) (user data, never a record:
 * ldr_core.c). The records it clears are at 0xE4F00 (staging sector 0xE4000) and 0xE8F00 (0xE8000). */
#if BOARD_SMK37
#define FL_RANGE_OK(off, n) FL_LDR_RANGE_OK(off, n)
#else
#define FL_RANGE_OK(off, n) (FL_IN(off, n, 0x4000u, 0x97000u) || FL_IN(off, n, 0xE0000u, 0xE5000u) || \
                             FL_IN(off, n, 0xE8000u, 0xFC000u))
#endif
#include "fm1_flash.h"
#include "../src/libc.c"
#include "../src/usb.c"

#include "ldr_service.c"

#if BOARD_SMK37
/* The SMK loader keeps USB service alive with a dark screen; its panel init
 * sequence is not yet qualified for the RAM-only loader. */
static void ldr_screen_init(void) {}
static void ldr_screen_status(uint32_t state, int32_t code) { (void)state; (void)code; }
static void ldr_screen_progress(uint32_t done, uint32_t total) { (void)done; (void)total; }
#else
#include "ldr_screen.c"
#endif

/* ---- ota.c hooks (the SysEx frame hooks are in usb.c) ---- */
static uint32_t ota_now_ms(void) { return ldr_ms(); }
static void ota_idle(void) { ldr_poll(); }
/* step-1 hooks of ota.c: not used by the loader */
static int ota_erase(uint32_t off) { (void)off; return -1; }
static int ota_prog(uint32_t off, const void *p, uint32_t n) { (void)off; (void)p; (void)n; return -1; }
static int ota_fread(uint32_t off, void *p, uint32_t n) { return fl_read_ram(off, p, n); }
static void ota_show(uint32_t step, int32_t code) { (void)step; (void)code; }
static void ota_commit(const uint8_t *parm) { (void)parm; }
#include "../src/ota.c"

/* ---- ldr_core.c hooks: interrupts are off for the whole loader ---- */
static int ldr_fread(uint32_t off, void *p, uint32_t n) { return fl_read_ram(off, p, n); }
static int ldr_erase(uint32_t off)
{
    uint32_t took;
    return fl_erase4k_ram(off, &took);
}
static int ldr_prog(uint32_t off, const void *p, uint32_t n)
{
    uint32_t took;
    return fl_prog_ram(off, p, n, &took);
}
static void ldr_record_clear(void)
{
    fm1_updata_parm_clear();                        /* CRC 0: the SPL ignores it on a warm reset */
}
static void ldr_progress(uint32_t done, uint32_t total) { ldr_screen_progress(done, total); ldr_poll(); }
static void ldr_status(uint32_t state, int32_t code) { ldr_screen_status(state, code); }
#include "ldr_core.c"
#include "ldr_install.c"
#if !BOARD_SMK37
_Static_assert(LDR_AUTO_LO == FL_AUTO_LO && LDR_AUTO_HI == FL_VBANK_HI && FL_AUTO_HI == FL_VBANK_LO,
               "the loader's protected window is the autosave pair plus the voice bank");
#endif

extern uint32_t _bss_start[], _bss_end[];

void ldr_main(void)
{
    fm1_wdt_arm(0x0D);                              /* ~8 s, fed by ldr_poll */
    fm1_time_init();
    ldr_screen_init();                             /* bounded display setup before USB enumeration */
    usb_start();
    ldr_usb_started = 1;
    for (;;) {
        ldr_poll();
        usb_retry(ldr_ms());
        if (usb.uboot_req) {                        /* soft key: mask-ROM UBOOT, as in Felucca */
            usb_detach();
            fm1_delay_ms(30);
            fm1_enter_uboot();
        }
        ota_service();                              /* handshake */
        if (usb.ota_req) {
            usb.ota_req = 0;
            ldr_install();
        }
    }
}

void ldr_cstart(void)
{
    uint32_t *p;
    ldr_record_clear();                             /* first thing: a crash below cannot loop through a
                                                     * warm reset; resume after power loss uses the flash record */
    for (p = _bss_start; p < _bss_end; p++)
        *p = 0;
    ldr_main();
}
