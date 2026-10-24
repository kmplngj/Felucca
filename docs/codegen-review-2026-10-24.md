<!-- SPDX-License-Identifier: GPL-3.0-only -->
# pi32v2 code-generation review — 2026-10-24

A community guide on r/MVaveFM1 ("All right, stop, collaborate and listen", October 2026)
recommends FM1 Open's compiler and linker switches, `-O2` for hot code, reciprocal
multiplies and 32-bit intermediates. This review checks each recommendation against
static target builds of Felucca. Its results:

- The CPU and FPU switches change nothing for Felucca's integer DSP.
- Two source-level patterns are real opportunities: constant divisors and wide 64-bit products.
- `-O2` is not a drop-in change.

This is static evidence only: no FM-1 timing, listening or device test was performed,
and no firmware or flag changed. Durable rules live in
[performance.md](performance.md#pi32v2-code-generation); the tracking summary is on
[#24](https://github.com/kmplngj/Felucca/issues/24).

## Inputs

| Input | Revision / identity |
| --- | --- |
| Felucca main | `f101979be19de475a6733e917bccc07733c87a65`, standard profile, default flags (`FELUCCA_CPU2=1`) |
| MIT Engines, firmware pin | `9630426f5c4a34a209ca851356fbe8ba3c4c6d19` |
| Toolchain | `jieli-linux-toolchains-20260730.1` from `tools/get_toolchain.sh`, clang 4.0.1; `pi32v2/bin/clang` SHA-256 `c45189ee624de0430deb0db02e6dce171fb5538e7fe323e3964dc8ac6236240f` |
| FM1 Open V14 | [`m-vave/fm1_open` `4c7496da`](https://github.com/m-vave/fm1_open/blob/4c7496daac04a95ff10d1afdcc8f9ead2dbabc41/sdk/Build.ps1#L358-L421): Windows toolchain 2.5.3, the same PI32v2 clang 4.0.1, `r3` target |
| Community guide | r/MVaveFM1 post, text supplied by the owner; a recommendation, not a measurement |

Each variant ran `tools/build.py`'s own `generate()`, `build_app()` and `check()`, with no
package and no SDK, and `tests/target_budget.py` on the resulting listing with its sidecar.
Two unchanged rebuilds were byte-identical to the baseline, so image comparisons are exact.
The MACRO profile and `FELUCCA_CPU2=0` were not built. The baseline app is 496,316 B
(85,248 B below `APP_SLOT`). RAM is 62,392 of 73,728 B, POOL 336,440 of 368,640 B,
and NOINIT has 120 B spare.

## Compiler and backend switches

The driver selects the `generic` pi32v2 CPU when no `-mcpu` is given, and `tools/build.py`
gives none. `-mcpu=help` lists r1–r5 variants and the features `fprev1`/`fprev2`, `simd`,
`instrev1..3`, `round-64`, `full-rep`, `cordic` and `secext`. `generic` already has
32×32→64 multiplies, the hardware divide, zero-overhead loops, `smax` and conditional blocks.

| Variant (added to the default flags) | App | Result |
| --- | --- | --- |
| `-mcpu=r3` | 496,316 B | Byte-identical image |
| `-mcpu=r3 -mfprev1` | 496,316 B | Byte-identical: no float code to change; FPU kernels remain [#82](https://github.com/kmplngj/Felucca/issues/82) |
| `-mllvm -pi32v2-enable-simd=true` | 496,316 B | Byte-identical |
| `-mllvm -enable-ipra=true` | 496,316 B | Byte-identical |
| `-mllvm -pi32v2-enable-rep-memop` | 495,932 B | −384 B; 25 functions, 3 of them ISR-reachable: [#626](https://github.com/kmplngj/Felucca/issues/626) |
| `-mllvm -global-merge-on-const -mllvm -pi32v2-merge-max-offset=4096` | 505,860 B | +9,544 B; render loops slightly larger; budget failure. Reject |
| `-mllvm -pi32v2-large-program=true` | 507,300 B | +10,984 B; `usb_poll` +84 % over budget. Reject |
| IR and code at `-O2`, `minsize` pass kept | — | Link fails: `__udivdi3` from `px_modal_exciter`: [#625](https://github.com/kmplngj/Felucca/issues/625) |
| FM1 Open's combined set (`-O2`, `r3`, `fprev1`, SIMD, IPRA, rep-memop, global merge) | — | Same link failure |

`-O2` in more detail. In the unlinked object, `.text` grows from 286,022 to 338,762 B
(+18 %) and the audio ISR body from 5,012 to 8,214 B. Innermost kernels are
instruction-identical: `analog_render*`, `fm6_op_run`/`fm6_op_fb`, `px_string_run`,
`px_symp_run`, ROOM, SPRING, `perf_block` and all drum voices. The rest is inlining that
moves work between functions, which the static estimator cannot rank. Single-TU Felucca
already gets whole-program inlining, so FM1 Open's `-flto` has no separate counterpart.

## Arithmetic patterns

**Division is never strength-reduced.** At `-Os` and at `-O2`, the backend emits the
hardware divide for every signed division and for every unsigned non-power-of-two
divisor. Only unsigned powers of two become shifts and masks. A pointer difference between
elements of a non-power-of-two struct is a divide: `sizeof(track_t)` is 1,840 B, so
`t - trk` divides by 1840. A heuristic scan finds about 250 constant-divisor divides in
the 594 audio- or TIMER5-reachable functions: `t - trk` in 57 functions, per-block
`/100`, `/127` and `/16000` scaling, 36 in `drum_render`, and `/250` and `/2902` in the
audio ISR. Exact replacements are [#623](https://github.com/kmplngj/Felucca/issues/623),
gated on the FM-1 cost of `div`, which is not yet measured. #7 keeps the variable
limiter divide.

**Wide products cost three multiplies.** A product with a 64-bit operand compiles to a
sign extension, three multiplies and an add chain. The guide's `bad_fn`/`good_fn` take
11 and 6 instructions. Hot loops contain 22 such sequences, in FORMANT and the PHYS
modal, membrane and string kernels. Narrowing them is exact only under a proven bound:
[#624](https://github.com/kmplngj/Felucca/issues/624).

**64/32 division is native.** `r1_r0 = r3_r2 / r7 (u)` divides a 64-bit dividend by a
32-bit divisor without a helper. At `-O2`, the PHYS exciter's
`((uint64_t)1 << 47) / dust_thr` or `v /= cut` becomes `__udivdi3`, which Felucca does
not link.

## Guide recommendations and owners

| Recommendation | Felucca disposition |
| --- | --- |
| CMake/Ninja instead of a custom build script | Not adopted. The single-TU build, `minsize` pass, profile contracts and resource guards live in `tools/build.py` |
| `-mcpu=r3 -mfprev1`, FM1 Open's backend switches | Measured above; only rep-memop remains a candidate |
| Keep 64-bit values out of variables; narrow intermediates | #624, exact sites only |
| Multiply by a precomputed reciprocal | #623 for constant divisors; #7, #164 and #109 for earlier cases |
| `-O2` hot code, `-Os`/`-Oz` for the rest | #625; Felucca's current split is `-Os` plus `minsize` |
| Update slow values every 32–128 frames, interpolate | Already the control-block design (32 samples); per-engine caches #86, #89, #179 and #180 |
| Hot code in SRAM, runtime engine loading | #459 and #6; capacity and overlay notes added to #459 |
| Both cores, 360 MHz, raised voltage | CPU2 worker integrated and OFF by default. The stock bootloader already runs 360 MHz, checked by [#618](https://github.com/kmplngj/Felucca/issues/618); supply changes are [#475](https://github.com/kmplngj/Felucca/issues/475). FM1 Open's public APP contains no clock or rail code |
| FreeRTOS | Not adopted. The bare-metal interrupt design has bounded audio and scan deadlines |
| Support the SMK-37 | [#192](https://github.com/kmplngj/Felucca/issues/192), after #293 |

## Limits

Only the standard profile with default flags was built. The Linux toolchain release
differs from FM1 Open's Windows 2.5.3. The wide-multiply and constant-divide counts come
from listing heuristics, and each site must be confirmed in disassembly. Host goldens use
the host compiler, so they cannot show target code-generation equivalence. No cycle cost,
deadline headroom or sound result is claimed. README assessment: unchanged, because
planning and static evidence do not change the fork's capabilities. Changelog
assessment: no entry, because no behavior changed.
