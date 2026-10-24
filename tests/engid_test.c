/* SPDX-License-Identifier: GPL-3.0-only */
/* The engine id space (#212): ids are stored and sent as they are, whatever engines a build has. Run on the default
 * build and on a test build with a placeholder after the real catalog and a sparse catalog (FELUCCA_ENG_TEST14=1
 * FELUCCA_ENG_OMIT=10/11/12: DRUM/NOISE/FM6 left out; tests/run_tests.sh builds each):
 *   - the catalog: eng_ok / eng_idx / eng_of, an unknown id never another engine, ENGINE_ORDER
 *   - INFO: the old prefix (NENGINES names, "-" for an id this build cannot play), the 49 01 block's bitmap
 *   - FAV_GET / FAV_SET: the new user marker (127), the old one (INFO's count), unavailable ids refused
 *   - favourites of ids past 13 (ENGI_TEST in the test build) into the settings as PER6, back as PER4 without them
 *   - projects, user presets and a full backup with an id this build lacks: kept (id, preset, E values), shown N/A,
 *     silent, packed again byte for byte; past the id space: refused
 *   - the editor's PRESET / SET G_ENGSEL / UP_PUT to an unavailable engine: refused, nothing changes */
static unsigned char host_samples[3][0x14000];
#define SMP_USER_XIP(k) host_samples[k]
#define FELUCCA_OTA 1
#define FELUCCA_FLASH 0
#define FELUCCA_VERSION "TEST"
#define FELUCCA_CDC 1
#define main hostsim_main
#include "hostsim.c"
#undef main

static uint32_t host_wire_n;
static uint8_t host_wire[4096];
static void host_drain(void)
{
    while (so_r != so_w) {
        uint32_t p = sx_out_q[so_r++ % SXQ], cin = p & 15u, i;
        uint32_t n = cin == 4u || cin == 7u ? 3u : cin == 6u ? 2u : 1u;
        for (i = 0; i < n && host_wire_n < sizeof host_wire; i++)
            host_wire[host_wire_n++] = (uint8_t)(p >> (8u * (i + 1u)));
    }
}
static uint32_t ota_now_ms(void) { return fm1_ms; }
static void ota_idle(void) { host_drain(); fm1_ms++; }
static void fm1_wdt_feed(void)
{
    fm1_ms++;
    if (transport_req == 2u) { seq_stop(); transport_req = 0; }
}
static void fm1_irq_off(void) {}
static void fm1_irq_on(void) {}
static int32_t fm1_enc_take(uint32_t e) { (void)e; return 0; }
static void lcd_sync(void) {}
static void lcd_power(uint32_t s) { (void)s; }
static void lcd_wake_now(void) {}
static void lcd_blit(uint32_t x, uint32_t y, uint32_t w, uint32_t h, const uint16_t *p)
{ (void)x; (void)y; (void)w; (void)h; (void)p; }
#include "../firmware/src/gfx.c"
#include "../firmware/src/panel.c"
#include "../firmware/src/ui.c"
#include "../firmware/src/menu_items.c"
static void panel_setup(void) {}
#include "../firmware/src/upreset.c"
#include "../firmware/src/project.c"

static uint32_t flash_ok = 1;
static void audio_silence(void) {}
static void fl_inval(uint32_t off, uint32_t n) { (void)off; (void)n; }
static uint8_t *host_flash_ptr(uint32_t off) { return &host_samples[0][0] + off - SMP_USER_BASE; }
static int fl_erase4k(uint32_t off, uint32_t *took) { memset(host_flash_ptr(off), 0xFF, 4096); *took = 0; return 0; }
static int fl_write(uint32_t off, const void *p, uint32_t n) { memcpy(host_flash_ptr(off), p, n); return 0; }
static int st_read(uint32_t off, void *p, uint32_t n) { (void)off; (void)p; (void)n; return -1; }
static int st_prog(uint32_t off, const void *p, uint32_t n) { (void)off; (void)p; (void)n; return -1; }
static int st_erase(uint32_t off) { (void)off; return -1; }
#include "../firmware/src/storage.c"
#include "../firmware/src/editor.c"

