/* SPDX-License-Identifier: GPL-3.0-only
 * Based on fgunited's upstream PR #269 (ebdf867), with boundary regressions.
 * Long-run external-clock phase measured against independent wire pulse counts.
 * Use rational musical positions, not another copy of the firmware clock math. */
#include "ui_harness.h"
#include <math.h>

static void drift_packet(uint32_t source, uint32_t status, uint32_t ms)
{
    fm1_ms = ms;
    if (source == 2u) um_byte(status);
    else midi_enqueue(0xFu | status << 8, source);
    events_block(CTL);
}
static void drift_setup(uint32_t source, uint32_t bpm)
{
    static const int16_t len[] = {16,17,23,64}, div[] = {2,3,5,6}, rate[] = {2,3,5,0};
    ui_power_on(); memset(&midi_clock,0,sizeof midi_clock); memset(&um,0,sizeof um);
    mi_r=mi_w=0; midi_beat_samples=0; fm1_ms=0;
    song.g[G_CLOCK]=(int16_t)source; song.g[G_BPM]=(int16_t)bpm;
    events_block(CTL);
    for(uint32_t k=0;k<NTRK;k++) {
        track_t *t=&trk[k];
        set_engine_of(t,0); apply_preset_to(t,0); t->engine=t->eng_req;
        memset(t->step,0,sizeof t->step);
        t->p[P_SLEN]=len[k]; t->p[P_SDIV]=div[k]; t->p[P_SSWING]=0;
    }
    drift_packet(source,0xFA,10);
    for(uint32_t k=0;k<NTRK;k++) {
        trk[k].p[P_AMODE]=AM_UP; trk[k].p[P_ARATE]=rate[k]; trk[k].p[P_ASWING]=0;
        input_on(&trk[k],60,100); input_on(&trk[k],64,100);
    }
    drift_packet(source,0xF8,10);
}
static double drift_beats(uint32_t div)
{
    static const double value[]={1.,.5,.25,.125,1./3.,1./6.,2.,4.,8.,16.};
    return value[div];
}
static int drift_run(uint32_t source, uint32_t bpm, uint32_t jitter, uint32_t interpolate)
{
    int bad=0; drift_setup(source,bpm);
    uint32_t steps[NTRK]={0},prev[NTRK]={0};
    uint32_t pulses=bpm*20u*24u;
    for(uint32_t i=1;i<=pulses;i++) {
        static const int8_t noise[]={0,1,-1,1,0,-1,0,-1,1,-1,0,1,1,0,-1,0,1,-1};
        uint32_t at=10u+(uint32_t)((uint64_t)i*60000u/(bpm*24u));
        if(jitter) at=(uint32_t)((int32_t)at+noise[i%18u]);
        if(interpolate) while(fm1_ms+1u<at) { fm1_ms++; events_block(CTL); }
        drift_packet(source,0xF8,at);
        for(uint32_t k=0;k<NTRK;k++) {
            steps[k]+=(trk[k].seq_idx+(uint32_t)trk[k].p[P_SLEN]-prev[k])%(uint32_t)trk[k].p[P_SLEN];
            prev[k]=trk[k].seq_idx;
        }
    }
    for(uint32_t k=0;k<NTRK;k++) {
        track_t *t=&trk[k];
        double expected=(double)pulses/24.;
        double seq=(steps[k]+(double)t->seq_pos/div_samples((uint32_t)t->p[P_SDIV]))*drift_beats((uint32_t)t->p[P_SDIV]);
        double arp=(t->arp_idx+(double)t->arp_pos/div_samples((uint32_t)t->p[P_ARATE]))*drift_beats((uint32_t)t->p[P_ARATE]);
        double seq_ms=(seq-expected)*60000./bpm,arp_ms=(arp-expected)*60000./bpm;
        printf("source %u, %u BPM, jitter %u, interpolate %u, T%u: seq %.4f ms, ARP %.4f ms after 20 min\n",
               source,bpm,jitter,interpolate,k+1u,seq_ms,arp_ms);
        bad+=check("sequencer phase stays within 2 ms of counted wire pulses",fabs(seq_ms)<2.);
        bad+=check("ARP phase stays within 2 ms without loop resets",fabs(arp_ms)<2.);
        bad+=check("polymetric lengths, rates and held ARP chords are retained",t->p[P_SLEN]==(int16_t[]){16,17,23,64}[k] && t->nheld==2u);
    }
    bad+=check("long-run transport keeps running without input overflow",song.playing && !midi_in_overflow);
    return bad;
}
static int drift_tempo_edges(uint32_t source)
{
    int bad=0; drift_setup(source,120);
    uint32_t steps[NTRK]={0},prev[NTRK]={0};
    uint64_t us=10000u;
    for(uint32_t i=1;i<=400u;i++) {
        uint32_t bpm=i<29u?120u:i<137u?97u:i<233u?240u:40u;
        us+=60000000u/(bpm*24u);
        drift_packet(source,0xF8,(uint32_t)(us/1000u));
        for(uint32_t k=0;k<NTRK;k++) {
            steps[k]+=(trk[k].seq_idx+(uint32_t)trk[k].p[P_SLEN]-prev[k])%(uint32_t)trk[k].p[P_SLEN];
            prev[k]=trk[k].seq_idx;
        }
    }
    for(uint32_t k=0;k<NTRK;k++) {
        track_t *t=&trk[k];
        double seq=(steps[k]+(double)t->seq_pos/div_samples((uint32_t)t->p[P_SDIV]))*drift_beats((uint32_t)t->p[P_SDIV]);
        double arp=(t->arp_idx+(double)t->arp_pos/div_samples((uint32_t)t->p[P_ARATE]))*drift_beats((uint32_t)t->p[P_ARATE]);
        bad+=check("tempo changes preserve sequence phase against wire pulse count",fabs(seq-400./24.)*1500.<2.);
        bad+=check("tempo changes preserve ARP phase against wire pulse count",fabs(arp-400./24.)*1500.<2.);
    }
    return bad;
}
static int drift_start_and_wrap(uint32_t source)
{
    int bad=0; drift_setup(source,120);
    transport_req=2; events_block(CTL);
    for(uint32_t i=0;i<8u;i++) {
        fm1_ms=i?100u+(i-1u)*21u:100u;
        uint32_t status=i?0xF8u:0xFAu;
        if(source==2u) um_byte(status); else midi_enqueue(0xFu|status<<8,source);
    }
    events_block(CTL);
    bad+=check("Start and seven queued clocks enter the first step before consuming progress",song.playing && trk[0].seq_idx==1u && trk[0].seq_pos==0u);
    drift_setup(source,120);
    midi_clock.pos=midi_clock.rendered=0xFFFFFC18u;
    drift_packet(source,0xF8,31u);
    bad+=check("musical counter wrap preserves forward track progress",midi_clock.pos==0u && trk[0].seq_pos>0u && trk[0].seq_idx==0u);
    return bad;
}

