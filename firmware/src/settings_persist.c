/* SPDX-License-Identifier: GPL-3.0-only */
/* Shared PER4 layout: each feature updates only its own fields, preserving
 * the other feature's saved preferences when either is built independently.
 * PER1/PER2 are upstream; PER3 added bold; PER4 added favorites; PER6 (#212) appends a versioned extension.
 * palette: UI_PAL_TAG + index; an old id (below 20, earlier firmware) is migrated on import.
 * bold: no longer used (one font weight); kept as it was saved, unless it holds the HOLD setting (panel.c).
 * zoom: no longer used (the large readout); kept as it was saved, unless it holds the LEDS setting (panel.c).
 * The PER4 block's favorites.factory[16][32]: rows 0..13 the favourites of engines 0..13, row 14 MIDI LEARN's map
 * (settings_ml), row 15 the device bytes (settings_dev; favorites.c):
 * [15][28..31]: CLICK / CLICK LEVEL / COUNT-IN (1.1), STYLE, MENU's flags, the layers seen (bytes no
 * engine uses; 0 in older settings = every one's default); [15][27]: AUTO OFF (ui.c): historical timer codes bits 0..2,
 * first-stage target bits 3..4, independent ALL DARK timer index bits 5..7 (0 = NEVER);
 * [15][26]: MENU > DISPLAY > HOME (1.3; 0 = SCOPE, 1 TRACKS, 2 LEVELS (1.5), ui.c ui_home_view);
 * [15][24]: MENU's 1.2 flags SCOPE MIX, STEP PREVIEW ON, CHORD ENTRY ADD (bits 0-2, ui.c ui_prefs2; 0 = the defaults),
 *   1.5 HELP ON (bit 3), 1.5.5 SELECT PAGE (bit 4; 0 = BPM, as before), 1.5.5 SCREEN WAKE PANEL (bit 5; 0 = +MIDI);
 *   1.6.1 2ND CORE ON (bit 7; 0 = OFF, one core, as before);
 * [15][10]: MENU > ANIM IDLE (1.2, Discussion #135, ui.c ui_idle: bit 0; 0 = off, ANIM as its bit in MENU's flags says),
 *   MENU > DISPLAY > GRAPH (#572, ui.c graph_mode: bits 1..2; 0 = TURN);
 * [15][11]: PRESETS > LIST's category (1.2, Discussion #90, ui.c ui_lcat: 0 none = ALL / FAV as favorites.filter says);
 * [15][0..9], [12] (1.6, #244: CUSTOM, a palette of the user's: five RGB565 colours little endian, flags: ui.c ui_cpal); older
 * firmware keeps the bytes as saved and shows the built-in palette in persist_t.palette.
 * [15][14..23]: the FX layer's key map (1.2, ui_layer.c fx_keys: 16 white keys x 5 bits, perform.c perf_map_of; 0 = the
 * key's default, an unknown code too: kept as saved, a later firmware's effect survives a round trip here).
 * MENU's flags (ui.c PREF_*) are append-only bits whose 0 is the default: BPM LOCK (16) is clear in every older setting
 * = unlocked, LARGE (32) = OFF, RESTORE LAST OFF (128, 1.2) = ON, read as saved (nothing to migrate, so importing twice changes nothing).
 *
 * PER6 (#212, the engine id space): the PER4 block, then persist_ext_t: a version, the stored counts, MIDI LEARN's map,
 * the device bytes and a favourites row per engine id (rows: FAV_ROWS = ENG_ID_MAX, 64), the authoritative copy. The
 * PER4 block still holds rows 0..13, the map and the device bytes as PER4 has them, so the first sizeof(persist_t)
 * bytes of a PER6 record with the magic PER4 are the PER4 record firmware up to 1.6 reads. A record is written as
 * PER4 while every favourite is on an engine id below 14 (always, without such an engine), else as PER6. Older
 * firmware does not read a PER6 record (its length): it starts with default settings, see web/EDITOR_PROTOCOL.md.
 * PER5 (an unmerged MACRO branch, #27: PER4 + MACRO's favourites row) is read: that row is engine 14's. */
#define PERSIST_BASE                                                    \
    uint32_t magic, palette, lowcut, zoom;                              \
    panel_t panel;                                                      \
    uint32_t bold;                                                      \
    struct { uint8_t factory[16][32]; uint32_t user, filter; } favorites;
