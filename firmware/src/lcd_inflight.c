/* SPDX-License-Identifier: GPL-3.0-only */
/* Included after storage/editor and before console. LP_OWNER_READY and LP_REDRAW
 * are owner adapters, not hardware substitution. Actual LCD/GFX paths remain in use. */
#if FELUCCA_LCD_INFLIGHT
_Static_assert(sizeof cv_px == LP_BYTES, "probe uses exactly the existing RGB565 canvas");
_Static_assert(__alignof__(cv_px) >= 4u, "DMA canvas alignment");
static uint32_t lp_hash(const void *p, uint32_t n)
{
    const uint8_t *s = p;
    uint32_t h = 2166136261u;
    while (n--) h = (h ^ *s++) * 16777619u;
    return h;
}
/* Latch the first issued-config or attempted-write observation before report
 * work. Later observations cannot replace that immutable software evidence. */
static void lp_reset_latch(uint32_t cause, uint32_t t, const uint32_t raw[4], uint32_t meta)
{
    uint32_t i, issued[2];
    if (lp.reset) return;
    fm1_lcd_baud_state(issued);
    lp.reset_cause = cause; lp.reset_phase = lp.phase;
    lp.reset_ticks = t; lp.reset_ms = fm1_ms; lp.reset_meta = meta;
    lp.reset_read_mask = FM1_LCD_READ_MASK;
    lp.reset_issued_baud = issued[0]; lp.reset_baud_writes = issued[1];
    for (i = 0; i < 4u; i++) lp.reset_raw[i] = raw[i];
    lp.hold = 1u; /* also freeze a repaint if reset was requested after finish */
    __asm__ volatile("" ::: "memory");
    lp.reset = 1u;
}
static void lp_request_reset(uint32_t cause)
{
    uint32_t raw[4], t, meta;
    if (lp.reset) return;
    t = fm1_ticks();
    fm1_lcd_snapshot(raw);
    meta = lcd_busy | (uint32_t)lcd_fault << 8 | (uint32_t)lcd_initialized << 16;
    lp_reset_latch(cause, t, raw, meta);
}
/* Reuse every existing no-late-ACK/write barrier when time advances within a
 * draw/wait. A timely completed recovery is outside this short qualification
 * window; the unchanged whole-armed-lifetime TTL still applies afterward. */
static inline uint32_t lp_stopped(void)
{
    if (lp.active && !lp.reset && lp.mode == LP_RECOVERY && lp.selected &&
        lp.recovery_stage < 4u && (uint32_t)(fm1_ms - lp.go_ms) >= LP_RECOVERY_MS)
        lp_request_reset(LP_RST_RECOVERY);
    return lp.active && lp.reset;
}
static uint32_t lp_baud_allowed(uint32_t value)
{
    if (!lp.active) return 1;
    /* FINISH has released the diagnostic lease before ordinary healthy redraw.
     * It does not release the active-lifetime persistence exclusion. */
    if (!lp.reset && lp.released && !lp.hold && lp.phase == LP_REPAINT &&
        !lcd_busy && !lcd_fault && value == 4u) return 1;
    if (!lp.reset) {
        lp.reset_attempt_valid = 1u; lp.reset_attempt_baud = value;
        lp_request_reset(LP_RST_BAUD_ATTEMPT);
    }
    return 0; /* every armed attempt, including same-value4, stops before stores */
}
static void lp_record(uint32_t event, uint32_t a, uint32_t b)
{
    uint32_t i = lp.count, t = fm1_ticks(), raw[4], meta, issued[2];
    fm1_lcd_snapshot(raw);
    meta = lcd_busy | (uint32_t)lcd_fault << 8 | (uint32_t)lcd_initialized << 16;
    fm1_lcd_baud_state(issued);
    if (issued[0] != 4u || !issued[1] ||
        (lp.active && lp.phase != LP_REPAINT && issued[1] != lp.baud_epoch))
        lp_reset_latch(LP_RST_ISSUED_BAUD, t, raw, meta);
    if (i == LP_TRACE_CAP) { lp.overflow = 1; lp_reset_latch(LP_RST_TRACE, t, raw, meta); return; }
    lp.trace[i][0] = event; lp.trace[i][1] = t; lp.trace[i][2] = raw[0];
    lp.trace[i][3] = meta;
    lp.trace[i][4] = a; lp.trace[i][5] = b;
    lp.trace[i][6] = raw[1]; lp.trace[i][7] = raw[2];
    __asm__ volatile("" ::: "memory");
    lp.count = i + 1u;
}
static uint32_t lp_submit(uint32_t command, const void *source, uint32_t bytes)
{
    if (LCD_PROBE_STOPPED()) return 0;
    if (!lp.active || lp.phase == LP_C_READY || lp.phase == LP_REPAINT) return 1;
    lp.submits++;
    lp_record(LP_SUBMIT, command, bytes);
    if (lp.reset) return 0;
    (void)command; (void)source; (void)bytes;
    if (lp.selected) {
        /* Refuse register submission after observing an invalid attempt. The
         * existing source lease remains intact until ordinary full-chip reset. */
        lp_request_reset(LP_RST_SUBMIT);
    }
    return !lp.reset;
}
/* HAL calls only after its actual volatile BUF or ADR/CNT stores. This records
 * software issuance, never hardware acceptance or physical bus transactions. */