/* N_DIV's ten rates are legal for SEQ/ARP. Dotted divisions are delay-only.
 * Sum completed audible step durations and compare them with wire clocks;
 * odd pattern lengths deliberately restart the swing parity each loop. */
static int drift_all_divisions(uint32_t source)
{
    int bad=0;
    for(uint32_t div=0;div<10u;div++) for(uint32_t swing=0;swing<=100u;swing+=100u) {
        drift_setup(source,120);
        track_t *t=&trk[0];
        t->p[P_SDIV]=t->p[P_ARATE]=(int16_t)div;
        t->p[P_SSWING]=t->p[P_ASWING]=(int16_t)swing;
        t->p[P_SLEN]=17;
        t->seq_idx=t->seq_pos=t->arp_idx=t->arp_pos=0;
        midi_seq_grid[0].remainder=midi_arp_grid[0].remainder=0;
        uint64_t seq_done=0,arp_done=0;
        int seq_ok=1,arp_ok=1;
        for(uint32_t pulse=1;pulse<=768u;pulse++) {
            uint32_t si=t->seq_idx,ai=t->arp_idx;
            uint32_t period=div_samples(div),shift=period*swing/250u;
            drift_packet(source,0xF8,10u+pulse*125u/6u);
            if(t->seq_idx!=si) seq_done+=period+((si&1u)?-(int32_t)shift:(int32_t)shift);
            if(t->arp_idx!=ai) arp_done+=period+((ai&1u)?(int32_t)shift:-(int32_t)shift);
            double expected=(double)pulse/24.*period/drift_beats(div);
            seq_ok &= fabs((double)(seq_done+t->seq_pos)-expected)<1.01;
            arp_ok &= fabs((double)(arp_done+t->arp_pos)-expected)<1.01;
        }
        printf("source %u division %u swing %u: seq %s ARP %s\n",source,div,swing,seq_ok?"PASS":"FAIL",arp_ok?"PASS":"FAIL");
        bad+=check("all legal SEQ divisions retain sample phase through odd swing loops",seq_ok);
        bad+=check("all legal ARP divisions retain sample phase through swing pairs",arp_ok);
    }
    return bad;
}

