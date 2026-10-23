/* SPDX-License-Identifier: GPL-3.0-only */
/* Settings A + selective details (#577): stable rows for finding/comparing values,
 * detail pages group related settings. Compose each strip before its
 * blit, within the existing canvas; never enlarge a row when focus moves. */
#define MENU_READ_ROWS 7u
#define MENU_READ_H 19
#define MENU_READ_GAP 2
static int32_t menu_read_height(void) { return MENU_READ_H; }
static uint32_t menu_read_first(void)
{
    uint32_t k = mtab_index(ui.menu_sel);
    return k < MENU_READ_ROWS ? 0u : k - MENU_READ_ROWS + 1u;
}
static int32_t menu_read_y(uint32_t row)
{
    return MP_Y + MP_PAD + (int32_t)(row - menu_read_first()) * (menu_read_height() + MENU_READ_GAP);
}
static void menu_read_value(uint32_t row, char *text, const char **unit)
{
    *unit = "";
    if (row == MI_SCROFF) { menu_off_summary(text); return; }
    if (row == MI_LCLEAR) {
        if (ml_count()) { fmt_int(text, (int32_t)ml_count()); str_cpy(text + str_len(text), " CC", 4); }
        else str_cpy(text, "NONE", 8);
        return;
    }
    if (row >= MI_VALUES) { str_cpy(text, "OPEN", 8); return; }
    if (row == MI_HOLD) {
        str_cpy(text, "0.4", 8); text[2] = (char)('0' + HOLD_MS[settings_hold % 4u] / 100u); *unit = "s";
        return;
    }
    str_cpy(text, menu_vname(row, menu_get(row)), 32);
    if (row == MI_TUNE) *unit = "ct";
}
static void menu_read_row(const char *label, const char *value, const char *unit, int selected, int detail, int inactive)
{
    int32_t ty = CAP_IN(M, MENU_READ_H), right = MR_VR - (detail ? 16 : 0);
    uint16_t bg = selected ? T_THEME : T_SURF, fg = selected ? T_INK : T_TEXT;
    uint16_t val = selected ? T_INK : inactive ? T_MID : T_THEME;
    cv_rect(MR_X, 0, MR_W, MENU_READ_H, bg);
    GFX_HOOK_ALIGN(0, 0, 0, MENU_READ_H, AL_V, "menu row name centred up/down");
    cv_text_on(MR_LX, ty, &AF_M, label, fg, bg);
    if (unit[0]) {
        GFX_HOOK_ALIGN(0, 0, 0, ty + AF_M.asc, AL_B, "menu row unit on its value's baseline");
        right = cv_text_r(right, ty, &AF_M, unit, val, bg) - UI_VALUE_UNIT_GAP;
    }
    GFX_HOOK_ALIGN(0, 0, 0, MENU_READ_H, AL_V, "menu row value centred up/down");
    cv_text_r(right, ty, &AF_M, value, val, bg);
    if (detail) cv_icon_in(MR_VR - 12, 0, 0, MENU_READ_H, 12, ICON_X_RIGHT, fg, bg);
}
static void menu_read_scroll(int32_t y, int32_t h, uint32_t n, uint32_t first, uint32_t shown)
{
    if (n > shown) {
        int32_t top = MP_Y + MP_PAD, height = (int32_t)shown * (MENU_READ_H + MENU_READ_GAP) - MENU_READ_GAP;
        int32_t thumb = height * (int32_t)shown / (int32_t)n;
        int32_t start = top + (height - thumb) * (int32_t)first / (int32_t)(n - shown);
        int32_t a = start > y ? start - y : 0, b = start + thumb < y + h ? start + thumb - y : h;
        cv_rect(236, 0, 2, h, T_LINE);
        if (b > a) cv_rect(236, a, 2, b - a, T_MID);
    }
}
static void menu_reading_list(const khint_t *keys)
{
    uint32_t n = mtab_rows(menu_tab()), first = menu_read_first(), shown = n < MENU_READ_ROWS ? n : MENU_READ_ROWS;
    int32_t y = menu_read_y(first);
    cv_begin(240, (uint32_t)(y - H_HEAD), T_BG); cv_oy = -H_HEAD;
    menu_tabs(); cv_oy = 0; cv_blit(0, H_HEAD);
    for (uint32_t k = first; k < first + shown; k++) {
        uint32_t row = mtab_row(menu_tab(), k);
        char value[32]; const char *unit;
        menu_read_value(row, value, &unit);
        cv_begin(240, MENU_READ_H + MENU_READ_GAP, T_BG);
        menu_read_row(MI_NAME[row], value, unit, row == ui.menu_sel,
                      row == MI_SCROFF || row >= MI_VALUES,
                      MI_TCH(row) && song.g[G_ROUTE] != ROUTE_TRACK);
        menu_read_scroll(y, MENU_READ_H + MENU_READ_GAP, n, first, shown);
        cv_blit(0, (uint32_t)y); y += MENU_READ_H + MENU_READ_GAP;
    }
    cv_begin(240, (uint32_t)(240 - y), T_BG);
    {
        char count[16]; fmt_int(count, (int32_t)mtab_index(ui.menu_sel) + 1);
        str_cpy(count + str_len(count), "/", 2); fmt_int(count + str_len(count), (int32_t)n);
        cv_text_r(232, 212 - y - AF_S_CAP_Y, &AF_S, count, T_MID, T_BG);
    }
    cv_key_row(8, 232, MK_Y - y, keys, 3, 7u, T_BG);
    cv_blit(0, (uint32_t)y);
}
static void menu_reading_off(const khint_t *keys)
{
    static const char *const NAME[MO_COUNT] = {"IDLE AFTER", "IDLE MODE", "ALL DARK", "WAKE", "BACK"};
    int32_t y = 56;
    cv_begin(240, (uint32_t)(y - H_HEAD), T_BG);
    cv_text_on(8, 34 - H_HEAD - AF_M_CAP_Y, &AF_M, "DISPLAY / AUTO OFF", T_TEXT, T_BG);
    cv_blit(0, H_HEAD);
    for (uint32_t k = 0; k < MO_COUNT; k++) {
        uint32_t v = menu_off_get(k);
        const char *value = k == MO_MODE ? OFF_MODE_N[v] : k == MO_WAKE ? menu_vname(MI_SCRWAKE, v) :
                            k == MO_BACK ? "" : OFF_TIME_N[v];
        cv_begin(240, MENU_READ_H + MENU_READ_GAP, T_BG);
        menu_read_row(NAME[k], value, "", k == menu_off_sel, k == MO_BACK, 0);
        cv_blit(0, (uint32_t)y); y += MENU_READ_H + MENU_READ_GAP;
    }
    cv_begin(240, (uint32_t)(240 - y), T_BG);
    if (menu_off_error) cv_text_on(8, 194 - y - AF_S_CAP_Y, &AF_S, "ALL DARK MUST BE LATER", T_TEXT, T_BG);
    cv_text_in(0, 210 - y - AF_S_CAP_Y, 240, &AF_S, "TIMES SINCE INPUT", T_MID, T_BG);
    cv_key_row(8, 232, MK_Y - y, keys, 2, 7u, T_BG);
    cv_blit(0, (uint32_t)y);
}
