/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* The editor's full backup (editor_backup.c: LIST / GET / PUT) against simulated NOR flash:
 * CRC before any write, stale runtime copies, USB resets and timeouts, malformed objects, older
 * project formats, settings values and user preset banks kept byte for byte; and (#321) the FM6 voice
 * bank (id 20) and the SLICE records (id 21): LIST 1, round trips, refusals, power cuts. */
static unsigned char nor[0x100000];                  /* the whole flash; the user sample slots (XIP) are 0xA0000.. of it */
#define SMP_USER_XIP(k) (nor + 0xA0000u + (k) * 0x14000u)
#define main hostsim_main
#include "hostsim.c"
#undef main

static int32_t fm1_enc_take(uint32_t e) { (void)e; return 0; }
static void fm1_irq_off(void) {}
static void fm1_irq_on(void) {}
static void lcd_sync(void) {}
static void lcd_power(uint32_t s) { (void)s; }   /* (MENU > SCREEN OFF: lcd.c) */
static void lcd_wake_now(void) {}
static void lcd_blit(uint32_t x, uint32_t y, uint32_t w, uint32_t h, const uint16_t *p)
{ (void)x; (void)y; (void)w; (void)h; (void)p; }
#define FELUCCA_FLASH 1
#include "../firmware/src/gfx.c"
#include "../firmware/src/panel.c"
#include "../firmware/src/ui.c"
static void panel_setup(void) {}

static uint8_t flash_ok = 1;
static int erase_error;
static uint32_t erases, progs;
static long cut_bytes = -1, cut_erase = -1;      /* the power goes after that many programmed bytes / at that erase */
static int dead;                                  /* .. and stays off: nothing more is written */
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
static uint32_t irq_save(void) { return 0; }
static void irq_restore(uint32_t f) { (void)f; }
static uint32_t fl_jedec_ram(void) { return 0; }
static void fl_plain_window_init(void) {}
#define FL_FAR(fn) (fn)
#include "../firmware/src/storage.c"
#include "../firmware/src/upreset.c"
#include "../firmware/src/project.c"
#include "old_pack.h"

enum { ED_BACKUP_LIST = 65, ED_BACKUP_GET, ED_BACKUP_PUT };
static uint8_t rep[4096];
static uint32_t rep_n;
static void ed_b(uint32_t v) { if (rep_n < sizeof rep) rep[rep_n++] = (uint8_t)(v & 127u); }
static uint32_t ed_unpack7(const uint8_t *a, uint32_t na, uint8_t *out, uint32_t max)
{
    uint32_t n = 0;
    while (na && n < max) {
        uint32_t m = *a++, j;
        na--;
        uint32_t k = na > 7u ? 7u : na;
        if (!k || n + k > max || (m >> k))
            return 0;
        for (j = 0; j < k; j++, na--)
            out[n++] = (uint8_t)(*a++ | ((m >> j) & 1u) << 7);
    }
    return na ? 0u : n;
}
static uint8_t ed_smp_buf[512] __attribute__((aligned(4)));
static void fm1_wdt_feed(void) {}
static int ed_flash_stop(void) { return transport_busy(); }
static void ed_str(const char *s, uint32_t max)
{
    uint32_t i;
    for (i = 0; s && s[i] && i < max; i++) ed_b((uint8_t)s[i]);
    ed_b(0);
}
#include "../firmware/src/editor_backup.c"
#include "../firmware/src/editor_fm6.c"

static int check(const char *what, int ok)
{
    printf("backup: %-72s %s\n", what, ok ? "ok" : "FAIL");
    return !ok;
}

static void reset(void)
{
    memset(nor, 0xFF, sizeof nor);
    memset(&song, 0, sizeof song);
    memset(trk, 0, sizeof trk);
    memset(&chain, 0, sizeof chain);
    chain_defaults(&chain_config);
    memset(proj_slot, 0, sizeof proj_slot);
    memset(up_bank, 0, sizeof up_bank);
    memset(&persist_saved, 0, sizeof persist_saved);
    memset(&settings, 0, sizeof settings);
    memset(&ui, 0, sizeof ui);
    panel = PANEL_DEFAULT;
    settings_init();
    host_tracks_init();
    fm1_ms = 0;
    transport_req = 0;
    usb.resets = 0;
    erase_error = 0;
    erases = progs = 0;
    dead = 0;
    cut_bytes = cut_erase = -1;
    memset(&fvb_tx, 0, sizeof fvb_tx);
    memset(usr_nz, 0, sizeof usr_nz);
#if FELUCCA_SLICE
    slc_man_save = 0;
    memset(slc_man, 0, sizeof slc_man);
#endif
    ed_bk_valid = ed_bk_put = 0;
}

static uint32_t call(uint32_t cmd, const uint8_t *a, uint32_t n)
{
    rep_n = 0;
    ed_backup_handle(cmd, a, n);
    return rep_n;
}
static void put32(uint8_t *a, uint32_t v) { for (uint32_t i = 0; i < 5u; i++) a[i] = (uint8_t)((v >> (7u * i)) & 127u); }

/* PUT begin: rc */
static uint32_t put_begin(uint32_t id, uint32_t len, uint32_t crc)
{
    uint8_t a[12] = {0, (uint8_t)id};
    put32(a + 2, len);
    put32(a + 7, crc);
    call(ED_BACKUP_PUT, a, sizeof a);
    return rep[2];
}
/* PUT one chunk of data at off: rc */
static uint32_t put_chunk(uint32_t id, uint32_t off, const uint8_t *p, uint32_t n)
{
    uint8_t a[16 + 300];
    uint32_t k = 7;
    a[0] = 1;
    a[1] = (uint8_t)id;
    put32(a + 2, off);
    while (n) {
        uint32_t g = n > 7u ? 7u : n, m = 0, i;
        for (i = 0; i < g; i++) m |= (uint32_t)(p[i] >> 7) << i;
        a[k++] = (uint8_t)m;
        for (i = 0; i < g; i++) a[k++] = p[i] & 127u;
        p += g;
        n -= g;
    }
    call(ED_BACKUP_PUT, a, k);
    return rep[2];
}
static uint32_t put_end(uint32_t id, uint32_t op)   /* op 2 commit, 3 abort */
{
    uint8_t a[2] = {(uint8_t)op, (uint8_t)id};
    call(ED_BACKUP_PUT, a, 2);
    return rep[2];
}
/* a whole object: begin, 256-byte chunks, commit; the first failing rc or the commit's */
static uint32_t put_all(uint32_t id, const void *v, uint32_t len, uint32_t crc)
{
    const uint8_t *p = v;
    uint32_t off, rc = put_begin(id, len, crc);
    for (off = 0; !rc && off < len; off += 256u)
        rc = put_chunk(id, off, p + off, len - off > 256u ? 256u : len - off);
    return rc ? rc : put_end(id, 2);
}
/* LIST: rc; the length and CRC of object id */
static uint32_t list(uint32_t id, uint32_t *len, uint32_t *crc)
{
    uint32_t i;
    call(ED_BACKUP_LIST, 0, 0);
    if (rep[1])
        return rep[1];
    for (i = 0; i < rep[2]; i++) {
        const uint8_t *o = rep + 3 + i * 11u;
        if (o[0] == id) {
            *len = ed_bk_r32(o + 1);
            *crc = ed_bk_r32(o + 6);
        }
    }
    return 0;
}
static uint32_t get(uint32_t id, uint32_t off, uint32_t count)
{
    uint8_t a[8] = {(uint8_t)id};
    put32(a + 1, off);
    a[6] = (uint8_t)(count & 127u);
    a[7] = (uint8_t)(count >> 7);
    call(ED_BACKUP_GET, a, sizeof a);
    return rep[1];
}

/* ---- #321: LIST 1, the FM6 voice bank (id 20) and the SLICE records (id 21) ---- */

/* LIST 1: rc; the length and CRC of object id (found = 1 when it is in the list) */
static uint32_t list1(uint32_t id, uint32_t *len, uint32_t *crc, int *found)
{
    uint8_t one = 1;
    uint32_t i;
    *found = 0;
    call(ED_BACKUP_LIST, &one, 1);
    if (rep[1])
        return rep[1];
    for (i = 0; i < rep[2]; i++) {
        const uint8_t *o = rep + 3 + i * 11u;
        if (o[0] == id) {
            *len = ed_bk_r32(o + 1);
            *crc = ed_bk_r32(o + 6);
            *found = 1;
        }
    }
    return 0;
}
/* GET of a whole object in 256-byte pieces: the first rc that was not 0 */
static uint32_t get_all(uint32_t id, uint32_t len, uint8_t *out)
{
    uint32_t off, rc = 0;
    for (off = 0; off < len && !rc; off += 256u) {
        uint32_t n = len - off > 256u ? 256u : len - off;
        rc = get(id, off, n);
        if (!rc && ed_unpack7(rep + 9, rep_n - 9u, out + off, 256u) != n)
            rc = 99;
    }
    return rc;
}

/* a bank: per voice a packed record (a factory patch renamed "<tag> k"), the used mask */
typedef struct {
    uint8_t v[FM6_NBANK][FM6_PACKED];
    uint32_t used;
    char name[11];
} bank_t;
static void make_bank(bank_t *b, char tag, uint32_t used, const char *name)
{
    uint32_t k;
    memset(b, 0, sizeof *b);
    for (k = 0; k < FM6_NBANK; k++) {
        uint8_t v[FP_SIZE + 1u];
        char nm[11];
        fm6_unpack(FM6_FACTORY[(k + (uint32_t)tag) % FM6_NFACTORY], v);
        snprintf(nm, sizeof nm, "%c VOICE %02u", tag, (unsigned)(k + 1u));
        memcpy(v + FP_NAME, nm, 10);
        v[FP_ALG] = (uint8_t)((k * 7u + (uint32_t)tag) % 32u);
        v[FP_OP * 2u + FP_OL] = (uint8_t)(50u + k);
        fm6_pack(v, b->v[k]);
    }
    b->used = used;
    snprintf(b->name, sizeof b->name, "%s", name);
}
/* the editor's own transfer (FM6B_BEGIN, a WRITE per used voice, END): END's rc */
static uint32_t send_bank(const bank_t *b)
{
    uint8_t a[1 + FM6_PACKED], e[15];
    uint32_t k, c = 0xFFFFFFFFu;
    rep_n = 0; ed_fm6_handle(ED_FM6B_BEGIN, a, 0);
    if (rep[0]) return rep[0];
    for (k = 0; k < FM6_NBANK; k++) {
        if (!((b->used >> k) & 1u)) continue;
        a[0] = (uint8_t)k;
        memcpy(a + 1, b->v[k], FM6_PACKED);
        rep_n = 0; ed_fm6_handle(ED_FM6B_WRITE, a, sizeof a);
        if (rep[1]) return rep[1];
        c = st_crc32_add(c, b->v[k], FM6_PACKED);
    }
    c = ~c;
    memset(e, ' ', 10);
    memcpy(e, b->name, strlen(b->name));
    for (k = 0; k < 5u; k++) e[10 + k] = (uint8_t)((c >> (7u * k)) & 127u);
    rep_n = 0; ed_fm6_handle(ED_FM6B_END, e, sizeof e);
    return rep[0];
}
/* the bank the device holds now equals b (its voices, the used mask, the name) */
static int bank_is(const bank_t *b)
{
    uint8_t pk[FM6_PACKED];
    const fvb_info_t *in = fvb_info();
    char nm[11] = {0};
    uint32_t k;
    if (!in || fm6_bank_used != b->used) return 0;
    memcpy(nm, in->name, 10);
    for (k = 10; k && nm[k - 1] == ' '; k--) nm[k - 1] = 0;
    if (strcmp(nm, b->name)) return 0;
    for (k = 0; k < FM6_NBANK; k++) {
        int has = !fvb_read(k, pk);
        if (has != (int)((b->used >> k) & 1u) || (has && memcmp(pk, b->v[k], FM6_PACKED))) return 0;
    }
    return 1;
}
static int autosave_is(char tag)
{
    uint8_t got[600], want[600];
    memset(want, tag, sizeof want);
    return st_load(OBJ_AUTOSAVE, got, sizeof got) == (int)sizeof got && !memcmp(got, want, sizeof want);
}
static void power_on(void)                          /* RAM lost, the stores read again */
{
    memset(&fvb_tx, 0, sizeof fvb_tx);
    fm6_bank_used = 0;
    fvb_boot();
}

static int plain_list_tests(void)
{
    int bad = 0, ok, found;
    uint32_t i, len = 0, crc = 0;
    uint8_t a[2] = {1, 1};
    reset();
    call(ED_BACKUP_LIST, 0, 0);
    ok = rep[1] == 0 && rep[2] == 13u && rep_n == 3u + 13u * 11u;
    for (i = 0; i < rep[2]; i++) ok &= rep[3 + i * 11u] != 20u && rep[3 + i * 11u] != 21u;
    bad += check("plain LIST: still the 13 objects of 1.0.3 (an editor that counts them keeps working)", ok);
    bad += check("LIST 1 on an empty device: 15 objects, 20 and 21 last, both 0 bytes (CRC 0)",
                 list1(20, &len, &crc, &found) == 0 && rep[2] == 13u + ED_BK_XN && found && !len && !crc &&
                 rep[3 + 13 * 11] == 20u && (!FELUCCA_SLICE || rep[3 + 14 * 11] == 21u) &&
                 (!FELUCCA_SLICE || (list1(21, &len, &crc, &found) == 0 && found && !len && !crc)));
    a[0] = 2;
    call(ED_BACKUP_LIST, a, 1);
    ok = rep[1] == 1u && rep[2] == 0;
    a[0] = 1;
    call(ED_BACKUP_LIST, a, 2);
    ok &= rep[1] == 1u && rep[2] == 0;
    bad += check("LIST with another argument, or two: rc 1, as firmware without LIST 1 answers", ok);
    bad += check("INFO's 58 01 caps (editor.c) with the flash store and SLICE: 7 = LIST 1, id 20, id 21",
                 ED_BK_XCAPS == (FELUCCA_SLICE ? 7u : 3u) && ED_BK_XN == (FELUCCA_SLICE ? 2u : 1u) && sizeof ED_BK_XIDS == 2u && ED_BK_XIDS[0] == 20u && ED_BK_XIDS[1] == 21u);
    return bad;
}

static int bank_tests(void)
{
    int bad = 0, ok, found;
    static bank_t a, b, c;
    static uint8_t objA[FVB_LEN], got[FVB_LEN], m[FVB_LEN], snap[0x100000], pre[0x3000];
    uint32_t len = 0, crc = 0, k, e0;
    uint8_t as_data[600];
    memset(as_data, 'S', sizeof as_data);
    make_bank(&a, 'A', 0xFFFFFFFFu, "BANK A");
    make_bank(&b, 'B', 0x0000FFFFu, "BANK B");

    /* LIST 1 and GET of a bank */
    reset();
    fvb_boot();
    st_save(OBJ_AUTOSAVE, as_data, sizeof as_data);      /* an autosave (copy A) */
    ok = send_bank(&a) == 0 && bank_is(&a);
    bad += check("setup: a bank A written over the editor's FM6B commands", ok);
    ok = list1(20, &len, &crc, &found) == 0 && found && len == FVB_LEN && len == 3616u &&
         crc == st_crc32(nor + 0xE7000u + FVB_INFO, FVB_LEN);
    bad += check("LIST 1: id 20 is 3616 bytes, its CRC the bank payload's", ok);
    ok = get_all(20, len, objA) == 0 && !memcmp(objA, nor + 0xE7000u + FVB_INFO, FVB_LEN) && st_crc32(objA, len) == crc;
    bad += check("GET in 256-byte pieces: the payload as stored at 0xE7000, CRC as listed", ok);
    ok = !memcmp(objA, "FM6V", 4) && ((fvb_info_t *)objA)->used == 0xFFFFFFFFu && !memcmp(objA + 12, "BANK A", 6);
    bad += check("  .. it begins with the bank header (FM6V, ver 1, used mask, name)", ok);
    bad += check("GET at and past the end, and of 0 bytes: rc 1",
                 get(20, len, 1) == 1u && get(20, len - 1u, 2) == 1u && get(20, 0, 0) == 1u && get(20, 0, 256) == 0);
    project_save(0);                                       /* (the staging RAM is not used by id 20) */
    bad += check("a project save after LIST makes the runtime copy stale (5) but not id 20 (read from flash)",
                 get(0, 0, 16) == 5u && get(20, 0, 16) == 0);

    /* a restore on a device with no bank */
    reset();
    fvb_boot();
    st_save(OBJ_AUTOSAVE, as_data, sizeof as_data);
    memcpy(snap, nor, sizeof nor);
    ok = put_all(20, objA, FVB_LEN, st_crc32(objA, FVB_LEN)) == 0 && bank_is(&a);
    bad += check("PUT id 20 on a device with no bank: rc 0, the bank loads (32 voices, name) and reads back exactly", ok);
    ok = !memcmp(nor + 0xE7000u + FVB_INFO, objA, FVB_LEN);
    for (k = 0xE7F00u; k < 0xE8000u; k++) ok &= nor[k] == 0xFFu;
    bad += check("  .. 0xE7000 holds the object byte for byte, its tail (0xE7F00..) erased", ok);
    ok = 1;
    for (k = 0; k < 0x100000u; k++)
        if (nor[k] != snap[k] && !(k >= 0xE6000u && k < 0xE8000u)) ok = 0;
    bad += check("  .. only 0xE7000 (the bank) and 0xE6000 (the autosave's older copy, staged) were written",
                 ok && ((st_hdr_t *)(nor + 0xE6000u))->type == OBJ_FM6VB && autosave_is('S'));
    power_on();
    bad += check("  .. after a power-on: the same bank", bank_is(&a));
    ok = list1(20, &len, &crc, &found) == 0 && found && len == FVB_LEN && crc == st_crc32(objA, FVB_LEN);
    bad += check("  .. LIST 1 lists it again with the CRC of the archive's object (a full round trip)", ok);

    /* a restore over another bank */
    ok = send_bank(&b) == 0 && bank_is(&b) && !bank_is(&a);
    ok &= put_all(20, objA, FVB_LEN, st_crc32(objA, FVB_LEN)) == 0 && bank_is(&a) && autosave_is('S');
    bad += check("PUT id 20 over another bank (16 voices): replaced by A, the autosave kept", ok);

    /* an empty object changes nothing */
    memcpy(snap, nor, sizeof nor);
    e0 = erases;
    ok = put_all(20, 0, 0, st_crc32(0, 0)) == 0 && !memcmp(snap, nor, sizeof nor) && erases == e0 && bank_is(&a);
    bad += check("an empty id 20 is taken and ignored (rc 0): the device's bank is never deleted", ok);

    /* malformed and newer objects: nothing written */
#define REFUSED(what, expr_before) do { memcpy(m, objA, sizeof m); expr_before; \
        ok = put_all(20, m, FVB_LEN, st_crc32(m, FVB_LEN)) == 2u && !memcmp(snap, nor, sizeof nor) && erases == e0 && bank_is(&a); \
        bad += check(what, ok); } while (0)
    REFUSED("id 20 with another magic is refused (2), nothing written", m[0] ^= 1);
    REFUSED("id 20 of a newer version (ver 2) is refused (2)", m[4] = 2);
    REFUSED("id 20 with 31 voices in its layout is refused (2)", m[6] = 31);
    REFUSED("id 20 with the reserved words set is refused (2)", m[24] = 1);
    REFUSED("id 20 with a control character in the name is refused (2)", m[12 + 3] = 7);
    REFUSED("id 20 with the name's terminator set is refused (2)", m[12 + 10] = 'x');
    make_bank(&c, 'C', 0x0000FFFFu, "BANK C");
    send_bank(&c);
    list1(20, &len, &crc, &found);
    get_all(20, len, got);
    memcpy(snap, nor, sizeof nor);
    e0 = erases;
    memcpy(m, got, sizeof m);
    m[FVB_VOICES - FVB_INFO + 20 * UPF_PK + 5] = 0;       /* a voice slot of an unused voice that is not erased */
    ok = put_all(20, m, FVB_LEN, st_crc32(m, FVB_LEN)) == 2u && !memcmp(snap, nor, sizeof nor) && erases == e0 && bank_is(&c);
    bad += check("id 20 with data in the slot of a voice that is not used is refused (2)", ok);
    ok = put_all(20, got, FVB_LEN, st_crc32(got, FVB_LEN) ^ 1u) == 2u && !memcmp(snap, nor, sizeof nor) && erases == e0;
    bad += check("id 20 with a wrong CRC is refused at commit (2), nothing written", ok);
    ok = put_begin(20, FVB_LEN - 4u, 0) == 1u && put_begin(20, FVB_LEN + 4u, 0) == 1u && put_begin(20, 3840u, 0) == 1u &&
         put_begin(20, 4000u, 0) == 1u;
    bad += check("id 20 of another length is refused at begin (1)", ok);
    put_begin(20, FVB_LEN, st_crc32(got, FVB_LEN));
    put_chunk(20, 0, got, 64);
    ok = put_end(20, 2) == 2u && !memcmp(snap, nor, sizeof nor) && erases == e0;
    bad += check("a commit before all bytes arrived is refused (2), nothing written", ok);
    put_begin(20, FVB_LEN, st_crc32(got, FVB_LEN));
    usb.resets++;
    ok = put_chunk(20, 0, got, 64) == 5u;
    transport_req = 1;
    ok &= put_begin(20, FVB_LEN, 0) == 3u;
    transport_req = 0;
    bad += check("a USB reset during PUT ends it (5); PUT while starting PLAY is refused (3)", ok && bank_is(&c));

    /* a flash error: the old bank stays */
    erase_error = 1;
    ok = put_all(20, objA, FVB_LEN, st_crc32(objA, FVB_LEN)) == 4u && bank_is(&c);
    erase_error = 0;
    bad += check("a flash error (the stage's erase) answers 4; the old bank stays", ok);
    flash_ok = 0;
    ok = put_all(20, objA, FVB_LEN, st_crc32(objA, FVB_LEN)) == 4u;
    flash_ok = 1;
    bad += check("no flash: rc 4", ok);

    /* an FM6B transfer open in the editor: the restore takes the stage, the transfer ends (5) */
    {
        uint8_t w[1 + FM6_PACKED];
        rep_n = 0; ed_fm6_handle(ED_FM6B_BEGIN, w, 0);
        w[0] = 0; memcpy(w + 1, a.v[0], FM6_PACKED);
        rep_n = 0; ed_fm6_handle(ED_FM6B_WRITE, w, sizeof w);
        ok = rep[1] == 0;
        ok &= put_all(20, objA, FVB_LEN, st_crc32(objA, FVB_LEN)) == 0 && bank_is(&a);
        w[0] = 1; memcpy(w + 1, a.v[1], FM6_PACKED);
        rep_n = 0; ed_fm6_handle(ED_FM6B_WRITE, w, sizeof w);
        ok &= rep[1] == 5u && bank_is(&a);
        bad += check("a restore during an FM6B transfer: restored; the transfer's next WRITE answers 5, the bank is A", ok);
    }
    /* the autosave takes the staged sector later: the bank stays */
    {
        uint8_t t_data[600];
        memset(t_data, 'T', sizeof t_data);
        st_save(OBJ_AUTOSAVE, t_data, sizeof t_data);
        st_save(OBJ_AUTOSAVE, t_data, sizeof t_data);
        power_on();
        bad += check("autosaves into the staged sector afterwards (both copies): the bank at 0xE7000 and the autosave stand",
                     bank_is(&a) && autosave_is('T'));
    }
    /* GET after the bank changed: stale (5) */
    list1(20, &len, &crc, &found);
    send_bank(&c);
    ok = get(20, 0, 16) == 5u;
    list1(20, &len, &crc, &found);
    ok &= get(20, 0, 16) == 0;
    bad += check("GET of id 20 after the bank was replaced since LIST: rc 5; after a new LIST: rc 0", ok);
    transport_req = 1;
    ok = get(20, 0, 16) == 3u;
    transport_req = 0;
    bad += check("GET of id 20 while starting PLAY: rc 3", ok);

    /* power cuts: after every programmed byte, and in each erase, of a restore */
    {
        uint32_t n, total, old = 0, nw = 0, other = 0, eold = 0, enew = 0;
        reset();
        fvb_boot();
        st_save(OBJ_AUTOSAVE, as_data, sizeof as_data);
        send_bank(&b);                                     /* the device holds B (16 voices); A (32) is restored */
        memcpy(pre, nor + 0xE5000u, sizeof pre);
        progs = 0;
        put_all(20, objA, FVB_LEN, st_crc32(objA, FVB_LEN));
        total = progs;
        for (n = 0; n < total; n++) {
            memcpy(nor + 0xE5000u, pre, sizeof pre);
            power_on();
            dead = 0;
            cut_bytes = (long)n;
            put_all(20, objA, FVB_LEN, st_crc32(objA, FVB_LEN));
            dead = 0;
            cut_bytes = -1;
            power_on();
            if (bank_is(&b)) old++;
            else if (bank_is(&a)) nw++;
            else other++;
            if (!autosave_is('S')) other++;
        }
        for (k = 0; k < 2u; k++) {                         /* the stage's erase, the copy's erase */
            memcpy(nor + 0xE5000u, pre, sizeof pre);
            power_on();
            dead = 0;
            cut_erase = (long)k;
            put_all(20, objA, FVB_LEN, st_crc32(objA, FVB_LEN));
            dead = 0;
            cut_erase = -1;
            power_on();
            eold += bank_is(&b);
            enew += bank_is(&a);
            if (!autosave_is('S')) other++;
        }
        printf("backup:   %u cut points (bytes): %u the old bank, %u the new one, %u anything else\n", (unsigned)total,
               (unsigned)old, (unsigned)nw, (unsigned)other);
        bad += check("a power cut after any programmed byte of a restore: the old bank or the new one, never half",
                     !other && old && nw && old + nw == total && total > 7000u);
        bad += check("  .. a cut in the stage's erase: the old bank; in the copy's erase: the new one (finished at boot)",
                     eold == 1u && enew == 1u && !other);
    }
    return bad;
}

