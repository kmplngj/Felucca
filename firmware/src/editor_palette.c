/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* CUSTOM, the user's palette, for the editor (1.6, #244, Discussion #239; EDITOR_PROTOCOL.md "CUSTOM palette"; INFO 45 01 5):
 * PALETTE_GET reads it, PALETTE_SET shows five colours at once (a preview, RAM only), stores them (the palette in use from
 * then on, saved with the settings), removes it or goes back to the stored one. The colours are the five a palette stores
 * (color1 color2 color3 primary secondary), each as three 7-bit bytes (red 0..31, green 0..63, blue 0..31 of RGB565); the rest of the
 * tokens is derived as for every palette (gfx.c palette_set). Colours that are hard to read are not refused: the editor warns
 * (its rule, EDITOR_PROTOCOL.md), the device keeps what it is given. A way back is always there: PALETTE_SET op 2, or MENU >
 * DISPLAY > COLOR, the first row of the first tab */
enum { ED_PALETTE_GET = 80, ED_PALETTE_SET };
#define ED_PAL_N 5u
/* Read the persisted new order, or the current palette when no CUSTOM is stored. */
static void ed_palette_colors(uint16_t *c)
{
    uint32_t i, stored;
    cpal_fix();
    stored = (ui_cpal_flags & CPAL_STORED) != 0u;
    for (i = 0; i < ED_PAL_N; i++)
        c[i] = stored ? (uint16_t)(ui_cpal[2u * i] | ui_cpal[2u * i + 1u] << 8) : ux.pal[i];
}
/* Legacy clients keep BG SURF TEXT THEME ACCENT and flags 0..3. Only an explicit new-order request gets bit 2. */
static void ed_palette_body(uint32_t v2)
{
    uint16_t c[ED_PAL_N];
    uint32_t i;
    ed_palette_colors(c);
    if (!v2) {
        c[3] = c[1];                               /* THEME = color2; native Direction A's SURF = BG */
        c[1] = c[0];
    }
    ed_b((ui_cpal_flags & (CPAL_STORED | CPAL_ACTIVE)) | (v2 ? 4u : 0u));
    ed_b(ED_PAL_N);
    for (i = 0; i < ED_PAL_N; i++) {
        ed_b(c[i] >> 11); ed_b((c[i] >> 5) & 63u); ed_b(c[i] & 31u);
    }
}
static int ed_palette_handle(uint32_t cmd, const uint8_t *a, uint32_t n)
{
    uint32_t rc = 1, i, op = n ? a[0] : 255u, v2 = op >= 16u && op <= 19u;
    uint16_t c[ED_PAL_N];
    if (cmd == ED_PALETTE_GET) {
        ed_palette_body(n == 1u && a[0] == 2u);
        return 1;
    }
    if (cmd != ED_PALETTE_SET)
        return 0;
    if (v2) op -= 16u;
    if (n == 1u + 3u * ED_PAL_N && op <= 1u) {       /* 0 preview, 1 store: op, then 5 x (r, g, b) */
        uint16_t prior[ED_PAL_N];
        ed_palette_colors(prior);
        rc = 0;
        for (i = 0; i < ED_PAL_N; i++) {
            if (a[1 + 3 * i] > 31u || a[2 + 3 * i] > 63u || a[3 + 3 * i] > 31u)
                rc = 1;
            c[i] = (uint16_t)(a[1 + 3 * i] << 11 | a[2 + 3 * i] << 5 | a[3 + 3 * i]);
        }
        if (!v2) {                                /* The old client edits no primary; keep the existing one. */
            c[1] = c[3];
            c[3] = prior[3];
        }
        if (!rc && op == 0u) {                       /* preview: gfx.c's copy only, nothing stored */
            ux_cust.c1 = c[0]; ux_cust.c2 = c[1]; ux_cust.c3 = c[2]; ux_cust.primary = c[3]; ux_cust.secondary = c[4];
            palette_set(NPALETTES);
            ui.force = 1;
        } else if (!rc) {
            cpal_store(c);
            ui_cpal_flags |= CPAL_ACTIVE;
            palette_apply();
            ui.force = 1;
            rc = ed_settings_save();                         /* as UI_SET: 0 saved, 3 RAM only, 4 queued until STOP */
        }
    } else if (n == 1u && op == 2u) {                /* 2: removed (the built-in palette in use before is back) */
        memset(ui_cpal, 0, 2u * ED_PAL_N);
        ui_cpal_flags = 0;
        palette_apply();
        ui.force = 1;
        rc = ed_settings_save();
    } else if (n == 1u && op == 3u) {                /* 3: the preview dropped (the palette in use again) */
        palette_apply();
        ui.force = 1;
        rc = 0;
    }
    ed_b(rc);
    ed_palette_body(v2);
    return 1;
}
