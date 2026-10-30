/* SPDX-License-Identifier: GPL-3.0-only */
/* Drive production SMK matrix decoding without touching GPIO. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Stand-ins for the two architecture instructions; the real drain/guard
 * functions below still perform the saves, masking and exact restoration. */
static uint32_t test_icfg, irq_saves, irq_restores;
static uint32_t test_irq_save(void) { uint32_t f = test_icfg; test_icfg = 0; irq_saves++; return f; }
static void test_irq_restore(uint32_t f) { test_icfg = f; irq_restores++; }
#define SMK_INPUT_IRQ_SAVE() test_irq_save()
#define SMK_INPUT_IRQ_RESTORE(f) test_irq_restore(f)
#define BOARD_SMK37 1
#include "../firmware/hal/smk_input.h"
static void check(int ok, const char *message)
{
    if (!ok) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
}
static void contact(uint32_t code, uint32_t down)
{
    uint8_t bit = (uint8_t)(1u << (code & 15u));
    if (down) fm1_in.raw[code >> 4] |= bit;
    else fm1_in.raw[code >> 4] &= (uint8_t)~bit;
}
int main(void)
{
    uint32_t i, v;
    memset((void *)&fm1_in, 0, sizeof fm1_in);
    smk_trim_defaults();
    contact(SMK_KEYC[SMK_KEY_F3][0], 1);
    smk__keys(100u);
    check(fm1_in.notes == 0, "first key contact must not sound");
    contact(SMK_KEYC[SMK_KEY_F3][1], 1);
    smk__keys(100u + 1600u * FM1_TICKS_PER_US);
    v = fm1_in.key_vel[SMK_KEY_F3];
    check(fm1_in.notes == 1u && fm1_in.notes_pressed == 1u && v > 0u && v <= 127u,
          "F3 maps to note bit 0 with velocity and press edge");
    fm1_in.pnotes = 1u;
    contact(SMK_KEYC[SMK_KEY_F3][0], 0);
    contact(SMK_KEYC[SMK_KEY_F3][1], 0);
    for (i = 0; i < SMK_KEY_REL; i++) smk__keys(100000u);
    check(!fm1_in.knotes && fm1_in.notes == 1u, "key release preserves overlapping pad note");
    fm1_in.pnotes = 0;
    fm1_in.notes = 0;
    smk__padq(8, 73);
    check(fm1_in.pnotes == 1u && fm1_in.notes == 1u && fm1_in.key_vel[SMK_KEY_F3] == 73u,
          "bottom-left pad press publishes F3 with pad velocity");
    smk_pad_grid = 1;
    smk__padq(8, 0);
    check(!fm1_in.pnotes && !fm1_in.notes,
          "pad release ends original note after grid layout changes");
    smk_pad_grid = 0;
    smk__key_event(0, 88);
    check(smk_extq_w == 1u && smk_extq[0] == 88u && (fm1_in.keys & 1u),
          "outer C key emits its own event and all-key state");
    smk__key_event(36, 99);
    check(smk_extq[1] == (36u << 8 | 99u) && (fm1_in.keys & ((uint64_t)1u << 36)),
          "highest key is preserved beyond 32-bit central note mask");
    contact(SMK_BTNC[FM1_BTN_OCT_DOWN], 1);
    contact(SMK_BTNC[FM1_BTN_OCT_UP], 1);
    for (i = 0; i < SMK_DEB_PRESS; i++) smk__buttons();
    check((fm1_in.buttons & FM1_OCT_BOTH) == FM1_OCT_BOTH && (fm1_in.buttons & 3u) == 0u,
          "physical OCT pair is distinct from knob/fader bank buttons");
    check(SMK_WHITE_NOTE[SMK_WHITE_OF_PAD(8)] == 0u && SMK_PAD_OF_WHITE(0) == 8u,
          "bottom-left pad maps to lowest white note");
    for (i = 0; i < FM1_NENC; i++) fm1_in.enc_last[i] = 0xFF;
    smk__encoders();
    for (i = 0; i < 8u; i++) {
        static const uint8_t states[4] = {2, 3, 1, 0};
        uint32_t state = states[i % 4u];
        contact(SMK_ENCC[7][0], state & 1u);
        contact(SMK_ENCC[7][1], state >> 1);
        smk__encoders(); smk__encoders();
    }
    check(fm1_in.enc_steps[7] == 1 || fm1_in.enc_steps[7] == -1,
          "eighth encoder emits one detent after decoder startup");
    /* Exercise the real key/pad event paths around the last trim point. The
     * interpolator reaches 1024 exactly there, so MIDI conversion must clamp. */
    for (v = 949u; v <= 951u; v++) {
        memset((void *)&fm1_in, 0, sizeof fm1_in);
        fm1_in.pad_base[8] = 100u;
        for (i = 0; i < SMK_PAD_PEAKN; i++) smk__pad(8, v);
        check(fm1_in.pnotes == 1u && fm1_in.key_vel[SMK_KEY_F3] == 127u,
              "pad peaks below/at/above last trim point remain valid maximum MIDI velocity");
    }
    for (v = 979u; v <= 981u; v++) {
        uint32_t key;
        for (key = 0; key <= SMK_KEY_F3; key += SMK_KEY_F3) {
            memset((void *)&fm1_in, 0, sizeof fm1_in);
            smk_extq_w = smk_extq_r = 0;
            contact(SMK_KEYC[key][0], 1);
            smk__keys(100u);
            contact(SMK_KEYC[key][1], 1);
            smk__keys(100u + (1013u - v) * 100u * FM1_TICKS_PER_US);
            check(fm1_in.key_vel[key] == 127u,
                  "key timing below/at/above last trim point remains valid maximum MIDI velocity");
            if (!key)
                check(smk_extq_w == 1u && (smk_extq[0] & 0xFFu) == 127u,
                      "outer-key maximum strike remains note-on rather than velocity128/release");
        }
    }
    for (i = 0; i < 2u; i++) {
        uint32_t original = i ? 0x12345678u : 0u, outer, released;
        test_icfg = original;
        fm1_in.enc_steps[SMK_ENC_MASTER] = 2;
        smk_master = 724;
        check(fm1_adc_read(FM1_ADC_MASTER) == 772 && test_icfg == original,
              "boot/runtime MASTER drain preserves caller ICFG");
        fm1_in.pressed = 0x11u; fm1_in.released = 0x20u;
        check(fm1_input_edges(&released) == 0x11u && released == 0x20u && test_icfg == original,
              "button-edge drain preserves caller ICFG");
        fm1_in.notes_pressed = 0x123u;
        check(fm1_input_note_edges() == 0x123u && test_icfg == original,
              "note-edge drain preserves caller ICFG");
        outer = fm1__lock();
        check(test_icfg == 0u, "outer guard masks interrupts");
        fm1_in.enc_steps[SMK_ENC_MASTER] = 1;
        check(fm1_adc_read(FM1_ADC_MASTER) == 796 && test_icfg == 0u,
              "nested MASTER drain cannot enable outer masked context");
        fm1_in.pressed = 1;
        check(fm1_input_edges(NULL) == 1u && test_icfg == 0u,
              "nested button drain cannot enable outer masked context");
        fm1__unlock(outer);
        check(test_icfg == original && irq_saves == irq_restores,
              "outer guard restores exact initial configuration after nested drains");
    }
    puts("SMK matrix key/velocity/outer-key/OCT/pad/encoder contracts passed");
    return 0;
}
