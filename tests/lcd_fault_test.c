/* SPDX-License-Identifier: GPL-3.0-only */
/* Actual driver, canvas, native UI and capture against independent SPI ownership. */
#define UI_LCD_SOURCE "lcd_fault_model.h"
#define FELUCCA_SCREEN_CAPTURE 1
#include <stdint.h>
static uint32_t fault_page_calls, fault_drop_force;
#define UI_DRAW_PAGE_HOOK() do { \
    fault_page_calls++; \
    if (fault_drop_force && scrn.recovering && scrn.st == SCR_SHOW) ui.force = 0; \
} while (0)
#include "ui_harness.h"

static uint32_t fault_checks;
static uint16_t expected[240u * 240u], native_expected[240u * 240u], held_canvas[CV_MAX];
static void need(int ok, const char *why)
{
    fault_checks++;
    if (!ok) { fprintf(stderr, "FAIL LCD containment: %s (fault=%u owned=%u sent=%u)\n", why, lcd_fault, lcd_busy, lcd_model_sent); exit(1); }
}
static void reset_model(void)
{
    /* A simulated power cycle, only after the oracle explicitly completes any
     * outstanding transfer. This is test setup, never a production abort. */
    if (lcd_model_pending) { lcd_model_release = 1; fm1_lcd_complete(); fm1_lcd_deselect(); }
    lcd_busy = lcd_fault = lcd_retry_armed = 0; lcd_initialized = 1;
    lcd_faults = lcd_recoveries = lcd_retry_t = 0;
    lcd_model_sent = lcd_model_waits = lcd_model_polls = lcd_model_fail_at = lcd_model_fail_cmd = 0;
    lcd_model_init_n = lcd_model_baud = 0;
    lcd_model_partial = lcd_model_consumed = 0;
    memset(&scap, 0, sizeof scap);
    fm1_ms = 1000u; ui_power_on();
    ui_prefs = PREF_ANIM_OFF; ui_prefs2 = 0; ui_style = 0; ui_scr = 0;
    settings.palette = 0; palette_set(0);
    memset(host_screen, 0, sizeof host_screen);
}
static void poison_writers(void)
{
    static const uint16_t ramp[16] = {0};
    memcpy(held_canvas, cv_px, sizeof cv_px);
    cv_begin(240, 124, 0xF800);
    cv_pset(0, 0, 0x1234); cv_rect(0, 0, 240, 124, 0x1234);
    cv_line(0, 0, 239, 123, 0x1234);
    /* Invalid data is deliberate: failed raster work must stop before decode. */
    cv_alpha(0, 0, 240, 124, NULL, ramp);
#if UI_FONT_BITMAP
    cv_bitmap(0, 0, 240, 124, NULL, 1, 0x1234);
    cv_bitmap(0, 0, 240, 124, NULL, 2, 0x1234);
    cv_bitmap(0, 0, 240, 123, NULL, 3, 0x1234);
#endif
    cv_alpha_hc(0, 0, 240, 124, NULL, NULL, ramp);
    cv_blit_rect(0, 0, 1, 1, 20, 20);
    lcd_fill(0, 0, 240, 240, 0x1234); lcd_blit(0, 0, 240, 124, cv_px);
    draw_text_box(0, 0, 240, &AF_M, "STOP", 0xFFFF, 0);
    lcd_power(0); lcd_wake_now(); lcd_init();
    need(!memcmp(held_canvas, cv_px, sizeof cv_px), "failed canvas acquisition prevents every writer");
    lcd_model_owned();
}
static void failures_at_each_transfer(void)
{
    uint32_t at;
    for (at = 1; at <= 8u; at++) {
        uint32_t sent, waits, polls, i;
        reset_model(); cv_begin(240, 124, 0x5555);
        lcd_model_fail_at = at;
        lcd_fill(0, 0, 240, 3, 0xABCD); lcd_sync();
        need(lcd_fault && lcd_busy && lcd_model_pending, "timeout retains command/coordinate/pixel ownership");
        need(lcd_model_sent == at && lcd_faults == 1u, "first failure cancels remaining fill submissions");
        sent = lcd_model_sent; waits = lcd_model_waits; polls = lcd_model_polls;
        poison_writers();
        need(lcd_model_sent == sent && lcd_model_waits == waits, "failed work never submits or waits again");
        for (i = 0; i < 100u; i++) { fm1_ms += 15u; ui_draw(); lcd_model_owned(); }
        need(lcd_model_sent == sent && lcd_model_waits == waits && lcd_model_polls - polls <= 6u,
             "persistent failure has bounded observations across frames");
        lcd_model_release = 1; fm1_ms += LCD_RETRY_MS; ui_draw(); lcd_sync();
        need(!lcd_fault && !lcd_busy && lcd_recoveries == 1u, "late completion permits one fresh frame");
    }
}
static void final_canvas_and_retry(void)
{
    uint32_t sent, polls, t;
    reset_model(); cv_begin(20, 20, 0x4321);
    lcd_model_fail_at = 6; cv_blit(0, 0);
    need(!lcd_fault && lcd_busy, "healthy final transfer stays asynchronous");
    cv_begin(20, 20, 0xAAAA);
    need(lcd_fault && lcd_busy, "final in-flight failure is detected before canvas reuse");
    sent = lcd_model_sent; polls = lcd_model_polls;
    poison_writers(); need(lcd_model_sent == sent, "owned final canvas remains frozen");
    t = UINT32_MAX - 100u;
    need(!lcd_service(t), "fault backoff arms without polling");
    lcd_model_release = 1;
    need(!lcd_service(t + 249u) && lcd_model_polls == polls, "no early poll across time wrap");
    need(lcd_service(t + 250u) && lcd_model_polls == polls + 1u, "verified late completion releases at wrap-safe boundary");
    need(!lcd_service(t + 251u), "recovery edge published only once");
    lcd_model_fail_at = lcd_model_sent + 1u; lcd_fill(0, 0, 1, 1, 0);
    need(lcd_fault && lcd_faults == 2u, "a failed recovery relatches with a fresh backoff");
}
static void mixer_canvas_failure(void)
{
    uint32_t sent;
    reset_model(); go_page(GR_TRK); ui.force = 1;
    need(reading_kind() == RK_BANK && !bank_tall(), "native mixer exercises direct knob canvas path");
    cv_begin(240, 124, T_BG);
    lcd_model_fail_at = lcd_model_sent + 6u; cv_blit(0, 20);
    need(!lcd_fault && lcd_busy && lcd_model_pending, "mixer starts before failed ownership acquisition");
    memcpy(held_canvas, cv_px, sizeof cv_px); sent = lcd_model_sent;
    draw_tracks();
    need(lcd_fault && lcd_busy && lcd_model_sent == sent, "mixer cancels all submissions after acquisition failure");
    need(!memcmp(held_canvas, cv_px, sizeof cv_px), "mixer knob raster never changes DMA-owned canvas");
    lcd_model_owned();
}
static void latest_scene(uint32_t palette, uint32_t style, uint32_t large, uint32_t scene)
{
    uint32_t normal_sent;
    reset_model(); ui_draw(); lcd_sync(); normal_sent = lcd_model_sent;
    /* Fail a live canvas, then change page/theme/overlay while it is owned. */
    cv_begin(240, 124, T_BG); lcd_model_fail_at = lcd_model_sent + 6u; cv_blit(0, 20);
    cv_begin(240, 124, T_BG); need(lcd_fault, "scene starts with owned canvas failure");
    ui.menu = 1; ui.menu_sel = MI_COLOR; ui_style = (uint8_t)style;
    ui_prefs = PREF_ANIM_OFF | (large ? PREF_LARGE : 0u);
    settings.palette = (uint8_t)palette; palette_set(palette);
    if (scene == 1u) { ui.menu = 0; ui.confirm = CF_CLEAR_SEQ; }
    else if (scene == 2u) { ui.menu = 0; go_page(GR_ADSR); }
    else if (scene == 3u) { ui.menu = 0; name_open(NK_USER_SAVE, 5); }
    else if (scene == 4u) { ui.menu = 0; ui.home = 1; }
    else if (scene == 5u) { ui.menu = 0; go_page(GR_TRK); }
    ui.force = 0; fm1_ms += 15; ui_draw();
    need(lcd_fault && ui.force && lcd_model_sent == normal_sent + 6u, "failed page change keeps latest redraw pending");
    lcd_model_release = 1; fm1_ms += LCD_RETRY_MS; ui_draw(); lcd_sync();
    fm1_ms += 120; ui_draw(); fm1_ms += 120; ui_draw(); lcd_sync();
    need(!lcd_fault && !lcd_busy && scrn.st == SCR_ON, "latest scene recovered");
    memcpy(expected, host_screen, sizeof expected);
    /* STYLE/LARGE are retained data, not native layout choices. Keep all four
     * compatibility inputs and independently compare their complete images. */
    if (!style && !large) memcpy(native_expected, expected, sizeof expected);
    else need(!memcmp(native_expected, expected, sizeof expected), "retired STYLE/LARGE bits keep the unified native image");
    memset(host_screen, 0xA5, sizeof host_screen); lcd_fill(0, 0, 240, 240, T_BG); ui.force = 1; ui_draw(); lcd_sync();
    if (memcmp(expected, host_screen, sizeof expected))
        fprintf(stderr, "scene palette=%u style=%u large=%u scene=%u\n", palette, style, large, scene);
    need(!memcmp(expected, host_screen, sizeof expected), "recovery is pixel-identical to latest forced full redraw");
}
static void cached_scene_failure(uint32_t scene, uint32_t partial)
{
    uint32_t sig[5], sent;
    int32_t before, id = scene == 1u ? P_ATK : P_LEVEL;
    reset_model();
    if (!scene) { ui.menu = 1; ui.menu_sel = MI_LEDS; }
    else go_page(scene == 1u ? GR_ADSR : GR_TRK);
    ui_draw(); lcd_sync();
    if (scene) {
        need(bank_on() && ui.read_bank.was && bank_tall() == (scene == 1u), "cached scene uses tall or short native bank");
        memcpy(sig, ui.read_bank.sig, sizeof sig);
        TSEL->p[id]++;
    } else {
        sig[0] = ui.menu_sig;
        menu_put(MI_LEDS, menu_step(MI_LEDS, 1));
    }
    if (!partial) {
        /* The next cv_begin must acquire a canvas still borrowed by DMA. */
        cv_begin(240, 124, T_BG);
        lcd_model_fail_at = lcd_model_sent + 6u; cv_blit(0, 20);
        need(!lcd_fault && lcd_busy, "cache test begins with asynchronous canvas ownership");
    } else {
        lcd_model_fail_at = lcd_model_sent + 6u;
        lcd_model_partial = 128u;
    }
    sent = lcd_model_fail_at;
    if (scene) draw_columns(); else draw_menu();
    lcd_sync();
    need(lcd_fault && lcd_busy && lcd_model_pending && lcd_model_sent == sent, "cached renderer stops submissions at failed acquisition or payload");
    if (partial)
        need(lcd_model_consumed == 128u && lcd_model_consumed < lcd_model_n, "partial pixel DMA consumes a prefix without releasing the canvas");
    if (scene)
        need(ui.read_bank.was && memcmp(sig, ui.read_bank.sig, sizeof sig), "bank cache advanced despite incomplete image");
    else need(sig[0] != ui.menu_sig, "menu signature advanced despite incomplete image");
    poison_writers();
    before = scene ? TSEL->p[id] : (int32_t)menu_get(MI_LEDS);
    turn(scene ? EN_K1 : EN_K4, 1);
    need((scene ? TSEL->p[id] : (int32_t)menu_get(MI_LEDS)) != before, "latest cached value still changes through real panel input while blocked");
    need(ui.force && lcd_model_sent == sent, "failed frame keeps full repaint pending after cache publication");
    lcd_model_owned(); ui.hot_t = ui.curve_t = 0;
    lcd_model_release = 1; fm1_ms += LCD_RETRY_MS; ui_draw();
    fm1_ms += 120; ui_draw(); fm1_ms += 120; ui_draw(); lcd_sync();
    need(!lcd_fault && !lcd_busy && scrn.st == SCR_ON, "cached scene recovers only after verified release and wake");
    memcpy(expected, host_screen, sizeof expected);
    memset(host_screen, 0xA5, sizeof host_screen);
    lcd_fill(0, 0, 240, 240, T_BG); ui.force = 1; ui_draw(); lcd_sync();
    need(!memcmp(expected, host_screen, sizeof expected), "cached recovery matches the complete latest forced redraw");
}
static void power_and_capture(void)
{
    uint32_t st;
    reset_model(); lcd_model_fail_at = 1; lcd_power(0);
    need(lcd_fault && lcd_busy, "power command remains owned after failure");
    scrn.st = SCR_WAKE; kb_asleep = scrn.eat = 1;
    st = scrn.st; fm1_ms += 200; ui_draw();
    need(scrn.st == st && !kb_asleep && !scrn.eat, "failed wake neither claims ON nor suppresses musical input");
    need(!scr_input(0, 0), "input remains serviceable with failed display");
    lcd_model_release = 1; fm1_ms += 250; ui_draw();
    need(scrn.st == SCR_WAKE && !lcd_fault && scrn.recovering, "verified release begins conservative wake normalization");
    need(!scr_input(0, 0), "recovery delay does not suppress musical input");
    fm1_ms += 120; ui_draw();
    need(scrn.st == SCR_SLPOUT, "SLPOUT waits from actual late completion");
    fm1_ms += 120; ui_draw(); lcd_sync(); need(scrn.st == SCR_ON, "redraw precedes successful DISPON");
    reset_model(); ui_draw(); lcd_sync();
    need(scap_start(0), "begin capture");
    lcd_model_fail_at = lcd_model_sent + 1u; ui_draw();
    need(lcd_fault && scap.state == SCAP_COVERAGE && !scap.tapping && !scap_holding(fm1_ms), "failed capture is terminal, never READY");
    reset_model(); scrn.st = SCR_OFF; scrn.t = fm1_ms - 120u;
    need(scap_start(1) && scap.state == SCAP_WAKING, "begin explicit wake capture");
    lcd_model_fail_at = 1; ui_draw();
    need(lcd_fault && scap.state == SCAP_COVERAGE && !scap_holding(fm1_ms) && scrn.st != SCR_ON,
         "failed wake releases capture lease without claiming visibility");
}
static void final_capture_and_sleep(void)
{
    uint32_t count, base, at;
    reset_model(); ui_draw(); lcd_sync(); base = lcd_model_sent;
    need(scap_start(0), "measure healthy capture transfers"); ui_draw(); count = lcd_model_sent - base;
    need(scap.state == SCAP_READY && count, "healthy capture provides exact final-payload position");
    reset_model(); ui_draw(); lcd_sync(); base = lcd_model_sent;
    need(scap_start(0), "capture for final in-flight failure"); lcd_model_fail_at = base + count; ui_draw();
    need(lcd_fault && scap.state == SCAP_COVERAGE && !scap.tapping, "last capture payload cannot publish READY on failed completion");
    for (at = 1; at <= 2u; at++) {
        reset_model(); scr_idle_put(1); scr_mode_put(0); scr_sync(); scrn.idle = fm1_ms - 300001u;
        lcd_model_fail_at = at; ui_draw();
        need(lcd_fault && lcd_busy && scrn.st == SCR_ON, "failed sleep command never claims OFF");
        need(!kb_asleep, "failed sleep retains live keyboard");
        lcd_model_release = 1; fm1_ms += 1; ui_draw(); fm1_ms += 250; ui_draw();
        need(scrn.st == SCR_WAKE && scrn.recovering, "late SLPIN completion normalizes power, not just pixels");
        fm1_ms += 120; ui_draw(); fm1_ms += 120; ui_draw(); lcd_sync();
        need(scrn.st == SCR_ON && !scrn.recovering && !lcd_fault, "SLPOUT/full redraw/DISPON restore actual visible state");
    }
    reset_model(); scrn.st = SCR_SHOW; ui.force = 1; lcd_model_fail_cmd = 0x29; ui_draw();
    need(lcd_fault && scrn.st == SCR_SHOW && !kb_asleep, "failed DISPON cannot claim ON");
    reset_model(); ui_draw(); lcd_sync(); lcd_model_fail_at = lcd_model_sent + 1u; lcd_fill(0, 0, 1, 1, 0);
    { int16_t before = TSEL->p[P_ATK]; go_page(GR_ADSR); turn(EN_K1, before < 64 ? 1 : -1); need(TSEL->p[P_ATK] != before, "real ENV knob input still edits while display is failed"); }
}
static void normalization_failures(void)
{
    uint32_t phase;
    for (phase = 0; phase < 4u; phase++) {
        uint32_t fail, pages;
        reset_model(); lcd_model_fail_at = 1; lcd_fill(0, 0, 1, 1, 0); ui_draw();
        lcd_model_release = 1; fm1_ms += 250; ui_draw();
        need(!lcd_fault && scrn.st == SCR_WAKE, "normalization begins only after verified old completion");
        if (!phase) lcd_model_fail_at = lcd_model_sent + 1u; /* SLPOUT */
        fm1_ms += 120; ui_draw();
        if (phase) {
            /* First command, coordinates, and final pixel row of full clear. */
            lcd_model_fail_at = lcd_model_sent + (phase == 1u ? 1u : phase == 2u ? 2u : 245u);
            pages = fault_page_calls;
            fm1_ms += 120; ui_draw();
            need(fault_page_calls == pages, "failed recovery clear cancels page-render computation");
        }
        fail = lcd_model_fail_at;
        need(lcd_fault && lcd_busy && lcd_model_sent == fail && scrn.st != SCR_ON,
             "normalization/full-clear failure relatches before later redraw or visibility");
        poison_writers(); need(lcd_model_sent == fail, "failed normalization still owns its source");
        /* Change latest state during the second backoff and both timed waits. */
        ui.menu = 1; ui.menu_sel = MI_GRAPH; ui_style = 1; palette_set(8); settings.palette = 8;
        fm1_ms += 1; ui_draw(); lcd_model_release = 1; fm1_ms += 250; ui_draw();
        need(!scr_input(0, 0), "second recovery wait keeps input live");
        fm1_ms += 120; ui_draw(); ui.menu_sel = MI_COLOR;
        fm1_ms += 120; ui_draw(); lcd_sync();
        need(!lcd_fault && scrn.st == SCR_ON && lcd_recoveries == 2u, "second verified completion restores latest normalized image");
        memcpy(expected, host_screen, sizeof expected);
        lcd_fill(0, 0, 240, 240, T_BG); ui.force = 1; ui_draw(); lcd_sync();
        need(!memcmp(expected, host_screen, sizeof expected), "changes during recovery waits reach latest full image");
    }
}
static void boot_failure(void)
{
    static const uint32_t fail[] = {1, 4, 6, 8, 9, 14, 254};
    uint32_t i;
    for (i = 0; i < sizeof fail / sizeof fail[0]; i++) {
        reset_model(); lcd_initialized = 0; lcd_model_fail_at = fail[i]; lcd_init();
        need(lcd_fault && lcd_busy && !lcd_initialized && lcd_model_sent == fail[i], "boot stops at first failed command/data/pixel transfer");
        poison_writers();
        lcd_model_release = 1; lcd_service(1000); need(!lcd_service(1250), "partial init is not repaired by a frame retry");
        need(lcd_fault && !lcd_busy && !lcd_initialized, "partial boot stays fail-stopped after safe release");
        lcd_init(); need(lcd_model_init_n == 1u, "init never resets a fault as an abort");
    }
}

int main(int argc, char **argv)
{
    uint32_t p, s, large, scene;
    if (argc == 2 && !strcmp(argv[1], "--dma-negative")) {
        reset_model(); cv_begin(2, 2, 0x1234); cv_blit(0, 0); cv_px[0] ^= 1u; lcd_model_owned(); return 0;
    }
    if (argc == 2 && !strcmp(argv[1], "--cache-negative")) {
        fault_drop_force = 1; cached_scene_failure(1, 1); return 0;
    }
    if (argc != 1) return 2;
    failures_at_each_transfer(); final_canvas_and_retry(); mixer_canvas_failure();
    for (p = 0; p < NPALETTES; p++) for (scene = 0; scene < 6u; scene++)
        for (s = 0; s < 2u; s++) for (large = 0; large < 2u; large++) latest_scene(p, s, large, scene);
    for (scene = 0; scene < 3u; scene++) for (p = 0; p < 2u; p++) cached_scene_failure(scene, p);
    power_and_capture(); final_capture_and_sleep(); normalization_failures(); boot_failure();
    printf("PASS LCD containment: actual driver/canvas/UI, source ownership, bounded retries, late completion, latest pixels, power/capture/boot (%u checks)\n", fault_checks);
    return 0;
}
