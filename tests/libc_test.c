/* SPDX-License-Identifier: GPL-3.0-only */
/* Exercise the firmware implementations, including their aliasing attribute,
 * rather than compiler builtins or the host libc. No generated assets needed. */
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define memcpy felucca_memcpy
#define memset felucca_memset
#define memcmp felucca_memcmp
#include "../firmware/src/libc.c"
#undef memcpy
#undef memset
#undef memcmp

#define CAP 4097u
#define GUARD 16u
typedef union {
    uint32_t align;
    unsigned char byte[CAP + 2u * GUARD + 4u];
} buffer_t;
static unsigned cases;

static int copy_case(unsigned n, unsigned da, unsigned sa)
{
    buffer_t src, dst;
    unsigned i, start = GUARD + da;
    for (i = 0; i < sizeof src.byte; i++) {
        src.byte[i] = (unsigned char)(i * 37u + (i >> 3));
        dst.byte[i] = 0xa5;
    }
    if (felucca_memcpy(dst.byte + start, src.byte + GUARD + sa, n) != dst.byte + start)
        return 1;
    for (i = 0; i < sizeof dst.byte; i++) {
        unsigned char want = i >= start && i - start < n ? src.byte[GUARD + sa + i - start] : 0xa5;
        if (dst.byte[i] != want || src.byte[i] != (unsigned char)(i * 37u + (i >> 3))) {
            fprintf(stderr, "memcpy: n=%u dst=%u src=%u byte=%u\n", n, da, sa, i);
            return 1;
        }
    }
    cases++;
    return 0;
}

static int fill_case(unsigned n, unsigned da, int value)
{
    buffer_t dst;
    unsigned i, start = GUARD + da;
    for (i = 0; i < sizeof dst.byte; i++) dst.byte[i] = 0xa5;
    if (felucca_memset(dst.byte + start, value, n) != dst.byte + start)
        return 1;
    for (i = 0; i < sizeof dst.byte; i++) {
        unsigned char want = i >= start && i - start < n ? (unsigned char)value : 0xa5;
        if (dst.byte[i] != want) {
            fprintf(stderr, "memset: n=%u dst=%u value=%d byte=%u\n", n, da, value, i);
            return 1;
        }
    }
    cases++;
    return 0;
}

/* Exact allocation ends let ASan catch source overreads as well as writes.
 * The ordinary sentinel sweep alone cannot detect unused extra source reads. */
static int allocation_edges(void)
{
    unsigned n, da, sa, i;
    for (n = 0; n <= 65u; n++) for (da = 0; da < 4u; da++) for (sa = 0; sa < 4u; sa++) {
        unsigned char *d = malloc(n + da + 1u), *s = malloc(n + sa + 1u);
        if (!d || !s) exit(2);
        for (i = 0; i <= n + da; i++) d[i] = 0xa5;
        for (i = 0; i <= n + sa; i++) s[i] = (unsigned char)(i * 71u);
        /* Shift by one too, putting the range exactly at the allocation end. */
        unsigned char *p = d + da + 1u, *q = s + sa + 1u;
        int bad = felucca_memcpy(p, q, n) != p;
        for (i = 0; i < n; i++) bad |= p[i] != q[i];
        for (i = 0; i <= da; i++) bad |= d[i] != 0xa5;
        bad |= felucca_memset(p, -17, n) != p;
        for (i = 0; i < n; i++) bad |= p[i] != (unsigned char)-17;
        for (i = 0; i <= da; i++) bad |= d[i] != 0xa5;
        free(d);
        free(s);
        if (bad) return 1;
        cases += 2;
    }
    return 0;
}

static int typed_objects(void)
{
    struct object { double d; float f; int16_t p[101]; } src, dst;
    unsigned i;
    src.d = 1.25;
    src.f = -3.5f;
    for (i = 0; i < 101u; i++) src.p[i] = (int16_t)(i * 17u - 200u);
    dst.d = 0;
    dst.f = 0;
    for (i = 0; i < 101u; i++) dst.p[i] = 0;
    felucca_memcpy(&dst, &src, sizeof src);
    if (dst.d != src.d || dst.f != src.f) return 1;
    for (i = 0; i < 101u; i++) if (dst.p[i] != src.p[i]) return 1;
    felucca_memset(dst.p, 0xff, sizeof dst.p);
    for (i = 0; i < 101u; i++) if (dst.p[i] != -1) return 1;
    /* A short-aligned range exercises the byte fallback and its guards. */
    felucca_memcpy(dst.p + 1, src.p + 1, 99u * sizeof src.p[0]);
    if (dst.p[0] != -1 || dst.p[100] != -1) return 1;
    for (i = 1; i < 100u; i++) if (dst.p[i] != src.p[i]) return 1;
    cases += 3;
    return 0;
}

int main(void)
{
    static const unsigned large[] = {2047, 2048, 2049, 4095, 4096, 4097};
    static const int extra[] = {-257, -256, -1, 256, 0x1ab, INT_MIN, INT_MAX};
    unsigned n, da, sa, v, i;
    for (n = 0; n <= 1025u; n++) for (da = 0; da < 4u; da++) for (sa = 0; sa < 4u; sa++)
        if (copy_case(n, da, sa)) return 1;
    for (i = 0; i < sizeof large / sizeof large[0]; i++) for (da = 0; da < 4u; da++) for (sa = 0; sa < 4u; sa++)
        if (copy_case(large[i], da, sa)) return 1;
    for (n = 0; n <= 257u; n++) for (da = 0; da < 4u; da++) for (v = 0; v <= 255u; v++)
        if (fill_case(n, da, (int)v)) return 1;
    for (i = 0; i < sizeof large / sizeof large[0]; i++) for (da = 0; da < 4u; da++) for (v = 0; v <= 255u; v++)
        if (fill_case(large[i], da, (int)v)) return 1;
    for (n = 0; n <= 33u; n++) for (da = 0; da < 4u; da++) for (i = 0; i < sizeof extra / sizeof extra[0]; i++)
        if (fill_case(n, da, extra[i])) return 1;
    if (allocation_edges() || typed_objects()) return 1;
    printf("libc: %u copy/fill cases passed (sizes, alignments, guards, typed objects)\n", cases);
    return 0;
}
