<!-- SPDX-License-Identifier: GPL-3.0-only -->
# MIDI CC scaling without a divide (issue #164): host preparation

Status: candidate proven on the host; keep/reject needs the JieLi toolchain. Production code is unchanged.

## The expression

`midi_cc_set()` (`firmware/src/midi_control.c`) computes `v = min + (value * (max - min) + 63) / 127` with `value`
0..127 and `d = param_desc_of(eng_idx(t->eng_req), id)`. It is reached from the standard map (`MIDI_CC_MAP`, plus
CC74 / CC71 through `MIDI_CC_ENG`) and from every learned target (`ml_id() < P_COUNT`), so the domain is every
engine's `edit[]` entry and every common `TP[]` entry. `param_desc_of` is used, not the engine `desc` hook, so the
ranges are the static table ranges.

## Proven bounds (tests/cc_scale_test.c, real descriptor tables)

Host check against `main` at `0d44c20`, 14 engines x 111 parameter ids = 1554 descriptors.

| Quantity | Value |
| --- | --- |
| minimum / maximum over all descriptors | -64 / 127 |
| span `max - min` | 0..127 |
| numerator `value * span + 63` | 63..16192 (max 127 * 127 + 63) |
| descriptors with `max <= min` | 3 (constant or degenerate) |

The signed minimum is added after the division. For `max > min` the numerator is never negative, so C's
truncation toward zero never matters. For `max <= min` the current code evaluates the (possibly negative) division
and then returns without using it, so the candidate keeps the `d->max <= d->min` early return ahead of the
computation; the test models that and compares the observable result, including the "unchanged value returns
early" case.

## Candidate

```c
uint32_t x = value * (uint32_t)(max - min) + 63u;    /* 63 .. 32448 for span <= 255 */
v = min + (int32_t)((x * 33027u) >> 22);              /* 33027 = ceil(2^22 / 127) */
```

Why it is exact: `127 * 33027 - 2^22 = 125`, and `125 * 32448 = 4,056,000 < 2^22 = 4,194,304`, which is the
standard sufficient condition for `floor(x * M / 2^k) == floor(x / 127)` on `0 <= x <= 32448`. The product is at
most 32448 * 33027 (about 1.07e9), under 2^32 (compile-time assertion in the test), so a 32-bit multiply and
shift suffice. The proven domain is span <= 255 (twice the reachable maximum of 127). A descriptor with a wider range
fails the test's first check and the constants must be re-derived (span up to 1000 needs shift 24, multiplier
132105 and a 64-bit product).

## Host evidence

`tests/cc_scale_test.c`, wired into `tests/run_tests.sh` before the `build/felucca.fwsc` gate, built plain and with
`-fsanitize=undefined -fno-sanitize-recover=undefined`:

- every reachable descriptor x value 0..127 x changed/unchanged current value: candidate == reference;
- every span 1..255 x value 0..127 x minima -300..300: candidate == reference and inside `[min, max]`;
- `x * 33027 >> 22 == x / 127` for every x in 0..32448; CC 0 gives `min` and CC 127 gives `max` for every span.

Run (after `python3 -c "import sys; sys.path.insert(0,'tools'); import build; build.generate()"`):

```sh
mkdir -p build/host
cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/host/cc_scale_test tests/cc_scale_test.c -lm && build/host/cc_scale_test
```

## Remaining target steps (toolchain / hardware owner)

Per [docs/performance.md](../performance.md), change one cause and compare with an unchanged baseline:

1. Build the unchanged revision; record the pi32v2 disassembly of `midi_cc_set`: whether it calls a divide helper
   (for example `__divsi3`), its size, and whether `midi_cc_map` / `midi_learned` inline it.
2. Replace only the expression in `midi_cc_set` with the candidate (early return first), rebuild with identical
   flags and compare the disassembly: no helper call, instruction count of the function.
3. Run `tests/target_budget.py build/felucca.dis tests/target_budget.txt`; record the app size in bytes and
   RAM/stack before and after. If other callers still use the divide helper it stays linked and the gain is cycles only.
4. Time a dense CC stream (several controllers sweeping learned parameters on all four tracks) on a real FM-1 and
   compare the worst-case time per CC. CC handling is main-loop work, so the gain is main-loop headroom, not
   audio-interrupt time.
5. Keep if the divide disappears with no size growth beyond noise and the full suite passes with golden files
   unchanged; reject (leave the divide) if the compiler already strength-reduces division by 127 or size grows.
