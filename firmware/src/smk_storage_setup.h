/* SPDX-License-Identifier: GPL-3.0-only */
/* Physical first-install confirmation; no flash or timing side effects here. */
#pragma once
#include <stdint.h>
enum { SMK_SETUP_WAIT, SMK_SETUP_CANCEL, SMK_SETUP_CONFIRM, SMK_SETUP_TIMEOUT };
typedef struct { uint32_t started, previous; uint8_t armed; } smk_setup_t;
#define SMK_SETUP_TIMEOUT_MS 30000u
static uint32_t smk_setup_step(smk_setup_t *s, uint32_t now, uint32_t buttons,
                               uint32_t banks, uint32_t down, uint32_t up)
{
    uint32_t action = SMK_SETUP_WAIT;
    if ((uint32_t)(now - s->started) >= SMK_SETUP_TIMEOUT_MS)
        return SMK_SETUP_TIMEOUT;
    if (!s->armed) {
        if (!(buttons & (banks | down | up))) s->armed = 1;
    } else if (buttons & down) {
        action = SMK_SETUP_CANCEL;
    } else if (!(buttons & banks) && (buttons & up) && !(s->previous & up)) {
        action = SMK_SETUP_CONFIRM;
    }
    s->previous = buttons;
    return action;
}