static int check(const char *what, int ok)
{
    printf("engid: %-80s %s\n", what, ok ? "ok" : "FAIL");
    return !ok;
}
static void reset(void)
{
    uint32_t t, i;
    memset(&song, 0, sizeof song); memset(trk, 0, sizeof trk);
    memset(&chain, 0, sizeof chain); chain_defaults(&chain_config);
    memset(&ed_w, 0, sizeof ed_w); memset(&ui, 0, sizeof ui);
    memset(&favorites, 0, sizeof favorites); memset(settings_ml, 0, sizeof settings_ml);
    memset(settings_dev, 0, sizeof settings_dev); memset(&settings, 0, sizeof settings); settings_init();
    memset(proj_slot, 0, sizeof proj_slot); memset(up_bank, 0, sizeof up_bank);
    host_wire_n = 0;
    transport_req = panic_req = 0; sx_ready = sx_collect = sx_busy = 0;
    so_r = so_w = mi_r = mi_w = 0; usb.config = 1;
    for (i = 0; i < G_COUNT; i++) song.g[i] = GP[i].def;
    for (t = 0; t < NTRK; t++) {
        track_defaults(&trk[t]); set_engine_of(&trk[t], 0); apply_preset_to(&trk[t], 0);
        trk[t].engine = trk[t].eng_req; track_defaults_steps(&trk[t]);
    }
}
static uint32_t request(uint32_t cmd, const uint8_t *a, uint32_t n)
{
    uint32_t i;
    host_wire_n = 0; ota_frame_done();
    sysex_byte(0xF0); sysex_byte(ED_HDR0); sysex_byte(ED_HDR1); sysex_byte(ED_HDR2); sysex_byte((uint8_t)cmd);
    for (i = 0; i < n; i++) sysex_byte(a[i]);
    sysex_byte(0xF7); ed_service(); host_drain();
    return host_wire_n;
}

/* an id below the id space this build has no engine for, and one it can play that is past the old table */
#if FELUCCA_ENG_OMIT >= 0
#define ID_GONE ((uint32_t)FELUCCA_ENG_OMIT)          /* (left out of the catalog) */
#elif !FELUCCA_PROFILE_ENGINE_3
#define ID_GONE 3u                                    /* representative reduced portable profile */
#elif !FELUCCA_SLICE
#define ID_GONE 13u                                   /* (FELUCCA_SLICE=0: SLICE left out) */
#else
#define ID_GONE ((uint32_t)NENGINES)                  /* (past the table) */
#endif
#define ID_FAR 40u                                    /* (no build has it) */

static int catalog(void)
{
    int bad = 0, ok = 1;
    uint32_t e, n = 0;
    for (e = 0; e < 256u; e++) {
        const engine_t *en = eng_of(e);
        ok &= en != 0 && eng_idx(e) <= ENG_IDX_NONE;
        if (eng_ok(e)) { ok &= e < NENGINES && en != &ENG_NONE && en->npresets > 0; n++; }
        else ok &= e == ENGI_DIGITAL || en == &ENG_NONE;
        if (e >= NENGINES) ok &= eng_idx(e) == ENG_IDX_NONE && en == &ENG_NONE;
    }
    bad += check("every byte names this build's engine or ENG_NONE (never another engine); eng_ok = the ones it plays", ok);
    ok = n == NENG_SHOWN;
    for (e = 0; e < NENG_SHOWN; e++)
        ok &= eng_ok(eng_vis(e)) && eng_rank(eng_vis(e)) == e;
    bad += check("ENGINE_ORDER: each engine one can pick once, nothing else", ok);
    ok = !eng_ok(ID_GONE) && !eng_ok(ID_FAR) && eng_of(ID_FAR) == &ENG_NONE && eng_of(ID_GONE) == &ENG_NONE;
    ok &= eng_ok(eng_step(ID_GONE, 1)) && eng_ok(eng_step(ID_FAR, -1));   /* (a step away from one: a real engine) */
#if FELUCCA_ENG_TEST14
    ok &= NENGINES == FELUCCA_PROFILE_NSLOTS + 1u && eng_ok(ENGI_TEST) && str_eq(eng_of(ENGI_TEST)->name, "TEST14");
#else
    ok &= NENGINES == FELUCCA_PROFILE_NSLOTS && !eng_ok(NENGINES);              /* reserved slots remain even when their engine is absent */
#endif
    for (e = 10; e <= 12u; e++) ok &= (eng_ok(e) != 0) == (FELUCCA_ENG_OMIT != (int)e);
    ok &= (eng_ok(13) != 0) == (FELUCCA_SLICE && FELUCCA_ENG_OMIT != 13);
    bad += check("the id this build lacks and one past every table: unavailable, ENG_NONE (N/A, silent)", ok);
    bad += check("per-engine tables sized by the id space (MIDI_CC_ENG, PRESET_CAT)",
                 NELEM(MIDI_CC_ENG) == ENG_ID_MAX && NELEM(PRESET_CAT) == ENG_ID_MAX && !MIDI_CC_ENG[ID_FAR]);
    return bad;
}

