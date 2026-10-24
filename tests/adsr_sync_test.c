/* SPDX-License-Identifier: GPL-3.0-only */
/* Real handlers, frozen-original full-render comparison, and two race boundaries. */
#include "adapter.h"
static uint32_t ota_now_ms(void){return fm1_ms;}
static void ota_idle(void){so_r=so_w;fm1_ms++;}
static void audio_silence(void){}
static void fl_inval(uint32_t o,uint32_t n){(void)o;(void)n;}
static int fl_erase4k(uint32_t o,uint32_t *t){(void)o;*t=0;return 0;}
static int fl_write(uint32_t o,const void *p,uint32_t n){(void)o;(void)p;(void)n;return 0;}
static int st_read(uint32_t o,void *p,uint32_t n){(void)o;(void)p;(void)n;return -1;}
static int st_prog(uint32_t o,const void *p,uint32_t n){(void)o;(void)p;(void)n;return -1;}
static int st_erase(uint32_t o){(void)o;return -1;}
static uint32_t flash_ok=1;
#include "@ROOT@/firmware/src/storage.c"
#include "@ROOT@/firmware/src/editor.c"
static void editor_set(uint32_t cmd,uint32_t id,int value){
 uint32_t v=(uint32_t)(value+8192);ota_frame_done();so_r=so_w;usb.config=1;
 sysex_byte(0xf0);sysex_byte(ED_HDR0);sysex_byte(ED_HDR1);sysex_byte(ED_HDR2);sysex_byte(cmd);
 sysex_byte(0);sysex_byte((uint8_t)id);sysex_byte(v&127);sysex_byte(v>>7);sysex_byte(0xf7);
 trace_need(sx_ready,"editor frame queued");ed_service();trace_need(TSEL->p[id]==value && ui.force,"editor actual service");so_r=so_w;
}
static FILE *pixels;
static unsigned checkpoints;
static unsigned forced_checks;
static void forced_oracle(void) {
 if((scrn.st!=SCR_ON && scrn.st!=SCR_SHOW) || ui.home || ui.layer || page_over || ui.menu || ui.confirm || name_on() || (cur_page()->graph!=GR_ADSR && cur_page()->graph!=GR_LFO))return;
 static uint16_t was[240u*240u];static __typeof__(ui) saved;
 lcd_sync();memcpy(was,host_screen,sizeof was);saved=ui;uint32_t ph=pr_shown;uint8_t valid=pr_valid;
 uint32_t bytes=wire_bytes,windows=wire_windows,gb=graph_bytes,gw=graph_windows,cb=canvas_begins,gbg=graph_begins;
 ui.force=1;felucca_dbg.stage=5;draw_graph();lcd_sync();
 trace_need(!memcmp(was+graph_y()*240u,host_screen+graph_y()*240u,graph_h()*240u*2u),"independent forced-render graph equality");
 forced_checks++;ui=saved;pr_shown=ph;pr_valid=valid;
 wire_bytes=bytes;wire_windows=windows;graph_bytes=gb;graph_windows=gw;canvas_begins=cb;graph_begins=gbg;
}
static void inject_cell(void){TSEL->p[cur_page()->id[0]]=93;trace_cell_hook=0;}
static void inject_blit(void){TSEL->p[cur_page()->id[0]]=32;trace_blit_hook=0;}
static void inject_value(void){if(felucca_dbg.stage==5){TSEL->p[cur_page()->id[0]]=93;trace_begin_hook=0;}}

