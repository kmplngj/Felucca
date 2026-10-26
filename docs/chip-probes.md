<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Bounded developer chip probes (#699)

This first delivery is a default-off, explicit stopped test. It measures raw TIMER4
intervals around fixed kernels with interrupts enabled. No FM-1 measurements have
been collected. It establishes no physical frequency, CPU cycles, cache size/line
size, cold-cache state, isolated instruction latency or optimization benefit.

## Build and ownership

Use the normal build prerequisites in [BUILDING](../BUILDING.md). Build the exact
reviewed candidate with:

```sh
FELUCCA_PROFILE=standard FELUCCA_CHIP_PROBES=1 uv run --locked --group build ./build.sh
```

This slice supports only the standard profile (CPU2 compiled in or out). The build
refuses the probe flag with MACRO or another nonstandard profile before starting
generation or compilation. `FELUCCA_CDC=1` is required; `--release` also refuses it. The normal default
is `0`, compiling out the command, tables, scratch and kernels. No boot/main-loop
idle/playback hook exists. Keep a normal image to restore after testing.

The initial mode accepts only native TIMER4's expected free-running source/divider
and full period, nominal FS 44100 and HALF_FRAMES 128. Guards check transport
playback/count-in, pending transport or panic requests, pressed notes/buttons,
queued MIDI, active voices on any part (including release tails), an active worker,
USB audio streaming, pending updater/UBOOT requests, OTA receive/update work and
a live screen-capture session before and after every kernel. A checked busy state
refuses the run only when visible at a guard. Transient events and interrupt
interference may escape these checks. Keep all external MIDI sources disconnected
and leave the panel untouched during a run.

No interrupt, audio, worker, timer or clock state is acquired or modified. The
watchdog is fed between finite kernels. Every refusal/exit therefore has no device
state to restore. Each kernel has exactly 256 iterations, with a total raw TIMER4
budget of 2,400,000 ticks checked between kernels; there is no IRQ-off region. The
fixed iteration bound and existing watchdog remain relevant if the timer stops.
This is not a verified wall-time bound on unmeasured hardware.

All timing finishes before formatted output. Source declarations reserve a
1,024-byte RAM table, 216 bytes of sample records and a four-byte completed count;
there is a matching 1,024-byte const XIP table. These are source sizes, not linked
allocation deltas; compiler elimination, narrowing and padding can change them. Compiler/linker code, stack and total
resource deltas must be taken from the matching target artifacts, not these source
sizes. There is no NOINIT storage or RAMTEXT kernel. The code runs in normal XIP;
RAM-executed instruction isolation remains future scope.

## Target allocation evidence

Coordinator builds on 2026-10-26 at `82cd7f92645afe5ad724b3eaa87e71889fff7383`,
using JieLi Clang 4.0.1 and the pinned build inputs, measured the following linked
allocations. These are build/static results, not physical timing or stack use.

| Profile / flags | App bytes | RAM data+bss bytes | Result |
| --- | ---: | ---: | --- |
| Standard, probes off, CPU2 default | 496,148 | 62,392 | Same allocations as the unchanged base |
| Standard, probes on, CPU2 default | 498,872 | 63,624 | +2,724 app / +1,232 RAM bytes |
| Standard, probes on, `FELUCCA_CPU2=0` | 493,692 | 57,012 | Build/resource checks passed |
| MACRO, probes off | 580,204 | 62,392 | Unchanged; build/resource checks passed |
| MACRO, probes on | — | — | Link refused: XIP overflowed by 1,368 bytes |

The failed MACRO link specifically reported that section `.ram_text` would not fit
in region `XIP`; this identifies exhausted load-image space, not a probe RAMTEXT
allocation. No budget was relaxed. The explicit standard-profile guard replaces
that unsupported attempt with an early configuration refusal. Other profiles remain
unqualified. Preserve the matching logs, ELF and resource report when reproducing
these measurements; later code/toolchain/flag changes require fresh evidence.

## Kernels and protocol

The `probe caps` reply identifies protocol version 1, source commit when available,
repetitions, passes, footprint, raw deadline, enabled IRQs and unavailable clock
identity. `probe run` is the only execution command; it takes no arguments. Extra
arguments and unknown commands are refused. One command executes each kind twice:

| Kind | Kernel | Checksum |
| --- | --- | --- |
| 0 | Timer-pair/dispatch control, no kernel | `00000000` |
| 1 | Empty barrier loop, 256 iterations | `00000100` |
| 2 | Dependent uint32 add/multiply/unsigned-divide/XOR chain | `A5974C62` |
| 3 / 6 | XIP / RAM word loads, 4-byte stride | `C4650A80` |
| 4 / 7 | XIP / RAM word loads, 32-byte stride | `023B0300` |
| 5 / 8 | XIP / RAM word loads, 128-byte stride | `68865700` |

Tables contain `word[i] = uint32(i * 0x9E3779B9 + 0x01234567)`. Traversals wrap at
256 words. Every sum is uint32 modulo arithmetic. The integer chain starts with
12345, multiplies `(a + i)` by 679 modulo 2^32, divides the unsigned product by
679, then XORs with `0xA5A5A5A5`, for `i=0..255`. No zero divisors or faulting
operations occur. `cp_reference` supplies firmware comparisons; the host independently
checks the exact values above.

Success has `PROBE BEGIN version=1`, 18 ordered `PROBE SAMPLE` records and
`PROBE END complete`. Each sample supplies decimal `kind` and `pass` (0/1), and
8-digit hexadecimal `ticks`, `checksum` and `reference`. Ticks are unsigned TIMER4
end-minus-start, including dispatch, loop/control work and any interrupts. The
firmware neither scales ticks nor subtracts overhead. Kind 0 and kind 1 are separate
control observations; subtracting noisy controls can underflow or mislead.

`PROBE ERROR argument` refuses syntax. Numeric errors mean 1 unsupported timer/build,
2 busy or changed workload, 3 raw deadline exceeded, 4 checksum mismatch. Numeric
errors include the completed sample count and, when available, the last raw ticks,
checksum and reference, preserving mismatch evidence. A failed run has no complete
result. A later run starts afresh without a retained session.

The RAM initialization reads the XIP table before timing, so pass 0 is a **first
observation**, not a cold-cache sample. Pass 1 is an immediate repeated observation.
The 1 KiB footprint cannot identify cache capacity or line size. Cache state and
interference from normal IRQ code remain uncontrolled. Compare the same binary,
USB configuration and workload; inspect variation rather than selecting one low run.

## Explicit host capture

The existing four-command [health collector](diagnostics.md) keeps its allowlist
and semantics. It never executes these probes. The separate standard-library client
reuses only its exclusive POSIX serial transport and tty restoration:

```sh
python3 tools/fm1_chip_probes.py --port /dev/cu.usbmodem1234 \
  --firmware-revision FULL_INSTALLED_SOURCE_COMMIT \
  --manifest build/probe-build-manifest.json --runs 3
```

Select the exact CDC port yourself; Linux commonly uses `/dev/ttyACM…`. Close other
serial clients. The tool sends only `probe caps` and `probe run`, with 1–10 runs
(default 3), a 2-second timeout per reply and an 8 KiB response limit. It rejects
source-revision mismatches, incomplete/order/reference errors and refusals. Opening
the tty does not establish which image is installed. Device source commit plus an
operator manifest do not independently verify the installed package/hash/flags.

Supply a JSON object recording the native and Engines commits, clean/dirty input
identity, compiler/SDK versions, all build flags/profile, package and ELF SHA-256,
matching disassembly/hash and the locations of `cp_xip`, `cp_ram`, `cp_control`,
`cp_integer` and `cp_load`. Archive the actual ELF/package/disassembly beside it.
Use the target listing to establish which instructions and memory sections were
actually timed; source alone does not prove the emitted sequence. This guide does
not supply invented target addresses or a clock identity.

The fresh directory under ignored `build/chip-probes/` contains `console.raw` and
`summary.json`, including supplied manifest/hash, observed capabilities and each
raw sample. `--output` selects another new directory under this checkout's `build/`;
existing directories are refused. Partial replies and failures remain recorded.
A tty restoration failure invalidates the capture. `COMPLETE` means complete
protocol/reference capture, not a hardware timing, safety or audio qualification.

For a result sheet, retain each run's kinds 0/1 controls and all kernel samples,
first/repeated passes, minimum/maximum/range across repeated runs, exact provenance,
ambient workload and before/after health counters. Leave cold-cache measurements,
CPU frequency/cycle conversions and physical timing conclusions **unmeasured**.
If comparing a pinned fm1-emu later, retain identical ELF/inputs and separate emulator
model observations from hardware ticks; unsupported instructions/model discrepancies
must not change the expected checksums.

## Pending FM-1 user test route

Physical execution is pending and requires an explicitly authorized device session.
The agent has neither installed an image nor operated a device.

1. Prepare the reviewed probe `.fwsc` with the exact candidate/flag above, using
   [the trusted install procedure](../BUILDING.md#install); a `.bin` is not an
   install package. Record package/ELF hashes and the manifest. Boot with no keys
   held. Disconnect TRS MIDI, close DAWs, editor/MIDI senders and audio streams.
2. Start at HOME with PLAY off. Hold HOME for more than 0.7 seconds and release
   after MENU opens. Turn ALGORITHM to SYSTEM, PRESETS to ABOUT and tap OCT+;
   record the displayed version while retaining the exact installed artifact identity.
   Tap OCT− to return to rows. Select 2ND CORE with PRESETS and confirm OFF; builds
   without CPU2 omit this row. Select USB SERIAL and record its original value;
   tap OCT+ to turn it ON if needed. Tap HOME to close MENU and wait for the CDC port.
   If the worker was started earlier, reboot with its preference OFF before testing.
3. Leave HOME stopped and silent, hands off the panel, with no MIDI or audio stream.
   Let release tails finish. Run the command above against the selected CDC tty.
   Expect `COMPLETE`, three runs of 18 samples, exact reference checksums, raw ticks
   retained and `clock_identity: unavailable`. Report the actual ticks and variation;
   no specific speed, cache size or zero overhead is promised.
4. Check refusals separately: run with a held/ringing voice, while PLAY is active,
   with 2ND CORE actively running, or while a host USB audio stream is open.
   Expect error 2/INVALID and normal existing device behavior to continue. Do not
   interpret the refusal runs as valid measurements. Return to the stopped quiet
   state and repeat; expect a fresh complete run. A long release is still busy.
5. Listen for unexpected output and verify panel/PLAY responsiveness after completion
   and refusal. Compare matching pre/post health captures for crashes, lateness,
   shedding and stream errors. Stop any test workload and close the client. Restore
   USB SERIAL to its original setting and reinstall the normal image after testing.
   Report candidate/package, device version, host setup, scenario, logs and observed
   versus expected behavior. These steps do not authorize agent flashing.

## Provenance and remaining issue scope

The selected donor is [fm1-dock at e177e83e560483f419baad80511d9dd1acfdeffe](https://github.com/joakimeriksson/fm1-dock/tree/e177e83e560483f419baad80511d9dd1acfdeffe).
Its `LICENSING.md` credits `probes/` to Joakim Eriksson. The reviewed source files
and their interface each declare GPL-3.0-only, compatible with Felucca's existing
[GPL-3.0-only licence](../LICENSE). Copied instruction forms/traversal are attributed
in the native HAL/module. No assets, binaries or other donor dependencies are copied.
The source's `probe.h -> firmware/dock/hb_module.h` module dependency is replaced by
native HAL/console ownership; it is not a linked/copied dependency of this port.

| Reviewed donor path | SHA-256 |
| --- | --- |
| `probes/cycles.c` | `2b3fec3d05b5b21db755b84c009d78c4e65650503bbab2ec0e96793ba31ea4c2` |
| `probes/cache.c` | `21cf577592df150f07b18b75b3995158eda3bf615ceb4fa1f55f809f233d955a` |
| `probes/probe.h` | `24601fb60099b839050b71b222bfaa194344e7fa3147deaaf6ad2b402d90dcb7` |
| `probes/dsp.c` (reviewed, deferred) | `da4d45e8b74a7d12c2e51964d04605fb1c35a0bf810f6db689b79d2f1b9b931c` |
| `firmware/dock/hb_module.h` (reviewed, replaced) | `38fbe90335dd560a2e1d21b0022257fea00a32ede52d9600e3e16c3a21623fc2` |
| `LICENSING.md` | `b28187ed424f6587821949eb96eaeb17895d26254f7cbdf2946b55a0040fa9be` |
| `LICENSE` | `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` |

This is a first slice of [#699](https://github.com/kmplngj/Felucca/issues/699).
RAM-executed instruction kernels, exact saturation edge probes, broader footprint
sweeps, controlled cold/warm methodology, independent clock verification, pinned
fm1-emu comparison and all physical measurements remain open. Donor absolute
addresses, module loading, PC guards, IRQ-disable helpers, arbitrary RAM scans,
faulting instructions, RF/USB endpoint probes and clock writes are excluded.
