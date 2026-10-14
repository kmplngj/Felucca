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
static const uint8_t ED_BK_IDS[13] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 32, 33, 34};
#define ED_BK_N ((uint32_t)sizeof ED_BK_IDS)
#define ED_BK_ID_FVB 20u
#define ED_BK_ID_SLC 21u
#if FELUCCA_FLASH
#define ED_BK_HAS_FVB 1u
#else
#define ED_BK_HAS_FVB 0u
#endif
#if FELUCCA_FLASH && FELUCCA_SLICE
#define ED_BK_HAS_SLC 1u
#define ED_BK_LEN_SLC ((uint32_t)sizeof(slc_bk_t))
_Static_assert(sizeof(slc_bk_t) <= sizeof ed_smp_buf, "the SLICE backup object is built in ed_smp_buf");
#else
#define ED_BK_HAS_SLC 0u
#define ED_BK_LEN_SLC 0u
#endif
static const uint8_t ED_BK_XIDS[2] = {ED_BK_ID_FVB, ED_BK_ID_SLC};
#define ED_BK_XN (ED_BK_HAS_FVB + ED_BK_HAS_SLC)    /* the objects of "LIST 1" after the 13 */
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
static const uint8_t *ed_bk_object(uint32_t id, uint32_t *len)
{
    *len = 0;
    if (id == 0u) { *len = sizeof(project_store_t); return ED_BK_RAW; }
    if (id == 1u) { *len = persist_len(&ed_bk_settings); return (const uint8_t *)&ed_bk_settings; }
    if (id >= 2u && id <= 5u) {
        if (project_used(id - 2u)) *len = sizeof proj_slot[0];
        return (const uint8_t *)&proj_slot[id - 2u];
    }
    if (id == 6u || id == 7u) {
        if (up_bank[id - 6u].magic == UP_BANK_MAGIC) *len = sizeof up_bank[0];
        return (const uint8_t *)&up_bank[id - 6u];
    }
    if (id == 8u)                                   /* the retired FM6 patch bank: always empty */
        return ED_BK_RAW;
    if (id == 9u) {                                 /* the user presets' FM6 patches */
        if (upf_valid(&upf)) *len = sizeof upf;
        return (const uint8_t *)&upf;
    }
    if (id >= 32u && id < 32u + SMP_USER_SLOTS) {
        uint32_t k = id - 32u;
        const smp_user_hdr_t *h = (const smp_user_hdr_t *)smp_user_xip(k);
        if (usr_nz[k] && h->magic == SMP_USER_MAGIC && h->data_len <= SMP_USER_SIZE - SMP_USER_DATA)
            *len = SMP_USER_DATA + h->data_len;
        return smp_user_xip(k);
    }
#if FELUCCA_FLASH
    if (id == ED_BK_ID_FVB) {                       /* the bank is read from flash a piece at a time (ed_bk_fvb_fill) */
        *len = ed_bk_vlen;
        return ed_smp_buf;
    }
#endif
#if ED_BK_HAS_SLC
    if (id == ED_BK_ID_SLC) {                       /* built now from the slices in use, in ed_smp_buf */
        *len = slc_bk_make((slc_bk_t *)(void *)ed_smp_buf);
        return ed_smp_buf;
    }
#endif
    return 0;
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
    if (!proj_pack((project_store_t *)ED_BK_RAW, &proj_scratch)) return 2;
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
static uint32_t ed_bk_commit(void)
{
    uint8_t *raw = ED_BK_RAW;
    uint32_t obj;
    if (ed_bk_pos != ed_bk_len || st_crc32(raw, ed_bk_len) != ed_bk_crc) return 2;
    if (ed_bk_id == 0u || (ed_bk_id >= 2u && ed_bk_id <= 5u)) {
        if (ed_bk_len && !proj_import(&proj_scratch, raw, (int)ed_bk_len)) return 2;
        if (ed_bk_len) {                            /* an older format becomes FUN10 inside its ranges */
            proj_bound(&proj_scratch);
            if (!proj_pack((project_store_t *)raw, &proj_scratch)) return 2;
            ed_bk_len = sizeof(project_store_t);
        }
        if (ed_bk_id == 0u) {
            if (!ed_bk_len) return 2;
            return project_restore_runtime(&proj_scratch) ? 2u : 0u;
        }
        obj = OBJ_PROJECT0 + ed_bk_id - 2u;
    } else if (ed_bk_id == 1u) {
        const persist_t *p = (const persist_t *)raw;   /* PER4, or PER6 with an extension this firmware reads (#212) */
        if (!((ed_bk_len == sizeof *p && p->magic == PERSIST_MAGIC) || persist_ext_ok(p, (int)ed_bk_len)) ||
            !palette_stored_ok(p->palette) ||
            p->lowcut > 2u || !leds_stored_ok(p->zoom) || !hold_stored_ok(p->bold) || p->favorites.filter > 1u || !ed_bk_panel_valid(&p->panel)) return 2;
        obj = OBJ_SETTINGS;
    } else if (ed_bk_id == 6u || ed_bk_id == 7u) {
        const up_bank_t *p = (const up_bank_t *)raw;
        if (ed_bk_len && (ed_bk_len != sizeof *p || p->magic != UP_BANK_MAGIC ||
            p->rsize != sizeof(up_rec_t) || p->nslot != UP_PER_BANK)) return 2;
        /* Unknown record versions remain inert bytes, preserving future/older bank data. */
        obj = OBJ_UPRESET0 + ed_bk_id - 6u;
    } else if (ed_bk_id == 8u) {                    /* an older archive's FM6 bank: into the restored user presets */
        if (!ed_bk_len) return 0;
        if (ed_bk_len != sizeof(fm6_bank_t) || !fm6_bank_valid((const fm6_bank_t *)raw)) return 2;
        upf_migrate((const fm6_bank_t *)raw);
        sync_reload = 1; ui.force = 1;
        return upf_save() == 2 ? 4u : 0u;
    } else if (ed_bk_id == 9u) {                    /* the user presets' FM6 patches (0: none) */
        const upf_t *u = (const upf_t *)raw;
        if (ed_bk_len && (ed_bk_len != sizeof *u || !upf_valid(u) || (u->used >> (UP_SLOTS - 1u) >> 1))) return 2;
        if (ed_bk_len) memcpy(&upf, raw, sizeof upf); else upf_empty();
        sync_reload = 1; ui.force = 1;
        return upf_save() == 2 ? 4u : 0u;           /* (a failed write keeps the restored RAM copy) */
#if FELUCCA_FLASH
    } else if (ed_bk_id == ED_BK_ID_FVB) {          /* the FM6 voice bank (0: none in the archive: the device's is kept) */
        uint32_t rc;
        if (!ed_bk_len) return 0;
        if (ed_bk_fvb_check(raw)) return 2;
        rc = ed_bk_fvb_apply(raw);
        sync_reload = 1; ui.force = 1;
        return rc;
#endif
#if ED_BK_HAS_SLC
    } else if (ed_bk_id == ED_BK_ID_SLC) {          /* the SLICE records (0: none in the archive: the device's are kept) */
        uint32_t rc;
        if (!ed_bk_len) return 0;
        if (!flash_ok) return 4;
        if (slc_bk_check((const slc_bk_t *)(const void *)raw, ed_bk_len)) return 2;
        rc = slc_bk_apply((const slc_bk_t *)(const void *)raw);
        sync_reload = 1; ui.force = 1;
        return rc;
#endif
    } else return 1;
#if FELUCCA_FLASH
    if (!flash_ok || st_save(obj, raw, ed_bk_len)) return 4;
#else
    (void)obj;
#endif
    if (ed_bk_id >= 2u && ed_bk_id <= 5u) {
        memset(&proj_slot[ed_bk_id - 2u], 0, sizeof proj_slot[0]);
        if (proj_cur == ed_bk_id - 2u)
            proj_cur = PROJ_NO_SLOT;                     /* (another project there now: the music keeps its name) */
        if (ed_bk_len) memcpy(&proj_slot[ed_bk_id - 2u], raw, ed_bk_len);
    } else if (ed_bk_id == 1u) {
        memset(&ed_bk_settings, 0, sizeof ed_bk_settings);
        memcpy(&ed_bk_settings, raw, ed_bk_len);
        settings_import((persist_t *)(void *)&ed_bk_settings, (int)ed_bk_len);
        panel_init(); settings_init(); palette_apply();
#if FELUCCA_FLASH
        persist_saved = ed_bk_settings; persist_pending = 0;
#endif
    } else {
        uint32_t b = ed_bk_id - 6u;
        memset(&up_bank[b], 0, sizeof up_bank[b]);
        if (ed_bk_len) memcpy(&up_bank[b], raw, ed_bk_len);
        up_bank_check(b, (int)ed_bk_len); up_gen++;
    }
    sync_reload = 1; ui.force = 1;
    return 0;
}
/* a project object's length: FUN10 (today's, 1.2), FUN9 (1.1), FUN8 (before the DRUM lane levels, 1.0.x), FUN7 */
static int proj_store_len(uint32_t len)
{
    return len == sizeof(project_store_t) || len == PROJ_STORE_V9 || len == PROJ_STORE_V8 || len == PROJ_STORE_V7;
}
/* the ids BACKUP_PUT takes in this build (the samples, 32..34, travel with SMP_*) */
static int ed_bk_put_id(uint32_t id)
{
    if (id <= 9u) return 1;
#if FELUCCA_FLASH
    if (id == ED_BK_ID_FVB) return 1;
#endif
#if ED_BK_HAS_SLC
    if (id == ED_BK_ID_SLC) return 1;
#endif
    return 0;
}
static uint32_t ed_bk_write(const uint8_t *a, uint32_t n)
{
    /* the arguments first: a malformed request never stops the transport */
    if (n < 2u || a[0] > 3u || !ed_bk_put_id(a[1])) return 1;
    if (a[0] == 0u) {
        if (n != 12u || a[6] > 15u || a[11] > 15u) return 1;
        uint32_t len = ed_bk_r32(a + 2);
        if (len > ED_BK_MAX || (a[1] == 0u && !proj_store_len(len)) ||
            (a[1] == 1u && len != sizeof(persist_t) && (len <= sizeof(persist_t) + PERSIST_EXT_HDR ||
                                                    len > sizeof(persist_rec_t) || (len - sizeof(persist_t) - PERSIST_EXT_HDR) % 32u)) ||
            (a[1] >= 2u && a[1] <= 5u && len && !proj_store_len(len)) ||
            ((a[1] == 6u || a[1] == 7u) && len && len != sizeof(up_bank_t)) ||
            (a[1] == 8u && len && len != sizeof(fm6_bank_t)) || (a[1] == 9u && len && len != sizeof(upf_t)) ||
            (a[1] == ED_BK_ID_FVB && len && len != FVB_LEN) || (a[1] == ED_BK_ID_SLC && len && len != ED_BK_LEN_SLC)) return 1;
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
        uint32_t rc = n && !ext ? 1u : ed_bk_capture(), cnt = ED_BK_N + (ext ? ED_BK_XN : 0u);
        ed_b(1); ed_b(rc); ed_b(rc ? 0u : cnt);
        if (!rc) for (uint32_t i = 0; i < cnt; i++) {
            uint32_t len, id = i < ED_BK_N ? ED_BK_IDS[i] : ED_BK_XIDS[i - ED_BK_N];
            const uint8_t *p = ed_bk_object(id, &len);
            ed_b(id); ed_bk_u32(len);
            ed_bk_u32(
#if FELUCCA_FLASH
                id == ED_BK_ID_FVB ? ed_bk_vcrc :
#endif
                st_crc32(p, len));
            fm1_wdt_feed();
        }
        return 1;
    }
    if (cmd == ED_BACKUP_GET) {
        uint32_t len = 0, off = n >= 6u ? ed_bk_r32(a + 1) : 0u;
        uint32_t count = n == 8u ? (uint32_t)a[6] | (uint32_t)a[7] << 7 : 0u;
        const uint8_t *p = n ? ed_bk_object(a[0], &len) : 0;
        uint32_t rc = (!ed_bk_valid || ed_bk_usb != usb.resets || (n && !a[0] && ed_bk_gen != proj_wire_gen)) ? 5u : transport_busy() ? 3u :
            n != 8u || a[5] > 15u || !p || !count || count > 256u || off > len || count > len - off ? 1u : 0u;
#if FELUCCA_FLASH
        if (!rc && a[0] == ED_BK_ID_FVB)              /* the bank: this piece from flash, if it is still the listed one */
            rc = ed_bk_fvb_fill(off, count);
#endif
        ed_b(n ? a[0] : 127u); ed_b(rc); ed_bk_u32(off); ed_b(rc ? 0u : count & 127u); ed_b(rc ? 0u : count >> 7);
        if (!rc) ed_bk_pack(
#if FELUCCA_FLASH
            a[0] == ED_BK_ID_FVB ? ed_smp_buf :
#endif
            p + off, count);
        return 1;
    }
    if (cmd == ED_BACKUP_PUT) {
        uint32_t rc = ed_bk_write(a, n);
        ed_b(n ? a[0] : 127u); ed_b(n >= 2u ? a[1] : 127u); ed_b(rc);
        return 1;
    }
    return 0;
}
