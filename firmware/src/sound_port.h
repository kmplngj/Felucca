/* SPDX-License-Identifier: GPL-3.0-only */
/* What sound.c (#298) requires from the rest of the firmware: the explicit replacement for what it used to take from
 * the files felucca.c included before it (#454 pilot, docs/modules.md). sound_port.c implements it inside felucca.c's
 * translation unit, from the owners' own static functions and state, which stay static there; so the audio code that
 * uses those owners compiles exactly as before. Include after core.h. Main loop only. */
#pragma once
#include <stdint.h>

/* static inline in the one translation unit: the wrappers vanish into their callers (0 B); external when sound.c is its
 * own unit (-DFELUCCA_OWN_UNIT / -DSOUND_SEPARATE, docs/modules.md) */
#if defined(FELUCCA_OWN_UNIT) || defined(SOUND_SEPARATE)
#define SND_PORT
#else
#define SND_PORT static inline
#endif

SND_PORT const param_desc_t *sound_port_params(void);          /* params.c TP: the track parameters' descriptors (P_COUNT) */
SND_PORT const engine_t *sound_port_engine(uint32_t id);        /* engines.c eng_of: id's engine (ENG_NONE where none) */
SND_PORT int sound_port_is_fm6(uint32_t id);                    /* engines.c eng_is(id, ENGI_FM6) */
SND_PORT uint32_t sound_port_preset_alias(const engine_t *e, uint32_t k);   /* eng_sample.c: SAMPLE's retired preset aliases */
SND_PORT uint32_t sound_port_track(const track_t *t);           /* seq.c trk_index: t's index in trk[] */
SND_PORT uint32_t sound_port_lock(void);                        /* the audio interrupt off; the state before it (nests) */
SND_PORT void sound_port_unlock(uint32_t f);                    /* .. given back */
SND_PORT void sound_port_panic(uint32_t tr);                    /* seq.c panic_req: release what track tr sounds */
SND_PORT int sound_port_fm6_slot_ok(int32_t slot);              /* a factory FM6 patch slot of this build */
SND_PORT void sound_port_fm6_unpack(int32_t slot, uint8_t *v);  /* eng_fm6.c fm6_unpack: factory slot (slot_ok) into v */
SND_PORT void sound_port_fm6_set_patch(uint32_t tr, const uint8_t *v);       /* eng_fm6.c fm6_set_patch */
SND_PORT void sound_port_fm6_slot_loaded(uint32_t tr, uint32_t slot);        /* a factory SLOT loaded: no OWN to bring back */
SND_PORT void sound_port_fm6_adopt(uint32_t tr);                /* eng_fm6.c fm6_adopt: SLOT = the factory patch it equals */
SND_PORT void sound_port_fm6_track_loaded(const track_t *t);    /* eng_fm6.c fm6_track_loaded: the patch of the SLOT */
SND_PORT void sound_port_assert_thread(void);                   /* FM1_ASSERT_THREAD, in the unit that owns its state */
