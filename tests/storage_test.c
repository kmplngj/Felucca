/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Host test of firmware/src/storage.c against a simulated NOR flash:
 * erase -> 0xFF, program can only clear bits, page writes must not wrap. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define __attribute__(x)   /* (the sources' .pool sections: no Mach-O section names) */

/* Preserve the original operation observers and non-sticky refusal policies.
 * The shared adapter owns physical bytes, page bounds and sticky power cuts. */
#define st_read host_nor_read
#define st_erase host_nor_erase
#define st_prog host_nor_prog
#include "host_nor.h"
#undef st_prog
#undef st_erase
#undef st_read
static int fail_after = -1;            /* torn-write injection: stop after N programs */
static int fail_bytes = -1;            /* non-sticky refusal after N programmed bytes */
static int write_protected;
static uint32_t io_calls;
static uint32_t read_calls, read_bytes, erase_calls, prog_calls;
static uint32_t read_fail_off = UINT32_MAX, read_fail_n, read_fail_after_program;

static int st_read(uint32_t off, void *dst, uint32_t n)
{
    io_calls++;
    read_calls++;
    read_bytes += n;
    if (off == read_fail_off && n == read_fail_n && prog_calls >= read_fail_after_program)
        return -8;
    return host_nor_read(off, dst, n);
}
static int st_erase(uint32_t off)
{
    io_calls++;
    erase_calls++;
    if (erase_error) return -8;
    if (write_protected) return 0;     /* an acknowledged no-op: mandatory readback must reject it */
    return host_nor_erase(off);
}
static int st_prog(uint32_t off, const void *src, uint32_t n)
{
    uint8_t protected_page[256];
    int rc, was_dead = dead;
    long saved_cut = cut_bytes;
    io_calls++;
    prog_calls++;
    if (fail_after == 0)
        return -9;
    if (fail_after > 0)
        fail_after--;
    if (write_protected) {
        /* Programming ones leaves the image intact while preserving the shared
         * page guard and this fixture's legacy byte-refusal behavior. */
        memset(protected_page, 0xFF, sizeof protected_page);
        src = protected_page;
    }
    if (fail_bytes < 0)
        return host_nor_prog(off, src, n);
    /* Adapt the old byte refusal without turning it into a latched power cut.
     * Its budget counts completed bytes and remains zero at the refusal. */
    cut_bytes = fail_bytes;
    rc = host_nor_prog(off, src, n);
    fail_bytes = dead && !was_dead ? 0 : (int)cut_bytes;
    cut_bytes = saved_cut;
    dead = was_dead;
    return rc;
}
#include "../firmware/src/storage.c"

static int check(const char *what, int ok)
{
    printf("%-46s %s\n", what, ok ? "ok" : "FAIL");
    return ok ? 0 : 1;
}

static uint32_t isr_hits;
static void isr_hook(const char *file, int line) { (void)file; (void)line; isr_hits++; }

static void nor_power_on(void)
{
    dead = erase_error = write_protected = 0;
    cut_bytes = cut_erase = -1;
    fail_after = fail_bytes = -1;
    erases = progs = 0;
}

static int outside_is(uint32_t base, const uint8_t *before)
{
    return !memcmp(nor, before, base) &&
           !memcmp(nor + base + ST_SECTOR, before + base + ST_SECTOR, sizeof nor - base - ST_SECTOR);
}

/* Derive retry erase work from the persisted image: a cut can leave the
 * destination entirely blank, so its next save skips erase even while dead. */
static int sector_blank(const uint8_t *image, uint32_t base)
{
    uint32_t i;
    for (i = 0; i < ST_SECTOR; i++)
        if (image[base + i] != 0xFFu) return 0;
    return 1;
}

/* All object maps, both destination copies and lengths on either side of a
 * page boundary. Reboot recovery uses the real loader, with its RAM scratch lost. */
