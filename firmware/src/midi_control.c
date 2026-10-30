/* SPDX-License-Identifier: GPL-3.0-only
 * Adapted from MIDI control contribution by ChanceTheMaker (2026).
 * Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments */
/* Shared USB/TRS channel controls. Included by seq.c after its input helpers.
 * USB and TRS intentionally share channel state, matching the existing routing.
 * A synth part has one live bend/wheel state; channels assigned to the same part
 * share it (last controller wins). Drum hits ignore bend and sustain. CC1 keeps the existing matrix routing. */
typedef struct {
    int16_t bend;                           /* signed 14-bit value, zero = centre */
    uint8_t wheel, pedal, soft, targets;
    uint8_t owned[NTRK];                    /* held/pedal notes per track, at most 128 per channel */
    uint8_t ready, semis, cents;
    uint8_t rpn_msb, rpn_lsb;
    uint16_t fine14;                        /* RPN1: 8192 = unison, retained by CC121 */
    int8_t coarse;                          /* RPN2: -64..63 semitones */
    uint8_t glide_switch, legato_switch;     /* 0 untouched, 1 OFF, 2 ON */
    uint8_t glide_parts, legato_parts;       /* destinations bound since last sound/panic */
    uint8_t bank_msb, bank_lsb;             /* retained CC0/32; bank 0 is legacy per-engine PC */
} midi_channel_t;
static midi_channel_t midi_ch[16];
/* Selector/map port: ordenador/Felucca #255, commit
 * 3348c2eb6aa4ba175f5e746a7e42d7670f74a498 (GPL-3.0-only).
 * Selectors belong to a source/channel; sound parameters and RPN stay shared. */
#include "midi_nrpn_map.h"
typedef struct { uint8_t msb, lsb, seen; } midi_nrpn_t;
static midi_nrpn_t midi_nrpn[2][16];
#define NRPN_DEST(lsb, id, name) [lsb] = (id) + 1u,
static const uint16_t MIDI_NRPN_COMMON_MAP[128] = { MIDI_NRPN_COMMON(NRPN_DEST) };
#undef NRPN_DEST
static void midi_nrpn_reset_channel(uint32_t ch)
{
    midi_nrpn[0][ch].seen = midi_nrpn[1][ch].seen = 0;
}
static void midi_nrpn_reset(void) { memset(midi_nrpn, 0, sizeof midi_nrpn); }
static uint32_t midi_nrpn_id(uint32_t msb, uint32_t lsb)
{
    uint32_t id = P_COUNT;
    if (lsb < 128u) {
        if (msb == 0u && MIDI_NRPN_COMMON_MAP[lsb])
            id = MIDI_NRPN_COMMON_MAP[lsb] - 1u;
        else if (msb == 1u && lsb < 8u)
            id = P_E0 + lsb;
    }
    return id < P_COUNT ? id : P_COUNT;
}
/* Low nibble: owner bits per part. High nibble: pedal-held subset of those owners.
 * Keep one byte per channel/pitch, including mixed synth/drum layers. */
static uint8_t midi_sel_on[16][128];
#define midi_notes midi_sel_on
static uint16_t midi_owners[NTRK];           /* avoids rescanning all 2048 entries for CC123 */
#define MIDI_PEDAL_NOTE 0xF0u
_Static_assert(NTRK == 4, "MIDI ownership packs four parts into one byte");

/* Session-only external-input zones. Store HIGH's distance from 127 so BSS
 * zero gives the full range at boot, without changing any saved parameter. */
static uint8_t midi_key_range[NTRK][2];

static int32_t midi_key_range_get(uint32_t track, uint32_t high)
{
    if (track >= NTRK || high > 1u)
        return -1;
    return high ? 127 - midi_key_range[track][1] : midi_key_range[track][0];
}

static int midi_key_range_set(uint32_t track, uint32_t high, uint32_t value)
{
    if (track >= NTRK || high > 1u || value > 127u)
        return 0;
    if (high ? value < (uint32_t)midi_key_range_get(track, 0) :
               value > (uint32_t)midi_key_range_get(track, 1))
        return 0;
    midi_key_range[track][high] = (uint8_t)(high ? 127u - value : value);
    return 1;
}

static uint32_t midi_key_mask(uint32_t mask, uint32_t note)
{
    uint32_t i;
    if (note > 127u)
        return 0;
    for (i = 0; i < NPART; i++)
        if (note < midi_key_range[i][0] || note > 127u - midi_key_range[i][1])
            mask &= ~(1u << i);
    return mask;
}

