/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Complete musical archive: no raw addresses are accepted. Small objects are staged
 * in main-loop RAM and fully validated before the existing A/B commit path writes.
 * Sample restore uses SMP_BEGIN/WRITE/END and its existing CRC/header-last commit.
 * A disconnected sample restore can lose that sample; the exported file is retained.
 * Id 8 (the FM6 patch bank of 1.0..1.0.2) is listed empty since 1.0.3; a PUT of it from an older archive moves its
 * patches into the user presets restored before it (ids 6, 7), as the first boot after the update does (up_fm6.c).
 * Id 9 is the user presets' FM6 patches (up_fm6.c), appended in 1.0.3.
 * Ids 20 and 21 (#321) are listed only for "BACKUP_LIST 1" (INFO 58 01 caps; the plain LIST stays the 13 objects of
 * 1.0.3, so editors that count them keep working):
 *   20  the FM6 voice bank (fm6_vbank.c) as stored at 0xE7000: the bank header (FM6V, ver 1, used mask, name) then
 *       32 voices of 112 bytes, 3616 bytes; 0 = no bank. Restore goes through the same BEGIN / WRITE / END path as
 *       the editor's own bank transfer (fvb_begin / fvb_write / fvb_end): staged in the autosave's older sector, the
 *       commit record last, then copied to 0xE7000, so a power cut leaves the old bank or the new one; an autosave
 *       cannot interleave (one main-loop call). An empty object changes nothing: there is no way to delete a bank.
 *   21  the SLICE records (slice_store.c) of the three user slots, 472 bytes; 0 = no slot has slices. Restore needs
 *       the samples (ids 32..34) in place first. An empty object or record changes nothing.
 */
#include "store_kind.h"
#define ED_BK_ID_FVB 20u
#define ED_BK_ID_SLC 21u
#if FELUCCA_FLASH
#define ED_BK_HAS_FVB 1u
#else
#define ED_BK_HAS_FVB 0u
#endif
#if FELUCCA_FLASH && FELUCCA_SLICE
#define ED_BK_HAS_SLC 1u
_Static_assert(sizeof(slc_bk_t) <= sizeof ed_smp_buf, "the SLICE backup object is built in ed_smp_buf");
#else
#define ED_BK_HAS_SLC 0u
#endif
#define ED_BK_XN (ED_BK_HAS_FVB + ED_BK_HAS_SLC)    /* the objects of "LIST 1" after the 13 (the SK_EXT rows) */
#define ED_BK_XCAPS (ED_BK_XN ? 1u | ED_BK_HAS_FVB << 1 | ED_BK_HAS_SLC << 2 : 0u)   /* INFO 58 01: bit 0 LIST 1, 1 id 20, 2 id 21 */
#define ED_BK_MAX ((uint32_t)sizeof proj_wire_u.raw)
#define ED_BK_RAW (proj_wire_u.raw)  /* reuse the existing serialized main-loop scratch */
_Static_assert(sizeof proj_wire_u.raw >= sizeof(upf_t) && sizeof proj_wire_u.raw >= sizeof(fm6_bank_t) &&
               sizeof proj_wire_u.raw >= sizeof(persist_rec_t) && sizeof proj_wire_u.raw >= FVB_LEN, "backup staging");
static persist_rec_t ed_bk_settings __attribute__((section(".pool")));   /* id 1: persist_len bytes (PER4 or PER6) */
static uint8_t ed_bk_valid, ed_bk_put, ed_bk_id, ed_bk_gen;
static uint32_t ed_bk_len, ed_bk_crc, ed_bk_pos, ed_bk_ms, ed_bk_usb;
#if FELUCCA_FLASH
/* id 20 as LIST saw it: 0 or FVB_LEN, and the bank's payload CRC. In the pool, not .bss: a .bss that shifts costs the key
 * scan ISR an instruction (a displacement past the short form; measured, tests/target_budget.py) */
