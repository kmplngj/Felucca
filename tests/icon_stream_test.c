/* SPDX-License-Identifier: GPL-3.0-only */
/* Real Huffman renderer versus the separate unpacked-alpha renderer, using raw source raster input. */
#include "../firmware/hal/fm1_lcd_contract.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define __attribute__(x)
static void lcd_sync(void) {}
static void lcd_power(uint32_t s) { (void)s; }
static void lcd_wake_now(void) {}
#include "host_lcd_blit_noop.h"
#include "../firmware/src/gfx.c"
#include "ui_icons.h"
#include "icon-stream-reference.h"

static int compare(uint32_t w, uint32_t h, const uint8_t *packed, const uint8_t *book,
                   const uint8_t *raw, uint32_t clip, uint32_t flip, uint32_t cold, uint16_t bg)
{
    uint16_t expected[32 * 32];
    uint8_t mirrored[24 * 24 / 2] = {0};
    const uint16_t *rv = ramp(T_TEXT, bg);
    uint32_t x, y;
    int32_t px = clip == 1 ? -3 : clip == 2 ? 27 : 0;
    int32_t py = clip == 1 ? -5 : clip == 2 ? 27 : 0;
    if (flip) {
        for (y = 0; y < h; y++)
            for (x = 0; x < w; x++) {
                uint32_t from = y * w + (w - 1u - x), to = y * w + x;
                uint32_t v = raw[from / 2u] >> (from & 1u ? 0 : 4) & 15u;
                mirrored[to / 2u] |= (uint8_t)(v << (to & 1u ? 0 : 4));
            }
        raw = mirrored;
    }
    cv_oy = 0;
    cv_begin(32, 32, bg);
    if (clip == 3) { cv_cy0 = 4; cv_cy1 = 12; }
    cv_alpha(px, py, w, h, raw, rv);
    memcpy(expected, cv_px, sizeof expected);
    cv_begin(32, 32, bg);
    if (clip == 3) { cv_cy0 = 4; cv_cy1 = 12; }
    if (cold)
        memset(hc_tab, 0, sizeof hc_tab);
    cv_flip = (uint8_t)flip;
    cv_alpha_hc(px, py, w, h, packed, book, rv);
    cv_flip = 0;
    return !memcmp(expected, cv_px, sizeof expected);
}

static int boundaries(void)
{
    /* Canonical prefix chain: symbol i < 14 has length i+1; symbols 14/15 length 15. */
    static const uint8_t book[] = {1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15};
    static const uint8_t long_stream[] = {0xff,0xfd,0xff,0xff,0xf8,0x00,0x00};
    static const uint8_t odd_raw[] = {0xef,0x70};    /* 15 bits + 15 bits + 8 bits, three meaningful pixels */
    uint32_t symbol;
    for (symbol = 0; symbol < 16u; symbol++) {
        uint32_t len = symbol < 14u ? symbol + 1u : 15u;
        uint32_t code = symbol == 15u ? 32767u : (1u << len) - 2u;
        uint32_t bytes = (len + 7u) / 8u, total = bytes + 2u;
        uint8_t raw = (uint8_t)(symbol << 4), *stream;
#ifdef ICON_PAD_MUTATION
        total = bytes;                              /* negative ASan fixture: omit the required lookahead */
#endif
        stream = calloc(total, 1);
        if (!stream)
            return 0;
        code <<= bytes * 8u - len;
        stream[0] = (uint8_t)(code >> (bytes == 2u ? 8 : 0));
        if (bytes == 2u)
            stream[1] = (uint8_t)code;
        if (!compare(1, 1, stream, book, &raw, 0, 0, 1, T_BG)) {
            free(stream);
            return 0;
        }
        free(stream);                                /* exact allocation lets ASan check final padding reads */
    }
    return compare(3, 1, long_stream, book, odd_raw, 0, 0, 1, T_BG) &&
           compare(3, 1, long_stream, book, odd_raw, 0, 1, 0, T_BG) &&
           compare(0, 0, long_stream, book, odd_raw, 0, 0, 1, T_BG);
}

static void benchmark(void)
{
    uint32_t clip, cold, repeat, cell, flip;
    volatile uint32_t checksum = 0;
    palette_set(0);
    cv_oy = 0;
    for (cold = 0; cold < 2u; cold++)
        for (clip = 0; clip < 4u; clip++) {
            uint32_t draws = 0;
            clock_t start = clock();
            for (repeat = 0; repeat < 40u; repeat++)
                for (cell = 0; cell < sizeof icon_cases / sizeof icon_cases[0]; cell++)
                    for (flip = 0; flip < 2u; flip++) {
                        const uint16_t *rv = ramp(T_TEXT, T_BG);
                        int32_t x = clip == 1u ? -3 : clip == 2u ? 27 : 0;
                        int32_t y = clip == 1u ? -5 : clip == 2u ? 27 : 0;
                        cv_begin(32, 32, T_BG);
                        if (clip == 3u) { cv_cy0 = 4; cv_cy1 = 12; }
                        if (cold)
                            memset(hc_tab, 0, sizeof hc_tab);
                        cv_flip = (uint8_t)flip;
                        cv_alpha_hc(x, y, icon_cases[cell].size, icon_cases[cell].size,
                                    icon_cases[cell].packed, AI_HC, rv);
                        checksum += cv_px[cell % (32u * 32u)];
                        draws++;
                    }
            printf("bench cold=%u clip=%u draws=%u ns_per_draw=%.3f checksum=%u\n", cold, clip, draws,
                   (double)(clock() - start) * 1e9 / CLOCKS_PER_SEC / draws, checksum);
        }
    cv_flip = 0;
}

int main(int argc, char **argv)
{
    uint32_t pal, style, cell, clip, flip, cold, scenes = 0;
    if (argc == 2 && !strcmp(argv[1], "--bench")) {
        benchmark();
        return 0;
    }
    for (pal = 0; pal < NPALETTES; pal++)
        for (style = 0; style < 2u; style++) {
            palette_set(pal);
            ux.style = (uint8_t)style;
            for (cell = 0; cell < sizeof icon_cases / sizeof icon_cases[0]; cell++)
                for (clip = 0; clip < 4u; clip++)
                    for (flip = 0; flip < 2u; flip++)
                        for (cold = 1; cold < 3u; cold++) {
                            uint32_t size = icon_cases[cell].size;
                            if (!compare(size, size, icon_cases[cell].packed, AI_HC, icon_cases[cell].raw,
                                         clip, flip, cold == 1u, style ? T_BG : T_SURF)) {
                                printf("FAIL palette=%u style=%u cell=%u size=%u clip=%u flip=%u cold=%u\n",
                                       pal, style, cell, size, clip, flip, cold == 1u);
                                return 1;
                            }
                            scenes++;
                        }
        }
    if (!boundaries()) {
        puts("FAIL: empty/odd/1..15-bit-code/final-lookahead boundary");
        return 1;
    }
    printf("Icons: %u actual C pixel comparisons; every cell, palette, style, clip, mirror and cold/hot cache; boundaries passed\n",
           scenes);
    return 0;
}