static void midi_key_reset(void)
{
    memset(midi_key_range, 0, sizeof midi_key_range);
}

/* LOW's distance from 1 and HIGH's distance from 127 keep boot defaults
 * in BSS. Zones select raw positive input velocity, before response scaling. */
static uint8_t midi_velocity_range[NTRK][2];

static int32_t midi_velocity_range_get(uint32_t track, uint32_t high)
{
    if (track >= NTRK || high > 1u)
        return -1;
    return high ? 127 - midi_velocity_range[track][1] : 1 + midi_velocity_range[track][0];
}

static int midi_velocity_range_set(uint32_t track, uint32_t high, uint32_t value)
{
    if (track >= NTRK || high > 1u || value < 1u || value > 127u)
        return 0;
    if (high ? value < (uint32_t)midi_velocity_range_get(track, 0) :
               value > (uint32_t)midi_velocity_range_get(track, 1))
        return 0;
    midi_velocity_range[track][high] = (uint8_t)(high ? 127u - value : value - 1u);
    return 1;
}

static uint32_t midi_velocity_mask(uint32_t mask, uint32_t velocity)
{
    uint32_t i;
    if (!velocity || velocity > 127u)
        return 0;
    for (i = 0; i < NPART; i++)
        if (velocity < 1u + midi_velocity_range[i][0] || velocity > 127u - midi_velocity_range[i][1])
            mask &= ~(1u << i);
    return mask;
}

static void midi_velocity_reset(void)
{
    memset(midi_velocity_range, 0, sizeof midi_velocity_range);
}

static midi_channel_t *midi_channel(uint32_t ch)
{
    midi_channel_t *c = &midi_ch[ch];
    if (!c->ready) {
        c->semis = 2;
        c->fine14 = 8192;
        c->rpn_msb = c->rpn_lsb = 127;
        c->ready = 1;
    }
    return c;
}

/* Session controller state: project replacement resets this along with routing setup.
 * Sound changes and note/sound panic keep the physical switch state. */
static void midi_soft_reset(void)
{
    uint32_t ch;
    for (ch = 0; ch < 16u; ch++)
        midi_ch[ch].soft = 0;
}

static uint32_t midi_targets(uint32_t ch)
{
    return midi_channel(ch)->targets | midi_route_mask(ch);
}

static void midi_expression(track_t *t, const midi_channel_t *c)
{
    int32_t range = ((int32_t)c->semis * 100 + c->cents) * 256 / 100;
    if (drum_track(t))
        return;
    midi_tune_q14[trk_index(t)] = (int32_t)c->coarse * 16384 + ((int32_t)c->fine14 - 8192) * 2;
    midi_bend_target[trk_index(t)] = (int32_t)c->bend * range / (c->bend < 0 ? 8192 : 8191);
}

static void midi_expression_channel(uint32_t ch)
{
    uint32_t i, mask = midi_targets(ch);
    for (i = 0; i < NPART; i++)
        if (mask & (1u << i))
            midi_expression(&trk[i], midi_channel(ch));
}

/* Bind switches to destinations when received. A sound/panic invalidates that
 * destination, so a later note cannot reinstall an old patch's controller mode. */
static void midi_articulation(track_t *t, const midi_channel_t *c)
{
    uint32_t i = trk_index(t), bit = 1u << i;
    if (c->glide_parts & bit)
        midi_glide_switch[i] = c->glide_switch;
    if (c->legato_parts & bit)
        midi_legato_switch[i] = c->legato_switch;
}

static void midi_articulation_control(uint32_t ch, uint32_t cc, uint32_t value)
{
    midi_channel_t *c = midi_channel(ch);
    uint32_t i, j, mask = midi_targets(ch), sw = value >= 64u ? 2u : 1u;
    if (cc == 65u) {
        c->glide_switch = (uint8_t)sw;
        c->glide_parts |= (uint8_t)mask;
    } else {
        c->legato_switch = (uint8_t)sw;
        c->legato_parts |= (uint8_t)mask;
    }
    for (i = 0; i < NPART; i++)
        if (mask & (1u << i)) {
            midi_articulation(&trk[i], c);
            /* OFF ends an in-progress portamento too; ON affects subsequent
             * transitions. Never rebuild the mono stack or retrigger on a CC. */
            if (cc == 65u && sw == 1u && !ENGINES[trk[i].engine]->oneshot)
                for (j = 0; j < NVOICE; j++) {
                    trk[i].v[j].pitch_cur = trk[i].v[j].pitch16;
                    trk[i].v[j].gstep = 0;
                }
        }
}

