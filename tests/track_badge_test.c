/* SPDX-License-Identifier: GPL-3.0-only */
/* Check the actual framebuffer difference from an empty cushion, independently
 * of the text placement expression and alignment hook. Native M8 1..4: all
 * palettes, FLAT/LINE, active/lit/idle/dim, 12/16 px used by normal/LARGE callers
 * and the supported 24 px path. A parity tie must go left/up, at most 0.5 px.
 * Optional argv[1]: RGB PPM, palette/state rows and 12/16/24 px columns. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define __attribute__(x)
#define FELUCCA_ICONS 0
#define NTRK 4u
typedef struct param_desc param_desc_t;
typedef struct track track_t;
typedef struct page page_t;
static void lcd_sync(void) {}
static void lcd_power(uint32_t s) { (void)s; }
static void lcd_wake_now(void) {}
static void lcd_blit(uint32_t x, uint32_t y, uint32_t w, uint32_t h, const uint16_t *p)
{ (void)x; (void)y; (void)w; (void)h; (void)p; }
static int32_t hook_box[4];
#define GFX_HOOK_ALIGN(x0, y0, x1, y1, mode, tag) \
    (hook_box[0] = (x0), hook_box[1] = (y0), hook_box[2] = (x1), hook_box[3] = (y1))
#define GFX_HOOK_PEN(y, f) ((void)0)
#define GFX_HOOK_ITEM(x0, y0, x1, y1) ((void)0)
#define GFX_HOOK_ICON(x, y, size, id) ((void)0)
#include "gfx.c"
#include "icons.c"
#define W 40u
#define H 40u
static uint16_t empty[W * H], actual[W * H];
static unsigned failures, cases;
static uint16_t sheet[360u * (10u * 4u * 36u)];
static void bounds(const uint16_t *a, const uint16_t *b, int32_t box[4])
{
    uint32_t x, y;
    box[0] = box[1] = 1000; box[2] = box[3] = -1000;
    for (y = 0; y < H; y++) for (x = 0; x < W; x++)
        if (a[y * W + x] != (b ? b[y * W + x] : swap16(cv_bg))) {
            if ((int32_t)x < box[0]) box[0] = (int32_t)x;
            if ((int32_t)y < box[1]) box[1] = (int32_t)y;
            if ((int32_t)x + 1 > box[2]) box[2] = (int32_t)x + 1;
            if ((int32_t)y + 1 > box[3]) box[3] = (int32_t)y + 1;
        }
}
static void require(int ok, const char *reason, unsigned palette, unsigned state, unsigned size, unsigned k)
{
    if (ok)
        return;
    if (failures < 12u)
        fprintf(stderr,"track badge %s: palette %u state %u size %u digit %u\n",reason,palette,state,size,k+1u);
    failures++;
}
int main(int argc, char **argv)
{
#if !UI_FONT_M8STEALTH
    (void)argc; (void)argv;
    puts("Track badges: M8 pixel fixture skipped for alternate face; UI alignment sweeps still apply");
    return 0;
#else
    static const unsigned sizes[] = {12, 16, 24};
    uint32_t st, p, s, si, k, x, y;
    for (st = ST_FLAT; st <= ST_LINE; st++) for (p = 0; p < NPALETTES; p++) {
        ux.style = (uint8_t)st;
        palette_set(p);
        for (s = 0; s < 4; s++) {
            uint16_t fill = s == 0 ? T_ACCENT : s == 1 ? T_TEXT : s == 2 ? T_MID : T_DIM;
            uint16_t under = s == 0 || s == 1 ? T_BG : T_SURF;
            for (si = 0; si < 3; si++) for (k = 0; k < 4; k++) {
                unsigned size = sizes[si], in = size == 24 ? 2 : 0, width = size - 2 * in;
                int32_t cushion[4], digit[4], dx, dy;
                cv_begin(W, H, under);
                cv_rrect(4 + in, 4 + in, width, width, -(int32_t)(width / 4), fill, under);
                memcpy(empty, cv_px, sizeof empty);
                bounds(empty, 0, cushion);
                cv_begin(W, H, under);
                require(cv_icon_on(4,4,size,trk_icon(k,1),fill,under)==(int32_t)size,"return width",p,s,size,k);
                memcpy(actual, cv_px, sizeof actual);
                bounds(actual, empty, digit);
                dx = digit[0] + digit[2] - cushion[0] - cushion[2];
                dy = digit[1] + digit[3] - cushion[1] - cushion[3];
                if (!st && !p && !s) printf("size%u digit%u cushion %d,%d..%d,%d ink %d,%d..%d,%d offset %+.1f,%+.1f\n",size,k+1,cushion[0],cushion[1],cushion[2],cushion[3],digit[0],digit[1],digit[2],digit[3],dx/2.,dy/2.);
                require(dx >= -1 && dx <= 0 && dy >= -1 && dy <= 0,"ink centre",p,s,size,k);
                require(!memcmp(hook_box, cushion, sizeof cushion),"true hook bounds",p,s,size,k);
                require(digit[0]>cushion[0] && digit[1]>cushion[1] && digit[2]<cushion[2] && digit[3]<cushion[3],"contained ink",p,s,size,k);
                for (y = 0; y < H; y++) for (x = 0; x < W; x++) if (actual[y * W + x] != empty[y * W + x])
                    require(actual[y * W + x] == swap16(under) && empty[y * W + x] == swap16(fill),"binary native ink",p,s,size,k);
                cv_begin(W, H, under); cv_icon_on(4,4,size,trk_icon(k,0),fill,under);
                require(!memcmp(actual, cv_px, sizeof actual),"filled argument compatibility",p,s,size,k);
                if (!st) for (y = 0; y < 32; y++) for (x = 0; x < 26; x++)
                    sheet[((p * 4 + s) * 36 + y) * 360 + si * 120 + k * 28 + x] = swap16(actual[y * W + x]);
                cases++;
            }
        }
    }
    if (argc > 1) {
        FILE *f = fopen(argv[1], "wb");
        if (!f) return 2;
        fprintf(f,"P6\n360 1440\n255\n");
        for (x = 0; x < 360u * 1440u; x++) {
            uint16_t v = sheet[x];
            fputc((v >> 11) * 255 / 31, f);
            fputc(((v >> 5) & 63) * 255 / 63, f);
            fputc((v & 31) * 255 / 31, f);
        }
        fclose(f);
    }
    printf("Track badges: %u rendered cases, %u failures\n",cases,failures);
    return failures != 0;
#endif
}
