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
 * Cuts are zero-based and latch dead until the harness restores power.
 * Test bugs abort with a message (exit 1) instead of overrunning host memory:
 * an erase must be 4096-aligned and inside the array, a program must stay in
 * one 256-byte page and inside the array. host_nor_set_bits counts program
 * calls that ask for a 0 -> 1 bit change (silently ignored, as on real flash,
 * so it is only counted, never fatal): a test that programs onto erased flash
 * can assert it stays 0. */
static uint8_t nor[0x100000];
static int erase_error;
static uint32_t erases, progs;
static long cut_bytes = -1, cut_erase = -1;
static int dead;
static uint32_t host_nor_set_bits;

static int st_read(uint32_t off, void *dst, uint32_t n) { memcpy(dst, nor + off, n); return 0; }
static int st_erase(uint32_t off)
{
    if ((off & 4095u) || off > sizeof nor - 4096u) { printf("erase outside the array or unaligned at %#x\n", off); exit(1); }
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
    int set_bits = 0;
    if (off > sizeof nor || n > sizeof nor - off) { printf("program outside the array at %#x len %u\n", off, n); exit(1); }
    if ((off & 0xFFu) + n > 256u) { printf("page wrap at %#x\n", off); exit(1); }
    for (i = 0; i < n; i++) {
        if (dead || (cut_bytes >= 0 && cut_bytes-- == 0)) { dead = 1; return -9; }
        if ((s[i] & ~nor[off + i] & 0xFFu) && !set_bits) { set_bits = 1; host_nor_set_bits++; }
        nor[off + i] &= s[i];                    /* NOR: bits only go 1 -> 0 */
        progs++;
    }
    return 0;
}

#endif
