/* SPDX-License-Identifier: GPL-3.0-only */
/* THROWAWAY HOST PROTOTYPE #572. No firmware changes or target resource claim.
 * Three layouts, same real fixtures/formatters/fonts. The browser only selects
 * captured variant/state; it never talks to a device or changes a project. */
#define IDENTITY_UI_RENDER 1
#include "../ui_render.c"

typedef struct { char label[32], value[32], unit[16]; } proto_field_t;
static proto_field_t prototype_fields[4];
static unsigned focus;
static const unsigned cases[] = {S_HOME, S_ENV_SYNC, S_MOD, S_FM6_ALG22, S_FM6_OP_FIXED,
    S_DETAIL, S_MIXER, S_USER, S_NAME_TYPING, S_MENU};
static const char *const topics[] = {"home", "fraction", "mod", "fm6", "operator", "detail",
    "mixer", "sound", "name", "settings"};

/* Take the strings emitted by the real NORMAL draw path. No second formatter. */
static void fields(void)
{
    unsigned i, c;
    memset(prototype_fields, 0, sizeof prototype_fields);
    for (i = 0; i < nscr; i++) {
        const rbox_t *b = &scr[i];
        if (b->y0 < 28 || b->y1 > 72 || !strcmp(b->s, "icon")) continue;
        c = b->x0 < 3 ? 0 : (unsigned)(b->x0 - 3) / 59u;
        if (c >= 4u) continue;
        if (b->y0 < 46) snprintf(prototype_fields[c].label, sizeof prototype_fields[c].label, "%s", b->s);
        else if (!prototype_fields[c].value[0]) snprintf(prototype_fields[c].value, sizeof prototype_fields[c].value, "%s", b->s);
        else snprintf(prototype_fields[c].unit, sizeof prototype_fields[c].unit, "%s", b->s);
    }
}
static const aafont_t *value_face(const char *s, int width)
{
    /* All named roles stay M; numeric roles have room for their fixture boundary
     * strings in A/C/focus. Full-domain production qualification remains open. */
    return large_face_has(s) && ink_w(&AF_L, s) <= width ? &AF_L : &AF_M;
}
static void at(int x, int y, const aafont_t *f, const char *s, uint16_t fg, uint16_t bg)
{
    cv_text_on(x, y - (f == &AF_L ? AF_L_CAP_Y : f == &AF_M ? AF_M_CAP_Y : AF_S_CAP_Y), f, s, fg, bg);
}
static void right(int x, int y, const aafont_t *f, const char *s, uint16_t fg, uint16_t bg)
{
    cv_text_r(x, y - (f == &AF_L ? AF_L_CAP_Y : f == &AF_M ? AF_M_CAP_Y : AF_S_CAP_Y), f, s, fg, bg);
}
static void prototype_panel(int h)
{
    cv_begin(234, h, T_BG);
    cv_rrect(0, 0, 234, h, 4, T_SURF, T_BG);
    if (ux.style) cv_rrect(1, 1, 232, h - 2, 3, T_SURF, T_SURF);
}
static void compact_mod(int h)
{
    unsigned k, count = h < 45 ? 1u : 4u;
    const aafont_t *f = h >= 70 || count == 1 ? &AF_M : &AF_S;
    int rh = count == 1 ? 22 : h / 4;
    for (k = 0; k < count; k++) {
        unsigned slot = count == 1 ? mod_ui_slot : k;
        const int16_t *p = &TSEL->p[P_M1SRC + 3u * slot];
        int y = (int)k * rh;
        uint16_t bg = slot == mod_ui_slot ? T_THEME : T_SURF;
        uint16_t ink = slot == mod_ui_slot ? T_INK : T_MID;
        char n[4], val[12]; const char *unit;
        if (slot == mod_ui_slot) cv_rect(3, y, 228, rh - 1, bg);
        fmt_int(n, (int)slot + 1);
        at(7, y + 2, f, n, ink, bg);
        at(25, y + 2, f, N_MSRC[clamp(p[0], 0, MS_N - 1)], ink, bg);
        cv_line(81, y + rh / 2, 94, y + rh / 2, p[0] && p[1] && p[2] ? ink : T_DIM);
        cv_line(91, y + rh / 2 - 2, 94, y + rh / 2, ink);
        at(101, y + 2, f, ui_mod_dst_name(TSEL, p[1]), ink, bg);
        param_format(&TP[P_M1AMT], p[2], val, &unit);
        right(210, y + 2, f, val, ink, bg);
        at(217, y + 2, &AF_S, unit, ink, bg);
    }
}
static void compact_fm(int h)
{
    unsigned alg = fm6_alg_of(TSEL), k, j, top = 0, hi = 0;
    uint8_t m[6]; char text[24];
    snprintf(text, sizeof text, "ALG %u", alg + 1u);
    at(7, 1, &AF_S, text, T_MID, T_SURF);
    if (h < 70) {
        snprintf(text, sizeof text, "OP %u  / 6", fop_page(cur_page()->graph) ? fop_op + 1u : 1u);
        at(7, 20, &AF_M, text, T_THEME, T_SURF);
        return; /* A/C explicitly sacrifice the topology; the gallery calls this out. */
    }
    int x[6], y[6];
    fm6_routes(alg, m);
    for (k = 0; k < 6; k++) {
        unsigned row = FM6_CELL[alg][k] >> 4, col = FM6_CELL[alg][k] & 7u;
        if (row > top) top = row;
        if (col > hi) hi = col;
    }
    int pitch = (h - 24) / ((int)top + 1);
    for (k = 0; k < 6; k++) {
        x[k] = 116 + (int)(FM6_CELL[alg][k] & 7u) * 27 - (int)hi * 27 / 2;
        y[k] = h - 17 - (int)(FM6_CELL[alg][k] >> 4) * pitch;
    }
    for (k = 0; k < 6; k++) for (j = 0; j < 6; j++) if ((m[k] >> j) & 1u) {
        int jog = y[k] - 2;
        cv_line(x[j], y[j] + 9, x[j], jog, T_THEME);
        cv_line(x[j], jog, x[k], jog, T_THEME);
        cv_line(x[k], jog, x[k], y[k], T_THEME);
    }
    unsigned car = fm6_car_ops(alg);
    for (k = 0; k < 6; k++) {
        uint16_t bg = fop_page(cur_page()->graph) && k == fop_op ? T_ACCENT : car >> k & 1u ? T_THEME : T_RAISE;
        char n[2] = {(char)('1' + k), 0};
        cv_rect(x[k] - 7, y[k], 15, 9, bg);
        at(x[k] - 3, y[k], &AF_S, n, bg == T_RAISE ? T_TEXT : T_INK, bg);
        if (car >> k & 1u) cv_line(x[k], y[k] + 9, x[k], h - 3, T_MID);
    }
    cv_line(65, h - 3, 175, h - 3, T_MID);
    /* This simplified native topology is illustrative; crossings/feedback need
     * the existing all-algorithm oracle before production integration. */
}
static void context(unsigned topic, int y, int h)
{
    prototype_panel(h);
    if (topic == 2) compact_mod(h);
    else if (topic == 3 || topic == 4) compact_fm(h);
    else if (topic == 1) { int saved = graph_ht; graph_ht = h - 4; graph_adsr(TSEL, T_THEME); graph_ht = saved; }
    else if (topic == 6) {
        unsigned c; int rh = h / 4;
        const aafont_t *f = h >= 70 ? &AF_M : &AF_S;
        for (c = 0; c < 4; c++) {
            char name[16], n[3] = {(char)('1' + c), 0};
            trk_short_name(c, name);
            at(7, c * rh + 1, f, n, T_MID, T_SURF);
            at(25, c * rh + 1, f, name, T_TEXT, T_SURF);
            if (trk[c].p[P_MUTE]) right(224, c * rh + 1, f, "MUTE", T_MID, T_SURF);
        }
    } else if (topic == 5) {
        char b[24]; snprintf(b, sizeof b, "STEP %u / %u", ui.cursor + 1u, (unsigned)TSEL->p[P_SLEN]);
        at(8, 1, &AF_M, b, T_TEXT, T_SURF);
        for (unsigned i = 0; i < 16; i++) {
            int on = step_on(&seq_steps(TSEL)[i]);
            cv_rect(9 + i * 14, h - 13, 9, on ? 7 : 2, on ? T_THEME : T_DIM);
            if (i == ui.cursor) cv_rect(9 + i * 14, h - 4, 9, 2, T_ACCENT);
        }
    } else {
        char name[20]; trk_short_name(song.sel, name);
        at(8, 3, &AF_M, name, T_TEXT, T_SURF);
        int yy = h / 2 + 5, amp = h / 3;
        for (int x = 0; x < 211; x++) {
            int a = scope_buf[(x * SCOPE_N / 212) % SCOPE_N] * amp / 16000;
            int b = scope_buf[((x + 1) * SCOPE_N / 212) % SCOPE_N] * amp / 16000;
            cv_line(11 + x, yy - a, 12 + x, yy - b, T_THEME);
        }
    }
    cv_blit(3, y);
}
static void value_block(unsigned c, unsigned variant)
{
    const proto_field_t *p = &prototype_fields[c];
    int row = c / 2, col = c % 2;
    int w = variant == 1 ? 115 : 234;
    int h = variant == 1 ? 56 : 32;
    uint16_t ink = c == focus ? T_ACCENT : T_THEME;
    const aafont_t *f = value_face(p->value, variant == 1 ? 105 : 110);
    char key[4]; snprintf(key, sizeof key, "K%u", c + 1);
    cv_begin(w, h, T_BG);
    cv_rrect(0, 0, w, h, 4, T_SURF, T_BG);
    if (variant == 1) {
        at(6, 1, &AF_S, key, T_MID, T_SURF);
        at(28, 1, &AF_M, p->label, T_MID, T_SURF);
        at(6, f == &AF_L ? 15 : 21, f, p->value, ink, T_SURF);
        right(w - 7, 41, &AF_M, p->unit, T_MID, T_SURF);
        cv_blit(3 + col * 119, 28 + row * 60);
    } else {
        at(6, 2, &AF_S, key, T_MID, T_SURF);
        at(29, 11, &AF_M, p->label, T_MID, T_SURF);
        right(193, f == &AF_L ? 6 : 12, f, p->value, ink, T_SURF);
        at(202, 12, &AF_M, p->unit, T_MID, T_SURF);
        cv_blit(3, 28 + c * 32);
    }
}
static void focus_block(void)
{
    const proto_field_t *p = &prototype_fields[focus];
    char key[6]; snprintf(key, sizeof key, "K%u", focus + 1);
    prototype_panel(38);
    at(8, 1, &AF_S, key, T_MID, T_SURF);
    at(30, 1, &AF_M, p->label, T_MID, T_SURF);
    const aafont_t *f = value_face(p->value, 155);
    right(192, f == &AF_L ? 15 : 20, f, p->value, T_ACCENT, T_SURF);
    at(201, 23, &AF_M, p->unit, T_MID, T_SURF);
    cv_blit(3, 76);
}
/* Exact 2x enlargement of existing M pixels, host-only scratch. This tests a
 * mixed-case reading role without inventing another font or shipping a cache. */
