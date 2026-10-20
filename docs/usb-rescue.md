<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Early USB rescue and compatible update loaders

Hold **OCT−** while powering on to select early USB rescue. On an ordinary boot,
holding **OCT− and OCT+** retains panel calibration. Two incomplete warm boots
select rescue; another warm reset while rescue is active escalates to ROM USB.
Recovery has priority over optional future usage-mode selection.

Rescue starts before settings/project import, OTA staging cleanup, synth, CPU1,
audio and TIMER5. The display says **USB RESCUE**, **CONNECT INSTALLER**, and
**READY TO UPDATE**. An unknown flash chip shows **FLASH NOT SUPPORTED** and
refuses OTA writes. Audio is off; USB exposes MIDI only, without UAC or CDC.
Rescue answers with the compiled **application** identity so the installer first
stages the selected package's RAM loader. Entry and idle cause no flash writes.

## Existing installation methods

Use the same reviewed `.fwsc` as for ordinary OTA, not a raw `.bin`:

```sh
python3 tools/fm1_pr.py NUMBER --automatic
# Python backend, for a locally built package:
python3 tools/fm1_install.py build/felucca.fwsc
```

The helper uses the exact m-flasher source pinned in `tools/m_flasher.py`, with
source-manifest and executable-digest checks. The maintained browser client is
**kmplngj/Felucca-WebApp**, pinned by the main-site workflow. Use the corresponding
PR/client checkout when testing: an older hosted installer does not establish this
contract. There is no automatic fallback to ROM flashing.

The application stages a loader, the installer reconnects, that loader writes,
and the installer verifies the returned application identity. An already-running
compatible loader resumes directly at the writing phase. A failed/aborted staging
session remains in rescue; staging may already have been written and cleaned up.

## Package / loader matrix

| Selected bytes | Actual accepted loader handshake | Installer |
| --- | --- | --- |
| CRC-checked current FM-1 image, exact `0x93000` flash image, supported loader heads and initial `FELUCCA-LOADER-1` literal | `ota-FM-1_900` | Native, Python, maintained browser |
| Unmodified official V15, whole-file SHA-256 `db1642b2b6fa5c2cccb11ffd13878068bb28601678d3644049f99dc40e7edb8a` | `ota-FM-1_015` | Python, maintained browser |
| Unknown loader, wrong model or crossed pair | Refused before that loader's START/data | All |

The custom firmware's update-record name `ota-FM-1_015` is an SPL handoff field;
the custom loader's actual handshake is `ota-FM-1_900`. A `9xx` version or matching
model alone is insufficient. Policy is checked for both resumed and newly staged
loaders. A rejected fresh handoff may already have written staging, but sends no
second-phase START/data to the incompatible loader.

Configured application products follow `tools/build.py` syntax; they do not rename
the fixed loader or authorize a layout. Final application identity must match.
Development builds can share that identity: retain provenance and verify ABOUT's
commit. Python `--force` only admits an absent marker at file preflight; it cannot
override the compatibility classifier, CRCs or final identity.

Original V15 return remains a separately validated Python/browser path, outside
the native CLI's package set. Its loader can write beyond the custom app-only
region; package acceptance does not prove stored-data preservation.

## Boot and service ownership

`boot_policy.h` reuses the existing twelve retained bytes. Only unambiguous power-on
discards failed-boot state; mixed/unknown reset causes stay warm. The independent
CPU1 exclusion is preserved. Intentional OTA/ROM transitions clear the boot guard.
Healthy confirmation occurs after more than thirty seconds from explicit musical
readiness; a future chooser's waiting time cannot qualify unactivated workflows.

A thirty-millisecond physical OCT scan precedes persisted panel mappings, adding
that interval to ordinary boot. Rescue polls USB at about 2 kHz, feeds the watchdog
and accumulates TIMER4 deltas across its roughly 179-second wrap. TIMER5/audio stay
off, leaving one USB SIE owner. Normal interrupt-driven service stays intact.
Rescue flash hooks call RAM-safe HAL operations with interrupts masked, avoiding
normal audio-dependent storage wrappers. Editor/musical MIDI cannot start the synth.

Without OTA (including flash-disabled builds), recovery selects the existing ROM
fallback. No new flash sector, settings schema, NOINIT allocation, boot stub or
firmware bank is introduced. The emulator has no physical early-rescue entry.

## One combined FM-1 handoff

**Hardware validation is pending.** Fake-HAL tests compile the actual policy,
rescue loop, OTA adapter/core and USB parser/descriptors. They cover idle writes,
unknown flash, abort/erase/program failures, deliberate resets, wrap, reconnect and
the MIDI-only persona. They do not prove real SIE/host enumeration or flash hardware.

Prepare the selected transition's backups and a known-good package. Retain one exact
candidate commit/package plus the pinned CLI and matching WebApp. Record hashes,
OS/browser and endpoint names; use a disposable project with known settings/sounds.

1. Install the candidate through the ordinary updater. Hold HOME to open MENU,
   release, select SYSTEM with ALGORITHM, ABOUT with PRESETS, and tap OCT+.
   Compare the displayed commit with package provenance.
2. Power off, hold OCT−, power on and release after **USB RESCUE** appears. Expect
   silence and MIDI-only enumeration. Wait more than three minutes, disconnect/
   reconnect USB, then identify through the installer. Cancelling its confirmation
   must not start an update.
3. Install the intended package from rescue with the native helper/Python command.
   Expect staging, loader reconnection, writing and expected application return.
   Verify ABOUT again. Repeat with the matching WebApp to qualify that browser path.
4. Boot normally and check the known project/settings. On a separate ordinary boot,
   hold both OCT buttons and verify the existing calibration route; complete that
   route using the normal panel instructions.
5. Check normal USB MIDI, CDC on/off and UAC capture at 44.1/48 kHz, then four-track
   playback and panel edits. Compare sound, controls and saved data with baseline.
6. Bootloop entry, reset-in-rescue ROM escalation, interrupted-loader resume and
   genuine unknown-chip behavior need specifically prepared bench scenarios; keep
   them pending until performed. Do not corrupt startup or interrupt app writing
   on the owner's sole unit. Stock return needs separate exact-transition checks.

Report scenario, exact commits/hashes, host setup and observed versus expected
results. Use one combined candidate rather than separate firmware installations
per issue, except where the install/resume/return scenario requires a transition.

Application rescue needs intact startup/HAL/USB/RAM-flash code. ROM recovery remains
#429; SPL interpretation of record-shaped user data remains #438. Full raw-backup,
readback, rollback and writer-failure qualification remain m-flasher #13/#15/#16.