static uint32_t ed_bk_vlen __attribute__((section(".pool")));
static uint32_t ed_bk_vcrc __attribute__((section(".pool")));
#endif
static void ed_bk_u32(uint32_t n) { for (uint32_t i = 0; i < 5u; i++) ed_b((n >> (i * 7u)) & 127u); }
static uint32_t ed_bk_r32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 7 | (uint32_t)p[2] << 14 | (uint32_t)p[3] << 21 | (uint32_t)p[4] << 28;
}
static void ed_bk_pack(const uint8_t *p, uint32_t n)
{
    while (n) {
        uint32_t k = n > 7u ? 7u : n, mask = 0;
        for (uint32_t i = 0; i < k; i++) mask |= (uint32_t)(p[i] >> 7) << i;
        ed_b(mask);
        for (uint32_t i = 0; i < k; i++) ed_b(p[i]);
        p += k; n -= k;
    }
}
#if FELUCCA_FLASH
/* id 20: the bank's payload bytes off.. into ed_smp_buf; 5 if the bank at 0xE7000 is no longer the one LIST saw */
static uint32_t ed_bk_fvb_fill(uint32_t off, uint32_t n)
{
    st_hdr_t h;
    if (st_read(FVB_HOME, &h, sizeof h) || h.magic != ST_MAGIC || h.type != OBJ_FM6VB || h.slot != 0 ||
        h.len != FVB_LEN || h.hcrc != st_crc32(&h, sizeof h - 4u) || h.crc != ed_bk_vcrc)
        return 5;
    return st_read(FVB_HOME + FVB_INFO + off, ed_smp_buf, n) ? 4u : 0u;
}
/* a bank object to restore (FVB_LEN bytes at o): the header as fvb_end writes it, the voices as stored; the slots of
 * the voices that are not there erased (0xFF), as in every bank this firmware wrote. 0 = whole, 2 = refused */
static int ed_bk_fvb_check(const uint8_t *o)
{
    fvb_info_t in;
    uint32_t k, i;
    memcpy(&in, o, sizeof in);
    if (in.magic != FVB_MAGIC || in.ver != 1u || in.n != FM6_NBANK || in.rsv[0] || in.rsv[1] || in.name[10] || in.name[11])
        return 2;
    for (i = 0; i < 10u; i++)
        if ((uint8_t)in.name[i] < 32u || (uint8_t)in.name[i] > 126u)
            return 2;
    for (k = 0; k < FM6_NBANK; k++)
        if (!((in.used >> k) & 1u))
            for (i = 0; i < UPF_PK; i++)
                if (o[FVB_VOICES - FVB_INFO + k * UPF_PK + i] != 0xFFu)
                    return 2;
    return 0;
}
/* a checked bank object -> flash through the editor's own transfer: the autosave's older sector erased, the voices
 * written, END (the CRC of their records) stages, commits and copies to 0xE7000. 0, 4 flash */
static uint32_t ed_bk_fvb_apply(const uint8_t *o)
{
    fvb_info_t in;
    uint8_t pk[FM6_PACKED];
    uint32_t k, c = 0xFFFFFFFFu, rc;
    memcpy(&in, o, sizeof in);
    if (!flash_ok || fvb_begin())
        return 4;
    for (k = 0; k < FM6_NBANK; k++)
        if ((in.used >> k) & 1u) {
            upf_pk_get(o + (FVB_VOICES - FVB_INFO) + k * UPF_PK, pk);
            if (fvb_write(k, pk))
                return 4;
            c = st_crc32_add(c, pk, FM6_PACKED);
            fm1_wdt_feed();
        }
    rc = fvb_end((const uint8_t *)in.name, ~c);
    return rc ? 4u : 0u;
}
#endif
static uint32_t ed_bk_capture(void)
{
    if (ed_flash_stop()) return 3;
    project_capture(&proj_scratch);
    if (!proj_encode((project_store_t *)ED_BK_RAW, &proj_scratch)) return 2;
    ed_bk_gen = ++proj_wire_gen;
#if FELUCCA_FLASH
    ed_bk_settings = persist_saved;                 /* fields absent from this build survive */
#else
    memset(&ed_bk_settings, 0, sizeof ed_bk_settings);
#endif
    settings_export_rec(&ed_bk_settings);
#if FELUCCA_FLASH
    {   /* id 20: the bank's identity for this snapshot (fvb_valid has read and checked all of it) */
        st_hdr_t h;
        ed_bk_vlen = flash_ok && !fvb_valid(FVB_HOME, 0, &h) ? FVB_LEN : 0u;
        ed_bk_vcrc = ed_bk_vlen ? h.crc : 0u;
    }
#endif
    ed_bk_put = 0; ed_bk_valid = 1; ed_bk_usb = usb.resets;
    return 0;
}
static int ed_bk_panel_valid(const panel_t *p)
{
    uint32_t b = 0, e = 0;
    if (p->magic != PANEL_MAGIC) return 0;
    for (uint32_t i = 0; i < NB; i++) {
        if (p->btn[i] >= NB || (b & (1u << p->btn[i]))) return 0;
        b |= 1u << p->btn[i];
    }
    for (uint32_t i = 0; i < NE; i++) {
        if (p->enc[i] >= NE || (e & (1u << p->enc[i])) || (p->dir[i] != 1 && p->dir[i] != -1)) return 0;
        e |= 1u << p->enc[i];
    }
    return 1;
}

/* ---- #310: the stored record kinds (store_kind.h), each with its lengths, validation, install, export and raw
 * schema state; the handlers below only iterate SK_KINDS. A check runs on the whole staged object before anything
 * is written; an install returns the reply code BACKUP_PUT's commit gives ---- */
