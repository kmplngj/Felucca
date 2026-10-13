<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Extending Felucca: engines, effects and platform contracts

This guide lists what a change must touch and preserve when it adds a sound engine, an effect
or anything that crosses the hardware, interrupt, flash or storage boundaries. It points at the
code and documents that hold the rules; it does not repeat them. When this page and the source
disagree, the source wins (and this page needs a fix). Process and evidence rules are in
[AGENTS.md](../AGENTS.md), build and test setup in [BUILDING.md](../BUILDING.md), measurement
procedure in [performance.md](performance.md), licensing in [LICENSING.md](../LICENSING.md) and
[CONTRIBUTING.md](../CONTRIBUTING.md).

The firmware is one translation unit: `firmware/src/felucca.c` includes the other C files in
dependency order, and `tests/hostsim.c` (also used by `web/emu/felucca_web.c`) includes the same
sources against simulated hardware. A file that is not included from those places is not built.

## 1. Adding an engine

### 1.1 Stable IDs

- An engine's number is its index in `ENGINES[NENGINES]` (`firmware/src/engines.c`). The
  editor protocol, user presets and projects store it. **Append; never reorder or reuse.**
  `core.h` says why `SLICE` is last: "the other engines keep their numbers" (`NENGINES`).
- A retired engine keeps its slot. Engine 1 (DIGITAL) is the example: `ENG_FM4_GONE` fills
  the slot, `eng_ok()` refuses to select it and old sounds convert to FM6
  (`firmware/src/fm4_convert.c`).
- `NENGINES` is `13 + FELUCCA_SLICE` in `core.h`; a new engine changes that count and the
  `ENGINES[]` table together. A build option that removes an engine (as `FELUCCA_SLICE=0`)
  has to keep every other number unchanged. Today SLICE (13) is last only because it is
  conditional: `&ENG_SLICE` sits under `#if FELUCCA_SLICE` at the end of `ENGINES[]`, so an
  engine simply appended after it would be 14 in a normal build and 13 (SLICE's stored/wire
  number) with `FELUCCA_SLICE=0`. Before appending, give `FELUCCA_SLICE=0` builds a reserved
  placeholder in slot 13 (as `ENG_FM4_GONE` holds slot 1, refused by `eng_ok()`) and make
  `NENGINES` independent of `FELUCCA_SLICE`.
- The numbers are a wire contract: the engine byte table in
  [web/EDITOR_PROTOCOL.md](../web/EDITOR_PROTOCOL.md) lists them and must gain the new row.
- `ENGINE_ORDER[]` (`engines.c`) is only the display order (PRESETS, EDIT layer, editor
  list). It must hold every selectable engine once. `NENG_SHOWN` is the count of those.
- Name `ENGI_*` constants for engines other code refers to by number
  (`core.h`, `eng_fm6.c`); compare engine pointers (`== &ENG_SLICE`) where a page or
  filter depends on one engine (`firmware/src/ui.c page_visible`).

### 1.2 `engine_t` (`firmware/src/core.h`)

An engine is a `static const engine_t ENG_X` defined in `firmware/src/eng_x.c` (see the small
`ENG_NOISE` in `eng_noise.c` for the minimal shape). Fields:

