/* SPDX-License-Identifier: GPL-3.0-only */
/* Native parameter bank (#572). Collect the existing column outputs, then draw
 * a focused reading path and four spatial overview cells. Main-loop UI state
 * only; no second formatter, edit path, framebuffer or persistent preference. */
#define BANK_W 234
#define BANK_TOP 22
#define BANK_OV (CARD_H - BANK_TOP)
#define BANK_VALUE_W 106
#define BANK_LABEL_W 74
#ifndef BANK_HOOK
#define BANK_HOOK(c, value, face) ((void)0)
#endif


static int bank_on(void)
{
    return !ui.layer && (large_kind() == LK_BANK || ((ui_prefs & PREF_LARGE) && lock_held()));
}
static const aafont_t *bank_font(unsigned f) { return f == 0u ? &AF_L : f == 1u ? &AF_M : &AF_S; }
static int bank_cap(const aafont_t *f)
{
    return f == &AF_L ? AF_L_CAP_H : f == &AF_M ? AF_M_CAP_H : AF_S_CAP_H;
}
static void bank_text(int x, int y, const aafont_t *f, const char *s, uint16_t fg, uint16_t bg)
{
    cv_text_on(x, y - (f == &AF_L ? AF_L_CAP_Y : f == &AF_M ? AF_M_CAP_Y : AF_S_CAP_Y), f, s, fg, bg);
}
static unsigned bank_big_face(const char *s)
{
    return AF_L_CAP_H <= BANK_TOP - 2 && large_face_has(s) && ink_w(&AF_L, s) <= BANK_VALUE_W ? 0u :
           ink_w(&AF_M, s) <= BANK_VALUE_W ? 1u : 2u;
}
static unsigned bank_small_face(const char *s)
{
    return AF_M_CAP_H + AF_S_CAP_H + 3 <= BANK_OV && ink_w(&AF_M, s) <= COL_W - 4 ? 1u : 2u;
}
static void bank_collect(uint32_t c, const char *label, const char *val, const char *unit,
                         uint16_t color, int motion, const card_span_t *sp)
{
    bank_field_t *f = &ui.read_bank.field[c];
    uint32_t key = str_hash(str_hash((uint32_t)(uintptr_t)sp->fn * 31u + (uint32_t)(uintptr_t)sp->p * 7u +
                                    (uint32_t)sp->lo * 131u + (uint32_t)sp->hi * 8191u + (uint32_t)sp->ctx * 524287u +
                                    song.sel + TSEL->eng_req * 4u, label), unit);
    if (!f->key || f->key != key) {
        f->key = key;
        f->face = 0; f->small = 1;
        if (sp->fn) {
            char s[16];
            for (int32_t v = sp->lo; v <= sp->hi; v++) {
                unsigned big, small;
                sp->fn(sp, v, s);
                big = bank_big_face(s); small = bank_small_face(s);
                if (big > f->face) f->face = (uint8_t)big;
                if (small > f->small) f->small = (uint8_t)small;
            }
        }
    }
    /* Non-parameter counters/actions have no declared span. The caller supplies
     * spans for editable domains; the actual text still has to fit this frame. */
    if (bank_big_face(val) > f->face) f->face = (uint8_t)bank_big_face(val);
    if (bank_small_face(val) > f->small) f->small = (uint8_t)bank_small_face(val);
    BANK_HOOK(c, val, f->face);
    str_cpy(f->label, label, sizeof f->label);
    str_cpy(f->value, val, sizeof f->value);
    str_cpy(f->unit, unit, sizeof f->unit);
    f->color = color; f->motion = (uint8_t)motion; f->lock = ui.read_bank.lock_next;
    f->fixed = sp->fn && sp->lo == sp->hi;
    ui.read_bank.lock_next = 0;
    if (label[0] || val[0]) ui.read_bank.mask |= (uint8_t)(1u << c);
    ui.col[c][0] = 0;                                  /* switching back to ordinary cards must repaint them */
    ui.roll[c].from[0] = 0;
}
static void bank_status(char *s, const bank_field_t *f)
{
    const char *state = f->motion ? "AUTO" : f->fixed ? "FIXED" : f->color == T_DIM ? "INACTIVE" : "VALUE";
    s[0] = 'K'; s[1] = (char)('1' + ui.read_bank.focus); s[2] = ' '; s[3] = 0;
    if (f->lock) {
        uint64_t held = lock_held();
        unsigned step = 0;
        while (step < NSTEP && !((held >> step) & 1u)) step++;
        str_cpy(s + 3, f->lock == 2u ? "LOCK" : "BASE", 6);
        fmt_int(s + str_len(s), (int32_t)step + 1);
        if (held & (held - 1u)) str_cpy(s + str_len(s), "+", 2);
        return;
    }
    if (mom.st) state = mom.st == MOM_ST_KEPT ? "KEPT" : "TEMP";
    str_cpy(s + 3, state, 12);
}
static uint32_t bank_field_sig(const bank_field_t *f)
{
    return str_hash(str_hash(str_hash(ux.gen + f->color * 31u + f->motion * 65537u + f->lock * 131071u +
                                    f->face * 7u + f->small * 13u + f->fixed * 524287u, f->label), f->value), f->unit);
}
static void bank_draw(void)
{
    uint32_t c, first = 0;
    int full = ui.force || !ui.read_bank.was;
    while (first < 4u && !(ui.read_bank.mask & (1u << first))) first++;
    ui.read_bank.focus = (uint8_t)(ui.hot_col < 4u && (ui.read_bank.mask & (1u << ui.hot_col)) ? ui.hot_col : first);
    /* One composed blit on entry/force: never erase visible text on the LCD
     * before its replacement is ready. Ordinary turns update only two bands. */
    if (full) cv_begin(BANK_W, CARD_H, T_SURF);
    for (c = 0; c < 4u; c++) {
        const bank_field_t *f = &ui.read_bank.field[c];
        uint32_t sig = bank_field_sig(f) + (c == ui.read_bank.focus ? 0x112357u : 0u);
        if (full || sig != ui.read_bank.sig[c]) {
            int x = full ? 59 * (int)c : 0, y = full ? BANK_TOP : 0;
            const aafont_t *vf = bank_font(f->small);
            uint16_t bg = c == ui.read_bank.focus ? T_THEME : T_SURF;
            uint16_t ink = c == ui.read_bank.focus ? T_INK : T_MID;
            if (!full) cv_begin(COL_W, BANK_OV, T_SURF);
            cv_line(x, y, x + COL_W - 1, y, T_DIM);
            if (c == ui.read_bank.focus) cv_rect(x + 2, y + 1, COL_W - 4, AF_S_CAP_H + 2, bg);
            if (f->label[0]) {
                GFX_HOOK_ALIGN(x, 0, x + COL_W, 0, AL_H, "bank overview label");
                cv_text_in(x, y + 2 - AF_S_CAP_Y, COL_W, &AF_S, f->label, ink, bg);
            }
            if (f->value[0]) {
                uint16_t tc = f->color == T_DIM ? T_MID : T_TEXT;
                GFX_HOOK_ALIGN(x, 0, x + COL_W, 0, AL_H, "bank overview value");
                cv_text_in(x, y + BANK_OV - 2 - bank_cap(vf) - (vf == &AF_M ? AF_M_CAP_Y : AF_S_CAP_Y), COL_W, vf,
                           f->value, tc, T_SURF);
            }
            if (f->motion) cv_rect(x + 4, y + BANK_OV - 1, COL_W - 8, 1, T_THEME);
            if (!full) cv_blit((uint32_t)CARD_X(c), Y_LABEL + BANK_TOP);
            ui.read_bank.sig[c] = sig;
        }
    }
    if (ui.read_bank.focus < 4u) {
        const bank_field_t *f = &ui.read_bank.field[ui.read_bank.focus];
        const aafont_t *vf = bank_font(f->face), *lf = &AF_M, *uf = &AF_M;
        char status[20];
        int hot = ui.hot_t && ui.hot_col == ui.read_bank.focus;
        uint32_t sig;
        bank_status(status, f);
        sig = str_hash(bank_field_sig(f) + ui.read_bank.focus * 104729u + hot * 65537u, status);
        if (full || sig != ui.read_bank.sig[4]) {
            uint16_t tc = f->color == T_DIM ? T_MID : hot ? T_ACCENT : T_THEME;
            uint16_t bg = hot ? T_THEME : T_SURF, ink = hot ? T_INK : T_MID;
            if (AF_M_CAP_H + AF_S_CAP_H + 3 > BANK_TOP || ink_w(lf, f->label) > BANK_LABEL_W) lf = &AF_S;
            if (ink_w(uf, f->unit) > 34) uf = &AF_S;
            if (!full) cv_begin(BANK_W, BANK_TOP, T_SURF);
            if (hot) cv_rect(4, 0, ink_w(&AF_S, status) + 4, AF_S_CAP_H + 2, bg);
            bank_text(6, 1, &AF_S, status, ink, bg);
            bank_text(6, BANK_TOP - bank_cap(lf) - 1, lf, f->label, T_TEXT, T_SURF);
            GFX_HOOK_ALIGN(0, 0, 0, BANK_TOP - 2, AL_B, "bank focus value baseline");
            cv_text_r(190, BANK_TOP - 2 - bank_cap(vf) - (vf == &AF_L ? AF_L_CAP_Y : vf == &AF_M ? AF_M_CAP_Y : AF_S_CAP_Y),
                      vf, f->value, tc, T_SURF);
            if (f->unit[0]) GFX_HOOK_ALIGN(0, 0, 0, BANK_TOP - 2, AL_B, "bank focus unit baseline");
            bank_text(198, BANK_TOP - 2 - bank_cap(uf), uf, f->unit, T_TEXT, T_SURF);
            if (!full) cv_blit(3, Y_LABEL);
            ui.read_bank.sig[4] = sig;
        }
    }
    if (full) cv_blit(3, Y_LABEL);
    ui.read_bank.was = 1;
}
