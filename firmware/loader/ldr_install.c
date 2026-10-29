/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Native successful-session restart sequence, shared with the host fixture.
 * A failed attempt returns directly to the loader's handshake/retry loop. */
static void ldr_install(void)
{
    if (ldr_session() == 0) {
#if FELUCCA_LDR_LCD_TRACE
        ldr_trace_read_window();
#endif
        fm1_delay_ms(200);                          /* the "success" reply leaves */
        usb_detach();
        fm1_delay_ms(30);
        fm1_core_reset();                          /* the SPL boots the verified app */
    }
}
