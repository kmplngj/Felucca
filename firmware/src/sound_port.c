/* SPDX-License-Identifier: GPL-3.0-only */
/* sound_port.h, implemented inside felucca.c's translation unit (and the host builds' tests/hostsim.c), where the owners'
 * static functions and state are visible: sound.c (#298) reaches them only through these. The wrappers can inline in
 * the single unit; they are external only in the dormant separate-compilation pilot (#454). The owners' functions stay
 * static. Compare target output after integration (docs/modules.md). Included where
 * sound.c was (felucca.c: after its providers, before its consumers). Main loop only (docs/modules.md). */
#include "isr_assert.h"
#include "sound_port.h"
#include "sound.h"

_Static_assert(SND_FM6_PATCH == FP_SIZE + 1u, "sound.h SND_FM6_PATCH: an unpacked FM6 patch (fm6_core.c FP_SIZE + 1)");

SND_PORT const param_desc_t *sound_port_params(void) { return TP; }
SND_PORT const engine_t *sound_port_engine(uint32_t id) { return eng_of(id); }
SND_PORT int sound_port_is_fm6(uint32_t id) { return eng_is(id, ENGI_FM6); }
/* SAMPLE 1, once TRANH, is PIANO (tools/gen_samples.py SMP_SET_ORIG); SAMPLE 4, once PERC, is past SMP_NPRESETS */
SND_PORT uint32_t sound_port_preset_alias(const engine_t *e, uint32_t k)
{
    return e->presets == SMP_PRESET_TABLE && k < SMP_NSETS ? SMP_SET_ORIG[k] : k;
}
SND_PORT uint32_t sound_port_track(const track_t *t) { return trk_index(t); }

/* the publication guard: the audio interrupt off, the state before it given back (nests in a caller's window) */
SND_PORT uint32_t sound_port_lock(void)
{
#if defined(FM1_IRQ_TARGET)
    uint32_t f = fm1_icfg();
    fm1_irq_off();
    return f;
#else
    return 0;
#endif
}
SND_PORT void sound_port_unlock(uint32_t f)
{
#if defined(FM1_IRQ_TARGET)
    fm1_icfg_set(f);
#else
    (void)f;
#endif
}
SND_PORT void sound_port_panic(uint32_t tr) { panic_req |= (uint8_t)(1u << tr); }   /* tr < NTRK (sound_port_track) */

SND_PORT int sound_port_fm6_slot_ok(int32_t slot) { return slot >= 0 && slot < (int32_t)FM6_NFACTORY; }
SND_PORT void sound_port_fm6_unpack(int32_t slot, uint8_t *v) { fm6_unpack(FM6_FACTORY[slot], v); }
SND_PORT void sound_port_fm6_set_patch(uint32_t tr, const uint8_t *v) { fm6_set_patch(tr, v); }
SND_PORT void sound_port_fm6_slot_loaded(uint32_t tr, uint32_t slot)
{                                                     /* tr < NTRK (sound_port_track) */
    fm6_own_ok &= (uint8_t)~(1u << tr);               /* (fm6_load_slot: nothing of OWN to bring back) */
    fm6_slot[tr] = (uint8_t)slot;
}
SND_PORT void sound_port_fm6_adopt(uint32_t tr) { fm6_adopt(tr); }
SND_PORT void sound_port_fm6_track_loaded(const track_t *t) { fm6_track_loaded(t); }
/* isr_assert.h keeps its counter (target, with the HAL's crash state behind it) or depth (host) in static state: a
 * copy per translation unit, so sound.c must not expand FM1_ASSERT_THREAD itself (its copy would never count, never
 * see a simulated interrupt). Empty without FELUCCA_ISR_ASSERT */
SND_PORT void sound_port_assert_thread(void) { FM1_ASSERT_THREAD(); }
SND_PORT uint32_t sound_port_fx_default(uint32_t i) { return FX_DEF[i]; }