static int drift_continue(uint32_t source)
{
    int bad=0; drift_setup(source,120);
    /* Released HOLD waits for transport; physically held keys now play locally. */
    trk[0].p[P_AHOLD]=1;
    input_off(&trk[0],60); input_off(&trk[0],64);
    for(uint32_t i=1;i<=11u;i++) drift_packet(source,0xF8,10u+i*125u/6u);
    drift_packet(source,0xFC,240u);
    track_t *t=&trk[0];
    uint32_t si=t->seq_idx,sp=t->seq_pos,ai=t->arp_idx,ap=t->arp_pos;
    uint32_t sr=midi_seq_grid[0].remainder,ar=midi_arp_grid[0].remainder;
    for(uint32_t i=1;i<=24u;i++) drift_packet(source,0xF8,240u+i*125u/6u);
    bad+=check("Stop freezes musical positions and fractional carries while clocks continue",
               !song.playing && t->seq_idx==si && t->seq_pos==sp && t->arp_idx==ai && t->arp_pos==ap &&
               midi_seq_grid[0].remainder==sr && midi_arp_grid[0].remainder==ar && !t->arp_note);
    drift_packet(source,0xFB,750u);
    drift_packet(source,0xF8,750u);
    bad+=check("Continue anchors its first pulse without resetting or advancing paused phase",
               song.playing && t->seq_idx==si && t->seq_pos==sp && t->arp_idx==ai && t->arp_pos==ap &&
               midi_seq_grid[0].remainder==sr && midi_arp_grid[0].remainder==ar);
    drift_packet(source,0xF8,771u);
    bad+=check("Continue resumes sequencer and held ARP on the following clock",
               t->seq_idx!=si || t->seq_pos!=sp);
    bad+=check("Continue resumes the ARP without dropping its held chord",
               (t->arp_idx!=ai || t->arp_pos!=ap) && t->nheld==2u);
    return bad;
}

static int drift_bounded_catchup(void)
{
    int bad=0; drift_setup(1,120);
    track_t *t=&trk[0];
    t->p[P_ARATE]=9; t->p[P_ASWING]=100;
    t->arp_idx=1u;
    /* A phase just before the longest legal old step, then hot-edit RATE
     * from 4BAR to 1/32. No wall-clock advancement during catch-up calls. */
    uint32_t slow=div_samples(9),fast=div_samples(3),sw=fast*100u/250u;
    uint32_t initial=slow+slow*100u/250u-1u,expected=initial,idx=1u;
    while(expected>=fast+((idx&1u)?sw:(uint32_t)-(int32_t)sw)) {
        expected-=fast+((idx&1u)?sw:(uint32_t)-(int32_t)sw);
        idx++;
    }
    t->arp_pos=initial; t->p[P_ARATE]=3;
    arp_step(t,0,0);
    bad+=check("extreme live ARP rate reduction fires at most eight overdue steps per block",
               t->arp_idx>1u && t->arp_idx<=9u && t->arp_pos>=fast);
    uint32_t paused_idx=t->arp_idx,paused_pos=t->arp_pos;
    t->p[P_AHOLD]=1; input_off(t,60); input_off(t,64);
    seq_stop();
    for(uint32_t i=0;i<4u;i++) arp_step(t,0,CTL);
    bad+=check("Stop freezes an outstanding bounded ARP catch-up backlog",
               t->arp_idx==paused_idx && t->arp_pos==paused_pos && !t->arp_note);
    song.playing=1;
    for(uint32_t i=0;i<64u && t->arp_idx<idx;i++) arp_step(t,0,0);
    bad+=check("bounded ARP catch-up retains every elapsed step and the exact sample remainder",
               t->arp_idx==idx && t->arp_pos==expected);
    /* All physical held keys are filtered out by WHITE quantization. The
     * list is empty although nheld is nonzero: arp_fire cannot advance idx. */
    t->nheld=1; t->held[0]=61; held_key[0][0]=2u; held_dt[0][0]=0;
    t->p[P_QUANT]=QN_WHITE;
    t->arp_idx=1; t->arp_pos=initial;
    uint32_t before=t->arp_pos;
    arp_step(t,0,0);
    bad+=check("filtered empty ARP list also bounds catch-up without losing pending phase",
               t->arp_idx==1u && t->arp_pos<before && before-t->arp_pos<=8u*(fast+sw) && t->arp_pos>=fast);
    return bad;
}

