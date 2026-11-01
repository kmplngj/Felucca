<!-- SPDX-License-Identifier: GPL-3.0-only -->
# FM-1 device control for hardware tests

`tools/fm1_control.py` provides an explicit USB-MIDI warm restart for automated
FM-1 tests. Its default action only reads device information. It is separate
from the read-only [diagnostics collector](diagnostics.md).

A warm restart runs the ordinary installed firmware again. It does not enter
UBOOT or the update loader, save the working project, install firmware or change
the bootloader. Unsaved edits can be lost. Cold-power, brownout and unresponsive
USB recovery still require their own procedures.

## Connect and identify

Connect one FM-1 running this capability by USB. Close editors, installers,
DAWs and other test clients using its MIDI ports. Use the trusted caller checkout
and its locked MIDI dependencies:

```sh
uv run --locked --group midi tools/fm1_control.py info --port Felucca --json
```

Port names must match exactly. When input and output names differ, specify
`--input` and `--output` separately. Missing or duplicate names are refused;
the tool does not choose the first substring match. A shared port name and a
matching build are selection checks, not a hardware serial-number attestation.

Older firmware without the advertised capability is refused without sending
a restart request. Keep the package provenance alongside the reported full
commit and dirty flag; a self-reported commit alone is not an independent flash
readback. With extended identity capability bit 2, JSON also records the verified
`pr` label and canonical compiled `profile` name. An empty PR label means no
verified PR association; the tool does not infer one from a branch or commit.
A profile name identifies the resolved profile, with feature overrides recorded
separately in package provenance. Older query-capable firmware uses the unchanged
six-byte request and reports both fields as JSON `null`. Firmware without the
identity capability remains unsupported by this control tool.

## Restart once and verify the return

Stop playback and recording, release every note and sustain pedal, and leave
MIDI LEARN. Close menus/dialogs and let effect tails fall quiet. Finish any update, capture or data transfer and wait for pending
settings/SLICE writes to finish. Close USB audio streams. The tool never stops
transport, releases notes or saves changes on your behalf.

```sh
uv run --locked --group midi tools/fm1_control.py restart --port Felucca --json
```

The request includes a fresh boot-scoped token and correlation ID. The firmware requires at least 100 ms without observed master-audio activity and
checks its busy state in the main loop and again before reset. It waits for actual
USB endpoint completion of the acknowledgement, rather than treating queue
insertion as transmission. A bounded timeout or changed busy state cancels the
restart. The reset is marked intentional and uses the existing CPU1-safe HAL.

The host sends the mutating request once. It closes the old connection, opens
the selected exact port pair again, and requires the same full commit, dirty
flag and version with the next boot generation. An acknowledgement alone,
reenumeration alone or a smaller uptime does not pass. A fast restart may happen
between enumeration polls; the report records disappearance separately from the
boot-generation check.

If the command times out, retain its JSON evidence and inspect the device before
another explicit invocation. A missing acknowledgement may mean the request was
not received, was cancelled or reset before the host observed it. The tool does
not retry a restart automatically.

## Transfer ownership

An editor transfer can pause while remaining resumable. The firmware therefore
keeps a conservative transfer latch after transfer commands instead of assuming
that inactivity means completion. Completing a backup does not automatically
make this latch disappear. The exclusive controlling client must explicitly
release the latch after its transfer has completed or been cancelled. This
release is separate from `restart` and never happens implicitly.

```sh
uv run --locked --group midi tools/fm1_control.py transfer-complete --port Felucca --json
```

Run this only as the exclusive owner after the transfer has completed or been
cancelled. It is a declaration of ownership completion, not a way to force an
active write through a busy guard. Then query `info` before requesting `restart`.

The protocol is intended for one cooperative controlling client. Tokens protect
against stale requests and accidental replay; they do not authenticate a host
or provide isolation against other simultaneously connected clients.

## Validation scope

Host regressions exercise the protocol and the command's refusal/reconnect
logic with simulated transports. Target reports establish linked allocations
and static guards. Neither establishes physical USB completion, power behavior,
MIDI/audio/panel operation or persistence on an FM-1. Those checks remain pending
until recorded for the exact package and scenario.
