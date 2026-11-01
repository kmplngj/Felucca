/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Felucca menu (HOME held): its rows in tabs (1.0.5: DISPLAY CONTROL AUDIO SYSTEM; 1.2: MIDI before SYSTEM; ALGORITHM
 * between them, PRESETS within one; no scrolling), the rows in menu_items.c (the settings, shared with the editor's
 * MENU_DESC / MENU_SET; 1.2: TUNE and MIDI IN, the project's). No BACK row: HOME closes it (ui_input.c). The two-valued
 * rows are bits of ui_prefs (MENU_FLAGS). PRESETS scrolls from ABOUT through all credits (OCT- back to the tabs).
 * ui.menu: 1 the tabs, 2 ABOUT (information and credits), 3 INFO (1.2: the device's state, the old SYSTEM page's USB and
 * CPU readings), 4 AUTO OFF (five editable/detail rows, explicit BACK). */
/* ------------------------------------------------------------ menu --- */
/* (the rows, their values and names, usb_serial_apply: menu_items.c) */
enum { MENU_OFF = 4 };
enum { MO_IDLE, MO_MODE, MO_DARK, MO_WAKE, MO_BACK, MO_COUNT };
static uint8_t menu_off_sel, menu_off_error;
static int menu_has_value(void)
{
    return ui.menu == MENU_OFF ? menu_off_sel < MO_BACK : menu_valued(ui.menu_sel) && ui.menu_sel != MI_SCROFF;
}
static uint32_t menu_off_get(uint32_t row)
{
    return row == MO_IDLE ? scr_idle_get() : row == MO_MODE ? scr_mode_get() :
           row == MO_DARK ? scr_dark_get() : row == MO_WAKE ? menu_get(MI_SCRWAKE) : 0u;
}
static uint32_t menu_off_n(uint32_t row) { return row == MO_MODE ? 3u : row == MO_WAKE ? 2u : row == MO_BACK ? 0u : 5u; }
static int menu_off_put(uint32_t row, uint32_t v)
{
    if (row >= MO_BACK || v >= menu_off_n(row)) return 0;
    int ok = row == MO_IDLE ? scr_idle_put(v) : row == MO_MODE ? scr_mode_put(v) :
             row == MO_DARK ? scr_dark_put(v) : row == MO_WAKE ? menu_try_put(MI_SCRWAKE, v) : 0;
    menu_off_error = (uint8_t)!ok;
    ui.force = 1;
    return ok;
}
static uint32_t menu_off_next(uint32_t row, int32_t s)
{
    uint32_t v = menu_off_get(row), n = menu_off_n(row);
    int32_t next, step = (s > 0) - (s < 0);
    if (!s || !n) return v;
    if (row == MO_WAKE) return menu_step(MI_SCRWAKE, s);
    /* Walk at most five timer values. NEVER is independent; enabled ALL DARK must be later than IDLE. */
    for (next = (int32_t)v + step; next >= 0 && next < (int32_t)n; next += step)
        if ((row != MO_IDLE || !next || !scr_dark_get() || (uint32_t)next < scr_dark_get()) &&
            (row != MO_DARK || !next || !scr_idle_get() || (uint32_t)next > scr_idle_get()))
            return (uint32_t)next;
    return v;
}
static void menu_off_step(int32_t s)
{
    if (s && menu_off_sel < MO_BACK)
        menu_off_put(menu_off_sel, menu_off_next(menu_off_sel, s));
}
static void menu_off_open(void)
{
    ui.menu = MENU_OFF;
    ui.menu_sel = MI_SCROFF;
    menu_off_sel = menu_off_error = 0;
    ui.force = 1;
}
static void menu_off_back(void)
{
    ui.menu = 1;
    ui.menu_sel = MI_SCROFF;
    menu_off_error = 0;
    ui.force = 1;
}

/* All notices are in flash. Wrap at the font's actual width, without dropping URL
 * characters; the same layout computes the scroll limit and draws clipped bands.
 * Mixed case here (long text); S throughout, the title in L. */
#define MENU_DOC_H 196                                /* the document: screen rows 24..220 */
enum { MC_TEXT, MC_TITLE, MC_URL };
typedef struct { const char *text; uint8_t kind; } menu_credit_t;
static const menu_credit_t MENU_CREDITS[] = {
    {"H\xFCgelton Instruments", MC_TITLE},  /* Felucca's own: above; these are ours too */
    {"Leo Kuroshita", MC_TEXT},
    {"The PHASE and DRUM engines: GPL-3.0-only", MC_TEXT},
    {"The Sample Pack: CC0 1.0", MC_TEXT},
    {"Fukiai icon font: MIT", MC_TEXT},
    {"https://github.com/hugelton", MC_URL},
    {"", MC_TEXT},
    {"KLATTSCH", MC_TITLE},
    {"Tony Gies / MIT", MC_TEXT},
    {"https://github.com/tgies/klattsch", MC_URL},
    {"", MC_TEXT},
    {"DAISYSP", MC_TITLE},
    {"Electrosmith, Emilie Gillet", MC_TEXT},
    {"MIT", MC_TEXT},
    {"https://github.com/electro-smith/DaisySP", MC_URL},
    {"", MC_TEXT},
    {"DEXED + MSFA", MC_TITLE},
    {"Pascal Gauthier, Google Inc.", MC_TEXT},
    {"msfa: Apache-2.0, Dexed: GPL-3.0", MC_TEXT},
    {"https://github.com/asb2m10/dexed", MC_URL},
    {"", MC_TEXT},
    {"RINGS", MC_TITLE},
    {"Emilie Gillet / MIT", MC_TEXT},
    {"https://github.com/pichenettes/eurorack", MC_URL},
    {"", MC_TEXT},
#if FELUCCA_PROFILE_ENGINE_14 && FELUCCA_ENG_OMIT != 14
    {"BRAIDS (MACRO)", MC_TITLE},
    {"Emilie Gillet / MIT", MC_TEXT},
    {"https://github.com/pichenettes/eurorack", MC_URL},
    {"", MC_TEXT},
#endif
    /* Native text and keycap legends share the M8Stealth family. */
    {"M8STEALTH", MC_TITLE},
    {"Trash80 / CC BY-SA 3.0", MC_TEXT},
    {"With local extra bitmap marks", MC_TEXT},
    {"https://fontstruct.com/fontstructors/100463/trash80", MC_URL},
    {"", MC_TEXT},
    {"VSCO-2 CE + VCSL", MC_TITLE},
    {"Versilian Studios / CC0 1.0", MC_TEXT},
    {"https://github.com/sgossner/VSCO-2-CE", MC_URL},
    {"https://github.com/sgossner/VCSL", MC_URL},
    {"", MC_TEXT},
    {"VOICE", MC_TITLE},
    {"Dennis H. Klatt (1980)", MC_TEXT},
    {"https://doi.org/10.1121/1.383940", MC_URL},
    {"Hillenbrand, Getty, Clark and Wheeler (1995)", MC_TEXT},
    {"https://doi.org/10.1121/1.411872", MC_URL},
};

static int32_t menu_text(const char *s, int32_t y, uint16_t col, int draw)
{
    while (*s) {
        char line[64];
        uint32_t n = 0, space = 0, take, prev = 0;
        int32_t pen = 0;                                 /* 1/16 px, as text_w adds it up */
        while (s[n] && n < sizeof line - 1u) {
            uint32_t c = (uint8_t)s[n];
            line[n] = s[n];
            line[n + 1u] = 0;
            pen += (prev ? kern(&AF_S, prev, c) : 0) + AF_S.g[glyph(&AF_S, c)].adv;
            prev = c;
            if ((pen + 8) >> 4 > 226)
                break;
            if (s[n] == ' ')
                space = n;
            n++;
        }
        take = s[n] && space ? space : n;
        if (!take) take = 1;                         /* progress even for an unusually wide glyph */
        line[take] = 0;
        if (draw && y + AF_S.h > 0 && y < MENU_DOC_H)
            cv_text(6, y, &AF_S, line, col);
        y += 18;
        s += take;
        while (*s == ' ') s++;
    }
    return y;
}

static int32_t menu_document(int32_t y, int draw)
{
    uint32_t i;
    if (draw) {
        cv_text(6, y + 2, &AF_L, "FELUCCA", T_THEME);
        cv_text(6, y + 38, &AF_S, "Multi-engine synthesizer", T_TEXT);
        cv_text(6, y + 58, &AF_M, FELUCCA_VERSION, T_THEME);
        cv_text(6, y + 80, &AF_S, FELUCCA_BUILD_ID, T_TEXT);
        if (FELUCCA_BUILD_PR[0])
            cv_text_r(232, y + 80, &AF_S, FELUCCA_BUILD_PR, T_MID, T_BG);
    }
    y = menu_text("SOURCE", y + 104, T_THEME, draw);
    y = menu_text(FELUCCA_SOURCE_REPOSITORY, y, T_MID, draw);
    y = menu_text("GPL-3.0-only", y + 8, T_TEXT, draw);
    y = menu_text("(C) 2026 Leo Kuroshita", y + 8, T_TEXT, draw);
    y = menu_text("H\xFCgelton Instruments", y, T_TEXT, draw);
    y = menu_text("CREDITS", y + 20, T_THEME, draw) + 8;
    for (i = 0; i < NELEM(MENU_CREDITS); i++) {
        const menu_credit_t *c = &MENU_CREDITS[i];
        const char *text = c->text;
        /* Display host/path once; the full source URL stays in the flash table. */
        if (c->kind == MC_URL && str_len(text) >= 8u && !memcmp(text, "https://", 8))
            text += 8;
        if (!text[0]) y += 8;
        else y = menu_text(text, y, c->kind == MC_TITLE ? T_THEME : c->kind == MC_URL ? T_MID : T_TEXT, draw);
    }
    y = menu_text("LICENSES + SOURCE", y + 12, T_THEME, draw);
    y = menu_text("PHASE + DRUM: GPL-3.0-only", y, T_TEXT, draw);
    y = menu_text("H\xFCgelton Sample Pack: CC0 1.0", y, T_TEXT, draw);
    y = menu_text("Fonts and icons: their licences travel with the source and the release files.", y, T_TEXT, draw);
    y = menu_text("NO WARRANTY", y, T_TEXT, draw);
    y = menu_text("Full notices in source:", y + 8, T_TEXT, draw);
    y = menu_text(FELUCCA_SOURCE_REPOSITORY, y, T_MID, draw);
    return y + 4;
}
static int32_t menu_scroll_max(void)
{
    int32_t h = menu_document(0, 0);
    return h > MENU_DOC_H ? h - MENU_DOC_H : 0;
}

/* the menu's header (0..24): its icon and title, the REC mark, the way back (the tabs: HOME CLOSE before the dots) */
static void menu_head(void)
{
    cv_begin(240, H_HEAD, T_BG);
    GFX_HOOK_ALIGN(0, HEAD_MY + AF_M_CAP_Y, 0, HEAD_MY + AF_M_CAP_Y + AF_M_CAP_H, AL_V, "header icon on its title's line");
    cv_icon_mid(8, H_HEAD / 2, 16, ui.menu == 2 || ui.menu == 3 ? ICON_X_INFO : ICON_X_COG, T_THEME, T_BG);
    GFX_HOOK_ALIGN(0, 0, 0, H_HEAD, AL_V, "header text on its middle");
    cv_text(30, HEAD_MY, &AF_M, ui.menu == MENU_OFF ? "AUTO OFF" : ui.menu == 3 ? "INFO" : ui.menu == 2 ? "ABOUT / CREDITS" : "MENU", T_TEXT);
    if (ui.menu == 2 || ui.menu == 3) {                /* the way back at the right, the REC mark before it (then */
        const char *w = song.rec ? 0 : "BACK";        /* the keycap goes without its word: no room for both) */
        int32_t x = 232 - kh_w(KC_OCTDN, w);
        GFX_HOOK_ALIGN(0, 0, 0, H_HEAD, AL_V, "header text on its middle");
        cv_key_hint(x, HALF_UP(H_HEAD - KC_H), KC_OCTDN, w, 1, T_BG);
        draw_rec_mark(x - 20, T_BG);
    } else {
        int32_t x = 232 - kh_w(KC_HOME, "CLOSE");     /* (#572: the tab bar says the tab; no dots) */
        GFX_HOOK_ALIGN(0, 0, 0, H_HEAD, AL_V, "header text on its middle");
        cv_key_hint(x, HALF_UP(H_HEAD - KC_H), KC_HOME, "CLOSE", 1, T_BG);
        draw_rec_mark(x - 20, T_BG);
    }
    cv_blit(0, Y_HEAD);
}

/* MENU: native header, the tab names with a sliding underline (#572), seven uniform rows and bottom key hints.
 * Selection never changes row height; rows are fully composed
 * before transfer within the existing 124-row canvas. INFO and ABOUT retain
 * their own bounded content bands. */
#define MT_Y 29                                        /* the tab bar */
#define MT_H 24
#define MT_X0 6
#define MT_X1 234
#define MT_ONE 64                                      /* mt.pos per tab */
#define MP_Y 59                                        /* the rows' panel */
#define MP_PAD 3
#define MR_X 8                                         /* a row */
#define MR_W 224
#define MR_LX 16                                       /* its label */
#define MR_VR 224                                      /* its value's right edge */
#define MK_Y 224                                       /* the key hints */
static uint32_t menu_tab(void) { return MI_TAB[ui.menu_sel % MI_COUNT]; }

/* the tab bar's place: the tab shown at pos tab * MT_ONE; with ANIM ON it follows in halving steps, a frame each
 * (a frame missed, as when the menu opens: it snaps, as ui_graph.c pr_follow) */
static struct { int16_t pos; uint32_t frame; } mt;
static void mt_follow(void)
{
    int32_t want = (int32_t)menu_tab() * MT_ONE, d = want - mt.pos;
    if (ui.frame != mt.frame + 1u || (ui_prefs & PREF_ANIM_OFF) || (d < 3 && d > -3))
        mt.pos = (int16_t)want;
    else
        mt.pos = (int16_t)(mt.pos + d / 2);
    mt.frame = ui.frame;
}
/* #572: the five tabs' names (S) justified across MT_X0..MT_X1, the shown one TEXT over an accent underline that
 * slides with mt.pos (ANIM ON); the others MID. a: each one's share of the shown look (0 .. MT_ONE), x: its pen, w */
static void mt_layout(int32_t *a, int32_t *x, int32_t *w)
{
    uint32_t k;
    int32_t tot = 0, cum = MT_X0, gap;
    for (k = 0; k < MTAB_COUNT; k++) {
        int32_t d = mt.pos - (int32_t)k * MT_ONE;
        a[k] = MT_ONE - (d < 0 ? -d : d);
        if (a[k] < 0) a[k] = 0;
        w[k] = ink_w(&AF_S, MTAB_NAME[k]);
        tot += w[k];
    }
    gap = (MT_X1 - MT_X0 - tot) / (int32_t)(MTAB_COUNT - 1u);
    for (k = 0; k < MTAB_COUNT; k++) {
        x[k] = k + 1u == MTAB_COUNT ? MT_X1 - w[k] : cum;
        cum += w[k] + gap;
    }
}
#define MT_TY (MT_Y + CAP_IN(S, MT_H))                    /* the names' line top; the underline 3 px under their capitals */
static void menu_tabs(void)                            /* (in screen rows: cv_oy set by the caller) */
{
    int32_t a[MTAB_COUNT], x[MTAB_COUNT], w[MTAB_COUNT], i = mt.pos / MT_ONE, f = mt.pos % MT_ONE, lx, lw;
    int32_t uy = MT_TY + AF_S_CAP_Y + AF_S_CAP_H + 3;
    uint32_t k;
    mt_layout(a, x, w);
    cv_rule(4, MP_Y - 3, 232, 1);                      /* a rule under the tabs */
    for (k = 0; k < MTAB_COUNT; k++) {
        int on = k == (uint32_t)((mt.pos + MT_ONE / 2) / MT_ONE);   /* (half way, the shown look moves over) */
        GFX_HOOK_ALIGN(0, MT_Y, 0, MT_Y + MT_H, AL_V | AL_PASS, "menu tab names on one line");
        cv_text_on(x[k], MT_TY, &AF_S, MTAB_NAME[k], on ? T_TEXT : T_MID, T_BG);
    }
    if (i + 1 >= (int32_t)MTAB_COUNT) { i = (int32_t)MTAB_COUNT - 1; f = 0; }
    lx = x[i] + (f ? (x[i + 1] - x[i]) * f / MT_ONE : 0);
    lw = w[i] + (f ? (w[i + 1] - w[i]) * f / MT_ONE : 0);
    cv_rect(lx, uy, lw, 2, T_ACCENT);
}

static void menu_off_summary(char *b)
{
    uint32_t a = scr_idle_get(), d = scr_dark_get(), n;
    if (!(a | d)) {
        str_cpy(b, "NEVER", 16);
        return;
    }
    str_cpy(b, OFF_SHORT_N[a], 16);
    n = str_len(b);
    str_cpy(b + n, " / ", 16u - n);
    n = str_len(b);
    str_cpy(b + n, OFF_SHORT_N[d], 16u - n);
}
#include "ui_menu_reading.c"                           /* #577: uniform settings rows and selective choice pages */
/* MENU > SYSTEM > INFO (1.2, ui.menu 3): what the old GLO > SYSTEM page showed, read only: the firmware, the USB link (the
 * SYSTEM page's MIDI card: OFF no USB, WAIT no bus yet, BUS frames seen, ENUM being set up, MIDI in use) and the CPU load
 * of the audio (its SYSTEM card; the shown value follows every INFO_CPU_MS, not every frame). The rows as the menu's (no
 * tabs: from INFO_Y), the selected look on none; OCT- back to the tabs, HOME closes */
#define INFO_Y 32
#define INFO_N (FELUCCA_BUILD_PR[0] ? 4u : 3u)
#define INFO_CPU_MS 500u
static struct { uint8_t cpu; uint32_t t; } info;
static uint32_t info_usb(void)                         /* 0 OFF, 1 WAIT, 2 BUS, 3 ENUM, 4 MIDI */
{
    return !usb.up ? 0u : usb.config ? 4u : usb.setups ? 3u : usb.sof_seen ? 2u : 1u;
}
static uint32_t info_sig(void)
{
    if (fm1_ms - info.t >= INFO_CPU_MS) {
        info.t = fm1_ms;
        info.cpu = (uint8_t)(song.cpu_q8 * 100u / 256u);
    }
    return info.cpu * 7u + info_usb() * 131u + 1u;
}
static void info_rows(void)                            /* (in screen rows: cv_oy set by the caller) */
{
    static const char *const LBL[] = {"FIRMWARE", "COMMIT", "USB", "CPU"};
    static const char *const USB_N[5] = {"OFF", "WAIT", "BUS", "ENUM", "MIDI"};
    int32_t h = 28;
    int32_t identity_h = h * (text_w(&AF_S, FELUCCA_SPLASH_ID) > MR_VR - MR_LX ? 2 : 1);
    uint32_t k;
    char cpu[8];
    fmt_int(cpu, info.cpu);
    if (!ux.style)                                     /* FLAT: the rows' panel */
        cv_rrect(4, INFO_Y, 232, (int32_t)INFO_N * (h + 2) + identity_h - 2 + 2 * MP_PAD, 8, T_SURF, T_BG);
    for (k = 0; k < INFO_N; k++) {
        uint32_t row = k && !FELUCCA_BUILD_PR[0] ? k + 1u : k;
        int32_t y = INFO_Y + MP_PAD + (int32_t)k * (h + 2) + (k ? identity_h : 0), vy = y + CAP_IN(M, h);
        if (k)
            cv_rect(MR_X + 6, y - 1, MR_W - 12, 1, ux.style ? T_RULE : T_LINE);
        GFX_HOOK_ALIGN(0, y, 0, y + h, AL_V, "info row name centred up/down");
        cv_text_on(MR_LX, vy, &AF_M, LBL[row], T_TEXT, T_SURF);
        if (!row) {
            /* Keep the full identity below its label: release versions and PR
             * labels can be wider than a menu value. PR builds also name the
             * actual compiled commit in the following row. */
            const aafont_t *f = text_w(&AF_M, FELUCCA_SPLASH_ID) <= MR_VR - MR_LX ? &AF_M : &AF_S;
            const char *value = FELUCCA_SPLASH_ID, *tail = "";
            char prefix[32];
            if (identity_h > h) {                       /* bounded release version: wrap without losing characters */
                uint32_t n;
                str_cpy(prefix, value, sizeof prefix);
                n = str_len(prefix);
                while (n && text_w(f, prefix) > MR_VR - MR_LX)
                    prefix[--n] = 0;
                tail = value + n;
                value = prefix;
            }
            GFX_HOOK_ALIGN(0, y + h, 0, y + 2 * h, AL_V, "info firmware identity centred up/down");
            cv_text_r(MR_VR, y + h + (f == &AF_M ? CAP_IN(M, h) : CAP_IN(S, h)), f,
                      value, T_THEME, T_SURF);
            if (tail[0]) {
                GFX_HOOK_ALIGN(0, y + 2 * h, 0, y + 3 * h, AL_V, "info firmware continuation centred up/down");
                cv_text_r(MR_VR, y + 2 * h + CAP_IN(S, h), &AF_S, tail, T_THEME, T_SURF);
            }
            continue;
        }
        GFX_HOOK_ALIGN(0, y, 0, y + h, AL_V, "info row value centred up/down");
        if (row == 3u) {                               /* CPU: the value and its unit, as HOLD's */
            GFX_HOOK_ALIGN(0, 0, 0, vy + AF_M.asc, AL_B, "info row unit on its value's baseline");
            cv_text_r(cv_text_r(MR_VR, vy + AF_M.asc - AF_S.asc, &AF_S, "%", T_MID, T_SURF) - UI_VALUE_UNIT_GAP,
                      vy, &AF_M, cpu, T_THEME, T_SURF);
        } else if (row == 1u) {
            cv_text_r(MR_VR, y + CAP_IN(S, h), &AF_S, FELUCCA_BUILD_ID, T_THEME, T_SURF);
        } else {
            cv_text_r(MR_VR, vy, &AF_M, USB_N[info_usb()], T_THEME, T_SURF);
        }
    }
}

static void draw_menu(void)
{
    static const khint_t KEYS[3][3] = {{{KC_ALGO, "TAB"}, {KC_PRESETS, "ROW"}, {KC_K1, "VALUE"}},
                                       {{KC_ALGO, "TAB"}, {KC_PRESETS, "ROW"}, {KC_OCTUP, "OPEN"}},
                                       {{KC_ALGO, "TAB"}, {KC_PRESETS, "ROW"}, {KC_OCTUP, "CLEAR"}}};
    uint32_t pass, sig;
    int32_t pos0 = mt.pos;
    if (ui.menu == 1)
        mt_follow();
    sig = ui.menu * 7u + ui.menu_sel * 131u + palette_cur() * 1009u + settings.lowcut * 7919u + settings_hold * 3511u +
          settings_leds * 6151u + ui_leds_inv * 12289u + ui_prefs * 4099u + ui_style * 257u + song.rec * 65537u + song.sel * 13u +
          ui_rec_prefs * 92821u + ui_scr * 131071u +          /* (#157: SCREEN OFF's value redraws its row) */
          ui_prefs2 * 524287u + ui_idle * 1048573u +      /* (1.2: ANIM IDLE's value redraws its row) */
          ui_home_view * 7340033u +    /* (1.3: HOME) */
          (uint32_t)(song.g[G_TUNE] + 64) * 8191u + (uint32_t)song.g[G_ROUTE] * 27449u +   /* (1.2: the project's rows) */
          (song.mch[0] | (uint32_t)song.mch[1] << 8 | (uint32_t)song.mch[2] << 16 | (uint32_t)song.mch[3] << 24) *
          2246822519u +                                   /* (1.5.5: T1..T4 CHANNEL) */
          scr_dark_get() * 67867967u + scr_mode_get() * 2147483647u +
          (ui.menu == MENU_OFF ? menu_off_sel * 48611u + menu_off_error * 374761393u : 0u) +
          (ui.menu == 2 ? ui.menu_scroll * 48611u : 0u) + (ui.menu == 3 ? info_sig() * 2654435761u : 0u);
    if (!ui.force && sig == ui.menu_sig) {
        if (ui.menu == 1 && mt.pos != pos0) {          /* only the tabs slid: their strip */
            cv_begin(240, MP_Y - H_HEAD, T_BG);
            cv_oy = -H_HEAD;
            menu_tabs();
            cv_oy = 0;
            cv_blit(0, H_HEAD);
        }
        return;
    }
    ui.menu_sig = sig;
    menu_head();
    if (ui.menu == MENU_OFF) {
        static const khint_t OFF_KEYS[2][2] = {{{KC_PRESETS, "ROW"}, {KC_OCTPM, "VALUE"}},
                                               {{KC_PRESETS, "ROW"}, {KC_OCTUP, "OPEN"}}};
        menu_reading_off(OFF_KEYS[!menu_has_value()]);
        return;
    }
    if (ui.menu == 3) {                                /* INFO: identity and live state span both bands */
        for (pass = 0; pass < 2u; pass++) {
            uint32_t top_y = pass ? 132u : (uint32_t)H_HEAD;
            cv_begin(240, pass ? 240u - 132u : 132u - H_HEAD, T_BG);
            cv_oy = -(int32_t)top_y;
            info_rows();
            cv_oy = 0;
            cv_blit(0, top_y);
        }
        return;
    }
    if (ui.menu == 2) {
        int32_t scroll = ui.menu_scroll, max = menu_scroll_max();
        int32_t thumb = MENU_DOC_H * MENU_DOC_H / (max + MENU_DOC_H);
        if (thumb < 12) thumb = 12;
        for (pass = 0; pass < 2u; pass++) {
            cv_begin(240, pass ? MENU_DOC_H - 124u : 124u, T_BG);
            cv_oy = pass ? -124 : 0;
            cv_scroll = 1;
            menu_document(-scroll, 1);
            cv_scroll = 0;
            cv_rrect(235, 2, 3, MENU_DOC_H - 4, 1, T_LINE, T_BG);           /* the scroll bar */
            cv_rrect(235, 2 + (max ? scroll * (MENU_DOC_H - 4 - thumb) / max : 0), 3, thumb, 1, T_MID, T_LINE);
            cv_oy = 0;
            cv_blit(0, H_HEAD + pass * 124u);
        }
        cv_begin(240, 240 - (H_HEAD + MENU_DOC_H), T_BG);
        cv_key_hint(8, 4, KC_PRESETS, "SCROLL", 1, T_BG);
        cv_blit(0, H_HEAD + MENU_DOC_H);
        return;
    }
    menu_reading_list(KEYS[ui.menu_sel == MI_LCLEAR ? 2 : !menu_has_value()]);
}

static void enc_drop(void)                             /* knob turns nobody takes */
{
    uint32_t k;
    for (k = 0; k < NE; k++)
        panel_enc(k);
}

static void menu_close(void)
{
    settings_save();                                   /* palette / panel table, if changed */
    ui.menu = 0;
    ui.force = 1;
    go_home();
}

/* menu: ALGORITHM steps between the tabs, PRESETS between the rows of one (both wrap; a tab comes back at the row
 * last picked in it), any of KNOB 1..4 or OCT+ / OCT- change a value (menu_items.c menu_step), OCT+ opens CALIBRATION /
 * INFO / ABOUT / AUTO OFF (OCT- nothing there); OCT- in INFO and ABOUT goes back to the tabs. AUTO OFF keeps
 * OCT-/+ for values and uses its BACK action. HOME closes every page
 * (ui_input.c). COLOR and LEDS retain immediate knob edits; OCT+ opens a choice
 * page instead of stepping. There PRESETS/knobs pick, OCT+ applies, OCT- cancels. */
static void menu_move(int32_t s)                       /* PRESETS: the next / previous row of the tab */
{
    uint32_t t = menu_tab(), n = mtab_rows(t), k = (mtab_index(ui.menu_sel) + (s > 0 ? 1u : n - 1u)) % n;
    ui.menu_sel = (uint8_t)mtab_row(t, k);
    ui.menu_row[t] = (uint8_t)k;
}
static void menu_tab_go(int32_t s)                     /* ALGORITHM: the next / previous tab, at its last row */
{
    uint32_t t = menu_tab(), k;
    ui.menu_row[t] = (uint8_t)mtab_index(ui.menu_sel);
    t = (t + (s > 0 ? 1u : MTAB_COUNT - 1u)) % MTAB_COUNT;
    k = ui.menu_row[t] < mtab_rows(t) ? ui.menu_row[t] : 0u;
    ui.menu_sel = (uint8_t)mtab_row(t, k);
}
static void menu_input(uint32_t oct)                  /* oct: ui_input.c oct_taps */
{
    int32_t s;
    uint32_t k, up = (oct >> 1) & 1u, dn = oct & 1u;
    if (ui.menu == MENU_OFF) {
        if ((s = panel_enc(EN_PRESET)) != 0) {
            menu_off_sel = (uint8_t)((menu_off_sel + (s > 0 ? 1u : MO_COUNT - 1u)) % MO_COUNT);
            menu_off_error = 0;
        }
        for (s = 0, k = 0; k < 4u; k++)
            s += panel_enc(EN_K1 + k);
        if (menu_has_value())
            menu_off_step(s + (int32_t)up - (int32_t)dn);
        else if (up)
            menu_off_back();
        enc_drop();
        return;
    }
    if (ui.menu >= 2) {                                /* ABOUT: PRESETS scrolls (bounded); INFO, ABOUT: OCT- back to
                                                        * the tabs */
        if (dn)
            ui.menu = 1, ui.force = 1;
        else if (ui.menu == 2 && (s = panel_enc(EN_PRESET)) != 0)
            ui.menu_scroll = (uint16_t)clamp((int32_t)ui.menu_scroll + clamp(s, -128, 128) * 18, 0, menu_scroll_max());
        enc_drop();
        return;
    }
    if ((s = panel_enc(EN_PRESET)) != 0)
        menu_move(s);
    if ((s = panel_enc(EN_ALGO)) != 0)
        menu_tab_go(s);
    for (s = 0, k = 0; k < 4u; k++)                    /* KNOB 1..4, any of them */
        s += panel_enc(EN_K1 + k);
    if (menu_has_value()) {
        /* One direct-edit rule for every value row. FX LATCH is off while MENU is up. */
        s += (int32_t)up - (int32_t)dn;
        if (s)
            menu_put(ui.menu_sel, menu_step(ui.menu_sel, s));
    } else if (up) {
        if (ui.menu_sel == MI_SCROFF) {
            menu_off_open();
        } else if (ui.menu_sel == MI_LCLEAR) {         /* LEARN CLEAR (1.5): every learned CC; 1.8: the dialog first */
            if (ml_count()) {
                menu_close();
                confirm_open(CF_LEARN_CLEAR, 0);
            } else {
                ui_message("NOTHING LEARNED");
            }
        } else if (ui.menu_sel == MI_CLRALL) {          /* CLEAR ALL (1.8, #266): the dialog, out of the menu */
            menu_close();
            confirm_open(CF_CLEAR_ALL, 0);
        } else if (ui.menu_sel == MI_PANEL) {
            panel_setup();
            scrn.idle = fm1_ms;                         /* (SCREEN OFF: its own loop had the input) */
            ui.force = 1;
        } else if (ui.menu_sel == MI_INFO) {
            ui.menu = 3;
            info.t = fm1_ms - INFO_CPU_MS;              /* (the CPU load read at once) */
            ui.force = 1;
        } else {                                       /* MI_ABOUT */
            ui.menu = 2;
            ui.menu_scroll = 0;
            ui.force = 1;
        }
    }
    enc_drop();                                        /* swallow the rest while the menu is up */
}