static int drift_chain_boundaries(uint32_t source)
{
    int bad=0;
    for(uint32_t div=0;div<10u;div++) {
        drift_setup(source,120); seq_stop();
        memset(&chain.source,0,sizeof chain.source);
        chain.config.count=2;
        chain.config.row[0]=chain_row_of(0,1);
        chain.config.row[1]=chain_row_of(1,1);
        chain.config.row[1].slot[0]=CHAIN_SILENT; /* the next section's clock moves to T2 */
        for(uint32_t k=0;k<NTRK;k++) {
            chain.source[0].timing[k][0]=1;
            chain.source[0].timing[k][1]=(int16_t)div;
            chain.source[0].timing[k][3]=64;
            chain.source[0].qnt[k]=1;
            chain.source[1].timing[k][0]=1;
            chain.source[1].timing[k][1]=5; /* 16T: exactly four wire clocks */
            chain.source[1].timing[k][3]=64;
            chain.source[1].qnt[k]=1;
        }
        chain.armed=1;
        drift_packet(source,0xFA,10u); drift_packet(source,0xF8,10u);
        uint32_t boundary=(uint32_t)(24.*drift_beats(div));
        int row_ok=1,phase_ok=1;
        for(uint32_t i=1;i<boundary+4u;i++) {
            drift_packet(source,0xF8,10u+i*125u/6u);
            row_ok &= song.playing && chain.running && chain.row==(i<boundary?0u:1u);
            if(i>=boundary) {
                double expected=(double)(i-boundary)*div_samples(5)/4.;
                phase_ok &= chain.clk==1u && trk[1].seq_idx==0u && fabs((double)trk[1].seq_pos-expected)<1.01;
            }
        }
        drift_packet(source,0xF8,10u+(boundary+4u)*125u/6u);
        bad+=check("SONG sections change on counted clock boundaries for every legal division",row_ok);
        bad+=check("SONG retains phase when the next section changes division and clock track",phase_ok);
        bad+=check("SONG stops on the final section's counted wire-clock boundary",!song.playing && !chain.running);
    }
    return bad;
}