static uint32_t sk_done(void) { sync_reload = 1; ui.force = 1; return 0; }

/* projects (backup id 0 the live music, 2..5 the slots; storage types 1..4 and the autosave, 9): any format
 * proj_decode reads, stored as FUN10 inside its ranges (project_codec.h); the decoded project stays in proj_scratch */
static uint32_t sk_proj_check(uint8_t *b, uint32_t *n)
{
    if (!*n) return 0;                              /* (a slot: erased) */
    if (!proj_decode(&proj_scratch, b, (int)*n) || !proj_encode((project_store_t *)(void *)b, &proj_scratch)) return 2;
    *n = sizeof(project_store_t);
    return 0;
}
static uint32_t sk_live_check(uint8_t *b, uint32_t *n) { return *n ? sk_proj_check(b, n) : 2u; }
static uint32_t sk_live_install(uint32_t k, const uint8_t *b, uint32_t n)
{
    (void)k; (void)b; (void)n;
    return project_restore_runtime(&proj_scratch) ? 2u : 0u;
}
static const uint8_t *sk_live_view(uint32_t k, uint32_t *n) { (void)k; *n = sizeof(project_store_t); return ED_BK_RAW; }
static uint32_t sk_slot_install(uint32_t k, const uint8_t *b, uint32_t n)
{
    memset(&proj_slot[k], 0, sizeof proj_slot[0]);
    if (proj_cur == k)
        proj_cur = PROJ_NO_SLOT;                    /* (another project there now: the music keeps its name) */
    if (n) memcpy(&proj_slot[k], b, n);
    return sk_done();
}
static const uint8_t *sk_slot_view(uint32_t k, uint32_t *n)
{
    if (project_used(k)) *n = sizeof proj_slot[0];
    return (const uint8_t *)&proj_slot[k];
}
/* the codec's own classification (project_codec.c proj_classify); a format's magic and length with a bad size word
 * or hash (PROJ_DAMAGED) is UNKNOWN here: DAMAGED is a copy whose storage CRC failed */
static uint32_t sk_proj_state(const uint8_t *b, uint32_t n)
{
    uint32_t k = proj_classify(b, n);
    return k == PROJ_CURRENT ? ED_RAW_CURRENT : k == PROJ_LEGACY ? ED_RAW_LEGACY : ED_RAW_UNKNOWN;
}

/* settings (backup id 1, type 0): PER4, or PER6 with an extension this firmware reads (#212), every field inside the
 * values this firmware stores; the record is stored as it came and imported */
static int sk_set_current(const persist_t *p, uint32_t n)
{
    return (n == sizeof *p && p->magic == PERSIST_MAGIC) || persist_ext_ok(p, (int)n);
}
static int sk_set_accepts(uint32_t n)               /* PER4, or PER4 + an extension of 1.. rows of 32 bytes */
{
    return n == sizeof(persist_t) || (n > sizeof(persist_t) + PERSIST_EXT_HDR && n <= sizeof(persist_rec_t) &&
                                      (n - sizeof(persist_t) - PERSIST_EXT_HDR) % 32u == 0);
}
static uint32_t sk_set_check(uint8_t *b, uint32_t *n)
{
    const persist_t *p = (const persist_t *)(const void *)b;
    return sk_set_current(p, *n) && palette_stored_ok(p->palette) && p->lowcut <= 2u && leds_stored_ok(p->zoom) &&
           hold_stored_ok(p->bold) && p->favorites.filter <= 1u && ed_bk_panel_valid(&p->panel) ? 0u : 2u;
}
static uint32_t sk_set_install(uint32_t k, const uint8_t *b, uint32_t n)
{
    (void)k;
    memset(&ed_bk_settings, 0, sizeof ed_bk_settings);
    memcpy(&ed_bk_settings, b, n);
    settings_import((persist_t *)(void *)&ed_bk_settings, (int)n);
    panel_init(); settings_init(); palette_apply();
#if FELUCCA_FLASH
    persist_saved = ed_bk_settings; persist_pending = 0;
#endif
    return sk_done();
}
static const uint8_t *sk_set_view(uint32_t k, uint32_t *n)
{
    (void)k;
    *n = persist_len(&ed_bk_settings);
    return (const uint8_t *)&ed_bk_settings;
}
static uint32_t sk_set_state(const uint8_t *b, uint32_t n)
{
    const persist_t *p = (const persist_t *)(const void *)b;
    uint32_t m = 0;
    if (n >= 8u) memcpy(&m, b, 4);
    if (sk_set_current(p, n))
        return ED_RAW_CURRENT;
    return (m == PERSIST_MAGIC_EXT && n > sizeof *p && n <= sizeof(persist_rec_t)) ||   /* (another extension) */
           (m == PERSIST_MAGIC_V5 && n == sizeof *p + 32u) ||
           (m == 0x50455233u && n == sizeof *p - sizeof p->favorites) ||                 /* PER3, PER2, PER1 */
           (m == 0x50455232u && n == sizeof *p - sizeof p->favorites - sizeof p->bold) ||
           (m == 0x50455231u && n == 8u + sizeof(panel_t)) ? ED_RAW_LEGACY : ED_RAW_UNKNOWN;
}

