/* SPDX-License-Identifier: GPL-3.0-only */
/* Sound install (#298): the public interface of sound.c, the first module compiled as its own translation unit
 * (#454 pilot, docs/modules.md). Include after core.h (track_t, engine_t, preset_t, P_COUNT); core.h has no include
 * guard and defines state, so this header does not include it.
 *
 * What a consumer (ui.c, upreset.c, project.c, hostsim.c) may use is declared here; everything else of sound.c is
 * private to it. What sound.c needs from the rest of the firmware is declared in sound_port.h, not reached through
 * felucca.c's include order. Main loop only: no interrupt path may call these (tools/size_fns.py rejects
 * ISR-reachable code that calls a function defined outside felucca.c's translation unit). */
#pragma once
#include <stdint.h>

#define SND_PANIC 1u      /* release what the track sounds (its MONO/POLY or engine may change) */
#define SND_ALL 2u        /* every value, the track's own (param_kept) too: a project's track, a converted sound */
#define SND_FM6_SLOT 4u   /* FM6: the patch the new SLOT (E8) names (a factory sound); without patch only */
#define SND_EDIT_DEF 8u   /* sound_load_factory: E1..E8 at the engine's defaults first (an engine change) */
#define SND_FM6_PATCH 156u   /* bytes of an unpacked FM6 patch, FP_SIZE + 1 (fm6_core.c; sound_port.c checks it) */

/* parameter i is the track's own setting, not the sound's: a sound load leaves it alone */
int param_kept(uint32_t i);
/* the preset factory preset k of engine e stands for (a retired alias loads as its original) */
uint32_t preset_orig(const engine_t *e, uint32_t k);
/* every common value of the sound in p (before E1..E8) that is not the track's own at its default */
void sound_defaults(int16_t *p);
/* factory preset pr's sound into p as a preset load sets it; the track's own values in p are the caller's */
void sound_preset_values(int16_t *p, const preset_t *pr);
/* track t's sound = engine id eng, preset number preset, values p, FM6 patch (SND_FM6_PATCH bytes) or 0; SND_* */
void sound_install(track_t *t, uint32_t eng, uint32_t preset, const int16_t *p, const uint8_t *patch,
                   uint32_t flags);
/* engine ei's factory preset pi as track t's sound: the track's own values stay; SND_PANIC, SND_EDIT_DEF */
void sound_load_factory(track_t *t, uint32_t ei, uint32_t pi, uint32_t flags);