/* a MIDI note of track t sounds note: one played as itself, or a tone of one played as a chord (chord.c) */
static int midi_note_held(const track_t *t, uint32_t note)
{
    uint32_t ch, id = trk_index(t) + 1u;
    for (ch = 0; ch < 16u; ch++)
        if ((midi_notes[ch][note] & (1u << (id - 1u))) && !mchord_of(ch, note, id))
            return 1;
    return mchord_held(id, note);
}

/* a key held on track t sounds note (the key's own note, or a tone of its chord) */
static int midi_local_held(const track_t *t, uint32_t note)
{
    uint32_t k, i;
    for (k = 0; k < 27u; k++)
        if (kb_chn[k] && kb_trk[k] == trk_index(t))
            for (i = 0; i < kb_chn[k]; i++)
                if (kb_chord[k][i] == note)
                    return 1;
    return 0;
}

static void midi_release_track(uint32_t ch, uint32_t note, uint32_t track)
{
    uint32_t bit = 1u << track, id = (midi_notes[ch][note] & bit) ? track + 1u : 0;
    midi_notes[ch][note] &= (uint8_t)~(bit | (bit << 4));
    if (id) {
        midi_owners[id - 1u]--;
        if (!--midi_ch[ch].owned[id - 1u])
            midi_ch[ch].targets &= (uint8_t)~(1u << (id - 1u));
    }
    if (id) {
        mchord_t *m = mchord_of(ch, note, id);
        uint8_t nn[CHORD_MAX];
        uint32_t n = 1, i;
        nn[0] = (uint8_t)note;
        if (m) {                                  /* a chord: exactly the notes it started */
            n = m->n;
            for (i = 0; i < n; i++)
                nn[i] = m->note[i];
            m->id = 0;
        }
        for (i = 0; i < n; i++)
            if (!midi_local_held(&trk[id - 1u], nn[i]))
                input_off(&trk[id - 1u], nn[i]);  /* input_off also checks other MIDI owners */
    }
}

static void midi_release(uint32_t ch, uint32_t note)
{
    uint32_t i;
    for (i = 0; i < NPART; i++)
        if (midi_notes[ch][note] & (1u << i))
            midi_release_track(ch, note, i);
}

/* a MIDI note-on (ch, note) of track t: its chord (chord.c) or the note alone. A note another key or MIDI
 * note holds already sounds: not started again */
static void midi_play(track_t *t, uint32_t ch, uint32_t note, uint32_t vel)
{
    uint8_t nn[CHORD_MAX];
    uint32_t n = chord_build(t, note, nn), i, f = 0;
    if (n > 1u || nn[0] != note)
        for (f = 0; f < MCHORD_N && mchord[f].id; f++)
            ;
    if (f == MCHORD_N) {                          /* no room to keep a chord: the note alone */
        n = 1;
        nn[0] = (uint8_t)note;
    }
    for (i = 0; i < n; i++)
        if (!midi_note_held(t, nn[i]) && !midi_local_held(t, nn[i]))
            input_on(t, nn[i], vel);
    if (n > 1u || nn[0] != note) {
        mchord_t *m = &mchord[f];
        m->ch = (uint8_t)ch;
        m->src = (uint8_t)note;
        m->n = (uint8_t)n;
        for (i = 0; i < n; i++)
            m->note[i] = nn[i];
        m->id = (uint8_t)(trk_index(t) + 1u);
    }
}

static void midi_note_event(uint32_t ch, uint32_t note, uint32_t vel)
{
    midi_channel_t *c = midi_channel(ch);
    uint32_t i, mask;
    if (vel) {
        /* Repeated notes replace all previous owners, including pedal-held ones. */
        midi_release(ch, note);
        /* Filter raw source pitch before transpose, CHRD and ARP expansion.
         * Releases above/below use captured owners, never the current zone. */
        mask = midi_key_mask(midi_route_mask(ch), note);
        mask = midi_velocity_mask(mask, vel);
        for (i = 0; i < NPART; i++) {
            track_t *t = &trk[i];
            if (!(mask & (1u << i)))
                continue;
            midi_expression(t, c);
            midi_articulation(t, c);
            if (t != TSEL)
                midi_hint = (uint8_t)(i + 1u);
            midi_seen |= (uint8_t)(1u << i);
            c->targets |= (uint8_t)(1u << i);
            /* Select destinations with raw velocity first (zones), then soften once.
             * Round half upward: every positive MIDI velocity remains positive. */
            midi_play(t, ch, note, c->soft ? (vel + 1u) >> 1 : vel);
            midi_notes[ch][note] |= (uint8_t)(1u << i);
            midi_owners[i]++;
            c->owned[i]++;
        }
    } else {
        for (i = 0; i < NPART; i++)
            if (midi_notes[ch][note] & (1u << i)) {
                if (c->pedal && !drum_track(&trk[i]))
                    midi_notes[ch][note] |= (uint8_t)(1u << (i + 4u));
                else
                    midi_release_track(ch, note, i);
            }
    }
}

