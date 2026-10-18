/* SPDX-License-Identifier: GPL-3.0-only */
#define main hostsim_main
#include FX_TEST_HOSTSIM
#undef main
#include <assert.h>
/* Identical native timelines for the old mixer, candidate, and unedited control. */
int main(int argc, char **argv) {
    assert(argc == 7);
    const char *dir = argv[1]; int chord=atoi(argv[2]), spread=atoi(argv[3]), bus=atoi(argv[4]), mode=atoi(argv[5]), edit=atoi(argv[6]);
    char path[1024]; FILE *raw, *wav[4]; const char *names[]={"chorus","delay","reverb","master"};
    snprintf(path,sizeof path,"%s/data.bin",dir); raw=fopen(path,"wb"); assert(raw);
    for(int k=0;k<4;k++){snprintf(path,sizeof path,"%s/%s.wav",dir,names[k]); wav[k]=fopen(path,"wb"); assert(wav[k]);wav_hdr(wav[k],32768);}
    host_tracks_init(); host_preset(&trk[0],0,0);
    track_t *t=&trk[0]; t->p[P_DIST]=t->p[P_ITYPE]=0; t->p[P_AMODE]=0; t->p[P_SPRD]=spread?127:0;
    t->p[P_ATK]=0;t->p[P_DEC]=0;t->p[P_SUS]=127;t->p[P_REL]=16;t->p[P_LEVEL]=mode==8?127:88;
    t->p[P_E0]=chord?0:3;t->p[P_E1]=0;t->p[P_E2]=0;t->p[P_E3]=127;t->p[P_E4]=0;t->p[P_E5]=0;t->p[P_E6]=0;t->p[P_E7]=0;
    song.g[G_DMIX]=64; song.g[G_DFDBK]=0; song.master_q12=2048;
    for(int k=0;k<(mode==8?8:chord?4:1);k++)trk_note_on(t,57+k*4,110);
    int32_t out[2*CTL];
    for(uint32_t at=0;at<32768;at+=CTL){
        int gain=(mode==1 || mode==5)?127:mode==2?63:0;
        if(edit && at>=8192){if(mode==0)gain=127;else if(mode==1 || mode==5)gain=0;else if(mode==2)gain=64;else if(mode==3)gain=((at/CTL)&1)?127:0;else if(mode==6)gain=127;else gain=clamp(((int)at-8192)/512,0,127);}
        if(mode>=7)gain=edit && at>=1024 && at<16896 ? (((at/CTL)&1)?0:127) : 0;
        t->p[P_CHOR]=(bus&1)?gain:0;t->p[P_DLY]=(bus&2)?gain:0;t->p[P_REV]=(bus&4)?gain:0;
        if(mode>=5 && at==1024){perf_press(PF_RTHR,1);perf_press(PF_ETHR,1);}
        if(mode>=5 && at==16384){perf_press(PF_RTHR,0);perf_press(PF_ETHR,0);}
        mix_block(out,CTL);
        for(uint32_t i=0;i<CTL;i++) {int32_t row[]={send_c[i],send_d[i],send_r[i],out[2*i],out[2*i+1],experiment_dry[0][i],experiment_dry[1][i]}; fwrite(row,sizeof row,1,raw);for(int k=0;k<3;k++)wav_put(wav[k],row[k],row[k]);wav_put(wav[3],row[3],row[4]);}
    }
    fclose(raw);for(int k=0;k<4;k++)fclose(wav[k]);
    snprintf(path,sizeof path,"%s/engine-state.bin",dir); FILE *state=fopen(path,"wb"); assert(state);
    for (int k=0;k<NTRK;k++) {
        fwrite(trk[k].v,sizeof trk[k].v,1,state);
        fwrite(&trk[k].lfo_ph,sizeof trk[k].lfo_ph,1,state);
        fwrite(&trk[k].lfo_rnd,sizeof trk[k].lfo_rnd,1,state);
    }
    fwrite(&rng_state,sizeof rng_state,1,state);fwrite(&mod_seed,sizeof mod_seed,1,state);fclose(state);
    return 0;
}
