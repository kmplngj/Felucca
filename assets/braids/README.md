<!-- SPDX-License-Identifier: MIT -->
# MACRO's Braids tables

`macro.json` contains the original WAV LINE sequence's 64 waves and the sine,
sine-fold and triangle-fold tables. Copyright 2012 Emilie Gillet; see
[MIT-Braids.txt](../../LICENSES/MIT-Braids.txt).

Source: [Mutable Instruments eurorack](https://github.com/pichenettes/eurorack/tree/08460a69a7e1f7a81c5a2abcc7189c9a6b7208d4/braids)
at revision `08460a69a7e1f7a81c5a2abcc7189c9a6b7208d4`.
The asset records SHA-256 hashes of `braids/resources.cc` and
`braids/digital_oscillator.cc`. `wave_line` preserves the indices in
`DigitalOscillator::RenderWaveLine`; `waves` contains their 129-byte slices from
`wt_waves` (128 samples and a wrap point). The other arrays are `wav_sine`,
`ws_sine_fold` and `ws_tri_fold`, each 257 signed 16-bit entries.

`tools/gen_macro.py` emits `build/gen/felucca_macro.h` without a network dependency.
It adds a duplicate of the last wave as an endpoint guard: at maximum TIMBRE the
next-wave interpolation stays at the final wave instead of indexing past the
64-entry sequence. Generated table payload: `65 * 129 + 3 * 257 * 2 = 9927` bytes.
The remaining Braids wave bank, tuning tables and delay buffers are unnecessary
for these models and are not bundled.

The C adaptation retains the selected topology and original table data. It uses
Felucca's tuning, control cadence and filters, so it does not claim sample identity
with Braids hardware or the M8 implementation. See [the engine notes](../../docs/macro-engine.md).
