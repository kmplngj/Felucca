<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Target cost comparison, 2026-10-12

Fresh JieLi Clang 4.0.1/pi32v2 builds, `-Os -ffunction-sections -fno-builtin`, selective minsize, default features/assets and AC79 SDK `d179b4484759423312073f5fbb232501aa491047`. Both builds pass resource/HAL/loader checks without compiler warnings. These are static heuristic counts, not FM-1 cycles or device timings.

Checker SHA-256: before `899637a7e1c1b57c111b4295f6730297237370b29a634a25ef9db649300de57b`; after `a33a7e54a73fdb6fd13b27ec016ee40a7b532b58acd0a30a92a6327b79a6f4c3`.

The original checker is main `19a7081`; the candidate adds input rejection and safe zero-budget reporting. No weights, tolerance or target baselines changed. Raw reports and build logs are retained under ignored `build/pr-review/`. The separate MACRO source branch is measured for coverage; it is not integrated into main.

## main: `19a70814e48793f956040ed236467fc22da92d8f`

All 62 configured entries have identical before/after results. `absent` denotes a function absent from this configuration, not zero cost.

| Function | Before | After |
| --- | ---: | ---: |
| `analog_render` | 614 | 614 |
| `digital_render` | absent | absent |
| `digital_render_legacy` | absent | absent |
| `digital_render_custom` | absent | absent |
| `phase_render` | 77 | 77 |
| `lofi_render` | 123 | 123 |
| `sample_render` | 128 | 128 |
| `formant_render` | 312 | 312 |
| `trio_render` | 341 | 341 |
| `trio_pass` | 175 | 175 |
| `wheel_render` | 267 | 267 |
| `wheel_block` | 86 | 86 |
| `grain_render` | 1723 | 1723 |
| `grain_block` | 137 | 137 |
| `phys_render` | 61 | 61 |
| `drum_render` | 89 | 89 |
| `noise_render` | 259 | 259 |
| `fm6_render` | 363 | 363 |
| `fm6_op_run` | 72 | 72 |
| `fm6_op_fb` | 26 | 26 |
| `px_modal_block` | 111 | 111 |
| `px_modal_run` | 195 | 195 |
| `px_memb_block` | 106 | 106 |
| `px_string_excite` | 171 | 171 |
| `px_string_run` | 264 | 264 |
| `px_symp_run` | 252 | 252 |
| `dv_metal_run` | 26 | 26 |
| `dv_kick_run` | 151 | 151 |
| `dv_snare_run` | 154 | 154 |
| `dv_clap_run` | 74 | 74 |
| `dv_hat_run` | 61 | 61 |
| `dv_tom_run` | 75 | 75 |
| `dv_rim_run` | 61 | 61 |
| `dv_bell_run` | 52 | 52 |
| `dv_cym_run` | 67 | 67 |
| `dv_out` | 35 | 35 |
| `dv_metal_mix` | 16 | 16 |
| `slicer_track` | 557 | 557 |
| `slice_render` | 436 | 436 |
| `slc_rev` | 120 | 120 |
| `fm1_alnk0_irq` | 38871 | 38871 |
| `fm1_timer5_irq` | 35056 | 35056 |
| `uac_tap48` | 504 | 504 |
| `click_render` | 30 | 30 |
| `mod_begin` | 168 | 168 |
| `mod_voice` | 30 | 30 |
| `mod_end` | 7 | 7 |
| `perf_begin` | 28 | 28 |
| `perf_mute` | 19 | 19 |
| `perf_pre` | 26 | 26 |
| `perf_block` | 846 | 846 |
| `perf_master` | 32 | 32 |
| `perf_flanger` | 368 | 368 |
| `perf_phaser` | 448 | 448 |
| `perf_throw` | 52 | 52 |
| `rev_room` | 218 | 218 |
| `rev_spring` | 127 | 127 |
| `rev_hall` | 1994 | 1994 |
| `rev_side_mix` | 8 | 8 |
| `track_insert` | 3 | 3 |
| `ins_drive` | 272 | 272 |
| `ins_swept` | 230 | 230 |

## macro: `c2d91aa4c71b4294e44d8fcbddc4f0ec28956ccc`