/* the user preset banks (backup ids 6, 7; types 5, 6): the bank's shape. Unknown record versions remain inert bytes,
 * preserving future/older bank data */
static int sk_up_shape(const up_bank_t *u)
{
    return u->magic == UP_BANK_MAGIC && u->rsize == sizeof(up_rec_t) && u->nslot == UP_PER_BANK;
}
static uint32_t sk_up_check(uint8_t *b, uint32_t *n)
{
    return *n && !sk_up_shape((const up_bank_t *)(const void *)b) ? 2u : 0u;
}
static uint32_t sk_up_install(uint32_t k, const uint8_t *b, uint32_t n)
{
    memset(&up_bank[k], 0, sizeof up_bank[k]);
    if (n) memcpy(&up_bank[k], b, n);
    up_bank_check(k, (int)n); up_gen++;
    return sk_done();
}
static const uint8_t *sk_up_view(uint32_t k, uint32_t *n)
{
    if (up_bank[k].magic == UP_BANK_MAGIC) *n = sizeof up_bank[0];
    return (const uint8_t *)&up_bank[k];
}
static uint32_t sk_up_state(const uint8_t *b, uint32_t n)
{
    return n == sizeof(up_bank_t) && sk_up_shape((const up_bank_t *)(const void *)b) ? ED_RAW_CURRENT : ED_RAW_UNKNOWN;
}

/* the retired FM6 patch bank (backup id 8, type 7; read only since 1.0.3): an older archive's moves its patches into
 * the user presets restored before it (ids 6, 7), as the first boot after the update does (up_fm6.c); 0 bytes: nothing */
static uint32_t sk_fm6b_check(uint8_t *b, uint32_t *n)
{
    return *n && !fm6_bank_valid((const fm6_bank_t *)(const void *)b) ? 2u : 0u;
}
static uint32_t sk_fm6b_install(uint32_t k, const uint8_t *b, uint32_t n)
{
    (void)k;
    if (!n) return 0;
    upf_migrate((const fm6_bank_t *)(const void *)b);
    sk_done();
    return upf_save() == 2 ? 4u : 0u;
}
static const uint8_t *sk_fm6b_view(uint32_t k, uint32_t *n) { (void)k; (void)n; return ED_BK_RAW; }   /* always empty */
static uint32_t sk_fm6b_state(const uint8_t *b, uint32_t n)
{
    return n == sizeof(fm6_bank_t) && fm6_bank_valid((const fm6_bank_t *)(const void *)b) ? ED_RAW_LEGACY : ED_RAW_UNKNOWN;
}

/* the user presets' FM6 patches (backup id 9, type 8; 0 bytes: none) */
static uint32_t sk_upf_check(uint8_t *b, uint32_t *n)
{
    const upf_t *u = (const upf_t *)(const void *)b;
    return *n && (!upf_valid(u) || (u->used >> (UP_SLOTS - 1u) >> 1)) ? 2u : 0u;
}
static uint32_t sk_upf_install(uint32_t k, const uint8_t *b, uint32_t n)
{
    (void)k;
    if (n) memcpy(&upf, b, sizeof upf); else upf_empty();
    sk_done();
    return upf_save() == 2 ? 4u : 0u;               /* (a failed write keeps the restored RAM copy) */
}
static const uint8_t *sk_upf_view(uint32_t k, uint32_t *n)
{
    (void)k;
    if (upf_valid(&upf)) *n = sizeof upf;
    return (const uint8_t *)&upf;
}
static uint32_t sk_upf_state(const uint8_t *b, uint32_t n)
{
    return n == sizeof(upf_t) && upf_valid((const upf_t *)(const void *)b) ? ED_RAW_CURRENT : ED_RAW_UNKNOWN;
}

/* the user sample slots (backup ids 32..34; export only: restore travels with SMP_BEGIN / WRITE / END) */
static const uint8_t *sk_smp_view(uint32_t k, uint32_t *n)
{
    const smp_user_hdr_t *h = (const smp_user_hdr_t *)smp_user_xip(k);
    if (usr_nz[k] && h->magic == SMP_USER_MAGIC && h->data_len <= SMP_USER_SIZE - SMP_USER_DATA)
        *n = SMP_USER_DATA + h->data_len;
    return smp_user_xip(k);
}

