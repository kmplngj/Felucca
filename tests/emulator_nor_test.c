/* SPDX-License-Identifier: GPL-3.0-only */
/* Actual emulator storage hooks, page contract, and panel save across processes. */
#include "../web/emu/felucca_web.c"
#ifdef __EMSCRIPTEN__
/* Only this test module exports a direct storage probe; the page does not. */
EXPORT int emulator_nor_program(uint32_t off, uint32_t n)
{
    uint8_t bytes[2] = {0x35, 0x69};
    return n > sizeof bytes ? -1 : st_prog(off, bytes, n);
}
#else
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "emulator NOR line %d: %s\n", __LINE__, #x); return 1; } } while (0)

static void render_ms(uint32_t ms)
{
    uint32_t n = ms * 441u / 10u;
    while (n) {
        uint32_t part = n > 128u ? 128u : n;
        web_render(part);
        n -= part;
    }
}
static void tap(uint32_t button)
{
    web_buttons(1u << button); render_ms(60);
    web_buttons(0); render_ms(60);
}
static int bounds(void)
{
    uint8_t b[256], got[4];
    uint32_t writes;
    memset(nor, 0x96, sizeof nor); memset(b, 0x35, sizeof b);
    memset(got, 0xA5, sizeof got);
    CHECK(st_read(0, got, 4) == 0 && got[0] == 0x96 && got[3] == 0x96);
    CHECK(st_read(sizeof nor - 1u, got, 1) == 0);
    memset(got, 0xA5, sizeof got);
    CHECK(st_read(sizeof nor, got, 0) == -1 && st_read(UINT32_MAX, got, 1) == -1);
    CHECK(st_read(sizeof nor - 1u, got, 2) == -1 && got[0] == 0xA5);
    CHECK(st_read(0, got, 0) == 0 && !web_flash_writes);
    CHECK(st_erase(0x1024) == 0 && web_flash_writes == 1);
    for (uint32_t i = 0; i < sizeof nor; i++) CHECK(nor[i] == (i >= 0x1000 && i < 0x2000 ? 0xFF : 0x96));
    CHECK(st_erase(sizeof nor - 4096u) == 0 && web_flash_writes == 2);
    CHECK(st_erase(sizeof nor - 4095u) == -8 && st_erase(UINT32_MAX) == -8 && web_flash_writes == 2);
    CHECK(st_prog(0x1100, b, sizeof b) == 0 && web_flash_writes == 3);
    memset(b, 0x4F, sizeof b);
    CHECK(st_prog(0x1100, b, sizeof b) == 0 && web_flash_writes == 4);
    for (uint32_t i = 0; i < sizeof b; i++) CHECK(nor[0x1100 + i] == (0x35 & 0x4F));
    CHECK(nor[0x10FF] == 0xFF && nor[0x1200] == 0xFF);
    CHECK(st_prog(0x12FF, b, 1) == 0 && nor[0x12FF] == 0x4F);
    CHECK(st_prog(sizeof nor - 1u, b, 1) == 0 && nor[sizeof nor - 1u] == 0x4F);
    writes = web_flash_writes;
    CHECK(st_prog(0x12FF, b, 0) == 0 && web_flash_writes == writes + 1u);
    CHECK(st_prog(sizeof nor, b, 0) == -8 && st_prog(UINT32_MAX, b, 1) == -8);
    CHECK(st_prog(sizeof nor - 1u, b, 2) == -8 && web_flash_writes == writes + 1u);
    CHECK(nor[sizeof nor - 1u] == 0x4F);
    puts("emulator NOR bounds, rounding, AND, zero-length and write counts passed");
    return 0;
}
static int persistence(int restore)
{
    uint32_t summary[8];
    float pcm[256];
    web_nor_erase();
    if (restore) CHECK(fread(nor, sizeof nor, 1, stdin) == 1);
    web_boot(); render_ms(600);
    CHECK(flash_ok && web_test_user_preset(0) == (uint32_t)restore);
    if (!restore) {
        tap(B_SAVE); tap(B_OCTUP); tap(B_OCTUP); render_ms(200);
        CHECK(web_test_user_preset(0) == 1 && web_flash_writes > 0);
    }
    CHECK(up_load(0) == 0);
    web_keys((1u << 7) | (1u << 11)); render_ms(100);
    web_render(128);
    for (uint32_t i = 0; i < 128; i++) { pcm[i * 2] = out_l[i]; pcm[i * 2 + 1] = out_r[i]; }
    summary[0] = web_flash_writes; summary[1] = fm1_ms; summary[2] = web_ticks; summary[3] = web_draws;
    summary[4] = web_test_user_preset(0); summary[5] = TSEL->engine; summary[6] = ring_r; summary[7] = ring_w;
    /* The NOR prefix can be fed directly to the next fresh process. */
    CHECK(fwrite(nor, sizeof nor, 1, stdout) == 1);
    CHECK(fwrite(summary, sizeof summary, 1, stdout) == 1);
    CHECK(fwrite(web_fb, sizeof web_fb, 1, stdout) == 1);
    CHECK(fwrite(pcm, sizeof pcm, 1, stdout) == 1);
    return 0;
}
int main(int argc, char **argv)
{
    if (argc == 1) return bounds();
    if (!strcmp(argv[1], "save")) return persistence(0);
    if (!strcmp(argv[1], "load")) return persistence(1);
    if (!strcmp(argv[1], "page-wrap")) {
        uint8_t b[2] = {0x35, 0x69};
        web_nor_erase();
        st_prog(0xFF, b, sizeof b);
        fputs("page-spanning write was accepted\n", stderr);
        return 0;
    }
    return 2;
}
#endif