static void lp_issued(uint32_t command, const void *source, uint32_t bytes)
{
    if (LCD_PROBE_STOPPED()) return;
    if (!lp.active || lp.phase == LP_C_READY || lp.phase == LP_REPAINT) return;
    lp.issued_submits++;
    if (lp.phase == LP_SETUP && !command && source == cv_px && bytes == LP_BYTES) {
        lp.selected_submits++;
        lp.source = (uintptr_t)source; lp.programmed_bytes = bytes;
        lp.issued_seq = lp.issued_submits;
        __asm__ volatile("" ::: "memory");
        lp.selected = 1; lp.phase = LP_TRANSFER;
    } else if (lp.selected) lp_request_reset(LP_RST_SELECTION);
}
static uint32_t lp_wait_budget(void)
{
    if (!lp.short_wait) return 4000000u;
    lp.short_wait = 0;
    lp_record(LP_SHORT_WAIT, 16u, LP_BYTES);
    return 16u; /* one genuine software observation policy; hardware is untouched */
}
static void lp_wait_result(uint32_t result)
{
    if (lp.active && lp.selected && lp.phase == LP_TRANSFER) {
        lp.wait_result = result;
        lp_record(LP_WAIT_RESULT, result, 0);
    }
}
static uint32_t lp_pack_begin(uint32_t x0, uint32_t y0, uint32_t w, uint32_t h)
{
    if (!lp.active || !lp.selected || lp.phase != LP_TRANSFER) return 0;
    lp_record(LP_PACK_ATTEMPT, y0 * cv_w + x0, w * h);
    if (lp.reset) return 1;
    if (lp.wait_result && !lcd_busy && !lcd_fault) {
        lp.phase = LP_MISS; lp.released = 1;
        lp.after_hash = lp_hash(cv_px, sizeof cv_px);
        lp_record(LP_RELEASE, lp.after_hash, 1u); /* real normal wait already released */
        return 1;
    }
    if (x0 || y0 != 62u || w != 240u || h != 62u || cv_w != 240u || cv_h != 124u ||
        lp.source != (uintptr_t)cv_px || lp.selected_submits != 1u || lp.wait_result ||
        !lcd_busy || !lcd_fault || !lcd_initialized || fm1_lcd_done()) {
        lp.phase = LP_MISS;
        return 1; /* recognized probe, but never permission to store or resubmit */
    }
    lp.pending_before_copy = 1u;
    lp.phase = LP_WAITING;
    __asm__ volatile("" ::: "memory");
    return 1;
}
static uint32_t lp_control_write(uint32_t probe)
{
    return probe && !lp.reset && !lp.overflow && lp.phase == LP_WAITING && lp.mode == LP_CONTROL;
}
static void lp_pack_denied(uint32_t probe)
{
    if (probe) { lp.denied++; lp_record(LP_DENIED, lp.phase, 0); }
}
static uint32_t lp_pack_ready(uint32_t probe)
{
    if (!probe) return 1;
    if (!lp_control_write(probe) || fm1_lcd_done()) { lp.phase = LP_MISS; return 0; }
    /* Fresh raw hardware completion observation, then ordered real packing.
     * SPI_CNT is retained raw only: it has no assumed remaining-byte semantics. */
    lp_record(LP_COPY_BEGIN, 29760u, 29760u);
    if (lp.reset || lp.overflow || (lp.trace[lp.count - 1u][2] & 0x8000u)) {
        lp.phase = LP_MISS;
        return 0; /* completion raced the fresh COPY_BEGIN snapshot: no stores */
    }
    __asm__ volatile("" ::: "memory");
    return 1;
}
static void lp_pack_end(uint32_t probe, uint32_t stores)
{
    if (probe) {
        __asm__ volatile("" ::: "memory");
        lp.stores = stores;
        lp_record(LP_COPY_END, 0, stores * 2u);
    }
}
/* Position codes are intentionally disjoint at upper-half coordinates.
 * C is dark grey; A upper is red/white, lower blue/yellow. Packing repeats the
 * lower code at upper coordinates, impossible under partial unchanged A over C. */
