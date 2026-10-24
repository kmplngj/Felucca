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
# Download/verify a successful automatic build for this PR's current base/head:
uv run --locked --group midi tools/fm1_pr.py NUMBER --automatic
# Install an already downloaded or locally built package:
uv run --locked --group midi tools/fm1_install.py build/felucca.fwsc
```

The helper uses `tools/fm1_install.py` from the trusted caller checkout. Install uv
first (`brew install uv` on macOS); the `midi` group supplies locked dependencies
automatically, as described in
[BUILDING](../BUILDING.md#test-a-pull-request-on-hardware). The maintained browser
client is **kmplngj/Felucca-WebApp**, pinned by the main-site workflow. Use the
corresponding PR/client checkout when testing: an older hosted installer does not
establish this contract. There is no automatic fallback to ROM flashing.

The application stages a loader, the installer reconnects, that loader writes,
and the installer verifies the returned application identity. An already-running
compatible loader resumes directly at the writing phase. A failed/aborted staging
session remains in rescue; staging may already have been written and cleaned up.

## Package / loader matrix

| Selected bytes | Actual accepted loader handshake | Installer |
| --- | --- | --- |
| CRC-checked current FM-1 image, exact `0x93000` flash image, supported loader heads and initial `FELUCCA-LOADER-1` literal | `ota-FM-1_900` | Python, maintained browser |
| Unmodified official V15, whole-file SHA-256 `db1642b2b6fa5c2cccb11ffd13878068bb28601678d3644049f99dc40e7edb8a` | `ota-FM-1_015` | Python, maintained browser |
| Unmodified official V16, whole-file SHA-256 `d017fb65e70aca97ee29d944470c3515a74581df5c0576bf70de917c7b2b61d5` | `ota-FM-1_015` | Python; browser pending its client update |
| Unknown loader, wrong model, crossed pair, another `FM-1_0NN` file | Refused before that loader's START/data | All |
| m-bootloader's installer (`FM-1_099`), an FM1 Open package (`FM-1_8nnnnnn`) | Refused before MIDI, with their own explanation | Python |

The custom firmware's update-record name `ota-FM-1_015` is an SPL handoff field;
the custom loader's actual handshake is `ota-FM-1_900`. A `9xx` version or matching
model alone is insufficient. Policy is checked for both resumed and newly staged
loaders. A rejected fresh handoff may already have written staging, but sends no
second-phase START/data to the incompatible loader.

M-VAVE's update loader is byte-identical in V15 and V16, so both official files
use the same handshake. A `FM-1_0NN` identity is no evidence of an official file:
modified packages already reuse `FM-1_016`. Only the pinned files are accepted.

Configured application products follow `tools/build.py` syntax; they do not rename
the fixed loader or authorize a layout. Final application identity must match.
Development builds can share that identity: retain provenance and verify ABOUT's
commit. Python `--force` is a deprecated compatibility option with no effect.
Unknown package loader families fail file preflight before MIDI discovery or an
installation prompt; the flag cannot override the classifier, CRCs or final identity.

### Return to official firmware and the boot area (#619)

Unlike Felucca's loader, M-VAVE's loader writes the whole `flash.bin`, **boot area
included**, and the flash above Felucca's app area (V16's app area ends at `0xA9000`).
Felucca's staging (`firmware/src/ota.c`, `OTA_STOCK`) therefore accepts M-VAVE's
loader only with a reviewed official image: the `flash.bin` size and UFW data CRC16
and the CRC16 of its 16 KiB boot area must match V15's or V16's, and the device's
own chip key must be the image's (`0x980F`). The hosts additionally pin each whole
file by SHA-256. Before #619, the package's boot area had to equal the device's,
so V15 was refused on a unit with V16's bootloader or m-bootloader and V16 was
refused everywhere. Now either official file installs over any boot area, and its
boot area replaces the one the unit had. Original V15 return remains a separately
validated Python/browser path; V16 return and every crossed boot-area transition
are not yet observed on our FM-1 (see [the survey](#boot-area-survey)). Package
acceptance does not prove stored-data preservation.

### Update result codes

A refused or failed update shows **UPDATE FAILED -N** on the FM-1 for 1.5 s and
Felucca continues; the Python installer then reports that the FM-1 stopped answering.
Codes −1 to −7, −15 and −16 come before anything is erased.

| Code | Meaning |
| --- | --- |
| −1, −2 | The package's UFW header or entry list could not be read or is damaged |
| −3 | No `flash.bin` or no `ota.bin` |
| −4, −6 | Reading the boot area or the loader from the host failed |
| −5 | M-VAVE's loader with a flash image that is not a reviewed official one |
| −7 | Unknown or malformed update loader |
| −8 … −12 | Staging the loader failed (erase, read, program, verify, head); staging is erased again |
| −13 | The host did not confirm; staging is erased again |
| −14 | The update record could not be written |
| −15 | Felucca's loader with a `flash.bin` that is not this board's `0x93000` |
| −16 | Official image, but this FM-1's chip key differs or cannot be read |

## Boot areas and other firmware

Felucca's loader never writes the boot area `[0, 0x4000)`, so Felucca runs with
whichever bootloader the unit has. The current static evidence:

| Boot area | Identification | What we know | Device status |
| --- | --- | --- | --- |
| M-VAVE V15 | SPL `0x3830` B, record CRC `0x71C8` | Felucca's reference platform; its `isd_config.ini` declares `SYS_CLK` 360 MHz | Felucca qualified on it |
| M-VAVE V16 (2026-10-21) | SPL `0x3898` B, record CRC `0xDCC8` | Same chip key `0x980F` and app directory at `0x4000`; its `isd_config.ini` declares `SYS_CLK` **320 MHz** (11 % below V15) | Pending: install, boot, rescue, OTA and the clock reading (#618) |
| m-bootloader 1.2 | `AC79BLID`, board `fm1` in the SPL | Keeps the rest of the boot area; checks every firmware file's CRC before starting it | Pending |

`isd_config.ini`'s declared clock is static evidence, consistent with felucca-bsp's
one 320 MHz reading after a bootloader change; whether a unit actually runs Felucca
at 320 MHz under V16's bootloader is the measurement #618 asks for. Every CPU budget
in [performance.md](performance.md) assumes 360 MHz.

### m-bootloader

[m-bootloader](https://github.com/jvitkauskas/m-bootloader) (MIT) replaces the boot
area. Felucca's installers do not install or offer it, and refuse its installer
package `FM-1_099` with an explanation. Its power-on keys are read before Felucca
starts and do not overlap with Felucca's:

| Held at power-on | Read by | Result |
| --- | --- | --- |
| PLAY | m-bootloader | Its recovery menu (also when the firmware cannot start); **Boot app** starts Felucca |
| REC | m-bootloader | ROM USB download mode for M-Flasher: no MIDI port |
| OCT− | Felucca | Early USB rescue (above) |
| OCT− and OCT+ | Felucca | Panel calibration |

The Python installer's "FM-1 not found" error mentions the PLAY/REC states. The
menu's **Wipe user data** erases the settings areas the firmware declares and lists
them first. Felucca's package declares VM `0x93000`–`0xE9000` (its sample store,
OTA staging, autosave and FM6 bank), BTIF `0xE9000`–`0xEA000` and USR
`0xEA000`–`0xFC000`: expect Felucca's stored data to go, and check the listed ranges
before confirming. Installing official V15 or V16 replaces m-bootloader with
M-VAVE's bootloader, as m-bootloader documents.

### M-VAVE FM1 Open firmware

M-VAVE's FM1 Open firmware answers the identity query as `FM1_OFFICIAL_OPEN`,
`FM1_COMMUNITY_n` or `FM-1_8nnnnnn` (V12: `FM-1_8000012`). Its updater accepts
only a package it was armed for first, which Felucca's installers do not do. The
Python installer refuses it before the confirmation prompt (exit code 6) and
explains the route: return the unit to official V15 with the FM1 Open updater
(it offers the official V15), then install Felucca. FM1 Open packages are refused
before MIDI. Arming the Open updater for Felucca packages is out of scope.

### Boot-area survey

Name a unit's boot area from a flash dump (for example FM-1 Transporter's or
M-Flasher's 1 MiB read) or a package without touching the device:

```sh
python3 tools/fm1_bootarea.py DUMP.bin
```

It reports V15/V16/m-bootloader/unknown, whether the boot records and SPL
container CRCs are intact, the chip key and the clock fields of `isd_config.ini`.
A dump of the current boot area is part of every device check below. Record per
unit: boot area, previous firmware, the transition, and the #618 clock readings.

## Boot and service ownership

`boot_policy.h` reuses the existing twelve retained bytes. Only unambiguous power-on
discards failed-boot state; mixed/unknown reset causes stay warm. The independent
CPU1 exclusion is preserved. Intentional OTA/ROM transitions clear the boot guard.
Healthy confirmation occurs after more than thirty seconds from explicit musical
readiness; a future chooser's waiting time cannot qualify unactivated workflows.

A thirty-millisecond panel-rail settle followed by a thirty-millisecond physical
OCT scan precedes persisted panel mappings, adding about 60 ms to ordinary boot.
PA2 must be driven low as an output before sampling: it supplies the key/LED
matrix rail as well as the backlight. The early path enables that rail without
initializing the LCD, then polls the normal input HAL at TIMER5's 100 us cadence.
Rescue polls USB at about 2 kHz, feeds the watchdog
and accumulates TIMER4 deltas across its roughly 179-second wrap. TIMER5/audio stay
off, leaving one USB SIE owner. Normal interrupt-driven service stays intact.
Rescue flash hooks call RAM-safe HAL operations with interrupts masked, avoiding
normal audio-dependent storage wrappers. Editor/musical MIDI cannot start the synth.

Without OTA (including flash-disabled builds), recovery selects the existing ROM
fallback. No new flash sector, settings schema, NOINIT allocation, boot stub or
firmware bank is introduced. The emulator has no physical early-rescue entry.

### Physical entry evidence and related firmware

The first PR #487 hardware report found normal startup with OCT− held, while
both-OCT calibration still worked. That later path runs after `lcd_init` has
enabled PA2; the original early check did not enable it. The original host test
assigned button bits in its input-init stub and could not detect an unpowered matrix.

The registered watch sources were compared at immutable revisions:

- [ChoralRoot boot-safety investigation](https://github.com/Quixotic7/ChoralRootFM1/blob/7d97982a7db3dad2da456a3e4d4478548b6571d9/docs/BOOT-SAFETY.md):
  documents the same failure before PA2 was enabled, then a real-device OCT− cold
  boot and both-OCT calibration after enabling it. Its v3 stub excludes the first
  30 ms from the key decision and settles each selected column for 100 us.
- [Melodee stub](https://github.com/keremimo/melodee/blob/398ada1e09d864c12f3b778a43e45c7c2a8031b8/firmware/stub/stub.c):
  explicitly enables the shared PA2 rail and uses 100 us column settling too.
  These boot-stub layouts/loaders are separate from Felucca's application rescue.
- [Ghoulbox](https://github.com/jasonpersinger/ghoulbox-fm1-dungeon-synth/blob/f23fbc593f8af29dfa01174278f08ee79155ed27/firmware/src/rescue.c),
  [Dinghy](https://github.com/zvenson/dinghy/blob/d44df7db09b98ccad2f1233b8f83f5f09c04829e/firmware/src/recovery.c)
  and [SLOOP](https://github.com/isod89/sloop-fm1/blob/4ec1ac829fd2bdf2c571ea215fb3d62477d01220/firmware/src/recovery.c):
  implement similar application rescue, but their inspected early key checks use
  the older full-frame scanner without enabling PA2 first. They do not supply a
  correction for this hardware failure. Current upstream Felucca at
  `5738617968a22b5d4c0d3470cfcc95559052f446` has no equivalent rescue entry.

Felucca reuses its own LCD HAL's existing rail-enable sequence and its normal
input scanner. `tests/rescue_input_test.c` compiles both actual HAL helpers and
the rescue-entry function against a shift-register/row model with an initially
unpowered rail, rail startup delay, row settling and timer wrap. This catches the
original omission; simulated timing is not a measured FM-1 rail-rise bound.
The corrected Felucca entry still needs the device check below.

## One combined FM-1 handoff

**Hardware validation is pending.** Fake-HAL tests compile the actual policy,
rescue loop, OTA adapter/core and USB parser/descriptors. They cover idle writes,
unknown flash, abort/erase/program failures, deliberate resets, wrap, reconnect and
the MIDI-only persona. They do not prove real SIE/host enumeration or flash hardware.

Prepare the selected transition's backups and a known-good package. Retain one exact
candidate commit/package plus the caller's Python installer revision and matching WebApp. Record hashes,
OS/browser and endpoint names; use a disposable project with known settings/sounds.

1. Install the candidate through the ordinary updater. Hold HOME to open MENU,
   release, select SYSTEM with ALGORITHM, ABOUT with PRESETS, and tap OCT+.
   Compare the displayed commit with package provenance.
2. Power off, hold OCT−, power on and release after **USB RESCUE** appears. Expect
   silence and MIDI-only enumeration. Wait more than three minutes, disconnect/
   reconnect USB, then identify through the installer. Cancelling its confirmation
   must not start an update.
3. Install the intended package from rescue with the Python helper or direct installer command.
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
readback, rollback and writer-failure qualification remain [legacy m-flasher #13](https://github.com/kmplngj/m-flasher-legacy/issues/13),
[#15](https://github.com/kmplngj/m-flasher-legacy/issues/15) and
[#16](https://github.com/kmplngj/m-flasher-legacy/issues/16).
