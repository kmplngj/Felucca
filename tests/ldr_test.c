/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Host test of the Felucca update loader (firmware/loader/ldr_core.c): a fake
 * host serves a package over the SysEx protocol, the "device" flash starts as
 * another package's flash.bin (as if that firmware were installed).
 *   ldr_test OLD.fwsc NEW.fwsc */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "update_record_fixture.h"
#define __attribute__(x)   /* (the sources' .pool sections: no Mach-O section names) */

#define FELUCCA_ID "ota-FM-1_900"
#define FELUCCA_OTA_DRYRUN 0

static uint8_t nor[0x100000], *logical;
static size_t logical_len;
static uint8_t rx[1024];
static uint32_t rx_len, rx_full, now_ms, requests, erases, bad_range, record_cleared, f0_asked;
static uint32_t erase_n[0x100], prot_reads, rd_fail_off = 0xFFFFFFFFu, er_fail_off = 0xFFFFFFFFu;   /* per 4K sector; fault injection */
static uint32_t flip_addr = 0xFFFFFFFFu, flip_seen, flip_on;   /* serve addr's flip_on-th reply with a byte changed */

static uint32_t pack7(const uint8_t *in, uint32_t n, uint8_t *out)
{
    uint32_t acc = 0, nb = 0, o = 0;
    while (n--) {
        acc |= (uint32_t)*in++ << nb;
        nb += 8;
        while (nb >= 7) { out[o++] = acc & 0x7F; acc >>= 7; nb -= 7; }
    }
    if (nb) out[o++] = acc & 0x7F;
    return o;
}
static uint32_t unpack7h(const uint8_t *in, uint32_t n, uint8_t *out)
{
    uint32_t acc = 0, nb = 0, o = 0;
    while (n--) {
        acc |= (uint32_t)*in++ << nb;
        nb += 7;
        if (nb >= 8) { out[o++] = (uint8_t)acc; acc >>= 8; nb -= 8; }
    }
    return o;
}

static int ota_wire_send(const uint8_t *p, uint32_t n)
{
    uint8_t u[64], m[600];
    uint32_t addr, len, i, s = 0;
    unpack7h(p + 1, n - 2, u);
    if (u[2] == 0x11) return 0;
    addr = u[7] | u[8] << 8 | u[9] << 16 | (uint32_t)u[10] << 24;
    len = u[11] | u[12] << 8 | u[13] << 16;
    requests++;
    memcpy(m, "\x00\x59\x30", 3);
    m[3] = (uint8_t)(len + 8); m[4] = (uint8_t)((len + 8) >> 8); m[5] = 0; m[6] = 0;
    memcpy(m + 7, &addr, 4);
    m[11] = (uint8_t)len; m[12] = (uint8_t)(len >> 8); m[13] = 0;
    if (addr >= 0xE0000000u) {
        f0_asked += addr == 0xF0000000u;
        memset(m + 14, 0, len);
        memcpy(m + 14, "success", 8);
    } else {
        if (addr + len > logical_len) { printf("read past the package %#x\n", addr); exit(1); }
        memcpy(m + 14, logical + addr, len);
        if (addr == flip_addr && ++flip_seen == flip_on)
            m[14 + len / 2u] ^= 0x10;                /* a transfer error the frame checksum does not see */
    }
    for (i = 6; i < 14 + len; i++) s += m[i];
    m[14 + len] = (uint8_t)~s;
    rx_len = pack7(m, 15 + len, rx);
    rx_full = 1;
    return 0;
}
static int ota_frame_get(const uint8_t **p, uint32_t *n) { if (!rx_full) return 0; *p = rx; *n = rx_len; return 1; }
static void ota_frame_done(void) { rx_full = 0; }
static uint32_t ota_now_ms(void) { return now_ms; }
static void ota_idle(void) { now_ms++; }
static int ota_erase(uint32_t off) { (void)off; return -1; }
static int ota_prog(uint32_t off, const void *p, uint32_t n) { (void)off; (void)p; (void)n; return -1; }
static int ota_fread(uint32_t off, void *p, uint32_t n) { memcpy(p, nor + off, n); return 0; }
static void ota_show(uint32_t step, int32_t code) { (void)step; (void)code; }
static void ota_commit(const uint8_t *parm) { (void)parm; }
#include "../firmware/src/ota.c"