static int transactions(void)
{
    static uint8_t before[sizeof nor], retry_before[sizeof nor];
    static const uint32_t lengths[] = {0, 1, 255, 256, 257, ST_PAYLOAD_MAX};
    uint8_t old[ST_PAYLOAD_MAX], next[ST_PAYLOAD_MAX], got[ST_PAYLOAD_MAX], torn[ST_SECTOR];
    uint32_t obj, to, l, i, cut, base, len, total, trials = 0;
    int bad = 0, seeded = 1, cuts_ok = 1, sticky_ok = 1, retry_ok = 1, half_ok = 1, refused_ok = 1;
    memset(old, 0xA6, sizeof old);
    memset(next, 0x59, sizeof next);
    for (obj = 0; obj < OBJ_COUNT; obj++)
        for (to = 0; to < 2u; to++)
            for (l = 0; l < sizeof lengths / sizeof lengths[0]; l++) {
                uint32_t points[12], count = 0, old_seq;
                int ok;
                st_hdr_t h;
                nor_power_on();
                memset(nor, 0x5A, sizeof nor);      /* every unrelated byte is a guard */
                len = lengths[l];
                total = len + sizeof(st_hdr_t);
                ok = 1;
                for (i = 0; i < 2u + to; i++)
                    ok &= st_save(obj, old, len) == 0;
                ok &= st_current(obj, &h) == (int)(1u - to);
                seeded &= ok;
                if (!ok) return check("all object/copy maps start with two valid copies", 0);
                old_seq = h.seq;
                base = st_sector(obj, to);
                memcpy(before, nor, sizeof nor);
#define CUT_POINT(n) do { \
    uint32_t p = (n), j; \
    for (j = 0; j < count && points[j] != p; j++) {} \
    if (p <= total && j == count) points[count++] = p; \
} while (0)
                CUT_POINT(0u); CUT_POINT(1u);
                CUT_POINT(255u); CUT_POINT(256u); CUT_POINT(257u);
                if (len) CUT_POINT(len - 1u);
                CUT_POINT(len); CUT_POINT(len + 1u);
                CUT_POINT(total - 1u); CUT_POINT(total);
#undef CUT_POINT
                for (i = 0; i < count; i++) {
                    int rc;
                    cut = points[i];
                    memcpy(nor, before, sizeof nor);
                    nor_power_on();
                    cut_bytes = (long)cut;
                    rc = st_save(obj, next, len);
                    memset(st_buf, 0xCC, sizeof st_buf);
                    ok = erases == 1u && progs == cut && outside_is(base, before);
                    if (cut < total) {
                        int committed = st_current(obj, &h) == (int)to;
                        uint32_t retry_base = st_sector(obj, committed ? 1u - to : to);
                        uint32_t retry_erases = (uint32_t)!sector_blank(nor, retry_base);
                        int dead_error = retry_erases ? -8 : -9;
                        /* A not-yet-clocked trailing 0xFF can already equal the
                         * erased byte: an error may still leave a complete commit.
                         * Only the exact old or complete new payload may load. */
                        cuts_ok &= ok && rc == -9 && dead && h.seq == old_seq + (uint32_t)committed &&
                                   st_load(obj, got, sizeof got) == (int)len &&
                                   !memcmp(got, committed ? next : old, len);
                        memcpy(torn, nor + base, sizeof torn);
                        cut_bytes = -1;            /* a cleared injector does not restore power */
                        sticky_ok &= st_save(obj, next, len) == dead_error && dead && erases == 1u && progs == cut &&
                                     !memcmp(torn, nor + base, sizeof torn) && outside_is(base, before);
                        memcpy(retry_before, nor, sizeof nor);
                        nor_power_on();
                        retry_ok &= st_save(obj, next, len) == 0 && erases == retry_erases && progs == total &&
                                    outside_is(retry_base, retry_before);
                    } else {
                        cuts_ok &= ok && rc == 0 && !dead;
                    }
                    memset(st_buf, 0xCC, sizeof st_buf);
                    retry_ok &= st_load(obj, got, sizeof got) == (int)len && !memcmp(got, next, len);
                    trials++;
                }
                memcpy(nor, before, sizeof nor);
                nor_power_on();
                cut_erase = 0;
                ok = st_save(obj, next, len) == -8 && dead && erases == 1u && !progs && outside_is(base, before);
                for (i = 0; i < ST_SECTOR / 2u; i++) ok &= nor[base + i] == 0xFFu;
                ok &= !memcmp(nor + base + ST_SECTOR / 2u, before + base + ST_SECTOR / 2u, ST_SECTOR / 2u);
                memset(st_buf, 0xCC, sizeof st_buf);
                ok &= st_load(obj, got, sizeof got) == (int)len && !memcmp(got, old, len);
                memcpy(torn, nor + base, sizeof torn);
                cut_erase = -1;
                {
                    uint32_t retry_erases = (uint32_t)!sector_blank(nor, base);
                    int dead_error = retry_erases ? -8 : -9;
                    ok &= st_save(obj, next, len) == dead_error && dead && erases == 1u && !progs &&
                          !memcmp(torn, nor + base, sizeof torn) && outside_is(base, before);
                    nor_power_on();
                    ok &= st_save(obj, next, len) == 0 && erases == retry_erases && progs == total &&
                          outside_is(base, before);
                }
                memset(st_buf, 0xCC, sizeof st_buf);
                half_ok &= ok && st_load(obj, got, sizeof got) == (int)len && !memcmp(got, next, len);

                memcpy(nor, before, sizeof nor);
                nor_power_on();
                erase_error = 1;
                ok = st_save(obj, next, len) == -8 && !dead && !erases && !progs && !memcmp(nor, before, sizeof nor);
                memset(st_buf, 0xCC, sizeof st_buf);
                ok &= st_load(obj, got, sizeof got) == (int)len && !memcmp(got, old, len);
                erase_error = 0;
                ok &= st_save(obj, next, len) == 0 && erases == 1u && progs == total && outside_is(base, before);
                memset(st_buf, 0xCC, sizeof st_buf);
                refused_ok &= ok && st_load(obj, got, sizeof got) == (int)len && !memcmp(got, next, len);
            }
    printf("shared NOR: %u byte boundaries, %u half/refused erases each, %u object/copy maps\n",
           trials, OBJ_COUNT * 2u * (unsigned)(sizeof lengths / sizeof lengths[0]), OBJ_COUNT * 2u);
    bad += check("all object/copy maps start with two valid copies", seeded);
    bad += check("shared byte cuts keep old data or complete commit, neighbors intact", cuts_ok);
    bad += check("shared byte cuts stay dead after injector clears", sticky_ok);
    bad += check("restored power retries complete data, neighbors intact", retry_ok);
    bad += check("half erases keep old copy, latch dead, then retry", half_ok);
    bad += check("refused erases change nothing, clear without reboot", refused_ok);
    nor_power_on();
    return bad;
}

