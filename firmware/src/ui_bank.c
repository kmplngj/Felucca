/* SPDX-License-Identifier: GPL-3.0-only */
/* Native parameter bank (#572). Collect the existing column outputs, then draw
 * a focused reading path and four spatial overview columns. Main-loop UI state
 * only; no second formatter, edit path, framebuffer or persistent preference.
 * The look (direction A): no boxes. The focused knob's label and state on one line, its value as the dominant
 * numeral flush left (X where the page is tall, bank_tall; L in the 44 px band), then the four knob columns under
 * rules: the focused column's rule heavy, its form the state (solid the value, dashed automation, doubled a step
 * lock, dotted MOMENTARY's temporary value), the accent only while the knob turns. */
#define BANK_W 234
#define BANK_TOP (bank_tall() ? 40 : 19)              /* the readout above it, the overview columns from it */
#define BANK_OV ((int)card_h() - BANK_TOP)
#define BANK_RULE (BANK_TOP + 3)                      /* the columns' rule (the heavy one: a row above and below) */
#define BANK_LBL_DY (bank_tall() ? 5 : 4)             /* rule -> the column label's capitals */
#define BANK_NUM_B (bank_tall() ? 40 : 19)            /* the numeral's capitals end on this row */
#define BANK_NUM_W (bank_tall() ? 195 : 150)          /* the numeral's room: the unit after it (tall), the label and
                                                       * state right of it (the 44 px band) */
#define BANK_LABEL_W 74
#ifndef BANK_HOOK
#define BANK_HOOK(c, value, face) ((void)0)
#endif
enum { BR_SOLID, BR_DASH, BR_DOUBLE, BR_DOT };