/* Felucca's autosave pair and FM6 voice bank (storage.c, fm6_vbank.c): the loader must neither erase nor read them */
#define PROT_LO 0xE5000u
#define PROT_HI 0xE8000u
static int ldr_fread(uint32_t off, void *p, uint32_t n)
{
    if (off < PROT_HI && off + n > PROT_LO) prot_reads++;
    if (rd_fail_off >= off && rd_fail_off < off + n) return -1;
    memcpy(p, nor + off, n);
    return 0;
}
static int ldr_erase(uint32_t off)
{
    if (off < 0x4000u || off >= 0xFC000u || (off & 0xFFFu) || (off >= 0x97000u && off < 0xE0000u) ||
        (off >= PROT_LO && off < PROT_HI)) bad_range++;
    if (off < 0x4000u) { printf("ERASE IN THE HEAD %#x\n", off); exit(1); }
    erase_n[(off >> 12) & 0xFFu]++;
    if (off == er_fail_off) return -1;               /* a failing erase leaves the sector as it was */
    erases++;
    memset(nor + off, 0xFF, 0x1000);
    return 0;
}
static int ldr_prog(uint32_t off, const void *p, uint32_t n)
{
    const uint8_t *s = p;
    uint32_t i;
    if (off < 0x4000u || off + n > 0x93000u || ((off & 0xFFu) + n) > 256u) bad_range++;
    for (i = 0; i < n; i++) nor[off + i] &= s[i];
    return 0;
}
static void ldr_record_clear(void) { record_cleared++; }
static void ldr_progress(uint32_t done, uint32_t total) { (void)done; (void)total; }
#include "../firmware/loader/ldr_core.c"

/* the production storage objects (storage.c) on the same simulated flash: st_save writes the real layout (commit
 * record at sector + 0, payload at sector + 0x100). Its erases are not the loader's: erase_n counts only ldr_erase. */
static int st_read(uint32_t off, void *dst, uint32_t n) { memcpy(dst, nor + off, n); return 0; }
static int st_erase(uint32_t off) { memset(nor + off, 0xFF, 0x1000); return 0; }
static int st_prog(uint32_t off, const void *src, uint32_t n)
{
    const uint8_t *s = src;
    uint32_t i;
    if ((off & 0xFFu) + n > 256u) { printf("page wrap at %#x\n", off); exit(1); }
    for (i = 0; i < n; i++) nor[off + i] &= s[i];
    return 0;
}
#include "../firmware/src/storage.c"

static uint8_t *load_logical(const char *path, size_t *len)
{
    FILE *f = fopen(path, "rb");
    uint8_t *raw = malloc(0x200000), *lg;
    size_t n, i;
    if (!f) { perror(path); exit(2); }
    n = fread(raw, 1, 0x200000, f);
    fclose(f);
    if (n < 20 * 48 + 0x400) { printf("%s: too short for a package\n", path); exit(2); }
    lg = malloc(n);
    for (i = 0; i < 20; i++) memcpy(lg + i * 47, raw + i * 48, 47);
    memcpy(lg + 20 * 47, raw + 20 * 48, n - 20 * 48);
    *len = n - 20;
    free(raw);
    return lg;
}

static uint32_t flash_off(const uint8_t *lg)        /* flash.bin offset in the logical image */
{
    uint8_t h[0x400];
    uint32_t i, n;
    memcpy(h, lg, sizeof h);
    ota_jl_enc(h, 0x40);
    n = ota_rd16(h + 8);
    for (i = 0; i < n; i++) {
        uint8_t *e = h + 0x40 + i * 0x50u;
        ota_jl_enc(e, 0x50);
        if (ota_rd16(e) == 0) return ota_rd32(e + 8);
    }
    return 0;
}