typedef struct {
    PERSIST_BASE
} persist_t;
#define PERSIST_MAGIC 0x50455234u                 /* PER4: the record up to 1.6, the base of PER6 */
#define PERSIST_MAGIC_V5 0x50455235u              /* PER5: PER4 + 32 bytes, MACRO's row (kori/macro-engine, #27) */
#define PERSIST_MAGIC_EXT 0x50455236u             /* PER6: PER4 + persist_ext_t */
#define PERSIST_ROWS_V4 14u                       /* PER4's rows of engine favourites (0..13) */
#define PERSIST_EXT_VER 1u
typedef struct {
    uint8_t ver;                                  /* PERSIST_EXT_VER */
    uint8_t rows;                                 /* favourite rows stored: engine ids 0..rows-1 (1..FAV_ROWS) */
    uint8_t ml_n, dev_n;                          /* 32, 32: the bytes of ml and dev */
    uint8_t ml[32];                               /* MIDI LEARN's map (settings_ml) */
    uint8_t dev[32];                              /* the device bytes (settings_dev, PER4's row 15) */
    uint8_t fav[FAV_ROWS][32];                    /* the favourites of engine id r (preset bits, LSB first) */
} persist_ext_t;
#define PERSIST_EXT_HDR (4u + 32u + 32u)          /* persist_ext_t before fav */
/* a settings record as stored: the PER4 block (persist_t's fields: persist_rec_t * and persist_t * name the same
 * bytes) and the extension; its length is persist_len's */
typedef struct {
    PERSIST_BASE
    persist_ext_t x;
} persist_rec_t;
_Static_assert(sizeof(persist_ext_t) == PERSIST_EXT_HDR + FAV_ROWS * 32u, "persist_ext_t has no padding");
_Static_assert(sizeof(persist_rec_t) == sizeof(persist_t) + sizeof(persist_ext_t), "persist_rec_t: PER4 then the extension");
_Static_assert(FAV_ROWS <= 255u, "persist_ext_t.rows");
static uint32_t persist_len(const persist_rec_t *r)
{
    return r->magic == PERSIST_MAGIC_EXT ? (uint32_t)sizeof(persist_t) + PERSIST_EXT_HDR + r->x.rows * 32u
                                         : (uint32_t)sizeof(persist_t);
}
/* n bytes of a PER6 record at p (a persist_rec_t): its extension readable (version 1, the counts this firmware knows) */
static int persist_ext_ok(const persist_t *p, int n)
{
    const persist_ext_t *x = (const persist_ext_t *)(const void *)(p + 1);
    if (p->magic != PERSIST_MAGIC_EXT || n < (int)(sizeof *p + PERSIST_EXT_HDR))
        return 0;
    return x->ver == PERSIST_EXT_VER && x->ml_n == 32u && x->dev_n == 32u && x->rows >= 1u && x->rows <= FAV_ROWS &&
           n == (int)(sizeof *p + PERSIST_EXT_HDR + x->rows * 32u);
}

/* Normalize in place; 1 = current (PER4, PER6), 2 = migrated, 0 = invalid. n bytes at p: past sizeof *p (PER5, PER6)
 * p is a persist_rec_t. Only the PER4 block is normalized; a PER6 record's extension is read as it is. A PER6 record
 * whose extension this firmware cannot read (another version, other counts) is read by its PER4 block: rows 0..13,
 * the map and the device bytes as PER4 has them (migrated: written again as this firmware's) */