static uint16_t lp_pixel(uint32_t x, uint32_t y)
{
    uint32_t code = ((x / 16u) ^ (y % 62u / 8u)) & 1u;
    return y < 62u ? (code ? 0xFFFFu : 0xF800u) : (code ? 0xFFE0u : 0x001Fu);
}
static int lp_arm(uint32_t mode, uint32_t run, uint32_t backup_restore_confirmed)
{
    uint32_t issued[2];
    if (lp.active || mode > LP_RECOVERY || !run || !backup_restore_confirmed || !LP_OWNER_READY()) return 0;
    lcd_sync();
    if (lcd_busy || lcd_fault || !lcd_initialized) return 0;
    memset(&lp, 0, sizeof lp);
    lp.active = lp.hold = 1; lp.mode = mode; lp.run = run;
    lp.phase = LP_C_READY; lp.arm_ms = fm1_ms;
    fm1_lcd_baud_state(issued); lp.baud_epoch = issued[1];
    if (issued[0] != 4u || !issued[1]) { lp_request_reset(LP_RST_ISSUED_BAUD); return 0; }
    /* All later write producers are now excluded, including during C setup. */
    lcd_fill(0, 58, 240, 124, 0x1082u);
    LP_LABEL(mode, run); /* outside y58..181, before selected DMA */
    lcd_sync();
    if (lcd_busy || lcd_fault) { lp_request_reset(LP_RST_C_SETUP); return 0; }
    cv_begin(240, 124, 0x1082u);
    lp.c_hash = lp_hash(cv_px, sizeof cv_px);
    lp_record(LP_ARM, mode, run);
    return !lp.reset;
}
static int lp_go(void)
{
    uint32_t x, y;
    if (!lp.active || lp.phase != LP_C_READY || lp.reset || lcd_busy || lcd_fault) return 0;
    cv_begin(240, 124, 0);
    for (y = 0; y < 124u; y++) for (x = 0; x < 240u; x++) cv_px[y * 240u + x] = swap16(lp_pixel(x,y));
    lp.a_hash = lp_hash(cv_px, sizeof cv_px);
    lp.phase = LP_SETUP; lp.go_ms = fm1_ms;
    __asm__ volatile("" ::: "memory");
    lcd_blit(0, 58, 240, 124, cv_px); /* normal six submissions: window, then selected data */
    if (lp.phase != LP_TRANSFER || lp.selected_submits != 1u || lp.submits != 6u ||
        lp.issued_submits != 6u || lp.issued_seq != 6u || lp.source != (uintptr_t)cv_px || lp.programmed_bytes != LP_BYTES) { lp_request_reset(LP_RST_SELECTION); return 0; }
    lp_record(LP_SELECTED, (uint32_t)lp.source, lp.programmed_bytes); /* actual post-store issued tuple */
    if (lp.reset) return 0;
    if (lp.mode == LP_RECOVERY) {
        /* One software deadline only. Normal DMA/clock/PND are unchanged. */
        lp.short_wait = 1;
        lcd_sync();
        if (lp.reset) return 0;
        if (!lcd_fault || !lcd_busy || lp.wait_result || fm1_lcd_done()) {
            /* A completed-before-timeout transfer is not a qualified failure. */
            lp_request_reset(LP_RST_RECOVERY);
            return 0;
        }
        lp_record(LP_RECOVERY_FAULT, lp.a_hash, 0);
        if (lp.reset || (lp.trace[lp.count - 1u][2] & 0x8000u)) {
            if (!lp.reset) lp_request_reset(LP_RST_RECOVERY);
            return 0;
        }
        lp.recovery_stage = 1u;
        LP_RECOVERY_VIEW(); /* fixed RAM-only view, never settings/sound data */
        lp.phase = LP_WAITING;
        lp.hold = 0u; /* ordinary ui_draw/lcd_service now own ALL recovery */
    } else if (lp.mode != LP_A_ONLY) {
        lp.short_wait = 1;
        /* Both modes call the actual ownership-protected producer. Only control
         * may bypass its failed guard, once and inside this exact copy range. */
        cv_blit_rect(0, 58, 0, 62, 240, 62);
    } else lp.phase = LP_WAITING;
    return !lp.reset;
}
static void lp_step(void)
{
    if (!lp.active) return;
    if ((uint32_t)(fm1_ms - lp.arm_ms) >= LP_HOLD_MS) lp_request_reset(LP_RST_HOLD);
    if (lp.mode == LP_RECOVERY) {
        if (lp.selected && lp.recovery_stage < 4u &&
            (uint32_t)(fm1_ms - lp.go_ms) >= LP_RECOVERY_MS)
            lp_request_reset(LP_RST_RECOVERY);
        return; /* never acknowledge, deselect or release in this mode */
    }
    if (!lp.selected || lp.released || lp.reset) return;
    if (fm1_lcd_done()) {
        lp_record(LP_COMPLETE, lp.phase, 0);
        if (lp.reset || lp.overflow) return;
        if (!fm1_lcd_complete()) { lp_request_reset(LP_RST_COMPLETE); return; }
        fm1_lcd_deselect();
        __asm__ volatile("" ::: "memory");
        lcd_busy = 0;
        lp.released = 1;
        lp.after_hash = lp_hash(cv_px, sizeof cv_px); /* outside the short race */
        if (lp.phase != LP_MISS) lp.phase = LP_SETTLED;
        lp_record(LP_RELEASE, lp.after_hash, 0);
    } else if ((uint32_t)(fm1_ms - lp.go_ms) >= LP_HW_MS) lp_request_reset(LP_RST_HW);
}
/* Only observation metadata changes here: the ordinary driver already owns
 * retry timing, ACK, CS and source release. No hardware or LCD-state writes. */