/* Counts cover complete saves, including copy selection and mandatory readback. */
static void reset_counts(void)
{
    read_calls = read_bytes = erase_calls = prog_calls = 0;
}

/* a power cycle: RAM state (st_tried, st_buf) is gone, the flash stays */
static void reboot(void)
{
    st_tried = 0;
    memset(st_buf, 0, sizeof st_buf);
}

/* a fresh device: blank flash, nothing tried since boot */
static void fresh(void)
{
    memset(nor, 0xFF, sizeof nor);
    reboot();
}

static int blank_sector_tests(void)
{
    static uint8_t payload[ST_PAYLOAD_MAX], got[ST_PAYLOAD_MAX];
    uint32_t base = st_sector(OBJ_PROJECT0, 0), other = st_sector(OBJ_PROJECT0, 1), i, len;
    int bad = 0, ok = 1;
    for (i = 0; i < sizeof payload; i++) payload[i] = (uint8_t)(i * 7u + 3u);
    for (len = 0; len <= ST_PAYLOAD_MAX; len++) {
        fresh();
        reset_counts();
        ok &= st_save(OBJ_PROJECT0, payload, len) == 0 && erase_calls == 0u;      /* fresh: blank A skips */
        ok &= st_load(OBJ_PROJECT0, got, sizeof got) == (int)len && !memcmp(got, payload, len);
        ok &= st_save(OBJ_PROJECT0, payload, len) == 0 && erase_calls == 1u;      /* blank B, valid A: erases */
        ok &= st_save(OBJ_PROJECT0, payload, len) == 0 && erase_calls == 2u;      /* reused A */
        ok &= st_load(OBJ_PROJECT0, got, sizeof got) == (int)len && !memcmp(got, payload, len);
    }
    bad += check("all lengths: only a fresh copy skips, A/B reuse erases", ok);

    fresh();
    reset_counts();
    ok = st_save(OBJ_PROJECT0, payload, 600) == 0 && erase_calls == 0u && prog_calls == 4u;
    reboot();                                                   /* B blank, A valid: not fresh after a reboot */
    ok &= st_save(OBJ_PROJECT0, payload + 1, 600) == 0 && erase_calls == 1u;
    bad += check("fresh first use skips; a later boot's blank B erases", ok);

    ok = 1;
    for (i = 0; i < ST_SECTOR; i++) {
        fresh();
        nor[base + i] = 0;                        /* includes padding and unused tail, not just payload */
        reset_counts();
        ok &= st_save(OBJ_PROJECT0, payload, 1) == 0 && erase_calls == 1u;
        ok &= nor[base + ST_SECTOR - 1u] == 0xFFu;
    }
    bad += check("one dirty byte at every offset forces erase", ok);

    {   /* a commit record of any type in either copy: the pair has been used (the FM6 bank's, the voice bank's) */
        st_hdr_t h;
        ok = 1;
        for (i = 0; i < 2u; i++) {
            fresh();
            memset(&h, 0, sizeof h);
            h.magic = ST_MAGIC;
            h.type = (uint16_t)OBJ_FM6VB;
            h.hcrc = st_crc32(&h, sizeof h - 4u);
            memcpy(nor + st_sector(OBJ_AUTOSAVE, i), &h, sizeof h);   /* the other copy; the destination blank */
            reset_counts();
            ok &= st_save_to(OBJ_AUTOSAVE, payload, 600, (int)(1u - i)) == 0 && erase_calls == 1u;
        }
        bad += check("another type's commit record in the pair: erase", ok);
    }

    ok = 1;
    for (i = 0; i < ST_SECTOR; i += 256u) {
        fresh();
        reset_counts();
        read_fail_off = base + i;
        read_fail_n = 256u;
        read_fail_after_program = 0;
        ok &= st_save(OBJ_PROJECT0, payload, 1) == -8 && erase_calls == 0u && prog_calls == 0u;
        read_fail_off = UINT32_MAX;
        ok &= st_load(OBJ_PROJECT0, got, sizeof got) < 0;
        ok &= st_save(OBJ_PROJECT0, payload, 1) == 0 && erase_calls == 1u;   /* the retry: no scan, an erase */
    }
    bad += check("every scan read error refuses all writes; retry erases", ok);

    /* A blank header after an interrupted first write still has dirty payload bytes. */
    fresh();
    fail_after = 1;
    ok = st_save(OBJ_PROJECT0, payload, sizeof payload) == -9;
    fail_after = -1;
    reset_counts();
    ok &= st_save(OBJ_PROJECT0, payload, sizeof payload) == 0 && erase_calls == 1u;
    bad += check("retry erases an uncommitted payload", ok);

    {   /* #721: a first program cut before any byte changed (or one whose cells read 0xFF with too little
         * margin): the sector reads blank, but it saw a write attempt; the retry must erase */
        ok = 1;
        for (i = 0; i < 2u; i++) {
            fresh();
            fail_bytes = (int)i;
            ok &= st_save(OBJ_PROJECT0, payload, 600) == -9;
            fail_bytes = -1;
            if (!i)
                for (len = 0; len < ST_SECTOR; len++) ok &= nor[base + len] == 0xFFu;
            reset_counts();
            ok &= st_save(OBJ_PROJECT0, payload, 600) == 0 && erase_calls == 1u;
            ok &= st_load(OBJ_PROJECT0, got, sizeof got) == 600 && !memcmp(got, payload, 600);
        }
        bad += check("blank-looking copy after a failed first save: erase", ok);
    }

    {   /* #721: a half erase of B (old A valid) leaves B reading all 0xFF; the power latch then refuses
         * every write. The retry, in the same boot or after it, must erase B again, never trust it. */
        uint32_t boot;
        ok = 1;
        for (boot = 0; boot < 2u; boot++) {
            fresh();
            ok &= st_save(OBJ_PROJECT0, payload, 600) == 0;
            reboot();
            write_protected = 1;                            /* the latch: the erase "half" ran ... */
            erase_error = 1;
            memset(nor + other, 0xFF, ST_SECTOR);           /* ... and left B reading blank */
            reset_counts();
            ok &= st_save(OBJ_PROJECT0, payload + 1, 600) == -8 && erase_calls == 1u && prog_calls == 0u;
            write_protected = 0;
            erase_error = 0;
            ok &= st_load(OBJ_PROJECT0, got, sizeof got) == 600 && !memcmp(got, payload, 600);   /* old copy kept */
            if (boot)
                reboot();
            reset_counts();
            ok &= st_save(OBJ_PROJECT0, payload + 1, 600) == 0 && erase_calls == 1u;
            ok &= st_load(OBJ_PROJECT0, got, sizeof got) == 600 && !memcmp(got, payload + 1, 600);
        }
        bad += check("half erase keeps old copy, latch dead, retry erases", ok);
    }

    {   /* The previous copy survives a cut at every write boundary of the following (erasing) save. */
        uint8_t copies[2 * ST_SECTOR];
        fresh();
        ok = st_save(OBJ_PROJECT0, payload, 600) == 0;
        memcpy(copies, nor + base, sizeof copies);
        for (i = 0; i < 600u + sizeof(st_hdr_t); i++) {
            memcpy(nor + base, copies, sizeof copies);
            reboot();
            reset_counts();
            fail_bytes = (int)i;
            ok &= st_save(OBJ_PROJECT0, payload + 1, 600) == -9 && erase_calls == 1u;
            fail_bytes = -1;
            memset(st_buf, 0, sizeof st_buf);
            ok &= st_load(OBJ_PROJECT0, got, sizeof got) == 600 && !memcmp(got, payload, 600);
        }
        bad += check("every blank-B write cut keeps old data (B erased)", ok);
    }

    fresh();
    reset_counts();
    write_protected = 1;
    ok = st_save(OBJ_PROJECT0, payload, 600) == -7 && erase_calls == 0u;
    write_protected = 0;
    bad += check("blank write-protected flash never reports saved", ok);

    /* The scan's scratch is not st_buf: an explicit-copy save may source its bytes from st_buf. */
    fresh();
    memcpy(st_buf, payload, sizeof payload);
    reset_counts();
    ok = st_save_to(OBJ_UPFM6, st_buf, sizeof payload, 1) == 0 && erase_calls == 0u;
    ok &= st_load(OBJ_UPFM6, got, sizeof got) == (int)sizeof payload && !memcmp(got, payload, sizeof payload);
    /* migration: a bank copy in A, the patches into B: the pair was used, B is erased */
    fresh();
    ok &= st_save(OBJ_FM6BANK, payload, sizeof payload) == 0;
    reboot();
    reset_counts();
    ok &= st_load(OBJ_FM6BANK, got, sizeof got) == (int)sizeof payload;     /* the bank in st_buf, as upf_boot */
    ok &= st_save_to(OBJ_UPFM6, st_buf, sizeof payload, 1) == 0 && erase_calls == 1u;
    ok &= st_load(OBJ_UPFM6, got, sizeof got) == (int)sizeof payload && !memcmp(got, payload, sizeof payload);
    ok &= st_load(OBJ_FM6BANK, got, sizeof got) == (int)sizeof payload && !memcmp(got, payload, sizeof payload);
    bad += check("explicit-copy saves preserve their st_buf source", ok);

    /* Readback must still report a failure even if the blank scan and programs succeeded. */
    ok = 1;
    for (i = 0; i < 2u; i++) {
        fresh();
        reset_counts();
        read_fail_off = base + (i ? ST_PAYLOAD_OFF : 0u);
        read_fail_n = i ? 1u : sizeof(st_hdr_t);
        read_fail_after_program = 2u;
        ok &= st_save(OBJ_PROJECT0, payload, 1) == -7 && erase_calls == 0u && prog_calls == 2u;
        read_fail_off = UINT32_MAX;
    }
    bad += check("blank saves retain header/payload readback", ok);

    fresh();
    reset_counts();
    ok = st_save(OBJ_PROJECT0, payload, 600) == 0;
    printf("fresh A 600-byte save: reads=%u bytes=%u erases=%u programs=%u\n", read_calls, read_bytes, erase_calls, prog_calls);
    ok &= read_calls == 22u && read_bytes == 4856u && erase_calls == 0u && prog_calls == 4u;
    reset_counts();
    ok &= st_save(OBJ_PROJECT0, payload, 600) == 0;
    printf("blank B 600-byte save: reads=%u bytes=%u erases=%u programs=%u\n", read_calls, read_bytes, erase_calls, prog_calls);
    ok &= read_calls == 5u && read_bytes == 1296u && erase_calls == 1u && prog_calls == 4u;
    reset_counts();
    ok &= st_save(OBJ_PROJECT0, payload, 600) == 0;
    printf("reused A 600-byte save: reads=%u bytes=%u erases=%u programs=%u\n", read_calls, read_bytes, erase_calls, prog_calls);
    ok &= read_calls == 5u && read_bytes == 1296u && erase_calls == 1u && prog_calls == 4u;
    reboot();
    reset_counts();
    ok &= st_save(OBJ_PROJECT0, payload, 600) == 0;
    printf("after a reboot 600-byte save: reads=%u bytes=%u erases=%u programs=%u\n", read_calls, read_bytes, erase_calls, prog_calls);
    ok &= read_calls == 6u && read_bytes == 1328u && erase_calls == 1u && prog_calls == 4u;
    bad += check("complete save I/O cost", ok);
    return bad;
}