#if FELUCCA_FLASH && FELUCCA_SLICE
/* a slot k: a sample of nsamp samples (ADPCM from a seed), header and data in the flash image, scanned */
static void make_sample(uint32_t k, uint32_t nsamp, uint32_t seed)
{
    uint8_t *slot = nor + SMP_USER_BASE + k * SMP_USER_SIZE;
    smp_user_hdr_t h;
    uint32_t bytes = (nsamp + 1u) / 2u, i;
    memset(slot, 0xFF, SMP_USER_SIZE);
    for (i = 0; i < bytes; i++)
        slot[SMP_USER_DATA + i] = (uint8_t)(i * 131u + seed * 17u + (i >> 3));
    memset(&h, 0, sizeof h);
    h.magic = SMP_USER_MAGIC;
    h.version = 1;
    h.nz = 1;
    memcpy(h.name, "TEST", 4);
    h.data_len = bytes;
    h.crc = st_crc32(slot + SMP_USER_DATA, bytes);
    h.zone[0].n = nsamp;
    h.zone[0].le = nsamp - 1u;
    h.zone[0].rate = 32768u;
    h.zone[0].root16 = 60 * 16;
    h.zone[0].hi = 127;
    memcpy(slot, &h, sizeof h);
    smp_user_scan(k);
}
static const uint32_t POS_A[4] = {0, 1000, 2500, 4000}, POS_B[3] = {200, 3000, 7000};
static int slices_are(uint32_t k, uint32_t n, uint32_t end, const uint32_t *pos)
{
    const slc_man_t *m = slc_man_of(slc_get(k + 1u));
    return n ? m && m->n == n && m->end == end && !memcmp(m->pos, pos, n * 4u) : !m;
}
/* the SLICE state of the three slots: for a snapshot */
static void slot_slices(uint32_t k, slc_man_t *o)
{
    const slc_man_t *m = slc_man_of(slc_get(k + 1u));
    memset(o, 0, sizeof *o);
    if (m) *o = *m;
}
static void fix_rec(slc_rec_t *r) { r->rcrc = st_crc32(r, sizeof *r - 4u); }
/* the object in o as the device would send it now */
static uint32_t slc_object(uint8_t *o)
{
    uint32_t len = 0, crc = 0;
    int found;
    if (list1(21, &len, &crc, &found) || !found) return 0xFFFFFFFFu;
    if (len && get_all(21, len, o)) return 0xFFFFFFFEu;
    return len;
}

