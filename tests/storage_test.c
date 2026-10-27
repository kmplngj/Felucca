/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Host test of firmware/src/storage.c against a simulated NOR flash:
 * erase -> 0xFF, program can only clear bits, page writes must not wrap. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define __attribute__(x)   /* (the sources' .pool sections: no Mach-O section names) */

/* Preserve the original operation observer and non-sticky refusal policies.
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

static int st_read(uint32_t off, void *dst, uint32_t n)
{
    io_calls++;
    return host_nor_read(off, dst, n);
}
static int st_erase(uint32_t off)
{
    io_calls++;
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
                        /* A not-yet-clocked trailing 0xFF can already equal the
                         * erased byte: an error may still leave a complete commit.
                         * Only the exact old or complete new payload may load. */
                        cuts_ok &= ok && rc == -9 && dead && h.seq == old_seq + (uint32_t)committed &&
                                   st_load(obj, got, sizeof got) == (int)len &&
                                   !memcmp(got, committed ? next : old, len);
                        memcpy(torn, nor + base, sizeof torn);
                        cut_bytes = -1;            /* a cleared injector does not restore power */
                        sticky_ok &= st_save(obj, next, len) == -8 && dead && erases == 1u && progs == cut &&
                                     !memcmp(torn, nor + base, sizeof torn) && outside_is(base, before);
                        memcpy(retry_before, nor, sizeof nor);
                        nor_power_on();
                        retry_ok &= st_save(obj, next, len) == 0 && erases == 1u && progs == total &&
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
                ok &= st_save(obj, next, len) == -8 && dead && erases == 1u && !progs &&
                      !memcmp(torn, nor + base, sizeof torn) && outside_is(base, before);
                nor_power_on();
                ok &= st_save(obj, next, len) == 0 && erases == 1u && progs == total && outside_is(base, before);
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
    bad += transactions();
    printf("%s\n", bad ? "STORAGE TEST FAILED" : "storage test passed");
    return bad != 0;
}
