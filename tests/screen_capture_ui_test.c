/* SPDX-License-Identifier: GPL-3.0-only */
/* Real native UI and capture service; host_screen is an independent LCD sink. */
#define UI_TEST_NO_MAIN
#define FELUCCA_SCREEN_CAPTURE 1
#include "ui_test.c"

static uint32_t capture_checks, capture_frames, capture_scenes;
static void capture_need(int ok, const char *why)
{
    capture_checks++;
    if (!ok) {
        fprintf(stderr, "FAIL capture UI: %s (palette=%u style=%u large=%u menu=%u row=%u offset=%u state=%u covered=%u)\n",
                why, settings.palette, ui_style, !!(ui_prefs & PREF_LARGE), ui.menu, menu_off_sel,
                scap.offset, scap.state, scap.covered);
        exit(1);
    }
}
static void capture_setup(uint32_t palette, uint32_t style, uint32_t large, uint32_t row)
{
    lcd_sync(); memset(&scap, 0, sizeof scap);
    fm1_ms = 1000u; ui_power_on();
    ui_scr = 0; ui_prefs = PREF_ANIM_OFF | (large ? PREF_LARGE : 0u); ui_style = (uint8_t)style;
    palette_set(palette); settings.palette = (uint8_t)palette;
    ui.menu = 1; ui.menu_sel = MI_SCROFF;
    menu_off_sel = menu_off_error = 0;
    capture_need(scr_idle_put(1) && scr_mode_put(1) && scr_dark_put(3), "configure realistic independent 5m / 30m timers");
    if (row < MO_COUNT) { menu_off_open(); menu_off_sel = (uint8_t)row; }
    host_lcd_async = 1; host_dma_bad = 0;
    ui_draw(); lcd_sync(); /* establish ordinary cache/config before requesting capture */
}
static void capture_frame(void)
{
    ui_draw(); capture_frames++;
    capture_need(!host_dma.p && !host_dma_bad, "READY frame drains delayed DMA without reusing its source");
}
static void capture_scene(void)
{
    uint32_t offset, token, hash = 0, menu = ui.menu, sel = ui.menu_sel, row = menu_off_sel;
    uint32_t idle = scrn.idle, power = host_pw_n, hot = ui.hot_t, msg = ui.msg_t, bpm = ui.bpm_t;
    uint8_t saved[sizeof settings_dev], saved_scr = ui_scr, saved_prefs = ui_prefs;
    uint8_t saved_settings[sizeof settings], saved_prefs2 = ui_prefs2;
    uint8_t saved_style = ui_style;
    memcpy(saved, settings_dev, sizeof saved);
    memcpy(saved_settings, &settings, sizeof settings);
    scap_input_time = scrn.idle;
    capture_need(scap_begin(fm1_ms), "start UI capture"); token = scap.token;
    for (offset = 0; offset < 240u * 240u * 2u; offset += SCAP_BYTES) {
        capture_frame();
        capture_need(scap.state == SCAP_READY && scap.covered == 1920u, "actual menu forces full coverage of every band");
        capture_need(!memcmp(scap.pixels, (const uint8_t *)host_screen + offset, SCAP_BYTES), "band bytes equal actual completed LCD sink");
        if (!offset) hash = scap.draw_hash;
        capture_need(scap.draw_hash == hash, "real static menu stream is coherent for all 30 bands");
        capture_need(scap_next(token, offset + SCAP_BYTES), "advance UI capture");
    }
    capture_need(scap.state == SCAP_COMPLETE, "menu capture completes");
    capture_need(ui.menu == menu && ui.menu_sel == sel && menu_off_sel == row && scrn.idle == idle &&
                 host_pw_n == power && !song.playing && !memcmp(saved, settings_dev, sizeof saved) &&
                 !memcmp(saved_settings, &settings, sizeof settings) && ui_prefs2 == saved_prefs2 &&
                 ui_scr == saved_scr && ui_prefs == saved_prefs && ui_style == saved_style &&
                 hot == ui.hot_t && msg == ui.msg_t && bpm == ui.bpm_t,
                 "capture preserves navigation, settings, inactivity and unrelated UI timers");
    capture_scenes++;
}
static void test_menu_matrix(void)
{
    uint32_t palette, style, large, row;
    /* Built-in and CUSTOM palettes, both styles, normal/LARGE, root plus all detail rows. */
    for (palette = 0; palette <= NPALETTES; palette++)
        for (style = ST_FLAT; style <= ST_LINE; style++)
            for (large = 0; large < 2; large++)
                for (row = 0; row <= MO_COUNT; row++) {
                    capture_setup(palette, style, large, row); capture_scene();
                }
}
static void test_rejections(void)
{
    uint32_t kind, power, idle, state;
    for (kind = 0; kind < 6; kind++) {
        capture_setup(0, ST_FLAT, 0, MO_COUNT);
        if (kind == 0) ui.menu = 0;
        if (kind == 1) song.playing = 1;
        if (kind == 2) ui.menu = 3;
        if (kind == 3) scrn.st = SCR_OFF;
        if (kind == 4) fm1_in.buttons = 1;
        if (kind == 5) fm1_in.notes = 1;
        power = host_pw_n; idle = scrn.idle; state = scrn.st;
        scap_input_time = scrn.idle; capture_need(scap_begin(fm1_ms), "begin unsupported scene without side effects");
        ui_draw(); lcd_sync();
        capture_need(scap.state == (kind == 3 ? SCAP_ASLEEP : SCAP_UNSUPPORTED), "HOME playback INFO held controls and sleep rejected");
        capture_need(host_pw_n == power && scrn.idle == idle && scrn.st == state && song.playing == (kind == 1),
                     "unsupported capture neither wakes nor pauses music nor resets inactivity");
    }
    capture_setup(0, ST_FLAT, 0, MO_IDLE); scap_input_time = scrn.idle;
    capture_need(scap_begin(fm1_ms), "begin input invalidation"); capture_frame();
    scrn.idle++; scap_scene_check();
    capture_need(scap.state == SCAP_CHANGED, "new input invalidates READY band before a host read");
    capture_setup(0, ST_FLAT, 0, MO_IDLE); scap_input_time = scrn.idle;
    capture_need(scap_begin(fm1_ms), "begin sleeping invalidation"); capture_frame();
    scrn.st = SCR_OFF; scap_scene_check();
    capture_need(scap.state == SCAP_ASLEEP, "display sleeping invalidates READY band before a host read");
    capture_setup(0, ST_FLAT, 0, MO_IDLE); scap_input_time = scrn.idle;
    capture_need(scap_begin(fm1_ms), "begin menu-change invalidation"); capture_frame();
    capture_need(scap_next(scap.token, SCAP_BYTES), "advance before selection changes"); menu_off_sel = MO_MODE;
    capture_frame(); capture_need(scap.state == SCAP_CHANGED, "menu change across bands rejects mixed image");
    host_lcd_async = 0;
}
static void test_last_band_status(void)
{
    static const char *const cases[] = {
        "transport starts while WAKE PANEL keeps input timestamp unchanged",
        "count-in starts", "physical button held", "physical note held", "confirmation opens",
        "layer opens", "update overlay opens", "MENU closes", "live INFO opens", "NAME opens",
        "display sleeps", "input generation changes"
    };
    uint32_t completed, kind, offset, token, idle, power, expected;
    uint8_t saved_ui[sizeof ui], saved_scrn[sizeof scrn], saved_settings[sizeof settings];
    uint8_t saved_dev[sizeof settings_dev], saved_prefs2, saved_scr;
    /* Exercise the actual 30 renders, then the same pure check used by console
     * READ/NEXT/STATUS. Last-band READY and final COMPLETE are both race windows. */
    for (completed = 0; completed < 2u; completed++)
        for (kind = 0; kind < NELEM(cases); kind++) {
            capture_setup(0, ST_FLAT, 0, MO_IDLE);
            capture_need(menu_try_put(MI_SCRWAKE, 1), "select PANEL-only wake for transport regression");
            scap_input_time = scrn.idle; idle = scrn.idle;
            capture_need(scap_begin(fm1_ms), "begin last-band status scenario"); token = scap.token;
            for (offset = 0; offset < 240u * 240u * 2u; offset += SCAP_BYTES) {
                capture_frame(); capture_need(scap.state == SCAP_READY, "last-band setup remains a coherent real menu");
                if (completed || offset + SCAP_BYTES < 240u * 240u * 2u)
                    capture_need(scap_next(token, offset + SCAP_BYTES), "advance to final status boundary");
            }
            capture_need(scap.state == (completed ? SCAP_COMPLETE : SCAP_READY), "reach actual final READY or COMPLETE boundary");
            scap_scene_check();
            capture_need(scap.state == (completed ? SCAP_COMPLETE : SCAP_READY), "unchanged final status remains valid");
            switch (kind) {
            case 0: seq_start(); break;
            case 1: cin_left = cin_total = 4; break;
            case 2: fm1_in.buttons = 1; break;
            case 3: fm1_in.notes = 1; break;
            case 4: ui.confirm = 1; break;
            case 5: ui.layer = 1; break;
            case 6: ui.uboot = 1; break;
            case 7: ui.menu = 0; break;
            case 8: ui.menu = 3; break;
            case 9: nm.kind = NK_USER_SAVE; break;
            case 10: scrn.st = SCR_OFF; break;
            case 11: scrn.idle++; break;
            }
            capture_need(kind == 11 || scrn.idle == idle, "late eligibility changes need not generate an input timestamp");
            memcpy(saved_ui, &ui, sizeof ui); memcpy(saved_scrn, &scrn, sizeof scrn);
            memcpy(saved_settings, &settings, sizeof settings); memcpy(saved_dev, settings_dev, sizeof saved_dev);
            saved_prefs2 = ui_prefs2; saved_scr = ui_scr; power = host_pw_n;
            scap_scene_check();
            expected = kind == 10 ? SCAP_ASLEEP : kind == 11 ? SCAP_CHANGED : SCAP_UNSUPPORTED;
            capture_need(scap.state == expected, cases[kind]);
            capture_need(!memcmp(saved_ui, &ui, sizeof ui) && !memcmp(saved_scrn, &scrn, sizeof scrn) &&
                         !memcmp(saved_settings, &settings, sizeof settings) && !memcmp(saved_dev, settings_dev, sizeof saved_dev) &&
                         ui_prefs2 == saved_prefs2 && ui_scr == saved_scr && power == host_pw_n &&
                         song.playing == (kind == 0) && seq_counting() == (kind == 1),
                         "status rejection neither wakes, stops transport, changes timers/settings nor navigates");
            capture_need(!scap_next(token, 240u * 240u * 2u) && scap.state == expected,
                         "invalidated last band cannot acknowledge completion");
            song.playing = 0; cin_left = 0; fm1_in.buttons = fm1_in.notes = 0;
            ui.confirm = ui.layer = ui.uboot = 0; ui.menu = MENU_OFF; nm.kind = NK_NONE;
            scrn.st = SCR_ON; scrn.idle = idle; scap_scene_check();
            capture_need(scap.state == expected, "returning to eligible scene cannot revive invalidated final capture");
        }
    host_lcd_async = 0;
}
int main(void)
{
    test_menu_matrix(); test_rejections(); test_last_band_status();
    printf("PASS screen capture UI: %u scenes, %u complete render bands, %u checks; real menu bytes/coherence and safe rejections\n",
           capture_scenes, capture_frames, capture_checks);
    return 0;
}
