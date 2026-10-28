/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Host test of firmware/src/storage.c against a simulated NOR flash:
 * erase -> 0xFF, program can only clear bits, page writes must not wrap. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define __attribute__(x)   /* (the sources' .pool sections: no Mach-O section names) */

static uint8_t nor[0x100000];
static int fail_after = -1;            /* torn-write injection: stop after N programs */
static int fail_bytes = -1;            /* power loss after any programmed byte */
static int erase_error, write_protected;
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
    memcpy(dst, nor + off, n);
    return 0;
}
static int st_erase(uint32_t off)
{
    io_calls++;
    erase_calls++;
    if (erase_error) return -8;
    if (!write_protected) memset(nor + off, 0xFF, 4096);
    return 0;
}
static int st_prog(uint32_t off, const void *src, uint32_t n)
{
    const uint8_t *s = src;
    uint32_t i;
    io_calls++;
    prog_calls++;
    if (fail_after == 0)
        return -9;
    if (fail_after > 0)
        fail_after--;
    if ((off & 0xFFu) + n > 256u) {
        printf("page wrap at %#x\n", off);
        exit(1);
    }
    for (i = 0; i < n; i++) {
        if (fail_bytes == 0) return -9;
        if (fail_bytes > 0) fail_bytes--;
        if (!write_protected) nor[off + i] &= s[i];
    }
    return 0;
}
#include "../firmware/src/storage.c"

static int check(const char *what, int ok)
{
    printf("%-46s %s\n", what, ok ? "ok" : "FAIL");
    return ok ? 0 : 1;
}

static uint32_t isr_hits;
static void isr_hook(const char *file, int line) { (void)file; (void)line; isr_hits++; }

/* Counts cover complete saves, including copy selection and mandatory readback. */
static void reset_counts(void)
{
    read_calls = read_bytes = erase_calls = prog_calls = 0;
}