static int settings_import(persist_t *p, int n)
{
    const persist_ext_t *x = (const persist_ext_t *)(const void *)(p + 1);
    int ext = persist_ext_ok(p, n);
    int ext_other = !ext && n > (int)sizeof *p && n <= (int)sizeof(persist_rec_t) && p->magic == PERSIST_MAGIC_EXT;
    int per5 = n == (int)(sizeof *p + 32u) && p->magic == PERSIST_MAGIC_V5;
    int current = (n == (int)sizeof *p && p->magic == PERSIST_MAGIC) || ext;
    int old3 = n == (int)(sizeof *p - sizeof p->favorites) && p->magic == 0x50455233u;
    int old2 = n == (int)(sizeof *p - sizeof p->favorites - sizeof p->bold) && p->magic == 0x50455232u;
    int old1 = n == (int)(8u + sizeof(panel_t)) && p->magic == 0x50455231u;
    if (!(current || ext_other || per5 || old3 || old2 || old1)) return 0;
    if (old1) {
        panel_t old;
        memcpy(&old, (uint8_t *)p + 8, sizeof old);
        p->panel = old;
        p->lowcut = p->zoom = 0;
    }
    if (old1 || old2) p->bold = 0;
    if (old1 || old2 || old3) memset(&p->favorites, 0, sizeof p->favorites);
    if (ext) {                                     /* the extension's map, device bytes and rows 0..13 into the PER4 block */
        uint32_t r;
        memcpy(p->favorites.factory[14], x->ml, 32);
        memcpy(p->favorites.factory[15], x->dev, 32);
        for (r = 0; r < PERSIST_ROWS_V4; r++)
            if (r < x->rows) memcpy(p->favorites.factory[r], x->fav[r], 32);
            else memset(p->favorites.factory[r], 0, 32);
    }
    if (p->favorites.factory[15][29] > 1u)        /* STYLE (ui.c ui_style): 2, the retired PIXEL = LINE; unknown = FLAT */
        p->favorites.factory[15][29] = p->favorites.factory[15][29] == 2u ? 1u : 0u;
    {   /* CLICK, CLICK LEVEL, COUNT-IN (ui.c ui_rec_prefs): two bits each, 3 is no value: the default (0) */
        uint32_t b = p->favorites.factory[15][28], f;
        for (f = 0; f < 3u; f++)
            if (((b >> (2u * f)) & 3u) == 3u)
                b &= ~(3u << (2u * f));
        p->favorites.factory[15][28] = (uint8_t)b;
    }
    {   /* AUTO OFF: retain old 0..7 bytes, including legacy NEVER/unknown codes. A zero timer may remember MODE.
         * Malformed new targets/timer codes never enable ALL DARK; unknown or unordered ALL DARK disables only it. */
        uint32_t v = p->favorites.factory[15][27], low = v & 31u, time = low & 7u, target = low >> 3, dark = v >> 5;
        uint32_t idle = time == 2u ? 1u : time == 1u ? 2u : time == 4u ? 3u : time == 7u ? 4u : 0u;
        if (target > 2u || (target && time && !idle)) {
            low = 0;
            dark = 0;
        }
        if (dark > 4u || (time && !idle) || (idle && dark && dark <= idle))
            dark = 0;
        p->favorites.factory[15][27] = (uint8_t)(low | dark << 5);
    }
    if (p->favorites.factory[15][11] > 8u)         /* PRESETS LIST's category (1.2, ui.c ui_lcat, CAT_*): unknown = none */
        p->favorites.factory[15][11] = 0;
    /* [15][26] HOME (1.3, ui.c ui_home_view): kept as saved; a value this firmware does not know draws SCOPE */
    {   /* CUSTOM (1.6, #244, favorites.c ui_cpal): [15][0..9] five RGB565 colours, [12] bit 0 stored, bit 1 in use. Anything else
         * in [12], or colours without the stored flag: none (zero). The colours themselves are whatever the user chose */
        uint8_t *f = p->favorites.factory[15];
        f[12] &= 3u;
        if (!(f[12] & 1u)) {
            memset(f, 0, 10);
            f[12] = 0;
        }
    }
    if (!ext)
        p->magic = PERSIST_MAGIC;                  /* (PER6 stays PER6: its extension follows, persist_len) */
    p->palette = palette_to_stored(palette_from_stored(p->palette));
    settings.magic = SETTINGS_MAGIC;
    settings.palette = palette_from_stored(p->palette);
    settings.lowcut = p->lowcut;
    settings.zoom = p->zoom;
    settings_hold = (uint8_t)hold_from_stored(p->bold);
    settings_leds = (uint8_t)leds_from_stored(p->zoom);
    memcpy(settings_ml, p->favorites.factory[14], sizeof settings_ml);
    memcpy(settings_dev, p->favorites.factory[15], sizeof settings_dev);
#ifdef FELUCCA_FAVORITES
    {
        uint32_t r;
        memset(&favorites, 0, sizeof favorites);
        for (r = 0; r < PERSIST_ROWS_V4; r++)
            memcpy(favorites.factory[r], p->favorites.factory[r], 32);
        for (r = PERSIST_ROWS_V4; ext && r < x->rows; r++)   /* engine ids 14.. (kept whether this build has them) */
            memcpy(favorites.factory[r], x->fav[r], 32);
        if (per5)                                  /* PER5: MACRO's row, engine 14 (#27) */
            memcpy(favorites.factory[PERSIST_ROWS_V4], (const uint8_t *)(p + 1), 32);
        favorites.user = p->favorites.user;
        favorites.filter = p->favorites.filter == 1u;
    }
#if defined(FM4_NPRESETS) && !FELUCCA_FM4
    {   /* DIGITAL's starred presets (engine 1, retired) -> the FM6 presets that cover them (fm4_convert.c) */
        uint32_t k;
        for (k = 0; k < FM4_NPRESETS; k++)
            if ((favorites.factory[ENGI_DIGITAL][0] >> k) & 1u)
                favorites.factory[ENGI_FM6][FM4_TO_FM6[k] / 8u] |= (uint8_t)(1u << (FM4_TO_FM6[k] % 8u));
        memset(favorites.factory[ENGI_DIGITAL], 0, sizeof favorites.factory[ENGI_DIGITAL]);
    }
#endif
#ifdef SMP_SET_PERC
    if ((favorites.factory[ENGI_SAMPLE][0] >> SMP_SET_PERC) & 1u) {   /* SAMPLE's PERC (preset 4, retired): DRUM's */
        favorites.factory[ENGI_DRUM][0] |= 1u;                         /* kit (core.h drum_from_perc) */
        favorites.factory[ENGI_SAMPLE][0] &= (uint8_t)~(1u << SMP_SET_PERC);
    }
#endif
#endif
    if (p->panel.magic == PANEL_MAGIC) panel = p->panel;
    return current ? 1 : 2;
}

