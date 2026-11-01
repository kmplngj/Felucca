/* SPDX-License-Identifier: GPL-3.0-only */
/* Sound install (#298): the one path that puts a sound into a track. Every entry point ends here: the panel's
 * engine / preset choice, INIT and CLEAN INIT, MIDI Program Change, a user preset, a project or the autosave, undo,
 * the editor's loads (through those), a retired DIGITAL sound once converted (ui.c fm4_apply) and the host renders
 * behind the DSP goldens (tests/hostsim.c host_preset).
 *
 * It owns the publication: the engine id (eng_req), the preset number and the values change as one sound under one
 * interrupt guard, so the audio side (voice.c engine_block, the renders) sees the old engine with its values or the
 * new one with its own, never one with the other's; with an FM6 patch of the caller's (or the factory patch the new
 * SLOT names: SND_FM6_SLOT), that patch too (fm6_pgen: the renderer takes it at its next block; an FM6 track reloaded
 * as FM6 has no engine-switch fade, so fm6_sync must not see the new values on the old patch). The guard saves and
 * restores the interrupt state, so an install nests in a caller's own IRQ-off window (a project restores four tracks
 * and its motion in one). After the guard: the FM6 slot's bookkeeping (fm6_adopt, fm6_slot: main-loop state no render
 * reads, outside the window). Values a future sound carries
 * beside p[] (an engine's extension, #324) belong in the same window; the fading old engine's copy of them is
 * voice.c engine_block's, as pe_old[] is.
 *
 * It owns no UI state: the callers keep their undo copy (ui.c load_begin / load_end, which also pause and rebase the
 * track's motion around the load), their messages, sync_reload / ui.force, the user preset slot (t->user), and the
 * translation of retired sounds (DIGITAL, PHYS, SAMPLE PERC: #299 / #456), which hands its result to this module.
 * Main loop only; no interrupt path calls it. Included before ui.c (felucca.c) and by tests/hostsim.c. */
#include "isr_assert.h"

#define SND_PANIC 1u      /* release what the track sounds (its MONO/POLY or engine may change) */
#define SND_ALL 2u        /* every value, the track's own (param_kept) too: a project's track, a converted sound */
#define SND_FM6_SLOT 4u   /* FM6: the patch the new SLOT (E8) names (a factory sound); without patch only */
#define SND_EDIT_DEF 8u   /* sound_load_factory: E1..E8 at the engine's defaults first (an engine change) */

/* the track's settings, not the sound's: what a sound load (factory or user preset, an engine jump,
 * TOOLS INIT) leaves alone. The mix (LEVEL, PAN, MUTE: the TRACKS faders), the arpeggiator (ARP, ARP 2),
 * the scale and key map (SCL), the pattern parameters (LEN, DIV, SWING, GATE; 1.2: QUANTIZE) and the SLICER
 * insert, which chops whatever the track plays in time with its sequencer */
static int param_kept(uint32_t i)
{
    return i == P_LEVEL || i == P_PAN || i == P_MUTE || (i >= P_AMODE && i <= P_SGATE) ||
           (i >= P_SLCR && i <= P_SLDEPTH) || i == P_CHRD || i == P_VOIC || i == P_SQNT;
}

/* a retired preset kept as an alias, so stored preset numbers stay valid: SAMPLE 1, once TRANH, is PIANO
 * (tools/gen_samples.py SMP_SET_ORIG). It loads as the original; browsing skips it. -> the preset k stands for.
 * (SAMPLE 4, once PERC, is past SMP_NPRESETS: ui.c apply_preset_to loads it as DRUM) */
static uint32_t preset_orig(const engine_t *e, uint32_t k)
{
    return e->presets == SMP_PRESET_TABLE && k < SMP_NSETS ? SMP_SET_ORIG[k] : k;
}

/* the publication guard: the audio interrupt off, the state before it given back (nests in a caller's window) */
static uint32_t sound_guard(void)
{
#if defined(FM1_IRQ_TARGET)
    uint32_t f = fm1_icfg();
    fm1_irq_off();
    return f;
#else
    return 0;
#endif
}
static void sound_unguard(uint32_t f)
{
#if defined(FM1_IRQ_TARGET)
    fm1_icfg_set(f);
#else
    (void)f;
#endif
}

/* #147 (voice.c note_hit): main-loop reset of one part's note events, guarded against the audio-event owner:
 * NOTE_HIT_SLOTS stores. Main loop only (sound_install; the LED service: ui_input.c) */
static void note_hits_clear(uint32_t part)
{
    uint32_t i, f = sound_guard();
    for (i = 0; i < NOTE_HIT_SLOTS; i++)
        note_hit[part % NPART][i] = 0;
    sound_unguard(f);
}

/* an event older than this is dropped by the sweep: far past any reader's window, far short of the 24-bit time's wrap
 * (4.6 h), so an idle part's old note never comes back as a new one */
#define NOTE_HIT_STALE_MS 4096u
/* drop the stale events (a rare clear per event: the interrupt off for one compare and store, and only if the slot
 * still holds the word seen, so a note-on that refreshed it in between is kept). Main loop only, every few seconds */