static void queued(uint32_t st,uint32_t d1,uint32_t d2) {
 midi_enqueue((st>>4)|st<<8|d1<<16|d2<<24,1); events_block(CTL);
}
static void stat_reset(void) { wire_bytes=wire_windows=graph_bytes=graph_windows=canvas_begins=graph_begins=0; }
static void emit(const char *tag) {
 lcd_sync(); forced_oracle(); uint32_t hash=2166136261u;
 for(uint32_t i=0;i<240u*240u;i++)hash=(hash^host_screen[i])*16777619u;
 printf("%u %s %u %u %u %u %u %u %u\n",checkpoints++,tag,hash,wire_bytes,wire_windows,graph_bytes,graph_windows,canvas_begins,graph_begins);
 trace_need(fwrite(host_screen,sizeof host_screen,1,pixels)==1,"image output"); stat_reset();
}
static void stable(const char *tag) { for(uint32_t i=0;i<45;i++)frame();emit(tag); }
static void page_graph(uint32_t gr) { for(uint32_t i=0;i<NELEM(PAGES);i++) if(PAGES[i].graph==gr && page_visible(i)){ui.home=0;ui.page=i;page_entered();return;}trace_need(0,"page exists"); }
int main(int argc,char **argv) {
 trace_need(argc==2,"output argument");pixels=fopen(argv[1],"wb");trace_need(pixels!=0,"open image output");
 ui_power_on(); page_graph(GR_ADSR); stable("initial");
 for(uint32_t k=0;k<4;k++) { TSEL->p[cur_page()->id[k]]=(int16_t)(17+23*k); stable("direct-relevant"); }
 motion_clear(TSEL);motion_set_enabled(TSEL,1);lock_turn(0,1,1ull<<2);stable("inactive-lock");
 motion_step(TSEL,2,&motion,1);stable("lock-play");motion_step(TSEL,3,&motion,1);stable("lock-restore");
 motion_clear(TSEL);TSEL->p[P_M1SRC]=MS_LFO;TSEL->p[P_M1DST]=MD_PAN;TSEL->p[P_M1AMT]=91;
 {int16_t p[P_COUNT];memcpy(p,TSEL->p,sizeof p);mod_begin(TSEL);mod_end(TSEL);trace_need(!memcmp(p,TSEL->p,sizeof p),"MOD restored parameters");}stable("mod-negative");
 editor_set(ED_SET,P_ATK,39);stable("editor-relevant");editor_set(ED_SET,P_LEVEL,67);stable("editor-irrelevant-force");
 TSEL->p[P_ATK]=32;trace_begin_hook=inject_value;frame();emit("sync-changed-actual-view");
 TSEL->p[P_ATK]=32;stable("sync-ABA-followup");
 TSEL->p[P_ATK]=93;trace_blit_hook=inject_blit;frame();frame();emit("post-raster-followup");
 TSEL->p[P_ATK]=32;ui.force=1;trace_cell_hook=inject_cell;frame();TSEL->p[P_ATK]=32;frame();emit("saved-snapshot-live-render-followup");
 for(uint32_t k=0;k<4;k++){ui.hot_col=k;ui.hot_t=3;frame();emit("focus-only-hot");frame();frame();frame();emit("focus-only-cool");}
 TSEL->p[P_LEVEL]=31;stable("direct-level"); TSEL->p[P_ESYNC]^=1;stable("direct-esync");
 queued(0xb0,73,104);stable("cc-attack"); queued(0xb0,7,90);stable("cc-level");
 for(uint32_t k=0;k<4;k++){turn(EN_K1+k,1);emit("panel-hot");stable("panel-cool");}
 ui.force=1;frame();emit("forced-same");
 for(uint32_t k=0;k<NPALETTES;k++){palette_choose(k);stable("palette");}
 uint8_t page=ui.page;page_graph(GR_LFO);stable("lfo");TSEL->p[P_LEVEL]++;stable("lfo-irrelevant-conservative");
 ui.page=page;ui.home=0;page_entered();stable("adsr-return");
 uint8_t lfo=0;for(uint32_t i=0;i<NELEM(PAGES);i++)if(PAGES[i].graph==GR_LFO){lfo=i;break;}
 ui.page=lfo;ui.force=0;frame();emit("nonforced-lfo");ui.page=page;ui.force=0;frame();emit("nonforced-adsr");
 hold(B_HOME);emit("menu-open");hold(B_HOME);stable("menu-close");
 ui.home=0;ui.page=page;page_entered();stable("adsr-after-menu");
 ui.confirm=1;ui.force=1;frame();emit("confirm");ui.confirm=0;ui.force=1;stable("confirm-close");
 page_graph(GR_TRK);stable("tracks");ui.page=page;page_entered();stable("tracks-return");
 ui.home=1;ui.force=1;stable("home");ui.home=0;ui.page=page;page_entered();stable("home-return");
 scr_put(1);scrn.idle=fm1_ms-scr_limit();felucca_dbg.stage=0;ui_draw();trace_need(scrn.st==SCR_OFF,"sleep entered");emit("sleep");
 scr_touch();scr_wake();for(uint32_t i=0;i<20;i++)frame();trace_need(scrn.st==SCR_ON,"wake complete");emit("wake");
#ifdef ADSR_SYNC_TEST
#if FELUCCA_FM4
 set_engine(ENGI_DIGITAL);
#endif
 for(uint32_t k=0;k<NELEM(PAGES);k++)if(PAGES[k].graph==GR_ADSR && page_visible(k)){
  ui.page=(uint8_t)k;ui.home=0;page_entered();stable("all-adsr-pages");
  for(uint32_t n=0;n<4;n++){TSEL->p[PAGES[k].id[n]]=(int16_t)(11+31*n);stable("all-adsr-relevant");}
 }
#endif
 fprintf(stderr,"forced checks %u; ui bytes %zu\n",forced_checks,sizeof ui);
 fclose(pixels); return 0;
}