/* the FM6 voice bank (backup id 20, type 32 at 0xE7000; 0 bytes: none in the archive, the device's is kept) */
static uint32_t sk_fvb_state(const uint8_t *b, uint32_t n)
{
    const fvb_info_t *v = (const fvb_info_t *)(const void *)b;
    return n == FVB_LEN && v->magic == FVB_MAGIC && v->ver == 1u && v->n == FM6_NBANK ? ED_RAW_CURRENT : ED_RAW_UNKNOWN;
}
#if FELUCCA_FLASH
static uint32_t sk_fvb_check(uint8_t *b, uint32_t *n) { return *n && ed_bk_fvb_check(b) ? 2u : 0u; }
static uint32_t sk_fvb_install(uint32_t k, const uint8_t *b, uint32_t n)
{
    uint32_t rc;
    (void)k;
    if (!n) return 0;
    rc = ed_bk_fvb_apply(b);
    sk_done();
    return rc;
}
static const uint8_t *sk_fvb_view(uint32_t k, uint32_t *n)   /* read from flash a piece at a time (ed_bk_fvb_fill) */
{
    (void)k;
    *n = ed_bk_vlen;
    return ed_smp_buf;
}
#define SK_FVB_BK ED_BK_ID_FVB, 1, OBJ_FM6VB, 1, SK_EMPTY | SK_EXT, FVB_LEN, 0, sk_fvb_check, sk_fvb_install, sk_fvb_view, \
                  &ed_bk_vcrc, ed_bk_fvb_fill
#else
#define SK_FVB_BK SK_NONE, 0, OBJ_FM6VB, 1, 0, FVB_LEN, 0, 0, 0, 0, 0, 0   /* (the raw export lists it without flash) */
#endif

#if ED_BK_HAS_SLC
/* the SLICE records (backup id 21; not a commit-record object; 0 bytes: none in the archive, the device's are kept).
 * Restore needs the samples (ids 32..34) in place first */
static uint32_t sk_slc_check(uint8_t *b, uint32_t *n)
{
    if (!*n) return 0;
    if (!flash_ok) return 4;
    return slc_bk_check((const slc_bk_t *)(const void *)b, *n) ? 2u : 0u;
}
static uint32_t sk_slc_install(uint32_t k, const uint8_t *b, uint32_t n)
{
    uint32_t rc;
    (void)k;
    if (!n) return 0;
    rc = slc_bk_apply((const slc_bk_t *)(const void *)b);
    sk_done();
    return rc;
}
static const uint8_t *sk_slc_view(uint32_t k, uint32_t *n)   /* built now from the slices in use, in ed_smp_buf */
{
    (void)k;
    *n = slc_bk_make((slc_bk_t *)(void *)ed_smp_buf);
    return ed_smp_buf;
}
#endif

/* The kinds. Their order is the wire order: BACKUP_LIST walks the rows with backup ids (SK_EXT ones only for
 * "LIST 1", and they come last), STORE_LIST the rows with storage types, ascending. Without flash the voice bank is
 * only a raw-export row, without SLICE there is no row 21. Storage types are append-only (storage.c OBJ_*) */
static const store_kind_t SK_KINDS[] = {
    /* bk, nbk, obj, nobj, flags, size, accepts, check, install, view, crc, fill, state */
    {0, 1, SK_NONE, 0, SK_SCRATCH, 0, proj_accepts_length, sk_live_check, sk_live_install, sk_live_view, 0, 0, 0},
    {1, 1, OBJ_SETTINGS, 1, SK_SAVE, 0, sk_set_accepts, sk_set_check, sk_set_install, sk_set_view, 0, 0, sk_set_state},
    {2, 4, OBJ_PROJECT0, 4, SK_EMPTY | SK_SAVE, 0, proj_accepts_length, sk_proj_check, sk_slot_install, sk_slot_view,
     0, 0, sk_proj_state},
    {6, 2, OBJ_UPRESET0, 2, SK_EMPTY | SK_SAVE, sizeof(up_bank_t), 0, sk_up_check, sk_up_install, sk_up_view, 0, 0,
     sk_up_state},
    {8, 1, OBJ_FM6BANK, 1, SK_EMPTY, sizeof(fm6_bank_t), 0, sk_fm6b_check, sk_fm6b_install, sk_fm6b_view, 0, 0,
     sk_fm6b_state},
    {9, 1, OBJ_UPFM6, 1, SK_EMPTY, sizeof(upf_t), 0, sk_upf_check, sk_upf_install, sk_upf_view, 0, 0, sk_upf_state},
    {SK_NONE, 0, OBJ_AUTOSAVE, 1, 0, 0, 0, 0, 0, 0, 0, 0, sk_proj_state},   /* (the live music is backup id 0) */
    {32, SMP_USER_SLOTS, SK_NONE, 0, 0, 0, 0, 0, 0, sk_smp_view, 0, 0, 0},
    {SK_FVB_BK, sk_fvb_state},
#if ED_BK_HAS_SLC
    {ED_BK_ID_SLC, 1, SK_NONE, 0, SK_EMPTY | SK_EXT, sizeof(slc_bk_t), 0, sk_slc_check, sk_slc_install, sk_slc_view,
     0, 0, 0},
#endif
};
#define SK_N ((uint32_t)(sizeof SK_KINDS / sizeof SK_KINDS[0]))
_Static_assert(OBJ_COUNT == 10u && OBJ_FM6VB == 32u, "a new storage type: give it a row in SK_KINDS (and the protocol)");
_Static_assert(sizeof proj_wire_u.raw >= sizeof(project_store_t), "a project is staged in ED_BK_RAW");

