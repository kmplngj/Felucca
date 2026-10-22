/* SPDX-License-Identifier: GPL-3.0-only */
/* Diagnostic LCD submission capture. Main-loop only; owned eight-row storage, never
 * a DMA source. The ordered draw hash detects changes between repeated full draws;
 * it is not a checksum of the final image. The host checks and assembles that image. */
#if FELUCCA_SCREEN_CAPTURE
#define SCAP_W 240u
#define SCAP_H 240u
#define SCAP_ROWS 8u
#define SCAP_BYTES (SCAP_W * SCAP_ROWS * 2u)
#define SCAP_TTL 120000u
enum { SCAP_IDLE, SCAP_PENDING, SCAP_READY, SCAP_COMPLETE, SCAP_CHANGED,
       SCAP_EXPIRED, SCAP_CANCELLED, SCAP_COVERAGE, SCAP_ASLEEP, SCAP_UNSUPPORTED, SCAP_WAKING };
static struct {
    uint8_t pixels[SCAP_BYTES], coverage[SCAP_W * SCAP_ROWS / 8u];
    uint32_t token, offset, started, hash, draw_hash;
    uint16_t covered;
    uint8_t state, tapping, wake;
} scap;

static int scap_live(void)
{
    return scap.state == SCAP_WAKING || scap.state == SCAP_PENDING ||
           scap.state == SCAP_READY || scap.state == SCAP_COMPLETE;
}
static void scap_tick(uint32_t now)
{
    if (scap_live() && now - scap.started >= SCAP_TTL) {
        scap.state = SCAP_EXPIRED;
        scap.tapping = 0;
    }
}
/* Main-loop AUTO OFF guard, including time waiting for redraw or a stalled host.
 * Terminal states release it immediately; polling never renews the fixed TTL. */
static int scap_holding(uint32_t now)
{
    scap_tick(now);
    return scap.wake && scap_live();
}
static int scap_begin(uint32_t now)
{
    scap_tick(now);
    if (scap.state == SCAP_WAKING || scap.state == SCAP_PENDING || scap.state == SCAP_READY)
        return 0;
    if (!++scap.token) ++scap.token;
    scap.offset = scap.draw_hash = 0;
    scap.started = now;
    scap.tapping = scap.wake = 0;
    scap.state = SCAP_PENDING;
    return 1;
}
static int scap_next(uint32_t token, uint32_t offset)
{
    if (!token || token != scap.token || scap.state != SCAP_READY || offset != scap.offset + SCAP_BYTES)
        return 0;
    scap.offset = offset;
    scap.state = offset == SCAP_W * SCAP_H * 2u ? SCAP_COMPLETE : SCAP_PENDING;
    return 1;
}
static int scap_cancel(uint32_t token)
{
    if (!token || token != scap.token) return 0;
    scap.state = SCAP_CANCELLED;
    scap.tapping = 0;
    return 1;
}
static void scap_hash_byte(uint8_t b)
{
    scap.hash = (scap.hash ^ b) * 16777619u;
}
static void scap_hash_word(uint32_t n)
{
    uint32_t k;
    for (k = 0; k < 4u; k++, n >>= 8) scap_hash_byte((uint8_t)n);
}
static void scap_render_begin(void)
{
    uint32_t k;
    scap.hash = 2166136261u;
    scap.covered = 0;
    for (k = 0; k < sizeof scap.coverage; k++) scap.coverage[k] = 0;
    scap.tapping = scap.state == SCAP_PENDING;
}
static void scap_pixel(uint32_t x, uint32_t y, uint8_t hi, uint8_t lo)
{
    uint32_t top = scap.offset / (SCAP_W * 2u), i, mask;
    if (y < top || y >= top + SCAP_ROWS) return;
    i = (y - top) * SCAP_W + x;
    scap.pixels[2u * i] = hi;
    scap.pixels[2u * i + 1u] = lo;
    mask = 1u << (i & 7u);
    if (!(scap.coverage[i / 8u] & mask)) {
        scap.coverage[i / 8u] |= (uint8_t)mask;
        scap.covered++;
    }
}
static void scap_rect(uint32_t kind, uint32_t x, uint32_t y, uint32_t w, uint32_t h)
{
    scap_hash_word(kind); scap_hash_word(x); scap_hash_word(y);
    scap_hash_word(w); scap_hash_word(h);
}
static void scap_fill(uint32_t x, uint32_t y, uint32_t w, uint32_t h, uint16_t c)
{
    uint32_t xx, yy, top, end;
    if (!scap.tapping || !w || !h || x >= SCAP_W || y >= SCAP_H) return;
    if (w > SCAP_W - x) w = SCAP_W - x;
    if (h > SCAP_H - y) h = SCAP_H - y;
    scap_rect(0u, x, y, w, h);
    scap_hash_word(c);
    top = scap.offset / (SCAP_W * 2u);
    end = y + h < top + SCAP_ROWS ? y + h : top + SCAP_ROWS;
    if (y < top) y = top;
    for (yy = y; yy < end; yy++)
        for (xx = x; xx < x + w; xx++) scap_pixel(xx, yy, (uint8_t)(c >> 8), (uint8_t)c);
}
static void scap_blit(uint32_t x, uint32_t y, uint32_t w, uint32_t h, const uint16_t *px)
{
    uint32_t xx, yy, stride = w, cw = w, ch = h;
    const uint8_t *bytes = (const uint8_t *)px;
    if (!scap.tapping || !w || !h || x >= SCAP_W || y >= SCAP_H) return;
    /* Callers already require valid on-screen LCD extents. Bound capture independently,
     * preserving the original source stride for defensive right/bottom clipping. */
    if (cw > SCAP_W - x) cw = SCAP_W - x;
    if (ch > SCAP_H - y) ch = SCAP_H - y;
    if (stride > SCAP_W || h > SCAP_H) { scap.state = SCAP_COVERAGE; scap.tapping = 0; return; }
    scap_rect(1u, x, y, cw, ch);
    for (yy = 0; yy < ch; yy++) {
        for (xx = 0; xx < cw; xx++) {
            uint32_t i = 2u * (yy * stride + xx);
            scap_hash_byte(bytes[i]); scap_hash_byte(bytes[i + 1u]);
            scap_pixel(x + xx, y + yy, bytes[i], bytes[i + 1u]);
        }
    }
}
/* Call only after lcd_sync: READY promises the tapped draws completed on the LCD. */
static void scap_render_end(void)
{
    uint8_t tapped = scap.tapping;
    scap.tapping = 0;
    if (!tapped || scap.state != SCAP_PENDING) return;
    if (scap.covered != SCAP_W * SCAP_ROWS) scap.state = SCAP_COVERAGE;
    else if (scap.offset && scap.hash != scap.draw_hash) scap.state = SCAP_CHANGED;
    else { scap.draw_hash = scap.hash; scap.state = SCAP_READY; }
}
static uint32_t scap_crc(const uint8_t *p, uint32_t n)
{
    uint32_t c = ~0u, k;
    while (n--) {
        c ^= *p++;
        for (k = 0; k < 8u; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
    return ~c;
}
#endif
