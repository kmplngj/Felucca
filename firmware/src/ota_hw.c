/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* The firmware side of ota.c (FELUCCA_OTA): clock and watchdog, erases and writes only inside the
 * OTA area, the progress screen, the commit (record into RAM, core reset). The host test
 * (ota_test.c) provides its own. */
static void rescue_poll(void);
static void rescue_wait(uint32_t ms);
static uint32_t ota_now_ms(void)
{
    if (usb_rescue_mode)
        rescue_poll();
    return fm1_ms;
}
static void ota_idle(void)
{
    if (usb_rescue_mode)
        rescue_poll();
    else
        fm1_wdt_feed();
}
static int ota_in_area(uint32_t off, uint32_t n) { return FL_IN(off, n, OTA_AREA, OTA_AREA + OTA_AREA_LEN); }
static int ota_erase(uint32_t off)
{
    uint32_t took;
    if (!flash_ok || !ota_in_area(off, 0x1000u) || (off & 0xFFFu))
        return -8;
    if (usb_rescue_mode) {
        int rc = FL_FAR(fl_erase4k_ram)(off, &took);
        rescue_poll();
        return rc;
    }
    audio_silence();
    return fl_erase4k(off, &took);
}
static int ota_prog(uint32_t off, const void *p, uint32_t n)
{
    if (!flash_ok || !ota_in_area(off, n))
        return -8;
    if (usb_rescue_mode) {
        const uint8_t *src = p;
        while (n) {
            uint32_t took, k = 256u - (off & 255u);
            int rc;
            if (k > n)
                k = n;
            rc = FL_FAR(fl_prog_ram)(off, src, k, &took);
            rescue_poll();
            if (rc)
                return rc;
            off += k;
            src += k;
            n -= k;
        }
        return 0;
    }
    return fl_write(off, p, n);
}
static int ota_fread(uint32_t off, void *p, uint32_t n)
{
    if (!flash_ok)
        return -8;
    if (usb_rescue_mode) {
        int rc = FL_FAR(fl_read_ram)(off, p, n);
        rescue_poll();
        return rc;
    }
#if BOARD_SMK37
    return st_raw_read(off, p, n);              /* updater remains available while the store is locked */
#else
    return st_read(off, p, n);
#endif
}
static void ota_show(uint32_t step, int32_t code)
{
    static const char *const STEP[] = {"", "PACKAGE", "CHECK HEAD", "LOADER", "CONFIRM", "RESTART"};
    char b[24];
    lcd_fill(0, 0, 240, 240, usb_rescue_mode ? 0 : T_BG);
    draw_text_box(0, 92, 240, &AF_M, "UPDATE", usb_rescue_mode ? 0xFFFFu : T_TEXT, 1);
    if (step < 9u) {
        draw_text_box(0, 124, 240, &AF_S, STEP[step < 6u ? step : 0], usb_rescue_mode ? 0x07FFu : T_THEME, 1);
        return;
    }
    if (code == 1)
        str_cpy(b, "DRY RUN OK", sizeof b);
    else {
        uint32_t k = 0, v = (uint32_t)-code;
        str_cpy(b, "FAILED  -", sizeof b);
        while (b[k])
            k++;
        if (v >= 10u)
            b[k++] = (char)('0' + v / 10u);
        b[k++] = (char)('0' + v % 10u);
        b[k] = 0;
    }
    draw_text_box(0, 124, 240, &AF_S, b, usb_rescue_mode ? 0x07FFu : T_THEME, 1);
    if (usb_rescue_mode)
        rescue_wait(1500);
    else
        fm1_delay_ms(1500);
}
static void ota_commit(const uint8_t *parm)
{
    boot_policy_intentional(&bootguard);                 /* intentional update, including from rescue */
    usb_detach();
    if (usb_rescue_mode)
        rescue_wait(30);
    else
        fm1_delay_ms(30);
    fm1_enter_update(parm);                             /* record into RAM, core reset (fm1_sys.h) */
}
