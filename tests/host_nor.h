/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
#ifndef FELUCCA_TESTS_HOST_NOR_H
#define FELUCCA_TESTS_HOST_NOR_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Shared backup/FM6-bank NOR model. Harnesses own their reset and power-on
 * sequence; reads remain available after a cut so they can inspect/recover it.
 * progs counts completed bytes, erases counts erases not refused before work.
 * Cuts are zero-based and latch dead until the harness restores power. */
static uint8_t nor[0x100000];
static int erase_error;
static uint32_t erases, progs;
static long cut_bytes = -1, cut_erase = -1;
static int dead;

static int st_read(uint32_t off, void *dst, uint32_t n) { memcpy(dst, nor + off, n); return 0; }
static int st_erase(uint32_t off)
{
    if (erase_error || dead) return -8;
    erases++;
    if (cut_erase >= 0 && cut_erase-- == 0) {    /* cut during the erase: half of it done */
        memset(nor + off, 0xFF, 2048);
        dead = 1;
        return -8;
    }
    memset(nor + off, 0xFF, 4096);
    return 0;
}
static int st_prog(uint32_t off, const void *src, uint32_t n)
{
    const uint8_t *s = src;
    uint32_t i;
    if ((off & 0xFFu) + n > 256u) { printf("page wrap at %#x\n", off); exit(1); }
    for (i = 0; i < n; i++) {
        if (dead || (cut_bytes >= 0 && cut_bytes-- == 0)) { dead = 1; return -9; }
        nor[off + i] &= s[i];                    /* NOR: bits only go 1 -> 0 */
        progs++;
    }
    return 0;
}

#endif
