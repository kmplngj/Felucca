/* SPDX-License-Identifier: GPL-3.0-only */
/* Sound install (#298, firmware/src/sound.c): the publication invariant. Every way a sound goes into a track (the
 * PRESETS knob on the same engine, an engine change, TOOLS INIT and CLEAN INIT, MIDI Program Change, a user preset,
 * undo, a project, a retired DIGITAL sound converted) must change the track's engine id, preset number and sound values
 * inside ONE interrupt-off window: an audio interrupt, wherever it comes, sees the old sound whole or the new one whole.
 *
 * The audio interrupt is emulated at the only places the main loop lets it in around a guarded section: each time the
 * interrupt mask goes off -> on (a pending interrupt runs at once) and just before it goes on -> off (the latest
 * moment one can still run), plus before and after the load. At each such point the probe records whether the track
 * holds the old sound, the new one or a mixture. Passing needs: no mixture ever, and the change from old to new
 * between one mask-on edge and the next mask-off edge (one window). A write outside any window shows as a mixture at
 * the next edge, or as old -> new without a window between (the PRESETS knob's preset values written with the
 * interrupt enabled before #298). An FM6 sound's SLOT (E8: main-loop state no render reads) is normalized after the
 * window by fm6_adopt, as before, and is left out of the comparison for FM6.
 *   cc -w -Ibuild/gen -Ifirmware/src -o build/host/sound_install_test tests/sound_install_test.c -lm */
#define UI_TEST_NO_MAIN 1
#include <stdint.h>
#define HOST_IRQ_STUBS 1
#define FM1_IRQ_TARGET 1
static int host_mask;
static void si_edge(int masking);
static uint32_t fm1_icfg(void) { return (uint32_t)host_mask; }
static void fm1_irq_off(void)
{
    if (!host_mask)
        si_edge(1);
    host_mask = 1;
}
static void fm1_irq_on(void)
{
    if (host_mask) {
        host_mask = 0;
        si_edge(0);
    }
}
static void fm1_icfg_set(uint32_t f)
{
    if (f)
        fm1_irq_off();
    else
        fm1_irq_on();
}
#include "ui_harness.h"

/* what the audio side would read of a track: engine id, preset number, every value of the sound */
typedef struct {
    uint8_t eng, preset;
    int16_t p[P_COUNT];
} si_snd_t;
static void si_take(si_snd_t *s, const track_t *t)
{
    uint32_t i;
    memset(s, 0, sizeof *s);
    s->eng = t->eng_req;
    s->preset = t->preset;
    for (i = 0; i < P_COUNT; i++)
        if (!param_kept(i))
            s->p[i] = t->p[i];
}
static int si_eq(const si_snd_t *a, const si_snd_t *b, int fm6)
{
    si_snd_t x = *a, y = *b;
    if (fm6)
        x.p[P_E7] = y.p[P_E7] = 0;
    return !memcmp(&x, &y, sizeof x);
}

#define SI_MAX 4096u
static uint32_t si_on;                         /* bit per track watched */
static si_snd_t si_log[NTRK][SI_MAX];
static uint8_t si_kind[SI_MAX];                 /* 0 a probe with the interrupt allowed, 1 masking, 2 unmasked */
static uint32_t si_n;
/* FM6 patch/values coherence (SLOT a factory sound): at every point an interrupt could run, track 0's patch is the
 * factory one its SLOT value names (fm6_sync would otherwise render the new preset with the old patch) */
static uint32_t si_fm6chk, si_fm6bad;
static void si_fm6_probe(void)
{
    uint8_t v[FP_SIZE + 1u];
    int32_t s = trk[0].p[P_E7];
    if (s < 0 || s >= (int32_t)FM6_NFACTORY)
        return;
    fm6_unpack(FM6_FACTORY[s], v);
    if (memcmp(v, fm6_patch[0], FP_SIZE))
        si_fm6bad++;
}
static void si_probe(uint32_t kind)
{
    uint32_t k;
    if (si_fm6chk)
        si_fm6_probe();
    if (!si_on || si_n >= SI_MAX)
        return;
    for (k = 0; k < NTRK; k++)
        si_take(&si_log[k][si_n], &trk[k]);
    si_kind[si_n++] = (uint8_t)kind;
}
static void si_edge(int masking) { si_probe(masking ? 1u : 2u); }

