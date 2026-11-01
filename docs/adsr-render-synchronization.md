<!-- SPDX-License-Identifier: GPL-3.0-only -->
# ADSR render synchronization

Ordinary ADSR pages now plot one coherent parameter snapshot and save the redraw
signature for those same values. This prevents a stale curve when asynchronous
parameter changes occur around a display transfer. FM-1 qualification and the final
capacity decision remain pending; this is a narrowly scoped correctness fix under
[#95](https://github.com/kmplngj/Felucca/issues/95), not completion of its broader
unrelated-parameter redraw work.

## Cause and scope

Previously the UI hashed live parameters before `cv_begin` waited for the preceding
LCD DMA transfer, then plotted live ADSR values afterward. A change from A to B in
that interval could draw B while saving a signature for A. Returning to A could
then hit the cached signature and leave B displayed.

After the existing DMA synchronization, the UI briefly saves/restores the interrupt
configuration while reading four int16 values. The same local 8-byte vector feeds
the curve and a generic four-ID substitution in the original conservative
all-parameter signature. A later change after rasterization is detected on the next
UI frame; an already completed raster is not repainted instantaneously.

The non-NULL snapshot contract explicitly excludes HOME and disjoint graph-only
signature branches so the compiler does not duplicate SONG/scope work for ADSR.
The NULL wrapper keeps their behavior. Common hash order and engine/scope suffixes
remain intact, without assuming all future ADSR pages have the same scope or
adjacent parameter IDs.

Scope is native ENV and, only in `FELUCCA_FM4=1` builds, OP1 ENV through OP4 ENV.
HOME's envelope, FM6's distinct OP ENV graph, other graphs, panel controls, stored
values/aliases and wire IDs retain their existing behavior. Editor force requests
and unrelated-parameter redraws remain conservative. There is no persistent cache,
new framebuffer, transport change or editor-force audit. Existing finite signature
collision semantics are unchanged.

## Focused checks

After the normal [asset build](../BUILDING.md#build):

```sh
uv run --locked --group build python tests/adsr_sync_test.py --negative-controls
uv run --locked --group build python tests/adsr_sync_test.py --fm4 --out build/adsr-sync-fm4
```

Both modes are required units in `tests/run_tests.sh`. They compile actual UI,
MIDI/editor and LCD driver sources against a delayed-DMA wire model, compare the
completed graph with a forced full render and validate windows/source lifetime.
Normal mode also requires causal failures for the old signature, a live post-raster
hash, a live renderer, and a DMA reference/copy mismatch. The driver refuses Python `-O`
or `PYTHONOPTIMIZE`, which would disable required assertions.

The independent pre-change source renderer was also forced to draw and compared
with the candidate at 62 shared full-LCD checkpoints: all 7,142,400 RGB565 bytes
matched. Current focused positives cover 67 normal and 87 FM4 checkpoints, including
all five ordinary ADSR pages. The original unforced renderer fails the scheduled
ABA follow-up; that expected baseline defect is kept separate from forced-render
equality. These counts describe the bounded fixture, not exhaustive UI coverage.

Strict positive ASan/UBSan checks can be run without the general DSP exclusions:

```sh
CC='clang -g -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer' \
  uv run --locked --group build python tests/adsr_sync_test.py --out build/adsr-sync-sanitize
CC='clang -g -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer' \
  uv run --locked --group build python tests/adsr_sync_test.py --fm4 --out build/adsr-sync-sanitize-fm4
```

Both passed with Apple Clang 21.0.0, with no sanitizer exclusions or runtime
suppressions. These positive checks do not promise that every firmware path is free
of undefined behavior. Tests inject changes after DMA synchronization, after the
snapshot/before plotting, and after rasterization/before publication. Direct
fixtures complement real panel, queued CC, ED_SET, lock and MOD handler paths.
Hardware incidence and device deadlines are not inferred from host injections.

## Controlled target cost and remaining gates

The controlled pre-commit comparison uses native base
`2579e55791df0ccc2d72f35177526248d75cbc79`, Engines
`9630426f5c4a34a209ca851356fbe8ba3c4c6d19` and actual JieLi Clang 4.0.1. Native/build
inputs equal pristine `29ad24fdc33617b623c8506cc1283c0208d76cce`; each profile reuses
its exact archived generated data and identity. Thus these are matched **app-only
measurements**, not installable final-revision packages. Final committed identity,
full tests/browser and fresh package/resource reports remain separate gates.

| Profile | App bytes before → after | Delta | Remaining app capacity |
| --- | ---: | ---: | ---: |
| standard | 496,316 → 497,040 | +724 | 84,524 |
| CPU2=0 | 492,768 → 493,496 | +728 | 88,068 |
| no selective minsize | 515,824 → 516,424 | +600 | 65,140 |
| MACRO | 580,368 → 581,088 | +720 | **476** |

All four build/resource guards and unchanged static target budgets passed. RAM,
POOL, RAMTEXT, NOINIT, UI structure size and stack reservations are unchanged.
`draw_graph`'s actual own frame grows 2,016→2,024 bytes in selective builds,
1,992→2,008 without minsize. The existing ADSR primitive grows 92→96 bytes of
own frame in selective builds (unchanged 92 without minsize); HOME has no new
wrapper nesting. ISR function sizes/instruction counts/own frames are unchanged.
These are static allocations/frames, not live watermarks or FM-1 timing.

A needed ordinary ADSR draw performs an extra conservative hash/four-ID scan in the
main loop. It still submits 48,000 payload plus 11 command/address bytes for the
240×100 graph. This fix does **not** claim fewer redraws or CPU savings. The first
generic implementation duplicated disjoint graph branches and failed MACRO's link;
the explicit snapshot contract removes that duplication. The retained comparison
still spends 720 of MACRO's prior 1,196 spare bytes. **476 bytes is a pending capacity
and retention gate, not general approval for main or default builds.**

Real FM-1 checks remain pending: current ENV/legacy FM4 curves during panel and
MIDI edits, return-to-value and force/overlay/wake restoration, loaded audio/panel
response, USB audio 44.1/48 kHz and applicable USB/TRS MIDI, audio lateness/shedding,
scan/stream errors and nested-interrupt stack. Begin with the default second-core
preference OFF; optional ON (BETA) requires its own recorded restart/workload and
must not clear a retained worker exclusion merely to qualify this UI change.
See [second-core limits](fork-features.md#optional-second-core),
[diagnostic workload rules](diagnostics.md) and the final PR's separate user procedure.
