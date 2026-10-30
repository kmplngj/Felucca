<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Experimental SMK-37 targets

The opt-in SMK build adapts Felucca to the SMK-37 Pro, SMK-37 Elite and MKE-P37.
These targets share a board adapter and have separate package, application and
loader identities. Each model still needs independent physical qualification.
The normal build, PR CI and Latest Dev continue to produce the standard FM-1
firmware. Tagged releases additionally carry experimental SMK model assets;
the FM-1 hardware attestation does not qualify those assets.

Existing work is tracked in [#192](https://github.com/kmplngj/Felucca/issues/192)
(board/model support), [#246](https://github.com/kmplngj/Felucca/issues/246)
(adoption) and [#293](https://github.com/kmplngj/Felucca/issues/293)
(fail-closed storage ownership). The older direct upstream
[PR #237](https://github.com/hugelton/Felucca/pull/237) closed unmerged after
upstream moved its HAL to a separate BSP; it is a source reference, not a
completed integration or hardware qualification of this fork.

## Build and packages

Use the toolchain and SDK from [BUILDING.md](../BUILDING.md). Board selection is
independent of the engine profile; these examples use the standard engines.

```sh
uv run --locked --group build ./build.sh --board smk37
uv run --locked --group build ./build.sh --board smk37 --model elite
uv run --locked --group build ./build.sh --board smk37 --model mke
```

| Model option | Device model | Development package |
| --- | --- | --- |
| `pro` (default) | SMK-37 Pro | `build/felucca-smk37.fwsc` |
| `elite` | SMK-37 Elite | `build/felucca-smk37-elite.fwsc` |
| `mke` | MKE-P37 | `build/felucca-smk37-mke.fwsc` |

`BOARD=smk37 MODEL=elite` is the equivalent environment selection. Unknown
boards/models and a model supplied with FM-1 fail before generation. The plain
`smk37` asset corresponds to Pro; there is no additional model named Standard.
`standard` remains the engine profile and FM-1 remains the default board.
SMK forces `FELUCCA_UART=0`; explicitly enabling it fails because PH8 is a key row.

`--release X.Y` writes `felucca-X.Y-smk37[-elite|-mke].fwsc` and a separate
`release-X.Y-smk37[-elite|-mke]/` bundle. Development identities end in `_900`;
release identities end in `_9XY`, using the selected model prefix. Product
overrides must retain that model. Each successful build produces resource and
identity sidecars, with board/model selection bound to the compiler inputs.
Scratch ELF, app and generated headers are overwritten by the next build:
preserve each model's outputs before building another.

For static checks, append `tests/target_budget_smk37.txt` to the common
`tests/target_budget.txt` and pass that combined file to `tests/target_budget.py`.
Only the different hardware scanner gets an initial SMK reference; shared DSP
budgets stay unchanged. This heuristic does not measure scan/audio deadlines.

The **Experimental SMK firmware** Actions workflow can be run manually and is
also called by tagged releases. It builds all three models as separate artifacts.
Release publication retains the existing exact-package FM-1 acceptance, while
the SMK assets and notes explicitly remain experimental. Each model carries
independent build/resource evidence; publication does not establish physical
SMK qualification. To return to ordinary development:

```sh
uv run --locked --group build ./build.sh --board fm1
uv run --locked --group build tests/run_tests.sh --ai-output
```

Unset `BOARD`/`MODEL` when using environment selection. Host and browser suites
remain FM-1 simulations; the SMK host fixtures exercise production board/storage/
update code without compiling additional target firmware in normal CI.

## Controls and limits

| Physical control | Felucca action |
| --- | --- |
| Middle keys F3–G5 | The existing 27-key panel mapping, with velocity |
| Outer ten keys | Additional notes for the selected track |
| Pads | White-key notes with velocity; top row steps 1–8 and bottom row 9–16 in grid views |
| K1 | Master volume |
| K2 / K3 / K4 | SELECT / ALGORITHM / PRESETS |
| K5–K8 | KNOB 1–4 |
| FX / SCALE / CHORD / NOTE REPEAT / PARA / GLOBE | FX / SCL / ENV / LFO / EDIT / GLO |
| PATCH / BT | HOME / SAVE |
| ARP / SEQ / SEQ PLAY / SEQ REC | ARP / SEQ / PLAY / REC |
| KNOB BANK | Open/close the menu |
| Left / right | Previous/next page or menu row |
| FADER BANK | Cycle LEVEL, PAN, reverb send, delay send for tracks 1–4 |
| Faders 1–4 | Set the selected bank after movement; no crossing pickup guarantee |
| Wheels | Selected track pitch bend and CC1/modulation |
| Both OCT buttons at startup | Hardware panel calibration |

USB MIDI is available. The SMK jack is MIDI output hardware; this adapter does
not implement TRS output or FM-1 TRS input. Bluetooth, pedal and pad aftertouch
are not qualified features. The scan samples velocity contacts once per 1.6 ms
frame; fast-strike response needs device testing. LCD and RGB pads share SPI1;
pad service drains LCD DMA and restores LCD routing before another screen write.
The adapter does not drive FM-1's PA2 backlight/matrix rail on SMK.

USR1 and USR2 retain 80 KiB each. USR3 retains its stored/wire ID but is unavailable
on SMK; writes are refused. FM-1 keeps all three slots. Project, settings, user
preset and voice-bank formats retain their native IDs and serialization.

## Storage and recovery

Back up the device and retain the manufacturer's package and recovery tools for
the exact model before trying this firmware. Physical installation, recovery and
stock return remain pending for this fork on every model.

First boot accepts only this adapter's confirmed store tag, or initializes an
entirely blank metadata area. Existing donor, stock or unknown metadata is kept:
the instrument shows **STORAGE LOCKED / FOREIGN DATA KEPT** and runs in RAM-only
mode. Saves, sample writes and later automatic persistence remain blocked.
A failed read, erase, program or verification never grants storage ownership.
The USB updater and read-only factory calibration remain available independently.

To deliberately initialize metadata, hold **KNOB BANK + FADER BANK while powering
on**. Read the warning, release the held buttons, then press **OCT+** to confirm
or **OCT−** to cancel. Confirmation erases Felucca's metadata area and commits
ownership only after verification; successful initialization restarts the device.
Keep backups: this removes previous projects, settings, presets and FM6 bank
metadata in that area. It does not erase the sample area. Interrupted or failed
initialization keeps persistence unavailable until a successful explicit retry.

| Flash range | Purpose / rule |
| --- | --- |
| `0x00000..0x03FFF` | Boot area; never written |
| `0x04000..0x9CFFF` | Application; updater only |
| `0x9D000..0xBAFFF` | Metadata; owner tag at `0xAF000`, FM6 bank at `0xB0000` |
| `0xBB000..0xBFFFF` | Loader staging/update record |
| `0xC0000..0xC1FFF` | Bluetooth pairing and factory calibration; never written |
| `0xC2000..0xE9FFF` | Two user sample slots |
| `0xEA000..0xEAFFF` | Stock mapping marker; verified release before a sample-area write |
| `0xF4000..0xFDFFF` | Stock resources; never written |
| `0xFF000..0xFFFFF` | Key data; never written |

The RAM flash driver independently rejects protected regions, even if a caller
supplies an incorrect allow-list. Loader cleanup skips metadata and samples.
The first sample write releases the stock mapping marker so stock firmware can
rebuild its mapping; this is not a promise to preserve stock custom mappings.

The Python installer accepts a native package only for the exact connected model,
requires its matching loader identity and verifies the final application identity.
The standalone SMK update loader currently leaves the display dark; use the
installer's progress and final result, and keep the USB connection intact.
It refuses unreviewed official SMK packages, including with `--force`; the FM-1
official-image exceptions do not apply to SMK. Maintained browser installer
changes belong to Felucca-WebApp; use the Python path for these experimental
packages. Do not use the FM-1 PR installer or hosted Latest Dev package for SMK.

## User test instructions — pending hardware validation

Use a trusted checkout of this candidate, uv and the documented target
prerequisites. Retain the exact commit, model, `.fwsc` SHA256 and resource report.
Use a reliable USB data cable, stable power and a host that can monitor USB MIDI
and listen to USB audio. Back up with tools compatible with the currently running
firmware before installing or initializing storage.

1. Build the selected model using the commands above. From the trusted checkout,
   run `uv run --locked --group midi tools/fm1_install.py --info` and verify the
   reported physical model. Install only its matching file, for example
   `uv run --locked --group midi tools/fm1_install.py build/felucca-smk37-elite.fwsc`
   for Elite. Expect successful completion and the exact final model/application
   identity. A different model must be refused before update staging.
2. Cold-start without holding buttons. Expect HOME and no automatic destruction
   of existing data. On an unrecognized store, expect **STORAGE LOCKED / FOREIGN
   DATA KEPT** and RAM-only operation. Play and release the lowest, middle and
   highest keys and each pad; each note must end on release. Turn K1 and K5–K8,
   move both wheels and each fader; listen and monitor MIDI for the mapped action.
3. With the transport stopped, press KNOB BANK to open the menu, turn K3 to change
   its tab and K4 to change its selected row, then press KNOB BANK to close it.
   Expect readable, stable graphics while pads flash and USB audio is active.
4. For a disposable, backed-up store only, power off and hold both BANK buttons
   while powering on. Expect the initialization warning. Release both and press
   OCT−: expect normal RAM-only startup and preserved data. Repeat, release all
   BANK/OCT buttons, then press OCT+: expect initialization and restart. A held
   OCT+ at entry must not confirm; leaving the screen alone cancels after 30 s.
5. With the matching reviewed package ready, power on holding OCT− alone. Expect
   USB rescue and successful model discovery without loading stored projects.
   Both OCT buttons instead retain hardware calibration. During an SMK loader
   update the display may be dark; require the host's successful final identity
   before disconnecting. Failed/interrupted-update and stock-return qualification
   require the model's recovery setup and remain separate pending checks.

Report model/revision/stock version, host OS, commit/artifact hash, the actions
performed and expected versus observed results. Keep the original backup and
known-good recovery package; returning to stock is not implemented by the Python
installer's SMK path.

## Source and qualification

The port adapts GPL-3.0-only SMK code by M. Geisler (genkigenki/makkuro) from
[genkigenki/Felucca at `b67312cd25bd01b097ed69388b83e86bd8449365`](https://github.com/genkigenki/Felucca/tree/b67312cd25bd01b097ed69388b83e86bd8449365).
Individual file notices are retained. Dinghy's
[v0.4 release](https://github.com/zvenson/dinghy/releases/tag/v0.4), commit
`7c31bb25c90cc11b2a94f1a10f549d0817884ac1`, is the model/asset reference;
its release notes also distinguish host tests from device qualification.
No vendor dumps, calibration data, guide artwork or restricted logo assets are
distributed here.

For **each** model, record board/revision/stock version and exact package SHA256,
then independently check boot, all keys/pads/encoders/faders/wheels, display and
RGB bus sharing, audio deadlines under USB/UAC load, storage initialization and
power-loss recovery, saves/backups, update/reconnect and return to stock. Exercise
early rescue using physical OCT− and the both-OCT calibration route. A successful
Pro run does not qualify Elite or MKE. Host fixtures and target resource checks
are separate evidence and cannot establish these physical results.
