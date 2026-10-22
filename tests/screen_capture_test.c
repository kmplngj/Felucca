/* SPDX-License-Identifier: GPL-3.0-only */
/* Full-frame storage belongs only to this independent, delayed-DMA LCD oracle. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define FELUCCA_SCREEN_CAPTURE 1
#include "../firmware/src/screen_capture.c"

static uint8_t image[240u * 240u * 2u], assembled[sizeof image], dma_copy[sizeof image];
static const uint8_t *dma_src;
static uint32_t dma_n, selected, command, x0, x1, y0, y1, cx, cy, transfers, checks;
static void need(int ok, const char *why)
{
    checks++;
    if (!ok) { fprintf(stderr, "FAIL screenshot model: %s (state=%u offset=%u)\n", why, scap.state, scap.offset); exit(1); }
}
static void fm1_lcd_hw_init(void) {}
static void fm1_lcd_baud(uint32_t b) { (void)b; }
static void fm1_lcd_backlight(uint32_t on) { (void)on; }
static void fm1_lcd_send_cmd(uint8_t c)
{
    need(!selected && !dma_src, "command owns an idle bus");
    command = c; selected = 1;
    if (c == 0x2Cu) { cx = x0; cy = y0; }
}
static void fm1_lcd_send_data(const void *p, uint32_t n)
{
    need(!selected && !dma_src && n && n <= sizeof dma_copy, "bounded DMA begins on idle bus");
    selected = 1; dma_src = p; dma_n = n;
    memcpy(dma_copy, p, n); transfers++;
}
static void fm1_lcd_wait(void)
{
    uint32_t i;
    need(selected, "completion has a selected transfer");
    if (!dma_src) return;
    need(!memcmp(dma_src, dma_copy, dma_n), "in-flight source remains unchanged");
    if (command == 0x2Au || command == 0x2Bu) {
        uint32_t a, b;
        need(dma_n == 4u, "window command has four bytes");
        a = (uint32_t)dma_src[0] * 256u + dma_src[1];
        b = (uint32_t)dma_src[2] * 256u + dma_src[3];
        need(a <= b && b < 240u, "LCD window stays on screen");
        if (command == 0x2Au) { x0 = a; x1 = b; } else { y0 = a; y1 = b; }
    } else {
        need(command == 0x2Cu && !(dma_n & 1u), "pixel transfer is RGB565 pairs");
        for (i = 0; i < dma_n; i += 2u) {
            uint32_t at = (cy * 240u + cx) * 2u;
            need(cx <= x1 && cy <= y1, "pixel lies inside programmed window");
            image[at] = dma_src[i]; image[at + 1u] = dma_src[i + 1u];
            if (++cx > x1) { cx = x0; cy++; }
        }
    }
    dma_src = NULL; dma_n = 0;
}
static void fm1_lcd_deselect(void) { need(selected && !dma_src, "deselect after completion"); selected = 0; }
#include "../firmware/src/lcd.c"

static uint16_t patch[13u * 19u];
static void scene(uint16_t accent)
{
    lcd_fill(0, 0, 240, 240, 0x1843);
    lcd_fill(3, 5, 121, 27, 0xF800);
    lcd_blit(117, 7, 13, 19, patch);
    lcd_fill(119, 8, 2, 3, 0x07E0);
    lcd_fill(238, 238, 20, 20, 0x001F); /* real driver clipping */
    lcd_fill(0, 239, 240, 1, accent);
}
static void reset_capture(void)
{
    lcd_sync(); memset(&scap, 0, sizeof scap);
    need(scap_begin(100u), "begin new capture");
}
static void render_scene(uint16_t accent)
{
    scap_render_begin(); scene(accent);
    need(dma_src != NULL && scap.state == SCAP_PENDING, "last DMA remains pending until explicit sync");
    lcd_sync(); scap_render_end();
}
static void test_image(void)
{
    uint32_t i, token, hash = 0;
    uint8_t *p = (uint8_t *)patch;
    for (i = 0; i < sizeof patch; i += 2u) { p[i] = (uint8_t)(i * 17u); p[i + 1u] = (uint8_t)(255u - i); }
    reset_capture(); token = scap.token;
    for (i = 0; i < sizeof image; i += SCAP_BYTES) {
        render_scene(0xFFE0);
        need(scap.state == SCAP_READY && scap.covered == 1920u && !dma_src && !lcd_busy, "complete band published only after DMA");
        need(!memcmp(scap.pixels, image + i, SCAP_BYTES), "captured band equals independently decoded LCD wire pixels");
        if (!i) hash = scap.draw_hash;
        need(scap.draw_hash == hash, "static ordered stream coherent across all 30 bands");
        memcpy(assembled + i, scap.pixels, SCAP_BYTES);
        need(scap_next(token, i + SCAP_BYTES), "exact band acknowledgment");
    }
    need(scap.state == SCAP_COMPLETE && !memcmp(image, assembled, sizeof image), "full RGB565 image matches LCD oracle");
    need(!scap_next(token, sizeof image + SCAP_BYTES) && scap.offset == sizeof image && scap.state == SCAP_COMPLETE,
         "completed image cannot advance past the final band");
    need(assembled[0] == 0x18 && assembled[1] == 0x43 && assembled[sizeof image - 2u] == 0xFF && assembled[sizeof image - 1u] == 0xE0,
         "RGB565 big-endian channels and final pixel preserved");
}
static void test_coverage_and_clipping(void)
{
    uint8_t *p = (uint8_t *)patch;
    uint32_t i;
    reset_capture(); scap_render_begin();
    scap_fill(0, 0, 239, 8, 0); scap_fill(239, 0, 1, 7, 0); scap_fill(0, 0, 239, 8, 1);
    scap_render_end(); need(scap.covered == 1919u && scap.state == SCAP_COVERAGE, "overlap cannot hide a single uncovered pixel");
    reset_capture(); scap_render_begin(); scap_fill(0, 0, UINT32_MAX, UINT32_MAX, 0xA53C);
    scap_blit(238, 6, 13, 19, patch); scap_render_end();
    need(scap.state == SCAP_READY && scap.covered == 1920u, "defensive fill and blit clipping cover exactly one band");
    for (i = 0; i < 2; i++)
        need(!memcmp(scap.pixels + ((6u + i) * 240u + 238u) * 2u, p + i * 13u * 2u, 4u), "clipped blit retains original source stride");
    reset_capture(); scap.offset = sizeof image - SCAP_BYTES; scap_render_begin();
    scap_fill(0, 0, 240, 240, 0); scap_blit(238, 238, 13, 19, patch);
    for (i = 0; i < 2; i++)
        need(!memcmp(scap.pixels + ((6u + i) * 240u + 238u) * 2u, p + i * 13u * 2u, 4u), "right and bottom clipping preserves final RGB565 pixels");
    scap_cancel(scap.token);
    reset_capture(); scap_render_begin();
    scap_blit(240, 0, UINT32_MAX, UINT32_MAX, NULL); scap_blit(0, 240, 1, 1, NULL); scap_blit(0, 0, 0, 1, NULL);
    need(!scap.covered && scap.tapping, "empty and off-screen rectangles never dereference source");
    scap_blit(0, 0, UINT32_MAX, 1, NULL);
    need(scap.state == SCAP_COVERAGE && !scap.tapping, "oversized source stride rejected before access");
    reset_capture(); scap_render_begin(); scap_blit(0, 0, 1, UINT32_MAX, NULL);
    need(scap.state == SCAP_COVERAGE, "oversized source height rejected before access");
}
static void test_coherence(void)
{
    uint8_t saved[SCAP_BYTES];
    uint32_t token;
    reset_capture(); token = scap.token; render_scene(0xFFE0); memcpy(saved, scap.pixels, sizeof saved);
    scene(0x1234); lcd_sync();
    need(!memcmp(saved, scap.pixels, sizeof saved), "ordinary LCD drawing cannot mutate a READY band");
    need(scap_next(token, SCAP_BYTES), "advance for changed-scene test"); render_scene(0x1234);
    need(scap.state == SCAP_CHANGED, "change outside captured band invalidates complete ordered stream");
    reset_capture(); scap_render_begin(); scap_fill(0, 0, 240, 240, 0); scap_render_end();
    token = scap.token; need(scap_next(token, SCAP_BYTES), "advance equivalent-image test");
    scap_render_begin(); scap_fill(0, 0, 240, 240, 1); scap_fill(0, 0, 240, 240, 0); scap_render_end();
    need(scap.state == SCAP_CHANGED, "ordered operation signature is conservatively distinct from final image CRC");
}
static void test_lifecycle(void)
{
    uint32_t token, i, before;
    reset_capture(); token = scap.token;
    need(!scap_begin(101) && !scap_next(token, SCAP_BYTES), "PENDING is busy and cannot be acknowledged");
    scap_render_end(); need(scap.state == SCAP_PENDING, "end without render begin cannot publish stale coverage");
    render_scene(0xFFE0); before = transfers;
    need(!scap_begin(101) && scap.state == SCAP_READY, "READY cannot be replaced by a second capture");
    for (i = 0; i < 100u; i++) { scap_tick(101u + i); need(scap.state == SCAP_READY && scap.started == 100u, "slow host preserves band without extending session TTL"); }
    need(transfers == before, "waiting for host does not initiate LCD work");
    need(!scap_next(0, SCAP_BYTES) && !scap_next(token + 1u, SCAP_BYTES) && !scap_next(token, 0) &&
         !scap_next(token, SCAP_BYTES + 1u) && !scap_next(token, UINT32_MAX) && scap.offset == 0 && scap.state == SCAP_READY,
         "invalid token and offsets leave READY band unchanged");
    need(!scap_cancel(0) && !scap_cancel(token + 1u), "stale cancellation has no effect");
    need(scap_next(token, SCAP_BYTES), "advance valid band"); scap_render_end();
    need(scap.state == SCAP_PENDING, "new band cannot reuse prior render coverage");
    scap_render_begin(); need(scap_cancel(token), "cancel active tap"); scap_fill(0, 0, 240, 240, 0); scap_render_end();
    need(scap.state == SCAP_CANCELLED && !scap.tapping, "cancellation prevents completion");
    scap.token = UINT32_MAX; need(scap_begin(0) && scap.token == 1u, "token wraps to nonzero");
    for (i = SCAP_PENDING; i <= SCAP_COMPLETE; i++) {
        scap.state = (uint8_t)i; scap.started = UINT32_MAX - 200u; scap.tapping = 1;
        scap_tick(scap.started + SCAP_TTL - 1u); need(scap.state == i, "TTL remains valid immediately before boundary across clock wrap");
        scap_tick(scap.started + SCAP_TTL); need(scap.state == SCAP_EXPIRED && !scap.tapping, "PENDING READY COMPLETE expire at fixed begin deadline");
    }
    token = scap.token; need(scap_begin(200) && scap.token != token, "expired session can be replaced without accepting stale token");
    need(!scap_cancel(token) && scap_cancel(scap.token), "new session protects against old cancellation");
    need(scap_begin(100u), "start waking lifecycle");
    scap.state = SCAP_WAKING; scap.wake = 1;
    need(scap_holding(100u) && !scap_begin(101u), "waking is live, holds awake and rejects competing BEGIN");
    need(scap_holding(100u + SCAP_TTL - 1u), "waking hold lasts to fixed expiry");
    need(!scap_holding(100u + SCAP_TTL) && scap.state == SCAP_EXPIRED, "abandoned waking expires without host polls");
    for (i = SCAP_CHANGED; i <= SCAP_UNSUPPORTED; i++) {
        scap.state = (uint8_t)i;
        need(!scap_holding(100u), "every terminal error or cancellation releases wake hold");
    }
    need(scap_crc((const uint8_t *)"123456789", 9) == 0xCBF43926u && scap_crc(NULL, 0) == 0u, "IEEE CRC32 known vectors");
}
int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "--dma-negative")) {
        lcd_blit(0, 0, 13, 19, patch); patch[0] ^= 1u;
        lcd_sync(); /* expected failure: demonstrates delayed source-ownership oracle */
        return 0;
    }
    if (argc != 1) return 2;
    test_image(); test_coverage_and_clipping(); test_coherence(); test_lifecycle();
    printf("PASS screen capture: delayed-DMA RGB565 oracle, 30 bands, coverage, coherence, lifecycle (%u checks)\n", checks);
    return 0;
}