static void midi_pedal_up(uint32_t ch)
{
    uint32_t note, i;
    midi_channel(ch)->pedal = 0;
    for (note = 0; note < 128u; note++)
        for (i = 0; i < NPART; i++)
            if (midi_notes[ch][note] & (1u << (i + 4u)))
                midi_release_track(ch, note, i);
}

/* Preset/project panic and CC120 must discard ownership so a later pedal-up
 * or note-off cannot release notes subsequently started on another patch. */
static void __attribute__((noinline)) midi_forget_track(uint32_t track)
{
    uint32_t ch, note;
    midi_glide_switch[track] = midi_legato_switch[track] = 0;
    for (ch = 0; ch < 16u; ch++) {
        midi_ch[ch].glide_parts &= (uint8_t)~(1u << track);
        midi_ch[ch].legato_parts &= (uint8_t)~(1u << track);
        if (!(midi_ch[ch].targets & (1u << track)))
            continue;
        for (note = 0; note < 128u; note++)
            midi_notes[ch][note] &= (uint8_t)~((1u << track) | (1u << (track + 4u)));
        midi_ch[ch].targets &= (uint8_t)~(1u << track);
        midi_ch[ch].owned[track] = 0;
    }
    midi_owners[track] = 0;
    mchord_forget(track);
    midi_bend_q8[track] = midi_bend_target[track] = 0;
    midi_tune_q14[track] = 0;
}

static void midi_silence_track(uint32_t track)
{
    track_t *t = &trk[track];
    uint32_t i;
    trk_all_off(t);
    t->nheld = t->arp_phys = t->rh_n = 0;
    arp_forget(t);
    t->seq_n = t->seq_hold = t->slide_glide = 0;
    for (i = 0; i < NVOICE; i++)
        if (t->v[i].active)
            voice_kill(&t->v[i]);             /* one-block fade, regardless of RELEASE */
    sl[track].rec = sl[track].loop = 0;       /* do not keep replaying captured sound */
    midi_forget_track(track);
}

static int midi_track_held(uint32_t track)
{
    uint32_t k;
    if (midi_owners[track])
        return 1;
    for (k = 0; k < 27u; k++)
        if ((fm1_in.notes & (1u << k)) && kb_trk[k] == track)
            return 1;
    return 0;
}

/* The standard CC map (#103): always on, these CCs only, on the track the channel plays (ROUT as notes). A CC
 * sets its parameter as a knob would, 0..127 over the parameter's range (64: the middle of a bipolar one), and
 * AUTOMATION records it as a knob move (motion_capture: the selected track, armed and playing). CC74 / CC71 are
 * the engine's own brightness / resonance (MIDI_CC_ENG); an engine without one ignores them. CC121 resets none
 * of them (RP-015: they are the sound's) */
#define MCC_CUT 0xFEu
#define MCC_RES 0xFFu
static const uint8_t MIDI_CC_MAP[][2] = {
    {5, P_GLIDE}, {7, P_LEVEL}, {10, P_PAN}, {71, MCC_RES}, {72, P_REL}, {73, P_ATK}, {74, MCC_CUT}, {75, P_DEC},
    {91, P_REV}, {93, P_CHOR}, {94, P_DLY},
};
/* per engine id (ENGINES[] order; sized by the id space, #212: an id without an engine, ENG_IDX_NONE included, has
 * none): CC74's E index + 1 in the high nibble, CC71's in the low one, 0 = none */