static int slice_tests(void)
{
    int bad = 0, ok;
    static uint8_t obj[sizeof(slc_bk_t)] __attribute__((aligned(4))), m[sizeof(slc_bk_t)] __attribute__((aligned(4))), snap[0x100000];
    slc_bk_t *o = (slc_bk_t *)(void *)obj, *x = (slc_bk_t *)(void *)m;
    uint32_t len = 0, crc = 0, e0;
    int found;
    slc_man_t keep0, keep2;

    if ((uintptr_t)nor < (uintptr_t)SMP_DATA || (uintptr_t)nor - (uintptr_t)SMP_DATA > 0xF0000000u) {
        printf("backup: the flash image must lie above SMP_DATA within 4 GiB (32-bit offsets)\n");
        return 1;
    }
    reset();
    slc_store_boot();                                      /* (persist_boot: the scans read the records) */
    make_sample(0, 12000, 1);
    make_sample(2, 9000, 2);
    ok = usr_nz[0] && usr_nz[2] && !usr_nz[1] && slc_get(1) && slc_get(3) && slc_rec_room(0) && slc_rec_room(2);
    bad += check("setup: samples in USR1 and USR3, scanned", ok);
    ok = list1(21, &len, &crc, &found) == 0 && found && !len && !crc;
    bad += check("LIST 1: samples without slices: id 21 is 0 bytes", ok);

    ok = slc_man_restore(0, 4, 5000, POS_A) == 0 && slc_man_restore(2, 3, 0, POS_B) == 0 && slc_store_write(0) == 3 &&
         slc_store_write(2) == 3;
    bad += check("setup: MAN slices on USR1 (4, end 5000) and USR3 (3), their records stored", ok);
    len = slc_object(obj);
    ok = len == sizeof(slc_bk_t) && len == 472u && o->magic == SLC_BK_MAGIC && o->ver == 1 && o->rsize == 152u &&
         o->n == 3u && o->r[0].n == 4u && o->r[0].end == 5000u && o->r[1].n == 0 && o->r[1].len == 0 && o->r[2].n == 3u &&
         !memcmp(o->r[0].pos, POS_A, sizeof POS_A) && o->r[0].rcrc == st_crc32(&o->r[0], 148u);
    ok &= list1(21, &len, &crc, &found) == 0 && crc == st_crc32(obj, 472u);
    bad += check("LIST 1 / GET: id 21 is 472 bytes: header SLB1, the three records (slot 2 empty), CRC as listed", ok);
    ok = !memcmp(&o->r[0], nor + SMP_USER_BASE + SLC_REC_OFF, sizeof(slc_rec_t)) &&
         !memcmp(&o->r[2], nor + SMP_USER_BASE + 2u * SMP_USER_SIZE + SLC_REC_OFF, sizeof(slc_rec_t));
    bad += check("  .. the records are those stored in the slots' last sectors", ok);

    /* the slices are lost (a new device: the samples restored, the last sectors erased): PUT brings them back */
    slot_slices(0, &keep0);
    slot_slices(2, &keep2);
    memset(nor + SMP_USER_BASE + SLC_REC_OFF, 0xFF, 0x1000u);
    memset(nor + SMP_USER_BASE + 2u * SMP_USER_SIZE + SLC_REC_OFF, 0xFF, 0x1000u);
    smp_user_scan(0);
    smp_user_scan(2);
    ok = slices_are(0, 0, 0, 0) && slices_are(2, 0, 0, 0) && !slc_object(m);
    ok &= put_all(21, obj, 472u, crc) == 0;
    bad += check("PUT id 21 after the samples are back: rc 0", ok);
    ok = slices_are(0, 4, 5000, POS_A) && slices_are(2, 3, 0, POS_B);
    {
        slc_man_t g0, g2;
        slot_slices(0, &g0);
        slot_slices(2, &g2);
        ok &= !memcmp(&g0, &keep0, sizeof g0) && !memcmp(&g2, &keep2, sizeof g2);   /* (starts, end and decoder states) */
    }
    bad += check("  .. the slices are in use again, starts, end and decoder states as before", ok);
    ok = !memcmp(&o->r[0], nor + SMP_USER_BASE + SLC_REC_OFF, sizeof(slc_rec_t)) &&
         !memcmp(&o->r[2], nor + SMP_USER_BASE + 2u * SMP_USER_SIZE + SLC_REC_OFF, sizeof(slc_rec_t));
    smp_user_scan(0);
    smp_user_scan(2);
    ok &= slices_are(0, 4, 5000, POS_A) && slices_are(2, 3, 0, POS_B);
    bad += check("  .. and in the slots' last sectors: a slot scan (a power-on) finds them", ok);
    ok = slc_object(m) == 472u && !memcmp(m, obj, 472u);
    bad += check("  .. a new LIST / GET gives the archive's object byte for byte (a full round trip)", ok);
    memcpy(snap, nor, sizeof nor);
    e0 = erases;
    ok = put_all(21, obj, 472u, crc) == 0 && erases == e0 && !memcmp(snap, nor, sizeof nor);
    bad += check("the same object again writes nothing (records unchanged: no erase)", ok);

    /* empty object / empty records change nothing */
    ok = put_all(21, 0, 0, st_crc32(0, 0)) == 0 && erases == e0 && slices_are(0, 4, 5000, POS_A);
    bad += check("an empty id 21 is taken and ignored (rc 0): no slice is deleted", ok);
    memcpy(m, obj, 472u);
    memset(&x->r[0], 0, sizeof x->r[0]);
    x->r[0].magic = SLC_REC_MAGIC;
    fix_rec(&x->r[0]);                                     /* slot 1: no slices in the archive */
    x->r[2].pos[1] += 10u;                                 /* slot 3: others (valid) */
    fix_rec(&x->r[2]);
    ok = put_all(21, m, 472u, st_crc32(m, 472u)) == 0 && slices_are(0, 4, 5000, POS_A) &&
         slices_are(2, 3, 0, (const uint32_t[]){200, 3010, 7000});
    bad += check("an empty record leaves that slot's slices; a record with slices replaces them", ok);
    ok = put_all(21, obj, 472u, crc) == 0 && slices_are(2, 3, 0, POS_B);
    bad += check("  .. and the archive's object puts the first ones back", ok);

    /* the sample must be there: nothing is applied or written */
    memset(nor + SMP_USER_BASE + 2u * SMP_USER_SIZE, 0xFF, 0x1000u);   /* USR3's header sector erased (SMP_BEGIN) */
    smp_user_scan(2);
    memcpy(m, obj, 472u);
    x->r[0].pos[1] = 1100;                                 /* (slot 1: a change that would be applied) */
    fix_rec(&x->r[0]);
    memcpy(snap, nor, sizeof nor);
    e0 = erases;
    ok = !usr_nz[2] && put_all(21, m, 472u, st_crc32(m, 472u)) == 2u && erases == e0 && !memcmp(snap, nor, sizeof nor) &&
         slices_are(0, 4, 5000, POS_A);
    bad += check("a record whose slot has no sample yet: refused (2), no record of the object is applied or written", ok);
    make_sample(2, 9000, 7);                               /* another sample in USR3 */
    memcpy(snap, nor, sizeof nor);
    ok = put_all(21, obj, 472u, crc) == 2u && erases == e0 && !memcmp(snap, nor, sizeof nor) && slices_are(0, 4, 5000, POS_A);
    bad += check("a record for another sample (data CRC differs): refused (2), nothing written", ok);
    make_sample(2, 9000, 2);                               /* the sample is back */
    ok = put_all(21, obj, 472u, crc) == 0 && slices_are(2, 3, 0, POS_B);
    bad += check("  .. with the same sample restored again the object is taken", ok);

    /* malformed objects: all refused (2), nothing written */
    memcpy(snap, nor, sizeof nor);
    e0 = erases;
#define SREFUSED(what, stmt) do { memcpy(m, obj, 472u); stmt; \
        ok = put_all(21, m, 472u, st_crc32(m, 472u)) == 2u && erases == e0 && !memcmp(snap, nor, sizeof nor) && \
             slices_are(0, 4, 5000, POS_A); \
        bad += check(what, ok); } while (0)
    SREFUSED("id 21 with another magic is refused (2)", x->magic ^= 1);
    SREFUSED("id 21 of a newer version (ver 2) is refused (2)", x->ver = 2);
    SREFUSED("id 21 with another record size is refused (2)", x->rsize = 156);
    SREFUSED("id 21 with 2 records is refused (2)", x->n = 2);
    SREFUSED("id 21 with the reserved word set is refused (2)", x->rsv = 1);
    SREFUSED("a record with another magic is refused (2)", (x->r[0].magic ^= 1, fix_rec(&x->r[0])));
    SREFUSED("a record whose own CRC fails is refused (2)", x->r[0].pos[2] ^= 1);
    SREFUSED("a record with 33 slices is refused (2)", (x->r[0].n = 33, fix_rec(&x->r[0])));
    SREFUSED("slices out of order are refused (2)", (x->r[0].pos[2] = 900, fix_rec(&x->r[0])));
    SREFUSED("slices closer than SLC_MIN are refused (2)", (x->r[0].pos[1] = 30, fix_rec(&x->r[0])));
    SREFUSED("an end past the material is refused (2)", (x->r[0].end = 12001, fix_rec(&x->r[0])));
    SREFUSED("a start past the end is refused (2)", (x->r[0].pos[3] = 5000, fix_rec(&x->r[0])));
    SREFUSED("a start after the last slice that is not 0 is refused (2)", (x->r[0].pos[7] = 1, fix_rec(&x->r[0])));
    SREFUSED("an empty record with a length set is refused (2)", (x->r[1].len = 5, fix_rec(&x->r[1])));
    SREFUSED("slices of another length of material are refused (2)", (x->r[0].len += 2, fix_rec(&x->r[0])));
    ok = put_begin(21, 471u, 0) == 1u && put_begin(21, 473u, 0) == 1u && put_begin(21, 3840u, 0) == 1u;
    bad += check("id 21 of another length is refused at begin (1)", ok);
    memcpy(m, obj, 472u);
    ok = put_all(21, m, 472u, st_crc32(m, 472u) ^ 1u) == 2u && erases == e0 && !memcmp(snap, nor, sizeof nor);
    bad += check("id 21 with a wrong CRC is refused at commit (2), nothing written", ok);

    /* a sample that reaches the last sector: no room for a record, none in the backup, none accepted */
    make_sample(1, 156000u, 3);
    ok = usr_nz[1] && !slc_rec_room(1) && slc_man_restore(1, 2, 0, (const uint32_t[]){0, 5000}) == 0;
    ok &= slc_object(m) == 472u && x->r[1].n == 0;
    bad += check("slices on a sample that leaves no room (TOO LONG TO SAVE): not in the object (they die with the power)", ok);
    memcpy(m, obj, 472u);
    x->r[1] = o->r[0];
    x->r[1].len = slc_get(2)->len;
    x->r[1].crc = ((const smp_user_hdr_t *)smp_user_xip(1))->crc;
    fix_rec(&x->r[1]);
    memcpy(snap, nor, sizeof nor);
    e0 = erases;
    ok = put_all(21, m, 472u, st_crc32(m, 472u)) == 2u && erases == e0 && !memcmp(snap, nor, sizeof nor);
    bad += check("a record for a sample that leaves no room is refused (2): its last sector is the sample's", ok);

    /* flash errors */
    make_sample(1, 100, 4);
    memset(nor + SMP_USER_BASE + SLC_REC_OFF, 0xFF, 0x1000u);
    smp_user_scan(0);
    erase_error = 1;
    ok = put_all(21, obj, 472u, crc) == 4u;
    erase_error = 0;
    bad += check("a flash error (the record's erase): rc 4", ok);
    flash_ok = 0;
    ok = put_all(21, obj, 472u, crc) == 4u;
    flash_ok = 1;
    bad += check("no flash: rc 4", ok);
    ok = put_all(21, obj, 472u, crc) == 0 && slices_are(0, 4, 5000, POS_A);
    bad += check("  .. and with flash again the object is taken", ok);

    /* power cuts: the sample is never touched, the slices are the old, the new, or none */
    {
        static uint8_t base[3u * 0x14000u], objN[472] __attribute__((aligned(4)));
        slc_bk_t *n = (slc_bk_t *)(void *)objN;
        uint32_t i, total, so = 0, sn = 0, sz = 0, other = 0, bytes_ok = 1;
        make_sample(1, 100, 4);                            /* (a small one, the cut points are the two records') */
        memset(nor + SMP_USER_BASE + SLC_REC_OFF, 0xFF, 0x1000u);
        smp_user_scan(0);
        slc_man_restore(0, 4, 5000, POS_A);
        slc_man_restore(2, 3, 0, POS_B);
        slc_store_write(0);
        slc_store_write(2);
        slc_object(m);
        memcpy(objN, m, 472u);                             /* N: slot 1 gets 3 slices, slot 3 gets 4 */
        n->r[0].n = 3;
        memset(n->r[0].pos, 0, sizeof n->r[0].pos);
        memcpy(n->r[0].pos, POS_B, sizeof POS_B);
        n->r[0].end = 0;
        fix_rec(&n->r[0]);
        n->r[2].n = 4;
        n->r[2].end = 5000;
        memset(n->r[2].pos, 0, sizeof n->r[2].pos);
        memcpy(n->r[2].pos, POS_A, sizeof POS_A);
        fix_rec(&n->r[2]);
        memcpy(base, nor + SMP_USER_BASE, sizeof base);
        progs = 0;
        put_all(21, objN, 472u, st_crc32(objN, 472u));
        total = progs;
        ok = slices_are(0, 3, 0, POS_B) && slices_are(2, 4, 5000, POS_A);
        bad += check("setup for power cuts: object N (other slices on USR1 and USR3) restores", ok);
        for (i = 0; i < total + 2u; i++) {
            uint32_t j;
            memcpy(nor + SMP_USER_BASE, base, sizeof base);
            for (j = 0; j < 3u; j++) smp_user_scan(j);     /* (the old slices, from the flash) */
            dead = 0;
            if (i < total) cut_bytes = (long)i;
            else cut_erase = (long)(i - total);
            put_all(21, objN, 472u, st_crc32(objN, 472u));
            dead = 0;
            cut_bytes = cut_erase = -1;
            for (j = 0; j < 3u; j++) {                      /* the next power-on: the RAM lost, the slots scanned */
                slc_man[j][0].n = slc_man[j][1].n = 0;
                smp_user_scan(j);
                if (memcmp(nor + SMP_USER_BASE + j * SMP_USER_SIZE, base + j * SMP_USER_SIZE, SLC_REC_OFF)) bytes_ok = 0;
            }
            /* USR1 had POS_A (4) and gets POS_B (3); USR3 had POS_B (3) and gets POS_A (4): each old, new or none */
            if (slices_are(0, 4, 5000, POS_A)) so++;
            else if (slices_are(0, 3, 0, POS_B)) sn++;
            else if (slices_are(0, 0, 0, 0)) sz++;
            else other++;
            if (slices_are(2, 3, 0, POS_B)) so++;
            else if (slices_are(2, 4, 5000, POS_A)) sn++;
            else if (slices_are(2, 0, 0, 0)) sz++;
            else other++;
            if (!slices_are(1, 0, 0, 0)) other++;          /* (USR2 has no slices and gets none) */
        }
        printf("backup:   %u cut points (bytes + 2 erases), two slots each: %u old, %u new, %u without slices, %u anything else\n",
               (unsigned)total, (unsigned)so, (unsigned)sn, (unsigned)sz, (unsigned)other);
        bad += check("a power cut anywhere in a restore: each slot has its old slices, the new, or none; never a half record",
                     !other && so && sn && sz && so + sn + sz == 2u * (total + 2u));
        bad += check("  .. and no sample byte (header, data) of any slot changes", bytes_ok);
    }
    return bad;
}