static int info(void)
{
    int bad = 0, ok;
    uint32_t n, i, pos, e;
    uint8_t a[1] = {0};
    reset();
    n = request(ED_INFO, a, 0);
    pos = 5u;                                         /* (F0 7D 46 4C cmd, then the version string) */
    while (pos < n && host_wire[pos]) pos++;
    pos++;
    ok = host_wire[pos] == NENGINES;                  /* the old prefix: its count, P_COUNT G_COUNT NSTEP P_E0, the names */
    pos += 5u;
    for (e = 0; e < NENGINES; e++) {
        char nm[16];
        uint32_t k = 0;
        while (host_wire[pos] && k < 15u) nm[k++] = (char)host_wire[pos++];
        nm[k] = 0;
        pos++;
        ok &= eng_ok(e) ? str_eq(nm, ENGINES[e]->name) : str_eq(nm, "-");
    }
    bad += check("INFO's old prefix: NENGINES names, \"-\" where this build cannot play the id", ok);
    ok = host_wire[n - 4u] == 0x59 && host_wire[n - 3u] == 1u && host_wire[n - 2u] == (FELUCCA_FLASH ? ED_RAW_CAPS : 0u);
    bad += check("INFO 59 01: the raw store export (#456: cmds 82, 83), last", ok);
    n -= 3u;                                                    /* (the 58 01 block before it, as before) */
    ok = host_wire[n - 4u] == 0x58 && host_wire[n - 3u] == 1u && host_wire[n - 2u] == ED_BK_XCAPS;   /* #321: 58 01 caps */
    bad += check("INFO 58 01: the full backup's capabilities (#321), before it", ok);
    n -= 3u;                                                    /* (the 49 01 block before it, as before) */
    ok = host_wire[n - 15u] == 0x49 && host_wire[n - 14u] == 1u && host_wire[n - 13u] == ENG_ID_MAX &&
         host_wire[n - 12u] == ENG_USER_WIRE;
    for (i = 0; i < ENG_ID_MAX; i++)
        ok &= ((host_wire[n - 11u + i / 7u] >> (i % 7u)) & 1u) == (eng_ok(i) ? 1u : 0u);
    for (i = 0; i < 10u; i++)
        ok &= host_wire[n - 11u + i] < 128u;
    bad += check("INFO 49 01: the id space (64), FAV's user marker (127), a bit per id this build plays", ok);
    return bad;
}