static const uint8_t MIDI_CC_ENG[ENG_ID_MAX] = {
#include "engine_cc.inc"
};
/* a CC sets parameter id of track t as a knob would: 0..127 over its range */
static void midi_cc_set(track_t *t, uint32_t id, uint32_t value)
{
    const param_desc_t *d = param_desc_of(eng_idx(t->eng_req), id);
    int32_t v = d->min + ((int32_t)value * (d->max - d->min) + 63) / 127;
    if (d->max <= d->min || t->p[id] == v)
        return;
    t->p[id] = (int16_t)v;
    (void)motion_capture(t, id, (int16_t)v);
}
/* MIDI LEARN (1.5, Discussion #170): up to ML_N CCs, each set to one parameter of one track, whatever channel it
 * comes on (a channel ROUT ignores stays ignored) and whichever track that channel plays. Kept with the settings in
 * the 32 bytes of settings_ml (favorites.c; #212: favorites.factory[14] in the settings of firmware up to 1.6, which a
 * PER4 record still holds; all 0 in every older setting = nothing learned),
 * an entry two bytes, as a 16-bit value LSB first: bits 0..6 the CC, 7..8 the track, 9..15 the parameter's code, 0 =
 * an empty entry: a common parameter its P_* id + 1 (1 .. ML_E0 - 1: their ids never move, new ones go before P_E0),
 * an engine parameter ML_E0 + k for P_E0 + k (P_E0 moves when common ones are added). A learned CC no longer reaches
 * the standard map (#103) on any channel: the controller is the user's now. The CCs with a meaning of their own
 * (midi_control's cases, CC0 / 32 bank select, CC11 EXPR, CC96 / 97 data increment, CC120..127) are never learned. The UI
 * (midi_learn.c) writes the entries with the interrupts off; ml_arm / ml_heard hand a CC heard while learning to it */
#define ML_N 16u
#define ML_E0 120u
typedef char ml_ids_fit[P_E0 < ML_E0 && P_COUNT - P_E0 == 8 ? 1 : -1];
static uint8_t *const ml_tab;               /* settings_ml (midi_learn.c: a build without the UI, none) */
static volatile uint8_t *const ml_io;       /* ui.ml.io (midi_learn.c; not globals here: the ISR's data keeps its layout) */
#define ml_arm (ml_io[0])                   /* the UI waits for a CC (MIDI LEARN with a parameter picked) */
#define ml_heard (ml_io[1])                 /* .. the CC that came meanwhile, + 1 (0 none) */
static uint32_t ml_id(uint32_t code)        /* an entry's code -> P_* id, P_COUNT: none this firmware knows */
{
    return code >= ML_E0 ? P_E0 + code - ML_E0 : code && code <= P_E0 ? code - 1u : P_COUNT;
}
static int ml_free_cc(uint32_t cc)          /* fixed expressive controls and selectors are reserved */
{
    return cc && cc < 120u && cc != 1u && cc != 6u && cc != 11u && cc != 32u && cc != 38u && cc != 64u &&
           cc != 65u && cc != 67u && cc != 68u && (cc < 96u || cc > 101u);
}
/* 1: cc is learned (set here) or taken by MIDI LEARN waiting for one */
static int __attribute__((noinline)) midi_learned(uint32_t cc, uint32_t value)
{
    uint32_t i, e, id, hit = 0;
    if (!ml_tab || !ml_free_cc(cc))
        return 0;
    if (ml_arm) {
        if (!ml_heard)
            ml_heard = (uint8_t)(cc + 1u);
        return 1;
    }
    for (i = 0; i < ML_N; i++) {
        e = ml_tab[2u * i] | (uint32_t)ml_tab[2u * i + 1u] << 8;
        if ((e >> 9) && (e & 127u) == cc) {
            if ((id = ml_id(e >> 9)) < P_COUNT)
                midi_cc_set(&trk[(e >> 7) & 3u], id, value);
            hit = 1;
        }
    }
    return hit;
}

static void __attribute__((noinline)) midi_cc_map(track_t *t, uint32_t cc, uint32_t value)
{
    uint32_t i, id = 0xFFFFu, e;
    for (i = 0; i < NELEM(MIDI_CC_MAP); i++)
        if (MIDI_CC_MAP[i][0] == cc)
            id = MIDI_CC_MAP[i][1];
    if (id >= MCC_CUT) {
        if (id == 0xFFFFu)
            return;
        e = MIDI_CC_ENG[eng_idx(t->eng_req)] >> (id == MCC_CUT ? 4 : 0) & 15u;
        if (!e)
            return;
        id = P_E0 + e - 1u;
    }
    midi_cc_set(t, id, value);
}