static void note_hits_sweep(void)
{
    uint32_t now = fm1_ms, p, i, w, f;
    for (p = 0; p < NPART; p++)
        for (i = 0; i < NOTE_HIT_SLOTS; i++) {
            w = note_hit[p][i];
            if (!(w & NOTE_HIT_VALID) || note_hit_age(now, w) < NOTE_HIT_STALE_MS)
                continue;
            f = sound_guard();
            if (note_hit[p][i] == w)
                note_hit[p][i] = 0;
            sound_unguard(f);
        }
}

/* every common value of the sound in p (before E1..E8) that is not the track's own (param_kept) at its default */
static void sound_defaults(int16_t *p)
{
    uint32_t i;
    for (i = 0; i < P_E0; i++)
        if (!param_kept(i))
            p[i] = TP[i].def;
}

/* factory preset pr's sound into p as a preset load sets it: the sound's common values at their defaults (a preset
 * sounds the same after any edit), then E1..E8, the ENV, ENV -> FLT, VOICE (a mono preset keeps the legato feel) and
 * the sends (a preset without its own: the defaults below). The track's own values in p are the caller's */
static void sound_preset_values(int16_t *p, const preset_t *pr)
{
    uint32_t i;
    sound_defaults(p);
    for (i = 0; i < 8u; i++)
        p[P_E0 + i] = (int16_t)pr->e[i];
    p[P_ATK] = pr->env[0];
    p[P_DEC] = pr->env[1];
    p[P_SUS] = pr->env[2];
    p[P_REL] = pr->env[3];
    p[P_ED_FLT] = pr->fenv;
    p[P_VOICE] = pr->mono ? V_LEGATO : V_POLY;
    for (i = 0; i < 4u; i++)
        p[P_DIST + i] = (int16_t)(pr->fx[i] ? pr->fx[i] - 1 : FX_DEF[i]);
}

/* track t's sound = engine id eng, preset number preset, values p (the track's own ones only with SND_ALL), with an
 * FM6 patch (FP_SIZE + 1 bytes, unpacked) as the track's own or 0. flags SND_*. Main loop only */
static void sound_install(track_t *t, uint32_t eng, uint32_t preset, const int16_t *p, const uint8_t *patch,
                          uint32_t flags)
{
    uint8_t fv[FP_SIZE + 1u];
    uint32_t i, tr = trk_index(t) % NTRK, f;
    int32_t slot = p[P_E7];
    int fslot = 0;
    FM1_ASSERT_THREAD();                              /* sound loads are main-loop work (#428) */
    if (!patch && (flags & SND_FM6_SLOT) && eng_is(eng, ENGI_FM6) && slot >= 0 && slot < (int32_t)FM6_NFACTORY) {
        fm6_unpack(FM6_FACTORY[slot], fv);            /* a factory SLOT: its patch goes in the window with the values */
        patch = fv;                                   /* (a same-engine reload has no engine-switch fade to hide */
        fslot = 1;                                    /* new values on the old patch from fm6_sync) */
    }
    f = sound_guard();                                /* the audio side sees the old sound or the new one */
    t->eng_req = (uint8_t)eng;
    t->preset = (uint8_t)preset;
    for (i = 0; i < P_COUNT; i++)
        if ((flags & SND_ALL) || !param_kept(i))
            t->p[i] = p[i];
    if (patch)
        fm6_set_patch(tr, patch);
    if (flags & SND_PANIC)
        panic_req |= (uint8_t)(1u << tr);
    note_hits_clear(tr);                              /* (#147: the old sound's note events are not the new one's) */
    sound_unguard(f);                                  /* a new-sound note-on may run as soon as this publishes */
    if (fslot) {
        fm6_own_ok &= (uint8_t)~(1u << tr);           /* (fm6_load_slot: nothing of OWN to bring back) */
        fm6_slot[tr] = (uint8_t)slot;
    } else if (patch) {
        fm6_adopt(tr);                                /* SLOT: the factory patch it equals (F n), else OWN */
    } else if (flags & SND_FM6_SLOT)
        fm6_track_loaded(t);                          /* FM6: the patch of the preset's SLOT */
}

/* engine ei's factory preset pi (wrapped; an alias loads as its original, preset_orig) as track t's sound: the
 * track's own values stay. An engine without presets keeps the sound's other values and its preset number
 * (SND_EDIT_DEF: E1..E8 at the engine's defaults). ei is a valid id of this build (eng_ok) */
static void sound_load_factory(track_t *t, uint32_t ei, uint32_t pi, uint32_t flags)
{
    const engine_t *e = eng_of(ei);
    int16_t p[P_COUNT];
    uint32_t i, pr = t->preset;
    memcpy(p, t->p, sizeof p);
    if (flags & SND_EDIT_DEF)
        for (i = 0; i < 8u; i++)
            p[P_E0 + i] = e->edit[i].def;
    if (e->npresets) {
        pr = preset_orig(e, pi % e->npresets);
        sound_preset_values(p, &e->presets[pr]);
    }
    sound_install(t, ei, pr, p, 0, (flags & SND_PANIC) | SND_FM6_SLOT);
}
