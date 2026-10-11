/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
#define FELUCCA_FAVORITES 1
/* Stable engine/preset references; fixed capacity independent of optional engines. */
typedef struct {
    uint8_t factory[16][32]; /* engines 0..13; row 14 is MIDI LEARN, row 15 is UI preferences */
    uint32_t user, filter;
    uint8_t macro[32];       /* engine 14, appended in PER5 without reusing MIDI LEARN's bytes */
} favorites_t;
static favorites_t favorites __attribute__((section(".pool")));
static int favorite_has(uint32_t engine, uint32_t preset)
{
    if (engine == NENGINES)
        return preset < UP_SLOTS && ((favorites.user >> preset) & 1u);
    if (engine >= NENGINES || engine >= 15u || preset >= 256u) return 0;
    const uint8_t *row = engine == ENGI_MACRO ? favorites.macro : favorites.factory[engine];
    return (row[preset / 8u] >> (preset % 8u)) & 1u;
}
static int favorite_set(uint32_t engine, uint32_t preset, int on)
{
    if (engine > NENGINES || (engine == NENGINES ? preset >= UP_SLOTS : engine >= 15u || preset >= 256u))
        return 0;
    if (favorite_has(engine, preset) == !!on) return 0;
    if (engine == NENGINES) {
        if (on) favorites.user |= 1u << preset;
        else favorites.user &= ~(1u << preset);
    } else {
        uint8_t *row = engine == ENGI_MACRO ? favorites.macro : favorites.factory[engine];
        uint8_t *b = &row[preset / 8u];
        if (on) *b |= (uint8_t)(1u << (preset % 8u));
        else *b &= (uint8_t)~(1u << (preset % 8u));
    }
    return 1;
}
