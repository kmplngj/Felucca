/* SPDX-License-Identifier: GPL-3.0-only */
/* What sound.c (#298) requires from the rest of the firmware: the explicit replacement for what it used to take from
 * the files felucca.c included before it (#454 pilot, docs/modules.md). sound_port.c implements it inside felucca.c's
 * translation unit, from the owners' own static functions and state, which stay static there; so the audio code that
 * uses those owners compiles exactly as before. Include after core.h. Main loop only. */
#pragma once
#include <stdint.h>

const param_desc_t *sound_port_params(void);          /* params.c TP: the track parameters' descriptors (P_COUNT) */
const engine_t *sound_port_engine(uint32_t id);        /* engines.c eng_of: id's engine (ENG_NONE where none) */
int sound_port_is_fm6(uint32_t id);                    /* engines.c eng_is(id, ENGI_FM6) */
uint32_t sound_port_preset_alias(const engine_t *e, uint32_t k);   /* eng_sample.c: SAMPLE's retired preset aliases */
uint32_t sound_port_track(const track_t *t);           /* seq.c trk_index: t's index in trk[] */
uint32_t sound_port_lock(void);                        /* the audio interrupt off; the state before it (nests) */
void sound_port_unlock(uint32_t f);                    /* .. given back */
void sound_port_panic(uint32_t tr);                    /* seq.c panic_req: release what track tr sounds */
int sound_port_fm6_factory(int32_t slot, uint8_t *v);  /* FM6 factory patch slot unpacked into v; 0: no such slot */
void sound_port_fm6_set_patch(uint32_t tr, const uint8_t *v);       /* eng_fm6.c fm6_set_patch */
void sound_port_fm6_slot_loaded(uint32_t tr, uint32_t slot);        /* a factory SLOT loaded: no OWN to bring back */
void sound_port_fm6_adopt(uint32_t tr);                /* eng_fm6.c fm6_adopt: SLOT = the factory patch it equals */
void sound_port_fm6_track_loaded(const track_t *t);    /* eng_fm6.c fm6_track_loaded: the patch of the SLOT */
void sound_port_assert_thread(void);                   /* FM1_ASSERT_THREAD, in the unit that owns its state */