static void lp_recovery_observe(uint32_t event)
{
    if (!lp.active || lp.mode != LP_RECOVERY || !lp.selected || LCD_PROBE_STOPPED()) return;
    if (event == LP_SERVICE_ARM) {
        if (lp.recovery_stage != 1u || !lcd_fault || !lcd_busy) {
            lp_request_reset(LP_RST_RECOVERY); return;
        }
        lp.recovery_arm_ms = fm1_ms;
    } else if (event == LP_SERVICE_POLL) {
        if (lp.recovery_stage != 1u || !lcd_fault || !lcd_busy ||
            (uint32_t)(fm1_ms - lp.recovery_arm_ms) < LCD_RETRY_MS) {
            lp_request_reset(LP_RST_RECOVERY); return;
        }
    } else if (event == LP_SERVICE_RELEASE) {
        if (lp.recovery_stage != 1u || lcd_busy || !lcd_fault) {
            lp_request_reset(LP_RST_RECOVERY); return;
        }
        lp.recovery_stage = 2u; lp.recovery_release_ms = fm1_ms;
        lp.released = 1u; lp.after_hash = lp_hash(cv_px, sizeof cv_px);
        lp.phase = LP_REPAINT; /* permit only ordinary post-release redraw */
    } else if (event == LP_RECOVERY_CLEAR) {
        if (lp.recovery_stage != 2u || lcd_fault || lcd_busy ||
            (uint32_t)(fm1_ms - lp.recovery_release_ms) < 240u) {
            lp_request_reset(LP_RST_RECOVERY); return;
        }
        lp.recovery_stage = 3u;
    } else if (event == LP_RECOVERY_SHOWN) {
        if (lp.recovery_stage == 4u) return;
        if (lp.recovery_stage != 3u || lcd_fault) {
            lp_request_reset(LP_RST_RECOVERY); return;
        }
        /* SHOWN is the production DISPON-issued/SCR_ON transition, not LCD ACK. */
        lp.recovery_stage = 4u; lp.recovery_shown_ms = fm1_ms;
    } else { lp_request_reset(LP_RST_RECOVERY); return; }
    lp_record(event, lp.recovery_stage, fm1_ms);
}
static int lp_finish(void)
{
    if (!lp.active || !lp.released || lp.reset || lp.overflow ||
        (lp.phase != LP_SETTLED && lp.phase != LP_MISS)) return 0;
    lp_record(LP_HOLD_END, lp.phase, 0);
    if (lp.reset) return 0;
    lp.hold = 0; lp.phase = LP_REPAINT;
    LP_REDRAW(); /* normal service/wake/full latest redraw; still no writes/gestures */
    return 1;
}
#endif