static int fav(void)
{
    int bad = 0, ok;
    uint8_t a[4];
    reset();
    up_store(3, "MINE");
    a[0] = ENG_USER_WIRE; a[1] = 3; a[2] = 64; a[3] = 1;   /* (v14: 8192 + preset) */
    request(ED_FAV_SET, a, 4);
    ok = host_wire[5] == 3u && host_wire[6] == ENG_USER_WIRE && favorite_has(ENG_USER, 3);
    a[3] = 0; a[0] = NENGINES;                        /* the old marker: INFO's count */
    request(ED_FAV_SET, a, 4);
    ok &= host_wire[5] == 3u && host_wire[6] == NENGINES && !favorite_has(ENG_USER, 3);
    a[3] = 1; request(ED_FAV_SET, a, 4);
    a[0] = ENG_USER_WIRE; a[3] = 4; request(ED_FAV_GET, a, 4);   /* slots 3..6 with the new marker */
    ok &= host_wire[5] == 0u && host_wire[6] == ENG_USER_WIRE && host_wire[10] == 1u && host_wire[11] == 0u;
    bad += check("FAV_SET / FAV_GET: a user slot by 127 and by the old marker (INFO's count), echoed as asked", ok);
    a[0] = (uint8_t)ID_GONE; a[1] = 0; a[2] = 64; a[3] = 1;
    request(ED_FAV_SET, a, 4);
    ok = host_wire[5] == 1u && !favorite_has(ID_GONE, 0);
    a[0] = ID_FAR; request(ED_FAV_SET, a, 4);
    ok &= host_wire[5] == 1u;
    a[0] = ENGI_DIGITAL; a[1] = 0; request(ED_FAV_SET, a, 4);
    ok &= FELUCCA_FM4 || host_wire[5] == 1u;          /* (retired: no presets; with FELUCCA_FM4 an engine) */
    a[1] = 0;
    a[0] = 0x7E; request(ED_FAV_GET, a, 4);
    ok &= host_wire[5] == 1u;
    bad += check("FAV_SET / FAV_GET of an id this build lacks, DIGITAL, a byte that is no marker: rc 1, nothing kept", ok);
#if FELUCCA_ENG_TEST14
    a[0] = ENGI_TEST; a[1] = 1; a[2] = 64; a[3] = 1;   /* the appended fixture is an engine, never the user marker */
    request(ED_FAV_SET, a, 4);
    ok = host_wire[5] == 3u && favorite_has(ENGI_TEST, 1) && !favorite_has(ENG_USER, 1);
    {
        static persist_rec_t r;
        settings_export_rec(&r);
        ok &= r.magic == PERSIST_MAGIC_EXT && r.x.fav[ENGI_TEST][0] == 2u && persist_len(&r) > sizeof(persist_t);
    }
    bad += check("test build: appended engine presets starred like any (PER6 settings); no user-marker collision", ok);
#endif
    return bad;
}

/* the mix as the render tests have it (the engine ids stay), MASTER slewed up from the reset's 0, track 2 alone;
 * then a note on track 2: the peak of what the mix plays */
static int32_t play_peak(void)
{
    int32_t o[2 * CTL], peak = 0;
    uint32_t b, i, k;
    host_tracks_init();
    for (k = 0; k < NTRK; k++) trk[k].p[P_LEVEL] = k == 1u ? 127 : 0;
    for (b = 0; b < 600u; b++) mix_block(o, CTL);
    input_on(&trk[1], 60, 120);
    for (b = 0; b < 600u; b++) {
        mix_block(o, CTL);
        for (i = 0; i < 2u * CTL; i++) if (o[i] > peak || -o[i] > peak) peak = o[i] < 0 ? -o[i] : o[i];
    }
    input_off(&trk[1], 60);
    return peak;
}

