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
static void lp_record(uint32_t event, uint32_t a, uint32_t b)
{
    uint32_t i = lp.count, t = fm1_ticks(), raw[4];
    fm1_lcd_snapshot(raw);
    if (raw[3] != 4u) lp.reset = 1;
    if (i == LP_TRACE_CAP) { lp.overflow = lp.reset = 1; return; }
    lp.trace[i][0] = event; lp.trace[i][1] = t; lp.trace[i][2] = raw[0];
    lp.trace[i][3] = lcd_busy | (uint32_t)lcd_fault << 8 | (uint32_t)lcd_initialized << 16;
    lp.trace[i][4] = a; lp.trace[i][5] = b;
    lp.trace[i][6] = raw[1]; lp.trace[i][7] = raw[2];
    __asm__ volatile("" ::: "memory");
    lp.count = i + 1u;
}
static void lp_submit(uint32_t command, const void *source, uint32_t bytes)
{
    if (!lp.active || lp.phase == LP_C_READY || lp.phase == LP_REPAINT) return;
    lp.submits++;
    lp_record(LP_SUBMIT, command, bytes);
    if (lp.phase == LP_SETUP && !command && source == cv_px && bytes == LP_BYTES) {
        lp.selected_submits++;
        lp.source = (uintptr_t)source;
        lp.selected = 1;
        lp.phase = LP_TRANSFER;
    } else if (lp.selected) {
        /* Observer never suppresses a real submit: unexpected traffic invalidates
         * evidence and requests ordinary full-chip reset at the next main pass. */
        lp.reset = 1;
    }
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
    if (lp.active || mode > LP_CONTROL || !run || !backup_restore_confirmed || !LP_OWNER_READY()) return 0;
    lcd_sync();
    if (lcd_busy || lcd_fault || !lcd_initialized) return 0;
    memset(&lp, 0, sizeof lp);
    lp.active = lp.hold = 1; lp.mode = mode; lp.run = run;
    lp.phase = LP_C_READY; lp.arm_ms = fm1_ms;
    /* All later write producers are now excluded, including during C setup. */
    lcd_fill(0, 58, 240, 124, 0x1082u);
    LP_LABEL(mode, run); /* outside y58..181, before selected DMA */
    lcd_sync();
    if (lcd_busy || lcd_fault) { lp.reset = 1; return 0; }
    cv_begin(240, 124, 0x1082u);
    lp.c_hash = lp_hash(cv_px, sizeof cv_px);
    lp_record(LP_ARM, mode, run);
    return 1;
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
    if (lp.phase != LP_TRANSFER || lp.selected_submits != 1u || lp.submits != 6u) { lp.reset = 1; return 0; }
    lp_record(LP_SELECTED, (uint32_t)(uintptr_t)cv_px, LP_BYTES); /* after real ADR/CNT submission */
    if (lp.mode != LP_A_ONLY) {
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
    if ((uint32_t)(fm1_ms - lp.arm_ms) >= LP_HOLD_MS) lp.reset = 1;
    if (!lp.selected || lp.released || lp.reset) return;
    if (fm1_lcd_done()) {
        lp_record(LP_COMPLETE, lp.phase, 0);
        if (!fm1_lcd_complete()) { lp.reset = 1; return; }
        fm1_lcd_deselect();
        __asm__ volatile("" ::: "memory");
        lcd_busy = 0;
        lp.released = 1;
        lp.after_hash = lp_hash(cv_px, sizeof cv_px); /* outside the short race */
        if (lp.phase != LP_MISS) lp.phase = LP_SETTLED;
        lp_record(LP_RELEASE, lp.after_hash, 0);
    } else if ((uint32_t)(fm1_ms - lp.go_ms) >= LP_HW_MS) lp.reset = 1;
}
static int lp_finish(void)
{
    if (!lp.active || !lp.released || lp.reset || lp.overflow ||
        (lp.phase != LP_SETTLED && lp.phase != LP_MISS)) return 0;
    lp_record(LP_HOLD_END, lp.phase, 0);
    lp.hold = 0; lp.phase = LP_REPAINT;
    LP_REDRAW(); /* normal service/wake/full latest redraw; still no writes/gestures */
    return 1;
}
#endif