/* rewrite flash.bin's size in the logical image's UFW entry list (the entries' and the header's CRCs too): a package
 * of the same chip whose app area is another board's size */
static void set_fl_size(uint8_t *lg, uint32_t size)
{
    uint8_t h[0x40 + 11 * 0x50];
    uint32_t i, n;
    memcpy(h, lg, sizeof h);
    ota_jl_enc(h, 0x40);
    n = ota_rd16(h + 8);
    for (i = 0; i < n; i++) {
        uint8_t *e = h + 0x40 + i * 0x50u;
        ota_jl_enc(e, 0x50);
        if (ota_rd16(e) == 0)
            ota_wr32(e + 12, size);
        ota_jl_enc(e, 0x50);
    }
    ota_wr16(h + 2, ota_crc16(h + 0x40, n * 0x50u, 0));   /* (over the entries as stored) */
    ota_wr16(h, ota_crc16(h + 2, 0x3E, 0));
    ota_jl_enc(h, 0x40);
    memcpy(lg, h, 0x40 + n * 0x50u);
}

static int check(const char *what, int ok) { printf("%-56s %s\n", what, ok ? "ok" : "FAIL"); return ok ? 0 : 1; }

/* ---- #418: the cleanup must not classify or erase the autosave pair and the voice bank ----
 * A record as the native loader's cleanup recognises it: u16 at 0 = nonzero CRC16 of the next 78
 * bytes, u16 0x5441 at +6. seed makes each one different. */
static void make_record(uint8_t *r, uint32_t seed)
{
    uint32_t i;
    memset(r, 0, 80);
    for (i = 2; i < 80; i++) r[i] = (uint8_t)(seed * 31u + i * 7u + 1u) & 0x7Fu;   /* (7-bit: also FM6-patch shaped) */
    r[6] = 0x41; r[7] = 0x54;
    ota_wr16(r, ota_crc16(r + 2, 78, 0));
}
static int looks_like_record(const uint8_t *r)
{
    return ota_rd16(r + 6) == 0x5441u && ota_rd16(r) && ota_rd16(r) == ota_crc16(r + 2, 78, 0);
}
/* an arbitrary storage object (not a valid project): 3840 bytes, a record at payload + 0xE00 = sector + 0xF00 */
static void make_payload(uint8_t *pl, uint32_t seed)
{
    uint32_t i;
    for (i = 0; i < ST_PAYLOAD_MAX; i++) pl[i] = (uint8_t)(i * 13u + seed);
    make_record(pl + 0xE00, seed);
}
static uint32_t protected_erases(void) { return erase_n[0xE5] + erase_n[0xE6] + erase_n[0xE7]; }
static int sector_blank(uint32_t off)
{
    uint32_t i;
    for (i = 0; i < 0x1000u; i++) if (nor[off + i] != 0xFF) return 0;
    return 1;
}
static void arm_update_records(void)               /* Felucca's step-1 record and the stock firmware's */
{
    uint8_t r[112] = {0};
    uint32_t i;
    make_record(r, 99);
    r[2] = 0x0D; r[3] = 0x5A; r[4] = 0x01; r[5] = 0x5A;
    ota_wr16(r, ota_crc16(r + 2, 78, 0));
    for (i = 0; i < 0xF00u; i++) nor[0xE4000 + i] = nor[0xE8000 + i] = (uint8_t)(i * 5u + 3u);   /* (sector bytes below it) */
    memcpy(nor + 0xE4F00, r, sizeof r);
    memcpy(nor + 0xE8F00, r, sizeof r);
}
/* Variants of what lies in 0xE5000..0xE7FFF. All of them put record-shaped bytes at sector + 0xF00 of every sector
 * that holds an arbitrary object or raw bytes; 3 mirrors production's voice bank (fm6_vbank.c keeps its tail erased) */