static void twice_m(int x, int y, const char *s, uint16_t fg, uint16_t bg)
{
    uint16_t pixels[112 * 16];
    cv_begin(112, 16, bg); at(0, 0, &AF_M, s, fg, bg);
    memcpy(pixels, cv_px, sizeof pixels);
    cv_begin(224, 32, bg);
    for (int yy = 0; yy < 16; yy++) for (int xx = 0; xx < 112; xx++) {
        uint16_t p = pixels[yy * 112 + xx];
        for (int dy = 0; dy < 2; dy++) for (int dx = 0; dx < 2; dx++) cv_px[(yy * 2 + dy) * 224 + xx * 2 + dx] = p;
    }
    cv_blit(x, y);
}
static void name_proposal(void)
{
    lcd_fill(0, 28, 240, 170, T_BG);
    twice_m(8, 40, nm.s, T_TEXT, T_BG);
    char prefix[16]; snprintf(prefix, sizeof prefix, "%.*s", nm.cur, nm.s);
    lcd_fill(8 + 2 * text_w(&AF_M, prefix), 64, 16, 2, T_ACCENT);
    cv_begin(234, 10, T_BG);
    char title[20]; snprintf(title, sizeof title, "SAVE U%02u", nm.slot + 1u);
    at(0, 1, &AF_S, title, T_MID, T_BG);
    char count[16]; snprintf(count, sizeof count, "%u/12", nm.len);
    right(234, 1, &AF_S, count, T_MID, T_BG);
    cv_blit(3, 28);
    nm_draw_panel(); /* retain the actual keyboard map and all existing controls */
}
static void settings_proposal(void)
{
    lcd_fill(0, 54, 240, 166, T_BG); /* keep the native tab strip and footer */
    const unsigned rows[] = {MI_COLOR, MI_STYLE, MI_LARGE, MI_ANIM, MI_LEDS};
    for (unsigned i = 0; i < 5; i++) {
        unsigned row = rows[i];
        prototype_panel(i == 0 ? 38 : 22);
        uint16_t bg = i == 0 ? T_THEME : T_SURF, fg = i == 0 ? T_INK : T_TEXT;
        if (!i) cv_rect(2, 1, 230, 36, bg);
        const char *value = menu_vname(row, menu_get(row));
        if (i) {
            at(8, 6, &AF_M, MI_NAME[row], fg, bg);
            right(226, 6, &AF_M, value, fg, bg);
        }
        cv_blit(3, i == 0 ? 56 : 72 + i * 24);
        if (!i) { char line[32]; snprintf(line, sizeof line, "COLOR %s", value); twice_m(8, 66, line, T_INK, T_THEME); }
    }
    cv_begin(234, 9, T_BG); right(232, 1, &AF_S, "1/8", T_MID, T_BG); cv_blit(3, 209);
}
int main(int argc, char **argv)
{
    const char *out = argc > 1 ? argv[1] : "build/large-prototype";
    char file[512], tag[100], name[60];
    snprintf(file, sizeof file, "%s/scenes.txt", out); scene_manifest = fopen(file, "w");
    snprintf(file, sizeof file, "%s/report.txt", out); rep = fopen(file, "w");
    for (unsigned topic = 0; topic < sizeof cases / sizeof cases[0]; topic++)
        for (unsigned p = 0; p < NPALETTES; p++) for (unsigned st = 0; st < 2; st++)
            for (unsigned v = 0; v < 5; v++) for (unsigned state = 0; state < 4; state++) {
                unsigned s = cases[topic]; focus = state;
                large_on = v == 0; setup(s); pal(p); ui_style = st; style_apply();
                ui.hot_col = focus; ui.hot_t = 30;
                if (topic == 0 && state == 3) TSEL->p[P_ATK] = TSEL->p[P_REL] = 127;
                if (topic == 2 && state == 3) TSEL->p[P_M2AMT] = 63;
                if (topic == 7) { up_store(3, "MiXeD Bass12"); ui.uslot = 3; }
                if (topic == 8) { str_cpy(nm.s, "MiXeD Bass12", sizeof nm.s); nm.len = 12; nm.cur = 8; }
                draw(s);
                if (v > 0 && v < 4) {
                    fields();
                    ui_prefs |= PREF_LARGE;
                    if (topic == 8) name_proposal();
                    else if (topic == 9) settings_proposal();
                    else if (topic != 7) {
                        if (v != 2) {
                            lcd_fill(0, 28, 240, 170, T_BG);
                            for (unsigned c = 0; c < 4; c++) value_block(c, v);
                            context(topic, v == 1 ? 148 : 160, v == 1 ? 50 : 38);
                        } else {
                            lcd_fill(0, 76, 240, 122, T_BG);
                            focus_block(); context(topic, 118, 80);
                        }
                    }
                }
                snprintf(tag, sizeof tag, "%s-%s-%s", v == 0 ? "current" : v == 4 ? "normal" : v == 1 ? "A" : v == 2 ? "B" : "C", UI_PALETTES[p].name, st ? "LINE" : "FLAT");
                snprintf(name, sizeof name, "%s-k%u", topics[topic], state + 1);
                cur_name = name;
                lint(); mono_check();
                write_ppm(out, tag, name);
            }
    fprintf(rep, "native captures=%u lint=%u alignment=%u\n", 10u * NPALETTES * 2u * 5u * 4u, nfind, al_fail);
    fclose(rep); fclose(scene_manifest);
    return nfind || al_fail ? 1 : 0; /* Existing pixel bounds remain the floor. */
}
