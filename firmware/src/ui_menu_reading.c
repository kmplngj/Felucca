/* SPDX-License-Identifier: GPL-3.0-only */
/* Selected menu reading role (#577). Pure drawing/window calculations: menu
 * movement, descriptor values and actions retain their existing owners. Each
 * row is composed before its blit; no intermediate clear or extra framebuffer. */
#define MENU_READ_ROWS 5u
#define MENU_READ_H 24
#define MENU_READ_GAP 2
static int32_t menu_read_height(void)
{
    int32_t h = AF_M_CAP_H + AF_N_CAP_H + 11;
    return h < 38 ? 38 : h;
}
static uint32_t menu_read_first(void)
{
    uint32_t n = mtab_rows(menu_tab()), k = mtab_index(ui.menu_sel);
    uint32_t first = k > 2u ? k - 2u : 0u, last = n > MENU_READ_ROWS ? n - MENU_READ_ROWS : 0u;
    return first < last ? first : last;
}
static int32_t menu_read_y(uint32_t row)
{
    uint32_t first = menu_read_first(), selected = mtab_index(ui.menu_sel);
    int32_t y = MP_Y + MP_PAD;
    for (uint32_t k = first; k < row; k++) y += (k == selected ? menu_read_height() : MENU_READ_H) + MENU_READ_GAP;
    return y;
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
static void menu_read_focus(const char *label, const char *value, const char *unit, int32_t h, int color, int detail)
{
    const aafont_t *f = detail ? &AF_M : &AF_N;
    int32_t cy = AF_M_CAP_H + 5, vy = cy - (detail ? AF_M_CAP_Y : AF_N_CAP_Y);
    int32_t baseline = vy + f->asc, right = MR_VR;
    cv_rect(MR_X, 0, MR_W, h, T_THEME);
    cv_text_on(MR_LX, 2 - AF_M_CAP_Y, &AF_M, label, T_INK, T_THEME);
    if (color) right -= 80;
    if (detail) right -= 18;
    if (unit[0]) {
        GFX_HOOK_ALIGN(0, 0, 0, baseline, AL_B, "menu focused unit baseline");
        right = cv_text_r(right, baseline - AF_M.asc, &AF_M, unit, T_INK, T_THEME) - UI_VALUE_UNIT_GAP;
    }
    GFX_HOOK_ALIGN(0, 0, 0, baseline, AL_B, "menu focused value baseline");
    cv_text_r(right, vy, f, value, T_INK, T_THEME);
    if (detail) cv_icon_in(MR_VR - 12, cy, 0, AF_M_CAP_H, 12, ICON_X_RIGHT, T_INK, T_THEME);
    if (color) {
        const uint16_t *tok = &T_BG;
        int32_t sy = cy + HALF_UP(AF_N_CAP_H - 12);
        for (uint32_t k = 0; k < 5u; k++) {
            int32_t x = MR_VR - 74 + (int32_t)k * 15;
            cv_rrect(x, sy, 12, 12, -3, T_RAISE, T_THEME);
            cv_rrect(x + 1, sy + 1, 10, 10, -2, tok[k], T_RAISE);
        }
    }
}
static void menu_read_scroll(int32_t y, int32_t h, uint32_t n, uint32_t first, uint32_t shown)
{
    if (n > shown) {
        int32_t top = MP_Y + MP_PAD, height = (int32_t)(shown - 1u) * (MENU_READ_H + MENU_READ_GAP) + menu_read_height();
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
    int32_t y = MP_Y + MP_PAD;
    cv_begin(240, (uint32_t)(y - H_HEAD), T_BG); cv_oy = -H_HEAD;
    menu_tabs(); cv_oy = 0; cv_blit(0, H_HEAD);
    for (uint32_t k = first; k < first + shown; k++) {
        uint32_t row = mtab_row(menu_tab(), k);
        int sel = row == ui.menu_sel;
        int32_t h = sel ? menu_read_height() : MENU_READ_H;
        cv_begin(240, (uint32_t)(h + MENU_READ_GAP), T_BG);
        if (sel) {
            char value[32]; const char *unit;
            menu_read_value(row, value, &unit);
            menu_read_focus(MI_NAME[row], value, unit, h, row == MI_COLOR, row == MI_SCROFF);
        } else {
            cv_rect(MR_X, 0, MR_W, h, T_SURF);
            menu_row_at(k, row, 0, h);
        }
        menu_read_scroll(y, h + MENU_READ_GAP, n, first, shown);
        cv_blit(0, (uint32_t)y); y += h + MENU_READ_GAP;
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
    int32_t y = 32;
    cv_begin(240, 8, T_BG); cv_blit(0, H_HEAD);
    for (uint32_t k = 0; k < MO_COUNT; k++) {
        int sel = k == menu_off_sel;
        int32_t h = sel ? menu_read_height() : MENU_READ_H;
        uint32_t v = menu_off_get(k);
        const char *value = k == MO_MODE ? OFF_MODE_N[v] : k == MO_WAKE ? menu_vname(MI_SCRWAKE, v) :
                            k == MO_BACK ? "BACK" : OFF_TIME_N[v];
        cv_begin(240, (uint32_t)(h + MENU_READ_GAP), T_BG);
        if (sel) menu_read_focus(NAME[k], value, "", h, 0, 0);
        else {
            int32_t ty = CAP_IN(M, h);
            cv_rect(MR_X, 0, MR_W, h, T_SURF);
            cv_text_on(MR_LX, ty, &AF_M, NAME[k], T_TEXT, T_SURF);
            cv_text_r(MR_VR, ty, &AF_M, value, T_THEME, T_SURF);
        }
        cv_blit(0, (uint32_t)y); y += h + MENU_READ_GAP;
    }
    cv_begin(240, (uint32_t)(240 - y), T_BG);
    if (menu_off_error) cv_text_on(8, 194 - y - AF_S_CAP_Y, &AF_S, "ALL DARK MUST BE LATER", T_TEXT, T_BG);
    cv_text_in(0, 210 - y - AF_S_CAP_Y, 240, &AF_S, "TIMES SINCE INPUT", T_MID, T_BG);
    cv_key_row(8, 232, MK_Y - y, keys, 2, 7u, T_BG);
    cv_blit(0, (uint32_t)y);
}