enum { V_BOTH_COPIES, V_STAGED_BANK, V_RAW_SECTORS, V_PRODUCTION_BANK };
static uint8_t prot_ref[PROT_HI - PROT_LO];
static void fixture_protected(int v)
{
    static uint8_t pl[ST_PAYLOAD_MAX];
    uint32_t i;
    memset(nor + PROT_LO, 0xFF, PROT_HI - PROT_LO);
    if (v == V_RAW_SECTORS) {                      /* exact boundaries: the first, middle and last protected sector */
        for (i = 0; i < 3u; i++) {
            uint8_t r[80];
            memset(nor + PROT_LO + i * 0x1000u, 0x5A + (int)i, 0xF00);
            make_record(r, 40 + i);
            memcpy(nor + PROT_LO + i * 0x1000u + 0xF00, r, sizeof r);
        }
    } else {
        make_payload(pl, 1);
        if (st_save(OBJ_AUTOSAVE, pl, ST_PAYLOAD_MAX)) { printf("st_save failed\n"); exit(1); }   /* copy A */
        if (v == V_BOTH_COPIES) {
            make_payload(pl, 2);
            if (st_save(OBJ_AUTOSAVE, pl, ST_PAYLOAD_MAX)) { printf("st_save failed\n"); exit(1); }   /* copy B */
        } else if (v == V_STAGED_BANK) {           /* a bank staged in the older copy (fm6_vbank.c): commit record
                                                    * type OBJ_FM6VB, slot 1; payload from 224 to 0xEFF, tail erased */
            st_hdr_t h;
            memset(&h, 0xFF, sizeof h);
            h.magic = ST_MAGIC; h.type = OBJ_FM6VB; h.slot = 1; h.seq = 3; h.len = 3616;
            for (i = 0; i < 3616u; i++) nor[0xE6000 + 224 + i] = (uint8_t)(i * 3u + 1u);
            h.crc = st_crc32(nor + 0xE6000 + 224, h.len);
            h.hcrc = st_crc32(&h, sizeof h - 4u);
            memcpy(nor + 0xE6000, &h, sizeof h);
        }
        if (v == V_PRODUCTION_BANK || v == V_BOTH_COPIES || v == V_STAGED_BANK) {   /* the bank, tail erased */
            st_hdr_t h;
            memset(&h, 0xFF, sizeof h);
            h.magic = ST_MAGIC; h.type = OBJ_FM6VB; h.slot = 0; h.seq = 2; h.len = 3616;
            for (i = 0; i < 3616u; i++) nor[0xE7000 + 224 + i] = (uint8_t)(i * 5u + 2u);
            h.crc = st_crc32(nor + 0xE7000 + 224, h.len);
            h.hcrc = st_crc32(&h, sizeof h - 4u);
            memcpy(nor + 0xE7000, &h, sizeof h);
        }
        if (v == V_STAGED_BANK) {                  /* ... and an arbitrary object's bytes in the bank's sector */
            uint8_t r[80];
            make_record(r, 77);
            memcpy(nor + 0xE7F00, r, sizeof r);
        }
    }
    memcpy(prot_ref, nor + PROT_LO, sizeof prot_ref);
}
/* ordinary records outside the window: cleaned (negative controls); user objects that look like records: kept */
static const uint32_t CLEAN_AT[] = {0x93000u, 0xE0000u, 0xE3000u, 0xE4000u, 0xE8000u, 0xFB000u};
static uint8_t user_ref[0x1000], proj_ref[0x1000];
static void arm_outside(void)
{
    static uint8_t pl[ST_PAYLOAD_MAX];
    uint32_t i;
    uint8_t r[80];
    for (i = 0; i < sizeof CLEAN_AT / sizeof *CLEAN_AT; i++) {
        make_record(r, 10 + i);
        memset(nor + CLEAN_AT[i], 0x33, 0xF00);
        memcpy(nor + CLEAN_AT[i] + 0xF00, r, sizeof r);
    }
    arm_update_records();                          /* (0xE4F00 and 0xE8F00 as the update protocol leaves them) */
    make_payload(pl, 5);                           /* a project slot and a sample slot that look like records */
    memset(nor + 0x97000, 0xFF, 0x2000);
    if (st_save(OBJ_PROJECT0, pl, ST_PAYLOAD_MAX)) { printf("st_save failed\n"); exit(1); }
    memcpy(proj_ref, nor + 0x97000, sizeof proj_ref);
    for (i = 0; i < 0x1000u; i++) nor[0xA0000 + i] = (uint8_t)(i * 7u);
    make_record(r, 6);
    memcpy(nor + 0xA0F00, r, sizeof r);
    memcpy(user_ref, nor + 0xA0000, sizeof user_ref);
}
static int outside_cleaned(void)                   /* every record there is gone with its whole sector */
{
    uint32_t i;
    for (i = 0; i < sizeof CLEAN_AT / sizeof *CLEAN_AT; i++)
        if (!sector_blank(CLEAN_AT[i])) return 0;
    return 1;
}
static int user_kept(void)
{
    return !memcmp(nor + 0xA0000, user_ref, sizeof user_ref) && !memcmp(nor + 0x97000, proj_ref, sizeof proj_ref);
}
static void reset_counters(void)
{
    memset(erase_n, 0, sizeof erase_n);
    prot_reads = 0; bad_range = 0; erases = 0; requests = 0;
    rd_fail_off = er_fail_off = 0xFFFFFFFFu;
}