/* the load done by fn on the tracks in mask: 1 when each changed (or kept) its sound as one window says */
static int si_watch(void (*fn)(void), uint32_t mask, uint32_t *changed)
{
    si_snd_t old[NTRK], neu[NTRK];
    uint32_t k, j, ok = 1;
    for (k = 0; k < NTRK; k++)
        si_take(&old[k], &trk[k]);
    si_n = 0;
    si_on = mask;
    si_probe(0);
    fn();
    si_probe(0);
    si_on = 0;
    *changed = 0;
    for (k = 0; k < NTRK; k++) {
        int fm6, seen_new = 0, windowed = 0;
        if (!((mask >> k) & 1u))
            continue;
        si_take(&neu[k], &trk[k]);
        fm6 = eng_is(trk[k].eng_req, ENGI_FM6);
        if (si_eq(&old[k], &neu[k], fm6))
            continue;
        *changed |= 1u << k;
        for (j = 0; j < si_n; j++) {
            int is_old = si_eq(&si_log[k][j], &old[k], fm6), is_new = si_eq(&si_log[k][j], &neu[k], fm6);
            if (!is_old && !is_new) {
                printf("sound_install: track %u: a mixed sound at probe %u (kind %u)\n", k + 1u, j, si_kind[j]);
                ok = 0;
                break;
            }
            if (is_new && !seen_new) {             /* the first probe that sees it: right after a window */
                seen_new = 1;
                windowed = j > 0 && si_kind[j] == 2u && si_kind[j - 1u] == 1u;
                if (!windowed)
                    printf("sound_install: track %u: the new sound appeared outside one window (probe %u, kind %u)\n",
                           k + 1u, j, si_kind[j]);
            }
            if (seen_new && is_old && !is_new) {
                printf("sound_install: track %u: back to the old sound at probe %u\n", k + 1u, j);
                ok = 0;
            }
        }
        ok &= seen_new && windowed;
    }
    return (int)ok;
}

static int si_check(const char *what, int ok)
{
    printf("sound_install: %-72s %s\n", what, ok ? "ok" : "FAIL");
    return ok ? 0 : 1;
}

static void op_preset(void) { apply_preset(2); }                  /* the PRESETS knob: the same engine */
static void op_engine(void) { set_engine(3); }                    /* ENGINE: another engine, its first preset */
static void op_engine_fm6(void) { set_engine(ENGI_FM6); }
static void op_init(void) { set_engine(TSEL->eng_req); }          /* TOOLS INIT */
static void op_clean(void) { clean_engine(); }                    /* TOOLS CLEAN INIT */
static void op_clean_fm6(void) { clean_engine(); }
static void op_pc(void) { midi_pc_load(TSEL, 1); }                /* MIDI Program Change 2 */
static void op_user(void) { (void)up_load(2); }
static void op_undo(void) { undo_swap(); }
static void op_project(void) { project_load(1); }
#if !FELUCCA_FM4
static void op_digital(void) { set_engine(ENGI_DIGITAL); }        /* a retired DIGITAL request: converted, FM6 */
#endif

int main(void)
{
    uint32_t bad = 0, ch, k;
    ui_power_on();
    track_select(0);
    bad += si_check("PRESETS on the same engine (values only) in one window",
                 si_watch(op_preset, 1u, &ch) && ch == 1u);
    bad += si_check("an engine change (id + values) in one window", si_watch(op_engine, 1u, &ch) && ch == 1u);
    bad += si_check("undo of it in one window", si_watch(op_undo, 1u, &ch) && ch == 1u);
    trk[0].p[P_GLIDE] = 3;                                  /* (an edit: INIT has something to put back) */
    bad += si_check("TOOLS INIT in one window", si_watch(op_init, 1u, &ch) && ch == 1u);
    trk[0].p[P_GLIDE] = 3;
    bad += si_check("CLEAN INIT in one window", si_watch(op_clean, 1u, &ch) && ch == 1u);
    bad += si_check("MIDI Program Change in one window", si_watch(op_pc, 1u, &ch) && ch == 1u);
    bad += si_check("FM6 (its patch, SLOT after) in one window", si_watch(op_engine_fm6, 1u, &ch) && ch == 1u);
    trk[0].p[P_E2] = 5;
    bad += si_check("CLEAN INIT of FM6 (the init voice) in one window",
                 si_watch(op_clean_fm6, 1u, &ch) && ch == 1u);
    track_select(1);
    up_store(2, "SI");                                    /* track 2's sound (power-on) as user preset 3 */
    track_select(0);
    bad += si_check("a user preset load in one window", si_watch(op_user, 1u, &ch) && ch == 1u);
#if !FELUCCA_FM4
    bad += si_check("a retired DIGITAL sound, converted to FM6, in one window",
                 si_watch(op_digital, 1u, &ch) && ch == 1u);
#endif
    project_save(1);
    for (k = 0; k < NTRK; k++) {                          /* every track another sound, then the project back */
        track_select(k);
        set_engine(k == 3u ? 0u : 5u);
        apply_preset(1);
    }
    track_select(0);
    bad += si_check("a project load, every track in the same window",
                 si_watch(op_project, (1u << NTRK) - 1u, &ch) && ch == (1u << NTRK) - 1u);
    /* TOOLS INIT on an FM6 track: no engine-switch fade, so the patch must change inside the window with the values */
    track_select(0);
    set_engine(ENGI_FM6);
    trk[0].p[P_E7] = 5;
    fm6_poll();
    trk[0].p[P_GLIDE] = 3;
    si_fm6chk = 1;
    si_fm6bad = 0;
    bad += si_check("FM6 INIT on an FM6 track: values and factory patch in one window",
                 si_watch(op_init, 1u, &ch) && ch == 1u && si_fm6bad == 0 && fm6_slot[0] == (uint8_t)trk[0].p[P_E7]);
    si_fm6chk = 0;
    printf("sound_install: %s\n", bad ? "FAIL" : "ok");
    return bad ? 1 : 0;
}