static int blank_sector_tests(void)
{
    static uint8_t payload[ST_PAYLOAD_MAX], got[ST_PAYLOAD_MAX];
    uint32_t base = st_sector(OBJ_PROJECT0, 0), other = st_sector(OBJ_PROJECT0, 1), i, len;
    int bad = 0, ok = 1;
    for (i = 0; i < sizeof payload; i++) payload[i] = (uint8_t)(i * 7u + 3u);
    for (len = 0; len <= ST_PAYLOAD_MAX; len++) {
        memset(nor, 0xFF, sizeof nor);
        reset_counts();
        ok &= st_save(OBJ_PROJECT0, payload, len) == 0 && erase_calls == 0u;
        ok &= st_load(OBJ_PROJECT0, got, sizeof got) == (int)len && !memcmp(got, payload, len);
        ok &= st_save(OBJ_PROJECT0, payload, len) == 0 && erase_calls == 0u; /* blank B */
        ok &= st_save(OBJ_PROJECT0, payload, len) == 0 && erase_calls == 1u; /* reused A */
        ok &= st_load(OBJ_PROJECT0, got, sizeof got) == (int)len && !memcmp(got, payload, len);
    }
    bad += check("all lengths: blank A/B skip, reused A erases", ok);

    ok = 1;
    for (i = 0; i < ST_SECTOR; i++) {
        memset(nor, 0xFF, sizeof nor);
        nor[base + i] = 0;                        /* includes padding and unused tail, not just payload */
        reset_counts();
        ok &= st_save(OBJ_PROJECT0, payload, 1) == 0 && erase_calls == 1u;
        ok &= nor[base + ST_SECTOR - 1u] == 0xFFu;
    }
    bad += check("one dirty byte at every offset forces erase", ok);

    ok = 1;
    for (i = 0; i < ST_SECTOR; i += 256u) {
        memset(nor, 0xFF, sizeof nor);
        ok &= st_save(OBJ_PROJECT0, payload, sizeof payload) == 0;
        reset_counts();
        read_fail_off = other + i;
        read_fail_n = 256u;
        read_fail_after_program = 0;
        ok &= st_save(OBJ_PROJECT0, payload, 1) == -8 && erase_calls == 0u && prog_calls == 0u;
        read_fail_off = UINT32_MAX;
        memset(st_buf, 0, sizeof st_buf);          /* no RAM payload survives a reboot */
        ok &= st_load(OBJ_PROJECT0, got, sizeof got) == (int)sizeof payload && !memcmp(got, payload, sizeof payload);
    }
    bad += check("every scan read error refuses all writes", ok);

    /* A blank header after an interrupted first write still has dirty payload bytes. */
    memset(nor, 0xFF, sizeof nor);
    fail_after = 1;
    ok = st_save(OBJ_PROJECT0, payload, sizeof payload) == -9;
    fail_after = -1;
    reset_counts();
    ok &= st_save(OBJ_PROJECT0, payload, sizeof payload) == 0 && erase_calls == 1u;
    bad += check("retry erases an uncommitted payload", ok);

    {   /* The new no-erase path must retain the previous copy at every write boundary too. */
        uint8_t copies[2 * ST_SECTOR];
        memset(nor, 0xFF, sizeof nor);
        ok = st_save(OBJ_PROJECT0, payload, 600) == 0;
        memcpy(copies, nor + base, sizeof copies);
        for (i = 0; i < 600u + sizeof(st_hdr_t); i++) {
            memcpy(nor + base, copies, sizeof copies);
            reset_counts();
            fail_bytes = (int)i;
            ok &= st_save(OBJ_PROJECT0, payload + 1, 600) == -9 && erase_calls == 0u;
            fail_bytes = -1;
            memset(st_buf, 0, sizeof st_buf);
            ok &= st_load(OBJ_PROJECT0, got, sizeof got) == 600 && !memcmp(got, payload, 600);
        }
        bad += check("every blank-target write cut keeps old data", ok);
    }

    memset(nor, 0xFF, sizeof nor);
    reset_counts();
    write_protected = 1;
    ok = st_save(OBJ_PROJECT0, payload, 600) == -7 && erase_calls == 0u;
    write_protected = 0;
    bad += check("blank write-protected flash never reports saved", ok);

    /* Explicit-copy migration may source the retired object's bytes from shared scratch. */
    memset(nor, 0xFF, sizeof nor);
    ok = st_save(OBJ_FM6BANK, payload, sizeof payload) == 0;
    reset_counts();
    ok &= st_save_to(OBJ_UPFM6, st_buf, sizeof payload, 1) == 0 && erase_calls == 0u;
    ok &= st_load(OBJ_UPFM6, got, sizeof got) == (int)sizeof payload && !memcmp(got, payload, sizeof payload);
    ok &= st_load(OBJ_FM6BANK, got, sizeof got) == (int)sizeof payload && !memcmp(got, payload, sizeof payload);
    bad += check("blank explicit-copy save preserves st_buf source", ok);

    /* Readback must still report a failure even if the blank scan and programs succeeded. */
    ok = 1;
    for (i = 0; i < 2u; i++) {
        memset(nor, 0xFF, sizeof nor);
        reset_counts();
        read_fail_off = base + (i ? ST_PAYLOAD_OFF : 0u);
        read_fail_n = i ? 1u : sizeof(st_hdr_t);
        read_fail_after_program = 2u;
        ok &= st_save(OBJ_PROJECT0, payload, 1) == -7 && erase_calls == 0u && prog_calls == 2u;
        read_fail_off = UINT32_MAX;
    }
    bad += check("blank saves retain header/payload readback", ok);

    memset(nor, 0xFF, sizeof nor);
    reset_counts();
    ok = st_save(OBJ_PROJECT0, payload, 600) == 0;
    printf("blank 600-byte save: reads=%u bytes=%u erases=%u programs=%u\n", read_calls, read_bytes, erase_calls, prog_calls);
    ok &= read_calls == 20u && read_bytes == 4792u && erase_calls == 0u && prog_calls == 4u;
    reset_counts();
    ok &= st_save(OBJ_PROJECT0, payload, 600) == 0;
    printf("blank B 600-byte save: reads=%u bytes=%u erases=%u programs=%u\n", read_calls, read_bytes, erase_calls, prog_calls);
    ok &= read_calls == 21u && read_bytes == 5392u && erase_calls == 0u && prog_calls == 4u;
    reset_counts();
    ok &= st_save(OBJ_PROJECT0, payload, 600) == 0;
    printf("reused A 600-byte save: reads=%u bytes=%u erases=%u programs=%u\n", read_calls, read_bytes, erase_calls, prog_calls);
    ok &= read_calls == 6u && read_bytes == 1552u && erase_calls == 1u && prog_calls == 4u;
    bad += check("complete save I/O cost and early dirty exit", ok);
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
    printf("%s\n", bad ? "STORAGE TEST FAILED" : "storage test passed");
    return bad != 0;
}
