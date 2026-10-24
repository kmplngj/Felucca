/* SPDX-License-Identifier: GPL-3.0-only */
/* Contrast of text emitted by the real draw paths, including their actual backgrounds. */
#include <stdint.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static uint16_t read_fg, read_bg;
static unsigned read_group, read_on, read_mutes, read_examples;
static unsigned read_count[10], read_low[10];
static void read_text(const char *s, uint32_t flags);
#define GFX_HOOK_INK(ink, bg) (read_fg = (ink), read_bg = (bg))
#define GFX_HOOK_TEXT(x0, y0, x1, y1, s, flags) read_text(s, flags)
#define GFX_HOOK_BEGIN() ((void)0)
#define GFX_HOOK_BLIT(x, y, r0) ((void)0)
#define GFX_HOOK_PIXELS(n) ((void)0)
#define UI_TEST_NO_MAIN 1
#include "ui_test.c"

static double read_luma(uint16_t color)
{
    const double weights[] = {0.2126, 0.7152, 0.0722};
    const unsigned channels[] = {color >> 11, (color >> 5) & 63u, color & 31u};
    double sum = 0;
    unsigned k;
    for (k = 0; k < 3u; k++) {
        double v = channels[k] / (k == 1u ? 63.0 : 31.0);
        sum += weights[k] * (v <= 0.04045 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4));
    }
    return sum;
}
static void read_text(const char *s, uint32_t flags)
{
    double a, b, ratio;
    if (!read_on) return;
    if (flags & 4u) {                       /* unavailable keycap fills have their own intentional state */
        read_mutes += !strcmp(s, "MUTE");
        return;
    }
    if (!s[0]) return;
    a = read_luma(read_fg); b = read_luma(read_bg);
    ratio = (fmax(a, b) + 0.05) / (fmin(a, b) + 0.05);
    read_count[read_group]++;
    if (ratio + 1e-9 < 4.5) {
        read_low[read_group]++;
        if (read_examples++ < 8u)
            printf("LCD readability: group %u %s/%s '%s' %.2f:1\n", read_group,
                   UI_PALETTES[settings.palette].name, ux.style ? "LINE" : "FLAT", s, ratio);
    }
}
static void read_start(unsigned group) { read_group = group; read_on = 1; }
static void read_stop(void) { read_on = 0; }

