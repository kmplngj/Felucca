/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Optional device preferences, advertised in INFO. No preset format changes. The font weight
 * (ED_UI_FONT) is gone: one weight; UI_SET of it answers rc 2 (not supported), UI_STATE 127. */
enum { ED_UI_PALETTE = 1, ED_UI_FONT = 2, ED_UI_MONITOR = 4, ED_UI_FAVORITES = 8, ED_UI_UNIFIED = 16 };
static uint32_t ed_ui_caps(void)
{
    uint32_t caps = ED_UI_PALETTE | ED_UI_UNIFIED; /* informational: hide legacy MENU id 2; not a UI_SET slot */
#ifdef FELUCCA_MONITOR
    caps |= ED_UI_MONITOR;
#endif
#ifdef FELUCCA_FAVORITES
    caps |= ED_UI_FAVORITES;
#endif
    return caps;
}
static void ed_u28(uint32_t n)
{
    for (uint32_t i = 0; i < 4; i++) ed_b((n >> (i * 7)) & 127u);
}
static void ed_ui_state(void)
{
    uint32_t sig = 0;
    ed_b(ed_ui_caps());
    ed_b(palette_cur());                               /* (1.6: NPALETTES is CUSTOM) */
    ed_b(127);                                         /* font: not supported */
#ifdef FELUCCA_MONITOR
    ed_b(settings.monitor);
#else
    ed_b(127);
#endif
#ifdef FELUCCA_FAVORITES
    ed_b(favorites.filter);
    sig = 2166136261u;
    for (uint32_t i = 0; i < sizeof favorites; i++)
        sig = (sig ^ ((const uint8_t *)&favorites)[i]) * 16777619u;
#else
    ed_b(127);
#endif
    ed_u28(sig);
    ed_u28(up_gen);
}
/* Every editor settings write (UI_SET, FAV_SET, MENU_SET, LEARN_SET, PALETTE_SET) saves through the panel's flash
 * path, and its rc is project.c settings_save_result's durability (#296) on the wire: 0 saved (or unchanged: no
 * erase), 3 applied in RAM only (no flash, a failed write: retried by the settings path), 4 queued until STOP */
static uint32_t ed_settings_save(void)
{
    uint32_t d = settings_save_result();
    return d == SETTINGS_SAVED ? 0u : d == SETTINGS_QUEUED ? 4u : 3u;
}
static uint32_t ed_ui_set(const uint8_t *a, uint32_t n)
{
    if (n != 2u || a[0] > 3u) return 1;
    if (!(ed_ui_caps() & (1u << a[0]))) return 2;
    if (a[1] >= (a[0] == 0 ? palette_n() : a[0] == 2 ? 3u : 2u)) return 1;
    switch (a[0]) {
    case 0:
        palette_choose(a[1]); break;
#ifdef FELUCCA_MONITOR
    case 2:
        fm1_irq_off();
        settings.monitor = a[1]; monitor_mode = a[1]; monitor_event.valid = 0;
        fm1_irq_on();
        break;
#endif
#ifdef FELUCCA_FAVORITES
    case 3:
        favorites.filter = a[1]; break;
#endif
    }
    ui.force = 1;
    return ed_settings_save();
}
#ifdef FELUCCA_FAVORITES
/* FAV_GET / FAV_SET's engine byte (#212) -> engine id, ENG_USER for a user preset slot, ED_FAV_BAD: an engine this
 * build has (eng_ok), ENG_USER_WIRE (INFO's 49 01 block), or the old marker: NENGINES, the count INFO's old prefix
 * sends, which editors up to 1.6 took from there (14; 13 with FELUCCA_SLICE=0). It is never an engine id of this
 * build (its table ends below it), so it is unambiguous here; an editor that has it built in as 14 talks to a build
 * whose INFO count is 14. Engine 1 (DIGITAL, retired), an unavailable id: rc 1 */
#define ED_FAV_BAD 0x100u
static uint32_t ed_fav_ref(uint32_t b)
{
    if (b == ENG_USER_WIRE || b == NENGINES)
        return ENG_USER;
    return eng_ok(b) ? b : ED_FAV_BAD;
}
static uint32_t ed_fav_limit(uint32_t e) { return e == ENG_USER ? UP_SLOTS : ENGINES[e]->npresets; }
#endif
static int ed_ui_handle(uint32_t cmd, const uint8_t *a, uint32_t n)
{
    switch (cmd) {
    case ED_UI_STATE:
        ed_ui_state(); return 1;
    case ED_UI_SET:
        ed_b(ed_ui_set(a, n));
        ed_b(n ? a[0] : 127u); ed_b(n > 1u ? a[1] : 127u);
        ed_ui_state(); return 1;
    case ED_UI_PALETTES:
        ed_b(palette_n());                             /* (1.6: CUSTOM last, while one is stored) */
        for (uint32_t i = 0; i < palette_n(); i++) ed_str(palette_name(i), 12);
        return 1;
    case ED_FAV_GET:
#ifdef FELUCCA_FAVORITES
        if (n == 4u && ed_fav_ref(a[0]) != ED_FAV_BAD) {
            int32_t start = ed_rv(a + 1);
            uint32_t e = ed_fav_ref(a[0]), limit = ed_fav_limit(e);
            if (start >= 0 && a[3] && a[3] <= 32u && (uint32_t)start + a[3] <= limit) {
                ed_b(0); ed_b(a[0]); ed_v(start); ed_b(a[3]);   /* (the engine byte as asked: either marker) */
                for (uint32_t i = 0; i < a[3]; i++) ed_b(favorite_has(e, (uint32_t)start + i));
                return 1;
            }
        }
        ed_b(1);
#else
        ed_b(2);
#endif
        return 1;
    case ED_FAV_SET:
#ifdef FELUCCA_FAVORITES
        if (n == 4u && ed_fav_ref(a[0]) != ED_FAV_BAD && a[3] <= 1u) {
            int32_t preset = ed_rv(a + 1);
            uint32_t e = ed_fav_ref(a[0]), limit = ed_fav_limit(e);
            if (preset >= 0 && (uint32_t)preset < limit &&
                (e != ENG_USER || !a[3] || up_used((uint32_t)preset))) {
                favorite_set(e, (uint32_t)preset, a[3]);
                ui.force = 1;
                ed_b(ed_settings_save()); ed_b(a[0]); ed_v(preset); ed_b(a[3]);
                return 1;
            }
        }
        ed_b(1);
#else
        ed_b(2);
#endif
        return 1;
    default: return 0;
    }
}