/* Start with the last imported/saved object, including fields owned by a
 * feature absent from this build. No save-on-boot or extra flash writes.
 * This is the PER4 record (magic PER4): favourites of engine ids 14.. are not in it (a downgrade's view;
 * settings_export_rec writes the whole record) */
static void settings_export(persist_t *p)
{
    p->magic = PERSIST_MAGIC;
    p->palette = palette_to_stored(settings.palette);
    p->lowcut = settings.lowcut;
    p->zoom = settings.zoom = leds_to_stored(settings.zoom, settings_leds);
    p->panel = panel;
    p->bold = hold_to_stored(p->bold, settings_hold);
#ifdef FELUCCA_FAVORITES
    {
        uint32_t r;
        for (r = 0; r < PERSIST_ROWS_V4; r++)
            memcpy(p->favorites.factory[r], favorites.factory[r], 32);
        p->favorites.user = favorites.user;
        p->favorites.filter = favorites.filter;
    }
#endif
    memcpy(p->favorites.factory[14], settings_ml, sizeof settings_ml);
    memcpy(p->favorites.factory[15], settings_dev, sizeof settings_dev);
}
/* the whole record: PER4 while every favourite is on an engine id below 14 (the extension then all 0), else PER6 */
static void settings_export_rec(persist_rec_t *r)
{
    uint32_t i, more = 0;
    settings_export((persist_t *)(void *)r);
    memset(&r->x, 0, sizeof r->x);
#ifdef FELUCCA_FAVORITES
    for (i = PERSIST_ROWS_V4 * 32u; i < sizeof favorites.factory; i++)
        more |= (&favorites.factory[0][0])[i];
#endif
    if (!more)
        return;
    r->magic = PERSIST_MAGIC_EXT;
    r->x.ver = PERSIST_EXT_VER;
    r->x.rows = FAV_ROWS;
    r->x.ml_n = r->x.dev_n = 32u;
    memcpy(r->x.ml, settings_ml, sizeof r->x.ml);
    memcpy(r->x.dev, settings_dev, sizeof r->x.dev);
#ifdef FELUCCA_FAVORITES
    memcpy(r->x.fav, favorites.factory, sizeof r->x.fav);
#endif
    (void)i;
}
