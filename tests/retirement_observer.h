/* SPDX-License-Identifier: GPL-3.0-only */
/* Included ONLY in frozen host copies of voice.c by retirement_measure.py.
 * Deliberately performs file IO: never include this in production firmware. */
#ifndef RV_COUNTERFACTUAL
#define RV_COUNTERFACTUAL 0
#endif
static uint64_t rv_block_visits, rv_inactive_gate_slots;
static uint32_t rv_last_mask[NPART];
static void rv_write(const char *s, int n)
{
    const char *path = getenv("RETIREMENT_EVENTS");
    FILE *f;
    if (!path) return;
    /* stdio, not <fcntl.h>: hostsim.c blanks __attribute__, which breaks glibc's fortified open() */
    f = fopen(path, "a");
    if (!f || fwrite(s, 1, (size_t)n, f) != (size_t)n || fclose(f) != 0) {
        perror("retirement observer");
        exit(2);
    }
}
static void rv_observe_block(track_t *t)
{
    uint32_t i, mask = 0, part = (uint32_t)(t - trk);
    char line[512];
    if (part >= NPART) return;
    rv_block_visits++;
    for (i = 0; i < NVOICE; i++)
        if (!t->v[i].active && t->v[i].gate) {
            mask |= 1u << i;
            rv_inactive_gate_slots++;
        }
    /* Transitions retain the phenomenon without a per-block multi-megabyte log.
     * Cumulative slot-block counts include unchanged masks and are sampled here
     * and at every note event, not claimed as final process-wide totals. */
    if (mask != rv_last_mask[part]) {
        rv_write(line, snprintf(line, sizeof line,
            "{\"kind\":\"block_transition\",\"pid\":%ld,\"part\":%u,\"engine\":%u,"
            "\"inactive_gate_mask\":%u,\"block_visits\":%llu,\"inactive_gate_slot_blocks\":%llu}\n",
            (long)getpid(), part, t->eng_req, mask,
            (unsigned long long)rv_block_visits, (unsigned long long)rv_inactive_gate_slots));
        rv_last_mask[part] = mask;
    }
}
static uint32_t rv_phrase_gates(track_t *t, uint32_t note)
{
    uint32_t i, all = 0, live = 0, inactive = 0;
    char line[768];
    for (i = 0; i < NVOICE; i++)
        if (t->v[i].gate) {
            all |= 1u << i;
            if (t->v[i].active) live |= 1u << i;
            else inactive |= 1u << i;
        }
    rv_write(line, snprintf(line, sizeof line,
        "{\"kind\":\"note\",\"pid\":%ld,\"part\":%u,\"engine\":%u,\"note\":%u,"
        "\"ltrig\":%d,\"all_gate_mask\":%u,\"active_gate_mask\":%u,\"inactive_gate_mask\":%u,"
        "\"note_reset_suppressed_by_inactive_only\":%u,\"phase_before\":%u,\"fade_before\":%d,"
        "\"configured_phase\":%u,\"counterfactual\":%u,\"block_visits\":%llu,"
        "\"inactive_gate_slot_blocks\":%llu}\n",
        (long)getpid(), (unsigned)(t - trk), t->eng_req, note, t->p[P_LTRIG], all, live, inactive,
        !t->p[P_LTRIG] && inactive && !live, t->lfo_ph, t->lfo_fade,
        (uint32_t)t->p[P_LPHASE] << 25, RV_COUNTERFACTUAL,
        (unsigned long long)rv_block_visits, (unsigned long long)rv_inactive_gate_slots));
    /* The ONLY behavioral counterfactual: exclude inactive gates from the
     * fresh-phrase predicate. Never mutate gate/active/stage/env or ownership. */
    return RV_COUNTERFACTUAL ? live : all;
}
