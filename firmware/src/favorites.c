/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
#define FELUCCA_FAVORITES 1
/* Stable engine/preset references; fixed capacity independent of optional engines (#212): a row of 256 preset bits
 * per engine id 0..FAV_ROWS-1, whatever engines a build has (a row of an id this build lacks is kept as saved), and
 * the user preset slots. A reference is (engine id, preset), or (ENG_USER, slot) for a user preset. Up to 1.6 the
 * rows were factory[16][32] with row 14 MIDI LEARN's map and row 15 device settings: those are settings_ml and
 * settings_dev now (below), and the settings keep the old 16 rows as well (settings_persist.c) */
#define FAV_ROWS ENG_ID_MAX
typedef struct {
    uint8_t factory[FAV_ROWS][32]; /* engine id 0..FAV_ROWS-1, preset 0..255 */
    uint32_t user, filter;
} favorites_t;
static favorites_t favorites __attribute__((section(".pool")));
/* settings bytes that were favourites rows up to 1.6 (#212; the same bytes, the same meaning): MIDI LEARN's map
 * (midi_control.c ml_tab, PER4's factory[14]) and the device's own preferences (PER4's factory[15]: ui.c ui_prefs,
 * ui_style, .., the FX key map, CUSTOM's colours; their indices are the old row's) */
static uint8_t settings_ml[32] __attribute__((section(".pool")));
static uint8_t settings_dev[32] __attribute__((section(".pool")));
static int favorite_has(uint32_t engine, uint32_t preset)
{
    if (engine == ENG_USER)
        return preset < UP_SLOTS && ((favorites.user >> preset) & 1u);
    return engine < FAV_ROWS && preset < 256u &&
        ((favorites.factory[engine][preset / 8u] >> (preset % 8u)) & 1u);
}
/* marks / clears one (the caller checks that the engine has the preset, or the slot a sound); 1 = it changed */
static int favorite_set(uint32_t engine, uint32_t preset, int on)
{
    if (engine == ENG_USER ? preset >= UP_SLOTS : engine >= FAV_ROWS || preset >= 256u)
        return 0;
    if (favorite_has(engine, preset) == !!on) return 0;
    if (engine == ENG_USER) {
        if (on) favorites.user |= 1u << preset;
        else favorites.user &= ~(1u << preset);
    } else {
        uint8_t *b = &favorites.factory[engine][preset / 8u];
        if (on) *b |= (uint8_t)(1u << (preset % 8u));
        else *b &= (uint8_t)~(1u << (preset % 8u));
    }
    return 1;
}

/* MENU > DISPLAY > COLOR's 11th value, CUSTOM (1.6, #244, Discussion #239): a palette of the user's, five RGB565 colours (BG
 * SURF TEXT THEME ACCENT, 16 bits little endian) in settings_dev[0..9] (PER4's favorites.factory[15]), flags in [12] (bit 0: one is stored, bit 1:
 * it is the palette in use), set from the editor (PALETTE_SET, editor_palette.c) and saved with the settings. settings.palette
 * stays a built-in palette (the one in use before, or after): firmware before 1.6 shows that and keeps the bytes. The value
 * is in COLOR only while one is stored. Zero (every older setting) = none */
#define ui_cpal (&settings_dev[0])
#define ui_cpal_flags (settings_dev[12])
#define CPAL_STORED 1u
#define CPAL_ACTIVE 2u
static uint32_t cpal_on(void) { return (ui_cpal_flags & (CPAL_STORED | CPAL_ACTIVE)) == (CPAL_STORED | CPAL_ACTIVE); }
static uint32_t palette_n(void) { return NPALETTES + ((ui_cpal_flags & CPAL_STORED) ? 1u : 0u); }     /* COLOR's values */
static uint32_t palette_cur(void) { return cpal_on() ? NPALETTES : settings.palette % NPALETTES; }
static const char *palette_name(uint32_t v) { return v == NPALETTES ? "CUSTOM" : UI_PALETTES[v % NPALETTES].name; }
/* the palette in use into gfx.c (the settings changed under it: a start, an import, a restore, a STYLE change) */
static void palette_apply(void)
{
    if (cpal_on()) {
        palette_custom_load(ui_cpal);
        palette_set(NPALETTES);
    } else {
        palette_set(settings.palette % NPALETTES);
    }
}

/* the five colours into the settings' bytes (stored; not yet the palette in use: palette_choose / palette_apply) */
static void cpal_store(const uint16_t *c)
{
    uint32_t i;
    for (i = 0; i < 5u; i++) {
        ui_cpal[2u * i] = (uint8_t)c[i];
        ui_cpal[2u * i + 1u] = (uint8_t)(c[i] >> 8);
    }
    ui_cpal_flags |= CPAL_STORED;
}
