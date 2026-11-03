/* SPDX-License-Identifier: GPL-3.0-only
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Frozen original scan functions from f101979be19de475a6733e917bccc07733c87a65.
 * Reference only: preserve independently of the candidate mask walker. */
static void motion_restore(track_t *t)
{
    uint32_t k = trk_index(t), id, f = motion_guard();
    for (id = 0; id < P_COUNT; id++)
        if ((motion_active[k][id / 32u] >> (id % 32u)) & 1u) t->p[id] = motion_base[k][id];
    memset(motion_active[k], 0, sizeof motion_active[k]);
    memset(motion_locked[k], 0, sizeof motion_locked[k]);
    motion_unguard(f);
}

static __attribute__((noinline)) void motion_unlock(track_t *t, uint32_t step, const motion_store_t *m)
{
    uint32_t k = trk_index(t), id, i;
    for (id = 0; id < P_COUNT; id++) {
        int32_t best = -1;
        int16_t v;
        if (!((motion_locked[k][id / 32u] >> (id % 32u)) & 1u))
            continue;
        v = motion_base[k][id];
        for (i = 0; i < m->count; i++) {
            const motion_event_t *e = &m->event[i];
            int32_t s = (int32_t)(e->place & 63u);
            if ((e->place >> 6) != k || e->param != id || s > (int32_t)step || s <= best)
                continue;                               /* (e->param == id: automation only, no MOTION_LOCK) */
            best = s;
            v = (int16_t)param_fit(param_desc_of(eng_idx(t->eng_req), id), e->value);
        }
        t->p[id] = v;
    }
    memset(motion_locked[k], 0, sizeof motion_locked[k]);
}