/* One session-only pair. CC 0 disables future edits; assignments never restore
 * old levels or retain a controller position. Parts remain absolute, as LEARN's
 * targets do, and heard USB/TRS channels share the assignment. */
static uint8_t midi_mix_config[3] = {0, 0, 1};

static void midi_mix_reset(void)
{
    midi_mix_config[0] = midi_mix_config[1] = 0;
    midi_mix_config[2] = 1;
}

static uint32_t midi_mix_config_get(uint32_t field)
{
    return field < NELEM(midi_mix_config) ? midi_mix_config[field] : 0;
}

static int midi_mix_config_set(uint32_t field, uint32_t value)
{
    uint32_t i;
    if (field >= NELEM(midi_mix_config))
        return 0;
    if (!field) {
        if (value) {
            if (!ml_free_cc(value) || value == 65u || value == 67u || value == 68u)
                return 0;
            for (i = 0; i < NELEM(MIDI_CC_MAP); i++)
                if (MIDI_CC_MAP[i][0] == value)
                    return 0;
        }
    } else if (value >= NPART || value == midi_mix_config[3u - field])
        return 0;
    midi_mix_config[field] = (uint8_t)value;
    return 1;
}

/* Linear complementary amplitude, 0..unity, quantized to the native LEVEL
 * table. Binary search is bounded to seven comparisons per part; nearest gain
 * wins, with ties toward the quieter value. No floating point or render work. */
static uint32_t midi_mix_level(uint32_t position)
{
    uint32_t gain = (LEVEL_Q12[112] * position + 63u) / 127u;
    uint32_t lo = 0, hi = 112, mid;
    while (lo < hi) {
        mid = (lo + hi) / 2u;
        if (LEVEL_Q12[mid] < gain)
            lo = mid + 1u;
        else
            hi = mid;
    }
    if (lo && gain - LEVEL_Q12[lo - 1u] <= LEVEL_Q12[lo] - gain)
        lo--;
    return lo;
}

static int midi_mix_control(uint32_t ch, uint32_t cc, uint32_t value)
{
    uint32_t i, level;
    (void)ch;                                    /* midi_event gates unheard channels */
    if (!midi_mix_config[0] || cc != midi_mix_config[0] || value > 127u)
        return 0;
    for (i = 1; i < 3u; i++) {
        track_t *t = &trk[midi_mix_config[i]];
        level = midi_mix_level(i == 1u ? 127u - value : value);
        if (t->p[P_LEVEL] != (int16_t)level) {
            t->p[P_LEVEL] = (int16_t)level;
            (void)motion_capture(t, P_LEVEL, (int16_t)level);
        }
    }
    return 1;
}

/* Integration bridge for session configuration; root wires feature helpers here.
 * Return nonzero only when the address is handled. */
static int midi_nrpn_extra(uint32_t address, uint32_t value)
{
    if (address >= 0x3000u && address < 0x3040u) {
        uint32_t track = (address - 0x3000u) >> 4, field = address & 15u;
        if (track < NPART && field < 4u) {
            if (field < 2u)
                (void)midi_key_range_set(track, field, value);
            else
                (void)midi_velocity_range_set(track, field - 2u, value);
            return 1;                       /* invalid/reversed values leave the setup unchanged */
        }
    } else if (address >= 0x3100u && address <= 0x3102u) {
        (void)midi_mix_config_set(address - 0x3100u, value);
        return 1;
    }
    return 0;
}

/* Called only for an active RPN selection; selector/source ownership stays in
 * the controller dispatcher. Partial data entry preserves the other byte. */
static void midi_rpn_data(uint32_t ch, uint32_t msb, uint32_t lsb, uint32_t cc, uint32_t value)
{
    midi_channel_t *c = midi_channel(ch);
    if (msb || lsb > 2u)
        return;
    if (!lsb) {                              /* RPN0: existing bend sensitivity */
        if (cc == 6u)
            c->semis = (uint8_t)(value > 24u ? 24u : value);
        else
            c->cents = (uint8_t)(value > 99u ? 99u : value);
    } else if (lsb == 1u) {                  /* RPN1: 14-bit +/- one semitone */
        if (cc == 6u)
            c->fine14 = (uint16_t)((value << 7) | (c->fine14 & 127u));
        else
            c->fine14 = (uint16_t)((c->fine14 & 16256u) | value);
    } else {                                /* RPN2: LSB is ignored */
        if (cc != 6u)
            return;
        c->coarse = (int8_t)((int32_t)value - 64);
    }
    midi_expression_channel(ch);
}

