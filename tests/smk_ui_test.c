/* SPDX-License-Identifier: GPL-3.0-only */
/* Production UI input/calibration with the existing display and input adapters. */
#include <stdint.h>
#define BOARD_SMK37 1
#define FM1_NBTN 18u
#define FM1_NENC 8u
#define SMK_ENC_MASTER 0u
#define SMK_NLED 19u
#define SMK_NPAD 16u
enum { SMK_BTN_KNOB_BANK, SMK_BTN_FADER_BANK, SMK_BTN_LEFT, SMK_BTN_RIGHT };
static const uint8_t SMK_WHITE_NOTE[SMK_NPAD] = {0,2,4,6,7,9,11,12,14,16,18,19,21,23,24,26};
#define SMK_PAD_OF_WHITE(w) (w)
/* Use the existing actual-driver fault model for sleep/recovery as well. */
#define UI_LCD_SOURCE "lcd_fault_model.h"
static void fm1_padled_send(const void *p, uint32_t n);
static void fm1_padled_done(void);
static int32_t outer_event = -1;
static int32_t outer_take(void) { int32_t e = outer_event; outer_event = -1; return e; }
#define HOST_SMK_EXTKEY_TAKE() outer_take()
#include "ui_harness.h"
#define host_pad_rgb padled_rgb
static void fm1_padled_send(const void *p, uint32_t n)
{
    lcd_model_submit(3);
    lcd_model_src = p; lcd_model_n = n; memcpy(lcd_model_copy, p, n);
}
static void fm1_padled_done(void)
{
    lcd_model_need(!lcd_model_pending, "LED route restored only after completion");
}
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); return 1; } } while (0)
static void reset_smk(void)
{
    lcd_sync();
    lcd_model_need(!lcd_fault && !lcd_busy, "reset cannot abandon a failed DMA");
    lcd_initialized = 1;
    ui_power_on(); kb_boot_hold = 0; smk_fbank = smk_fbank_new = 0;
    host_pressed = host_notes = 0;
    smk_extkeys_held = smk_extkeys_pressed = smk_extkeys_asleep = 0;
    outer_event = -1; padled_hold_until = 0; memset(host_pad_rgb, 0, sizeof host_pad_rgb);
    memset(host_enc, 0, sizeof host_enc); memset(host_enc_late, 0, sizeof host_enc_late);
}
static void raw_press(uint32_t id)
{
    fm1_in.buttons = 1u << id; host_pressed = 1u << id; ui_input();
}
static uint32_t calibration_calls;
static void calibration_input(void)
{
    uint32_t step = calibration_calls++;
    fm1_ms++;
    if (step < NB) host_pressed = 1u << PANEL_DEFAULT.btn[step];
    else if (step == NB) host_enc[SMK_ENC_MASTER] = 1;   /* reserved K1 must not complete SELECT */
    else if (step <= NB + NE) host_enc[step - NB] = 1;
    else fm1_in.notes = 1;                           /* a broken loop cancels instead of hanging */
}
static int auto_off_leds(void)
{
    uint32_t role, bank, menu, playing, recording, i;
    reset_smk(); host_anim = host_idle = 0; fm1_ms = 1000; CHECK(scr_write(1, 1, 2));
    smk_fbank = 3; ui.menu = 1; fm1_ms += 300000; ui_leds();
    if (fm1_led[SMK_BTN_FADER_BANK] || fm1_led[SMK_BTN_KNOB_BANK]) {
        fprintf(stderr, "auto-off bank LEDs: FADER=%u KNOB=%u; both must be zero\n",
                fm1_led[SMK_BTN_FADER_BANK], fm1_led[SMK_BTN_KNOB_BANK]); return 1;
    }
    for (role = 0; role < 3; role++) for (bank = 0; bank < 4; bank++)
        for (menu = 0; menu < 2; menu++) for (playing = 0; playing < 2; playing++)
            for (recording = 0; recording < 2; recording++) {
                uint32_t expected = role == 1 ? playing : role == 2 ? recording : bank != 0;
                reset_smk(); host_anim = host_idle = 0; settings_leds = LEDS_DIM;
                if (role) panel.btn[role == 1 ? B_PLAY : B_REC] = SMK_BTN_FADER_BANK;
                panel_init(); ui.menu = (uint8_t)menu;
                song.playing = (uint8_t)playing; song.rec = (uint8_t)recording; smk_fbank = (uint8_t)bank;
                fm1_ms = 1000; CHECK(scr_write(1, 1, 2));  /* LEDS 5 MIN; ALL DARK 15 MIN */
                ui_leds();
                CHECK(fm1_led[SMK_BTN_FADER_BANK] == expected && fm1_led[SMK_BTN_KNOB_BANK] == menu);
                fm1_ms += 300000;
                padled_hold_until = fm1_ms + 20000;       /* AUTO OFF must override the diagnostic pad hold */
                for (i = 0; i < SMK_NPAD; i++) host_pad_rgb[i] = 0x123456;
                ui_leds();
                for (i = 0; i < SMK_NLED; i++) if (fm1_led[i]) {
                    fprintf(stderr, "auto-off LED %u stayed on: role=%u bank=%u menu=%u playing=%u rec=%u\n",
                            i, role, bank, menu, playing, recording); return 1;
                }
                for (i = 0; i < SMK_NPAD; i++) CHECK(!host_pad_rgb[i]);
                scr_touch(); ui_leds();                  /* wake restores normal indicators */
                CHECK(fm1_led[SMK_BTN_FADER_BANK] == expected && fm1_led[SMK_BTN_KNOB_BANK] == menu);
            }
    /* The ordinary low-level heartbeat survives; ALL DARK suppresses it even
     * on an otherwise eligible 30-second boundary and during pad diagnostics. */
    reset_smk(); host_anim = host_idle = 0; fm1_ms = 1000; CHECK(scr_write(1, 1, 2));
    fm1_ms += 330000; padled_hold_until = fm1_ms + 20000; ui_leds();
    CHECK(host_pad_rgb[SMK_PAD_OF_WHITE(0)] != 0);
    for (i = 1; i < SMK_NPAD; i++) CHECK(!host_pad_rgb[SMK_PAD_OF_WHITE(i)]);
    fm1_ms = scrn.idle + 900000; padled_hold_until = fm1_ms + 20000; ui_leds();
    for (i = 0; i < SMK_NPAD; i++) CHECK(!host_pad_rgb[i]);
    for (i = 0; i < SMK_NLED; i++) CHECK(!fm1_led[i]);
    scr_touch();
    for (i = 0; i < SMK_NPAD; i++) host_pad_rgb[i] = 0x123456;
    ui_leds();                                           /* awake padtest still owns the pad colours */
    for (i = 0; i < SMK_NPAD; i++) CHECK(host_pad_rgb[i] == 0x123456);
    return 0;
}
static void recover_display(void)
{
    lcd_model_fail_cmd = 0; lcd_model_release = 1;
    fm1_ms++; ui_draw();
    fm1_ms += 250u; ui_draw();
    fm1_ms += 120u; ui_draw();
    fm1_ms += 120u; ui_draw(); lcd_sync();
}
static int failed_display_outer_keys(void)
{
    uint32_t path;
    for (path = 0; path < 2u; path++) {
        reset_smk(); fm1_ms = 1000u; CHECK(scr_write(1, 0, 0));
        fm1_ms += 300000u;
        CHECK(!scr_frame() && scrn.st == SCR_OFF && kb_asleep && smk_extkeys_asleep);
        outer_event = 0x8000 | 100; /* an already queued wake gesture, retained across failure */
        smk_extkeys_pressed = 1; CHECK(scr_input(0, 0));
        CHECK(scrn.st == SCR_WAKE);
        lcd_model_fail_cmd = 0x11; fm1_ms += 120u;
        CHECK(!scr_frame() && lcd_fault && lcd_busy); /* genuine SLPOUT wait timeout */
        if (path) ui_draw(); else CHECK(!scr_input(0, 0));
        CHECK(!scrn.eat && !kb_asleep && !smk_extkeys_asleep);
        CHECK(outer_event == (0x8000 | 100)); /* neither failure path flushes queued markers */
        events_block(CTL); CHECK(!ext_note[0]);
        outer_event = 0; events_block(CTL);
        outer_event = (smk_extkeys_asleep ? 0x8000 : 0) | 100;
        events_block(CTL); CHECK(ext_note[0]); /* future outer presses play despite failed LCD */
        outer_event = 0; events_block(CTL); CHECK(!ext_note[0]);
        recover_display();
        CHECK(!lcd_fault && scrn.st == SCR_ON && !scrn.recovering);
        CHECK(!scr_input(0, 0) && !smk_extkeys_asleep); /* SCR_ON early return cannot retain mute */
        outer_event = (smk_extkeys_asleep ? 0x8000 : 0) | 100;
        events_block(CTL); CHECK(ext_note[0]);
        outer_event = 0; events_block(CTL); CHECK(!ext_note[0]);
    }
    reset_smk(); scrn.recovering = 1;
    scrn.eat = kb_asleep = smk_extkeys_asleep = 1;
    CHECK(!scr_input(0, 0) && !smk_extkeys_asleep); /* healthy transport, redraw still recovering */
    scrn.recovering = 0;
    /* A display failure must not release splash suppression or rewrite a
     * wake/boot-only press already retained for the audio consumer. */
    reset_smk(); kb_boot_hold = smk_extkeys_asleep = 1;
    outer_event = 0x8000 | 100;
    lcd_model_fail_cmd = 0x11; lcd_power(1); CHECK(lcd_fault);
    ui_draw(); CHECK(kb_boot_hold && smk_extkeys_asleep && outer_event == (0x8000 | 100));
    ui_input(); CHECK(!kb_boot_hold && !smk_extkeys_asleep);
    events_block(CTL); CHECK(!ext_note[0]);
    recover_display(); CHECK(!lcd_fault && !lcd_busy);
    return 0;
}
int main(void)
{
    uint32_t role, label, id;
    CHECK(failed_display_outer_keys() == 0);
    CHECK(auto_off_leds() == 0);
    reset_smk(); panel_init();
    CHECK(sizeof(panel_t) == 32 && !memcmp(&panel, &PANEL_DEFAULT, sizeof panel));
    /* The spare bank indicator owns id 1 only while calibration leaves it free. */
    for (role = 0; role < 3; role++) {
        uint32_t bank, playing, recording;
        reset_smk(); host_anim = host_idle = 0; settings_leds = LEDS_DIM;
        if (role) panel.btn[role == 1 ? B_PLAY : B_REC] = SMK_BTN_FADER_BANK;
        panel_init();
        for (bank = 0; bank < 4; bank++) for (playing = 0; playing < 2; playing++)
            for (recording = 0; recording < 2; recording++) {
                uint32_t expected = role == 1 ? playing : role == 2 ? recording : bank != 0;
                smk_fbank = (uint8_t)bank; song.playing = (uint8_t)playing; song.rec = (uint8_t)recording;
                ui_leds();
                if (fm1_led[SMK_BTN_FADER_BANK] != expected) {
                    fprintf(stderr, "id1 LED role=%s bank=%u playing=%u rec=%u: got %u expected %u\n",
                            role == 1 ? "PLAY" : role == 2 ? "REC" : "FADER BANK", bank, playing, recording,
                            fm1_led[SMK_BTN_FADER_BANK], expected);
                    return 1;
                }
            }
    }
    reset_smk();
    /* A live free FADER BANK press acts exactly once; release and idle do nothing. */
    raw_press(SMK_BTN_FADER_BANK); CHECK(smk_fbank == 1 && smk_fbank_new);
    fm1_in.buttons = 0; ui_input(); ui_input(); CHECK(smk_fbank == 1);
    /* Splash dismissal and wake presses are consumed before any bank side effect. */
    reset_smk(); kb_boot_hold = 1; raw_press(SMK_BTN_FADER_BANK);
    CHECK(smk_fbank == 0 && !smk_fbank_new && kb_boot_hold);
    fm1_in.buttons = 0; ui_input(); CHECK(!kb_boot_hold && smk_fbank == 0);
    reset_smk(); scrn.st = SCR_OFF; raw_press(SMK_BTN_FADER_BANK);
    CHECK(smk_fbank == 0 && !smk_fbank_new && scrn.st != SCR_OFF);
    /* Calibration owns reassigned physical id 1: ENV opens, bank stays unchanged. */
    reset_smk(); panel.btn[B_ENV] = SMK_BTN_FADER_BANK; panel_init();
    raw_press(SMK_BTN_FADER_BANK); fm1_in.buttons = 0; ui_input();
    CHECK(!ui.home && cur_page()->fam == FAM_ENV && !smk_fbank && !smk_fbank_new);
    /* Every page role works on both physical ids above the old 16-bit mask. */
    for (label = 0; label < 3; label++) for (id = 16; id <= 17; id++) {
        static const uint8_t roles[3] = {B_ENV, B_LFO, B_ARP};
        static const uint8_t families[3] = {FAM_ENV, FAM_LFO, FAM_ARP};
        uint8_t old;
        reset_smk(); old = panel.btn[roles[label]];
        panel.btn[id == 16 ? B_PLAY : B_REC] = old; panel.btn[roles[label]] = id; panel_init();
        raw_press(id); CHECK(ui.home && (ui.pg_down & (1u << id)));
        ui_input(); CHECK(ui.home && (ui.pg_down & (1u << id)));
        fm1_in.buttons = 0; ui_input();
        CHECK(!ui.home && cur_page()->fam == families[label] && !ui.pg_down);
    }
    /* A momentary LFO turn consumes only LFO, preserving another high page bit. */
    reset_smk(); panel.btn[B_ENV] = 16; panel.btn[B_PLAY] = 9; panel.btn[B_LFO] = 17; panel.btn[B_REC] = 7;
    panel_init(); fm1_in.buttons = (1u << 16) | (1u << 17); host_pressed = fm1_in.buttons; ui_input();
    CHECK(ui.pg_down == ((1u << 16) | (1u << 17)));
    host_enc[panel.enc[EN_K1]] = 1; ui_input();
    CHECK(ui.pg_down == (1u << 16));
    fm1_in.buttons = 0; ui_input(); CHECK(!ui.home && cur_page()->fam == FAM_ENV);
    /* Saved mappings may never give MASTER to any ordinary encoder role. */
    for (role = 0; role < NE; role++) {
        reset_smk(); panel.enc[role] = SMK_ENC_MASTER; panel_init();
        CHECK(!memcmp(&panel, &PANEL_DEFAULT, sizeof panel));
    }
    reset_smk(); calibration_calls = 0; host_wdt_hook = calibration_input; panel_setup(); host_wdt_hook = 0;
    CHECK(calibration_calls == NB + NE + 1 && panel.magic == PANEL_MAGIC);
    for (role = 0; role < NE; role++) CHECK(panel.enc[role] == role + 1 && panel.dir[role] == 1);
    host_enc[SMK_ENC_MASTER] = 3; CHECK(panel_enc(EN_SELECT) == 0 && fm1_enc_take(SMK_ENC_MASTER) == 3);
    host_enc[panel.enc[EN_K4]] = 2; CHECK(panel_enc(EN_K4) == 2);
    /* Splash dismissal also waits for the outer keys, consuming old queued
     * presses even if audio processes them after main releases the boot gate. */
    reset_smk(); kb_boot_hold = smk_extkeys_asleep = 1; smk_extkeys_held = 1;
    ui_input(); CHECK(kb_boot_hold && smk_extkeys_asleep);
    smk_extkeys_held = 0; ui_input(); CHECK(!kb_boot_hold && !smk_extkeys_asleep);
    outer_event = 0x8000 | 100; events_block(CTL); CHECK(!ext_note[0]);
    /* Outer keys keep both timers alive, wake in PANEL mode, and the wake
     * gesture remains consumed until every outer key is released. */
    reset_smk(); fm1_ms = 400000; scrn.idle = 0;
    smk_extkeys_held = smk_extkeys_pressed = 1; ui_input();
    CHECK(scrn.idle == fm1_ms && !smk_extkeys_pressed);
    fm1_ms += 400000; ui_input(); CHECK(scrn.idle == fm1_ms);
    smk_extkeys_held = 0; smk_extkeys_pressed = 2; fm1_ms++; ui_input();
    CHECK(scrn.idle == fm1_ms); /* short press/release between main-loop polls */
    reset_smk(); ui_prefs2 |= PREF_WAKE_PANEL >> 16;
    scrn.st = SCR_OFF; scrn.eat = kb_asleep = smk_extkeys_asleep = 1;
    fm1_ms = 1000; smk_extkeys_held = smk_extkeys_pressed = 1;
    outer_event = 0x8000 | (0 << 8) | 100; events_block(CTL); ui_input();
    CHECK(scrn.st == SCR_WAKE && kb_asleep && !ext_note[0]);
    scrn.st = SCR_ON; fm1_ms += 1000; ui_input();
    CHECK(kb_asleep && smk_extkeys_asleep); /* held across completed wake */
    smk_extkeys_held = 0; ui_input();
    CHECK(!kb_asleep && !smk_extkeys_asleep);
    /* Even if audio consumes the old queue only after waking, no stale press
     * may sound; a fresh post-release press is playable and releases normally. */
    outer_event = 0x8000 | (0 << 8) | 100; events_block(CTL); CHECK(!ext_note[0]);
    outer_event = (0 << 8); events_block(CTL); CHECK(!ext_note[0]);
    outer_event = (0 << 8) | 100; events_block(CTL); CHECK(ext_note[0]);
    outer_event = 0; events_block(CTL); CHECK(!ext_note[0]);
    puts("SMK UI consumed/reassigned bank presses, 18-bit page releases and reserved MASTER calibration passed");
    return 0;
}