static int cleanup_case(const char *name, int v)
{
    static const char *const VN[] = {"autosave A+B + bank", "autosave A + staged bank + bank sector record",
                                     "raw record-shaped sectors", "autosave A + production bank"};
    char what[120];
    int bad = 0, rc, rep;
    (void)name;
    for (rep = 0; rep < 2; rep++) {                /* a successful update, then the repeated one (records armed again) */
        fixture_protected(v);
        arm_outside();
        reset_counters();
        rc = ldr_session();
        snprintf(what, sizeof what, "%s, %s: rc 0", VN[v], rep ? "repeated update" : "update");
        bad += check(what, rc == 0);
        snprintf(what, sizeof what, "  protected sectors 0xE5000..0xE7FFF byte-identical, 0 erases");
        bad += check(what, !memcmp(nor + PROT_LO, prot_ref, sizeof prot_ref) && protected_erases() == 0);
        bad += check("  ... not even read (no classification)", prot_reads == 0);
        bad += check("  records outside it (0x93F00, 0xE0F00, 0xE3F00, 0xE4F00, 0xE8F00, 0xFBF00) cleaned",
                     outside_cleaned() && erase_n[0xE4] == 1 && erase_n[0xE8] == 1);
        bad += check("  user objects that look like records kept; only allowed windows written",
                     user_kept() && bad_range == 0);
        if (v == V_BOTH_COPIES) {                  /* the objects themselves, as the app would load them */
            static uint8_t got[ST_PAYLOAD_MAX], pl[ST_PAYLOAD_MAX];
            make_payload(pl, 2);
            bad += check("  autosave loads (newest copy B), payload intact",
                         st_load(OBJ_AUTOSAVE, got, sizeof got) == (int)ST_PAYLOAD_MAX && !memcmp(got, pl, sizeof pl) &&
                         looks_like_record(nor + 0xE5F00) && looks_like_record(nor + 0xE6F00));
        }
    }
    return bad;
}

