<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Native guest instruction attribution (#662)

`tools/native_hotspots.py` attributes the already captured, bounded PR733 native
replay windows to target function ranges and emulator instruction classes. It does
not execute firmware, rebuild an image or collect a new trace. It consumes the
[held-key/mixed-UART replay evidence](native-emulator-replay.md), including its
silent controls and repeated windows. The supported replay verifier is commit
`4ffca0afc71c0f347475370a5adb2c52441e47a2` from PR733.

## Reproduce with existing evidence

Use Python 3.11+, Linux/macOS build-verification prerequisites, the native
producer's original SDK/toolchain environment, and these explicit trusted roots:

```sh
python3 tests/native_hotspots_test.py
python3 -O tests/native_hotspots_test.py
uv run --locked --group build python tools/native_hotspots.py \
  --replay-root /absolute/clean-pr733-checkout \
  --proof /absolute/clean-pr733-checkout/build/native-replay-c1 \
  --native-root /absolute/native-producer \
  --out build/native-hotspots
```

The reporter itself requires a Git consumer checkout and refuses SOURCE-PINS
archive consumers before helper imports. Output must be a new directory below
this checkout's ignored `build/`, separate from all inputs. No network, device,
firmware execution or native build is requested. Existing replay evidence is
reused; do not repeat its twelve native children solely to run this analysis.

The caller must select the trusted clean PR733 verifier checkout and the clean
native producer. A saved JSON report never selects a code root. The verifier
checkout must remain at the exact supported PR733 head; relevant helper bytes
and the replay capture driver hash must match this consumer's reviewed base.
The original `emulator_trace.py verify` CLI runs in that original checkout, so its
receipt paths and ignored-output contract are preserved without relocation or
relaxed checks. The existing native resource verifier, package validator, replay
log/PCM/image functions and repeat comparisons remain the authorities.

All twelve expected saved children are checked in their fixed order: invocation,
complete process record, log hashes, parsed terminal/IRQ/audio evidence, exact
trace bytes, complete PCM and decoded app matching the verified BIN. Repeats and
silent/nonzero controls are recomputed. The capture's `passed` label and stored
comparison booleans alone cannot establish valid inputs. Native artifact/source
and original verifier context are checked again before completing the report.

These are **trusted local saved artifacts**. Their consistency checks and hashes
are not a signature, remote attestation or independent proof that a child ran.
Jointly rewritten metadata and artifacts are outside that claim. Keep the original
source/receipt contexts and their reviewed execution evidence available.

## Range and counting rules

The reporter obtains a bounded raw symbol table from the verified native ELF with
the producer's normal target-tool selection. The objdump bytes must match the
existing resource report's compiler closure. `target_frames.inventory` supplies
actual sized function ranges and alias groups; `build.disassembly_rows` supplies
instruction/data rows. No second ELF parser or registry dependency is added.
Frame-size scores, unsupported stack operations and call-chain inference are not
used as instruction-cost evidence.

- Sized function ranges are half-open: `start <= PC < end`. The end address
  belongs to a following range only if that range actually starts there.
- Aliases sharing the same address, size and section form one group with all
  names. They count each executed row once. Same names at different addresses
  remain distinct groups.
- Zero-sized code labels have no invented extent. Labels at a sized group's
  entry are listed as entry labels; a label without a containing sized function
  remains unresolved. The complete unsized inventory is retained.
- PCs must be decoded instruction starts. Mid-instruction, inline-data, `(bad)`,
  `unknown` and function-end-crossing instructions remain unresolved.
- Overlapping candidate ranges are ambiguous; the reporter never guesses the
  smallest function or duplicates a row across functions.

Any unresolved/ambiguous coverage makes the report `unavailable` and its process
exit nonzero, while preserving the explicit PC/reason/count findings. Missing or
malformed symbols and invalid saved inputs leave an incomplete report. Empty or
partial evidence never produces success. Inputs, file counts and output have
fixed bounds; no arbitrary directory traversal or trace subprocess is added.

`hotspots.json` contains four canonical groups: held-key and mixed-UART workload,
and each matched no-input control. Each group's 4,096-row window is counted once;
its second trace must independently produce the identical aggregation. It is not
summed into an 8,192-row workload. Outputs include per-range and per-class guest
instruction counts, entry-PC hits, unresolved coverage, exact window, native
identity/artifact/configuration bindings, symbol-table/tool hashes and saved input
hashes. Raw symbol output and bounded verifier process logs remain beside it.

Entry-PC hits are **not function calls**: branches can revisit an entry, and
inlined functions have no separate range. Inlined work remains in its containing
range. Class names come from the corrected pinned emulator, not from disassembler
mnemonics. No sampled guest count becomes a cycle, elapsed ISR path, static-budget
score or device utilization estimate. Saved trace/plain host wall observations
are recomputed and retain the replay guide's noise/overhead limits.

## Validation scope

Portable fixtures cover aliases, adjacent and end addresses, zero-sized labels,
overlaps, unknown/undecoded/mid-instruction PCs, crossing boundaries, malformed and
oversized tables, JSON/path/source refusals, a complete saved plan and changed
trace/log/PCM/image/process records. Saved-evidence fixtures simulate only existing
verifier boundaries; actual native evidence is checked separately with the command
above. A short manual check should compare selected trace PCs with symbol ranges,
disassembly bytes and the unchanged BIN/XIP extent.

For the demonstrated unchanged `ce5f4f5f83abee570bdf9141e8f8ec16aaacdd88` image,
the four retained PR733 windows have complete unique sized-range coverage. This
is a bounded workload/window finding, not proof that all firmware paths have
symbols. Stock-USR initialization, modeled UART serialization, source-reviewed
factory routing, one-core restrictions and unsupported host sample timelines stay
as documented in the replay guide. No firmware/RAM delta, device observation,
optimization or hardware acceptance is claimed. Broader profiling and any later
optimization qualification remain under [#662](https://github.com/kmplngj/Felucca/issues/662).
