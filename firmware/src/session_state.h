/* SPDX-License-Identifier: GPL-3.0-only */
/* Read-only main-loop observations for diagnostic acquisition (#57). Include
 * after UI and project.c: no save/export helper or service runs while reading. */
#pragma once

typedef struct {
    uint8_t features, learn, settings_later, menu, settings_pending, slice_pending;
} session_state_t;

static session_state_t session_state_read(void)
{
    session_state_t s = {0};
    /* All owners below are main-loop-only except io[1] (ml_heard), which the
     * audio-side MIDI consumer writes as one volatile byte. Read it exactly
     * once while the other owners cannot change. No IRQ mask is needed; this
     * is an observation at that read, not a reservation between polls. */
    uint8_t heard = ui.ml.io[1];
    s.learn = (uint8_t)((ui.ml.on != 0u) | (ui.ml.pick != 0u) << 1 |
                       (ui.ml.io[0] != 0u) << 2 | (heard != 0u) << 3);
    s.settings_later = set_later.on != 0u;
    s.menu = ui.menu != 0u;
#if FELUCCA_FLASH
    s.features |= 1u;
    s.settings_pending = persist_pending;
#if FELUCCA_SLICE
    s.features |= 2u;
    s.slice_pending = slc_man_save;
#endif
#endif
    return s;
}
