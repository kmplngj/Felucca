/* SPDX-License-Identifier: GPL-3.0-only */
/* Panel knob editing (#295): which value KNOB 1..4 edits in a panel context, and how a turn edits it. HOME, MIXER,
 * a parameter page's cell, the GLO layer and MOMENTARY (LFO held) all resolve their value here and turn it here, so
 * the turning arithmetic, the automation capture and the MIDI LEARN pick are decided once.
 *
 * Navigation and gesture arbitration stay with their owners (ui_input.c ui_input / edit_param, ui_layer.c layer_knob):
 * a quick layer's precedence, the encoder deltas a layer consumed, step locks (lock_turn), the pages whose knobs pick
 * or act (lists, STEP, AUTOMATION, SLICES' markers, FM6's operators, MOD's slot, BROWSE ..), the hot column and the
 * messages' priority. Resolving a target (knob_*, mom_target) never writes a value, captures, picks or reads an encoder;
 * only knob_edit, knob_default and mom_turn write. Main loop only; no state of its own beyond MOMENTARY's (ui.c mom).
 *
 * The callers, as they were before this module (kept exactly; the cells marked * are deliberate differences):
 *
 *   context        KNOB k's value                         turn                      capture + LEARN   MOMENTARY
 *   HOME           selected track's engine knob[k]        param_turn, accel once    the track         yes
 *   HOME LEVELS    track k's LEVEL                        param_turn, accel once    track k           yes
 *   MIXER K1..K3   selected track's LEVEL PAN REV         param_turn, accel once    the track         yes
 *   MIXER K4       selected track's MUTE                  * by direction, no accel  * LEARN only      * numeric turn
 *   page, track    page_desc (TSEL; MOD: its slot's)      param_turn, accel once    the track         eligible pages
 *   page, global   page_desc (song.g)                     param_turn, accel once    * neither         FX values, RTYPE
 *   GLO layer      track k's LEVEL                        param_turn, accel once    track k           no (a layer)
 *
 * "param_turn, accel once": accel(EN_K1 + k) over the descriptor's range (0, no acceleration, for a list of names),
 * then param_turn (bounds, enum order and aliases). A fixed value (min == max) or an empty cell is not edited anywhere
 * (knob_live, in knob_edit and mom_target): no turn, no capture, no LEARN pick; HOME as the pages and MOMENTARY (#295
 * follow-up). Capture (motion.c motion_capture) records only while the track is armed and playing; LEARN
 * (midi_learn.c ml_knob) picks only while MIDI LEARN is on. */

static int32_t accel(uint32_t role, int32_t s, int32_t range);   /* (ui_input.c) */
static uint64_t lock_held(void);                                   /* (ui_input.c) */

typedef struct {
    track_t *t;                  /* the track whose value it is; 0: a global one (song.g) */
    int16_t *vp;                 /* the value; 0: none (an empty cell) */
    const param_desc_t *d;       /* its descriptor (a dynamic one as track_desc gives it) */
    uint8_t dir;                 /* 1: a permanent turn sets it by direction (MIXER MUTE: right ON, left OFF) */
} knob_target_t;

/* HOME: KNOB k's value (MENU > HOME LEVELS: track k's LEVEL; else the selected track's engine knob, ui.c home_param) */
static void knob_home(uint32_t k, knob_target_t *kt)
{
    kt->d = home_param(k, &kt->vp);
    kt->t = home_trk(k);
    kt->dir = 0;
}
/* MIXER: KNOB 1 LEVEL, 2 PAN, 3 REV send, 4 MUTE of the selected track (right = ON, left = OFF: the track itself is
 * ALGORITHM's, on every page). Pattern length stays on SEQ */
static void knob_mixer(uint32_t k, knob_target_t *kt)
{
    static const uint8_t MIX_ID[4] = {P_LEVEL, P_PAN, P_REV, P_MUTE};
    uint32_t id = MIX_ID[k & 3u];
    kt->t = TSEL;
    kt->vp = &TSEL->p[id];
    kt->d = &TP[id];
    kt->dir = id == P_MUTE;
}
/* the GLO layer: KNOB k track k's LEVEL, as HOME LEVELS and MIXER's KNOB 1 */
static void knob_glo(uint32_t k, knob_target_t *kt)
{
    kt->t = &trk[k & 3u];
    kt->vp = &kt->t->p[P_LEVEL];
    kt->d = &TP[P_LEVEL];
    kt->dir = 0;
}
/* a parameter page's cell k (params.c page_desc: the selected track's, or a global one); 0 = an empty cell */
static int knob_page(const page_t *pg, uint32_t k, knob_target_t *kt)
{
    kt->d = page_desc(pg, k, &kt->vp);
    kt->t = pg->scope == SC_GLOBAL ? 0 : TSEL;
    kt->dir = 0;
    return kt->d && kt->vp;
}
/* KNOB k's value in the panel context shown (HOME, MIXER or the page's cell; not a layer's): 0 = none */
static int knob_here(uint32_t k, knob_target_t *kt)
{
    const page_t *pg = cur_page();
    if (ui.home) {
        knob_home(k, kt);
        return 1;
    }
    if (pg->scope == SC_TRK) {
        knob_mixer(k, kt);
        return 1;
    }
    return knob_page(pg, k, kt);
}
/* a value a turn can change (not an empty cell, not a fixed one) */
static int knob_live(const knob_target_t *kt)
{
    return kt->d && kt->vp && kt->d->max != kt->d->min;
}
/* the value KNOB k turned s detents gives (accel once over the range, then the descriptor's bounds and order). No
 * write; accel keeps the knob's timing */