static int bank_on(void)
{
    return !ui.layer && (reading_kind() == RK_BANK || lock_held());
}
/* faces, largest first; a column keeps the smallest its whole domain needs (bank_collect) */
static const aafont_t *bank_font(unsigned f) { return f == 0u ? &AF_X : f == 1u ? &AF_L : f == 2u ? &AF_M : &AF_S; }
static int bank_cap(const aafont_t *f)
{
    return f == &AF_X ? AF_X_CAP_H : f == &AF_L ? AF_L_CAP_H : f == &AF_M ? AF_M_CAP_H : AF_S_CAP_H;
}
static int bank_cap_y(const aafont_t *f)
{
    return f == &AF_X ? AF_X_CAP_Y : f == &AF_L ? AF_L_CAP_Y : f == &AF_M ? AF_M_CAP_Y : AF_S_CAP_Y;
}
static void bank_text(int x, int y, const aafont_t *f, const char *s, uint16_t fg, uint16_t bg)
{
    cv_text_on(x, y - bank_cap_y(f), f, s, fg, bg);   /* y: the capitals' top */
}
static unsigned bank_big_face(const char *s)
{
    int big = large_face_has(s);
    return bank_tall() && big && ink_w(&AF_X, s) <= BANK_NUM_W ? 0u : big && ink_w(&AF_L, s) <= BANK_NUM_W ? 1u :
           ink_w(&AF_M, s) <= BANK_NUM_W ? 2u : 3u;
}
static unsigned bank_small_face(const char *s)
{
    return AF_M_CAP_H + AF_S_CAP_H + 3 <= BANK_OV && ink_w(&AF_M, s) <= COL_W - 4 ? 2u : 3u;
}
static void bank_collect(uint32_t c, const char *label, const char *val, const char *unit,
                         uint16_t color, int motion, const card_span_t *sp)
{
    bank_field_t *f = &ui.read_bank.field[c];
    uint32_t key = str_hash(str_hash((uint32_t)(uintptr_t)sp->fn * 31u + (uint32_t)(uintptr_t)sp->p * 7u +
                                    (uint32_t)sp->lo * 131u + (uint32_t)sp->hi * 8191u + (uint32_t)sp->ctx * 524287u +
                                    song.sel + TSEL->eng_req * 4u + (uint32_t)bank_tall() * 65599u, label), unit);
    if (!f->key || f->key != key) {
        f->key = key;
        f->face = 0; f->small = 2;
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
/* a column's rule w px from x on row y: heavy 3 rows (y - 1 .. y + 1; doubled: y - 1 and y + 1) */
static void bank_rule(int x, int y, int w, unsigned form, int heavy, uint16_t c)
{
    int i, r, on = form == BR_DASH ? 6 : form == BR_DOT ? 2 : w, off = form == BR_DASH ? 3 : 2;
    for (r = -1; r <= 1; r++) {
        if (form == BR_DOUBLE ? r == 0 : !heavy && r)
            continue;
        for (i = 0; i < w; i += on + off)
            cv_rect(x + i, y + r, i + on > w ? w - i : on, 1, c);
    }
}
static unsigned bank_form(const bank_field_t *f, int focus)
{
    if (f->motion) return BR_DASH;
    if (f->lock == 2u) return BR_DOUBLE;
    if (focus && mom.st && mom.st != MOM_ST_KEPT) return BR_DOT;
    return BR_SOLID;
}
/* overview column c at canvas x, its rule on row y */
static void bank_column(int x, int y, uint32_t c, int hot)
{
    const bank_field_t *f = &ui.read_bank.field[c];
    int focus = c == ui.read_bank.focus;
    const aafont_t *vf = bank_font(f->small);
    unsigned form = bank_form(f, focus);
    uint16_t rc = focus ? (hot ? T_ACCENT : f->color == T_DIM ? T_DIM : T_THEME) : form == BR_SOLID ? T_LINE : T_THEME;
    if (f->label[0] || f->value[0] || focus)
        bank_rule(x, y, COL_W, form, focus, rc);
    int ly = y + BANK_LBL_DY, vb = ly + AF_S_CAP_H + 2 + AF_M_CAP_H;
    if (f->label[0])
        bank_text(x, ly, &AF_S, f->label, focus ? T_TEXT : T_MID, T_SURF);
    if (f->value[0]) {
        GFX_HOOK_ALIGN(0, 0, 0, vb, AL_B, "bank overview value baseline");
        bank_text(x, vb - bank_cap(vf), vf, f->value, f->color == T_DIM ? T_MID : T_TEXT, T_SURF);
    }
}
/* the focused knob: label and state, the numeral and its unit */
static void bank_readout(const bank_field_t *f, int hot, const char *status)
{
    const aafont_t *vf = bank_font(f->face), *lf = &AF_M, *uf = &AF_M;
    int tall = bank_tall(), nb = BANK_NUM_B, x, sw = ink_w(&AF_S, status);
    int mono = hot && T_ACCENT == T_THEME;             /* MONO: no colour tells the turning knob: its state inverted */
    uint16_t tc = f->color == T_DIM ? T_MID : hot ? T_ACCENT : T_THEME;
    if (ink_w(lf, f->label) > (tall ? BANK_W - 12 - sw : BANK_LABEL_W)) lf = &AF_S;
    if (ink_w(uf, f->unit) > 34) uf = &AF_S;
    if (tall) {                                        /* label left, state right on the first line */
        GFX_HOOK_ALIGN(0, 0, 0, 1 + AF_M_CAP_H, AL_B, "bank label and state baseline");
        bank_text(3, 1 + AF_M_CAP_H - bank_cap(lf), lf, f->label, T_TEXT, T_SURF);
    } else {                                           /* label and state right of the numeral */
        GFX_HOOK_ALIGN(0, 0, 0, 2 + AF_M_CAP_H, AL_B, "bank label baseline");
        bank_text(BANK_W - 3 - ink_w(lf, f->label), 2 + AF_M_CAP_H - bank_cap(lf), lf, f->label, T_TEXT, T_SURF);
    }
    {
        int sy = (tall ? 1 + AF_M_CAP_H : nb) - AF_S_CAP_H, sx = BANK_W - 3 - sw;
        if (mono) cv_rect(sx - 2, sy - 2, sw + 4, AF_S_CAP_H + 4, T_THEME);
        GFX_HOOK_ALIGN(0, 0, 0, sy + AF_S_CAP_H, AL_B, "bank state baseline");
        bank_text(sx, sy, &AF_S, status, mono ? T_INK : T_MID, mono ? T_THEME : T_SURF);
    }
    GFX_HOOK_ALIGN(0, 0, 0, nb, AL_B, "bank focus value baseline");
    bank_text(3, nb - bank_cap(vf), vf, f->value, tc, T_SURF);
    x = 3 + ink_w(vf, f->value) + UI_VALUE_UNIT_GAP + (vf == &AF_X ? 3 : 1);
    if (f->unit[0]) {
        GFX_HOOK_ALIGN(0, 0, 0, nb, AL_B, "bank focus unit baseline");
        bank_text(x, nb - bank_cap(uf), uf, f->unit, T_MID, T_SURF);
    }
}
static void bank_draw(void)
{
    uint32_t c, first = 0, h = card_h();
    int full = ui.force || !ui.read_bank.was, top = BANK_TOP;
    while (first < 4u && !(ui.read_bank.mask & (1u << first))) first++;
    ui.read_bank.focus = (uint8_t)(ui.hot_col < 4u && (ui.read_bank.mask & (1u << ui.hot_col)) ? ui.hot_col : first);
    /* One composed blit on entry/force: never erase visible text on the LCD
     * before its replacement is ready. Ordinary turns update only two bands. */
    if (full) cv_begin(BANK_W, h, T_SURF);
    for (c = 0; c < 4u; c++) {
        const bank_field_t *f = &ui.read_bank.field[c];
        int hot = ui.hot_t && ui.hot_col == c && c == ui.read_bank.focus;
        uint32_t sig = bank_field_sig(f) + (c == ui.read_bank.focus ? 0x112357u : 0u) + (uint32_t)hot * 7919u +
                       (uint32_t)bank_form(f, c == ui.read_bank.focus) * 104729u;
        if (full || sig != ui.read_bank.sig[c]) {
            if (!full) cv_begin(COL_W, (uint32_t)BANK_OV, T_SURF);
            bank_column(full ? 59 * (int)c : 0, full ? BANK_RULE : 3, c, hot);
            if (!full) cv_blit((uint32_t)CARD_X(c), Y_LABEL + (uint32_t)top);
            ui.read_bank.sig[c] = sig;
        }
    }
    if (ui.read_bank.focus < 4u) {
        const bank_field_t *f = &ui.read_bank.field[ui.read_bank.focus];
        char status[20];
        int hot = ui.hot_t && ui.hot_col == ui.read_bank.focus;
        uint32_t sig;
        bank_status(status, f);
        sig = str_hash(bank_field_sig(f) + ui.read_bank.focus * 104729u + hot * 65537u, status);
        if (full || sig != ui.read_bank.sig[4]) {
            if (!full) cv_begin(BANK_W, (uint32_t)top, T_SURF);
            bank_readout(f, hot, status);
            if (!full) cv_blit(3, Y_LABEL);
            ui.read_bank.sig[4] = sig;
        }
    }
    if (full) cv_blit(3, Y_LABEL);
    ui.read_bank.was = 1;
}