| Field | Meaning |
| --- | --- |
| `name`, `page_title[2]` | Shown in PRESETS and as the titles of EDIT 1 / EDIT 2. |
| `edit[8]` | `param_desc_t` for `P_E0..P_E7`: label, `fmt`, `min`, `max`, `def`, `names` (F_ENUM), `unit`. Range and default are the stored/wire contract (see 1.5). |
| `presets`, `npresets` | `preset_t` factory sounds: `e[8]` values, `env`, `fenv`, `mono`, `fx[]` sends (stored +1, 0 = default), `pat` hint. |
| `knob[4]` | The four parameters on HOME KNOB 1..4. |
| `poly` | Voice cap for POLY/UNISON, 0 = `NVOICE`. |
| `sampled` | Plays recorded material (a position, not a phase): `voice.c` keeps no phases on retrigger, spreads none for UNISON, renders at SUS 0. |
| `keep` | Bit k: voice state `s[k]` survives retriggering a sounding voice (filters). |
| `oneshot` | Hits (DRUM): always POLY, no glide, the amp ends the voice. |
| `note_on(t, v)` | Initialises a voice. |
| `render(t, v, out, n, m)` | Renders `n` samples of one voice into `out`, given the block's `vmod_t`. Runs in the audio ISR. |
| `amp`, `desc`, `block`, `keys` | Optional hooks (0 = none): amplitude instead of the ADSR; a mode-dependent descriptor for EDIT k (same range and default as `edit[k]`); once per block and part before its voices; own key-to-note map. |
| `ownenv`, `done` | The engine's own envelopes are the amplitude (FM6); `done()` ends the voice. |
| `mem` | Bytes of per-part engine memory (see 1.3), 0 = none. |

Per-voice state lives in `voice_t` (`ph[]`, `s[]`); the `render` path is bounded ISR work
(section 3.1). Preserve fixed-point units, rounding, saturation and phase/RNG order (AGENTS.md,
"Stable sound").

### 1.3 Per-part memory (`eng_mem_claim`, `ENG_MEM_FITS`)

- A part plays one engine at a time, so engines with large per-part state share one region per
  part: `eng_mem[NPART]` in `.pool`, `ENG_MEM_PART` bytes each (`engines.c`).
- Declare the state type, point to it through `ENG_MEM(p)`, set `.mem = sizeof(state)`, and
  put `ENG_MEM_FITS("NAME", sizeof(state));` next to the type (`eng_drum.c`, `eng_fm6.c`,
  `eng_grain.c`, `eng_phys.c`, `eng_slice.c` do this). It is a `_Static_assert`.
- If your state is larger than `ENG_MEM_PART`, raising it costs that many bytes **times
  `NPART`** of the pool; `performance.md` ("RAM and stack") says to weigh it. PHYS currently sets
  the size.
