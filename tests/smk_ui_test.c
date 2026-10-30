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
#include "ui_harness.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); return 1; } } while (0)
static void reset_smk(void)
{
    ui_power_on(); kb_boot_hold = 0; smk_fbank = smk_fbank_new = 0;
    host_pressed = host_notes = 0;
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
    puts("SMK UI consumed/reassigned bank presses, 18-bit page releases and reserved MASTER calibration passed");
    return 0;
}