static void midi_control_source(uint32_t ch, uint32_t cc, uint32_t value, uint32_t source)
{
    midi_channel_t *c = midi_channel(ch);
    uint32_t i, mask;
    midi_nrpn_t *n = source == 1u || source == 2u ? &midi_nrpn[source - 1u][ch] : 0;
    switch (cc) {
    case 0: c->bank_msb = (uint8_t)value; break;
    case 32: c->bank_lsb = (uint8_t)value; break;
    case 1:
        c->wheel = (uint8_t)value;
        break;
    case 120:                                      /* All Sound Off: ignores the pedal */
        mask = midi_targets(ch);
        for (i = 0; i < NTRK; i++)
            if (mask & (1u << i))
                midi_silence_track(i);
        break;
    case 123:                                      /* All Notes Off: normal releases, honours pedal */
        mask = midi_targets(ch);
        for (i = 0; i < 128u; i++)
            if (midi_notes[ch][i])
                midi_note_event(ch, i, 0);
        for (i = 0; i < NTRK; i++)
            if ((mask & (1u << i)) && !midi_track_held(i)) {
                trk_all_off(&trk[i]);
                trk[i].nheld = trk[i].arp_phys = trk[i].rh_n = 0;
                arp_forget(&trk[i]);
            }
        break;
    case 121:                                      /* RP-015: keep registered tuning and bend sensitivity */
        midi_nrpn_reset_channel(ch);
        c->bend = 0;
        c->wheel = 0;
        c->soft = 0;
        c->rpn_msb = c->rpn_lsb = 127;
        midi_expression_channel(ch);
        midi_articulation_control(ch, 65, 0);
        midi_articulation_control(ch, 68, 0);
        midi_pedal_up(ch);
        break;
    case 65: case 68:
        midi_articulation_control(ch, cc, value);
        break;
    case 64:
        if (value >= 64u)
            c->pedal = 1;
        else
            midi_pedal_up(ch);
        break;
    case 67:
        c->soft = (uint8_t)(value >= 64u);
        break;
    case 101: midi_nrpn_reset_channel(ch); c->rpn_msb = (uint8_t)value; break;
    case 100: midi_nrpn_reset_channel(ch); c->rpn_lsb = (uint8_t)value; break;
    case 99: case 98:                              /* NRPN selection cancels RPN data entry */
        c->rpn_msb = c->rpn_lsb = 127;
        if (n) {
            if (cc == 99u) { n->msb = (uint8_t)value; n->seen |= 1u; }
            else { n->lsb = (uint8_t)value; n->seen |= 2u; }
            if (n->seen == 3u && n->msb == 127u && n->lsb == 127u)
                n->seen = 0;
        }
        break;
    case 6: case 38:
        if (!c->rpn_msb && c->rpn_lsb <= 2u) {
            midi_rpn_data(ch, c->rpn_msb, c->rpn_lsb, cc, value);
        } else if (cc == 6u && n && n->seen == 3u) {
            uint32_t id = midi_nrpn_id(n->msb, n->lsb);
            if (!midi_nrpn_extra(((uint32_t)n->msb << 7) | n->lsb, value) && id < P_COUNT) {
                mask = midi_route_mask(ch);
                for (i = 0; i < NPART; i++)
                    if ((mask & (1u << i)) && (id < P_E0 || eng_ok(trk[i].eng_req)))
                        midi_cc_set(&trk[i], id, value);
            }
        }
        break;
    default:
        if (!midi_learned(cc, value) && !midi_mix_control(ch, cc, value)) {
            mask = midi_route_mask(ch);
            for (i = 0; i < NPART; i++)
                if (mask & (1u << i))
                    midi_cc_map(&trk[i], cc, value);
        }
        break;
    }
}

/* ROUT CH1-4 listens to channels 1..4 only (1.2: CH5-8, CH9-12, CH13-16 to their four). A switch to a block from
 * SEL or another block (events_block, before the queue) lets go of what the other channels hold: their notes
 * released (also pedal-held ones), their pedal, soft switch, bend, wheel and RPN selection reset, so no note can hang on a
 * channel that is no longer heard. When entering, leaving or editing TRACK, a still-heard channel also releases
 * notes whose former track is no longer its destination (duplicates / OMNI). Legacy SEL -> block keeps heard
 * channels' original owners until note-off. Each part's bend then follows the new routing. */
