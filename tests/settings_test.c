/* SPDX-License-Identifier: GPL-3.0-only */
#include "../firmware/hal/fm1_lcd_contract.h"
#include <stdint.h>
#include "../firmware/hal/fm1_input_contract.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>
#define __attribute__(x)
#define NENGINES 9u
#define ENG_ID_MAX 64u                           /* (core.h: the engine id space, favourites' rows) */
#define ENG_USER 0xFFu
#define UP_SLOTS 32u
#define ENGI_SAMPLE 4u                           /* (core.h: SAMPLE, DRUM, the retired PERC set) */
#define ENGI_DRUM 10u
#define SMP_SET_PERC 4u
static uint8_t fx_lowcut;
static void fm1_led_key(unsigned k, int on) { (void)k; (void)on; }
static fm1_enc_take_fn fm1_enc_take;
static int32_t fm1_enc_take(uint32_t k) { (void)k; return 0; }
static void lcd_sync(void) {}
static void lcd_power(uint32_t s) { (void)s; }   /* (MENU > SCREEN OFF: lcd.c) */
static void lcd_wake_now(void) {}
#include "host_lcd_blit_noop.h"
#include "../firmware/src/gfx.c"
#include "../firmware/src/panel.c"
static void settings_save(void) {}
#if __has_include("../firmware/src/favorites.c")
#include "../firmware/src/favorites.c"
#endif
#include "../firmware/src/settings_persist.c"
int main(void)
{
    persist_t original = {0}, p;
    original.magic = PERSIST_MAGIC;
    original.palette = 4; original.bold = original.lowcut = original.zoom = 1;   /* old id 4: MONO, now GREY */
    original.panel = PANEL_DEFAULT; original.panel.enc[0] = 3;
    original.favorites.factory[8][0] = 1;
    original.favorites.user = 1u << 31; original.favorites.filter = 1;
    p = original;
    assert(settings_import(&p, sizeof p) == 1); settings_init();
    assert(settings.palette == UI_GREY_INDEX && fx_lowcut && settings.zoom && panel.enc[0] == 3);
    assert(p.palette == palette_to_stored(UI_GREY_INDEX));        /* migrated in place */
    {   /* every old id maps to a palette; tagged ids round trip; anything else is GREY */
        persist_t q = original;
        for (uint32_t i = 0; i < 20u; i++) assert(palette_from_stored(i) < NPALETTES);
        assert(palette_from_stored(13) == 6u && palette_from_stored(11) == 7u && palette_from_stored(19) == 7u);
        for (uint32_t i = 0; i < NPALETTES; i++) assert(palette_from_stored(palette_to_stored(i)) == i);
        assert(palette_from_stored(40) == UI_GREY_INDEX && !palette_stored_ok(40) && palette_stored_ok(3));
        /* 1.0.2: the old MONO keeps its id as GREY (a saved MONO looks the same); the new black and white MONO is
         * appended, a new id */
        assert(palette_from_stored(UI_PAL_TAG + 0u) == UI_GREY_INDEX && !strcmp(UI_PALETTES[UI_GREY_INDEX].name, "GREY"));
        assert(UI_BW_INDEX == NPALETTES - 1u && !strcmp(UI_PALETTES[UI_BW_INDEX].name, "MONO") &&
               palette_from_stored(UI_PAL_TAG + UI_BW_INDEX) == UI_BW_INDEX && palette_stored_ok(UI_PAL_TAG + UI_BW_INDEX));
        q.palette = palette_to_stored(5);
        assert(settings_import(&q, sizeof q) == 1 && settings.palette == 5u);
        settings.magic = SETTINGS_MAGIC_OLD; settings.palette = 13; settings_init();   /* retained SET3 */
        assert(settings.magic == SETTINGS_MAGIC && settings.palette == 6u);
        p = original; assert(settings_import(&p, sizeof p) == 1); settings_init();
    }
#ifdef FELUCCA_FAVORITES
    assert(favorite_has(8, 0) && favorite_has(ENG_USER, 31) && favorites.filter);
    {   /* SAMPLE's PERC starred (preset 4, retired): DRUM's kit (preset 0) instead; SAMPLE's others kept; twice the same */
        persist_t q = original;
        q.favorites.factory[ENGI_SAMPLE][0] = 1u << SMP_SET_PERC | 1u << 2;
        assert(settings_import(&q, sizeof q) == 1 && favorites.factory[ENGI_SAMPLE][0] == 1u << 2 &&
               favorites.factory[ENGI_DRUM][0] == 1u);
        settings_export(&q);
        assert(settings_import(&q, sizeof q) == 1 && favorites.factory[ENGI_SAMPLE][0] == 1u << 2 &&
               favorites.factory[ENGI_DRUM][0] == 1u);
        p = original; assert(settings_import(&p, sizeof p) == 1);
    }
#endif
    settings.lowcut = 0;
    settings_export(&p);
    assert(!p.lowcut && p.bold == 1 && p.favorites.user == (1u << 31));   /* bold: kept as saved */
    assert(p.favorites.factory[8][0] == 1 && p.favorites.filter == 1);
    assert(p.panel.enc[0] == 3); /* saving one feature preserves the other */
    p = original; p.magic = 0x50455233u;
    assert(settings_import(&p, sizeof p - sizeof p.favorites) == 2);
    assert(p.bold == 1 && !p.favorites.user && !p.favorites.filter);
    settings_export(&p); assert(p.bold == 1); /* favorites-only preserves PER3 font */
    p = original; p.magic = 0x50455232u;
    assert(settings_import(&p, sizeof p - sizeof p.favorites - sizeof p.bold) == 2);
    assert(!p.bold && !p.favorites.user && settings.zoom && panel.enc[0] == 3);
    p = original; p.magic = 0x50455231u;
    memcpy((uint8_t *)&p + 8, &PANEL_DEFAULT, sizeof(panel_t));
    assert(settings_import(&p, 8 + sizeof(panel_t)) == 2);
    assert(!p.bold && !p.zoom && !p.lowcut && !p.favorites.user && panel.magic == PANEL_MAGIC);
    {   /* HOLD: in the retired bold field; older records (bold 0 / 1) are 0.4 s, and stay as saved */
        p = original; p.bold = 0;
        assert(settings_import(&p, sizeof p) == 1 && settings_hold == HOLD_DEF && HOLD_MS[settings_hold] == 400u);
        p = original;
        assert(settings_import(&p, sizeof p) == 1 && settings_hold == HOLD_DEF);
        settings_hold = 3;
        settings_export(&p);
        assert(hold_stored_ok(p.bold) && p.bold != 1u);
        settings_hold = 0;
        assert(settings_import(&p, sizeof p) == 1 && settings_hold == 3u && HOLD_MS[settings_hold] == 600u);
        settings_hold = HOLD_DEF;
        settings_export(&p);
        assert(p.bold == 0u && settings_import(&p, sizeof p) == 1 && settings_hold == HOLD_DEF);
        assert(!hold_stored_ok(2u) && !hold_stored_ok(HOLD_TAG + 4u) && hold_stored_ok(HOLD_TAG | 2u));
        p = original; p.magic = 0x50455231u;
        memcpy((uint8_t *)&p + 8, &PANEL_DEFAULT, sizeof(panel_t));
        settings_hold = 2;
        assert(settings_import(&p, 8 + sizeof(panel_t)) == 2 && settings_hold == HOLD_DEF);
    }
    {   /* LEDS: in the retired zoom field; older records (zoom 0 / 1) are DIM, and stay as saved; idempotent */
        persist_t q;
        p = original;                                   /* zoom 1: an older record's large readout */
        assert(settings_import(&p, sizeof p) == 1 && settings_leds == LEDS_DIM);
        q = p; settings_export(&q); assert(q.zoom == 1u);                  /* DIM: kept as saved */
        settings_leds = LEDS_INV;
        settings_export(&p);
        assert(p.zoom == (LEDS_TAG | LEDS_INV) && leds_stored_ok(p.zoom));
        q = p; settings_export(&q); assert(!memcmp(&q, &p, sizeof q));   /* a second save: the same record */
        settings_leds = LEDS_DIM;
        assert(settings_import(&p, sizeof p) == 1 && settings_leds == LEDS_INV);
        q = p; assert(settings_import(&q, sizeof q) == 1 && !memcmp(&q, &p, sizeof q));   /* import twice: the same */
        settings_leds = LEDS_DIM;
        settings_export(&p);
        assert(p.zoom == 0u && settings_import(&p, sizeof p) == 1 && settings_leds == LEDS_DIM);
        assert(leds_stored_ok(0u) && leds_stored_ok(1u) && !leds_stored_ok(2u) && leds_stored_ok(LEDS_TAG | 2u) &&
               leds_stored_ok(LEDS_TAG | 3u) && !leds_stored_ok(LEDS_TAG + 4u) && leds_from_stored(LEDS_TAG + 4u) == LEDS_DIM &&
               leds_from_stored(7u) == LEDS_DIM && leds_from_stored(2u) == LEDS_DIM);
        /* the modes appended (append-only: DIM 0, INV 1 as before): OFF 2, DIM LO 3, each saved and read back,
         * twice the same */
        {
            uint32_t m;
            static const uint32_t ADDED[2] = {LEDS_OFF, LEDS_DIM_LO};
            assert(LEDS_DIM == 0 && LEDS_INV == 1 && LEDS_OFF == 2 && LEDS_DIM_LO == 3 && LEDS_COUNT == 4);
            for (m = 0; m < 2u; m++) {
                settings_leds = (uint8_t)ADDED[m];
                settings_export(&p);
                assert(p.zoom == (LEDS_TAG | ADDED[m]) && leds_stored_ok(p.zoom));
                q = p; settings_export(&q); assert(!memcmp(&q, &p, sizeof q));
                settings_leds = LEDS_DIM;
                assert(settings_import(&p, sizeof p) == 1 && settings_leds == ADDED[m]);
            }
            settings_leds = LEDS_DIM;
            settings_export(&p);
            assert(p.zoom == 0u);
        }
        p = original; p.magic = 0x50455231u;           /* PER1: no zoom field, DIM */
        memcpy((uint8_t *)&p + 8, &PANEL_DEFAULT, sizeof(panel_t));
        settings_leds = LEDS_INV;
        assert(settings_import(&p, 8 + sizeof(panel_t)) == 2 && settings_leds == LEDS_DIM);
    }
#ifdef FELUCCA_FAVORITES
    {   /* 1.1 CLICK / CLICK LEVEL / COUNT-IN (ui.c ui_rec_prefs, settings_dev[28]): 0 in every older record
         * (the defaults: OFF / MID / OFF); each field 0..2 kept, 3 (no value) back to 0, bits 6-7 kept; twice the same */
        persist_t q;
        uint32_t b;
        p = original; p.magic = 0x50455233u;            /* PER3 (no favorites): 0 */
        assert(settings_import(&p, sizeof p - sizeof p.favorites) == 2 && settings_dev[28] == 0u);
        for (b = 0; b < 256u; b++) {
            uint32_t f, want = b;
            for (f = 0; f < 3u; f++)
                if (((b >> (2u * f)) & 3u) == 3u) want &= ~(3u << (2u * f));
            p = original; p.favorites.factory[15][28] = (uint8_t)b;
            assert(settings_import(&p, sizeof p) == 1 && settings_dev[28] == want && p.favorites.factory[15][28] == want);
            q = p; assert(settings_import(&q, sizeof q) == 1 && !memcmp(&q, &p, sizeof q));
            settings_export(&q); assert(q.favorites.factory[15][28] == want);
        }
        p = original; assert(settings_import(&p, sizeof p) == 1);
    }
    {   /* 1.2 RESTORE LAST (ui.c PREF_RESTORE_OFF, bit 7 of MENU's flags, settings_dev[30]): clear in every
         * older record = ON; set = OFF, kept as saved with the other flags */
        persist_t q;
        p = original; p.magic = 0x50455233u;
        assert(settings_import(&p, sizeof p - sizeof p.favorites) == 2 && !(settings_dev[30] & 128u));
        p = original; p.favorites.factory[15][30] = 128u | 64u | 1u;
        assert(settings_import(&p, sizeof p) == 1 && settings_dev[30] == (128u | 64u | 1u));
        q = p; settings_export(&q); assert(q.favorites.factory[15][30] == (128u | 64u | 1u));
        p = original; assert(settings_import(&p, sizeof p) == 1);
    }
    {   /* 1.2 the FX layer's key map (ui_layer.c fx_keys, settings_dev[14..23], 16 x 5 bits, 0 = the key's
         * default): 0 in every older record; any bytes kept as saved (codes of a later firmware too), the bytes around
         * them untouched; twice the same */
        persist_t q;
        uint32_t i;
        p = original; p.magic = 0x50455233u;
        assert(settings_import(&p, sizeof p - sizeof p.favorites) == 2);
        for (i = 14; i < 24u; i++) assert(settings_dev[i] == 0u);
        p = original;
        for (i = 14; i < 24u; i++) p.favorites.factory[15][i] = (uint8_t)(i * 37u + 5u);
        assert(settings_import(&p, sizeof p) == 1);
        for (i = 14; i < 24u; i++) assert(settings_dev[i] == (uint8_t)(i * 37u + 5u));
        assert(settings_dev[13] == original.favorites.factory[15][13] && settings_dev[24] == original.favorites.factory[15][24]);
        memset(&q, 0, sizeof q); settings_export(&q); assert(!memcmp(&q.favorites, &p.favorites, sizeof q.favorites));
        assert(settings_import(&q, sizeof q) == 1);
        for (i = 14; i < 24u; i++) assert(settings_dev[i] == (uint8_t)(i * 37u + 5u));
        p = original; assert(settings_import(&p, sizeof p) == 1);
    }
    {   /* 1.5 MIDI LEARN's map (midi_control.c, favorites.factory[14], no engine's): 0 = nothing learned in every older
         * record; kept as saved, byte for byte (an entry of a later firmware too), the rows around it untouched; an
         * export / import round trip and importing twice change nothing */
        persist_t q;
        uint32_t i;
        p = original; p.magic = 0x50455233u;
        assert(settings_import(&p, sizeof p - sizeof p.favorites) == 2);
        for (i = 0; i < 32u; i++) assert(settings_ml[i] == 0u);
        p = original;
        for (i = 0; i < 32u; i++) p.favorites.factory[14][i] = (uint8_t)(i * 29u + 3u);
        assert(settings_import(&p, sizeof p) == 1);
        for (i = 0; i < 32u; i++) assert(settings_ml[i] == (uint8_t)(i * 29u + 3u));
        assert(!memcmp(favorites.factory[13], original.favorites.factory[13], 32) &&
               !memcmp(settings_dev, original.favorites.factory[15], 32));
        memset(&q, 0, sizeof q); settings_export(&q); assert(!memcmp(&q.favorites, &p.favorites, sizeof q.favorites));
        assert(settings_import(&q, sizeof q) == 1 && settings_import(&q, sizeof q) == 1);
        for (i = 0; i < 32u; i++) assert(settings_ml[i] == (uint8_t)(i * 29u + 3u));
        p = original; assert(settings_import(&p, sizeof p) == 1);
    }
    {   /* #212: PER6, the versioned extension (settings_persist.c): favourites for engine ids 0..63, MIDI LEARN's map and
         * the device bytes out of the favourites; PER4 while no favourite is on an id from 14, the PER4 block of a PER6
         * record the PER4 record older firmware reads (old -> new -> old), malformed and PER5 (MACRO's branch) records */
        static persist_rec_t r, r2;
        persist_t old, q;
        uint32_t i, len6 = (uint32_t)sizeof(persist_t) + PERSIST_EXT_HDR + FAV_ROWS * 32u;
        p = original;
        for (i = 0; i < 32u; i++) { p.favorites.factory[14][i] = (uint8_t)(i * 7u + 1u); p.favorites.factory[15][i] = 0; }
        p.favorites.factory[15][30] = 1u; p.favorites.factory[15][14] = 0x5Au;   /* MENU flags, the FX key map */
        p.favorites.factory[13][1] = 0x80u;                                     /* SLICE preset 15 */
        old = p;
        assert(settings_import(&p, sizeof p) == 1);                             /* old (PER4) */
        assert(settings_ml[0] == 1u && settings_ml[31] == (uint8_t)(31u * 7u + 1u) && settings_dev[30] == 1u &&
               favorite_has(13, 15) && !favorite_has(14, 0));
        memset(&r, 0xEE, sizeof r); memcpy(&r, &old, sizeof old);
        settings_export_rec(&r);                                                /* new, nothing past id 13: still PER4 */
        assert(r.magic == PERSIST_MAGIC && persist_len(&r) == sizeof(persist_t));
        for (i = 0; i < sizeof r.x; i++) assert(((const uint8_t *)&r.x)[i] == 0u);
        q = old; settings_export(&q);
        assert(!memcmp(&q, &r, sizeof q) && !memcmp(&q.favorites, &old.favorites, sizeof q.favorites));   /* -> old: the same */
        assert(favorite_set(20, 3, 1) && favorite_set(63, 255, 1) && !favorite_set(64, 0, 1) && !favorite_has(64, 0));
        assert(favorite_set(ENG_USER, 2, 1) && favorite_has(ENG_USER, 2) && !favorite_set(ENG_USER, 32, 1));
        settings_export_rec(&r);                                                /* a favourite on id 20: PER6 */
        assert(r.magic == PERSIST_MAGIC_EXT && persist_len(&r) == len6 && len6 <= 3840u && r.x.ver == 1u &&
               r.x.rows == FAV_ROWS && r.x.ml_n == 32u && r.x.dev_n == 32u && !memcmp(r.x.ml, settings_ml, 32) &&
               !memcmp(r.x.dev, settings_dev, 32) && r.x.fav[20][0] == 8u && r.x.fav[63][31] == 0x80u &&
               r.x.fav[13][1] == 0x80u);
        assert(!memcmp(r.favorites.factory[14], settings_ml, 32) && !memcmp(r.favorites.factory[15], settings_dev, 32) &&
               !memcmp(r.favorites.factory[13], old.favorites.factory[13], 32));   /* the PER4 block kept as PER4 has it */
        r2 = r;
        memset(&favorites, 0, sizeof favorites); memset(settings_ml, 0, 32); memset(settings_dev, 0, 32);
        assert(settings_import((persist_t *)&r2, (int)len6) == 1 && r2.magic == PERSIST_MAGIC_EXT);   /* -> new */
        assert(favorite_has(20, 3) && favorite_has(63, 255) && favorite_has(13, 15) && favorite_has(ENG_USER, 2) &&
               settings_ml[31] == (uint8_t)(31u * 7u + 1u) && settings_dev[14] == 0x5Au && !memcmp(&r2, &r, len6));
        assert(settings_import((persist_t *)&r2, (int)len6) == 1 && !memcmp(&r2, &r, len6));   /* twice: the same */
        memcpy(&q, &r, sizeof q); q.magic = PERSIST_MAGIC;                      /* -> old: the PER4 block of a PER6 */
        assert(settings_import(&q, sizeof q) == 1 && favorite_has(13, 15) && !favorite_has(20, 3) &&   /* (the documented */
               !favorite_has(63, 255) && settings_ml[31] == (uint8_t)(31u * 7u + 1u) && settings_dev[14] == 0x5Au);   /* limit) */
        assert(settings_import((persist_t *)&r2, (int)len6 - 32) == 2 && !favorite_has(20, 3) &&   /* a short extension: */
               favorite_has(13, 15) && settings_ml[0] == 1u && settings_dev[30] == 1u);        /* its PER4 block */
        r2 = r; r2.x.ver = 2u;                                                  /* another version: the PER4 block */
        assert(settings_import((persist_t *)&r2, (int)len6) == 2 && !favorite_has(20, 3) && favorite_has(13, 15));
        r2 = r; r2.x.ml_n = 33u;
        assert(settings_import((persist_t *)&r2, (int)len6) == 2 && !favorite_has(20, 3));
        r2 = r; r2.x.rows = 0u;
        assert(settings_import((persist_t *)&r2, (int)len6) == 2 && !favorite_has(20, 3));
        r2 = r; r2.x.rows = FAV_ROWS + 1u;
        assert(settings_import((persist_t *)&r2, (int)len6) == 2);
        r2 = r;                                                                 /* longer than any record: invalid */
        assert(settings_import((persist_t *)&r2, (int)sizeof r2 + 1) == 0 && settings_import((persist_t *)&r2, (int)sizeof r2 + 32) == 0);
        r2 = r; r2.x.rows = 21u;                                                /* fewer rows (an id space of 21): read */
        assert(settings_import((persist_t *)&r2, (int)(sizeof(persist_t) + PERSIST_EXT_HDR + 21u * 32u)) == 1 &&
               favorite_has(20, 3) && !favorite_has(63, 255));
        r2 = r; r2.x.rows = 10u; r2.x.fav[12][0] = 1u;                          /* rows 10..13 not stored: none */
        assert(settings_import((persist_t *)&r2, (int)(sizeof(persist_t) + PERSIST_EXT_HDR + 10u * 32u)) == 1 &&
               !favorite_has(13, 15) && !favorite_has(12, 0) && settings_ml[0] == 1u);
        memcpy(&r2, &old, sizeof old); r2.magic = PERSIST_MAGIC_V5;             /* PER5: MACRO's row is engine 14's */
        memset((uint8_t *)&r2 + sizeof(persist_t), 0, 32); ((uint8_t *)&r2)[sizeof(persist_t) + 1] = 4u;
        assert(settings_import((persist_t *)&r2, (int)sizeof(persist_t) + 32) == 2 && r2.magic == PERSIST_MAGIC &&
               favorite_has(14, 10) && settings_ml[0] == 1u && favorite_has(13, 15));
        assert(settings_import((persist_t *)&r2, (int)sizeof(persist_t) + 31) == 0);
        memcpy(&r2, &old, sizeof old);                                          /* PER4 magic with an extension's length */
        assert(settings_import((persist_t *)&r2, (int)len6) == 0);
        p = original; assert(settings_import(&p, sizeof p) == 1);
    }
#endif
    assert(settings_import(&p, 3) == 0 && settings_import(&p, -1) == 0);
    assert(settings_import(&p, sizeof p - 1) == 0);
    puts("Settings: PER1/PER2/PER3 migration, palette ids, calibration, HOLD, LEDS, CLICK / COUNT-IN, the FX key map, MIDI LEARN's map, PER6 (engine ids to 63, PER4 <-> PER6, malformed, PER5) and independent feature preservation passed.");
}
