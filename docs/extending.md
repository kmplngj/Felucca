<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Extending Felucca: engines, effects and platform contracts

This guide lists what a change must touch and preserve when it adds a sound engine, an effect
or anything that crosses the hardware, interrupt, flash or storage boundaries. It points at the
code and documents that hold the rules and summarises their native contracts. When this page and the source
disagree, the source wins (and this page needs a fix). Process and evidence rules are in
[AGENTS.md](../AGENTS.md), build and test setup in [BUILDING.md](../BUILDING.md), measurement
procedure in [performance.md](performance.md), licensing in [LICENSING.md](../LICENSING.md) and
[CONTRIBUTING.md](../CONTRIBUTING.md).

The firmware is one translation unit: [felucca.c](../firmware/src/felucca.c) includes the other C files in
dependency order, and [tests/hostsim.c](../tests/hostsim.c) (also used by
[web/emu/felucca_web.c](../web/emu/felucca_web.c)) includes the same
sources against simulated hardware. A file that is not included from those places is not built.
Target order is HAL/generated tables, display, core/engines/modulation/voices/mixer,
USB/sequencer/audio, UI, storage/update/editor, then boot/main. Do not add an independent audio
or main-loop wrapper. Feature defaults are defined beside their features: `felucca.c`
for the main options, [core.h](../firmware/src/core.h) for engine options,
[icons.c](../firmware/src/icons.c) for `FELUCCA_ICONS`,
[usb.c](../firmware/src/usb.c) for `FELUCCA_UAC_48K`, `FELUCCA_UAC_AS_FIRST` and
`FELUCCA_CDC_DEFAULT`, and [ota.c](../firmware/src/ota.c) for `FELUCCA_OTA_RAMONLY`.
[tools/build.py](../tools/build.py) forwards environment overrides; use
[BUILDING.md](../BUILDING.md#build) for their supported settings.

## 1. Adding an engine

### 1.1 Stable IDs

- An engine's number is its id in the engine id space 0..`ENG_ID_MAX`−1 (64, `core.h`) and its index in
  `ENGINES[]` (`firmware/src/engines.c`). The editor protocol, user presets, projects and favourites store
  it. **Append; never reorder or reuse.** `NENGINES` is only the length of this build's table (its highest
  id + 1); it is no stored value and no marker ([#212](https://github.com/kmplngj/Felucca/issues/212)).
- A retired engine keeps its slot. Engine 1 (DIGITAL) is the example: `ENG_FM4_GONE` fills
  the slot, `eng_ok()` refuses to select it and old sounds convert to FM6
  (`firmware/src/fm4_convert.c`).
- An id a build lacks (one its catalog leaves out, as `FELUCCA_SLICE=0` leaves out 13, or one past its table)
  maps to `ENG_NONE`: `eng_idx()` / `eng_of()` never give another engine. Such a sound is kept as stored, shown
  as N/A and silent. Compare ids exactly (`t->eng_req == ENGI_X`) or pointers (`eng_of(e) == &ENG_X`); never
  reduce an id with `% NENGINES`. A build option that leaves an engine out keeps the slot (`ENG_AT()` puts
  `ENG_NONE` there) and removes it from `ENGINE_ORDER[]`, so every other number stays.
- Favourites have a row per id (`FAV_ROWS` = `ENG_ID_MAX`); MIDI Learn's map and the device bytes are
  `settings_ml` / `settings_dev`, not favourites rows. A first favourite on an id from 14 makes the settings
  PER6 (`settings_persist.c`). Per-engine tables (`MIDI_CC_ENG[]`, `PRESET_CAT[]`) are sized by `ENG_ID_MAX`.
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
| `keep` | `voice_start` restores selected `s[k]` slots for a sounding, non-sampled retrigger: supported bits are 0, 1 and 4..7 (filters/colour poles); `s[2]`/`s[3]` are not restored. |
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
- Declare the state type, access it through `ENG_MEM_OF(t, engine_id, p)`, set `.mem = sizeof(state)`, and
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
- `ENG_MEM_OF` becomes `ENG_MEM` on the target. With host-only `FELUCCA_ARENA_CHECK=1`
  it validates the part, rendered engine and arena owner, then traps on an invalid access
  (or invokes the test handler and returns scratch). It does not detect an in-arena overrun.
  [tests/arena_test.c](../tests/arena_test.c) covers these boundaries. The region is currently
  12,888 bytes per part; growing it costs four aligned regions, not one (`NPART=4`).

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
- [#31](https://github.com/kmplngj/Felucca/issues/31) owns shared parameter-metadata
  exploration; reuse these native descriptors and preserve numeric/wire IDs rather
  than creating a plugin metadata system in an engine extension.

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
   reachability pass; trace reachability if you add a callback (section 3.6).
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

### 1.9 Worked example: the existing NOISE engine

Follow [eng_noise.c](../firmware/src/eng_noise.c), rather than copying a separate DSP:
`ENG_NOISE` supplies eight descriptors, two page titles, four presets, HOME knob bindings,
`noise_note_on`, `noise_render`, `noise_desc` and `.keep=0xF3`. It has no per-part arena
(`mem` defaults to zero); its filter, RNG, colour poles and clock live in `voice_t.s[]`/`ph[]`.
`voice_start()` in [voice.c](../firmware/src/voice.c) owns note/velocity/gate/envelope setup,
calls the hook, then restores the selected filter state and oscillator phases on a sounding
retrigger. `track_render()` computes the amplitude ramp and modulation before rendering.
The renderer **adds** `voice_amp()` samples into the mono `out[0..n-1]`; it does not clear
the mix or create/retire voices. `noise_desc()` changes labels/value names for LFSR/META
while keeping the stored ranges/defaults of `edit[]`.

The integration trail is `engines.c` (include, ID 11, display order),
[params.c](../firmware/src/params.c) (`N_ENGNAME`),
[category.c](../firmware/src/category.c) (`PRESET_CAT`),
[ui_graph.c](../firmware/src/ui_graph.c) (`eng_abbr`),
[icons.c](../firmware/src/icons.c) (`engine_icon`),
[ui_help.c](../firmware/src/ui_help.c), and the
[protocol engine table](../web/EDITOR_PROTOCOL.md). Generic EDIT/HOME pages reuse its
descriptors. For a new engine, check every integration site in 1.7, even if it needs no
special UI gate. NOISE's applicable harnesses are [noise_test.c](../tests/noise_test.c),
[regress.c](../tests/regress.c), [target_budget.py](../tests/target_budget.py),
[ui_test.c](../tests/ui_test.c), [ui_render.c](../tests/ui_render.c),
[descdump.c](../tests/descdump.c) and [web/test_web.mjs](../web/test_web.mjs), all wired
through [run_tests.sh](../tests/run_tests.sh). Arena-consuming engines additionally need
the union and arena tests in 1.3/1.8.

The native hook callers and units are in [core.h](../firmware/src/core.h),
[voice.c](../firmware/src/voice.c), [seq.c](../firmware/src/seq.c) and `params.c`:

| Hook | Caller/context and contract |
| --- | --- |
| `note_on` | `voice_start`, normally audio event processing; initialise the supplied core-owned voice, with MIDI note/velocity already set. No allocation or flash. |
| `block` | `track_render`, audio ISR, once per part/control block, including no sounding voices. |
| `amp` | `track_render`, audio ISR, once per active voice/control block; input/output Q15, after `env_tick`. Core still owns gating. |
| `done` | `track_render`, audio ISR, before rendering an `ownenv` voice; nonzero retires it. Preserve the engine's release tail until then. |
| `render` | `track_render`, audio ISR; add `n` mono samples using the supplied `vmod_t`, normally `n=CTL`. Do not confuse this buffer with the later interleaved stereo output. |
| `desc` | `track_desc`, device UI lookup; immutable descriptor or null fallback, same range/default. Editor `ed_tdesc` uses static `param_desc_of` without this hook (1.5). |
| `keys` | `kb_engine` through `kb_map`, including audio keyboard/sequencer paths and UI map drawing; logical key index, mapped MIDI note or -1 fallback. Must also be safe in interrupts. |

Direct host/emulator callers exercise the same hooks outside hardware interrupts.
`NVOICE=8` is the **shared sounding-voice budget** across four parts, even though every
part has eight voice slots. `voices_busy()` excludes voices already fading; `voice_victim()`
prefers release tails/excess unison voices and protects each part's bass/lead. A note-off
enters release, not immediate deallocation. Victims passed to `voice_kill()` for shared
budget room or overload fade over the next block. `voice_alloc()` instead reuses an
active lane in place when its part's lanes are exhausted or its shared-budget victim
is in that same part: no `voice_kill()` fade occurs on that path. `voice_start()` uses
the sounding retrigger rules above, so `note_on` must also remain click-safe without
a preceding fade. Engine switches follow the separate fade in 1.4. Do not add an
engine-local note queue or voice allocator.

## 2. Adding an effect or mixer bus

- The mix path is `mix_block()` in `firmware/src/fx.c`: events, each part (`mix_part`: voices,
  per-track DIST, INSERT, SLICER, level/pan, sends), performance send preparation (`perf_pre`),
  the three shared buses (`fx_buses`: chorus, tempo delay, reverb), master gain,
  FX hold processing (`perf_block` in `perform.c` when active), then the master
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
  4,096 B RAM / 8,192 B POOL spare, `tools/build.py`; NOINIT takes no new users and the build also fails below
  100 B of its spare). Buffer sizes grow per sample and channel
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

The current producer/consumer pairs are in [usb.c](../firmware/src/usb.c),
[midi_uart.c](../firmware/src/midi_uart.c), [seq.c](../firmware/src/seq.c) and
[main.c](../firmware/src/main.c):

| Data | Producer → consumer | Bounds/failure |
| --- | --- | --- |
| `midi_in_q`, timestamps, source | TIMER5 USB/TRS polls → audio `events_block` | `MQ=64` packets; full/broken input sets `midi_in_overflow`, consumer discards the broken stream and releases notes. |
| `midi_out_q` | Audio `midi_out_event` → TIMER5 `ep1_tx` | 64 packets; disconnected/full drops the new outgoing packet. |
| `ua_ring` | Audio `uac_tap` → TIMER5 `uac_service`/`uac_packet`, including nested ticks | Bounded by `UA_N`; overrun drops a block, underrun repeats the last frame and counts the error. |
| `sx_frame`, `sx_ready` | TIMER5 SysEx collection → main-loop editor/OTA service | One 640-byte frame; pending frames are not overwritten, extra frames drop and the update host retries. Consumer releases with `ota_frame_done`. |
| `sx_out_q` | Main-loop SysEx replies → TIMER5 `ep1_tx` | `SXQ=64`; the main-loop sender waits with timeout/idle servicing, never from an ISR. |

Publish every packet's payload **and** metadata before its write index. The empty asm
`RING_PUBLISH()` prevents compiler reordering in this single-core interrupt model; it is
not a hardware memory fence, atomic snapshot or CPU1/cache coherence protocol. The
`sx_ready` flag is a handoff with a buffer-lifetime rule. Multi-field mutations such as
`eng_req` plus eight parameters use a bounded IRQ-off window instead (`set_engine_of`
in [ui.c](../firmware/src/ui.c)). These disable/enable paths require main-loop context
with interrupts enabled at entry. Despite their names, `fm1_flash.h`'s `irq_save()`
always returns 0 and `irq_restore()` unconditionally enables interrupts: they do not
preserve prior state and must not be nested or used from an ISR/IRQ-off caller.
Adding `volatile` to each field would still let an
interrupt observe a partly updated engine selection.

### 3.4 Audio units and output taps

[gen_tables.py](../tools/gen_tables.py) defines `FS=44100` and `CTL=32` in the generated
tables; [core.h](../firmware/src/core.h) defines `HALF_FRAMES=128`. Thus one nominal DMA
half is four control blocks and `128 / 44100` seconds (~2.902 ms), with nested TIMER5 work
also spending that deadline. The actual I2S frame period is `DAC_TICKS=544` TIMER4 ticks
([audio.c](../firmware/src/audio.c)); nominal DSP sample rate is not a measurement of
device timing. `n` is frames/samples per channel, not stereo words: a mono voice buffer
has `n` `int32_t`s, `mix_block`/`audio_block` has `2*n` interleaved words (left `2*i`, right
`2*i+1`), and the double DMA buffer has `2*HALF_FRAMES*2` words.

The native path is events → voices → track DIST/INSERT/SLICER → level/pan/sends →
performance send preparation → shared buses → master gain → active performance hold
processing → `master_out` → `uac_tap` → optional `usb_fixed_dac` →
DAC-only `click_render` → multiply by `1 << OUT_SHIFT` → I2S DAC. See
[fx.c](../firmware/src/fx.c), [perform.c](../firmware/src/perform.c), `audio.c` and `usb.c`.
USB LEVEL MASTER (default) follows MASTER before master processing; USB LEVEL FIXED
processes/taps the full-level master output, then applies MASTER only to the DAC branch.
USB never contains the metronome. Its 16-bit samples are saturated by `uac_s16`, and a
48 kHz stream uses the optional FIR resampler, so USB PCM is not universally identical
to speaker/headphone output. `FELUCCA_UAC=1` and `FELUCCA_UAC_48K=1` are current defaults
([felucca.c](../firmware/src/felucca.c), [usb.c](../firmware/src/usb.c),
[BUILDING.md](../BUILDING.md#build)).

[dsp.c](../firmware/src/dsp.c) and `core.h` define the arithmetic: sample/amplitude values
use Q15 (32767 near unity); gain/cutoff coefficients also use named Q12 scales (4096 =
unity); `voice_t.env` is Q24; pitch is 1/16 semitone. Conventional oscillator `ph`/`inc`
are unsigned 32-bit phase (one full wrap per cycle), while sampled engines and FM6 have
their own documented units. Preserve each helper's bounds, rounding and saturation;
`mulq15` is a bounded 32-bit product followed by a shift, not a saturating arbitrary-range
multiply. `amp_at()` preserves signed division's truncation toward zero, and NOISE's
filter explicitly rounds to avoid DC drift. Replacing a signed divide with a bare shift
can change negative samples. Review sound goldens and target arithmetic together.

### 3.5 Flash-safe execution

- Code that runs while the flash (XIP) is busy lives in `.ram_text` (`RAMFN` in
  `hal/fm1_flash.h`) and may touch only SFRs, the stack and RAM: no `.rodata`, no libcalls, no
  XIP helpers, no calls. `tools/build.py` disassembles `.ram_text` and fails if it contains
  calls, and `loader_check()` in the same file checks the loader's sections against its RAM window.
- An erase pauses audio and scanning. Saves are deferred and coalesced
  (`firmware/src/settings_persist.c`, `storage.c`), autosave follows the stopped/idle policy and a
  knob detent must not start a new immediate erase.

### 3.6 Selective size pass

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

### 3.7 Linker regions

`firmware/app.ld` is authoritative: `XIP` (app slot, 0x8DFBC bytes), `RAMTEXT`
(`.ram_text`), `RAM` (72 KiB: `.data/.bss`, what the audio and scan interrupts touch), `POOL`
(`.pool`: big zero-initialised buffers, engine memory, FX lines), `NOINIT` (diagnostics and
retained slots that survive reset), two stacks with 256-byte guard bands, and the reserved top of
RAM. `RAM` and `POOL` are one SRAM: moving the boundary reallocates it. `tools/build.py` reads the
lengths from the linker script and enforces the spare minimums (4,096 B RAM, 8,192 B POOL, 100 B NOINIT).
Place big buffers in `.pool`; interrupt-touched small state stays in RAM. Keep the stack guards,
reserved RAM and reset diagnostics intact. Large automatic arrays spend stack even if static
sections stay flat.

| Region | Current address/capacity from [app.ld](../firmware/app.ld) |
| --- | --- |
| XIP app | `0x02000120`, `0x8DFBC` bytes (581,564), including RAM load images |
| RAMTEXT | `0x01C00000`, `0x6000` bytes; next `0x2000` bytes reserved for RAM-run debug |
| RAM | `0x01C08000`, 72 KiB |
| POOL | `0x01C1A000`, 360 KiB, ending at `0x01C74000` |
| User stack | `0x01C74100..0x01C7A000`, preceded by a 256-byte guard |
| Supervisor stack | `0x01C7A100..0x01C7C000`, preceded by a 256-byte guard |
| NOINIT | `0x01C7C000..0x01C7FD50`, `0x3D50` bytes; retained, not normal zero-initialised scratch |
| Reserved top | From `0x01C7FD50`: boot info/mailbox/vector table; never borrow for module state |

Spare static RAM/POOL bytes are not stack high-water measurements. Linker layout and
[fm1_guard.h](../firmware/hal/fm1_guard.h) guards detect different failures; follow
[performance.md](performance.md#ram-and-stack) for stack/resource evidence.

### 3.8 Panel, drawing and main-loop services

[fm1_input.h](../firmware/hal/fm1_input.h) exposes physical matrix IDs: `fm1_in.notes`,
`fm1_in.buttons`, `fm1_input_edges()`, `fm1_input_note_edges()` and `fm1_enc_take()`.
TIMER5 owns the scan/debounce. [panel.c](../firmware/src/panel.c) maps them to logical
`B_*` buttons and `EN_*` roles using the validated/calibrated `panel.btn[]`, `enc[]` and
`dir[]`. Use `panel_btn_of()` for a raw button and `panel_enc(EN_K1)` (etc.) for clockwise
logical steps; shifting `1u << B_PLAY` as if it were a physical bit is wrong. Invalid,
duplicate or out-of-range calibration resets to `PANEL_DEFAULT`. Musical keys are
consumed by audio `keyboard_block()` with press-time note ownership; UI key gestures
use the existing input layer. [ui_input.c](../firmware/src/ui_input.c) `ui_leds()` maps
logical buttons through `panel.btn[]` and uses local `led_put()` to compose lit, dim,
mid-level and breathing planes. It publishes their packed column arrays to `fm1_led`,
`fm1_led_dim`, `fm1_led_mid` and `fm1_led_breath`, with glow before lit so a transition
from lit to dim has no dark frame. Extend that composition for UI LED behavior.
HAL `fm1_led_key` is a separate binary on/off helper for physical button IDs 0..13
and note-key IDs 14..40; it is not `ui_leds()`'s multi-level path.
MASTER is the ADC pot, sampled by
[master.c](../firmware/src/master.c) `master_boot`/`master_poll`, not an encoder.

Drawing is main-loop work: [gfx.c](../firmware/src/gfx.c) `cv_begin`, `cv_rect`, `cv_line`,
`cv_text`/`cv_text_in`, `cv_blit`; `aafont_t` and generated `AF_S`/`AF_M`/`AF_L` fonts
use the selected build font. The 240×240 display has no full framebuffer: `CV_MAX` is
240×124 RGB565 pixels (59,520 bytes in `.pool`). `cv_begin` clips height to capacity;
callers still must provide bounded, nonzero dimensions and in-screen blit extents.
[lcd.c](../firmware/src/lcd.c) `lcd_data`/`lcd_blit` start asynchronous DMA from **RAM**.
The source stays valid and unmodified until `lcd_sync`; `cv_begin` synchronises before
reusing `cv_px`. A stack buffer that expires during DMA or a flash pointer is invalid.

[main.c](../firmware/src/main.c) services `ui_input`, `ui_leds`, `ui_draw`,
`master_poll`, `ed_service`, `ota_service`, settings/autosave and watchdog in the main
loop. It can request bounded audio actions; it does not drain the musical MIDI ring.
All normal SIE access is TIMER5's 2 kHz `usb_poll`, with the nested EP4 UAC exception
in 3.1. Startup/update bring-up has its own explicit paths; a UI hook must not poll SIE.

### 3.9 MIDI and time

USB and TRS feed the same bounded musical queue, with source 1/2 and arrival `fm1_ms`
timestamp (`midi_enqueue` in [usb.c](../firmware/src/usb.c)). Audio `events_block` in
[seq.c](../firmware/src/seq.c) owns consumption/routing, keyboard notes, transport and
external-clock dispatch; the selected clock source alone contributes clock events.
[midi_control.c](../firmware/src/midi_control.c) retains note-off ownership across route/
track changes. USB packet backpressure, TRS DMA overrun and input panic handling are
in `usb.c`/[midi_uart.c](../firmware/src/midi_uart.c); do not add another consumer.
Editor/update SysEx is collected separately and handed to main-loop
[editor.c](../firmware/src/editor.c)/[ota.c](../firmware/src/ota.c) services; editor replies
and updater requests share the transport's frame/TX lifetime rules, not the note queue.

[fm1_time.h](../firmware/hal/fm1_time.h) supplies TIMER4 at 24 MHz (`FM1_TICKS_PER_US=24`).
Its uint32 tick counter wraps every `2^32 / 24000000` seconds (~178.957 s). Take start and
end with separate, sequenced `fm1_ticks()` statements; compute the **unsigned tick
difference first**, then divide by `FM1_TICKS_PER_US`. This measures elapsed intervals
strictly shorter than one wrap (maximum representable delta `UINT32_MAX` ticks), provided
the timer was not reset. `fm1_micros()` divides each absolute reading before returning it:
it wraps from ~178,956,970 microseconds to zero, not at `UINT32_MAX`, so subtracting its
readings across the hardware wrap is unsafe. There is currently no firmware caller;
this is an API trap, not a claimed existing timing bug.

`fm1_ms` is a separate wrapping millisecond clock accumulated from unsigned TIMER4
differences in TIMER5. Sequencer/sample progress and DSP phase clocks follow control
blocks; a UI time reading is not sample-accurate scheduling. Keep these units explicit.

Variable 64-bit division/remainder can require unavailable `__udivdi3`/`__divdi3`/
`__umoddi3` helpers. [build_guard_target_test.py](../tests/build_guard_target_test.py)
and its [evidence guide](../tests/build_guard_fixtures/README.md) separately check those
link failures and successful widened multiplication/constant shifts with the production
JieLi flags. Bounded products and shifts are allowed; prove every divisor nonzero and
inspect target output. [fm1_irq.h](../firmware/hal/fm1_irq.h) intentionally disables the
native div0 trap because JieLi may hoist a guarded division; host tests alone cannot
prove target sequencing ([fm4_div0_test.c](../tests/fm4_div0_test.c)). Do not switch the
trap on or mechanically turn divisions into shifts. DSP remains fixed-point; this guide
makes no AC791N “no FPU” claim. [#82](https://github.com/kmplngj/Felucca/issues/82) owns
any separate opt-in FPU/ABI/IRQ/device experiment.

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

### 4.1 Flash map and deferred-save example

These are **flash offsets**, distinct from the CPU/XIP addresses in 3.7. The authorities
are [fm1_flash.h](../firmware/hal/fm1_flash.h) range guards,
[storage.c](../firmware/src/storage.c) object sectors,
[ota.c](../firmware/src/ota.c) staging, and
[fm1pkg_make.py](../tools/fm1pkg_make.py) app/package extents. Ends below are exclusive:

| Purpose | Flash offsets |
| --- | --- |
| Four project A/B pairs | `0x97000..0x9F000` |
| User-preset FM6 patches | A `0x9F000..0xA0000`, B `0xFE000..0xFF000` |
| User samples | `0xA0000..0xDC000` |
| User-preset banks | `0xDC000..0xE0000` |
| OTA loader staging | `0xE0000..0xE5000` (20 KiB), commit record at `0xE4F00` |
| Autosave A/B | `0xE5000..0xE7000` |
| FM6 voice bank | `0xE7000..0xE8000`; uses the autosave's older sector to stage an update |
| Settings A/B | `0xFC000..0xFE000` |

No sector in these ranges is free. Allocations for planned persistent features, the options and the
rules for a new object are in [flash-capacity.md](flash-capacity.md).

Storage objects have 4 KiB sectors, 3,840-byte payload capacity (`ST_PAYLOAD_MAX`),
and a 32-byte CRC-bearing header committed last after payload pages at offset 256.
Failed/torn writes keep the earlier valid A/B copy. This is not a 256-byte single-sector
save API. The package builder enforces `APP_SLOT=0x8DFBC`, a `FLASH_SIZE=0x93000`
initial flash image and its nested configuration extents; that image length is not a
licence to write the surrounding stock areas. `FL_STORE_OK` admits only native storage
ranges; `FL_RANGE_OK` additionally admits OTA staging. Keep their bounds unchanged for
extensions. [storage_hw.c](../firmware/src/storage_hw.c) silences DMA before IRQ-off
erase and rejects writes outside storage with `-8`; RAM flash primitives separately
validate erase alignment/page bounds. OTA verifies the package/loader and host success
before committing the update record; it does not share project scratch implicitly.

For example, `settings_save()` in [project.c](../firmware/src/project.c) marks
`persist_pending` and calls `settings_poll`: a busy transport defers the save; an
unchanged exported record clears the request without erase; failure sets
`persist_pending=2`, so subsequent polling without a new save request waits at least
1 s before retrying. A fresh `settings_save()` resets that state to 1 and calls the
poller immediately, bypassing the retry delay. It can save immediately **when stopped**
and is not a rate-limited API, so do not turn every new knob detent into a new call.
`autosave_poll()` runs in the main loop
every 250 ms, after 10 s unchanged/quiet and at least 60 s between successful writes
(30 s retry gap on failure). It requires stopped transport, no keys/buttons/active
voices and honors editor transfer holds/RESTORE LAST OFF. Boot restoration also follows
the existing clean-boot policy. Extend the same versioned records/defaults/tests instead
of bypassing these owners with a flash call from a callback.

## 5. Usage-mode coordination (proposed, not a current API)

Current source has one Felucca boot/main/sequence workflow and the build flags above.
It has no mode registry, startup chooser or module/profile resolver. The following
vocabulary and ownership are the planned coordination in
[#28](https://github.com/kmplngj/Felucca/issues/28) and
[#203](https://github.com/kmplngj/Felucca/issues/203), not callable hooks or delivered
features. Keep existing sound/UI/storage behavior as the baseline while extracting
the proposed default adapter:

| Identity | Responsibility |
| --- | --- |
| Build profile | Installed engines/effects/UI/assets/platform features and modes, resolved once for target/host/emulator. |
| Usage mode | One active top-level workflow/pages/control policy, using the entire installed sound catalog. Felucca is mandatory/default mode 0 in the proposal. |
| Instrument/preset | Per-part sound; engine IDs and persistence remain independent of mode/profile counts. |
| View | Visual presentation/sound editor, not another engine or scheduler. |
| Controller profile | Input mapping/action policy, not a separate MIDI consumer or ownership scheme. |
| Board profile / recovery persona | Hardware adaptation / recovery entry, separate from musical workflow selection. |

Modes own top-level workflow; engines/effects own reusable sound descriptors and
specialised editing UI. Core retains HAL/watchdog/recovery, audio/TIMER5, the one MIDI
consumer and queue publication, press-time note/release pairing, voices, fixed mixer
order, clock, persistence and global safety/menu. Planned prepare/start/UI/input hooks
run in the main loop; any declared sequencer/scheduler adapter is bounded at existing
control/event granularity, never per sample or on a new clock. ISR callbacks must be
covered by [#127](https://github.com/kmplngj/Felucca/issues/127) reachability and keep
`-Os` until proven otherwise, with no allocation, formatting or storage in interrupts.

Mode IDs need their own stable namespace, independent of engine/favorite/settings-row
IDs. The planned resolver must generate deterministic registration/includes/capabilities
for all three builds and reject duplicate/unknown IDs, missing providers/defaults and
explicit dependency conflicts. Standard starts with Felucca only; installing an extra
never changes the boot default or sound catalog. Every action entry point (panel, MIDI,
controllers, editor) must reject unsupported recording/sequence starts while preserving
generic notes/CC/STOP/panic and release ownership. No implicit borrowing of engine
arenas, LCD DMA buffers or restore scratch: inactive compiled modes still cost static
RAM/flash, and a shared workspace needs target fit/alignment and stopped-lifecycle proof.

[#204](https://github.com/kmplngj/Felucca/issues/204) owns chooser/default preference,
[#205](https://github.com/kmplngj/Felucca/issues/205) the proposed Instrument pilot.
Initial selection is session-only: current Felucca restore/autosave remains its own;
nondefault pilots do not automatically restore or overwrite that copy. Remembered
startup preference needs separate versioned device settings. Live switching, saved
mode sessions and project-driven switches need later policies. This documentation
does not implement a resolver, mode, scheduler, chooser or new persistence format.

## 6. Validation and related owners

Use [BUILDING.md](../BUILDING.md#tests) and [performance.md](performance.md) for commands
and measurement policy; the table maps changes to existing harnesses, not permission
to skip applicable full-suite or real-device gates:

| Change | Existing evidence paths |
| --- | --- |
| Engine/arena/switch | Engine-specific tests, `regress.c`, `union_test.c`, `arena_test.c`, UI/descriptor tests (1.8). |
| Audio/mixer/taps | [audio_test.c](../tests/audio_test.c), [uac_test.c](../tests/uac_test.c), FX tests (2), sound goldens, target budget. |
| MIDI/clock/publication | [midi_control_test.c](../tests/midi_control_test.c) (USB/TRS clocks, ownership and panic), [midi_uart_test.c](../tests/midi_uart_test.c), UAC/editor tests and emulator event regressions. |
| Persistence/update | [storage_test.c](../tests/storage_test.c), persistence/project/upreset/old-format/fuzz tests (4), [ota_test.c](../tests/ota_test.c), package guards. |
| Panel/drawing | [input_test.c](../tests/input_test.c), UI/render/layout tests and inspected images; hardware calibration, DMA/readability remain device checks. |
| Build/platform/resources | [build_guard_test.py](../tests/build_guard_test.py), target arithmetic smoke, size-pass tests, fresh target build/map/disassembly and native guards. |

Keep source inspection, host output, static target estimates, emulator behavior and
actual FM-1 observations distinct. A documentation review claims none of the unperformed
builds, executions or hardware checks. Host tests cannot establish scan timing, nesting
deadline, LCD DMA lifetime on hardware, USB-host compatibility or update/power-loss safety.
Follow [CONTRIBUTING.md](../CONTRIBUTING.md) and report remaining device gates explicitly.

Related work stays with its existing owners:
[#112](https://github.com/kmplngj/Felucca/issues/112)/
[#113](https://github.com/kmplngj/Felucca/issues/113) for interaction/audio experiments;
[#116](https://github.com/kmplngj/Felucca/issues/116)–
[#119](https://github.com/kmplngj/Felucca/issues/119) for recovery, guards and update work
(individual [#117](https://github.com/kmplngj/Felucca/issues/117) and
[#118](https://github.com/kmplngj/Felucca/issues/118));
[#117](https://github.com/kmplngj/Felucca/issues/117)/
[#35](https://github.com/kmplngj/Felucca/issues/35) for build guards/CI. Reuse existing
capabilities and tests instead of opening duplicate feature tickets.

## 7. Checklist

Engine:

- [ ] Appended to `ENGINES[]` (with `ENG_AT()`); `NENGINES`, `ENGINE_ORDER[]`, `eng_abbr()`, `PRESET_CAT[]`,
      `N_ENGNAME[]`, `MIDI_CC_ENG[]`, protocol engine table updated; no existing number moved in any build option;
      the id below `ENG_ID_MAX` (1.1).
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