static const store_kind_t *sk_of_bk(uint32_t id)   /* the kind of backup id id; 0 none */
{
    const store_kind_t *s;
    for (s = SK_KINDS; s < SK_KINDS + SK_N; s++)
        if (s->bk != SK_NONE && id - s->bk < s->nbk)
            return s;
    return 0;
}
static const store_kind_t *sk_of_obj(uint32_t id)  /* the kind of storage type id; 0 none */
{
    const store_kind_t *s;
    for (s = SK_KINDS; s < SK_KINDS + SK_N; s++)
        if (s->obj != SK_NONE && id - s->obj < s->nobj)
            return s;
    return 0;
}
static uint32_t sk_bk_count(uint32_t ext)          /* the objects BACKUP_LIST (ext: "LIST 1") lists */
{
    uint32_t c = 0;
    for (const store_kind_t *s = SK_KINDS; s < SK_KINDS + SK_N; s++)
        if (s->bk != SK_NONE && (ext || !(s->flags & SK_EXT)))
            c += s->nbk;
    return c;
}
static int sk_accepts(const store_kind_t *s, uint32_t n)   /* a length BACKUP_PUT begins with */
{
    if (!n && (s->flags & SK_EMPTY))
        return 1;
    return s->accepts ? s->accepts(n) : n == s->size;
}
/* the staged object, whole (length, CRC), through its kind: check, then (SK_SAVE) the A/B commit, then install */
static uint32_t ed_bk_commit(void)
{
    uint8_t *raw = ED_BK_RAW;
    const store_kind_t *s = sk_of_bk(ed_bk_id);
    uint32_t rc;
    if (ed_bk_pos != ed_bk_len || st_crc32(raw, ed_bk_len) != ed_bk_crc) return 2;
    if (!s || !s->install) return 1;
    if ((rc = s->check(raw, &ed_bk_len))) return rc;
#if FELUCCA_FLASH
    if ((s->flags & SK_SAVE) && (!flash_ok || st_save(s->obj + ed_bk_id - s->bk, raw, ed_bk_len))) return 4;
#endif
    return s->install(ed_bk_id - s->bk, raw, ed_bk_len);
}
static uint32_t ed_bk_write(const uint8_t *a, uint32_t n)
{
    /* the arguments first: a malformed request never stops the transport. BACKUP_PUT takes the kinds with an install
     * (the samples, 32..34, travel with SMP_*) */
    const store_kind_t *s = n >= 2u ? sk_of_bk(a[1]) : 0;
    if (n < 2u || a[0] > 3u || !s || !s->install) return 1;
    if (a[0] == 0u) {
        if (n != 12u || a[6] > 15u || a[11] > 15u) return 1;
        uint32_t len = ed_bk_r32(a + 2);
        if (len > ED_BK_MAX || !sk_accepts(s, len)) return 1;
        if (ed_flash_stop()) return 3;
        ed_bk_valid = 0; ed_bk_put = 1; ed_bk_id = a[1]; ed_bk_len = len; ed_bk_gen = ++proj_wire_gen;
        ed_bk_crc = ed_bk_r32(a + 7); ed_bk_pos = 0;
        ed_bk_usb = usb.resets; ed_bk_ms = fm1_ms;
        return 0;
    }
    if (!ed_bk_put || ed_bk_id != a[1] || ed_bk_usb != usb.resets || fm1_ms - ed_bk_ms > 15000u ||
        ed_bk_gen != proj_wire_gen) {                 /* (a project save / load reused the staging RAM) */
        ed_bk_put = 0; return 5;
    }
    ed_bk_ms = fm1_ms;
    if (a[0] == 3u) { ed_bk_put = 0; return n == 2u ? 0u : 1u; }
    if (a[0] == 2u) {
        if (n != 2u) return 1;
        if (ed_flash_stop()) return 3;
        uint32_t rc = ed_bk_commit(); ed_bk_put = 0; return rc;
    }
    if (n < 9u || a[6] > 15u || ed_bk_r32(a + 2) != ed_bk_pos) return 1;
    uint32_t count = ed_unpack7(a + 7, n - 7u, ed_smp_buf, 256u);
    if (!count || count > ed_bk_len - ed_bk_pos) return 1;
    if (ed_flash_stop()) return 3;
    memcpy(ED_BK_RAW + ed_bk_pos, ed_smp_buf, count); ed_bk_pos += count;
    return 0;
}
static int ed_backup_handle(uint32_t cmd, const uint8_t *a, uint32_t n)
{
    if (cmd == ED_BACKUP_LIST) {
        uint32_t ext = ED_BK_XN ? (uint32_t)(n == 1u && a[0] == 1u) : 0u;     /* "LIST 1": the objects of #321 after the 13 */
        uint32_t rc = n && !ext ? 1u : ed_bk_capture(), cnt = sk_bk_count(ext);
        const store_kind_t *s;
        ed_b(1); ed_b(rc); ed_b(rc ? 0u : cnt);
        for (s = SK_KINDS; !rc && s < SK_KINDS + SK_N; s++)
            for (uint32_t k = 0; s->bk != SK_NONE && (ext || !(s->flags & SK_EXT)) && k < s->nbk; k++) {
                uint32_t len = 0;
                const uint8_t *p = s->view(k, &len);
                ed_b(s->bk + k); ed_bk_u32(len);
                ed_bk_u32(s->crc ? *s->crc : st_crc32(p, len));
                fm1_wdt_feed();
            }
        return 1;
    }
    if (cmd == ED_BACKUP_GET) {
        uint32_t len = 0, off = n >= 6u ? ed_bk_r32(a + 1) : 0u;
        uint32_t count = n == 8u ? (uint32_t)a[6] | (uint32_t)a[7] << 7 : 0u;
        const store_kind_t *s = n ? sk_of_bk(a[0]) : 0;
        const uint8_t *p = s ? s->view(a[0] - s->bk, &len) : 0;
        uint32_t rc = (!ed_bk_valid || ed_bk_usb != usb.resets || (s && (s->flags & SK_SCRATCH) && ed_bk_gen != proj_wire_gen)) ? 5u :
            transport_busy() ? 3u : n != 8u || a[5] > 15u || !p || !count || count > 256u || off > len || count > len - off ? 1u : 0u;
        if (!rc && s->fill)                           /* a streamed object: this piece from flash, if still the listed one */
            rc = s->fill(off, count);
        ed_b(n ? a[0] : 127u); ed_b(rc); ed_bk_u32(off); ed_b(rc ? 0u : count & 127u); ed_b(rc ? 0u : count >> 7);
        if (!rc) ed_bk_pack(s->fill ? ed_smp_buf : p + off, count);
        return 1;
    }
    if (cmd == ED_BACKUP_PUT) {
        uint32_t rc = ed_bk_write(a, n);
        ed_b(n ? a[0] : 127u); ed_b(n >= 2u ? a[1] : 127u); ed_b(rc);
        return 1;
    }
    return 0;
}

