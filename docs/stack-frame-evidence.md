<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Observed target entry frames

After a successful target build, use its matching checkout, environment and
toolchain/SDK to verify the existing resource report and optionally export an
informational frame inventory:

```sh
python3 tools/build_report.py --verify build/resource-report.json \
  --frame-output build/stack-entry-frames.json
```

This command does not compile firmware or contact a device. The existing verifier
checks source/configuration/artifact freshness and reconstructs symbols/listing
from the ELF before the optional analysis runs. A failed verification produces no
new frame output. Output must stay inside `build/`, outside `build/gen/`; it cannot
overwrite the report, its artifacts or its inputs, including filesystem aliases.
An older output can remain after a failed command: inspect its binding before
using it. No existing resource-report format or build guard changes.

The JSON binds the verified resource report, ELF, listing, symbol table and
configuration by SHA-256 and retains build identity and stack reservations.
Those identify its inputs; they do not turn reservations into measured usage.

For each sized function in `.text`, `.ram_text` or `.c1_text`,
`tools/target_frames.py` reads the contiguous entry sequence of explicit register
saves and constant negative SP adjustments. `observed_entry_local_bytes` and
`observed_entry_save_bytes` describe that sequence. Supported ordinary register
saves count four bytes per register. `own_entry_bytes` is their sum only when the
function's listing boundaries and stack operations pass the supported syntax.
The prologue and other observed stack operations remain visible for inspection.

An unsupported/dynamic SP operation, allocation outside the entry sequence,
incomplete listing, overlapping boundary or undecoded data/instruction produces
`own_entry_bytes: null` with reasons. A leaf with a complete boundary and no stack
allocation can have an observed zero. Unsupported functions, zero-sized symbols,
ASM entries and unknown sections are never silently assigned zero. Exact aliases
with the same address/size share one record; partial overlaps remain unsupported.

Direct calls include the decoded relative target; register-indirect or unsupported
calls have an unresolved target. Outgoing branches remain separate observations:
the tool does not infer tail-frame release or add any callee frame. It does not
resolve callbacks or replace the source ISR callback/count contracts owned by
`tools/size_fns.py`. No transitive closure, recursive/reentry bound or maximum path
is computed.

The native ISR wrappers save 28 bytes at entry, while a fatal-vector stub plus
common assembly save contributes 4 + 100 bytes before its C handler. These are
manual assembly contracts to inspect separately: their zero-sized labels and
multiple entry points are not ordinary C function boundaries. CPU1 entry also
switches stack banks. Do not infer any of those costs from a zero or missing C
frame record.

The inventory is not a fit gate, stack high-water measurement, live peak or spare
margin. It does not combine startup ancestry, nested audio/TIMER5 interrupts,
fault contexts, hardware stack banks or callees. Host compiler frames are not
substitutes for these target observations. Keep reservations unchanged while
addressing those separate questions under [#21](https://github.com/kmplngj/Felucca/issues/21).

Portable causal checks require no target tools:

```sh
python3 tests/target_frames_test.py
python3 -O tests/target_frames_test.py
uv run --locked --group build python tests/build_report_test.py
```

Fixtures cover entry allocation/saves, unresolved calls, tail observations,
aliases, malformed/missing evidence and unknown SP forms. The report CLI fixture
checks successful export, refusal to overwrite verified inputs and refusal to
export after stale-input verification fails. Its target commands are simulated;
it does not establish native target or FM-1 acceptance.
