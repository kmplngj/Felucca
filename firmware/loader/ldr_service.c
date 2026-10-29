/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Shared by the loader and its production-source display/service fixture. */
static uint32_t ldr_ms(void)   /* monotonic ms; survives the TIMER4 wrap (178.9 s) */
{
    static uint32_t last, acc, ms;
    uint32_t now = fm1_ticks();
    acc += now - last;
    last = now;
    ms += acc / (1000u * FM1_TICKS_PER_US);
    acc %= 1000u * FM1_TICKS_PER_US;
    return ms;
}

static uint8_t ldr_usb_started;

/* usb_poll only services endpoints/framing. ota_service and ldr_session stay
 * in the outer loop: display waits must never re-enter package/flash work. */
static void ldr_poll(void)                          /* USB at ~2 kHz, watchdog */
{
    static uint32_t last;
    uint32_t now = fm1_ticks();
    fm1_wdt_feed();
    if (now - last >= 500u * FM1_TICKS_PER_US) {
        last = now;
        if (ldr_usb_started)
            usb_poll();
    }
}