/* ---- #456: the raw store export, STORE_LIST (82) and STORE_GET (83); INFO 59 01 caps (bit 0) ----
 * Every storage object as flash holds it: the payload of the copy storage.c's own reader takes (st_current: the newest
 * intact copy, A on a tie), byte for byte, with its commit record's length, CRC and sequence. Nothing here decodes,
 * converts, bounds or re-packs the bytes, so an object this firmware cannot load (a later format, a retired kind, a
 * damaged copy) is exported exactly as an object it can. The ids are the commit records' types (storage.c OBJ_*, on
 * flash, append-only), not the backup ids. Read only: no flash write, no erase, no runtime state, no transport stop
 * (rc 3 while it runs), no snapshot to go stale (the client checks each object's bytes against the listed CRC, and a
 * damaged one against a second LIST). Scratch: st_buf for the request only (as fvb_valid). web/EDITOR_PROTOCOL.md
 * "Raw store export", docs/legacy-formats.md. */
enum { ED_STORE_LIST = 82, ED_STORE_GET };
#define ED_RAW_CAPS 1u                              /* INFO 59 01: bit 0 STORE_LIST / STORE_GET */
/* copy c's commit record valid (the voice bank: one copy, its payload at FVB_INFO); 0 */
static int ed_raw_head(uint32_t id, uint32_t c, st_hdr_t *h)
{
    uint32_t base = id == OBJ_FM6VB ? (c ? 0u : FVB_HOME) : st_sector(id, c);
    return !base || st_read(base, h, sizeof *h) || h->magic != ST_MAGIC || h->type != id || h->slot != c ||
           h->len > ST_PAYLOAD_MAX || h->hcrc != st_crc32(h, sizeof *h - 4u);
}
/* copy c's payload (h->len bytes) -> st_buf; 0 when its CRC matches the record's */
static int ed_raw_body(uint32_t id, uint32_t c, const st_hdr_t *h)
{
    uint32_t base = id == OBJ_FM6VB ? FVB_HOME + FVB_INFO : st_sector(id, c) + ST_PAYLOAD_OFF;
    return st_read(base, st_buf, h->len) || st_crc32(st_buf, h->len) != h->crc;
}
/* the copy to export: the newest intact one (*ok 1), as st_current; none intact, the newest with a valid commit record
 * (*ok 0: DAMAGED, its bytes as stored); -1 = no commit record. *h its record, st_buf its payload */
