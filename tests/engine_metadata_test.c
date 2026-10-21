/* SPDX-License-Identifier: GPL-3.0-only */
/* Host metadata completeness and compiled descriptor identity. Also runs in the FELUCCA_ENG_TEST14 / FELUCCA_ENG_OMIT
 * catalog builds (run_tests.sh catalog_*): the host-only placeholder engine 14 has ENGINE_META but, being no catalog
 * engine, no generated PRESET_CAT string (NULL, which preset_cat treats as ""); an omitted id is not eng_ok, so skipped. */
#define main hostsim_main
#include "hostsim.c"
#undef main
#include "../firmware/src/category.c"
#include "ui_icons.h"
int main(void)
{
    uint32_t e, n, bad = 0;
    for (e = 0; e < NENGINES; e++) {
        const engine_meta_t *m = &ENGINE_META[e];
        if (!m->tag || !m->tag[0] || strlen(m->tag) > 4 || !m->preset_categories ||
            m->category < CAT_BASS || m->category >= CAT_N || m->icon >= ICON_COUNT ||
            (m->cc >> 4) > 8 || (m->cc & 15) > 8) bad++;
        if (!eng_ok(e)) continue;
        if (strcmp(N_ENGNAME[e], eng_of(e)->name)) bad++;
        if (MIDI_CC_ENG[e] != m->cc || strcmp(PRESET_CAT[e] ? PRESET_CAT[e] : "", m->preset_categories)) bad++;
        for (n = 0; n < NENG_SHOWN && eng_vis(n) != e; n++);
        if (n == NENG_SHOWN) bad++;
        if (e != 1 && e != 14 && strlen(m->preset_categories) != eng_of(e)->npresets) bad++;
    }
    printf("engine metadata (%s): %u failures\n", FELUCCA_PROFILE_NAME, bad);
    return bad != 0;
}
