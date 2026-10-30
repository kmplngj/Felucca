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
static uint32_t padled_hold_until;
static void padled_set(uint32_t p, uint8_t r, uint8_t g, uint8_t b) { (void)p; (void)r; (void)g; (void)b; }
static int32_t outer_event = -1;
static int32_t outer_take(void) { int32_t e = outer_event; outer_event = -1; return e; }
#define HOST_SMK_EXTKEY_TAKE() outer_take()
#include "ui_harness.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); return 1; } } while (0)
static void reset_smk(void)
{
    ui_power_on(); kb_boot_hold = 0; smk_fbank = smk_fbank_new = 0;
    host_pressed = host_notes = 0;
    smk_extkeys_held = smk_extkeys_pressed = smk_extkeys_asleep = 0;
    outer_event = -1;
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
int main(void)
{
    uint32_t role, label, id;
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
