<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Bounded native replay evidence (#662)

`tools/native_emulator_replay.py` runs an existing, unchanged native Felucca
package through the [corrected pinned external CLI](emulator-trace-prerequisite.md).
It checks repeated guest traces, PCM, modeled input delivery and terminal counts.
It produces **replay evidence**, not a symbol hotspot report. [Issue #662](https://github.com/kmplngj/Felucca/issues/662)
remains open for symbol/range attribution and the remaining profiling acceptance.

This is an opt-in host developer tool. It builds no firmware, changes no firmware
input, opens no device and downloads nothing. It requires an already built native
producer and a separately built, receipt-verified emulator inside this checkout's
ignored `build/`. See [BUILDING](../BUILDING.md) for native prerequisites and the
[performance guide](performance.md) for the distinct host, static and device evidence.

## Inputs and supported observations

The native producer must be a clean Git checkout with its matching standard,
M8Stealth build, UART enabled, 44,100 Hz / 128-frame audio halves, and
`build/resource-report.json`. The driver invokes that trusted producer's existing
`tools/build_report.py --verify` using the caller's interpreter/environment. This
rechecks source/configuration, real toolchain, ELF/disassembly and artifact evidence;
it does not compile. The existing pure `fm1_install.load_package` validator checks
package extents/CRCs and loader family without creating a MIDI transport. An emitted
package XIP window must contain the verified native BIN exactly at offset `0x120`.
The full native resource report, including source, compiler, SDK, profile, CPU2
configuration and exact ELF/BIN/FWSC hashes, is retained beside the replay summary.

The existing `emulator_trace.verify` is the emulator admission authority. Do not
copy a receipt from another checkout or alter its path/hash contract: build the
pinned external CLI in this checkout's `build/` using the prerequisite guide.
Its MIT/GPL source qualifications and unsigned local receipt limits still apply.

Two fixed inputs are supported; each starts from a fresh process and package:

| Case | Modeled input | Interval |
| --- | --- | --- |
| Held n7 key | CLI `--keys 700-1000:n7`, matrix note-key index 7 (matrix ID 21) | 700–1,000 emulated ms |
| Mixed UART | Full note-on status bytes on channels 1–4: notes 48, 55, 60, 67, velocity 100; matching note-offs | Bursts queued at 700 and 1,000 emulated ms |

The exact mixed CLI string is
`700:midi:903064913764923c64934364,1000:midi:803000813700823c00834300`.
Each 12-byte burst passes through modeled UART1 at 31,250 baud, ten bits per
byte: 320 microseconds per byte, about 3.84 ms for the burst. It is not four
simultaneous USB-MIDI or sample-aligned events. Native TIMER5 services the DMA
input and the real firmware handles the messages.

For the demonstrated clean native revision
`ce5f4f5f83abee570bdf9141e8f8ec16aaacdd88`, source review establishes CH1–4 routing
and the default ANALOG ACID / FM6 PAD / LOFI PULSE LD / DRUM KIT parts.
That routing/default-state statement is specific to this baseline. Generic reports
claim the observed channel/note/velocity argument delivery and PCM; they do not
certify that other clean forks keep those factory defaults or render four distinct parts.
Physical n7 identifies the key, not an invariant pitch after transpose/scale mapping.

The existing CLI's read-only breakpoint at the checked native `midi_note_event`
entry must show exactly eight expected `(channel, note, velocity)` tuples, with
zero-based channels and hexadecimal registers. The breakpoint comes from the
verified native disassembly, and its source signature must match the supported
three-argument function. These are entry observations before possible IRQ dispatch:
they do not count completed voice allocations, per-part renders or function calls.
A duplicate/preempted re-hit fails the fixed expectation. No symbol range lookup
or hotspot aggregation occurs.

## Reproduce

Use Linux or macOS, Python 3.11+, native build-verification prerequisites and the
pinned Rust emulator prerequisites. The native producer must retain the same build
environment that its resource verifier expects, including SDK/toolchain selectors
and generator dependencies. A source/configuration mismatch fails admission.

```sh
python3 tests/native_emulator_replay_test.py
python3 -O tests/native_emulator_replay_test.py

# Prepare build/emulator-cli/receipt.json using emulator-trace-prerequisite.md.
# /absolute/native-producer already contains its matching verified build/.
uv run --locked --group build python tests/native_emulator_replay_execution_test.py \
  --native-root /absolute/native-producer \
  --emulator-receipt build/emulator-cli/receipt.json \
  --out build/native-replay-proof
```

Select a new output name when repeating; existing paths are refused. The direct
`tools/native_emulator_replay.py` entry point takes the same arguments and runs
the same native plan. The execution test additionally damages local copies of a
real receipt and decoded image and requires their refusal. Do not run both merely
to repeat an unchanged full plan.

Each case and its matched no-input control runs **trace / plain / trace**, for
12 finite children total. Every child has 264,000,000 guest scheduling slots
(1,100 ms in this pinned model), a 60-second wall limit, a 2 MiB combined log cap,
and watched WAV/XIP file bounds. The parent polls through leader exit and pipe EOF,
refuses surviving descendant groups and kills its owned group on every terminal
path. Interruptions retain incomplete evidence. No child can establish a passed
replay solely by returning zero.

Traced runs must contain every slot in `[200000000,200004096)` exactly once,
in order: 4,096 rows, only core 0, no unknown class, and supported XIP/RAM code
windows. The row number is a scheduling slot, not a general retired count. This
one-core, unpaused recipe additionally requires its successful terminal retirement
count to equal the requested slots. Missing/malformed/extra terminal fields, halt,
empty/partial trace or WAV, inconsistent frame/IRQ counts, image mismatch, child
failure/timeout and stale emulator/native evidence fail the run. Plain children
have no T rows but must have the same complete native terminal/audio evidence.

The two traced runs must match exact trace bytes and PCM. Plain PCM and terminal
counts must match the traced run. Each no-input control must be silent; each
workload must produce nonzero PCM. A replay `summary.json` is passed only after
all four groups and final input checks pass. Raw stdout/stderr, process receipts,
trace.txt, audio.wav, xip.bin and result.json remain under each child directory.
Read the summary first. The portable tests cover parser/refusal contracts and real
failing, timeout, hidden-descendant and oversized children without native/Rust inputs.

The summary retains two traced wall durations, one interleaved plain duration and
their ratio per group. These observations include host scheduling, parent capture
and IO noise. Small or negative apparent overhead is possible for a 4,096-row
window within a long run; it is not a speedup, confidence interval, physical cycle
measurement, deadline margin or whole-chip utilization.

## Initial state and remaining limits

The pinned CLI's `--fwsc` loader performs stock-specific initialization even for
this native package. With the native package's erased USR region, it seeds stock
DX7 voice bytes at `0xEE000..0xF1FFF` and zeroed stock settings at
`0xFA000..0xFBD7F`. These lie in Felucca's reserved stock range; native settings
`0xFC000/0xFD000` and autosave `0xE5000/0xE6000` are outside that seed. The report
records this behavior. It does not claim an untouched device factory flash image.
No mutable `--flash`, `--raw-flash`, bank import or saved project is accepted.

Existing [interaction replay](interaction-replay.md) and stress definitions remain
the authorities for their host/integrated scenarios. Their direct parameter/engine
setters, RNG/master initialization, capture events and sample timelines are not
transparently supported by this CLI. The declared native cases deliberately expose
that narrower input mapping. Core 2 release or any second-core trace is refused,
even when CPU2 support is compiled in. Unknown-MMIO bring-up logs are retained;
success does not qualify other peripheral interactions.

No native optimization, firmware/RAM saving, hardware timing, physical keyboard
velocity, USB/TRS hardware behavior or browser/device timeline equivalence is
established. ELF aliases, symbol/range boundaries and execution-count aggregation
remain later work under #662. No device test is required for these tooling contracts.