/* failures of the cleanup's own I/O (best effort: the update has succeeded by then), without touching the window */
static int failure_cases(void)
{
    int bad = 0, rc;
    fixture_protected(V_BOTH_COPIES);
    arm_outside();
    reset_counters();
    er_fail_off = 0xE4000u;                        /* the erase of the staging sector fails */
    rc = ldr_session();
    bad += check("erase failure at 0xE4000: update still succeeds", rc == 0);
    bad += check("  its record stays; the other records are cleaned", nor[0xE4F06] == 0x41 && sector_blank(0xE8000) &&
                 sector_blank(0xFB000));
    bad += check("  protected sectors untouched, not read", !memcmp(nor + PROT_LO, prot_ref, sizeof prot_ref) &&
                 protected_erases() == 0 && prot_reads == 0);
    fixture_protected(V_BOTH_COPIES);
    arm_outside();
    reset_counters();
    rd_fail_off = 0xE4F00u;                        /* the read of the staging record fails */
    rc = ldr_session();
    bad += check("read failure at 0xE4F00: update still succeeds", rc == 0);
    bad += check("  its record stays; those above are cleaned", nor[0xE4F06] == 0x41 && sector_blank(0xE8000) &&
                 sector_blank(0xFB000));
    bad += check("  protected sectors untouched, not read", !memcmp(nor + PROT_LO, prot_ref, sizeof prot_ref) &&
                 protected_erases() == 0 && prot_reads == 0);
    fixture_protected(V_RAW_SECTORS);
    arm_outside();
    reset_counters();
    rd_fail_off = 0xE6F00u;                        /* a read failure inside the window is never even reached */
    er_fail_off = 0xE5000u;
    rc = ldr_session();
    bad += check("faults aimed at the window are never hit", rc == 0 && prot_reads == 0 && erase_n[0xE5] == 0 &&
                 !memcmp(nor + PROT_LO, prot_ref, sizeof prot_ref) && outside_cleaned());
    reset_counters();
    return bad;
}

/* #438: the same accepted UPF6 bytes survive the actual native loader. */
static int update_record_upfm6_tests(void)
{
    static uint8_t payload[UPDATE_RECORD_UPFM6_SIZE], got[UPDATE_RECORD_UPFM6_SIZE], before[2][ST_SECTOR];
    int bad = 0;
    update_record_upfm6(payload);
    bad += check("#438 fixture has production OTA CRC16 and loader marker predicate", looks_like_record(UPDATE_RECORD_FIXTURE) &&
                 ota_crc16(UPDATE_RECORD_FIXTURE + 2, 78, 0) == 0xB71Du);
    {
        uint8_t altered[sizeof UPDATE_RECORD_FIXTURE];
        memcpy(altered, UPDATE_RECORD_FIXTURE, sizeof altered);
        altered[20] ^= 1u;
        bad += check("#438 changed CRC-covered byte fails the production loader predicate", !looks_like_record(altered));
        memcpy(altered, UPDATE_RECORD_FIXTURE, sizeof altered);
        altered[6] ^= 1u;
        ota_wr16(altered, ota_crc16(altered + 2, 78, 0));
        bad += check("#438 changed marker fails predicate even with matching production CRC", !looks_like_record(altered));
    }
    bad += check("#438 production storage commits UPF6 fixture into both copies",
                 st_save_to(OBJ_UPFM6, payload, sizeof payload, 0) == 0 &&
                 st_save_to(OBJ_UPFM6, payload, sizeof payload, 1) == 0 &&
                 st_load(OBJ_UPFM6, got, sizeof got) == (int)sizeof got && !memcmp(got, payload, sizeof got));
    for (uint32_t copy = 0; copy < 2u; copy++)
        memcpy(before[copy], nor + st_sector(OBJ_UPFM6, copy), ST_SECTOR);
    for (uint32_t repeat = 0; repeat < 2u; repeat++) {
        fixture_protected(V_BOTH_COPIES);
        arm_outside();
        reset_counters();
        bad += check("#438 actual loader session/repeat completes with UPF6 record-shaped bytes", ldr_session() == 0);
        for (uint32_t copy = 0; copy < 2u; copy++) {
            uint32_t base = st_sector(OBJ_UPFM6, copy);
            bad += check("#438 UPF6 whole sector unchanged and never erased by loader",
                         !memcmp(before[copy], nor + base, ST_SECTOR) && erase_n[base >> 12] == 0 &&
                         looks_like_record(nor + base + 0xF00u) &&
                         !memcmp(nor + base + 0xF00u, UPDATE_RECORD_FIXTURE, sizeof UPDATE_RECORD_FIXTURE));
        }
        bad += check("#438 UPF6 remains loadable byte for byte after loader cleanup",
                     st_load(OBJ_UPFM6, got, sizeof got) == (int)sizeof got && !memcmp(got, payload, sizeof got));
        bad += check("#438 native staging/stock records cleaned; other protected windows unchanged",
                     outside_cleaned() && erase_n[0xE4] == 1 && erase_n[0xE8] == 1 && bad_range == 0 &&
                     !memcmp(nor + PROT_LO, prot_ref, sizeof prot_ref) && !protected_erases() && !prot_reads && user_kept());
    }
    /* Causal control for the actual cleanup branch, outside every protected
     * data window. CRC or marker changes alone must change its erase decision. */
    for (uint32_t variant = 0; variant < 3u; variant++) {
        uint8_t altered[sizeof UPDATE_RECORD_FIXTURE];
        memcpy(altered, UPDATE_RECORD_FIXTURE, sizeof altered);
        if (variant == 1u) altered[20] ^= 1u;
        if (variant == 2u) {
            altered[6] ^= 1u;
            ota_wr16(altered, ota_crc16(altered + 2, 78, 0));
        }
        memset(nor + 0x94000u, 0xFF, ST_SECTOR);
        memcpy(nor + 0x94F00u, altered, sizeof altered);
        reset_counters();
        bad += check("#438 native cleanup control session succeeds", ldr_session() == 0);
        bad += check("#438 actual cleanup erases only CRC-and-marker matching control",
                     variant == 0u ? sector_blank(0x94000u) && erase_n[0x94] == 1u :
                     erase_n[0x94] == 0u && !memcmp(nor + 0x94F00u, altered, sizeof altered));
    }
    return bad;
}