/* a project with track 2 on id e, preset 9 and E values -64 .. 127: packed, imported, restored, packed again */
static int projects(void)
{
    int bad = 0, ok;
    static project_t p, q;
    static project_store_t st, st2;
    uint32_t i, e;
    const uint32_t ids[2] = {ID_GONE, ID_FAR};
    for (e = 0; e < 2u; e++) {
        int32_t peak = 0;
        reset();
        project_capture(&p);                          /* (once through a restore: the project as one is after a load) */
        ok = proj_encode(&st, &p) && proj_import(&q, &st, PROJ_STORE_SIZE) && project_restore_runtime(&q) == 0;
        project_capture(&p);
        p.t[1].engine = (uint8_t)ids[e];
        p.t[1].preset = 9;
        for (i = 0; i < 8u; i++) p.t[1].p[P_E0 + i] = (int16_t)(i & 1u ? 127 : -64 + (int32_t)i);
        p.sum = proj_sum(&p);
        ok &= proj_encode(&st, &p) && proj_import(&q, &st, PROJ_STORE_SIZE) && q.t[1].engine == ids[e] && q.t[1].preset == 9u;
        ok &= project_restore_runtime(&q) == 0 && trk[1].eng_req == ids[e] && trk[1].preset == 9u &&
              eng_of(trk[1].eng_req) == &ENG_NONE;
        for (i = 0; i < 8u; i++) ok &= trk[1].p[P_E0 + i] == (int16_t)(i & 1u ? 127 : -64 + (int32_t)i);
        project_capture(&q);
        ok &= proj_encode(&st2, &q) && !memcmp(&st, &st2, sizeof st);
        bad += check(e ? "a project with id 40 (no build's): kept, N/A, packed again byte for byte"
                       : "a project with an id this build lacks: kept (id, preset, E values), N/A, packed byte for byte", ok);
        song.sel = 1;
        peak = play_peak();                           /* silent, never another engine's sound */
        ok = ENGINES[trk[1].engine] == &ENG_NONE && peak == 0 && trk[1].eng_req == ids[e];
        trk[1].xp_n = 0;                              /* (the switch is done: a note is not queued behind one forever, */
        trk_note_on(&trk[1], 60, 100);                /*  eng_req is an id, engine its index) */
        ok &= trk[1].xp_n == 0u && !trk[1].xf_on;
        bad += check(e ? "  .. id 40 plays nothing" : "  .. it plays nothing (ENG_NONE), the id stays", ok);
        ok = 1;
        set_engine_of(&trk[1], ids[e]); clean_engine_of(&trk[1]);   /* (a request for it: refused, the sound kept) */
        ok &= trk[1].eng_req == ids[e] && trk[1].p[P_E0 + 1] == 127;
        ok &= str_eq(eng_of(TSEL->eng_req)->name, "N/A") && preset_shown(TSEL->eng_req) == 0u;
        {   /* the screens that name it: N/A, no preset; the PRESETS list and EDIT's list run */
            uint32_t total, k;                    /* (drawn: tests/ui_test.c "#212") */
            (void)eng_list_pos(&total);
            ok &= total == 0u && !preset_favorite();
            (void)preset_all_pos(&total);
            for (k = 0; k < total; k++) ok &= preset_all_at(k, &i) != ids[e];
        }
        bad += check("  .. selecting / INIT of it refused; the UI shows N/A, no presets, not in the list", ok);
    }
    reset();                                          /* the control: the same notes on ANALOG sound */
    host_preset(&trk[1], 0, 0);
    bad += check("  (the control: the same notes on ANALOG sound)", play_peak() > 1000);
    {   /* past the id space: no project */
        reset();
        project_capture(&p);
        p.t[2].engine = ENG_ID_MAX; p.sum = proj_sum(&p);
        ok = project_restore_runtime(&p) == 1 && trk[2].eng_req == 0u;
        p.t[2].engine = 0; p.sum = proj_sum(&p);
        ok &= proj_encode(&st, &p);
        st.raw[68u + st.raw[66] + (st.raw[66] + 2u + NSTEP * 9u) * 2u] = (uint8_t)ENG_ID_MAX;   /* track 3's engine */
        {
            uint32_t sum = proj_hash(st.raw, PROJ_STORE_SIZE - 4u);
            memcpy(st.raw + PROJ_STORE_SIZE - 4u, &sum, 4);
        }
        ok &= !proj_import(&q, &st, PROJ_STORE_SIZE);
        bad += check("a project with an engine byte past the id space (64): no project, nothing changes", ok);
    }
    return bad;
}