static void __attribute__((noinline)) midi_route_block(void)
{
    uint32_t ch, note, i;
    uint32_t reassign = song.g[G_ROUTE] == ROUTE_TRACK || midi_route == ROUTE_TRACK || midi_route == MIDI_ROUTE_AGAIN;
    for (i = 0; i < NTRK; i++) {
        midi_glide_switch[i] = midi_legato_switch[i] = 0;
        if (reassign) {
            midi_tune_q14[i] = 0;
            midi_bend_target[i] = 0;
        }
    }
    for (ch = 0; ch < 16u; ch++) {
        midi_channel_t *c = midi_channel(ch);
        if (midi_in_block(ch)) {
            uint32_t mask = midi_route_mask(ch);
            if (reassign && (c->targets & (uint8_t)~mask))
                for (note = 0; note < 128u; note++)
                    for (i = 0; i < NPART; i++)
                        if ((midi_notes[ch][note] & (1u << i)) && !(mask & (1u << i)))
                            midi_release_track(ch, note, i);
            if (reassign) {
                c->glide_parts &= (uint8_t)mask;
                c->legato_parts &= (uint8_t)mask;
            }
            for (i = 0; i < NPART; i++)
                if ((mask | c->targets) & (1u << i))
                    midi_articulation(&trk[i], c);
            for (i = 0; i < NPART; i++)
                if (mask & (1u << i))
                    midi_expression(&trk[i], c);
            continue;
        }
        for (note = 0; note < 128u; note++)
            if (midi_notes[ch][note])
                midi_release(ch, note);
        c->glide_switch = c->legato_switch = c->glide_parts = c->legato_parts = 0;
        c->pedal = c->wheel = c->soft = 0;
        c->bend = 0;
        c->rpn_msb = c->rpn_lsb = 127;
        midi_nrpn_reset_channel(ch);
    }
}

/* One atomic word per destination: valid bit 7, program bits 0..6, bank bits 8..21.
 * The last PC before service wins, including unsupported addresses. Selectors alone
 * never touch pending requests. Both physical inputs share the channel's selectors. */
static volatile uint32_t *const mpc_io;
static void midi_bank_reset(void)                  /* boot/project reset, caller excludes input ISR */
{
    uint32_t ch;
    for (ch = 0; ch < 16u; ch++)
        midi_ch[ch].bank_msb = midi_ch[ch].bank_lsb = 0;
    if (mpc_io)
        for (ch = 0; ch < NTRK; ch++)
            mpc_io[ch] = 0;
}

/* Keep the occasional controller/panic dispatch outside the hot rendering loop. Channel voice messages only
 * (realtime and clock are handled in events_block, SysEx never reaches here). With ROUT CH1-4 channels
 * 5..16 are ignored entirely (with CH5-8 .. CH13-16 every channel outside the block): notes, bend, CCs (CC1/11/64, RPN, and the CC120/121/123 panic and reset),
 * channel aftertouch, Program Change, so they stay free for other instruments. */
static void __attribute__((noinline)) midi_event_source(uint32_t st, uint32_t ch, uint32_t d1, uint32_t d2, uint32_t source)
{
    uint32_t i, mask;
    if (song.g[G_ROUTE] != 1 && !midi_in_block(ch))
        return;
    if (st == 0x90u || st == 0x80u)
        midi_note_event(ch, d1, st == 0x90u ? d2 : 0);
    else if (st == 0xE0u) {
        midi_channel(ch)->bend = (int16_t)((int32_t)(d1 | (d2 << 7)) - 8192);
        midi_expression_channel(ch);
    } else {
        mask = midi_route_mask(ch);
        for (i = 0; i < NPART; i++)
            if (mask & (1u << i)) {
                if (st == 0xB0u || st == 0xD0u)
                    mod_midi(&trk[i], st, d1, d2);
                else if (st == 0xC0u && mpc_io)
                    mpc_io[i] = ((uint32_t)midi_channel(ch)->bank_msb << 15) |
                                ((uint32_t)midi_channel(ch)->bank_lsb << 8) | 0x80u | d1;
            }
        if (st == 0xB0u)
            midi_control_source(ch, d1, d2, source);
    }
}

/* Legacy internal callers are USB; queued input always supplies its real source. */
static void midi_control(uint32_t ch, uint32_t cc, uint32_t value)
{
    midi_control_source(ch, cc, value, 1u);
}
static void midi_event(uint32_t st, uint32_t ch, uint32_t d1, uint32_t d2)
{
    midi_event_source(st, ch, d1, d2, 1u);
}
