<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Firmware modules and their boundaries

This page documents how the firmware's source files depend on each other today, the dependency
direction new work should follow, and what separate compilation
([#454](https://github.com/kmplngj/Felucca/issues/454)) requires. It also records the separate-compilation pilot
for `sound.c` and its measurements. The owner decided on **header boundaries**: modules stay in the one
translation unit, with a public header and a port header, and a source check enforces the boundary (section 4). The
pilot's separate compilation was measured and is not adopted.

Source facts refer to `main` at [`13343d5`](https://github.com/kmplngj/Felucca/tree/13343d5cb288913954f9118e347a92d17005260a)
plus this pilot. Cross-file counts come from a source scan that follows `felucca.c`'s
include order (including the generated `engine_includes.inc`). That scan matches top-level
definitions by regular expression, not with a parser, so treat the counts as approximate. The pilot's
interface lists were checked by compiling the module.

## 1. How the firmware is compiled

- **Target:** [felucca.c](../firmware/src/felucca.c) defines the build options, includes the header-only HAL
  and generated tables, and then includes about 80 C files in a fixed order (directly, or through
  `engines.c`, `seq.c`, `ui.c`, `project.c`, `editor.c` and the generated `engine_includes.inc`). Every file
  can use any `static` function, macro or object defined in a file included before it. Some files also use
  functions defined after them, through forward declarations (section 3).
  [tools/build.py](../tools/build.py) emits unoptimized IR for that unit.
  [tools/size_fns.py](../tools/size_fns.py) marks main-loop functions `minsize`, keeps everything
  an interrupt reaches at `-Os`, and the IR is compiled and linked with the assembly objects.
- **Host and emulator:** [tests/hostsim.c](../tests/hostsim.c) includes the DSP, sequencer and
  sound-install files against stubs. `tests/ui_test.c` adds the UI, presets and projects, and
  [web/emu/felucca_web.c](../web/emu/felucca_web.c) includes `hostsim.c`. Each test program is one unit.
- **Collections:** the MIT [Felucca-Engines](https://github.com/kmplngj/Felucca-Engines) submodule
  (`firmware/engines`, pinned at `9630426f`) supplies `felucca_engine.h` (portable contract v1, #340), `dsp.c`
  and ANALOG, LOFI, TRIO, WHEEL and NOISE. Those files are compiled inside the GPL unit through
  `engines.c` and `engine_includes.inc`. The GPL collection and `firmware/engines-gpl/` pin are still
  pending [#360](https://github.com/kmplngj/Felucca/issues/360) and are not a build input.

## 2. Dependency direction

The table lists the layers in the order `felucca.c` includes them. The rule for new code: **a
layer may call or read only the layers above it in this table.** A lower layer reaches a higher one
through a request flag or queue that the higher one polls, such as `panic_req`, `shed_req` or the
SysEx frames. It can also declare a port that the higher layer implements, as `sound_port.h` does
(section 4).

| Layer | Files (nested includes in brackets) | Owns |
| --- | --- | --- |
| Platform | `hal/*.h`, `libc.c`, generated `felucca_tables.h`, `core.h` | Registers and interrupts; `memcpy`/`memset`; tables; the core types; **the unit's shared state `trk[]`, `song`, `fm1_ms`, `bootguard`** (defined in `core.h`) |
| Display primitives | `lcd.c`, `gfx.c` | LCD transfer and the drawing primitives (UI-only, but included first) |
| Synthesis | `engines.c` [`dsp.c`, `eng_*.c`, `fm6_core.c`, `drum_voice.c`, `phys_*.c`, `fm4_convert.c`], `params.c`, `mod.c`, `voice.c`, `slicer.c`, `fx.c` [`perform.c`, `click.c`] | Engine table/IDs/arena, parameter descriptors (`TP`), modulation, voices, inserts, mixer, buses, FX layer. Audio-interrupt code |
| I/O transport | `usb.c`, `midi_uart.c` | USB descriptors, MIDI/CDC/UAC endpoints, SysEx framing, TRS MIDI parser and queues |
| Sequencing | `song_chain.c`, `seq.c` [`chord.c`, `motion.c`, `midi_control.c`, `midi_clock.c`] | Steps, clock, chain, live input, automation, MIDI routing; `panic_req` |
| Application services: sound | `sound.c` (header boundary in the single unit; `sound.h`, `sound_port.c`) | Sound install (#298): the publication of engine, preset and values into a track |
| Audio entry | `audio.c` | The I2S interrupt handler and block scheduling |
| UI | `panel.c`, `ui.c` [`favorites.c`, `category.c`, `ui_slice.c`, `ui_events.c`, `midi_learn.c`], `menu_items.c`, `icons.c`, `ui_graph.c` [`ui_fm6op.c`], `ui_draw.c` [`ui_help.c`], `ui_menu.c`, `ui_knob.c`, `ui_input.c` [`ui_name.c`], `ui_layer.c` [`ui_tools.c`] | The `ui` state, pages, layers, knob policy (#295) and drawing |
| Storage | `storage_hw.c`, `storage.c` (`FELUCCA_FLASH`) | Flash driver, sectors and records |
| Application services: persistence | `upreset.c` [`category.c`, `up_fm6.c`, `fm6_vbank.c`], `project.c` [`settings_persist.c`, `slice_store.c`] | User presets, projects, settings (#296), slice slots |
| Editor transport | `ota.c`, `ota_hw.c`, `editor.c` [`editor_preferences.c`, `editor_backup.c`, `editor_fm6.c`, `editor_menu.c`, `editor_learn.c`, `editor_palette.c`] (`FELUCCA_OTA`) | Update entry, editor SysEx protocol and backup |
| System | `console.c`, `master.c`, `main.c` (`mul64_repro.c`: diagnostic builds) | Serial console, MASTER pot, boot and main loop |

The intended direction differs from the include order in one important respect. **Persistence is an
application service below the UI**, but today it is included after the UI and the UI reaches it through
forward declarations. In a separately compiled firmware, persistence should depend on synthesis,
sequencing and storage only, and the UI and the editor should call it through its header.

## 3. Cross-module accesses that separate compilation must resolve

Separate compilation turns every name a file takes from another file into an interface decision. The scan
found these kinds of implicit access:

**Shared state defined in headers.** `core.h` defines `trk[]` and `song` (used by about 37 and 31 files),
`fm1_ms` (16 files) and the external `bootguard`. The UI's `ui` struct (`ui.c`) is read outside the UI by
`main.c`, `project.c`, `upreset.c` and every `editor_*.c`. The HAL headers also hold state:
`fm1_irq.h` has the `.noinit` crash record and `isr_assert.h` its misuse counter (target) or interrupt depth
(host). A second unit that includes these headers gets **a second, private copy** of every `static`
object it uses. That error is silent and has no compile-time diagnostic. The pilot prevents it with
`FELUCCA_OWN_UNIT`: in a unit compiled with that macro, `core.h` omits its state, so the names do not
compile. `build.py` then rejects any `.data`, `.bss`, `.pool`, `.noinit` or `.ram_text` byte in a separate
module's object.

**Static tables in generated headers.** `felucca_tables.h`, `felucca_samples.h` (126 KB of ADPCM),
`felucca_fm6.h` and `ENGINE_META` in `core.h` are `static const`. Including one in two units is free only
while the second unit references nothing from it. Otherwise the second unit gets its own copy
of the table in flash. Such data needs one owning unit and an accessor. The pilot's `sound_port_preset_alias`
and `sound_port_fm6_unpack` are accessors of this kind.

**Back edges (cycles).** These are forward declarations of functions that a later file defines. All
of them become header dependencies, and the ones that point down the table become cycles to break:

| From → to | Functions | Resolution direction |
| --- | --- | --- |
| UI → persistence (`ui.c`, `ui_name.c`, `ui_input.c`, `ui_draw.c`, `ui_graph.c`, `panel.c`, `midi_learn.c`, `ui_menu.c`, `ui_layer.c`) | `project_*` (10), `up_*` (10), `settings_save`, `chain_prepare` | Persistence below the UI, with public headers |
| UI-internal (`ui.c` → `ui_input.c`/`ui_layer.c`/`ui_draw.c`/`ui_graph.c`, `ui_draw.c` → `ui_input.c`/`ui_menu.c`, `ui_input.c` → `ui_layer.c` (17), `ui_knob.c` → `ui_input.c` (`accel`, `lock_held`)) | Layer, name, menu and confirm hooks | One UI component until `ui` and its gestures have an owner (#295 follow-ups) |
| Sequencing → sequencing (`song_chain.c` → `seq.c`) | `seq_stop`, `seq_release`, `step_samples`, `motion_restore` | Merge or give `song_chain` a port |
| Synthesis → sequencing (`fx.c` → `seq.c`) | `events_block` | Audio-side event hook declared by synthesis |
| Synthesis-internal (`voice.c` → `fx.c`) | `beat_samples`, `div_samples` | Tempo helpers into a lower header |
| I/O → editor transport (`usb.c`, `ota.c` → `ota_hw.c`) | `ota_idle`, `ota_now_ms`, `ota_erase`, `ota_prog`, ... | Already a HAL-style port; keep as a header |
| Persistence → UI (`upreset.c` → `ui.c`, `project.c` → `ui_layer.c`) | `track_cat`, `now` | Move to persistence or a lower helper |

**Code that interrupts reach.** `size_fns.isr_reach` computes the interrupt closure inside one unit. A
function in another unit is only a declaration there, so the closure could not see past it. The pilot
makes `size_fns.py` **fail when interrupt-reachable code calls a function defined outside the unit**
(LLVM intrinsics excepted). A module can therefore be separated only if no interrupt reaches it.
In the pilot, that rules out the synthesis layer, `audio.c`, the sequencer's step path and everything in
`.ram_text`.

**Configuration.** Every unit must see the same options. `core.h` sets its own defaults for the macros that
shape its types (`FELUCCA_CPU2`, `FELUCCA_SLICE`, `FELUCCA_FM4`, the profile). `build.py` passes the same `-D`
flags to every unit. The options that only `felucca.c` defines (`FELUCCA_FLASH`, `_OTA`, `_CDC`, `_UAC`,
`_UART`) do not affect any type the pilot module sees. A module that depends on them needs a shared
configuration header first.

**Host builds.** The host tests and the emulator are single units built from many compile lines in
`tests/run_tests.sh`, Python harnesses and `web/emu/build.sh`. A module therefore stays textually included there
(`hostsim.c` includes `sound_port.c` and `sound.c`). A dedicated host program links the module as its own
unit (section 4). Converting every host build is part of each later step's cost.

## 4. Pilot: `sound.c` behind header boundaries

**Final state (owner decision: "Header boundaries").** `sound.c` is back in `felucca.c`'s single translation unit
(after `sound_port.c`, before `ui.c`). The source check adds no runtime checking; the port's compiler output must
still be compared at each integration. The original zero-byte measurement below applies to its recorded baseline.

- [`sound.h`](../firmware/src/sound.h) is the documented interface and
  [`sound_port.h`](../firmware/src/sound_port.h) lists what `sound.c` needs of the rest of the firmware. In the
  one unit both are `static` / `static inline` (`SND_API`, `SND_PORT`), so the compiler can inline across the boundary.
- [`tests/module_boundary_test.py`](../tests/module_boundary_test.py), run by `tests/run_tests.sh`, enforces the
  boundary at the source level: `sound.c` may include only `sound.h`, `sound_port.h`, `core.h`,
  `felucca_tables.h` and `stdint.h` / `string.h`, and of the firmware's functions and objects it may name only what
  the two headers declare. A function or object defined by another file (including `core.h`'s `trk`, `song`,
  `swing_step_len`, and macros that expand to them such as `TSEL`) fails the check. It ships with fixtures,
  mutations of `sound.c` that must be rejected.
  The inventory includes every declarator in a comma-separated declaration and the actual generated `.h`/`.inc`
  files, so generated FM6/sample tables are private dependencies too. The check runs in the existing
  asset-dependent `sound_install` unit. `build.generate()` seals the headers in `build/gen/generated-inputs.json`
  for both host-only preparation and target builds; no target binary, SDK or resource report is required.
  Missing headers/manifest or a generated-file/producer-input hash mismatch fails explicitly. The manifest
  reuses the existing input collector for tools, assets, profiles, engine sources and dependency locks; stale output is not
  accepted as an empty inventory. This source heuristic follows the repository's file-scope layout conventions;
  it is not a complete C parser.
- The mechanism for building a module as its own unit stays, dormant and tested: `build.py` `SEPARATE` is empty
  (`("sound",)` turns it on and makes `felucca.c` skip `sound.c` through `SOUND_SEPARATE`); `FELUCCA_OWN_UNIT`
  (the `core.h` state guards), `separate_check`, `size_fns.py --module` and the ISR-reachability check cost
  nothing in the default build. The no-minsize build also checks IR with the same main-unit configuration as its
  object, including `SOUND_SEPARATE` when the dormant pilot is enabled. `tests/run_tests.sh` still compiles
  `sound.c` as its own object (no data or bss) and
  runs `tests/sound_install_test.c` against it.
- The next module follows the same pattern: a public header, a port header for its needs, an entry in the boundary
  test.

The rest of this section keeps the pilot's history: the candidate choice, the separate-compilation shape and its
measurements, which is why separate compilation was not adopted.

### Candidate choice

**Choice.** The candidates had these implicit dependencies before the pilot:

| Candidate | Outbound (names, owners) | Inbound (names, consumers) | State | Interrupt-reachable |
| --- | --- | --- | --- | --- |
| `sound.c` (#298, #477) | 18 names from 5 owners: `TP`; `eng_of`, `eng_is`; `trk_index`, `panic_req`; `fm6_unpack`, `fm6_set_patch`, `fm6_adopt`, `fm6_track_loaded`, `fm6_own_ok`, `fm6_slot`, `ENGI_FM6`, `FP_SIZE`; the generated `FM6_FACTORY`, `FM6_NFACTORY`, `SMP_PRESET_TABLE`, `SMP_NSETS`, `SMP_SET_ORIG`. Also the HAL interrupt guard, `FM1_ASSERT_THREAD` and `memcpy` | 7 names (6 functions and the `SND_*` flags) from `ui.c`, `upreset.c`, `project.c` | none | no |
| `ui_knob.c` (#295, #485) | about 26 names from 7 owners, including the mutable `ui`, `mom` and `song`, and the UI-internal `accel`, `lock_held`, `cur_page`, `page_desc` | 8 functions and the `knob_target_t` type, from `ui_input.c`, `ui_layer.c` | `mom` (owned by `ui.c`) | no |
| `master.c` | `song`, `master_of_pot` | `master_boot`, `master_poll` | `master_knob` | no |

`master.c` has fewer dependencies, but it is two functions with one write. Separating it would measure
almost nothing and would not test a real interface. `sound.c` has the fewest dependencies of the
named candidates. It has no state of its own, has a documented public contract (#298), runs only in the main
loop, and uses all three of the hard cases: data owned by another unit (`TP`, the FM6 and sample
tables), an interrupt guard, and HAL/assertion state. `ui_knob.c` depends on most of the UI's private state
and would only move the UI's own cycle into headers.

**Shape of the separate-compilation pilot** (measured, not adopted; the headers and `sound_port.c` are shared with the final state):

- [`sound.h`](../firmware/src/sound.h) is the public interface: `param_kept`, `preset_orig`, `sound_defaults`,
  `sound_preset_values`, `sound_install`, `sound_load_factory` and `SND_*`. The consumers' source is
  unchanged. They see the same names through `sound.h`, which `felucca.c` includes where `sound.c` was.
- [`sound_port.h`](../firmware/src/sound_port.h) lists the 14 operations `sound.c` requires.
  [`sound_port.c`](../firmware/src/sound_port.c) implements them inside `felucca.c`'s unit as thin wrappers
  around the owners' `static` functions and state. The owners stay `static`, so their other callers
  (including the audio interrupt) are compiled the same way. Only the wrappers are external.
- The interrupt guard (`sound_port_lock`/`unlock`) and `FM1_ASSERT_THREAD` (`sound_port_assert_thread`) go
  through the port because their state (`isr_assert.h`, the host's interrupt model) is per unit.
- `build.py` compiles `sound.c` with `-DFELUCCA_OWN_UNIT=1` through the same IR, `size_fns.py --module`
  (minsize) and `-Os` pipeline, and links `sound.o` after `felucca.o`. `separate_check` rejects a module
  object with state. `size_fns.py` rejects interrupt code calling another unit.
- Host: `hostsim.c` includes `sound_port.c` and `sound.c` in its unit, so every host test, the emulator
  and the replay harness are unchanged. `tests/run_tests.sh` also compiles `sound.c` as its own host
  object, checks that it holds no data or bss, and runs `tests/sound_install_test.c` linked against it
  (`SOUND_SEPARATE`).

**Measurements of the pilot.** All figures are target builds with JieLi Clang 4.0.1, the standard profile and
the M8Stealth font. Each pair has the same flags and the same build-identity length. Baseline is `main`
`13343d5`; pilot is this change.

| Build | App image | .text | RAM .data+.bss | POOL | NOINIT | .ram_text |
| --- | --- | --- | --- | --- | --- | --- |
| default | 486,472 → 486,896 B (**+424**) | +424 | 62,056 (=) | 336,440 (=) | 15,576 (=) | 916 insns, no calls (=) |
| `FELUCCA_CPU2=0` | 481,420 → 481,848 B (+428) | +428 | 55,460 (=) | = | 15,564 (=) | = |
| `FELUCCA_SIZE=0` (no minsize) | 501,304 → 500,816 B (**−488**) | −488 | 62,072 (=) | = | = | = |
| `FELUCCA_ISR_ASSERT=1` | 485,460 → 485,976 B (+516) | +516 | 62,088 (=) | = | = | = |

Breakdown of the default +424 B, from per-symbol sizes:

- 14 port wrappers: +244 B. `sound_port_fm6_track_loaded` is 66 B because `fm6_track_loaded`
  is inlined into it.
- `sound_load_factory` is now out of line: +128 B. Its former caller `factory_load` shrank by 104 B.
- `sound_install` is smaller (294 → 200 B) because its FM6, guard and panic code moved into calls.
  `preset_orig` is now a 4-byte tail call.
- `FX_DEF` was duplicated (+4 B) at that measurement. Since #299 it has one definition in `core.h`, which
  `sound.c` reads through `sound_port_fx_default()`.
- Inlining changed in unrelated main-loop code: `ui_input` +354 B, `ui_draw_page` −38 B and smaller changes.
- Four interrupt functions grew by +46 B (below).

Inbound calls were already out of line in the baseline (27 call sites to `param_kept`, `preset_orig`,
`sound_defaults`, `sound_install` and `sound_preset_values`). Only `sound_load_factory`'s single call site
lost inlining. Outbound, `sound_install` now makes up to 9 calls through the port where the
baseline had inlined code. That code runs only in the main loop, once per sound load.

**Interrupt-reachable code in the pilot.** No interrupt reaches the module or the port; the build fails if one does.
The pilot still changes code that interrupts reach. `tests/target_budget.py` (no `BUDGET_UPDATE`)
reports for the default build:

| Function | Baseline | Pilot |
| --- | --- | --- |
| `perf_block` | 908 insns, 847 in loops, cost 847 | 917 insns, 854 in loops, cost 854 (+0.8 %; stored budget 814, within its +10 %) |
| `perf_begin` | 230 insns, cost 28 | 231 insns, cost 28 |
| `perf_pre` | 37 insns, cost 26 | 38 insns, cost 26 |
| `perf_mod_depth` (not budgeted) | 46 B | 50 B |

The cause is data layout, not calls or inlining across the boundary. LLVM's global merge places the small
`.bss` variables in `.L_MergedGlobals` groups. The port now accesses `panic_req`, `fm6_own_ok` and `fm6_slot`
from different functions, which changes their order in that group. `perf_k`/`perf_act` moved 4 B
further from the group's base, past the 255-byte displacement of a `b[rX+imm]` load, so each access
needs one more instruction to load the offset. In 44 other interrupt-reachable functions only the
displacements changed. With `FELUCCA_CPU2=0`, `perf_buf_done`, `perf_buf_start` and `sl_enter` gain one
instruction each and no budgeted function changes. `FELUCCA_SIZE=0` has no instruction-count change.
`FELUCCA_ISR_ASSERT=1` behaves like the default and also adds one instruction to `motion_put`.
Removing either the `panic_req` or the FM6 slot wrapper alone did not restore the layout. This sensitivity is
not specific to separate compilation: any change in which globals the main-loop code uses together can move
an audio-path variable across that displacement.

**LTO.** JieLi's toolchain includes `llvm-link`, `LLVMgold.so` and `lto-wrapper`. The vendor SDK links
with `-flto` and `lto-wrapper`. Both IR-linking routes work mechanically with `build.py`'s pieces but
are **not qualified**:

- Linking `felucca.ll` and `sound.ll` with `llvm-link`, then `size_fns.py` and `-Os`, removes the boundary
  cost. App `.text` is 192 B below the baseline, or 588 B below when the non-exported functions are
  internalized. However, `llvm-link` alone also reorders the module's globals, even for `felucca.ll` on
  its own. `.data` grows by 16 B, `.bss` shrinks by 48 B, and interrupt code changes: static cost of `mix_part`
  2835 → 3582, `fm1_timer5_irq` 33455 → 33755, `trio_render` +56 instructions.
- Gold-plugin LTO (`-flto` objects, `ld -plugin LLVMgold.so`) links, and its `.text` is 672 B below the
  baseline. It fails `tests/target_budget.py`: `trio_pass` is 36 % over budget, and it changes most render
  functions and both interrupt handlers.

Neither build was run on an FM-1, and neither went through `build.py`'s package checks. Qualifying LTO
means re-baselining the interrupt budgets and measuring deadlines on hardware. Neither step is cheap.

## 5. Next step

Final state: **header boundaries plus a source check**. In the historical comparison against `main` `b4b7a45`, the target app image, its
`.text`, `.data`, `.ram_text` and `.c1_text` sections and the `tests/target_budget.py` output are identical (the default
build's 487,024 B and `FELUCCA_SIZE=0`'s 503,536 B; the only differing bytes are the commit id in the build
identity), including `perf_block` 908 insns / cost 847, `perf_begin` 230 / 28 and `perf_pre` 37 / 26. Getting there took
care: a first port with one combined FM6 factory function cost +8 B in `sound_install` by register allocation alone;
splitting it into `sound_port_fm6_slot_ok` and `sound_port_fm6_unpack`, as the original code's two steps, removed it.

The separate-compilation pilot cost +424 B of flash and no RAM. It changed interrupt code by a few instructions, through
data layout only. Making the boundary explicit (two headers, a port, and checks against duplicated state
and cross-unit interrupt calls) found two hazards that would otherwise have been silent: per-unit copies of
`core.h`/HAL state, and interrupt reachability hidden across units. On these numbers:

- **Adopted:** stop at **documented header boundaries**. For the main-loop
  modules (application services, UI, persistence, editor), add public headers and port headers inside the
  single unit, so dependencies are visible and reviewed. Break the cycles in section 3 at their owners,
  starting with persistence below the UI. `tests/module_boundary_test.py` is that checker ("no name
  from another module except through its header"), extended one module at a time. It adds no runtime check;
  measure the target output after integration.
- Separate one more module only when the layering work already produces its header, and only for
  main-loop code, measuring each step as here. Each step costs roughly the size of its port and
  can move interrupt code through data layout.
- LTO is **not adopted**: it would change the whole audio path and needs its own qualification project.

### Current-main integration (2026-10-23)

Fresh comparisons against clean main `758f228878dd99e217881231c04a69f7957e2118` use the same JieLi Clang 4.0.1,
pinned AC79 SDK, standard profile, M8Stealth and clean eight-character build identities. `SEPARATE` remains empty;
LTO remains disabled. These replace the historical zero-byte claim for current integration:

| Variant | Main app | Integrated app | Delta | RAM data+BSS (both) |
| --- | ---: | ---: | ---: | ---: |
| Default, selective minsize | 491,876 B | 491,892 B | +16 B | 62,152 B |
| `FELUCCA_CPU2=0` | 488,164 B | 488,180 B | +16 B | 55,556 B |
| `FELUCCA_SIZE=0` | 510,680 B | 510,704 B | +24 B | 62,136 B |

POOL is unchanged at 336,440 B; NOINIT is 15,576 B (15,564 B with CPU2 off); RAM text including core 1 is
3,152 B (2,924 B with CPU2 off). Linker stack reservations and the 610,134 B installable package size are unchanged.
Complete static target-budget output is identical within each pair. In the default build the sole sized-symbol
change is `sound_install` (300 → 316 B); its explicit stack adjustment changes from 172 to 176 B. The boundary
changes main-loop register allocation even when wrappers inline. Static reservations and instruction estimates
do not establish live stack watermarks, execution time or audio-deadline margin. FM-1 sound-switch, persistence,
loaded USB/MIDI and timing qualification remains pending; current validation and routes belong in PR #491.

Decided by the owner: header boundaries, not separate compilation (open question 1). Still open: whether to
stabilize the audio path's variables against global-merge reordering (the `perf_block` layout effect above) as a
separate issue; it affects any change, not only separate compilation.