static int presets(void)
{
    int bad = 0, ok;
    uint8_t a[1];
    uint32_t i;
    up_rec_t *r;
    reset();
    up_store(5, "GONE");
    r = up_rec(5);
    r->engine = (uint8_t)ID_GONE;                     /* (as a backup of another build's bank holds it) */
    a[0] = 5; request(ED_UP_GET, a, 1);
    ok = up_used(5) && host_wire[5] == 5u && host_wire[6] == 1u && host_wire[7] == ID_GONE;
    ok &= up_load(5) == 0 && trk[song.sel].eng_req == ID_GONE && trk[song.sel].user == 6u;
    bad += check("a user preset stored with an id this build lacks: listed with its id, loads as N/A (kept)", ok);
    {
        char b[16];
        up_auto_name(b, ID_GONE, 4);
        ok = str_eq(b, "N/A 05");
        up_auto_name(b, ENGI_DIGITAL, 4);
        ok &= str_eq(b, FELUCCA_FM4 ? "DIGITAL 05" : eng_ok(ENGI_FM6) ? "FM6 05" : "N/A 05");
        bad += check("its automatic name says N/A (DIGITAL's still FM6)", ok);
    }
    {   /* UP_PUT to it: refused, the slot unchanged */
        uint8_t m[400];
        uint32_t n = 0;
        up_rec_t before = *up_rec(7);
        m[n++] = 7; m[n++] = (uint8_t)ID_GONE; m[n++] = 'X'; m[n++] = 0;
        for (i = 0; i < P_COUNT; i++) { m[n++] = 0; m[n++] = 64; }
        for (i = 0; i < 32u; i++) m[n++] = 0;
        request(ED_UP_PUT, m, n);
        ok = host_wire[5] == 7u && host_wire[6] == 1u && !memcmp(&before, up_rec(7), sizeof before);
        m[1] = 0; request(ED_UP_PUT, m, n);
        ok &= host_wire[6] != 1u;                     /* (no flash here: rc 2, the arguments taken) */
        bad += check("UP_PUT of an engine this build lacks: rc 1, the slot as it was (an engine it has: taken)", ok);
    }
    {   /* the editor's PRESET and SET G_ENGSEL to it: no change */
        uint8_t m[4];
        uint32_t e0;
        reset();
        e0 = TSEL->eng_req;
        m[0] = (uint8_t)ID_GONE; m[1] = 0;
        ok = request(ED_PRESET, m, 2) == 0u && TSEL->eng_req == e0;
        m[0] = 1; m[1] = G_ENGSEL; m[2] = (uint8_t)((8192 + ID_GONE) & 127u); m[3] = (uint8_t)((8192 + ID_GONE) >> 7);
        request(ED_SET, m, 4);
        ok &= TSEL->eng_req == e0;
        m[0] = (uint8_t)ID_GONE;                      /* NAMES: no reply past the table, ENG_NONE's (none) in it */
        ok &= ID_GONE >= NENGINES ? request(ED_NAMES, m, 1) == 0u : request(ED_NAMES, m, 1) > 0u && host_wire[6] == 0u;
        bad += check("PRESET / SET G_ENGSEL to an engine this build lacks: refused, the sound kept; NAMES: none", ok);
    }
    return bad;
}

/* the settings object of a full backup: PER4 while no favourite is past id 13, PER6 with one (an id this build may
 * lack: kept); restored (BACKUP_PUT) both ways; an extension it cannot read refused */