- `eng_mem_claim(t)` (called by `voice.c engine_block`) zeroes the first `mem` bytes when
  another engine owned the region (`eng_mem_owner`). Your engine's power-on state must therefore
  be all zeros. State that must survive notes and switches stays outside the region (WHEEL's
  wheels, GRAIN's random numbers).
- An engine with `mem == 0` leaves the region alone: a switch back finds the previous state.

### 1.4 Switching, fades and reset

`voice.c engine_block` implements the switch: the UI writes `eng_req` and the new `P_E0..P_E7`
together (IRQ off); sounding voices fade over `XF_BLOCKS` blocks on the **old** engine rendered
with the saved `pe_old[]` values, then `engine` changes, `eng_mem_claim()` runs, and note-ons
that arrived during the fade (`xp_*`) start on the new engine. Consequences for a new engine:

- It must never read another engine's `P_E*` values (they index its own tables); keep tables
  indexed by `p[P_E0+k]` bounded by the descriptor range.
- It must tolerate a zeroed region and values anywhere inside its descriptor ranges (project and
  preset loads `param_fit()` into range, `params.c`).
- Add switch coverage for state sharing: `tests/union_test.c` (see 1.8).

### 1.5 Parameters

- Track parameters are the `P_*` enum in `core.h`; `P_E0..P_E7` are last, then `P_COUNT`.
  **Common parameters are only added just before `P_E0`.** Stores keep the `np` (`P_COUNT`) they
  were written with and `params_by_count()` (`core.h`) maps them: the first `np - 8` are
  `P_LEVEL..` in order, the last 8 are `P_E0..P_E7`, missing ones take defaults.
- Adding an engine does not add common parameters, but its `edit[]` ranges and defaults are
  now stored contracts: do not change them later without the migration steps in section 4.
- `param_desc_of(engine, id)` (`params.c`) is the descriptor the editor protocol, user presets,
  projects and motion use; the device display goes through `track_desc()` (`params.c`), which also applies
  the optional `desc` hook (labels only: the hook must keep range and default).
- `F_*` formats are in `core.h`; reuse an existing format before adding one (UI, protocol and
  `tests/descdump.c` all switch on it).

### 1.6 Presets, categories, UI and help

- Factory `preset_t` arrays live in the engine's file. `PRESET_CAT[]` (`firmware/src/category.c`)
  needs one letter per preset for the engine's number; `tests/ui_test.c` checks each string
  against `npresets`. `cat_of_engine()` there also names kit-style engines.
- EDIT 1 / EDIT 2 and HOME are generated from `edit[]`, `page_title` and `knob[]`; a plain engine
  needs no new page. Engine-specific pages (`FILTER`, `LANES`, `OPERATOR`, `SLICES`) are gated by
  `page_visible()` in `ui.c`; add a gate there only for a genuinely engine-specific page.
- `eng_abbr()` in `ui_graph.c` holds four-letter abbreviations by engine name; `engine_icon()`
  is in `icons.c`. Add the new name to both.
- Contextual help strings are in `firmware/src/ui_help.c`.
- The UI render test (`tests/ui_render.c`) iterates every engine; inspect `build/ui_new/`
  for the new engine's pages (AGENTS.md requires it for UI changes).

### 1.7 Wiring the file

1. Create `firmware/src/eng_x.c` with the GPL-3.0-only SPDX header
   ([CONTRIBUTING.md](../CONTRIBUTING.md)).
2. `#include "eng_x.c"` in `firmware/src/engines.c` with the other `eng_*.c` files (this is the
   dependency-order include point used by `felucca.c`, `tests/hostsim.c` and `web/emu`), and
   add `&ENG_X` at the end of `ENGINES[]`.
3. Add it to `ENGINE_ORDER[]`, `eng_abbr()`, `PRESET_CAT[]`, `N_ENGNAME[]` in
   `firmware/src/params.c` (`GP[G_ENGSEL]` takes the engine-select enum's names and maximum, which
   the protocol's DESC advertises, from it) and the protocol document.
4. If its render function is not already covered, add the render function names to `FUNCS` in
   `tests/target_budget.py`.
5. `tools/size_fns.py` lists main-loop files (`SIZE_FILES`) that get `minsize`; the `eng_*.c` render files
   are not in that list and keep `-Os`; leave them out.
   `engines.c` itself is in `SIZE_FILES`, but ISR-reachable functions are excluded by the
   reachability pass; trace reachability if you add a callback (section 3.5).
6. Use `static` for implementation-local functions and state.

### 1.8 Tests and baselines

| Check | What to do |
| --- | --- |
| `tests/golden.txt` | `tests/regress.c` renders every engine and preset; a new engine adds `preset/NAME/...` entries. Add them with `GOLDEN_UPDATE=1` and review the diff: only the new entries may appear, existing hashes must not change. |
| `tests/union_golden.txt` | If `mem != 0` (or the engine shares state), extend `tests/union_test.c` and its golden. Existing hashes are 1.4's and must not change; `GOLDEN_UPDATE=1` only with a stated reason. |
| CPU baselines | `tests/cpu_baseline*.txt` per host/toolchain; `BUDGET_UPDATE=1` rewrites them, only on a host with a working counter ([performance.md](performance.md)). Budget growth failing is a finding, not a reason to regenerate. |
| Target budget | `tests/target_budget.txt` from the disassembly: `python3 tests/target_budget.py build/felucca.dis tests/target_budget.txt`. |
| Engine test | Add `tests/<engine>_test.c` and register it in `tests/run_tests.sh` (see `noise_test.c`, `drum_test.c`, `slice_test.c`). |
| UI | `tests/ui_render.c` / `tests/ui_test.c` (category strings, layout lint). |
| Editor tables | `tests/descdump.c` writes `build/host/desc.json`, which `web/test_web.mjs` compares with the web mock's tables. |

`GOLDEN_UPDATE=1` and `BUDGET_UPDATE=1` rewrite baselines intentionally; AGENTS.md
("Build and validate") sets the rule: explained changes only, review every changed entry,
retain unaffected entries.

## 2. Adding an effect or mixer bus

- The mix path is `mix_block()` in `firmware/src/fx.c`: events, each part (`mix_part`: voices,
  per-track DIST, INSERT, SLICER, level/pan, sends), the three shared buses
  (`fx_buses`: chorus, tempo delay, reverb), the FX hold layer (`perform.c`), then the master
  (`master_out`). `audio.c audio_block()` calls it per `CTL` block, then USB audio and the click.
- **Per-track insert.** The INSERT types are `IT_*` in `fx.c` with names in `N_ITYPE` and
  labels in `ins_desc()` (`params.c`). Types are **append-only because they are stored**
  (comment at `N_ITYPE`). `MIX 0` or `TYPE OFF` must leave the track bit-identical and cost
  nothing (`track_insert` is `noinline` so the ISR path gains only one test per part).
- **Buses and the FX layer.** Reverb models are selected by `G_RTYPE` (`fx.c`); layer effects are
  in `perform.c`. A new bus or layer effect adds state in `.pool` (declare with
  `__attribute__((section(".pool")))` as `fx.c` does) and, if it needs parameters, new global or
  track parameters under the rules in sections 1.5 and 4.
- **Budgets.** Effects run inside the audio ISR. Keep work bounded per block with a cheap idle
  path, add per-sample loops to `FUNCS` in `tests/target_budget.py` (existing entries cover
  `rev_*`, `perf_*`, `slicer_track`), and report RAM/POOL bytes (the build fails below
  4,096 B RAM / 8,192 B POOL spare, `tools/build.py`). Buffer sizes grow per sample and channel
  ([performance.md](performance.md), "RAM and stack").
- Tests to extend: `tests/insert_test.c`, `tests/perform_test.c`, `tests/reverb_test.c`,
  `tests/mod_test.c` as applicable, plus the golden mix entries in `tests/regress.c`.

## 3. Platform contracts

### 3.1 Interrupt priorities and bounded work

- Audio: ALNK0 DMA interrupt, priority 3 (`fm1_audio_init(..., isr_alnk0, 3)` in
  `firmware/src/audio.c`). It renders one DMA half (`HALF_FRAMES = 128`) in blocks of `CTL`.
- Input scan: TIMER5 at 10 kHz, priority 4, so it **nests inside** the audio ISR
  (`timer5_start()` in `firmware/src/main.c`; rationale in the comment above
  `fm1_timer5_irq`). Nested, it scans and counts time, and with `FELUCCA_UAC=1` (the build default in [BUILDING.md](../BUILDING.md))
  it also runs `uac_service()` every 5th tick: the USB audio stream cannot wait for a render. That
  path touches only EP4 and the consumer side of the audio ring; `usb_poll()` and
  `uart_midi_poll()` wait for the first tick outside the render, so the two USB paths never
  interleave. Count `uac_service` among the nested-ISR code in reachability and shared-state
  analysis.
- Overload: `shed_check()` / `shed_voice()` in `audio.c` drop voices after two consecutive
  halves above 85 %. Measurements to watch are in [performance.md](performance.md).
- Rules (AGENTS.md "Bounded interrupts"): UI, preset loading, flash operations and formatted
  diagnostics run in the main loop through the existing request/service paths; no allocation,
  blocking I/O or waiting locks in interrupts.

### 3.2 HAL boundary

All hardware register access lives in `firmware/hal/`. `tools/build.py` (`mmio_check`, the
comment above `MMIO_LIT`) fails the build when `src/` or `loader/` contain: a volatile pointer
cast (except of a C object's address), a literal in a register or reserved window, inline asm
other than the `RING_PUBLISH()` barrier, or a HAL register macro. Add a helper in `hal/`
(`FM1_INLINE` in `hal/fm1_cc.h` forces inlining where register sequence and timing matter)
and call it. Interrupt entry assembly is `hal/fm1_isr.S` / `hal/fm1_vec.S`; attachment is
`fm1_irq_attach(n, handler, prio)` in `hal/fm1_irq.h`.

### 3.3 Queues, publication and shared state

- `RING_PUBLISH()` (`core.h`) is a compiler barrier: store the slot, publish, then update the
  index. Keep each ring's single producer and single consumer, its bound and this order.
- `volatile` alone does not publish surrounding data, and a flag and a multi-field snapshot need
  different synchronisation (AGENTS.md "Explicit ownership"). Existing patterns: the audio ring
  consumed by `uac_service` (called from the TIMER5 handler, `main.c`), `midi_in_q` (`midi_uart.c`), `shed_req` (`audio.c`).
- Side-effecting register and test-clock reads go in separate statements (AGENTS.md).

### 3.4 Flash-safe execution

- Code that runs while the flash (XIP) is busy lives in `.ram_text` (`RAMFN` in
  `hal/fm1_flash.h`) and may touch only SFRs, the stack and RAM: no `.rodata`, no libcalls, no
  XIP helpers, no calls. `tools/build.py` disassembles `.ram_text` and fails if it contains
  calls, and `loader_check()` in the same file checks the loader's sections against its RAM window.
- An erase pauses audio and scanning. Saves are deferred and coalesced
  (`firmware/src/settings_persist.c`, `storage.c`), autosave follows the stopped/idle policy and a
  knob detent must not start a new immediate erase.

### 3.5 Selective size pass

`tools/size_fns.py` adds `minsize` to functions defined in `SIZE_FILES` (UI, stores, editor,
USB, sequencer, ...). Everything an interrupt reaches stays `-Os`: `ISR_ROOTS` are
`fm1_alnk0_irq` and `fm1_timer5_irq`, and `isr_reach` follows function bodies, global and alias references in the IR, and
unresolved ISR dispatch needs a reviewed entry in `ISR_INDIRECT`. Adding a callback or moving a helper that an ISR calls into a
`SIZE_FILES` file must be checked against that reachability; `tests/size_fns_test.py` and
`tests/size_fns_target_test.py` are the regression tests. The engine hooks (`note_on`, `render`, `amp`, `block`, `done`, `keys`) are reached through
`ENGINES[]` and are declared in `ISR_INDIRECT` (`track_render`, `voice_start`, `chord_kit`,
`kb_engine`, `seq_step`); a new kind of indirect call from interrupt code needs a reviewed entry
there. Compare with `FELUCCA_SIZE=0 ./build.sh`
([performance.md](performance.md), "Firmware size").

### 3.6 Linker regions

`firmware/app.ld` is authoritative: `XIP` (app slot, 0x8DFBC bytes), `RAMTEXT`
(`.ram_text`), `RAM` (72 KiB: `.data/.bss`, what the audio and scan interrupts touch), `POOL`
(`.pool`: big zero-initialised buffers, engine memory, FX lines), `NOINIT` (diagnostics and
retained slots that survive reset), two stacks with 256-byte guard bands, and the reserved top of
RAM. `RAM` and `POOL` are one SRAM: moving the boundary reallocates it. `tools/build.py` reads the
lengths from the linker script and enforces the spare minimums (4,096 B RAM, 8,192 B POOL).
Place big buffers in `.pool`; interrupt-touched small state stays in RAM. Keep the stack guards,
reserved RAM and reset diagnostics intact. Large automatic arrays spend stack even if static
sections stay flat.

## 4. Persistence and protocol

- Storage is a versioned A/B-sector object store (`firmware/src/storage.c`): the payload is
  written first and the header (magic, sequence, CRC) last as the commit record; the newest
  valid copy wins. Settings (`settings_persist.c`), user presets (`upreset.c`) and projects
  (`project.c`) sit on it.
- **Track parameters.** The `P_COUNT` a record was written with is stored; older records map by
  count (`params_by_count()`), so common parameters may only be added before `P_E0`. Projects
  ("FUN" formats, header comment in `project.c`) and user presets (`UP_VER`, header comment in
  `upreset.c`) document which counts, formats and migrations exist. If a change cannot map by
  count, bump the version and translate.
- **Old formats.** Keep reading every older format (`tests/old_pack.h` holds the historical
  layouts, `tests/persistence_test.c`, `project_test.c`, `upreset_test.c`, `fuzz_proj.c`
  cover them). Add round-trip, default and malformed-input tests together with the change.
  State downgrade limits explicitly: for example firmware that does not know a newer project
  count refuses it (`np > P_COUNT`; see the `project.c` header).
- **Retired values.** Retired engines, enum values and parameter ids stay reserved and keep a
  migration (`core.h` `drum_from_phys`, `drum_from_perc`; `params.c enum_orig`, `param_fit`).
- **Editor protocol.** SysEx commands, parameter ids and `INFO` are specified in
  [web/EDITOR_PROTOCOL.md](../web/EDITOR_PROTOCOL.md): the editor must take `P_E0` from `INFO`,
  and `DESC` supplies engine parameter labels and ranges. Changing a serializer means updating
  that document, `tests/descdump.c`/`tests/editor_test.c` and `web/test_web.mjs`. The editor and
  installer UI live in [Felucca-WebApp](https://github.com/hugelton/Felucca-WebApp).
- **Third-party code or data** needs its attribution and licence recorded
  ([LICENSING.md](../LICENSING.md), `LICENSES/`).

## 5. Checklist

Engine:

- [ ] SLICE's slot 13 reserved in `FELUCCA_SLICE=0` builds before appending (1.1).
- [ ] Appended to `ENGINES[]`; `NENGINES`, `ENGINE_ORDER[]`, `eng_abbr()`, `PRESET_CAT[]`,
      `N_ENGNAME[]`, protocol engine table updated; no existing number moved in any build option.
- [ ] `edit[]` ranges/defaults deliberate (they are stored); `desc` hook keeps range/default.
- [ ] `mem` set with `ENG_MEM_FITS`; zeroed region is a valid initial state; switch tests added.
- [ ] Render is bounded, fixed-point-exact, click-free on retrigger/switch, releases cleanly.
- [ ] Wired once via `engines.c`; builds for the target, `tests/hostsim.c` and `web/emu`.
- [ ] Goldens, union golden (if state shared), CPU and target budgets updated only with review.
- [ ] Engine test added to `tests/run_tests.sh`; UI renders inspected in `build/ui_new/`.

Effect / bus:

- [ ] Idle fast path; off state bit-identical; per-block work bounded; state in `.pool`.
- [ ] Types/ids append-only; new parameters added before `P_E0` with defaults for old records.
- [ ] Target budget and RAM/POOL/app-size deltas reported.

Platform / persistence:

- [ ] No register access outside `firmware/hal/`; `.ram_text` has no calls.
- [ ] ISR reachability checked if size lists or callbacks changed.
- [ ] Old-format import, round trip, malformed input and downgrade behaviour tested;
      `web/EDITOR_PROTOCOL.md` updated.
- [ ] `README.md` reviewed for user-facing changes (AGENTS.md "User-facing documentation").
- [ ] `./build.sh` clean (no new warnings) and `tests/run_tests.sh` green; skipped checks and
      real-device validation stated (AGENTS.md "Completion evidence").
