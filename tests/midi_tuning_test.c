/* SPDX-License-Identifier: GPL-3.0-only */
/* Reuse the production MIDI queue/renderer fixture, without running its suite. */
#define MIDI_CONTROL_NO_MAIN
#include "midi_control_test.c"
#include <math.h>
static void tuning_reset(void)
{
    midi_test_reset();
    memset(midi_tune_q14, 0, sizeof midi_tune_q14);
}
static void tuning_select(uint32_t ch, uint32_t rpn)
{
    queued(0xB0 | ch, 101, 0, 1); queued(0xB0 | ch, 100, rpn, 1);
}
static void tuning_fine(uint32_t v)
{
    tuning_select(0, 1); queued(0xB0, 6, v >> 7, 1); queued(0xB0, 38, v & 127, 1);
}
/* One actual oscillator sample exposes phase advance without frequency-estimator
 * ambiguity. Nonzero PCM below also checks that these are live render paths. */
static uint32_t tuning_increment(track_t *t)
{
    int32_t out[CTL];
    uint32_t before = t->v[0].ph[0];
    track_render(t, out, 1);
    return t->v[0].ph[0] - before;
}
int main(void)
{
    int bad = 0;
    const uint32_t fine[] = {0,8191,8192,8193,16383};
    const uint32_t coarse[] = {0,63,64,65,127};
    tuning_reset();
    for (uint32_t i=0;i<5;i++) {
        tuning_fine(fine[i]);
        bad += check("fine14 raw value and live offset", midi_ch[0].fine14 == fine[i] && midi_tune_q14[0] == ((int32_t)fine[i]-8192)*2);
    }
    tuning_fine(8192); queued(0xB0,38,1,2);
    bad += check("LSB-only entry preserves MSB across USB/TRS", midi_ch[0].fine14 == 8193);
    queued(0xB0,6,63,1);
    bad += check("MSB-only entry preserves LSB", midi_ch[0].fine14 == 8065);
    for (uint32_t i=0;i<5;i++) {
        tuning_select(0,2); queued(0xB0,6,coarse[i],1); queued(0xB0,38,127,1);
        bad += check("coarse MSB centered at64, LSB ignored", midi_ch[0].coarse == (int32_t)coarse[i]-64);
    }
    tuning_select(1,2); queued(0xB1,6,52,2);
    bad += check("different channel tuning independent", midi_ch[1].coarse == -12 && midi_ch[0].coarse == 63);
    tuning_select(0,127); queued(0xB0,101,127,1); queued(0xB0,6,0,1);
    tuning_select(0,3); queued(0xB0,38,0,1);
    bad += check("null and unknown RPN ignore data", midi_ch[0].coarse == 63 && midi_ch[0].fine14 == 8065);
    tuning_select(0,1); queued(0xB0,99,0,2); queued(0xB0,6,0,1);
    bad += check("NRPN cancels registered data entry", midi_ch[0].fine14 == 8065);
    queued(0xB0,121,0,1);
    bad += check("RP015 CC121 preserves both registered tunings", midi_ch[0].fine14 == 8065 && midi_ch[0].coarse == 63);

    const uint32_t engines[] = {0,2,5};
    for (uint32_t e=0;e<3;e++) {
        tuning_reset(); track_t *t=&trk[0]; set_engine_of(t,engines[e]);
        t->p[P_LD_PIT]=t->p[P_ED_PIT]=t->p[P_GLIDE]=0; song.g[G_TUNE]=0;
        queued(0x90,69,100,1);
        if (!e) {
            track_t saved=*t; int32_t a[CTL], b[CTL];
            track_render(t,a,CTL); *t=saved;
            tuning_fine(8192); tuning_select(0,2); queued(0xB0,6,64,1);
            track_render(t,b,CTL);
            bad += check("explicit neutral preserves actual PCM exactly", !memcmp(a,b,sizeof a));
        }
        uint32_t neutral=tuning_increment(t);
        tuning_fine(8192); tuning_select(0,2); queued(0xB0,6,64,1);
        bad += check("explicit neutral pitch is bit exact", tuning_increment(t)==neutral);
        for (uint32_t i=0;i<5;i++) {
            tuning_fine(fine[i]);
            double cents=(fine[i]-8192.0)*100.0/8192.0;
            double actual=1200.0*log2((double)tuning_increment(t)/neutral);
            bad += check("fine pitch within existing factor resolution", fabs(actual-cents)<0.6);
        }
        tuning_fine(8192); tuning_select(0,2); queued(0xB0,6,76,1);
        bad += check("held note octave tuning doubles oscillator rate", fabs((double)tuning_increment(t)/neutral-2.0)<0.00001 && t->v[0].note==69);
        song.g[G_TUNE]=-25; tuning_fine(4096); queued(0xE0,127,127,1);
        int32_t pcm[CTL]; int nonzero=0;
        for(uint32_t i=0;i<80;i++) {track_render(t,pcm,CTL); for(uint32_t j=0;j<CTL;j++) nonzero |= pcm[j]!=0;}
        double cents=1200.0*log2((double)tuning_increment(t)/neutral);
        bad += check("coarse+negative fine+global tune+bend compose", fabs(cents-1325.0)<0.9 && nonzero);
        queued(0xB0,64,127,1); queued(0x80,69,0,1);
        bad += check("sustain retains raw note identity under tuning", gate_note(t,69) && midi_notes[0][69]);
        queued(0xB0,121,0,1);
        bad += check("reset releases sustained raw note, retains tuning", !gate_note(t,69) && !midi_notes[0][69] && midi_ch[0].coarse==12 && midi_ch[0].fine14==4096);
    }
    tuning_reset();
    tuning_select(3,1); queued(0xB3,6,0,1);
    tuning_select(3,2); queued(0xB3,6,76,1);
    queued(0x93,36,100,1);
    bad += check("DRUM ignores channel tuning", !midi_tune_q14[3] && midi_ch[3].coarse==12);
    for(uint32_t high=0;high<2;high++) {
        tuning_reset(); track_t *t=&trk[0]; set_engine_of(t,0);
        t->p[P_LD_PIT]=t->p[P_ED_PIT]=t->p[P_GLIDE]=0; song.g[G_TUNE]=0;
        tuning_select(0,2); queued(0xB0,6,high?127:0,1);
        queued(0x90,high?127:0,100,1);
        bad += check("coarse extremes clamp existing oscillator pitch range", tuning_increment(t)==pitch_inc(high?2047:0));
    }
    printf("channel state bytes=%zu, part tuning bytes=%zu\n", sizeof(midi_channel_t)*16, sizeof(midi_tune_q14));
    printf("MIDI tuning: %s\n",bad?"FAILED":"passed"); return bad!=0;
}