All 79 configured entries have identical before/after results. `absent` denotes a function absent from this configuration, not zero cost.

| Function | Before | After |
| --- | ---: | ---: |
| `analog_render` | 614 | 614 |
| `digital_render` | absent | absent |
| `digital_render_legacy` | absent | absent |
| `digital_render_custom` | absent | absent |
| `phase_render` | 77 | 77 |
| `lofi_render` | 123 | 123 |
| `sample_render` | 128 | 128 |
| `formant_render` | 312 | 312 |
| `trio_render` | 341 | 341 |
| `trio_pass` | 175 | 175 |
| `wheel_render` | 267 | 267 |
| `wheel_block` | 86 | 86 |
| `grain_render` | 1723 | 1723 |
| `grain_block` | 137 | 137 |
| `phys_render` | 61 | 61 |
| `drum_render` | 89 | 89 |
| `noise_render` | 259 | 259 |
| `fm6_render` | 363 | 363 |
| `fm6_op_run` | 72 | 72 |
| `fm6_op_fb` | 26 | 26 |
| `px_modal_block` | 111 | 111 |
| `px_modal_run` | 192 | 192 |
| `px_memb_block` | 106 | 106 |
| `px_string_excite` | 171 | 171 |
| `px_string_run` | 264 | 264 |
| `px_symp_run` | 252 | 252 |
| `dv_metal_run` | 26 | 26 |
| `dv_kick_run` | 151 | 151 |
| `dv_snare_run` | 154 | 154 |
| `dv_clap_run` | 74 | 74 |
| `dv_hat_run` | 61 | 61 |
| `dv_tom_run` | 75 | 75 |
| `dv_rim_run` | 61 | 61 |
| `dv_bell_run` | 52 | 52 |
| `dv_cym_run` | 67 | 67 |
| `dv_out` | 35 | 35 |
| `dv_metal_mix` | 16 | 16 |
| `slicer_track` | 557 | 557 |
| `macro_render` | 19591 | 19591 |
| `mac_waveline` | 832 | 832 |
| `mac_fold` | 302 | 302 |
| `mac_fbfm` | 43 | 43 |
| `macro_block` | 20 | 20 |
| `braids_AnalogOscillator_Render` | 1207 | 1207 |
| `braids_DigitalOscillator_ComputeDelay` | 0 | 0 |
| `braids_DigitalOscillator_ComputePhaseIncrement` | 0 | 0 |
| `braids_DigitalOscillator_InterpolateFormantParameter` | 0 | 0 |
| `braids_DigitalOscillator_Render` | 3 | 3 |
| `braids_DigitalOscillator_RenderDigitalFilter` | 114 | 114 |
| `braids_DigitalOscillator_dispatch` | 3960 | 3960 |
| `braids_MacroOscillator_RenderDigital` | 0 | 0 |
| `braids_MacroOscillator_RenderDualSync` | 16 | 16 |
| `braids_MacroOscillator_RenderSub` | 19 | 19 |
| `braids_MacroOscillator_RenderTriple` | 64 | 64 |
| `braids_Svf_Process` | 0 | 0 |
| `slice_render` | 436 | 436 |
| `slc_rev` | 120 | 120 |
| `fm1_alnk0_irq` | 38871 | 38871 |
| `fm1_timer5_irq` | 35056 | 35056 |
| `uac_tap48` | 504 | 504 |
| `click_render` | 30 | 30 |
| `mod_begin` | 168 | 168 |
| `mod_voice` | 30 | 30 |
| `mod_end` | 7 | 7 |
| `perf_begin` | 28 | 28 |
| `perf_mute` | 19 | 19 |
| `perf_pre` | 26 | 26 |
| `perf_block` | 846 | 846 |
| `perf_master` | 32 | 32 |
| `perf_flanger` | 368 | 368 |
| `perf_phaser` | 448 | 448 |
| `perf_throw` | 52 | 52 |
| `rev_room` | 218 | 218 |
| `rev_spring` | 127 | 127 |
| `rev_hall` | 1994 | 1994 |
| `rev_side_mix` | 8 | 8 |
| `track_insert` | 3 | 3 |
| `ins_drive` | 272 | 272 |
| `ins_swept` | 230 | 230 |

