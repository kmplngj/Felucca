/* SPDX-License-Identifier: GPL-3.0-only */
#include <cstdio>
#include <cstring>
#include "braids/macro_oscillator.h"
#include "stmlib/utils/random.h"
extern "C" void port_init(int,int,int,int);
extern "C" void port_run(short*);
int main() {
 static braids::MacroOscillator osc;
 unsigned char sync[24]={0}; short a[24],b[24]; int failures=0;
 for(int model=0;model<48;model++) for(int t=0;t<3;t++) for(int c=0;c<3;c++) {
  int timbre=t==2?32767:t*16384,color=c==2?32767:c*16384;
  // Comb's historical negative-delay shift is corrected in the C adaptation.
  if(model==15 && t==0)continue;
  memset((void*)&osc,0,sizeof osc); osc.Init();osc.set_shape(static_cast<braids::MacroOscillatorShape>(model));
  osc.set_pitch(69*128);osc.set_parameters(timbre,color); stmlib::Random::Seed(0x21);
  port_init(model,69*128,timbre,color);
  for(int block=0;block<200;block++) {
   osc.Render(sync,a,24);port_run(b);
   if(memcmp(a,b,sizeof a)) { printf("FAIL model %d t%d c%d block %d\n",model,t,c,block); failures++;break; }
  }
 }
 printf("original 96 kHz C++ / C translation: %d failures\n",failures);return failures!=0;
}
