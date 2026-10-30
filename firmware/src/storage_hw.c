/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
#include "isr_assert.h"                    /* FM1_ASSERT_THREAD / FM1_ISR_SIM_* (#428) */
/* The firmware side of storage.c (FELUCCA_FLASH): flash reads in short IRQ-off windows so the
 * audio keeps up, erases and writes only inside the storage areas, the audio buffer silenced
 * first. The host tests (storage_test.c) provide their own st_* on a simulated NOR. */
static uint8_t flash_ok;                 /* JEDEC id matched at boot (persist_boot) */
static int st_raw_read(uint32_t off, void *dst, uint32_t n)   /* 256-byte IRQ-off windows: audio keeps up */
{
    uint8_t *d = dst;
    while (n) {
        uint32_t k = n > 256u ? 256u : n, f = irq_save();
        int rc = FL_FAR(fl_read_ram)(off, d, k);
        irq_restore(f);
        if (rc)
            return rc;
        off += k;
        d += k;
        n -= k;
    }
    return 0;
}
#if BOARD_SMK37
static uint8_t st_owner_ready;
static int st_owner_read(uint32_t off, void *dst, uint32_t n) { return st_raw_read(off, dst, n); }
static int st_owner_prog(uint32_t off, const void *src, uint32_t n)
{
    if (off != 0xAF000u || n != 16u) return -8;
    return fl_write(off, src, n);
}
#endif
static int st_read(uint32_t off, void *dst, uint32_t n)
{
#if BOARD_SMK37
    if (!st_owner_ready) return -8;
#endif
    return st_raw_read(off, dst, n);
}
static void audio_silence(void)                 /* IRQs off: the DMA would loop stale audio (buzz) */
{
    uint32_t i;
    for (i = 0; i < sizeof abuf / sizeof abuf[0]; i++)
        abuf[i] = 0;
}
#if BOARD_SMK37
static int st_owner_erase(uint32_t off)
{
    uint32_t took, f; int rc;
    FM1_ASSERT_THREAD();
    if (!flash_ok || !FL_IN(off, 0x1000u, FL_DATA_LO, FL_OTA_HI) || (off & 0xFFFu)) return -8;
    f = irq_save(); audio_silence();
    rc = FL_FAR(fl_erase4k_ram)(off, &took);
    irq_restore(f);
    return rc;
}
#endif
#if BOARD_SMK37
/* Require verified removal of the stock mapping marker before sample mutations. */
static int st_marker_blank(void)
{
    uint8_t b[64]; uint32_t a, i;
    for (a = FL_STOCKTAG_LO; a < FL_STOCKTAG_HI; a += sizeof b) {
        if (st_raw_read(a, b, sizeof b)) return -1;
        for (i = 0; i < sizeof b; i++) if (b[i] != 0xFFu) return 0;
    }
    return 1;
}
#endif
static int st_erase(uint32_t off)
{
    uint32_t took, f;
    int rc;
    FM1_ASSERT_THREAD();                        /* (#428) before irq_save: an erase stops audio and scan */
#if BOARD_SMK37
    if (!st_owner_ready) return -8;
    if (FL_IN(off, 0x1000u, FL_SMP_LO, FL_SMP_HI)) {
        int marker = st_marker_blank();
        if (marker < 0) return -8;
        if (!marker) {
        f = irq_save(); audio_silence();
        rc = FL_FAR(fl_erase4k_ram)(FL_STOCKTAG_LO, &took);
        irq_restore(f);
        if (rc) return rc;
        if (st_marker_blank() != 1) return -8;
        }
    }
#endif
    if (!FL_STORE_OK(off, 0x1000u))
        return -8;
    f = irq_save();
    audio_silence();
#if !BOARD_SMK37
    fm1__led_lines(0);                          /* (#236) the erase stops the LED scan for ~17 ms (the IRQs are off and its code */
#endif
    rc = FL_FAR(fl_erase4k_ram)(off, &took);    /* is in the flash): one column would stay lit at full duty and the rest dark, a */
    irq_restore(f);                             /* flash of the whole panel. Dark rows: the panel just drops out; the tick lights */
    return rc;                                  /* the rows again at its next pass */
}
static int st_prog(uint32_t off, const void *src, uint32_t n)
{
    FM1_ASSERT_THREAD();                        /* (#428) */
#if BOARD_SMK37
    if (!st_owner_ready) return -8;
    if (FL_IN(off, n, FL_SMP_LO, FL_SMP_HI) && st_marker_blank() != 1) return -8;
#endif
    if (!FL_STORE_OK(off, n))                   /* only inside the storage areas */
        return -8;
    return fl_write(off, src, n);
}
