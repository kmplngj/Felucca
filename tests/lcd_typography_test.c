/* SPDX-License-Identifier: GPL-3.0-only */
/* Exercise the actual card/MOD draw paths. Coordinates come from emitted text,
 * not from evaluating the layout expressions under test. */
#include <stdint.h>
#include <string.h>

typedef struct { int32_t x0, y0, x1, y1, cap0, cap1; uint32_t flags; char text[48]; } type_box_t;
static type_box_t type_boxes[64];
static uint32_t type_count;
static int32_t type_cap0, type_cap1;
static void type_text(int32_t x0, int32_t y0, int32_t x1, int32_t y1, const char *s, uint32_t flags);
#define GFX_HOOK_TEXT(x0, y0, x1, y1, s, flags) type_text(x0, y0, x1, y1, s, flags)
#define GFX_HOOK_BEGIN() ((void)0)
#define GFX_HOOK_BLIT(x, y, r0) ((void)0)
#define GFX_HOOK_PIXELS(n) ((void)0)
#define GFX_HOOK_ALIGN(x0, y0, x1, y1, mode, tag) ((void)0)
#define GFX_HOOK_ITEM(x0, y0, x1, y1) ((void)0)
#define GFX_HOOK_ICON(x, y, size, id) ((void)0)
#define GFX_HOOK_PEN(y, f) (type_cap1 = (y) + (f)->asc, \
                          type_cap0 = type_cap1 - ((f) == &AF_M ? AF_M_CAP_H : (f) == &AF_L ? AF_L_CAP_H : AF_S_CAP_H))
#define UI_TEST_NO_MAIN 1
#include "ui_test.c"

static void type_text(int32_t x0, int32_t y0, int32_t x1, int32_t y1, const char *s, uint32_t flags)
{
    type_box_t *b;
    if (type_count >= sizeof type_boxes / sizeof type_boxes[0]) return;
    b = &type_boxes[type_count++];
    b->x0 = x0; b->y0 = y0; b->x1 = x1; b->y1 = y1;
    b->cap0 = type_cap0; b->cap1 = type_cap1; b->flags = flags;
    str_cpy(b->text, s, sizeof b->text);
}
static type_box_t *type_find_at(const char *s, int32_t min_x)
{
    uint32_t i;
    for (i = 0; i < type_count; i++)
        if (type_boxes[i].x0 >= min_x && !strcmp(type_boxes[i].text, s)) return &type_boxes[i];
    return 0;
}
static int type_clean(void)
{
    uint32_t i;
    for (i = 0; i < type_count; i++)
        if (type_boxes[i].flags & 3u) return 0;
    return 1;
}
static int32_t type_pen_left(const type_box_t *b, const aafont_t *f)
{
    int32_t ink[4];
    text_ink(f, b->text, ink);
    return b->x0 - ink[0];                    /* remove the sign/letter's native bearing */
}
static int type_card(const char *value, const char *unit, type_box_t *v, type_box_t *u)
{
    type_box_t *vb, *ub;
    type_count = 0;
    ui.force = 1;
    draw_column(0, "VALUE", value, unit, T_THEME, -1, ICON_NONE);
    vb = type_find_at(value, 0); ub = type_find_at(unit, 0);
    if (!vb || !ub || !type_clean()) return 0;
    *v = *vb; *u = *ub;
    return 1;
}
int main(void)
{
#if !UI_FONT_M8STEALTH
    puts("LCD typography: M8-specific fit fixture skipped; alternate fonts retain the UI render/alignment sweeps");
    return 0;
#else
    static const char *const values[] = {"0", "9", "10", "99", "100", "-100", "0.1", "10.0"};
    uint32_t i;
    int32_t amount_value;
    type_box_t v, u, first_v, first_u;
    int bad = 0, ok = 1;
    ui_power_on();
    ui_prefs &= (uint8_t)~PREF_LARGE;
    ok &= type_card(values[0], "%", &first_v, &first_u);
    for (i = 0; i < NELEM(values); i++) {
        ok &= type_card(values[i], "%", &v, &u);
        ok &= u.x0 == first_u.x0 && u.x1 == first_u.x1 && type_pen_left(&v, &AF_M) == type_pen_left(&first_v, &AF_M);
        ok &= v.x1 < u.x0 && v.cap1 == u.cap1;
    }
    bad += check("LCD card: unit slot and numeric start stay fixed across signs, decimals and digit widths", ok);
    ok = type_card("1.0", "ms", &first_v, &first_u) && type_card("100.0", "ms", &v, &u);
    ok &= first_v.cap1 - first_v.cap0 > v.cap1 - v.cap0; /* the long value actually selected S */
    ok &= first_v.cap0 + first_v.cap1 == v.cap0 + v.cap1;
    ok &= first_u.x0 == u.x0 && first_u.x1 == u.x1 && v.cap1 == u.cap1 && v.x1 < u.x0;
    bad += check("LCD card: dense S fallback shares the M capital centre and keeps its unit slot", ok);
    ok = 1;
    for (amount_value = TP[P_M1AMT].min; amount_value <= TP[P_M1AMT].max; amount_value++) {
        type_box_t *amount, *unit;
        char b[8]; const char *name;
        TSEL->p[P_M1AMT] = (int16_t)amount_value;
        param_format(&TP[P_M1AMT], amount_value, b, &name);
        type_count = 0;
        cv_begin(240, 122, T_SURF);
        graph_mod(TSEL, T_THEME);
        amount = type_find_at(b, 172); unit = type_find_at(name, 172);
        if (!amount || !unit || !type_clean()) { ok = 0; continue; }
        if (amount_value == TP[P_M1AMT].min) { first_v = *amount; first_u = *unit; }
        ok &= type_pen_left(amount, &AF_M) == type_pen_left(&first_v, &AF_M) &&
              unit->x0 == first_u.x0 && unit->x1 == first_u.x1;
        ok &= amount->x1 < unit->x0 && amount->cap1 == unit->cap1;
    }
    bad += check("LCD MOD: full signed amount range fits before a stationary baseline-aligned unit", ok);
    return bad != 0;
#endif
}