int main(void)
{
    static const char *const names[] = {"inactive card values", "mixer names/values/units",
        "HOME track names", "piano-roll pitches", "muted drum lane names", "MOD rows and units", "focus and editing states", "menu selection", "name field", "list names"};
    unsigned p, st, large, state, c, k;
    int bad = 0, legends = 1;
    for (p = 0; p < NPALETTES; p++)
        for (st = ST_FLAT; st <= ST_LINE; st++)
            for (large = 0; large < 2u; large++)
                for (state = 0; state < 3u; state++) {
                    ui_power_on();
                    settings.palette = (uint8_t)p;
                    ui_style = (uint8_t)st;
                    style_apply();
                    ui_prefs = large ? PREF_LARGE : 0u;
                    ui.force = 1; song.playing = 0; song.rec = 0;
                    song.sel = state;
                    for (c = 0; c < NTRK; c++) {
                        trk[c].p[P_MUTE] = c >= 2u;
                        trk[c].p[P_LEVEL] = c ? 100 : 0;
                        trk[c].p[P_PAN] = -32;
                        trk[c].p[P_REV] = 64;
                    }
                    go_page(GR_TRK);
                    read_start(0);
                    ui.read_bank.mask = 0;
                    draw_column(0, "AMT", "-100", "%", T_DIM, 500, ICON_NONE);
                    bank_draw();
                    read_stop();
                    read_start(1);
                    draw_tracks();
                    read_stop();
                    read_start(2);
                    for (c = 0; c < NTRK; c++) home_track_row(c);
                    read_stop();
                    read_start(3);
                    proll.lo = 48;
                    cv_begin(240, 124, T_SURF);
                    graph_roll(TSEL, T_THEME, NSTEP);
                    read_stop();
                    TSEL->eng_req = ENGI_DRUM; TSEL->preset = 0; TSEL->p[P_E0] = 0;
                    drum_mute[trk_index(TSEL)] = 3u;
                    ui.lane = state;
                    read_start(4);
                    cv_begin(240, 124, T_SURF);
                    graph_grid(TSEL, T_THEME);
                    read_stop();
                    for (k = 0; k < NMSLOT; k++) {
                        TSEL->p[P_M1SRC + k * 3u] = k < 2u ? 1 : 0;
                        TSEL->p[P_M1DST + k * 3u] = k < 2u ? 1 : 0;
                        TSEL->p[P_M1AMT + k * 3u] = k == 0u ? 64 : 0;
                    }
                    mod_ui_slot = (uint8_t)state;
                    read_start(5);
                    cv_begin(240, 124, T_SURF);
                    graph_mod(TSEL, T_THEME);
                    read_stop();
                    go_home(); ui.force = 1;
                    read_start(6); draw_columns(); read_stop();
                    for (k = 0; k < MI_COUNT; k++) if (menu_native_row(k)) {
                        ui.menu = 1; ui.menu_sel = (uint8_t)k; ui.force = 1;
                        read_start(7); draw_menu(); read_stop();
                    }
                    ui.menu = 0;
                    name_open(NK_USER_SAVE, 0); ui.force = 1;
                    read_start(8); nm_draw_field(); read_stop(); name_close();
                    ui.force = 1; cv_begin(240, H_GRAPH, T_SURF);
                    read_start(9); graph_user(); read_stop();
                }
    for (k = 0; k < 10u; k++) {
        printf("LCD readability: %s, %u texts, %u below 4.5:1\n", names[k], read_count[k], read_low[k]);
        bad += !read_count[k] || read_low[k] != 0u;
    }
    bad += check("muted tracks retain their explicit MUTE badge", read_mutes == NPALETTES * 2u * 2u * 3u * 4u);
    legends &= !strcmp(KC[KC_SCL].label, "SEL") && !strcmp(KC[KC_SELECT].label, "SELECT");
    legends &= !strcmp(B_NAME[B_SCL], "SEL");
    for (k = 0; k < NELEM(HELP_PAGE); k++) {
        khint_t hint[3]; char words[48];
        if (strcmp(HELP_PAGE[k].title, "SCL") && strcmp(HELP_PAGE[k].title, "CHORD")) continue;
        legends &= help_parse(HELP_PAGE[k].hint, hint, words, sizeof words) == 3u && hint[2].key == KC_SCL;
    }
    { uint32_t n; legends &= kc_tag("[SEL]", &n) == KC_SCL && n == 5u; }
    bad += check("physical SEL and SELECT legends remain distinct and scale HELP parses every control", legends);
    {   /* #572: meaningful graphics (WCAG 1.4.11, 3:1) in every built-in palette: the knob's range fill on BG and
         * against its track, the accent (turning rule, curve dot), the curve and resting dot (THEME). DIM marks
         * an inactive knob (exempt; its state is also a word). The accent's own luminance is not relied on:
         * a turning knob also inverts its state (ui_bank.c bank_readout) */
        int gfx = 1;
        for (p = 0; p < NPALETTES; p++) {
            double bg, r[4];
            uint16_t pair[4][2];
            unsigned i;
            palette_set(p);
            bg = read_luma(T_BG);
            pair[0][0] = T_MID; pair[0][1] = T_BG; pair[1][0] = T_MID; pair[1][1] = T_LINE;
            pair[2][0] = T_ACCENT; pair[2][1] = T_BG; pair[3][0] = T_THEME; pair[3][1] = T_BG;
            (void)bg;
            for (i = 0; i < 4u; i++) {
                double a = read_luma(pair[i][0]), b = read_luma(pair[i][1]);
                r[i] = (fmax(a, b) + 0.05) / (fmin(a, b) + 0.05);
                gfx &= r[i] + 1e-9 >= 3.0;
            }
            printf("LCD graphics %-7s fill/BG %5.2f fill/track %5.2f accent/BG %5.2f curve/BG %5.2f\n", UI_PALETTES[p].name,
                   r[0], r[1], r[2], r[3]);
        }
        bad += check("graphics: knob range fill, its track, the accent and curves meet 3:1 in every built-in palette", gfx);
    }
    return bad != 0;
}