#endif /* FELUCCA_FLASH && FELUCCA_SLICE */

static int ext_tests(void)
{
    int bad = plain_list_tests() + bank_tests();
#if FELUCCA_SLICE
    bad += slice_tests();
#endif
    return bad;
}

int main(void)
{
    int bad = 0;
    uint32_t len = 0, crc = 0, before;
    static project_store_t st;
    static project_v6_t v6;
    persist_t ps;

    reset();
    trk[0].step[0] = (step_t){{60}, 1, ST_NOTE, 0, 96, 0, 0};
    bad += check("LIST captures the runtime: 13 objects (id 8 empty, id 9 the FM6 patches), runtime 3840 B (FUN10)",
                 list(0, &len, &crc) == 0 && rep[2] == 13u && len == sizeof(project_store_t) && len == 3840u &&
                 crc == st_crc32(ED_BK_RAW, len));
    bad += check("an empty project slot lists as length 0", list(2, &len, &crc) == 0 && len == 0);
    bad += check("GET of the runtime copy", get(0, 0, 64) == 0);
    project_save(0);
    bad += check("a project save after LIST reused the staging RAM: GET of the runtime is stale (5)",
                 get(0, 0, 64) == 5u);
    bad += check("a new LIST makes it readable again", list(0, &len, &crc) == 0 && get(0, 0, 64) == 0);
    usb.resets++;
    bad += check("a USB reset after LIST: GET is stale (5)", get(2, 0, 16) == 5u);

    /* settings */
    reset();
    memset(&ps, 0, sizeof ps);
    settings_export(&ps);
    ps.lowcut = 2;                                       /* SPEAKER BASS+ */
    ps.palette = palette_to_stored(6);
    bad += check("settings with SPEAKER BASS+ restore", put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 0 &&
                 settings.lowcut == 2u && fx_lowcut == 2u && settings.palette == 6u);
    ps.palette = 13;                                     /* an older backup: its PAPER (old id 13) */
    bad += check("settings of an older backup restore with the palette migrated",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 0 && settings.palette == 6u);
    ps.palette = palette_to_stored(6);
    before = erases;
    ps.lowcut = 3;
    bad += check("settings with an unknown SPEAKER value are refused, nothing written",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 2u && erases == before && settings.lowcut == 2u);
    ps.lowcut = 0;
    ps.bold = hold_to_stored(0, 3);                      /* HOLD 0.6 s */
    bad += check("settings with HOLD 0.6 s restore",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 0 && HOLD_MS[settings_hold] == 600u);
    ps.bold = 1;                                         /* an older backup (its font weight): HOLD 0.4 s */
    bad += check("settings of an older backup restore with HOLD 0.4 s",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 0 && HOLD_MS[settings_hold] == 400u);
    before = erases;
    ps.bold = HOLD_TAG + 7u;
    bad += check("settings with an unknown HOLD value are refused, nothing written",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 2u && erases == before);
    ps.bold = 0;
    ps.zoom = LEDS_TAG | LEDS_INV;                       /* LEDS INV */
    bad += check("settings with LEDS INV restore",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 0 && settings_leds == LEDS_INV);
    ps.zoom = 1;                                         /* an older backup (its large readout): LEDS DIM */
    bad += check("settings of an older backup restore with LEDS DIM",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 0 && settings_leds == LEDS_DIM);
    before = erases;
    ps.zoom = LEDS_TAG | LEDS_DIM_LO;                    /* LEDS DIM LO, OFF (appended) */
    bad += check("settings with LEDS DIM LO restore",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 0 && settings_leds == LEDS_DIM_LO);
    ps.zoom = LEDS_TAG | LEDS_OFF;
    bad += check("settings with LEDS OFF restore",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 0 && settings_leds == LEDS_OFF);
    before = erases;
    ps.zoom = LEDS_TAG + 4u;
    bad += check("settings with an unknown LEDS value are refused, nothing written",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps)) == 2u && erases == before);
    ps.zoom = 0;
    bad += check("a wrong CRC is refused before any write",
                 put_all(1, &ps, sizeof ps, st_crc32(&ps, sizeof ps) ^ 1u) == 2u && erases == before);

    /* malformed requests */
    bad += check("an unknown object id is refused", put_begin(8, sizeof ps, 0) == 1u);
    bad += check("a project of the wrong length is refused", put_begin(2, sizeof(project_store_t) - 4u, 0) == 1u);
    bad += check("settings of the wrong length are refused", put_begin(1, sizeof ps + 4u, 0) == 1u);
    bad += check("a chunk without a begin is refused (5)", (ed_bk_put = 0, put_chunk(1, 0, (const uint8_t *)&ps, 16)) == 5u);
    put_begin(1, sizeof ps, st_crc32(&ps, sizeof ps));
    bad += check("a chunk at the wrong offset is refused", put_chunk(1, 16, (const uint8_t *)&ps, 16) == 1u);
    bad += check("a chunk for another object is refused (5)", put_chunk(2, 0, (const uint8_t *)&ps, 16) == 5u);
    {
        uint32_t off = 0, step = sizeof ps - 8u;
        put_begin(1, sizeof ps, st_crc32(&ps, sizeof ps));
        for (; off + 256u <= step; off += 256u)
            put_chunk(1, off, (const uint8_t *)&ps + off, 256);
        if (off < step) put_chunk(1, off, (const uint8_t *)&ps + off, step - off);
        bad += check("a chunk past the length is refused", put_chunk(1, step, (const uint8_t *)&ps, 16) == 1u);
    }
    bad += check("commit before all bytes arrived is refused", put_end(1, 2) == 2u && erases == before);
    put_begin(1, sizeof ps, st_crc32(&ps, sizeof ps));
    put_chunk(1, 0, (const uint8_t *)&ps, 64);
    usb.resets++;
    bad += check("a USB reset during PUT ends it (5)", put_chunk(1, 64, (const uint8_t *)&ps + 64, 64) == 5u);
    put_begin(1, sizeof ps, st_crc32(&ps, sizeof ps));
    fm1_ms += 16000u;
    bad += check("16 s without a chunk ends the PUT (5)", put_chunk(1, 0, (const uint8_t *)&ps, 64) == 5u);
    put_begin(2, sizeof st, 0);
    put_chunk(2, 0, (const uint8_t *)&ps, 64);
    project_save(1);
    bad += check("a project save during PUT (the staging RAM) ends it (5)",
                 put_chunk(2, 64, (const uint8_t *)&ps, 64) == 5u);
    transport_req = 1;
    bad += check("PUT while starting PLAY is refused (3)", put_begin(1, sizeof ps, 0) == 3u);
    transport_req = 0;

    /* projects */
    reset();
    trk[1].step[3] = (step_t){{64}, 1, ST_NOTE, 0, 96, 0, 0};
    project_capture(&proj_scratch);
    proj_pack(&st, &proj_scratch);
    bad += check("a FUN10 project restores into slot 3 (flash and RAM)",
                 put_all(4, &st, sizeof st, st_crc32(&st, sizeof st)) == 0 && project_used(2) &&
                 !memcmp(&proj_slot[2], &st, sizeof st) && st_load(OBJ_PROJECT0 + 2, &proj_wire, sizeof proj_wire) == (int)sizeof st);
    {   /* FUN8 of 1.0.x (3584 bytes, 91 parameters) and FUN9 of 1.1 (3648, 99): restore as FUN10, E0 at P_E0, lanes
         * 100 %, the four 1.2 parameters at their defaults; a FUN9 with 64 motion records keeps them all */
        static uint8_t v8[3584], v9[3648];
        uint32_t k, ok;
        trk[2].p[P_E0] = 2;
        trk[2].p[P_LN3] = 90;
        project_capture(&proj_scratch);
        proj_scratch.t[2].p[P_LN3] = 127;              /* (FUN8 had no lane levels) */
        bad += check("a FUN8 project (1.0.x) restores as FUN10 into slot 2, E0 at P_E0, lane levels 100 %",
                     old_pack(v8, &proj_scratch, OLD_FUN8, 91u) == sizeof v8 &&
                     put_all(3, v8, sizeof v8, st_crc32(v8, sizeof v8)) == 0 && ((uint32_t *)proj_slot[1].raw)[0] == PROJ_MAGIC &&
                     proj_import(&proj_scratch, &proj_slot[1], sizeof st) && proj_scratch.t[2].p[P_E0] == 2 &&
                     proj_scratch.t[2].p[P_LN3] == 127 && proj_scratch.t[1].step[3].note[0] == 64u);
        project_capture(&proj_scratch);
        for (k = 0; k < 64u; k++)
            proj_scratch.motion.event[k] = (motion_event_t){(uint8_t)(1u << 6 | k), P_REV, (int8_t)k};
        proj_scratch.motion.count = 64;
        proj_scratch.motion.on = 2;
        ok = old_pack(v9, &proj_scratch, OLD_FUN9, 99u) == sizeof v9 &&
             put_all(4, v9, sizeof v9, st_crc32(v9, sizeof v9)) == 0 && ((uint32_t *)proj_slot[2].raw)[0] == PROJ_MAGIC &&
             proj_import(&proj_scratch, &proj_slot[2], sizeof st) && proj_scratch.t[2].p[P_E0] == 2 &&
             proj_scratch.t[2].p[P_LN3] == 90 && proj_scratch.motion.count == 64u && proj_scratch.motion.event[63].value == 63 &&
             proj_scratch.t[0].p[P_LSYNC] == 0 && proj_scratch.t[0].p[P_LTRIG] == 0 && proj_scratch.t[0].p[P_LPOL] == 0 &&
             proj_scratch.t[0].p[P_SQNT] == 1;
        bad += check("a FUN9 project (1.1) restores as FUN10 into slot 3: its 64 records, the lanes, LFO 2 / QUANTIZE defaults", ok);
    }
    memset(&v6, 0, sizeof v6);                           /* FUN6: 69 parameters, steps out of range */
    v6.magic = PROJ_MAGIC_V6;
    v6.size = sizeof v6;
    for (uint32_t i = 0; i < G_COUNT; i++)
        v6.g[i] = GP[i].def;
    for (uint32_t i = 0; i < NTRK; i++)
        v6.t[i].engine = trk[i].engine;
    v6.t[0].step[0] = (step10_t){{255, 72}, 9, 7, 0, 96, 0, 0};
    v6.t[0].p[61] = 3;                                   /* old E0 */
    memset(&v6.chain, 0, sizeof v6.chain);
    v6.sum = proj_hash(&v6, sizeof v6 - 4u);
    bad += check("a FUN6 project restores as FUN10, bounded, its E0 at P_E0",
                 put_all(5, &v6, sizeof v6, st_crc32(&v6, sizeof v6)) == 0 && ((uint32_t *)proj_slot[3].raw)[0] == PROJ_MAGIC &&
                 proj_import(&proj_scratch, &proj_slot[3], sizeof st) && proj_scratch.t[0].step[0].n == 4u &&
                 proj_scratch.t[0].step[0].note[0] == 127u && proj_scratch.t[0].p[P_E0] ==
                 clamp(3, param_desc_of(trk[0].engine, P_E0)->min, param_desc_of(trk[0].engine, P_E0)->max));
    {   /* 1.0.3: the FM6 patch bank (id 8) is retired; an older archive's bank moves into its user presets (ids 6, 7
         * restored first), the user presets' patches are id 9 */
        static up_bank_t ub;
        static fm6_bank_t bk;
        static upf_t got;
        uint8_t pk[FM6_PACKED];
        static const int16_t SL[5] = {FM6_NFACTORY + 2, 1, FM6_NFACTORY + 4, FM6_NFACTORY + 2, FM6_NFACTORY + 2};
        memset(&ub, 0, sizeof ub);
        ub.magic = UP_BANK_MAGIC; ub.rsize = sizeof(up_rec_t); ub.nslot = UP_PER_BANK;
        for (uint32_t k = 0; k < 5u; k++) {             /* slots 1..5: B3, F2, B5 (empty), B3 on DRUM, B3 */
            up_rec_t *r = &ub.r[k];
            uint32_t e = k == 3u ? ENGI_DRUM : ENGI_FM6;
            r->used = UP_USED; r->ver = UP_VER; r->engine = (uint8_t)e; r->np = P_COUNT;
            r->name[0] = (char)('A' + k);
            for (uint32_t i = 0; i < P_COUNT; i++) up_set_value(r, i, param_desc_of(e, i)->def);
            up_set_value(r, P_E7, SL[k]);                 /* (the raw stored value: B slots as 1.0.2 wrote them) */
        }
        ub.r[4].name[1] = 'X';
        up_set_value(&ub.r[4], P_E0, 3);                 /* (another sound than slot 1's) */
        memset(&bk, 0, sizeof bk);
        bk.magic = FM6_BANK_MAGIC; bk.ver = 1; bk.nslot = FM6_BANK_N; bk.used = 1u << 2;
        memcpy(bk.v[2], FM6_FACTORY[5], FM6_PACKED);
        memcpy(bk.v[2] + 118, "BANK B3   ", 10);
        upf_empty();
        bad += check("the user presets of an old archive (id 6) restore", put_all(6, &ub, sizeof ub, st_crc32(&ub, sizeof ub)) == 0);
        bad += check("an old archive's FM6 bank (id 8) is taken (0)", put_all(8, &bk, sizeof bk, st_crc32(&bk, sizeof bk)) == 0);
        bad += check("  .. its B3 patch is now the B3 presets' own (slots 1 and 5)",
                     !upf_get(0, pk) && !memcmp(pk + 118, "BANK B3   ", 10) && !upf_get(4, pk) && !memcmp(pk + 118, "BANK B3", 7));
        bad += check("  .. an F slot, an empty B slot and a DRUM sound get none (factory / init / no patch, as before)",
                     upf_get(1, pk) && upf_get(2, pk) && upf_get(3, pk));
        bad += check("  .. written to flash (the user presets' FM6 patches)",
                     st_load(OBJ_UPFM6, &got, sizeof got) == (int)sizeof got && !memcmp(&got, &upf, sizeof got));
        up_load(0);
        bad += check("  .. B3 preset keeps its patch; installed FM6 adopts OWN, unavailable SLOT stays", TSEL->eng_req == ENGI_FM6 &&
                     !memcmp(fm6_patch[song.sel] + FP_NAME, "BANK B3", 7) &&
                     TSEL->p[P_E7] == (eng_ok(ENGI_FM6) ? (int16_t)FM6_OWN : SL[0]));
        up_load(1);
        bad += check("  .. the F2 preset loads the factory patch, SLOT F2", TSEL->p[P_E7] == 1 &&
                     !memcmp(fm6_patch[song.sel] + FP_NAME, FM6_FACTORY[1] + 118, 10));
        bad += check("a restore of id 8 twice moves nothing more (idempotent)",
                     put_all(8, &bk, sizeof bk, st_crc32(&bk, sizeof bk)) == 0 && !memcmp(&got, &upf, sizeof got));
        bad += check("an empty id 8 (a 1.0.3 archive) is taken and ignored", put_all(8, 0, 0, st_crc32(0, 0)) == 0 &&
                     !memcmp(&got, &upf, sizeof got));
        bk.v[3][0] = 200;
        bad += check("an FM6 bank with a byte above 127 is refused (2)", put_all(8, &bk, sizeof bk, st_crc32(&bk, sizeof bk)) == 2u);
        bad += check("id 8 lists empty, id 9 with the patches' length", list(8, &len, &crc) == 0 && len == 0 &&
                     list(9, &len, &crc) == 0 && len == sizeof(upf_t) && crc == st_crc32(&upf, sizeof upf));
        memcpy(&got, &upf, sizeof got);
        upf_empty();
        bad += check("id 9 restores the user presets' FM6 patches (flash and RAM)",
                     put_all(9, &got, sizeof got, st_crc32(&got, sizeof got)) == 0 && !memcmp(&got, &upf, sizeof got) &&
                     !upf_get(0, pk) && !memcmp(pk + 118, "BANK B3", 7));
        got.magic ^= 1;
        bad += check("an id 9 of another layout is refused (2), the patches kept",
                     put_all(9, &got, sizeof got, st_crc32(&got, sizeof got)) == 2u && !upf_get(0, pk));
        bad += check("an id 9 of the wrong size is refused at begin (1)", put_begin(9, sizeof got - 4u, 0) == 1u);
        bad += check("an id 10 is refused (1)", put_begin(10, 0, 0) == 1u);
    }
    memcpy(&st, &proj_slot[2], sizeof st);
    erase_error = 1;
    proj_slot[2].raw[100] ^= 1;                          /* (marks the RAM copy, to see it is kept) */
    memcpy(&v6, &proj_slot[2], sizeof v6);
    bad += check("a flash error on commit (4) keeps the slot's RAM copy",
                 put_all(4, &st, sizeof st, st_crc32(&st, sizeof st)) == 4u && !memcmp(&proj_slot[2], &v6, sizeof v6));
    erase_error = 0;
    bad += check("an empty project object clears the slot", put_all(4, 0, 0, st_crc32(0, 0)) == 0 && !project_used(2));
    st.raw[200] ^= 1;                                    /* hash no longer matches */
    bad += check("a project whose own hash fails is refused", put_all(4, &st, sizeof st, st_crc32(&st, sizeof st)) == 2u);

    /* the runtime */
    reset();
    trk[2].step[5] = (step_t){{67}, 1, ST_NOTE, 0, 96, 0, 0};
    trk[2].p[P_LEVEL] = 77;
    project_capture(&proj_scratch);
    proj_pack(&st, &proj_scratch);
    host_tracks_init();
    bad += check("the runtime object restores the tracks",
                 put_all(0, &st, sizeof st, st_crc32(&st, sizeof st)) == 0 && trk[2].step[5].note[0] == 67u &&
                 trk[2].p[P_LEVEL] == 77);

    /* user preset banks: unknown record versions are kept as bytes */
    reset();
    {
        static up_bank_t b;
        memset(&b, 0, sizeof b);
        b.magic = UP_BANK_MAGIC;
        b.rsize = sizeof(up_rec_t);
        b.nslot = UP_PER_BANK;
        b.r[4].used = UP_USED;
        b.r[4].ver = 99;                                 /* a future record */
        memcpy(b.r[4].name, "Future", 7);
        b.r[4].p[0] = 55;
        bad += check("a bank with a future record version restores byte for byte",
                     put_all(6, &b, sizeof b, st_crc32(&b, sizeof b)) == 0 &&
                     st_load(OBJ_UPRESET0, &proj_wire, sizeof proj_wire) == (int)sizeof b &&
                     !memcmp(&proj_wire, &b, sizeof b));
        b.nslot = 3;
        bad += check("a bank with the wrong slot count is refused", put_all(7, &b, sizeof b, st_crc32(&b, sizeof b)) == 2u);
    }
    bad += ext_tests();
    printf("backup test %s\n", bad ? "FAILED" : "passed");
    return bad != 0;
}