static int16_t knob_value(const knob_target_t *kt, uint32_t k, int32_t s)
{
    const param_desc_t *d = kt->d;
    return (int16_t)param_turn(d, *kt->vp, accel(EN_K1 + k, s, d->fmt == F_ENUM ? 0 : d->max - d->min));
}
/* publish a permanent edit, then (a track's) automation capture and MIDI LEARN pick. A global value is neither;
 * MIXER's MUTE is only picked. Both ordinary turns and declared-default edits keep this policy */
static void knob_put(const knob_target_t *kt, int16_t value)
{
    uint32_t id;
    *kt->vp = value;
    if (!kt->t)
        return;
    id = (uint32_t)(kt->vp - kt->t->p);
    if (!kt->dir)
        motion_capture(kt->t, id, *kt->vp);
    ml_knob(kt->t, id);                                 /* (MIDI LEARN: picked) */
}
/* a live permanent turn: acceleration once, or MIXER's MUTE set by direction.
 * Reject fixed/empty targets before value calculation, capture and LEARN. */
static void knob_edit(const knob_target_t *kt, uint32_t k, int32_t s)
{
    if (!knob_live(kt))
        return;
    knob_put(kt, kt->dir ? (int16_t)(s > 0) : knob_value(kt, k, s));
}
/* ENV + knob (#569), inspired by X0X 102c47b9's single-knob-default gesture. The caller resolves a live sound/FX
 * target afresh (engine mode, INSERT and ENV SYNC may change its descriptor). An alias takes its current value
 * as an editor SET does; never use a preset snapshot. 1 consumes even an already-default detent: no acceleration,
 * temporary cache or no-op side effects */
static int knob_default(const knob_target_t *kt)
{
    int16_t value;
    if (!knob_live(kt))
        return 0;
    value = (int16_t)enum_orig(kt->d, param_fit(kt->d, kt->d->def));
    if (*kt->vp != value)
        knob_put(kt, value);
    return 1;
}

/* MOMENTARY (ui_input.c): a page whose knobs can be momentary (mom_target's page tests; a knob or two more there
 * refuse) */
static int mom_page(void)
{
    const page_t *pg = cur_page();
    if (ui.home || (pg->scope == SC_TRK && !lock_held()))
        return 1;
    return !(act_cols() || lock_held() || !(pg->scope == SC_TRACK || pg->scope == SC_ENGINE || pg->scope == SC_GLOBAL) ||
             pg->graph == GR_EVENTS || pg->graph == GR_SONG || pg->graph == GR_BROWSE || pg->graph == GR_USER ||
             pg->graph == GR_PATS);
}
/* KNOB k's momentary value here (HOME, MIXER's LEVEL PAN REV MUTE #195, or a sound / FX page's value, as a permanent
 * turn finds it), 1 = one; 0: none (the turn goes as ever). Only the values a sound and the FX are: no CLK, no actions.
 * No side effect (ui_input.c mom_status reads it every pass) */
static int mom_target(uint32_t k, knob_target_t *kt)
{
    const page_t *pg = cur_page();
    uint32_t g;
    if (!mom_page() || (!ui.home && ((pg->graph == GR_SLICES && k < 2u) || (pg->graph == GR_MOD && k == 0u))) ||
        !knob_here(k, kt) || !knob_live(kt))
        return 0;
    if (kt->t)
        return kt->vp < kt->t->p + P_COUNT;
    g = (uint32_t)(kt->vp - song.g);
    return (g <= G_CDEPTH && g != G_CLOCK) || g == G_RTYPE;
}
/* #569 keeps global resets on FX pages. MOMENTARY historically also accepts CLOCK's BPM/SWING; their existing
 * temporary-turn behavior stays separate from this sound-default gesture. */
static int knob_default_target(uint32_t k, knob_target_t *kt)
{
    const page_t *pg = cur_page();
    return (ui.home || pg->scope != SC_GLOBAL || pg->fam == FAM_FX) && mom_target(k, kt);
}
/* KNOB k turned s with LFO held: 1 = taken (a momentary value, or refused full), 0 = not a momentary value (the turn
 * goes as ever: the column picks, steps, acts). No capture, no undo, no LEARN pick; MIXER's MUTE turns as a number here
 * (not by direction as a permanent turn: #195 kept) */
static int mom_turn(uint32_t k, int32_t s)
{
    knob_target_t kt;
    uint32_t i;
    if (!mom_target(k, &kt))
        return 0;
    for (i = 0; i < mom.n && mom.vp[i] != kt.vp; i++)
        ;
    if (i == mom.n) {                                  /* the first turn of this value: what it was */
        if (mom.n >= MOM_N) {
            ui_message("MOMENTARY FULL");
            return 1;
        }
        mom.vp[i] = kt.vp;
        mom.v[i] = *kt.vp;
        mom.n++;
        mom.kept = 0;
        if (i == 0u)
            ui_message("MOMENTARY  [OCT+] KEEP");
    }
    *kt.vp = knob_value(&kt, k, s);
    return 1;
}