static uint32_t bk_u32(uint8_t *a, uint32_t v) { for (uint32_t i = 0; i < 5u; i++) a[i] = (uint8_t)((v >> (7u * i)) & 127u); return 5; }
static uint32_t bk_put_object(uint32_t id, const uint8_t *data, uint32_t len)
{
    uint8_t a[400];
    uint32_t off = 0, rc, n;
    a[0] = 0; a[1] = (uint8_t)id; bk_u32(a + 2, len); bk_u32(a + 7, st_crc32(data, len));
    if ((rc = ed_bk_write(a, 12)))
        return 100u + rc;
    while (off < len) {
        uint32_t k = len - off > 256u ? 256u : len - off, i, o = 0;
        a[0] = 1; a[1] = (uint8_t)id; bk_u32(a + 2, off);
        n = 7;
        while (o < k) {                               /* pack7: a mask byte, then up to 7 low bytes */
            uint32_t g = k - o > 7u ? 7u : k - o, m = n++;
            a[m] = 0;
            for (i = 0; i < g; i++, o++) { a[m] |= (uint8_t)((data[off + o] >> 7) << i); a[n++] = data[off + o] & 127u; }
        }
        if ((rc = ed_bk_write(a, n)))
            return 200u + rc;
        off += k;
    }
    a[0] = 2; a[1] = (uint8_t)id;
    return ed_bk_write(a, 2);
}
static uint32_t bk_put(const uint8_t *data, uint32_t len) { return bk_put_object(1, data, len); }
static int backup(void)
{
    int bad = 0, ok;
    static persist_rec_t r, r2;
    uint32_t len;
    const uint8_t *obj = 0;
    reset();
    panel = PANEL_DEFAULT;                            /* (a restore checks the calibration) */
    favorite_set(ENGI_FM6, 2, 1);
    ok = ed_bk_capture() == 0 && (obj = ed_bk_object(1, &len)) && len == sizeof(persist_t) &&
         ((const persist_t *)obj)->magic == PERSIST_MAGIC;
    favorite_set(ID_GONE, 1, 1); favorite_set(ID_FAR, 255, 1);   /* (an id this build lacks: kept, as imported) */
    ok &= ed_bk_capture() == 0 && (obj = ed_bk_object(1, &len)) && len == sizeof(persist_t) + PERSIST_EXT_HDR + FAV_ROWS * 32u &&
          ((const persist_t *)obj)->magic == PERSIST_MAGIC_EXT;
    bad += check("BACKUP_LIST's settings: PER4 (as 1.6) while no favourite is past 13, PER6 with one", ok);
    memcpy(&r, obj, len);
    memset(&favorites, 0, sizeof favorites);
    ok = bk_put((const uint8_t *)&r, len) == 0 && favorite_has(ID_GONE, 1) && favorite_has(ID_FAR, 255) &&
         favorite_has(ENGI_FM6, 2);
    bad += check("BACKUP_PUT of that PER6: restored, the unavailable ids' favourites kept", ok);
    memcpy(&r2, &r, sizeof(persist_t)); r2.magic = PERSIST_MAGIC;   /* a PER4 (1.6's, or a downgrade's prefix) */
    ok = bk_put((const uint8_t *)&r2, sizeof(persist_t)) == 0 && favorite_has(ENGI_FM6, 2) && !favorite_has(ID_FAR, 255);
    bad += check("BACKUP_PUT of a PER4 (older firmware's): restored; ids past 13 have none (the downgrade limit)", ok);
    r2 = r; r2.x.ver = 9u;
    ok = bk_put((const uint8_t *)&r2, len) == 2u;
    r2 = r; r2.x.rows = 3u;                            /* (rows that do not match the length) */
    ok &= bk_put((const uint8_t *)&r2, len) == 2u;
    {
        static uint8_t big[sizeof(persist_rec_t) + 32u];  /* (longer than any record: refused at begin) */
        memcpy(big, &r, sizeof r);
        ok &= bk_put((const uint8_t *)&r, len - 1u) == 101u && bk_put(big, sizeof big) == 101u;
    }
    bad += check("BACKUP_PUT of a PER6 it cannot read (another version, rows, length): refused (rc 2 / rc 1)", ok);
    return bad;
}

#ifndef FELUCCA_ENGID_HELPERS_ONLY
/* Playback/control paths must not reinterpret the stored values of an unavailable DRUM/FM6 track. */
static int unavailable_controls(void)
{
    int bad = 0, ok;
    uint32_t e, i;
    for (e = 10; e <= 12u; e += 2u) {
        int16_t before[P_COUNT];
        if (eng_ok(e)) continue;
        reset();
        TSEL->eng_req = (uint8_t)e;
        TSEL->engine = (uint8_t)eng_idx(e);
        for (i = 0; i < 8u; i++) TSEL->p[P_E0 + i] = (int16_t)(127u - i);
        memcpy(before, TSEL->p, sizeof before);
        ok = 1;
        for (i = 0; i < NPAGES; i++)
            if ((PAGES[i].scope == SC_TRACK && PAGES[i].id[0] >= P_LN0 && PAGES[i].id[0] <= P_LN7) ||
                (PAGES[i].graph >= GR_FMOP && PAGES[i].graph <= GR_FMENV))
                ok &= !page_visible(i);
        fm6_bank_used = 1u;
        midi_pc_load(TSEL, 0);
        ok &= !memcmp(before, TSEL->p, sizeof before);
        bad += check("an unavailable DRUM/FM6 track has no lane/operator pages; Program Change keeps its values", ok);
        /* Owner-checked sparse builds catch an accidental DRUM lane access from voice allocation. */
        eng_mem_claim(TSEL);
        (void)voice_alloc(TSEL, 36);
    }
    if (!eng_ok(ENGI_FM6)) {
        uint8_t v[FP_SIZE + 1u], before[FP_SIZE + 1u];
        reset();
        TSEL->eng_req = ENGI_FM6;
        fm6_unpack(FM6_FACTORY[3], v); memcpy(v + FP_NAME, "KEEP PATCH", 10);
        fm6_set_patch(0, v); memcpy(before, fm6_patch[0], sizeof before);
        TSEL->p[P_E7] = 127;
        fm6_adopt(0);
        ok = TSEL->p[P_E7] == 127;
        TSEL->p[P_E7] = 0;
        fm6_track_loaded(TSEL); fm6_poll();
        ok &= TSEL->p[P_E7] == 0 && !memcmp(before, fm6_patch[0], sizeof before);
        TSEL->p[P_E7] = 127; fm6_slot[0] = FM6_OWN + 1u;
        fm6_bank_changed();
        ok &= TSEL->p[P_E7] == 127 && !memcmp(before, fm6_patch[0], sizeof before);
        bad += check("unavailable FM6: adopt, preset SLOT, poll and bank replacement leave its values/patch intact", ok);
    }
    return bad;
}

