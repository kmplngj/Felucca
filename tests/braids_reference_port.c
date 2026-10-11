/* SPDX-License-Identifier: GPL-3.0-only */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "reference.h"
static braids_MacroOscillator osc;
void port_init(int shape,int pitch,int timbre,int color) {
 memset(&osc,0,sizeof osc); braids_MacroOscillator_Init(&osc);
 osc.shape_ = shape; osc.digital_oscillator_.rng_ = 0x21;
 braids_MacroOscillator_set_pitch(&osc,pitch);
 braids_MacroOscillator_set_parameters(&osc,timbre,color);
}
void port_run(short* out) { unsigned char sync[24]={0}; braids_MacroOscillator_Render(&osc,sync,out,24); }