int main(void)
{
    char a[600], b[600], got[600];
    int bad = 0, n;
    memset(nor, 0xFF, sizeof nor);
    memset(a, 'A', sizeof a);
    memset(b, 'B', sizeof b);
    bad += check("empty flash loads nothing", st_load(OBJ_PROJECT0, got, sizeof got) < 0);
    bad += check("save A", st_save(OBJ_PROJECT0, a, sizeof a) == 0);
    n = st_load(OBJ_PROJECT0, got, sizeof got);
    bad += check("load returns A", n == (int)sizeof a && !memcmp(got, a, sizeof a));
    bad += check("save B", st_save(OBJ_PROJECT0, b, sizeof b) == 0);
    n = st_load(OBJ_PROJECT0, got, sizeof got);
    bad += check("load returns B (newer seq)", n == (int)sizeof b && !memcmp(got, b, sizeof b));
    fail_after = 1;                                  /* payload page 1 written, the rest torn */
    st_save(OBJ_PROJECT0, a, sizeof a);
    fail_after = -1;
    n = st_load(OBJ_PROJECT0, got, sizeof got);
    bad += check("torn save keeps B", n == (int)sizeof b && !memcmp(got, b, sizeof b));
    fail_after = 3;                                  /* all payload pages, header torn */
    st_save(OBJ_PROJECT0, a, sizeof a);
    fail_after = -1;
    n = st_load(OBJ_PROJECT0, got, sizeof got);
    bad += check("header not written keeps B", n == (int)sizeof b && !memcmp(got, b, sizeof b));
    bad += check("save A again", st_save(OBJ_PROJECT0, a, sizeof a) == 0);
    n = st_load(OBJ_PROJECT0, got, sizeof got);
    bad += check("load returns A", n == (int)sizeof a && !memcmp(got, a, sizeof a));
    nor[st_sector(OBJ_PROJECT0, 0) + ST_PAYLOAD_OFF + 10] ^= 0x01;   /* bit rot in one copy */
    nor[st_sector(OBJ_PROJECT0, 1) + ST_PAYLOAD_OFF + 10] ^= 0x01;
    n = st_load(OBJ_PROJECT0, got, sizeof got);
    bad += check("both copies corrupt -> nothing", n < 0);
    bad += check("other objects untouched", st_load(OBJ_PROJECT0 + 1, got, sizeof got) < 0);
    bad += check("settings save/load",
                 st_save(OBJ_SETTINGS, "hello", 5) == 0 && st_load(OBJ_SETTINGS, got, 5) == 5 && !memcmp(got, "hello", 5));
    bad += check("CRC-32 is zlib's (check value 0xCBF43926)", st_crc32("123456789", 9) == 0xCBF43926u);
    memset(nor, 0xFF, sizeof nor);
    st_save(OBJ_PROJECT0 + 2, a, sizeof a);
    st_save(OBJ_PROJECT0 + 2, b, sizeof b);              /* B is newer, in the other copy */
    {
        st_hdr_t h;
        int cur = st_current(OBJ_PROJECT0 + 2, &h);
        nor[st_sector(OBJ_PROJECT0 + 2, (uint32_t)cur) + ST_PAYLOAD_OFF + 300] ^= 0x10;   /* rot in the newer copy */
    }
    n = st_load(OBJ_PROJECT0 + 2, got, sizeof got);
    bad += check("newer copy rotten -> the older one loads", n == (int)sizeof a && !memcmp(got, a, sizeof a));
    bad += check("save over the rotten copy", st_save(OBJ_PROJECT0 + 2, b, sizeof b) == 0);
    n = st_load(OBJ_PROJECT0 + 2, got, sizeof got);
    bad += check("... loads the new data", n == (int)sizeof b && !memcmp(got, b, sizeof b));
    nor[st_sector(OBJ_PROJECT0 + 2, 0) + 8] ^= 0x01;    /* both headers broken */
    nor[st_sector(OBJ_PROJECT0 + 2, 1) + 8] ^= 0x01;
    bad += check("both headers broken -> nothing", st_load(OBJ_PROJECT0 + 2, got, sizeof got) < 0);
    bad += check("data stays in the Felucca regions",
                 st_sector(OBJ_SETTINGS, 1) + 4096 <= 0xFF000 && st_sector(OBJ_PROJECT0 + 3, 1) + 4096 <= 0xE0000 &&
                     st_sector(OBJ_UPRESET0, 0) >= 0xDC000 && st_sector(OBJ_UPRESET0 + 1, 1) + 4096 <= 0xE0000);
    /* the user presets' FM6 patches (1.0.3) in the two sectors of the retired FM6 bank: 0x9F000 (after the projects)
     * and 0xFE000 (after the settings); the two objects share them, told apart by the commit record's type */
    bad += check("FM6 user preset patches (and the retired bank) in the sectors 0x9F000 / 0xFE000",
                 OBJ_UPFM6 == OBJ_COUNT - 2 && OBJ_FM6BANK == OBJ_UPFM6 - 1 && st_sector(OBJ_UPFM6, 0) == 0x9F000u &&
                     st_sector(OBJ_PROJECT0 + 3, 1) + 4096 == 0x9F000u && st_sector(OBJ_UPFM6, 1) == 0xFE000u &&
                     st_sector(OBJ_FM6BANK, 0) == 0x9F000u && st_sector(OBJ_FM6BANK, 1) == 0xFE000u &&
                     st_sector(OBJ_SETTINGS, 1) + 4096 == 0xFE000u);
    /* the autosave (1.2, project.c): its own pair 0xE5000 / 0xE6000, above the OTA staging, apart from every other
     * object; a save there touches no other object */
    {
        uint32_t o, c, ok = OBJ_AUTOSAVE == OBJ_COUNT - 1 && st_sector(OBJ_AUTOSAVE, 0) == 0xE5000u &&
                               st_sector(OBJ_AUTOSAVE, 1) == 0xE6000u;
        static uint8_t snap[0x100000];
        for (o = 0; o < OBJ_AUTOSAVE; o++)
            for (c = 0; c < 2u; c++)
                ok &= st_sector(o, c) + 4096u <= 0xE5000u || st_sector(o, c) >= 0xE7000u;
        memcpy(snap, nor, sizeof nor);
        ok &= st_save(OBJ_AUTOSAVE, a, sizeof a) == 0 && st_load(OBJ_AUTOSAVE, got, sizeof got) == (int)sizeof a &&
              !memcmp(got, a, sizeof a) && !memcmp(snap, nor, 0xE5000u) && !memcmp(snap + 0xE7000u, nor + 0xE7000u, 0x19000u);
        bad += check("the autosave in its own sectors 0xE5000 / 0xE6000, nothing else touched", ok);
    }
    {
        static uint8_t bank[3472], back[3728], tab[3728];
        uint32_t i;
        memset(nor, 0xFF, sizeof nor);
        for (i = 0; i < sizeof bank; i++) bank[i] = (uint8_t)(i * 7u);
        for (i = 0; i < sizeof tab; i++) tab[i] = (uint8_t)(i * 3u);
        st_save(OBJ_FM6BANK, bank, sizeof bank);         /* A (seq 1) */
        bank[0] ^= 1;
        st_save(OBJ_FM6BANK, bank, sizeof bank);         /* B (seq 2): the newest */
        bad += check("a bank copy does not read as the patches object (its type)", st_load(OBJ_UPFM6, back, sizeof back) < 0);
        bad += check("st_save_to: the first patches write into A, the bank's older copy; the bank's B still loads",
                     st_save_to(OBJ_UPFM6, tab, sizeof tab, 0) == 0 &&
                     st_load(OBJ_UPFM6, back, sizeof back) == (int)sizeof tab && !memcmp(back, tab, sizeof tab) &&
                     st_load(OBJ_FM6BANK, back, sizeof back) == (int)sizeof bank && !memcmp(back, bank, sizeof bank));
        tab[0] ^= 1;
        bad += check("the next save goes to B (over the bank), A/B as any object",
                     st_save(OBJ_UPFM6, tab, sizeof tab) == 0 && st_load(OBJ_FM6BANK, back, sizeof back) < 0 &&
                     st_load(OBJ_UPFM6, back, sizeof back) == (int)sizeof tab && back[0] == tab[0]);
        {
            int erased = 1;
            for (i = 256u + sizeof tab; i < 4096u; i++) erased &= nor[0x9F000u + i] == 0xFFu && nor[0xFE000u + i] == 0xFFu;
            bad += check("FM6 patches: the sector tails stay erased", erased);
        }
    }
    {
        uint8_t copies[2 * ST_SECTOR];
        uint32_t off = st_sector(OBJ_PROJECT0, 0), cut;
        int ok = 1;
        memset(nor, 0xFF, sizeof nor);
        st_save(OBJ_PROJECT0, a, sizeof a);
        st_save(OBJ_PROJECT0, b, sizeof b);
        memcpy(copies, nor + off, sizeof copies);
        for (cut = 0; cut < sizeof a + sizeof(st_hdr_t); cut++) {
            memcpy(nor + off, copies, sizeof copies);
            fail_bytes = (int)cut;
            ok &= st_save(OBJ_PROJECT0, a, sizeof a) != 0;
            fail_bytes = -1;
            ok &= st_load(OBJ_PROJECT0, got, sizeof got) == (int)sizeof b && !memcmp(got, b, sizeof b);
        }
        bad += check("every payload/header byte cut keeps old data", ok);
        erase_error = 1;
        ok = st_save(OBJ_PROJECT0, a, sizeof a) != 0;
        erase_error = 0;
        bad += check("erase failure keeps old data", ok && st_load(OBJ_PROJECT0, got, sizeof got) == (int)sizeof b &&
                                                      !memcmp(got, b, sizeof b));
        write_protected = 1;
        ok = st_save(OBJ_PROJECT0, a, sizeof a) != 0;
        write_protected = 0;
        bad += check("write protection is a save error", ok && st_load(OBJ_PROJECT0, got, sizeof got) == (int)sizeof b &&
                                                            !memcmp(got, b, sizeof b));
    }
    {
        st_hdr_t h;
        uint32_t copy;
        for (copy = 0; copy < 2u; copy++) {
            uint32_t off = st_sector(OBJ_PROJECT0, copy);
            memcpy(&h, nor + off, sizeof h);
            h.seq = 0xFFFFFFFEu + copy;
            h.hcrc = st_crc32(&h, sizeof h - 4u);
            memcpy(nor + off, &h, sizeof h);
        }
        bad += check("save sequence wraps", st_save(OBJ_PROJECT0, a, sizeof a) == 0);
        n = st_load(OBJ_PROJECT0, got, sizeof got);
        bad += check("wrapped sequence loads new data", n == (int)sizeof a && !memcmp(got, a, sizeof a));
        bad += check("save after sequence wrap", st_save(OBJ_PROJECT0, b, sizeof b) == 0 &&
                                                st_load(OBJ_PROJECT0, got, sizeof got) == (int)sizeof b &&
                                                !memcmp(got, b, sizeof b));
    }
    {
        uint32_t calls = io_calls;
        bad += check("invalid object load does no flash access", st_load(OBJ_COUNT, got, sizeof got) < 0 && io_calls == calls);
        bad += check("invalid object save does no flash access", st_save(OBJ_COUNT, a, sizeof a) < 0 && io_calls == calls);
        bad += check("wrapped object rejected", st_save(0xFFFFFFFFu, a, sizeof a) < 0 && io_calls == calls);
        memset(got, 'X', sizeof got);
        bad += check("small destination rejects whole object", st_load(OBJ_PROJECT0, got, sizeof got - 1u) < 0 && got[0] == 'X');
        bad += check("oversized save rejected", st_save(OBJ_PROJECT0, a, ST_PAYLOAD_MAX + 1u) < 0);
    }
    {   /* #428: a save from simulated interrupt context trips FM1_ASSERT_THREAD; from the main loop it does not */
        fm1_isr_assert_hook = isr_hook;
        bad += check("save in the main loop: no ISR assertion", st_save(OBJ_PROJECT0, a, sizeof a) == 0 && isr_hits == 0);
        FM1_ISR_SIM_ENTER();
        st_save(OBJ_PROJECT0, a, sizeof a);
        FM1_ISR_SIM_LEAVE();
        bad += check("save in simulated ISR context: assertion fires", isr_hits == 1u);
        bad += check("save after the ISR returns: quiet again", st_save(OBJ_PROJECT0, a, sizeof a) == 0 && isr_hits == 1u);
        fm1_isr_assert_hook = 0;
    }
    bad += blank_sector_tests();
    bad += transactions();
    printf("%s\n", bad ? "STORAGE TEST FAILED" : "storage test passed");
    return bad != 0;
}
