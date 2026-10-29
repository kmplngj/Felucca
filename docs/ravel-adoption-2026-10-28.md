<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Ravel adoption review — 2026-10-28

Tracking: [Felucca #762](https://github.com/kmplngj/Felucca/issues/762).

<!-- felucca-upstream:De-Pattern/Ravel_FM1@d7f51158f581050022fa35a691eddd4c078a9ab1:adoption-plan -->
## Recommendation
Selectively adapt Ravel's distinctive instruments and bounded musical controls. Do not replace Felucca's audio engine, HAL, storage, scheduler or project format.

Source review 2026-10-28: [Ravel main](https://github.com/De-Pattern/Ravel_FM1/tree/d7f51158f581050022fa35a691eddd4c078a9ab1/) at `d7f51158f581050022fa35a691eddd4c078a9ab1`; Felucca main `05a3de5fa60b2e940424f7e6e9a036c7e0b0008f`, MIT engine pin `9630426f5c4a34a209ca851356fbe8ba3c4c6d19`. Full donor main DAG fetched: 105 reachable commits, connectivity checked, no per-commit review coverage claimed.

Ravel is C99/single-precision float with 8 tracks, 8 shared synth voices and default 128-frame control steps (`RV_SUB`; the engine-file overview still says 32); FM-1 DMA halves are 512 frames (two 256-frame renders). Felucca uses its own fixed-point engine contracts, four parts, 32-frame control blocks and 128-frame DMA halves. Same hardware is not proof of fit. Donor README explicitly leaves hardware validation pending and has stale/conflicting storage/resource descriptions; prefer pinned source and fresh builds. The donor's separate `software` branch is outside this intake.

## Ordered plan
1. **Optimization experiments now, using existing owners.** #459: one measured hot DSP kernel in SRAM, using Ravel's explicit section/load/far-call implementation as additional evidence. #17: optional half-rate delay quality/memory A/B; Ravel implements paired writes and interpolated reads, but changes delay length, quantization and tone. Keep each experiment independent. Exact coefficient/mixer caches remain #179/#180/#160; idle preparation #161 and no-send specialization #185. No measured native speedup is claimed.
2. **Portable instrument audition.** Start ORGAN: pipe ranks, staggered speech, chiff/air/wind differ from WHEEL's tonewheel/rotary character. Then PARTICLE (coupled pulsarets) and LOGIC (function-block oscillators). TINE and RESIN later, after numerical/resource/provenance gates. Portable copied code/assets/generators go to **kmplngj/Felucca-Engines-GPL**.
3. **Optional host integration.** Depends on a reviewed portable engine and #360's GPL collection/profile support. Pin exact commits; preserve native sound-install, arena, stable IDs, native controls, old projects and omitted-engine round trips. Start one engine/one bounded voice allocation; standard profile stays unchanged until separately accepted.
4. **Feature reuse, then larger design experiments.** Ravel curved/windowed macro mappings strengthen #33; A/B/gliding scenes #32; explicit Euclidean editing #124/#214; tape/grain effect ideas #73 and compressor reference #613. Graph sequencing with two heads, bounded chainable envelopes and cross-track influence are later design candidates: agree native timing, recursion/event limits, control precedence, UI and storage allocation before implementation. More tracks stays #369. Do not import an eight-track graph or new .ravel format as engine glue.
5. **Firmware watch.** Register canonical `De-Pattern/Ravel_FM1`, repository ID `1425709397`, branch `main`, immutable pin above as **pending initialization** through a reviewed main PR. Existing watcher reconciles it into the canonical state branch and re-verifies identity/pin/full history before activation. No second automation, schedule change, fabricated journal entries or historical credit.

## Instrument decisions
| Candidate | First scope | Caveat |
|---|---|---|
| ORGAN | Original pipe-rank renderer and generated spectra | Audition against WHEEL; 3,840 B raw table is not linked total |
| PARTICLE | One bounded coupled-pulsaret voice | Preserve phase/coupling/RNG order; measure anti-aliasing |
| LOGIC | Arithmetic/logic oscillator, then optional self-grains | 1,024 int16 samples = 2,048 B per grain-enabled voice; 16 controls need explicit mapping |
| TINE | One kalimba/bar model before EP variants | Exciter/body/pickup and dense-tail cost |
| RESIN | Bow/reed numerical prototype | Verify 'after STK saxophone' provenance; nonlinear stability and memory |
| CZ/FM/VA/CHIP/PHYS/WAVE/PERC | Compare/reuse existing engines and adoption owners | Avoid duplicate ports: GPL #4 CZ, #19 FM4, #29 TRX/EFM; WAVE S/DUELL and native PHYS/FM6 already have owners |

## Evidence
- [Instrument code](https://github.com/De-Pattern/Ravel_FM1/blob/d7f51158f581050022fa35a691eddd4c078a9ab1/firmware/app/rv_synth.c), [state](https://github.com/De-Pattern/Ravel_FM1/blob/d7f51158f581050022fa35a691eddd4c078a9ab1/firmware/app/rv_int.h), [ORGAN generator](https://github.com/De-Pattern/Ravel_FM1/blob/d7f51158f581050022fa35a691eddd4c078a9ab1/tools/gen_organ.py), [percussion](https://github.com/De-Pattern/Ravel_FM1/blob/d7f51158f581050022fa35a691eddd4c078a9ab1/firmware/app/rv_perc.c).
- [RAM code macros](https://github.com/De-Pattern/Ravel_FM1/blob/d7f51158f581050022fa35a691eddd4c078a9ab1/firmware/app/rv_math.h#L20-L29), [linker](https://github.com/De-Pattern/Ravel_FM1/blob/d7f51158f581050022fa35a691eddd4c078a9ab1/firmware/fm1/app.ld), [delay](https://github.com/De-Pattern/Ravel_FM1/blob/d7f51158f581050022fa35a691eddd4c078a9ab1/firmware/app/rv_bus.c#L230-L374).
- [Modulation/envelope chains](https://github.com/De-Pattern/Ravel_FM1/blob/d7f51158f581050022fa35a691eddd4c078a9ab1/firmware/app/rv_mod.c), [graph/scenes/influence](https://github.com/De-Pattern/Ravel_FM1/blob/d7f51158f581050022fa35a691eddd4c078a9ab1/firmware/app/rv_seq.c), [licenses](https://github.com/De-Pattern/Ravel_FM1/blob/d7f51158f581050022fa35a691eddd4c078a9ab1/THIRD_PARTY.md).
- Ravel's threshold-based effect sleep is not a replacement for native exact-tail/state-preserving silent FX, already implemented (#41/#159/#263/#558). Native mode/partial-major loops also already exist. Do not import donor cache-RAM/debug-memory reuse, FPU enablement or wholesale -O2 as a presumed optimization.

## Acceptance and completion
- [ ] Linked portable instrument experiment and native integration owner record exact scope and dependencies.
- [ ] Optimization owners contain pinned source evidence, one-cause A/B work and retain/reject criteria.
- [ ] Registration PR validates; after merge, watcher independently initializes and publishes verified state (pending until then).
- [ ] Each implementation records baseline/candidate, toolchain/flags/profile/pins, app/RAM/POOL/RAMTEXT/NOINIT/stack, host PCM/future-state and target static evidence separately from FM-1 timing/listening. Preserve nested TIMER5, USB 44.1/48 kHz, USB/TRS MIDI, CPU2 OFF/ON/failure and transition/tail correctness.
- [ ] Audit copied files, presets, tables, generators and transitive dependencies; keep GPL and MAME BSD notices. Unknown provenance blocks copying that material.
- [ ] Close each pilot with adopt/revise/defer/reject, not an assumed all-instruments merge.

Planning/source inspection only: no firmware changes, benchmarks, target builds, donor scripts or FM-1 tests performed. README/changelog/diagnostics need no capability claim for this intake.

## Created work
- Portable instruments: [Engines-GPL #39](https://github.com/kmplngj/Felucca-Engines-GPL/issues/39).
- Native integration: #763.
- Existing optimization owners #459, #17 and #179 now contain pinned Ravel implementation evidence; no duplicate optimization issues created.
