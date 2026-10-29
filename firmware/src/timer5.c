/* SPDX-License-Identifier: GPL-3.0-only
 * TRS scheduling adapted from fgunited/Felucca-PR f3290a7 (upstream #258).
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* TIMER5 outranks ALNK0, so the scan keeps its 100 us pace while a half buffer renders: before,
 * the ticks stopped for the whole render (0.7 ms idle, several ms loaded), the column lit when it
 * began stayed lit that long (a ~16 Hz flicker over all LEDs, beating with the scan) and the
 * encoders lost frames. Nested in ALNK0 it scans GPIO, counts ms and publishes TRS packets into the MIDI ring.
 * TIMER5 remains the sole producer; ALNK0 consumes packets and changes sound/sequencer state.
 * USB MIDI stays deferred. Polling TRS at 2 kHz avoids render-dependent clock timestamps;
 * nested work is subtracted from the render-only load figures.
 * The USB audio stream cannot wait for the render (one packet per 1 ms frame, a render takes up to
 * ~5 ms): uac_service also runs nested. It touches only EP4 (INDEX is set on every access) and the
 * consumer side of the audio ring, and usb_poll never runs nested. The USB reset cleanup (usb_reset_state,
 * which also runs from the main loop via usb_start) can be preempted by ALNK0, so it does interleave with
 * the audio ISR: usb.config = 0 is published before the rest of the state is cleared. */
void fm1_timer5_irq(void)
{
    static uint32_t sub, owed;
    uint32_t t0 = fm1_ticks(), usb_due = sub % 5u == 0u;
    FM1_ISR_SIM_ENTER();                        /* host: simulated interrupt context (isr_assert.h) */
    fm1_timer5_ack();
    felucca_dbg.timer_irqs++;
    fm1_input_tick();
    {   /* milliseconds from the 24 MHz TIMER4 (robust to a late tick) */
        static uint32_t last, acc;
        acc += t0 - last;
        last = t0;
        while (acc >= 1000u * FM1_TICKS_PER_US) {
            acc -= 1000u * FM1_TICKS_PER_US;
            fm1_ms++;
        }
    }
    if (usb_due)
        owed |= 1u;                             /* 2 kHz: all USB SIE traffic lives here */
#if FELUCCA_UART
    if (sub % 5u == 2u)
        uart_midi_poll();                       /* 2 kHz, nested too: at most 2 new wire bytes per poll */
#endif
    if (++sub == 10u)
        sub = 0;
    if (felucca_dbg.in_audio) {
        felucca_dbg.nested++;
#if FELUCCA_UAC
        if (usb_due)
            uac_service();
#endif
        t5_nested_ticks += fm1_ticks() - t0;
        FM1_ISR_SIM_LEAVE();
        return;
    }
    if (owed & 1u)
        usb_poll();
    owed = 0;
    FM1_ISR_SIM_LEAVE();
}