int main(int argc, char **argv)
{
    size_t olen;
    static uint8_t user[0x1000];
    uint8_t *old, head[0x4000];
    uint32_t ofo, nfo, i;
    int bad = 0, rc;
    if (argc < 3) { printf("usage: ldr_test OLD.fwsc NEW.fwsc\n"); return 2; }
    old = load_logical(argv[1], &olen);
    logical = load_logical(argv[2], &logical_len);
    ofo = flash_off(old);
    nfo = flash_off(logical);
    /* device: OLD installed, plus a valid update record at 0xE4F00 (Felucca's step 1) and 0xE8F00 (the stock
     * firmware's, a first install from it); user sample data in Felucca's store that looks like a record */
    memset(nor, 0xFF, sizeof nor);
    memcpy(nor, old + ofo, 0x93000);
    memcpy(head, nor, sizeof head);
    {
        uint8_t r[112] = {0};
        r[2] = 0x0D; r[3] = 0x5A; r[4] = 0x01; r[5] = 0x5A; r[6] = 0x41; r[7] = 0x54;
        ota_wr16(r, ota_crc16(r + 2, 78, 0));
        memcpy(nor + 0xE4F00, r, sizeof r);
        memcpy(nor + 0xE8F00, r, sizeof r);
        for (i = 0; i < 0x1000u; i++) nor[0xA0000 + i] = (uint8_t)(i * 7u);
        memcpy(nor + 0xA0F00, r, sizeof r);
        memcpy(user, nor + 0xA0000, sizeof user);
    }
    fixture_protected(V_BOTH_COPIES);               /* the autosave pair and the bank, record-shaped bytes at sector + 0xF00 */
    bad += check("ota_crc16 is CRC-16/XMODEM (project_test.c's record check uses the same)",
                 ota_crc16((const uint8_t *)"123456789", 9, 0) == 0x31C3u);
    {
        bad += check("fixture: payload offset 0xE00 is sector + 0xF00, and it classifies as a record",
                     ST_PAYLOAD_OFF + 0xE00u == 0xF00u && looks_like_record(nor + 0xE5F00) &&
                     looks_like_record(nor + 0xE6F00) && sector_blank(0xE7000) == 0 && LDR_AUTO_LO == PROT_LO &&
                     LDR_AUTO_HI == PROT_HI);
    }
    /* 1.6.1: flash.bin must be exactly this board's [0, app area end): a package with another board's size (an
     * SMK-37's app area ends at 0x9D000, the FM-1's at 0x93000; one byte short too) is refused before any erase */
    {
        static const uint32_t SZ[2] = {0x9D000u, LDR_APP_HI - 1u};
        uint32_t k;
        for (k = 0; k < 2u; k++) {
            set_fl_size(logical, SZ[k]);
            erases = 0;
            rc = ldr_session();
            bad += check(k ? "flash.bin a byte short of the app area: refused, nothing erased" :
                             "another board's size (0x9D000): refused (-14), nothing erased",
                         rc == -14 && erases == 0 && !memcmp(nor + 0x4000, old + ofo + 0x4000, 0x93000 - 0x4000));
        }
        set_fl_size(logical, LDR_APP_HI);           /* back: this board's size, the install below takes it */
        requests = 0;
    }
    /* a damaged package (one byte deep in the app area): refused before anything is erased */
    {
        size_t at = nfo + 0x50123u;
        logical[at] ^= 0x01;
        erases = 0;
        rc = ldr_session();
        bad += check("damaged package (flash.bin CRC) refused, nothing erased", rc == -12 && erases == 0 &&
                     !memcmp(nor + 0x4000, old + ofo + 0x4000, 0x93000 - 0x4000) && nor[0xE4F06] == 0x41);
        logical[at] ^= 0x01;
        requests = 0;
    }
    /* a sector that comes in different the second time (a transfer error after the check) is read again */
    flip_addr = nfo + 0x20000u; flip_on = 2; flip_seen = 0;
    rc = ldr_session();
    printf("  rc %d, %u requests, %u sector erases\n", rc, requests, erases);
    bad += check("install completes (flash.bin exactly the app area, 0x93000)", rc == 0);
    bad += check("a sector changed in transfer after the check is read again", flip_seen == 3);
    flip_addr = 0xFFFFFFFFu;
    bad += check("app area == the new package's flash.bin", !memcmp(nor + 0x4000, logical + nfo + 0x4000, 0x93000 - 0x4000));
    bad += check("flash head [0, 0x4000) untouched", !memcmp(nor, head, sizeof head));
    bad += check("finish asked (0xF0000000)", f0_asked >= 1);
    bad += check("update records cleared (RAM + flash 0xE4F00, the stock firmware's 0xE8F00)",
                 record_cleared && nor[0xE4F06] == 0xFF && nor[0xE8F06] == 0xFF);
    bad += check("user data in Felucca's store that looks like a record is kept", !memcmp(nor + 0xA0000, user, sizeof user));
    bad += check("no write outside the allowed windows", bad_range == 0);
    bad += check("autosave pair + bank: byte-identical, never erased", !memcmp(nor + PROT_LO, prot_ref, sizeof prot_ref) &&
                 protected_erases() == 0);
    /* same package again: nothing to erase */
    erases = 0; requests = 0;
    rc = ldr_session();
    bad += check("re-run with the same package erases nothing", rc == 0 && erases == 0);
    /* #418: every variant of the autosave / voice bank window, an update and a repeated one; then the failure cases */
    bad += cleanup_case("both", V_BOTH_COPIES);
    bad += cleanup_case("staged", V_STAGED_BANK);
    bad += cleanup_case("raw", V_RAW_SECTORS);
    bad += cleanup_case("production", V_PRODUCTION_BANK);
    bad += failure_cases();
    bad += update_record_upfm6_tests();
    bad += check("app area still the new package's flash.bin", !memcmp(nor + 0x4000, logical + nfo + 0x4000, 0x93000 - 0x4000));
    /* a package for another chip key is refused before any erase */
    {
        uint8_t save = logical[nfo + 0x4000 + 5];
        logical[nfo + 0x4000 + 5] ^= 0x5A;           /* app area head no longer decrypts */
        memcpy(nor, old + ofo, 0x93000);
        erases = 0;
        rc = ldr_session();
        bad += check("foreign key / damaged app head refused, nothing erased", rc == -6 && erases == 0);
        logical[nfo + 0x4000 + 5] = save;
    }
    printf("%s\n", bad ? "LOADER TEST FAILED" : "loader test passed");
    free(old);
    free(logical);
    return bad != 0;
}
