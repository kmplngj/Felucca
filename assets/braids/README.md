<!-- SPDX-License-Identifier: MIT -->
# MACRO's Braids source and tables

The original MIT DSP and resource inputs are bundled in `upstream/`, with their
original notices and byte hashes in `upstream/SHA256.json`. Braids is by Emilie
Gillet; the complete notice is in [MIT-Braids.txt](../../LICENSES/MIT-Braids.txt).

- [eurorack / Braids](https://github.com/pichenettes/eurorack/tree/08460a69a7e1f7a81c5a2abcc7189c9a6b7208d4/braids),
  revision `08460a69a7e1f7a81c5a2abcc7189c9a6b7208d4`.
- [stmlib](https://github.com/pichenettes/stmlib/tree/e3bd7c9cc00e4364166f9905c0509b6ffd0535ec),
  the pinned submodule revision `e3bd7c9cc00e4364166f9905c0509b6ffd0535ec`.

`tools/gen_braids.py` verifies those hashes and emits the file-local, MIT
`build/gen/felucca_braids.h` offline. It translates the classes, overloads and
method tables into C, gives each part its own RNG, and retunes the original 96 kHz
phase/delay tables for two source samples per 44.1 kHz output frame. The delay
storage and complete 256-wave resource bank are retained. `c-arithmetic.json`
records explicit unsigned wrapping for the source's signed shifts, additions and
products. No C++ runtime, heap or network access is needed to build firmware.

`models.json` records the stable Felucca IDs, upstream IDs and control meanings.
WAVE/FOLD/FBFM retain IDs 0/1/2 and their existing adaptations. The remaining
45 source models append IDs 3..47, including the two SUB models and QUESTION.
This is a source-bank port, without a claim of exact M8 firmware/sound parity.

`macro.json` remains the original three-model extraction/provenance record:
`wave_line` is the original 64-entry WAV LINE index sequence, `waves` are 129-byte
slices of `wt_waves`, and the sine/folding arrays each have 257 signed 16-bit
entries. `tools/gen_macro.py` now points into the shared full bank instead of
emitting a duplicate 9,927-byte payload. It repeats the last wave pointer as the
endpoint guard, preserving the legacy interpolation and sound hashes.

The original 96 kHz C++ versus C comparison is rebuilt offline by
`tests/braids_reference.py`; strict bounds/arithmetic and Felucca integration are
covered by `tests/braids_test.c`. See [the engine notes](../../docs/macro-engine.md)
for resource costs, rate adaptation, polyphony and validation limits.
