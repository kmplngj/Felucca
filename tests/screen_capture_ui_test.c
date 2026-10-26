/* SPDX-License-Identifier: GPL-3.0-only */
/* Real native UI and capture service; host_screen is an independent LCD sink. */
#define FELUCCA_SCREEN_CAPTURE 1
#include "ui_harness.h"

static uint32_t capture_checks, capture_frames, capture_scenes, capture_dynamic, capture_advance_ms;
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
    capture_advance_ms = 0;
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
static void capture_home_setup(uint32_t palette, uint32_t style, uint32_t large, uint32_t view)
{
    capture_setup(palette, style, large, MO_COUNT);
    ui.home = 1; ui.menu = 0; ui_home_view = (uint8_t)view;
    ui_prefs &= (uint8_t)~PREF_ANIM_OFF; ui_prefs2 = 0; /* default animation policy */
    ui.msg_t = ui.hot_t = ui.help_t = ui.bpm_t = 0;
    song.master_q12 = 4096;
    memset(scope_buf, 0, sizeof scope_buf); scope_w = 0; scope_mix = 0;
    memset(midi_lit_ms, 0, sizeof midi_lit_ms);
    ui.force = 1; ui_draw(); lcd_sync();
    capture_advance_ms = 15;
}
static void capture_frame(void)
{
    fm1_ms += capture_advance_ms;
    ui_draw(); capture_frames++;
    capture_need(!host_dma.p && !host_dma_bad, "READY frame drains delayed DMA without reusing its source");
}
static void capture_scene(void)
{
    uint32_t offset, token, hash = 0, menu = ui.menu, sel = ui.menu_sel, row = menu_off_sel, home = ui.home, view = ui_home_view;
    uint32_t idle = scrn.idle, power = host_pw_n, hot = ui.hot_t, msg = ui.msg_t, bpm = ui.bpm_t, help = ui.help_t;
    uint8_t saved[sizeof settings_dev], saved_scr = ui_scr, saved_prefs = ui_prefs;
    uint8_t saved_settings[sizeof settings], saved_prefs2 = ui_prefs2;
    uint8_t saved_style = ui_style;
    memcpy(saved, settings_dev, sizeof saved);
    memcpy(saved_settings, &settings, sizeof settings);
    scap_input_time = scrn.idle;
    capture_need(scap_begin(fm1_ms), "start UI capture"); token = scap.token;
    for (offset = 0; offset < 240u * 240u * 2u; offset += SCAP_BYTES) {
        capture_frame();
        capture_need(scap.state == SCAP_READY && scap.covered == 1920u, "actual page forces full coverage of every band");
        capture_need(!memcmp(scap.pixels, (const uint8_t *)host_screen + offset, SCAP_BYTES), "band bytes equal actual completed LCD sink");
        if (!offset) hash = scap.draw_hash;
        capture_need(scap.draw_hash == hash, "real static page stream is coherent for all 30 bands");
        capture_need(scap_next(token, offset + SCAP_BYTES), "advance UI capture");
    }
    capture_need(scap.state == SCAP_COMPLETE, "page capture completes");
    capture_need(ui.menu == menu && ui.menu_sel == sel && menu_off_sel == row && ui.home == home && ui_home_view == view && scrn.idle == idle &&
                 host_pw_n == power && !song.playing && !memcmp(saved, settings_dev, sizeof saved) &&
                 !memcmp(saved_settings, &settings, sizeof settings) && ui_prefs2 == saved_prefs2 &&
                 ui_scr == saved_scr && ui_prefs == saved_prefs && ui_style == saved_style &&
                 hot == ui.hot_t && msg == ui.msg_t && bpm == ui.bpm_t && help == ui.help_t,
                 "capture preserves navigation, settings, inactivity and unrelated UI timers");
    capture_scenes++;
}
static void test_home_matrix(void)
{
    uint32_t palette, style, large, view;
    for (palette = 0; palette <= NPALETTES; palette++)
        for (style = ST_FLAT; style <= ST_LINE; style++)
            for (large = 0; large < 2; large++)
                for (view = 0; view < HV_COUNT; view++) {
                    capture_home_setup(palette, style, large, view); capture_scene();
                }
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
        if (kind == 0) ui.menu = ui.home = 0;
        if (kind == 1) song.playing = 1;
        if (kind == 2) ui.menu = 3;
        if (kind == 3) scrn.st = SCR_OFF;
        if (kind == 4) fm1_in.buttons = 1;
        if (kind == 5) fm1_in.notes = 1;
        power = host_pw_n; idle = scrn.idle; state = scrn.st;
        scap_input_time = scrn.idle; capture_need(scap_begin(fm1_ms), "begin unsupported scene without side effects");
        ui_draw(); lcd_sync();
        capture_need(scap.state == (kind == 3 ? SCAP_ASLEEP : SCAP_UNSUPPORTED), "nonHOME page playback INFO held controls and sleep rejected");
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
static void test_home_rejections(void)
{
    uint32_t kind, idle, power;
    for (kind = 0; kind < 10; kind++) {
        capture_home_setup(0, ST_FLAT, 0, HV_SCOPE);
        switch (kind) {
        case 0: song.playing = 1; break;
        case 1: cin_left = cin_total = 4; break;
        case 2: fm1_in.buttons = 1; break;
        case 3: fm1_in.notes = 1; break;
        case 4: ui.confirm = 1; break;
        case 5: ui.layer = 1; break;
        case 6: ui.uboot = 1; break;
        case 7: ui.home = 0; break;
        case 8: ui.menu = 3; break;
        case 9: nm.kind = NK_USER_SAVE; break;
        }
        idle = scrn.idle; power = host_pw_n; scap_input_time = idle;
        capture_need(scap_begin(fm1_ms), "begin unsupported HOME scenario");
        ui_draw(); lcd_sync();
        capture_need(scap.state == SCAP_UNSUPPORTED && scrn.idle == idle && host_pw_n == power &&
                     song.playing == (kind == 0) && seq_counting() == (kind == 1),
                     "HOME rejects playback/count-in/controls/overlays without stopping transport or waking");
    }
}
static void test_last_band_status(void)
{
    static const char *const cases[] = {
        "transport starts while WAKE PANEL keeps input timestamp unchanged",
        "count-in starts", "physical button held", "physical note held", "confirmation opens",
        "layer opens", "update overlay opens", "nonHOME page opens", "live INFO opens", "NAME opens",
        "display sleeps", "input generation changes"
    };
    uint32_t home, completed, kind, offset, token, idle, power, expected;
    uint8_t saved_ui[sizeof ui], saved_scrn[sizeof scrn], saved_settings[sizeof settings];
    uint8_t saved_dev[sizeof settings_dev], saved_prefs2, saved_scr;
    /* Exercise the actual 30 renders, then the same pure check used by console
     * READ/NEXT/STATUS. Last-band READY and final COMPLETE are both race windows. */
    for (home = 0; home < 2u; home++)
      for (completed = 0; completed < 2u; completed++)
        for (kind = 0; kind < NELEM(cases); kind++) {
            if (home) capture_home_setup(0, ST_FLAT, 0, HV_SCOPE);
            else capture_setup(0, ST_FLAT, 0, MO_IDLE);
            capture_need(menu_try_put(MI_SCRWAKE, 1), "select PANEL-only wake for transport regression");
            scap_input_time = scrn.idle; idle = scrn.idle;
            capture_need(scap_begin(fm1_ms), "begin last-band status scenario"); token = scap.token;
            for (offset = 0; offset < 240u * 240u * 2u; offset += SCAP_BYTES) {
                capture_frame(); capture_need(scap.state == SCAP_READY, "last-band setup remains a coherent real page");
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
            case 7: ui.menu = ui.home = 0; break;
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
enum { HC_HELD, HC_TAIL, HC_MIDI, HC_HOT, HC_MESSAGE, HC_HELP, HC_BPM, HC_REC, HC_SCOPE, HC_COUNT };
static uint32_t capture_audio_tick(void)
{
    int32_t out[CTL * 2u];
    uint32_t block, i, nonzero = 0;
    for (block = 0; block < 21; block++) {
        mix_block(out, CTL);
        for (i = 0; i < CTL; i++) nonzero += out[2u * i] != 0;
        /* audio.c's OUT-scope publication, following the real DSP mix. */
        for (i = 1; i < CTL; i += 2u)
            scope_buf[scope_w++ & (SCOPE_N - 1u)] = (int16_t)out[2u * i];
    }
    return nonzero;
}
static void capture_home_dynamic(uint32_t mode, uint32_t view, uint32_t large)
{
    uint32_t band, i, token, idle, nonzero = 0, expected;
    capture_home_setup(0, ST_FLAT, large, view);
    if (mode == HC_HELD || mode == HC_TAIL) {
        host_preset(&trk[0], 0, 0); /* ANALOG, a real voice without a held physical key */
        trk_note_on(&trk[0], 60, 100);
        nonzero += capture_audio_tick(); nonzero += capture_audio_tick();
        if (mode == HC_TAIL) trk_note_off(&trk[0], 60);
    }
    if (mode == HC_MIDI) midi_lit_ms[0] = fm1_ms | 1u;
    if (mode == HC_HOT) ui.hot_t = 4;
    if (mode == HC_MESSAGE) { ui.msg_t = 4; str_cpy(ui.msg, "PROBE", sizeof ui.msg); }
    if (mode == HC_HELP) ui.help_t = 4;
    if (mode == HC_BPM) ui.bpm_t = 4;
    if (mode == HC_REC) song.rec = 1;
    idle = scrn.idle; scap_input_time = idle;
    capture_need(scap_begin(fm1_ms), "begin timed HOME audio/indicator scenario"); token = scap.token;
    for (band = 0; band < 30; band++) {
        if (mode == HC_HELD || mode == HC_TAIL) nonzero += capture_audio_tick();
        if (mode == HC_SCOPE) {
            for (i = 0; i < SCOPE_N; i++)
                scope_buf[i] = (int16_t)((int32_t)((i * (band + 11u)) % 79u) * 400 - 15000);
            scope_w += 32;
        }
        capture_frame();
        capture_need(scap.covered == 1920u, "dynamic HOME still covers the complete current band");
        if (scap.state != SCAP_READY) break;
        capture_need(!memcmp(scap.pixels, (uint8_t *)host_screen + scap.offset, SCAP_BYTES), "dynamic READY band matches completed LCD bytes");
        capture_need(scap_next(token, scap.offset + SCAP_BYTES), "acknowledge dynamic HOME band");
    }
    expected = mode == HC_REC || (mode == HC_SCOPE && view != HV_SCOPE) ? SCAP_COMPLETE : SCAP_CHANGED;
    capture_need(scap.state == expected && scrn.idle == idle && !song.playing && !fm1_in.notes,
                 "visible audio/timer changes abort; unchanged REC or invisible scope changes remain coherent");
    if (mode == HC_HELD || mode == HC_TAIL)
        capture_need(nonzero && busy_now() && band == 1u, "actual sounding held/released voice changes the second band without panel input");
}
static void test_home_dynamic(void)
{
    uint32_t mode, view, large, result[2];
    /* Each child starts with the same silent DSP state; no prior test's effect
     * tail can masquerade as the voice under test. Only host fixtures fork. */
    for (mode = 0; mode < HC_COUNT; mode++)
        for (view = 0; view < HV_COUNT; view++)
            for (large = 0; large < 2; large++) {
                int fd[2], status;
                pid_t pid;
                capture_need(!pipe(fd), "dynamic fixture result pipe");
                pid = fork(); capture_need(pid >= 0, "isolate dynamic audio fixture");
                if (!pid) {
                    uint32_t checks = capture_checks, frames = capture_frames;
                    close(fd[0]); capture_home_dynamic(mode, view, large);
                    result[0] = capture_checks - checks; result[1] = capture_frames - frames;
                    if (write(fd[1], result, sizeof result) != sizeof result) _exit(2);
                    close(fd[1]); _exit(0);
                }
                close(fd[1]);
                capture_need(read(fd[0], result, sizeof result) == sizeof result, "dynamic child returns validation counts");
                close(fd[0]); capture_need(waitpid(pid, &status, 0) == pid && WIFEXITED(status) && !WEXITSTATUS(status), "isolated HOME dynamic scenario passes");
                capture_checks += result[0]; capture_frames += result[1]; capture_dynamic++;
            }
}
static void test_explicit_wake(void)
{
    uint32_t view, token, power, idle, at, offset, home, menu;
    uint8_t saved_dev[sizeof settings_dev], saved_settings[sizeof settings];
    for (view = 0; view < 2u; view++) {
        if (view) capture_home_setup(0, ST_FLAT, 0, HV_SCOPE);
        else capture_setup(0, ST_FLAT, 0, MO_IDLE);
        home = ui.home; menu = ui.menu;
        capture_need(scr_mode_put(0) && scr_dark_put(2), "configure SCREEN5m and ALL DARK15m");
        ui_prefs2 |= PREF_WAKE_PANEL >> 16;       /* no MIDI wake required */
        fm1_ms = scrn.idle + 900000u;
        ui_draw(); lcd_sync();
        capture_need(scrn.st == SCR_OFF && scr_led_dark(), "real idle timeout sleeps display and LEDs");
        idle = scrn.idle; power = host_pw_n;
        capture_need(scap_start(0) && scap.state == SCAP_ASLEEP && scrn.idle == idle && host_pw_n == power,
                     "default capture still rejects sleep without side effects");
        memcpy(saved_dev, settings_dev, sizeof saved_dev); memcpy(saved_settings, &settings, sizeof settings);
        at = fm1_ms;
        capture_need(scap_start(1) && scap.state == SCAP_WAKING && scrn.st == SCR_WAKE,
                     "explicit silent wake enters nonblocking waking state");
        token = scap.token; idle = scrn.idle;
        capture_need(!scap_start(1) && scap.token == token && scrn.idle == idle,
                     "second wake cannot replace or prolong waking session");
        ui_draw(); lcd_sync();
        capture_need(scrn.st == SCR_WAKE && scap.state == SCAP_WAKING, "SLPIN settling remains asynchronous");
        fm1_ms = at + 119u; ui_draw(); lcd_sync();
        capture_need(scrn.st == SCR_WAKE, "SLPOUT cannot precede120ms since SLPIN");
        fm1_ms = at + 120u; ui_draw(); lcd_sync();
        capture_need(scrn.st == SCR_SLPOUT && scap.state == SCAP_WAKING && !scap.tapping,
                     "SLPOUT first; no screenshot before wake redraw");
        fm1_ms = at + 239u; ui_draw(); lcd_sync();
        capture_need(scap.state == SCAP_WAKING && scrn.st == SCR_SLPOUT, "wait full120ms without blocking");
        fm1_ms = at + 240u; ui_draw(); lcd_sync();
        capture_need(scrn.st == SCR_ON && scap.state == SCAP_PENDING && !scap.covered &&
                     scrn.idle == idle && !scr_led_dark(), "completed wake redraw precedes first captured band");
        capture_need(!scrn.eat && !kb_asleep, "explicit wake releases input latches before the next input pass");
        for (offset = 0; offset < SCAP_W * SCAP_H * 2u; offset += SCAP_BYTES) {
            capture_frame();
            capture_need(scap.state == SCAP_READY && !memcmp(scap.pixels, (uint8_t *)host_screen + offset, SCAP_BYTES),
                         "post-wake image matches completed real LCD bytes");
            capture_need(scap_next(token, offset + SCAP_BYTES), "advance wake capture");
        }
        capture_need(scap.state == SCAP_COMPLETE && scap_holding(fm1_ms) && !song.playing && !gates() &&
                     !memcmp(saved_dev, settings_dev, sizeof saved_dev) && !memcmp(saved_settings, &settings, sizeof settings) &&
                     ui.home == home && ui.menu == menu,
                     "silent capture retains view, settings and stopped transport through final verification");
        capture_need(scap_cancel(token) && !scap_holding(fm1_ms), "cancel releases wake hold");
        key_down(white(0));
        capture_need(gates() == 1u, "first physical key after capture plays before the next UI input pass");
        key_up(white(0));
    }
}
static void capture_wake_input(void)
{
    if (scrn.st == SCR_ON) {
        fm1_in.buttons = 1u;
        host_lcd_sync_hook = NULL;
    }
}
static void test_wake_release_and_rejection(void)
{
    uint32_t kind, token, idle, power, at;
    for (kind = 0; kind < 8u; kind++) {
        capture_setup(0, ST_FLAT, 0, MO_IDLE);
        scrn.st = SCR_OFF;
        if (kind == 0) song.playing = 1;
        if (kind == 1) cin_left = cin_total = 4;
        if (kind == 2) fm1_in.buttons = 1;
        if (kind == 3) fm1_in.notes = 1;
        if (kind == 4) ui.menu = 3;
        if (kind == 5) ui.menu = ui.home = 0;
        if (kind == 6) ui.confirm = 1;
        if (kind == 7) ui.layer = 1;
        idle = scrn.idle; power = host_pw_n;
        capture_need(scap_start(1) && scap.state == SCAP_UNSUPPORTED && !scap_holding(fm1_ms) &&
                     scrn.st == SCR_OFF && scrn.idle == idle && host_pw_n == power && song.playing == (kind == 0),
                     "explicit wake rejects unsafe scenes before changing power, idle or transport");
    }
    for (kind = 0; kind < 4u; kind++) {
        capture_setup(0, ST_FLAT, 0, MO_IDLE);
        capture_need(scr_mode_put(2) && scr_dark_put(2), "configure BOTH5m ALL DARK15m for hold");
        capture_need(scap_start(1), "begin wake lease"); token = scap.token; at = fm1_ms;
        /* Put AUTO OFF at its boundary independently of the short session TTL,
         * as if its idle clock predated the lease. No production timer writes. */
        scap_input_time = scrn.idle = fm1_ms - 900000u;
        capture_need(!scr_expired() && !scr_led_dark() && scr_frame() && scrn.st == SCR_ON,
                     "live explicit capture inhibits both idle stages without refreshing input generation");
        capture_need(scrn.idle == scap_input_time && scap.started == at, "hold does not renew idle or session timestamps");
        if (kind == 0) capture_need(scap_cancel(token), "cancel live hold");
        if (kind == 1) { fm1_ms += SCAP_TTL; scap_scene_check(); }
        if (kind == 2) { scrn.idle++; scap_scene_check(); }
        if (kind == 3) { song.playing = 1; scap_scene_check(); }
        capture_need(!scap_holding(fm1_ms) && scr_expired() && scr_led_dark(),
                     "cancel, expiry, input and unsupported scene release both AUTO OFF stages");
        capture_need(scap.started == at && song.playing == (kind == 3), "release neither extends lease nor stops transport");
    }
    capture_setup(0, ST_FLAT, 0, MO_IDLE); scrn.st = SCR_OFF;
    capture_need(scap_start(1), "start asynchronous wake for input race");
    scrn.idle++; scap_scene_check();
    capture_need(scap.state == SCAP_CHANGED && !scap_holding(fm1_ms), "input while waking invalidates before acquiring pixels");
    capture_setup(0, ST_FLAT, 0, MO_IDLE);
    scrn.st = SCR_OFF; scrn.eat = kb_asleep = 1; scrn.t = fm1_ms - 120u;
    capture_need(scap_start(1), "start final wake input race");
    ui_draw(); lcd_sync(); fm1_ms += 120u;
    host_lcd_sync_hook = capture_wake_input;
    ui_draw(); lcd_sync();
    capture_need(scap.state == SCAP_UNSUPPORTED && !scap_holding(fm1_ms) && scrn.eat && kb_asleep,
                 "input arriving at wake completion aborts before clearing gesture suppression");
    fm1_in.buttons = 0;
}
static void test_wake_audio(void)
{
    uint32_t mode, result[2][2];
    /* Fork the same DSP state: one awake read-only capture, one sleeping explicit
     * wake. Both render the identical sounding voice and sample count. */
    for (mode = 0; mode < 2u; mode++) {
        int fd[2], status;
        pid_t pid;
        capture_need(!pipe(fd), "PCM comparison pipe");
        pid = fork(); capture_need(pid >= 0, "isolate identical DSP inputs");
        if (!pid) {
            uint32_t step, i, hash = 2166136261u, nonzero = 0;
            int32_t out[CTL * 2u];
            close(fd[0]);
            capture_setup(0, ST_FLAT, 0, MO_IDLE);
            song.master_q12 = 4096;
            host_preset(&trk[0], 0, 0); trk_note_on(&trk[0], 60, 100);
            if (mode) { scrn.st = SCR_OFF; scrn.t = fm1_ms; }
            capture_need(scap_start((uint8_t)mode), "begin PCM comparison capture");
            for (step = 0; step < 100u; step++) {
                fm1_ms += 15u; ui_draw(); lcd_sync();
                if (scap.state == SCAP_READY)
                    capture_need(scap_next(scap.token, scap.offset + SCAP_BYTES), "advance sounding MENU capture");
                mix_block(out, CTL);
                for (i = 0; i < CTL * 2u; i++) { hash = (hash ^ (uint32_t)out[i]) * 16777619u; nonzero += out[i] != 0; }
            }
            capture_need(scap.state == SCAP_COMPLETE && !song.playing && gates() == 1u,
                         "capture preserves existing voice and stopped transport");
            result[mode][0] = hash; result[mode][1] = nonzero;
            if (write(fd[1], result[mode], sizeof result[mode]) != sizeof result[mode]) _exit(2);
            close(fd[1]); _exit(0);
        }
        close(fd[1]);
        capture_need(read(fd[0], result[mode], sizeof result[mode]) == sizeof result[mode], "collect real DSP output hash");
        close(fd[0]);
        capture_need(waitpid(pid, &status, 0) == pid && WIFEXITED(status) && !WEXITSTATUS(status), "PCM comparison child passes");
    }
    capture_need(result[0][1] && !memcmp(result[0], result[1], sizeof result[0]),
                 "silent wake preserves sample-exact sounding PCM versus awake capture");
}
int main(void)
{
    test_menu_matrix(); test_home_matrix(); test_rejections(); test_home_rejections(); test_last_band_status(); test_home_dynamic(); test_explicit_wake(); test_wake_release_and_rejection(); test_wake_audio();
    printf("PASS screen capture UI: %u static scenes, %u dynamic scenarios, %u render bands, %u checks; MENU/HOME exact pixels, coherence and safe rejections\n",
           capture_scenes, capture_dynamic, capture_frames, capture_checks);
    return 0;
}
