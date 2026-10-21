/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* web/emu/felucca_web.c built natively (cc, as the host tests), playing emu_test.mjs's heavy song with the same
 * gestures and the same render calls: its samples, float32 L R interleaved, to OUT. emu_test.mjs compares the
 * WebAssembly build's against them (the browser plays what the host build plays).
 *   cc -O2 -ffp-contract=off -w -Ibuild/gen -Ifirmware/src -o build/emu/native_check web/emu/native_check.c -lm
 *   build/emu/native_check OUT.f32 */
#include "felucca_web.c"

static FILE *out;
static int rec;
static void render(double ms)                     /* as emu_test.mjs: 128-frame calls, the last one shorter */
{
    uint32_t n = (uint32_t)(ms * 44.1 + 0.5), k, i;
    for (k = 0; k < n; k += 128u) {
        uint32_t m = n - k < 128u ? n - k : 128u;
        web_render(m);
        for (i = 0; rec && i < m; i++) {
            float s[2] = {out_l[i], out_r[i]};
            fwrite(s, sizeof s, 1, out);
        }
    }
}

int main(int argc, char **argv)
{
    if (argc < 2 || !(out = fopen(argv[1], "wb")))
        return 2;
    web_nor_erase();
    web_boot();
    render(500);
    if (argc > 2 && !strcmp(argv[2], "macro")) {
        uint32_t pi;
        for (pi = 0; pi < web_test_macro_count(); pi++) {
            web_test_macro(pi); render(100);
            rec = 1;
            web_keys((1u << 7) | (1u << 11) | (1u << 14) | (1u << 19)); render(300);
            render(400);
            web_enc(EN_K1, 20); render(200);
            web_enc(EN_K2, -20); render(200);
            web_keys(0); render(1000);
            rec = 0; render(3000);
        }
        fclose(out);
        return 0;
    }
    web_test_heavy();
    web_buttons(1u << B_PLAY);
    render(60);
    web_buttons(0);
    render(60);
    rec = 1;
    render(2000);
    fclose(out);
    return 0;
}