/* Adapted from Tessera 87d0b3783c52e814435cad13e77611df1ef94160's tempo_flutter_test for millisecond input. */
static int drift_tempo_flutter(void)
{
    int bad = 0;
    for (uint32_t source = 1; source <= 2; source++) {
        drift_setup(source, 120);
        uint32_t start = 0xFFFFF000u;
        drift_packet(source, 0xFA, start);
        uint32_t min_beat = UINT32_MAX, max_beat = 0;
        int stable = 1, exact = 1;
        for (uint32_t pulse = 0; pulse <= 24u * 16u; pulse++) {
            uint32_t at = start + pulse * 125u / 6u + (pulse / 6u) % 2u;
            drift_packet(source, 0xF8, at);
            if (pulse >= 24u * 4u) {
                if (song.g[G_BPM] != 120) stable = 0;
                if (beat_samples() < min_beat) min_beat = beat_samples();
                if (beat_samples() > max_beat) max_beat = beat_samples();
            }
            if (pulse % 6u == 0 && (trk[0].seq_idx != pulse / 6u % 16u || trk[0].seq_pos)) exact = 0;
        }
        bad += check("jitter across millisecond wrap keeps displayed BPM at 120", stable);
        bad += check("jitter moves measured modulation period by less than 0.25 percent", max_beat - min_beat < FS / 800u);
        bad += check("smoothed tempo preserves exact six-clock step boundaries", exact);
        uint32_t last = start + 24u * 16u * 125u / 6u;
        for (uint32_t pulse = 1; pulse <= 6u; pulse++) drift_packet(source, 0xF8, last + pulse * 100u / 6u);
        bad += check("120 to 150 BPM locks within six clocks", song.g[G_BPM] == 150 && beat_samples() == FS * 2u / 5u);
        last += 100u;
        for (uint32_t pulse = 1; pulse <= 24u * 4u; pulse++)
            drift_packet(source, 0xF8, last + pulse * 60000u / (151u * 24u));
        bad += check("one-BPM edit reaches display within four beats", song.g[G_BPM] == 151);
        static const uint32_t bpm10[] = {400, 730, 1205, 1370, 2395, 2400};
        for (uint32_t k = 0; k < NELEM(bpm10); k++) {
            drift_setup(source, 120);
            drift_packet(source, 0xFA, start);
            uint32_t expected = FS * 600u / bpm10[k];
            int16_t shown = 0;
            int settled = 1, precise = 1, display_ok = 1;
            for (uint32_t pulse = 0; pulse <= 24u * 16u; pulse++) {
                uint32_t at = start + (uint32_t)((uint64_t)pulse * 600000u / (bpm10[k] * 24u)) + (pulse / 6u) % 2u;
                drift_packet(source, 0xF8, at);
                if (pulse == 24u * 4u) shown = song.g[G_BPM];
                if (pulse >= 24u * 4u) {
                    if (song.g[G_BPM] != shown) settled = 0;
                    if (song.g[G_BPM] * 10 < (int32_t)bpm10[k] - 10 || song.g[G_BPM] * 10 > (int32_t)bpm10[k] + 10) display_ok = 0;
                    if (beat_samples() + expected / 400u < expected || beat_samples() > expected + expected / 400u) precise = 0;
                }
            }
            char label[100];
            snprintf(label, sizeof label, "source %u %u.%u BPM BPM stays within one and modulation within 0.25 percent", source, bpm10[k] / 10u, bpm10[k] % 10u);
            /* Whole-ms timestamps add quantization to the master's jitter.
             * Near 240 BPM a fractional master can still cross the display's
             * hysteresis edge; measured modulation must remain precise. */
            bad += check(label, (settled || bpm10[k] == 2395u) && display_ok && precise && shown * 10 >= (int32_t)bpm10[k] - 10 && shown * 10 <= (int32_t)bpm10[k] + 10);
        }
        drift_setup(source, 120);
        for (uint32_t pulse = 1; pulse <= 6u; pulse++) drift_packet(source, 0xF8, 10u + pulse * 125u / 6u);
        drift_packet(source, 0xFC, 140u);
        drift_packet(source, 0xF8, 1000u);
        for (uint32_t pulse = 1; pulse <= 6u; pulse++) drift_packet(source, 0xF8, 1000u + pulse * 100u / 6u);
        bad += check("pulses after a stopped-master gap reacquire tempo in six clocks", !song.playing && song.g[G_BPM] == 150 && beat_samples() == FS * 2u / 5u);
    }
    return bad;
}

int main(void)
{
    int bad=drift_run(2,120,0,0)+drift_run(1,120,1,1)+drift_run(2,97,1,1)+
            drift_run(1,240,1,1)+drift_run(2,40,0,0);
    bad+=drift_tempo_edges(1)+drift_tempo_edges(2)+drift_start_and_wrap(1)+drift_start_and_wrap(2);
    bad+=drift_all_divisions(1)+drift_all_divisions(2)+drift_continue(1)+drift_continue(2)+drift_bounded_catchup();
    bad+=drift_tempo_flutter();
    bad+=drift_chain_boundaries(1)+drift_chain_boundaries(2);
    printf("MIDI LONG-RUN PHASE: %s\n",bad?"FAIL":"PASS");
    return bad!=0;
}
