<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Native analog/audio execution window (#662)

`tools/native_audio_window.py` adds one bounded audio/DSP window to the existing
[native replay](native-emulator-replay.md) and [attribution](native-hotspots.md)
evidence. It discovers a render entry in the unchanged native image, then captures
repeated workload and matched no-input windows. The original PR733 replay recipe,
receipts and historical captures remain usable without regeneration.

This first recipe supports only the source-audited clean native revision
`ce5f4f5f83abee570bdf9141e8f8ec16aaacdd88`, its verified standard/M8Stealth package
and the corrected pinned one-core external emulator. It requires a complete
retained PR733 proof from verifier revision
`4ffca0afc71c0f347475370a5adb2c52441e47a2`. These are stacked prerequisites; this
package does not make either open PR merged or close #662.

## Run with existing trusted artifacts

Use Python 3.11+, Linux/macOS, the original native producer's SDK/toolchain
verification environment and an already built, verified emulator receipt. No
firmware or emulator rebuild is requested. Select both trusted code roots
explicitly; a saved report cannot choose a helper to execute.

```sh
python3 tests/native_audio_window_test.py
python3 -O tests/native_audio_window_test.py
uv run --locked --group build python tools/native_audio_window.py \
  --replay-root /absolute/clean-pr733-checkout \
  --proof /absolute/clean-pr733-checkout/build/native-replay-c1 \
  --native-root /absolute/clean-ce5-native-producer \
  --out build/native-audio-window
```

The consumer requires a Git checkout and refuses SOURCE-PINS archives before
repository helper imports. Output must be a new ignored `build/` subdirectory,
separate from all inputs. The tool calls the existing hotspot reporter to
revalidate the full retained twelve-child proof and obtain the checked ELF symbol
inventory. It reads those saved artifacts; it does not rerun those twelve children.
The original replay verifier must remain clean at the exact supported revision,
with matching helper bytes and capture-driver hash. Its original
`emulator_trace.py verify` runs in that checkout, preserving the existing receipt
path contract. The native resource and package validators remain authoritative. Summary/receipt
rereads must match the original verified hashes before a new child can start;
rereading a changed file cannot refresh that expected digest.

## Fixed finite recipe and acceptance

Seven new emulator children each run the original 264,000,000-slot recipe
(1,100 modeled milliseconds). Each starts afresh from `--fwsc`, without a reused
raw-flash/autosave image. The held-key input is exactly `700-1000:n7`; the control
omits `--keys`. The package loader's stock-USR seeding and the unsupported host
parameter/engine setters, RNG/master initialization and sample-aligned timelines
remain as documented in the replay guide. The physical key's pitch and host/device
timing parity are not part of this recipe.

1. A discovery run logs at most sixteen `analog_render` entry observations. The
   first entry at or after slot 168,000,000 is the candidate for an 8,192-slot
   half-open window. Missing, excessive, duplicate, reordered or out-of-run
   observations fail. The audited entry ABI requires `r3=32` frames and modeled
   IRQ stack `[3]` at each reported entry.
2. A workload trace/plain/trace triplet uses that exact discovered window.
3. A no-input control trace/plain/trace triplet uses the same window and image.

Discovery breakpoints run **before pending IRQ dispatch**. They do not establish
which instruction actually executes next. Both workload traces must start at the
actual decoded `analog_render` entry after dispatch, contain only modeled IRQ
stack `[3]`, and include decoded PCs in `analog_render_1`. Every trace row,
including controls, must have complete unique attribution through the existing
sized-range/decoded-start rules. The control may follow another interrupt path;
it need not reach the same render entry or IRQ stack.

The priority label is specific to the audited source/model chain: native
`audio_init` passes priority 3 to `fm1_audio_init`; `fm1_irq_attach` encodes that
priority in the interrupt controller; the pinned SoC decodes the nibble and the
core records the dispatched priority in `irq_levels`. The corrected trace takes
its PC and IRQ stack after dispatch and emits a row only for a successful step.
The accepted actual `[3]` rows therefore support this model tag, not a physical
interrupt-latency or cycle claim. A nested stack or preempted first row fails this
recipe rather than being silently relabelled.

Repeated traces and their symbol/class aggregation must agree exactly. The
workload must produce nonzero PCM, each no-input control must be silent, and the
whole PCM/WAV observation for every new child must equal its matched original
held-key basis. Traced/plain terminal counts and decoded images must agree; the
discovery run is also compared with the workload triplet. These checks retain
the original replay parser's one-core, halt, partial-window and terminal refusals.

## Evidence, bounds and interpretation

`summary.json` records the discovered window/entry, source and native artifact
bindings, original proof and driver identities, verified symbol output and
emulator binary identity, each child's terminal/audio/image result, per-range and
per-class counts, and repeat/control comparisons. Each child retains its raw
stdout/stderr, process receipt, WAV, decoded XIP, extracted trace and result JSON.
`basis-validation/` retains the recomputed original hotspot report and verifier
logs. The summary hashes the exact saved input and new capture files.

Each emulator child has the existing 60-second deadline, combined 2 MiB log
limit, 256 KiB WAV and 1 MiB XIP bounds. The existing process-group capture owns
and cleans descendants. Seven fixed children, at most sixteen discovery entries,
an 8,192-row window, existing bounded symbol/listing inputs and a 2 MiB final
summary prevent unbounded retries or partial-success reports. A refusal leaves
available raw evidence and an incomplete summary, and returns nonzero.

Before success, the tool re-reads every new child result/process/log/trace/PCM/image
and recomputes its observations and attribution. It rechecks the unchanged native
producer, original clean verifier context and receipt, original saved input
hashes, symbol/report bytes, new capture-file hashes and consumed helper/driver
bytes. These are consistency checks on **trusted unsigned local artifacts**, not
a signature, independent execution attestation or protection against jointly
rewritten sources and metadata.

Per-range counts describe this partial window. Entry-PC hits are not calls;
inlined work remains in its containing range. Instruction classes come from the
pinned emulator. Trace/plain host wall ratios are small, noisy scheduling and IO
observations, not a speedup, physical cycles, deadline margin or utilization. The
window need not cover a complete ISR or render call. No firmware/RAM change,
optimization, mixed-workload extension or real-device qualification is claimed.

Portable fixtures exercise discovery/actual-dispatch separation, malformed and
bounded windows, missing DSP work, unknown/ambiguous decoding, controls on another
IRQ path, changed saved outputs, basis/PCM/image/source/helper/driver refusals,
reused repeat comparisons and early cached-helper refusal. Actual acceptance
also requires the seven-child command above, with a short manual trace PC versus
ELF/disassembly/BIN/XIP check. #662 remains open for further profiling and any
subsequent optimization/hardware acceptance.
