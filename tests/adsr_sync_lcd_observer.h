/* SPDX-License-Identifier: GPL-3.0-only */
/* Independent real-lcd.c wire model; adapted from screen_capture_test.c. */
static struct { uint32_t stage; } felucca_dbg;
static const uint8_t *wire_src;
static uint8_t wire_copy[240u*240u*2u];
static uint32_t wire_n, wire_selected, wire_cmd, wire_x0, wire_x1, wire_y0, wire_y1, wire_x, wire_y;
static uint32_t wire_bytes, wire_windows, graph_bytes, graph_windows, canvas_begins, graph_begins;
static void (*trace_sync_hook)(void);
static void (*trace_begin_hook)(void);
static void (*trace_cell_hook)(void);
static void (*trace_blit_hook)(void);
static void trace_need(int ok, const char *s) { if (!ok) { fprintf(stderr,"wire: %s\n",s); exit(2); } }
static void fm1_lcd_hw_init(void) {}
static void fm1_lcd_baud(uint32_t b) { (void)b; }
static void fm1_lcd_backlight(uint32_t on) { (void)on; }
static void fm1_lcd_send_cmd(uint8_t c) {
 trace_need(!wire_selected && !wire_src,"idle command"); wire_selected=1; wire_cmd=c; wire_bytes++;
 if(c==0x2c) { wire_x=wire_x0; wire_y=wire_y0; wire_windows++;
  if(felucca_dbg.stage==5) { graph_windows++; graph_bytes+=11; } }
}
static void fm1_lcd_send_data(const void *p,uint32_t n) {
 trace_need(!wire_selected && !wire_src && n && n<=sizeof wire_copy,"bounded idle data");
 wire_selected=1; wire_src=p; wire_n=n; memcpy(wire_copy,p,n); wire_bytes+=n;
 if(wire_cmd==0x2c && felucca_dbg.stage==5) graph_bytes+=n;
}
static void fm1_lcd_wait(void) {
 trace_need(wire_selected,"selected completion"); if(!wire_src) return;
 trace_need(!memcmp(wire_src,wire_copy,wire_n),"DMA source lifetime");
 if(wire_cmd==0x2a || wire_cmd==0x2b) {
  trace_need(wire_n==4,"address bytes"); uint32_t a=wire_src[0]*256u+wire_src[1],b=wire_src[2]*256u+wire_src[3];
  trace_need(a<=b && b<240,"window bounds");
  if(wire_cmd==0x2a) {wire_x0=a;wire_x1=b;} else {wire_y0=a;wire_y1=b;}
 } else {
  trace_need(wire_cmd==0x2c && !(wire_n&1),"RGB565 data");
  for(uint32_t i=0;i<wire_n;i+=2) {
   trace_need(wire_x<=wire_x1 && wire_y<=wire_y1,"window pixel bounds");
   host_screen[wire_y*240u+wire_x]=(uint16_t)(wire_src[i]|wire_src[i+1]<<8);
   if(++wire_x>wire_x1){wire_x=wire_x0;wire_y++;}
  }
 }
 wire_src=0;wire_n=0;
 if(trace_sync_hook) trace_sync_hook();
}
static void fm1_lcd_deselect(void){ trace_need(wire_selected&&!wire_src,"idle deselect");wire_selected=0; }
#include "@ROOT@/firmware/src/lcd.c"
#define GFX_HOOKS 1
#define GFX_HOOK_TEXT(x0,y0,x1,y1,s,flags) ((void)0)
#define GFX_HOOK_BLIT(x,y,r0) do { if(felucca_dbg.stage==5 && trace_blit_hook)trace_blit_hook(); } while(0)
#define GFX_HOOK_CELL(x0,y0,x1,y1) do { if(felucca_dbg.stage==5 && trace_cell_hook)trace_cell_hook(); } while(0)
#define GFX_HOOK_RECT(x,y,w,h) ((void)0)
#define GFX_HOOK_PIXELS(n) ((void)0)
#define GFX_HOOK_BEGIN() do { canvas_begins++; if(felucca_dbg.stage==5){graph_begins++;if(trace_begin_hook)trace_begin_hook();} } while(0)
