/* SPDX-License-Identifier: GPL-3.0-only */
/* Production publication and initialization against the register-backed scan. */
#define SMK_INPUT_IRQ_SAVE() 0u
#define SMK_INPUT_IRQ_RESTORE(f) ((void)(f))
#define main smk_scan_fixture_main
#include "smk_scan_test.c"
#undef main
#define check require
int main(void)
{
    uint32_t k, held;
    for (k = 0; k < FM1_NKEY; k++) {
        uint32_t bit;
        if (k >= SMK_KEY_F3 && k < SMK_KEY_F3 + 27u) continue;
        bit = 1u << (k < SMK_KEY_F3 ? k : k - 27u);
        smk_extq_r = smk_extq_w = 0;
        smk_extkeys_held = smk_extkeys_pressed = 0;
        smk_extkeys_asleep = 0;
        smk__key_event(k, 100);
        check(smk_extkey_activity(&held) == bit && held == bit, "every outer key publishes activity and hold");
        check(smk_extkey_take() == (int32_t)(k << 8 | 100), "awake queue retains exact key and velocity");
        check(!smk_extkey_activity(&held) && held == bit, "edge drains independently of held input");
        smk__key_event(k, 0);
        check(!smk_extkey_activity(&held) && !held, "outer release clears activity hold");
        check(smk_extkey_take() == (int32_t)(k << 8), "release retains queue identity");
        smk_extkeys_asleep = 1;
        smk__key_event(k, 100); smk__key_event(k, 0);
        smk_extkeys_asleep = 0;
        check(smk_extkey_activity(&held) == bit && !held, "short wake press survives release until UI poll");
        check(smk_extkey_take() == (int32_t)(0x8000u | k << 8 | 100), "wake press stays consumed after sleep ends");
        check(smk_extkey_take() == (int32_t)(k << 8), "wake release is still delivered");
    }
    /* Warm init preserves a real held key but drops stale activity; resetting
     * caller state before re-init must not retain an old held mask. */
    fm1_in.keys = (uint64_t)1u | (uint64_t)1u << 36;
    smk_extkeys_held = smk_extkeys_pressed = 0xFFFFFFFFu;
    smk_extkeys_asleep = 1;
    fm1_input_init(); service();
    check(smk_extkeys_held == (1u | 1u << 9) && !smk_extkeys_pressed && smk_extkeys_asleep,
          "warm init reconstructs held keys and preserves boot gate");
    now += 10u * FM1_TICKS_PER_US; service();
    memset((void *)&fm1_in, 0, sizeof fm1_in);
    fm1_input_init(); service();
    check(!smk_extkeys_held && !smk_extkeys_pressed && smk_extkeys_asleep,
          "caller input reset cannot retain stale outer activity");
    puts("SMK outer held/short-press activity and queued wake suppression passed");
    return 0;
}
