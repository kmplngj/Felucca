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
 * Main loop only; no interrupt path calls it.
 *
 * Its own translation unit (#454 pilot, docs/modules.md): tools/build.py compiles it apart from felucca.c and links
 * it. sound.h is all a consumer sees of it; sound_port.h is all it sees of the rest of the firmware (sound_port.c,
 * inside felucca.c's unit, implements that). It owns no state (build.py checks: no .data / .bss in its object), so
 * core.h's static objects (trk, song, ENGINE_META) must stay unused here: a copy of them in this unit would be a
 * second, different one. The host builds (tests/hostsim.c) still include it, with sound_port.c, in their one unit;
 * tests/sound_install_test.c also builds it apart (SOUND_SEPARATE). */
#ifdef FELUCCA_OWN_UNIT           /* its own unit: the types, then the two interfaces (else: the including unit's) */
#include "felucca_tables.h"       /* FS, CTL: core.h's engine contract needs them first (unused tables: no bytes) */
#include "core.h"
#endif
#include "sound.h"
#include "sound_port.h"
#ifdef __PI32V2__
void *memcpy(void *d, const void *s, unsigned n);   /* libc.c */
#else
#include <string.h>
#endif

/* the track's settings, not the sound's: what a sound load (factory or user preset, an engine jump,
 * TOOLS INIT) leaves alone. The mix (LEVEL, PAN, MUTE: the TRACKS faders), the arpeggiator (ARP, ARP 2),
 * the scale and key map (SCL), the pattern parameters (LEN, DIV, SWING, GATE; 1.2: QUANTIZE) and the SLICER
 * insert, which chops whatever the track plays in time with its sequencer */
int param_kept(uint32_t i)
{
    return i == P_LEVEL || i == P_PAN || i == P_MUTE || (i >= P_AMODE && i <= P_SGATE) ||
           (i >= P_SLCR && i <= P_SLDEPTH) || i == P_CHRD || i == P_VOIC || i == P_SQNT;
}

/* a retired preset kept as an alias, so stored preset numbers stay valid: SAMPLE 1, once TRANH, is PIANO
 * (tools/gen_samples.py SMP_SET_ORIG). It loads as the original; browsing skips it. -> the preset k stands for.
 * (SAMPLE 4, once PERC, is past SMP_NPRESETS: ui.c apply_preset_to loads it as DRUM) */
uint32_t preset_orig(const engine_t *e, uint32_t k)
{
    return sound_port_preset_alias(e, k);
}

/* the publication guard: the audio interrupt off, the state before it given back (nests in a caller's window) */
static uint32_t sound_guard(void) { return sound_port_lock(); }
static void sound_unguard(uint32_t f) { sound_port_unlock(f); }

/* every common value of the sound in p (before E1..E8) that is not the track's own (param_kept) at its default */
void sound_defaults(int16_t *p)
{
    const param_desc_t *tp = sound_port_params();
    uint32_t i;
    for (i = 0; i < P_E0; i++)
        if (!param_kept(i))
            p[i] = tp[i].def;
}

/* factory preset pr's sound into p as a preset load sets it: the sound's common values at their defaults (a preset
 * sounds the same after any edit), then E1..E8, the ENV, ENV -> FLT, VOICE (a mono preset keeps the legato feel) and
 * the sends (a preset without its own: the defaults below). The track's own values in p are the caller's */
void sound_preset_values(int16_t *p, const preset_t *pr)
{
    static const uint8_t FX_DEF[4] = {0, 24, 28, 36};
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
void sound_install(track_t *t, uint32_t eng, uint32_t preset, const int16_t *p, const uint8_t *patch,
                   uint32_t flags)
{
    uint8_t fv[SND_FM6_PATCH];
    uint32_t i, tr = sound_port_track(t) % NTRK, f;
    int32_t slot = p[P_E7];
    int fslot = 0;
    sound_port_assert_thread();                       /* sound loads are main-loop work (#428; isr_assert.h's state
                                                       * is felucca.c's unit's, so it expands there) */
    if (!patch && (flags & SND_FM6_SLOT) && sound_port_is_fm6(eng) && sound_port_fm6_factory(slot, fv)) {
        patch = fv;                                   /* a factory SLOT: its patch goes in the window with the values */
        fslot = 1;                                    /* (a same-engine reload has no engine-switch fade to hide new
                                                       * values on the old patch from fm6_sync) */
    }
    f = sound_guard();                                /* the audio side sees the old sound or the new one */
    t->eng_req = (uint8_t)eng;
    t->preset = (uint8_t)preset;
    for (i = 0; i < P_COUNT; i++)
        if ((flags & SND_ALL) || !param_kept(i))
            t->p[i] = p[i];
    if (patch)
        sound_port_fm6_set_patch(tr, patch);
    if (flags & SND_PANIC)
        sound_port_panic(tr);
    sound_unguard(f);
    if (fslot)
        sound_port_fm6_slot_loaded(tr, (uint32_t)slot);   /* (fm6_load_slot: nothing of OWN to bring back) */
    else if (patch)
        sound_port_fm6_adopt(tr);                     /* SLOT: the factory patch it equals (F n), else OWN */
    else if (flags & SND_FM6_SLOT)
        sound_port_fm6_track_loaded(t);               /* FM6: the patch of the preset's SLOT */
}

/* engine ei's factory preset pi (wrapped; an alias loads as its original, preset_orig) as track t's sound: the
 * track's own values stay. An engine without presets keeps the sound's other values and its preset number
 * (SND_EDIT_DEF: E1..E8 at the engine's defaults). ei is a valid id of this build (eng_ok) */
void sound_load_factory(track_t *t, uint32_t ei, uint32_t pi, uint32_t flags)
{
    const engine_t *e = sound_port_engine(ei);
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
