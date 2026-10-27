<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Pinned guest-trace correctness prerequisite (#662)

This optional developer check corrects the external `fm1-emu` CLI's executed-PC
trace before a native hotspot adapter can use it. It does not produce a hotspot
report. [Bounded native replay evidence](native-emulator-replay.md) adds matched
held-key/UART captures, repeat/control checks and limited wall-time observations.
[Issue #662](https://github.com/kmplngj/Felucca/issues/662) remains open for ELF
symbol attribution, broader scenario coverage, strict profiling reports and
general trace-overhead/multicore evidence.

The donor is [joakimeriksson/fm1-emu at
`eef6d957aa94d3dfa74551688d707b984b792922`](https://github.com/joakimeriksson/fm1-emu/tree/eef6d957aa94d3dfa74551688d707b984b792922).
The [pin descriptor](../tools/emulator_trace/pin.json) hashes all 31 inputs in
the selected four-crate source/manifest/notice closure. No emulator source,
firmware image or executable is vendored. The tracked
[patch](../tools/emulator_trace/retired-trace.patch) changes only the CLI:

- Capture the instruction PC and entry state after pending IRQ dispatch, then
  publish its `T` row only after `Cpu::step` succeeds.
- Decode class names through the existing core decoder, including its raw-family
  overrides. Histograms and successful-instruction tails use that same PC/class.
- Return a failing process exit status after any recorded halt, including quiet runs.

CPU execution, interrupt admission, peripheral advancement, core scheduling and
nop-slide/wild-jump guards remain upstream behavior. `T`'s first number still
identifies a scheduling slot, starting at one. It is **not a retired-instruction
counter**: paused cores and failed slots can leave gaps. `FM1_TRACE_RANGE=A:B`
selects the half-open slot window `[A,B)`. IRQ/register fields describe entry
state although publication follows retirement. The legacy `--trace` row keeps
its upstream post-step register fields.

The upstream class lookup's bounded six-byte XIP/RAM memory view is retained;
unsupported memory windows can still have class `?`. A future adapter must treat
unknown classes/coverage explicitly. This prerequisite does not validate window
syntax, reject successful empty/partial traces, add a terminal record, or certify
multi-core attribution. In particular `--steps 0` still succeeds without rows;
that is not a successful profiling capture.

## Licenses and build boundary

The root donor license is MIT, copyright 2026 Joakim Eriksson. The patch retains
MIT attribution and the [full notice](../tools/emulator_trace/LICENSE-MIT-fm1-emu.txt).
Per-file review found `crates/fm1-soc/src/usb.rs:36` explicitly declares
**GPL-3.0-only** and is unconditionally included by `fm1-soc/src/lib.rs`. Therefore
the selected CLI closure includes MIT and GPL source; the resulting combined
executable must not be described/distributed as MIT-only. Felucca's GPL text is
[LICENSE](../LICENSE). The four selected crates have only local dependencies;
no `include!`, `include_str!` or `include_bytes!` introduces other files. The
architecture-specific JIT modules are included in the pin even when inactive.
The generated ISA table is used as committed, without running corpus generators.
Rust's standard library and the host linker are external toolchain prerequisites.
No third-party firmware assets or `fm1-sid` submodule are required or fetched.

Unmodified workspace Cargo resolution requests unrelated registry dependencies
(`midir` from `fm1-live` in a clean offline environment). The helper therefore
copies only the reviewed inputs into a new ignored workspace, preserving package
version/edition/license and release `opt-level=3`, `lto=true`, while selecting only
`fm1-emu`, `fm1-core`, `fm1-isa` and `fm1-soc`. It builds offline with an empty
Cargo home. Ancestor Cargo configuration is refused, and caller flags/wrappers
are removed. Rust 1.90.0 fails upstream `if let` match guards; **Rust 1.99.1** is
the exact tested toolchain. Build-script Git identity in the isolated snapshot is
`unknown`; the source/patch/binary receipt supplies the actual identity.

## Reproduce on Linux or macOS

Prerequisites: Python 3.11+, Git, a host linker and rustup with Rust 1.99.1. Install
the toolchain separately if needed: `rustup toolchain install 1.99.1 --profile minimal`.
These commands fetch no firmware and run no device transport:

```sh
mkdir -p build/guest-trace
git clone --no-recurse-submodules https://github.com/joakimeriksson/fm1-emu.git build/guest-trace/clean
git -C build/guest-trace/clean checkout --detach eef6d957aa94d3dfa74551688d707b984b792922
python3 tests/emulator_trace_test.py
python3 -O tests/emulator_trace_test.py
python3 tests/emulator_trace_execution_test.py \
  --source build/guest-trace/clean --out build/guest-trace/proof
python3 tools/emulator_trace.py verify build/guest-trace/proof/candidate/receipt.json
```

`--cargo /absolute/path/to/rustup-managed/cargo` selects a local installation;
`RUSTUP_HOME`/`CARGO_HOME` may locate its toolchain. Existing proof/output directories
are refused: select a fresh name when repeating. The execution fixture clones
its input locally and patches that disposable clone; the input `clean` stays clean.
For a standalone corrected build, use:

```sh
git clone --no-hardlinks --no-checkout build/guest-trace/clean build/guest-trace/to-patch
git -C build/guest-trace/to-patch checkout --detach eef6d957aa94d3dfa74551688d707b984b792922
python3 tools/emulator_trace.py build --source build/guest-trace/to-patch --out build/guest-trace/cli
python3 tools/emulator_trace.py verify build/guest-trace/cli/receipt.json
```

The helper requires an exact, clean donor checkout inside this repository's
ignored `build/`; wrong/dirty/already-patched sources fail. It never downloads
source or installs dependencies itself. A failed build retains an incomplete
receipt. Verification binds reviewed upstream and effective source hashes, the
workspace adaptation and lockfile, patch/helper/pin, actual binary, compiler/Cargo
executables and logs. It detects changed retained inputs; it is an unsigned local
receipt, not independent proof of a trusted compiler or reproducible binary bytes.

## Expected evidence and remaining work

The portable test checks refusal contracts without Rust or network access. The
execution test builds matched baseline/candidate release CLIs, then runs real
synthetic guest images through their public CLI and CPU/SoC paths. The guest sets
IRQ120's vector, enable/priority nibble and software-pending latch via MMIO. At
slot 15, the unchanged binary prints interrupted PC `0x02000040`/`r_mov_i`; the
corrected binary prints actual handler PC `0x02000100`/`nop`, `irq=[1]`. Disabling
global interrupts keeps execution at `0x02000040`.

For a valid instruction followed by an unknown opcode, baseline emits two rows,
reports one retired instruction and exits zero. Candidate emits one row and
exits one. Further cases cover raw-decoder class overrides, entry register state,
quiet halt, wild jump, nop slide, a `[3,6)` window, zero slots and an identical
16-row IRQ repeat. Each subprocess has a ten-second wall-clock limit and finite
guest slots. Altered binary/source/log/compiler bindings and a second patch
application must be refused. `summary.json`, raw stdout/stderr and the candidate
receipt stay under the chosen proof directory. Upstream unit tests can also run
with `cargo +1.99.1 test --offline --locked --workspace --manifest-path
build/guest-trace/proof/candidate/source/Cargo.toml`.

These are synthetic guest instructions, not Felucca held-note/mixed workloads.
No target build, FM-1 flash, device observation, native audio comparison, timing
claim or CPU/RAM saving is established here. Firmware build inputs are unchanged;
full firmware/browser/device suites are unnecessary for this tooling-only slice.
Use [BUILDING](../BUILDING.md) and the [performance guide](performance.md) for
native build and measurement evidence when implementing the later adapter.