static int unavailable_storage(void)
{
    int bad = 0, ok;
    static project_t p, q;
    static project_store_t st, st2;
    if (!eng_ok(ENGI_DRUM)) {
        reset(); project_capture(&p);
        p.t[3].engine = ENGI_DRUM; p.t[3].preset = PROJ_DEF_KEEP; p.sum = proj_sum(&p);
        ok = project_restore_runtime(&p) == 0 && trk[3].eng_req == ENGI_DRUM &&
             !memcmp(trk[3].p + P_E0, (int16_t[8])DRUM_KIT_E, 8u * sizeof(int16_t)) &&
             trk[3].p[P_REL] == DRUM_PRESETS[0].env[3];
        bad += check("a legacy drum part restores stable kit defaults while DRUM is unavailable (no catalog dereference)", ok);
    }
    if (!eng_ok(ENGI_FM6)) {
        uint8_t pk[FM6_PACKED], got[FM6_PACKED], a[2] = {ED_FM6_USER, 5};
        uint32_t len;
        static upf_t saved;
        reset(); upf_empty(); up_store(5, "KEPT");
        up_rec(5)->engine = ENGI_FM6; up_set_value(up_rec(5), P_E7, 127);
        memcpy(pk, FM6_FACTORY[3], sizeof pk); memcpy(pk + 118, "KEPT PATCH", 10);
        upf_set(5, pk);
        ok = up_load(5) == 0 && TSEL->eng_req == ENGI_FM6 && TSEL->p[P_E7] == 127;
        fm6_pack(fm6_patch[0], got); ok &= !memcmp(pk, got, sizeof pk);
        project_capture(&p);
        ok &= proj_encode(&st, &p) && proj_import(&q, &st, sizeof st) && project_restore_runtime(&q) == 0;
        project_capture(&q);
        ok &= proj_encode(&st2, &q) && !memcmp(&st, &st2, sizeof st) && !memcmp(q.fm6[0], pk, sizeof pk);
        up_store(5, "KEPT AGAIN");
        ok &= !upf_get(5, got) && !memcmp(pk, got, sizeof pk);
        request(ED_FM6_GET, a, sizeof a);
        ok &= host_wire[7] == 0 && !memcmp(host_wire + 8, pk, sizeof pk);
        bad += check("unavailable FM6: preset load -> project round trip -> preset save/editor GET preserves the patch", ok);
        saved = upf;
        ok = ed_bk_object(9, &len) == (const uint8_t *)&upf && len == sizeof upf;
        upf_empty();
        ok &= bk_put_object(9, (const uint8_t *)&saved, sizeof saved) == 0 && !memcmp(&saved, &upf, sizeof upf) &&
              !upf_get(5, got) && !memcmp(pk, got, sizeof pk);
        bad += check("unavailable FM6: backup id 9 restores retained user-preset patches byte for byte", ok);
    }
    return bad;
}

int main(void)
{
    int bad;
    setvbuf(stdout, NULL, _IONBF, 0);
    bad = catalog() + info() + fav() + projects() + presets() + backup() + unavailable_controls() + unavailable_storage();
    printf("%s (NENGINES %u, appended test engine %d, catalog omits %d)\n", bad ? "ENGINE ID TEST FAILED" : "engine id test passed",
           (unsigned)NENGINES, FELUCCA_ENG_TEST14, FELUCCA_ENG_OMIT);
    return bad != 0;
}

#endif