static int ed_raw_pick(uint32_t id, st_hdr_t *h, int *ok)
{
    st_hdr_t r[2];
    int v0 = !ed_raw_head(id, 0, &r[0]), v1 = !ed_raw_head(id, 1, &r[1]), first, k;
    first = v1 && (!v0 || (r[1].seq != r[0].seq && r[1].seq - r[0].seq < 0x80000000u));
    for (k = 0; k < 2; k++) {
        int c = k ? !first : first;
        if ((c ? v1 : v0) && !ed_raw_body(id, (uint32_t)c, &r[c])) {
            *h = r[c]; *ok = 1;
            return c;
        }
    }
    if (!v0 && !v1)
        return -1;
    *h = r[first]; *ok = 0;
    (void)ed_raw_body(id, (uint32_t)first, h);
    return first;
}
/* the schema state of n intact payload bytes b of storage type id (its kind's state, store_kind.h): CURRENT what this
 * firmware writes, LEGACY an older layout it still converts on load, UNKNOWN neither (a later format, another layout:
 * it does not load it and keeps the bytes), EMPTY none (an erased slot: project_erase commits 0 bytes). Records inside a
 * container (a user preset's version and parameter count, a retired engine on a track) are the client's to read */
static uint32_t ed_raw_kind(uint32_t id, const uint8_t *b, uint32_t n)
{
    const store_kind_t *s = sk_of_obj(id);
    return !n ? ED_RAW_EMPTY : s && s->state ? s->state(b, n) : ED_RAW_UNKNOWN;
}
static uint32_t ed_raw_rc(void)                         /* 4 no flash, 3 the transport runs (no stop: read only), 0 */
{
#if FELUCCA_FLASH
    if (flash_ok)
        return transport_busy() ? 3u : 0u;
#endif
    return 4;
}
static int ed_raw_handle(uint32_t cmd, const uint8_t *a, uint32_t n)
{
    st_hdr_t h;
    int ok, c;
    uint32_t i, id, rc;
    if (cmd == ED_STORE_LIST) {
        const store_kind_t *s;
        rc = n ? 1u : ed_raw_rc();
        for (s = SK_KINDS, i = 0; s < SK_KINDS + SK_N; s++)   /* every storage type of the table, ascending */
            i += s->obj != SK_NONE ? s->nobj : 0u;
        ed_b(1); ed_b(rc); ed_b(rc ? 0u : i);   /* (1: this reply's layout) */
        for (s = SK_KINDS; !rc && s < SK_KINDS + SK_N; s++)
            for (id = s->obj; s->obj != SK_NONE && id < s->obj + s->nobj; id++) {
                uint32_t len, m = 0;
                c = ed_raw_pick(id, &h, &ok);
                len = c < 0 ? 0u : h.len;
                if (len >= 4u)
                    memcpy(&m, st_buf, 4);
                ed_b(id);
                ed_b(c < 0 ? ED_RAW_EMPTY : !ok ? ED_RAW_DAMAGED : ed_raw_kind(id, st_buf, len));
                ed_b(c < 0 ? 127u : (uint32_t)c);
                ed_bk_u32(len); ed_bk_u32(c < 0 ? 0u : h.crc); ed_bk_u32(c < 0 ? 0u : h.seq); ed_bk_u32(m);
                fm1_wdt_feed();
            }
        return 1;
    }
    if (cmd == ED_STORE_GET) {                          /* id, offset u32, count lo, count hi (as BACKUP_GET) */
        uint32_t off = n == 8u ? ed_bk_r32(a + 1) : 0u, count = n == 8u ? (uint32_t)a[6] | (uint32_t)a[7] << 7 : 0u;
        rc = n != 8u || a[5] > 15u || !count || count > 256u ? 1u : ed_raw_rc();
        id = n ? a[0] : 127u;
        if (!rc && (!sk_of_obj(id) || (c = ed_raw_pick(id, &h, &ok)) < 0 || off > h.len || count > h.len - off))
            rc = 1;
        ed_b(id); ed_b(rc); ed_bk_u32(off); ed_b(rc ? 0u : count & 127u); ed_b(rc ? 0u : count >> 7);
        if (!rc)
            ed_bk_pack(st_buf + off, count);
        return 1;
    }
    return 0;
}
