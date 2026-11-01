<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Flash and retained-RAM capacity plan

Planning document for [#213](https://github.com/kmplngj/Felucca/issues/213). It inventories every
flash sector and retained-RAM object, estimates what the planned persistent features need, chooses
among the ways to make room, and gives each consumer an allocation or a "blocked" verdict that its
own issue can cite. It also fixes the rules every new persistent object follows.

Nothing here is implemented, with one exception: [F8](#8-follow-up-issues) ([#321](https://github.com/kmplngj/Felucca/issues/321))
adds backup ids 20 and 21, and the two gap statements below record that. No flash map change, no new flash object and
no other behavior changes with this page, and no flash or device action was taken to write it. Allocation decisions are **proposed**; they
become the plan when the page is merged, and each follow-up issue in [section 8](#8-follow-up-issues)
still needs its own review, tests and device validation. When this page and the source disagree, the
source wins and this page needs a fix.

## Provenance

| Item | Value |
| --- | --- |
| Source revision | `main` at [`a373657`](https://github.com/kmplngj/Felucca/tree/a373657123fa50118c9e31848c21821c10f89b18) (PR #304, #212 merged: PER6 settings, `FAV_ROWS` = 64) |
| Date | 2026-10-14 |
| Target build | `./build.sh` on Linux x86-64, defaults (no `FELUCCA_*` overrides; UI font `m8stealth`), JieLi Clang 4.0.1, toolchain `jieli-linux-toolchains-20260730.1`, AC79 SDK `d179b4484759423312073f5fbb232501aa491047`, selective size pass on; the build passed its own checks (`.ram_text` no calls, RAM/POOL floors, HAL boundary); warnings were not compared with a baseline |
| Section sizes | `objdump -h` / `-t` of `build/felucca.elf` (the procedure in [performance.md](performance.md#ram-and-stack)); struct sizes from a host compile of `tests/engid_test.c` / `tests/project_test.c` with `build/gen` |
| Compression numbers | `zlib` level 9 on the host over three synthetic projects (see [Compression](#compression)); not a target measurement |
| Not done | No test suite run (documentation only), no host CPU counters, no browser, no FM-1 or flash access |

Links of the form `[file:lines]` are permalinks at `a373657`; relative links name a file as a whole.
Numbers marked **(est.)** are this page's estimates, not measurements; the owning issue replaces
them with measured values when it designs the format.

The preset spare-byte count, retained-parent selection and paired-save requirements below were
checked against source [`2579e557`](https://github.com/kmplngj/Felucca/tree/2579e55791df0ccc2d72f35177526248d75cbc79).
That source review adds no new build, compression or device measurements; existing measurements
retain their dated provenance.

## 1. Summary

1. **Flash is 100% allocated.** The 79 sectors Felucca may write (plus 5 sectors of OTA staging)
   are all spoken for, and no clear reserve exists. The only large, user-trade-able block is the
   three user sample slots (60 of the 79 writable sectors, 75.9%).
2. **Retained RAM is nearly full.** `.noinit` is 15,564 of 15,696 B (132 B spare); 15,360 B of it is the
   four retained project copies. No consumer gets NOINIT. Pool spare is 32,212 B (24,020 B above the
   build's 8,192 B floor); RAM spare is 18,364 B (14,268 B above its 4,096 B floor).
3. **Device-wide state** goes into the settings object. Today a PER6 record is 2,688 of 3,840 B, but
   1,600 B of that are favourite rows for engine ids that do not exist yet. Trimming the written rows and
   adding a versioned tail gives a **960 B device-wide budget with no pool growth** ([A2](#5-allocation-table)).
4. **Per-project state** (note timing, FM6 automation, generator configuration, deep patches,
   drum overrides, Jam rows) gets one tagged **sidecar sector pair per project** (PRX), 3,840 B each.
   Carving that, and the other new objects, out of the data window needs **20 sectors, and the only
   sane source is user sample slot 3 (USR3)**. The trade is an explicit, opt-in "reclaim" action;
   nothing changes on update ([A3, A9](#5-allocation-table)).
5. **A multi-sector project format is rejected**: it doubles `proj_slot` in NOINIT (+15,360 B against 132 B
   spare), the backup staging, and every protocol size. A sidecar needs none of that.
6. **Pattern banks (#62) are blocked as specified.** Eight banks per track per project need about
   19 KB per project (est.), 50 sectors for four slots plus the autosave with A/B, more than the 40 sectors of user sample
   area that remain after USR3 is reclaimed; those 40 sectors still hold USR1 and USR2, not free space.
   It needs a variable-length bank store and a further
   capacity trade, tracked as its own design issue ([A8](#5-allocation-table)). #66 depends on it.
7. **Common rules** ([section 7](#7-common-rules)): append-only object types, one payload per sector,
   commit record last, tag-verified sidecars written before their parent, a backup id for every
   object, lazy format upgrade with an explicit downgrade statement, and writes only from the main
   loop while stopped and quiet.

## 2. Inventory

### 2.1 Flash map

The authorities are [storage.c:20-34](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/storage.c#L20-L34)
(object enum and the map comment), [`st_sector()` storage.c:64-75](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/storage.c#L64-L75)
(the address of each object), and the range guards in
[fm1_flash.h:38-58](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/hal/fm1_flash.h#L38-L58).
[extending.md section 4.1](extending.md#41-flash-map-and-deferred-save-example) summarizes the same
map for contributors. The flash part is 1 MiB (JEDEC id checked in `persist_boot`, project.c:1163).
A sector is 4 KiB; a storage object has a 32-byte commit record at +0 and up to 3,840 payload bytes
from +256 (`ST_PAYLOAD_MAX`).

Ends are exclusive. "Sectors" counts 4 KiB sectors. "Payload" is bytes used of the 3,840 B available per
sector; "ver" is the on-flash identification.

| Range | Sectors | Object (type) | Owner source | Copy policy | Payload / ver | Full backup |
| --- | ---: | --- | --- | --- | --- | --- |
| `0x97000..0x9F000` | 8 | Projects 1-4 (types 1-4) | [project.c](../firmware/src/project.c) | A/B pair per slot, 2 sectors | 3,840 of 3,840 (full); `FUNA` "FUN10", reads FUN1..FUN9 | ids 2-5 |
| `0x9F000` + `0xFE000` | 2 | User-preset FM6 patches `OBJ_UPFM6` (8), the retired FM6 bank `OBJ_FM6BANK` (7) shares the pair | [up_fm6.c](../firmware/src/up_fm6.c) | A/B, the two sectors are far apart | 3,728 of 3,840; `UPF6` ver 1 | id 9 (id 8, the old bank, imports only) |
| `0xA0000..0xDC000` | 60 | User sample slots USR1-USR3, 20 sectors (80 KiB) each: `0xA0000`, `0xB4000`, `0xC8000` | [eng_sample.c:40-60](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/eng_sample.c#L40-L60) | Single copy; header written last, CRC; an interrupted upload loses that sample | 512 B header + up to 81,408 B ADPCM; `FSMP` | ids 32-34 (header + data) |
| last sector of each slot (`0xB3000`, `0xC7000`, `0xDB000`) | (in the 60) | SLICE MAN record, only if the sample leaves it free | [slice_store.c:21](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/slice_store.c#L21) | Single copy, CRC; torn = slices lost, sample kept | 152 B; `SLM1` | id 21 (all three records, 472 B; #321). Not in ids 32-34 (outside `512 + data_len`). MAN slices are user work, not derived, so they are backed up |
| `0xDC000..0xE0000` | 4 | User preset banks 1-2 (types 5, 6): 16 slots of 192 B each | [upreset.c:48-65](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/upreset.c#L48-L65) | A/B pair per bank | 3,080 of 3,840; `UPB1`, record ver 4 / 5 | ids 6, 7 |
| `0xE0000..0xE5000` | 5 | OTA loader staging; update record at `0xE4F00` | [ota.c:24-27](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/ota.c#L24-L27) | Erased at boot if non-blank ([ota.c `ota_boot_cleanup`](../firmware/src/ota.c)) | not data space | n/a |
| `0xE5000`, `0xE6000` | 2 | Autosave `OBJ_AUTOSAVE` (9); also the staging copy for a new FM6 voice bank | [project.c:1308-1424](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/project.c#L1308-L1424) | A/B; the older copy stages the voice bank | 3,840 of 3,840; a FUN10 project | via id 0 (the live music), not as an object |
| `0xE7000` | 1 | FM6 voice bank (commit-record type 32, not an `st_load` object) | [fm6_vbank.c:24-37](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/fm6_vbank.c#L24-L37) | Single copy, staged first in the autosave's older sector, copied after the CRC passes | 3,616 B (tail from `+0xF00` kept erased); `FM6V` ver 1 | id 20 (the payload, 3,616 B; #321). Restore reuses the `FM6B` stage-and-copy path |
| `0xFC000`, `0xFD000` | 2 | Settings `OBJ_SETTINGS` (0) | [settings_persist.c](../firmware/src/settings_persist.c) | A/B | 572 B (PER4) or up to 2,688 B (PER6, 64 favourite rows); see [3](#3-settings-headroom) | id 1 |

Total Felucca-writable flash: `FL_DATA` 73 sectors (`0x97000..0xE0000`) + `FL_GLOB` 3 (`0xFC000..0xFF000`) +
`FL_AUTO`/`FL_VBANK` 3 (`0xE5000..0xE8000`) = **79 sectors (316 KiB)**, plus the 5 OTA sectors that
`FL_RANGE_OK` admits. There is **no unmapped sector** in any of those ranges.

Object types are stored in each commit record ([`st_hdr_t`, storage.c:36-42](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/storage.c#L36-L42)),
so the enum values are on flash: `OBJ_COUNT` is 10, and the voice bank's 32 is kept at or above
`OBJ_COUNT` on purpose.

### Blank destination checks (#197, narrowed in #721)

`st_save_to` skips one erase only for a genuinely fresh object: neither copy holds a
commit record of any type (the retired FM6 bank and the voice bank's staged records
share pairs) and no save of that object has been attempted since boot. Only then does
it read the destination in 256-byte chunks, and it skips the erase only after all
4,096 bytes read as `0xFF`, including header padding and unused tail. The first dirty
byte keeps the ordinary erase path; a scan read error returns a save failure before
erasing or programming. Every other destination is erased without a scan, as before
#197: the blank B beside a valid A, a reused copy, any retry after a failed or
interrupted save to the object, and a voice-bank staging in the autosave pair.

**Interrupted-erase caveat.** A sector that reads all `0xFF` after a power cut during
an earlier erase or during its first program can hold cells with too little erase or
program margin. They may read correctly at write time and drift later; the newest
copy then fails its CRC and the older copy loads, losing the latest save. A full
erase clears that state, so the skip is limited to fresh copies. A first erase or
program interrupted before a commit, leaving a sector that reads entirely `0xFF`,
followed by a reboot remains indistinguishable from a fresh copy: no commit record
or RAM marker survives, so the next first save may still skip. This includes an
interrupted first erase over data left by stock firmware in the autosave margin.
Retention in this residual case is not established. The RAM marker (`st_tried`)
covers every retry in the same boot.

The scan uses a static 256-byte `.pool` buffer (main loop only, like `st_buf`, which
already holds the new payload, including explicit-copy legacy migration), so the
`st_save_to` frame stays at the baseline 112 bytes. The [Maku source](https://github.com/okumurari2/maku/blob/64cb7e4bc426d308185baf7d577a336968632657/firmware/src/storage.c)
supplied the complete-sector scan approach; native mandatory header/payload readback
and fail-closed read handling are retained. No proactive erase is added.

Production-source simulated-NOR checks count the following complete 600-byte saves,
including current-copy selection and final readback. The baseline always erases.

| Destination state | Baseline reads / bytes / erases | This branch reads / bytes / erases | Programs (both) |
| --- | --- | --- | --- |
| Fresh object, empty A | 4 / 696 / 1 | 22 / 4,856 / 0 | 4 |
| Empty B, valid A | 5 / 1,296 / 1 | 5 / 1,296 / 1 | 4 |
| Reused A, valid A/B | 5 / 1,296 / 1 | 5 / 1,296 / 1 | 4 |
| First save of the object after a boot, valid copy | 5 / 1,296 / 1 | 6 / 1,328 / 1 | 4 |

Thus only the first save of a fresh object adds two 32-byte record reads and 4 KiB
of scan reads and avoids one erase; the first save of a used object after each boot
adds one 32-byte record read and still erases; later saves cost exactly the baseline.
These are hook-operation counts, not FM-1 durations or endurance measurements. The
hardware driver still limits each read's IRQ-off window to at most 256 bytes.
Programming still pauses interrupts; no interruption-free save or measured latency
gain is claimed. Physical save, retention, audio/panel/USB timing remain separate
qualification gates. Saved formats, sector allocations and CRC/commit ordering stay
unchanged. The [storage fixture](../tests/storage_test.c) covers every payload length,
every single dirty-byte position, another type's record in the pair, scan errors,
blank-looking copies after a failed first save, a half erase with a dead power latch
and its retry (same boot and after a reboot), torn saves, readback failures,
sequence wrap, fallback and explicit-copy migration.

### 2.2 Areas Felucca must not touch

| Range | What | Evidence | Rule |
| --- | --- | --- | --- |
| `0x0000..0x4000` | SPL, `isd_config.ini`, JLFS head | the update loader writes only `[0x4000, 0x93000)` and states the head "is never written" ([ldr_core.c:12-22](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/loader/ldr_core.c#L12-L22)); the package's flash image carries a head for the stock installer ([fm1pkg_make.py:106-127](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/tools/fm1pkg_make.py#L106-L127)) | Never written by the app or the loader |
| `0x4000..0x93000` | The firmware image (`APP_SLOT` 581,564 B incl. the SDK files); the loader rewrites it on every update | ldr_core.c:15, `LDR_APP_HI` | App-flash spare (111,124 B now) is **not** persistent-data space: every update rewrites the whole area, and the app region is read through the cipher (`fl_plain_window_init` makes only flash above `0x93000` plaintext) |
| `0x93000..0x97000` | 4 sectors between the image and Felucca's store; native loader cleanup scans their tails; external SPL scan rules remain unverified | ldr_core.c:32-36 | Not in `FL_STORE_OK`; contents on stock-flashed devices are **unverified** |
| `0xE8000..0xFC000` | 20 sectors: the stock firmware's OTA VM backup; its update record at `0xE8F00` | [fm1_flash.h:47](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/hal/fm1_flash.h#L47), [ldr_core.c:34-35](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/loader/ldr_core.c#L34-L35) | Never written. The stock-return path means stock code may read it |
| `0xFF000..0x100000` | JLFS `key_mac` entry | [fm1pkg_make.py:127](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/tools/fm1pkg_make.py#L127) | Never written (`FL_GLOB_HI`) |
| `0xE0000..0xE5000` | OTA staging | ota.c | Not data space: any non-blank byte at `0xE0000` or `0xE4F00` is erased at boot as a stale update |

Two rules follow from the update path. First, the loader protects `0x97000..0xE0000` entirely
([ldr_core.c `LDR_DATA_LO`/`LDR_DATA_HI`](../firmware/loader/ldr_core.c),
and `tests/ldr_test.c` counts any erase there as a bad range), so new objects that stay inside that
window need **no native loader or guard-window change**. Second, the external SPL has a separate
boot-time update-record scan whose exact bounds, required fields and selection rules remain
unverified. Felucca's loader cleanup examines `sector + 0xF00` for a nonzero CRC16 over bytes 2..79
and u16 `0x5441` at +6 ([ldr_core.c `ldr_session`](../firmware/loader/ldr_core.c)). Object payloads
reach that offset (a project fills the sector), so new persistent layouts must account for this
record-shaped-data exposure without treating that loader predicate as a complete SPL specification.
User-uploaded sample bytes also carry that theoretical risk; reserved headers must not add to it.

**Loader cleanup versus the SPL scan (#418).** These are two different scans, and only the first is
Felucca's. After a successful update the loader's cleanup walks the sector tails from `0x93000` to
`0xFC000` and erases a sector whose `+0xF00` record matches. It skips `0x97000..0xE0000` (user data) and,
since #418, **`0xE5000..0xE8000`**: the autosave pair `0xE5000`/`0xE6000` (a 3,840-byte payload at
`sector + 0x100` reaches `+0xF00`) and the voice bank sector `0xE7000` (also the staging copy in the
autosave's older sector). The window is exactly `FL_AUTO_LO..FL_VBANK_HI`; `loader.c` asserts that at
compile time and narrows its flash guard (`FL_RANGE_OK`) to match, so the loader cannot erase there even
by mistake. The required cleanups stay: `0xE4F00` (staging sector `0xE4000`, Felucca's record) and
`0xE8F00` (sector `0xE8000`, the stock firmware's), as do `0x93000..0x97000` and `0xE0000..0xE5000`.
The SPL's own scan is **unchanged and outside this repository**: if a valid-looking record sat at
`+0xF00` of an autosave sector, the SPL could still read it as an update request at boot. The residual
risk is therefore: objects there may not realize that shape (the voice bank keeps its tail erased), and
the autosave payload can realize it only through a crafted FM6 patch (below). The loader fix
removes the data loss on a successful update; it does not remove a boot-time SPL hazard, which would
need the shape to be unreachable (a format change, not made here) or SPL knowledge that does not exist.
Before #418 the post-update erase incidentally cleared such a crafted autosave record by destroying that
copy; it no longer does. The project slots in `0x97000..0xE0000` carry the same exposure and were never
cleaned. If the SPL honours that record shape, it does so on every boot regardless of an update; its
scan order, record priority and validated fields are undocumented.

*Can a valid project hold that record at `+0xF00`?* The record occupies autosave payload bytes
3584..3663. In a current FUN10 project those are `PROJ_FM6_OFF + 2 * 128 + 16 .. + 95`: bytes 16..95 of
**track 3's packed FM6 patch**, written by `fm6_pack` from a sanitized voice (steps, parameters, chain,
motion and the name lie elsewhere). Bytes 0 and 1 of the record (the CRC) fall on operator 0's FF and
operator 1's R1 (each limited to 0..99), bytes 6 and 7 on operator 1's L2 and L3 (also 0..99; `0x41` and
`0x54` are legal), and the other 76 bytes are free within their field ranges, so a matching record is
constructible. `tests/project_test.c` builds one, round-trips it through `fm6_unpack`/`fm6_pack` (a fixed
point, so the autosave would write it back) and `proj_pack`/`proj_import`, and checks the loader's own
classification of the packed bytes. It needs a crafted voice (the editor's patch write or an FM6 voice);
a random or hand-edited patch matches with probability about 2^-32, and a project of init or factory
patches does not. The validators were not weakened and no historical payload was rewritten. This is
distinct from `tests/ldr_test.c`, whose fixture saves an arbitrary 3,840-byte storage object with a record
at `payload + 0xE00` and so proves the loader's behavior for any object, reachable or not. The voice bank
(`FVB_INFO + FVB_LEN == 0xF00`) cannot hold one: its tail stays erased.

**Accepted UPF6 backup bytes (#438).** The current user-preset FM6 patch object (`OBJ_UPFM6`,
backup id 9) is 3,728 bytes at `0x9F000` / `0xFE000`, with its payload at `sector + 0x100`.
Payload `0xE00` is entry 30's packed byte 84 (entries numbered from zero); the following bytes
cross into entry 31's tag and packed data. `BACKUP_PUT` validates the UPF6 header and transfer
CRC, then preserves inactive-entry bytes without running the patch sanitizer over them.
A valid header with no used entries can therefore carry an entire 112-byte native-style update
record at `sector + 0xF00`, including bytes above 127. This is a distinct path from the sanitized
FUN10 voice fixture above, not a claim about an ordinary musician's voice or SPL boot behavior.

The production-source [backup fixture](../tests/backup_test.c) sends the shared
[record fixture](../tests/update_record_fixture.h) through real PUT begin/chunks/commit,
checks rejection before writes for an incorrect outer CRC, and checks exact LIST/GET export,
reimport and valid A/B copies. The [loader fixture](../tests/ldr_test.c) validates its inner CRC
with production `ota_crc16`, then checks that both UPF6 sectors survive successful and repeated
native loader sessions byte for byte with no erase. Real staging/stock records still clear,
and the autosave/voice-bank windows remain untouched. An otherwise erasable control sector
confirms the actual cleanup erases the matching fixture but preserves versions with a changed
CRC-covered byte or a changed marker and recomputed CRC. Literal mode/magic, name and staging
address in this fixture describe its bytes; they do not establish that the SPL requires,
accepts or selects them.

This adds causal host evidence without a firmware, format, validator or update-policy change.
It does not remove existing record-shaped saved bytes. A runtime save refusal remains a separate
#438 decision after evidence of the exact SPL scan and failure behavior, with explicit save-error
UX and old-object/backup compatibility. A guard in `st_save` alone would also leave the user-sample
path uncovered: sample upload/restore writes raw data through `SMP_BEGIN/WRITE/END` and bypasses
`st_save`. No device access, crafted-data upload or destructive interruption establishes SPL
behavior in these host fixtures; that qualification remains pending.

An [offline saved-raw-file survey](update-record-survey.md) reports byte coverage,
input SHA-256 and matches of this native-loader predicate without accessing hardware.
Its observations do not establish the external SPL scan or justify a runtime save refusal.

### 2.3 Retained RAM and the RAM mirrors

`.noinit` is the only region that survives a warm reset and UBOOT entry
([app.ld:10-30](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/app.ld#L10-L30)).
Its length is `0x3D50` = 15,696 B at `0x01C7C000`; the stacks and `0x01C7FD50..` (boot_info, mailbox,
vectors) lie above it.

| Object | Bytes | Address | Owner |
| --- | ---: | --- | --- |
| `fm1_crash` | 64 | `0x01C7C000` | reset diagnostics |
| `felucca_dbg` | 76 | `0x01C7C040` | [audio.c:22](../firmware/src/audio.c) diagnostics |
| `bootguard` | 12 | `0x01C7C08C` | [core.h:485](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/core.h#L485) |
| `panel` | 32 | `0x01C7C098` | learned panel table |
| `settings` | 16 | `0x01C7C0B8` | palette, low-cut, zoom |
| `proj_slot[4]` | 15,360 | `0x01C7C0C8` | [project.c:217](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/project.c#L217): 4 x 3,840 B |
| `crash_seen` | 4 | `0x01C7FCC8` | main.c |
| **used** | **15,564** | | |
| **spare** | **132** | `0x01C7FCCC..0x01C7FD50` | |

At boot, `persist_boot` fetches flash only for retained slots whose import fails. A valid retained slot
can survive a warm reset and be selected without fetching flash; `project_load` also fetches only
when retained import fails ([current boot/load paths](https://github.com/kmplngj/Felucca/blob/2579e55791df0ccc2d72f35177526248d75cbc79/firmware/src/project.c#L1118-L1176)).
A sidecar must match the parent actually selected, not assume flash always wins. Growth of a project record is multiplied by
four here; this is the reason a multi-sector project format is rejected ([4](#4-options-and-their-user-visible-cost)).

Other measured sizes that new objects add to or must avoid duplicating (`.pool` unless noted):

| Object | Bytes | Note |
| --- | ---: | --- |
| `persist_saved`, `persist_tmp`, `ed_bk_settings` | 3 x 2,688 | every byte of `persist_rec_t` growth costs 3 bytes of pool |
| `st_buf` | 3,840 | the staging copy `st_save_to` always makes ([storage.c:77, 148-149](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/storage.c#L77)) |
| `st_scan` | 256 | the fresh-copy blank scan's scratch, main loop only ([blank destination checks](#blank-destination-checks-197-narrowed-in-721)) |
| `proj_wire_u` | 3,840 | also the backup staging; `ED_BK_MAX` ([editor_backup.c:13](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/editor_backup.c#L13)) caps a backup object at this size |
| `proj_scratch` | 4,784 | decoded `project_t` |
| `up_bank` / `upf` | 6,160 / 3,728 | mirrors of flash objects (#22 would read them through XIP) |
| `chain` (`.bss`) | 13,096 | decoded copies of the four slots for the song (#20) |

Static-region budget (this build; the build fails below 4,096 B RAM, 8,192 B POOL or 100 B NOINIT spare):

| Region | Used | Capacity | Spare | Above the build floor |
| --- | ---: | ---: | ---: | ---: |
| App (`felucca.bin`) | 470,440 | 581,564 | 111,124 | n/a |
| RAM (`.data+.bss`) | 55,364 | 73,728 | 18,364 | 14,268 |
| POOL | 336,428 | 368,640 | 32,212 | 24,020 |
| NOINIT | 15,564 | 15,696 | 132 | 32 |
| RAMTEXT | 2,924 | 24,576 | 21,652 | n/a |

These differ from the [2026-10-11 snapshot](development-review-2026-10-11.md#fresh-local-measurements)
(app 495,580, POOL 327,800): that build used a different UI font, and #212 and later changes moved POOL.
Stack high-water use is not measured by the build; none of this is a stack claim.

## 3. Settings headroom

PER4 is 572 B: `persist_t` = four u32, `panel_t` (32 B), the bold word and `favorites`
(`factory[16][32]`, `user`, `filter`). A PER6 record appends `persist_ext_t` (68 B header plus
`rows` x 32 B) ([settings_persist.c:43-75](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/settings_persist.c#L43-L75)).

| Case | Bytes written | Headroom to 3,840 |
| --- | ---: | ---: |
| PER4 (no favourite on an engine id from 14) | 572 | 3,268 |
| PER6 as `settings_export_rec` writes it (64 rows, always) | 2,688 | 1,152 |
| PER6 with `rows` = highest used id + 1: 14 rows today | 1,088 | 2,752 |
| the same with about 20 more planned engines (row 34) | 1,728 | 2,112 |

Findings:

- The reader already accepts any `rows` from 1 to 64 (`persist_ext_ok`, settings_persist.c:68-75); only
  the writer always stores 64. Writing fewer rows is a writer-only change.
- **The device-bytes row has one spare byte.** `settings_dev[0..12]`, `[14..31]` are claimed
  (favorites.c, ui.c, ui_layer.c); a source search finds no use of `settings_dev[13]`. It travels in
  PER4, so a value there needs no record change and no downgrade cost.
  AUTO OFF uses bits 3–4 of its already-owned byte `[27]` for the output target;
  its historical timer codes stay in bits 0–2. It claims no additional byte or
  sector; older firmware resets a LEDS/BOTH selection to NEVER. See
  [display settings compatibility](display-idle.md#storage-and-editor-compatibility).
  MENU > DISPLAY > GRAPH (#572) uses bits 1–2 of ANIM IDLE's already-owned byte `[10]`
  (bit 0 IDLE unchanged; stored 0 = TURN, the default). It claims no additional byte;
  older firmware ignores the bits and keeps them as saved.
- A record longer than 2,688 B (`sizeof(persist_rec_t)`) is *invalid* to a firmware built from `a373657`
  (`settings_import` returns 0 for `n` beyond it), not merely "not understood". A tail that keeps the
  total at or below 2,688 B with a different extension `ver` falls into that firmware's `ext_other`
  path and is read by its PER4 block. That is why the SETX budget below is 960 B and not 1,152 B.
- Whether any released firmware already writes PER6 is **unverified** (no release listing was read for this
  page). If none has shipped, the PER6 layout can still be adjusted without a downgrade story.

## 4. Options and their user-visible cost

| # | Option | What it gives | Visible cost | Verdict |
| --- | --- | --- | --- | --- |
| O1 | **Device-wide settings extension** (SETX tail, `ver` 2) | 960 B, no pool growth | Once any SETX field is non-default the record is PER6: firmware <= 1.6 starts with default settings (the cost #212 already accepted for a favourite on id >= 14). A 1-byte value in `settings_dev[13]` has no such cost | **Adopt**, for device-wide state only |
| O2 | **Sidecar sector pair per project (PRX), tagged to its parent** | 3,840 B per project and for the autosave | 10 sectors; one more erase when a project that has sidecar content is saved; 5 new backup objects; older firmware ignores the sidecar and a re-save there makes it stale | **Adopt** (needs O5 for sectors) |
| O3 | **Multi-sector project** (FUN11, second sector in the same object) | atomic commit, 7,680 B per project | `proj_slot` doubles: +15,360 B NOINIT against 132 B spare, or retention is dropped; `proj_wire_u` / `st_buf` / `ED_BK_MAX` / backup, `PROJECT` and song-chain sizes all double; older firmware refuses every project | **Reject** |
| O4 | **Trade project slots** | 2 sectors per slot removed | Songs reference slots 0-3 (`chain_row_t.slot[]`), editor `PROJECT 1-4`, backup ids 2-5; at most 8 sectors in total | **Reject**: small gain, large loss |
| O5 | **Trade user sample slot 3** | 20 sectors (`0xC8000..0xDC000`), all inside the loader-protected window | USR3 (80 KiB, about 7.4 s of ADPCM at 22.05 kHz, [slice_store.c:7-11](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/slice_store.c#L7-L11)) is no longer available; SLICE can no longer use it; backup id 34 empties; the slot count in the editor's sample info (`ED_SMP_INFO` sends `SMP_USER_SLOTS`) drops to 2 | **Adopt as an explicit opt-in reclaim**, never on update. Firmware that predates the reclaim cannot see the opt-in: after a downgrade its sample upload or backup-id-34 restore writes across `0xC8000..0xDC000` and destroys A3-A6 (see the downgrade paragraph below the table) |
| O5b | Trade slots 2 or 1 as well | 20 more sectors each | the same, for another slot | Held back for #62 only ([A8](#5-allocation-table)) |
| O6 | **Shrink each sample slot** | 1-3 sectors per slot | truncates existing samples, `SMP_USER_SIZE` is baked into the slot layout and the info reply | **Reject** |
| O7 | **Compression** | see below | main-loop codec, flash for the codec, variable size | **Adopt only for variable-length stores** (banks), never as capacity for fixed objects |
| O8 | **Sidecar tied by a uid in the project spare bytes** instead of a content hash | tag survives re-packing and unchanged sidecars need no rewrite | needs 4 project spare bytes; the 1.8 parameter layout leaves only 1 (the dated baseline had 13) | Blocked in the current layout; see [7, rule 5](#7-common-rules) |
| O9 | **Unclaimed flash outside the windows** (`0x93000..0x97000`, `0xE8000..0xFC000`) | 4 + 20 sectors | Needs a survey of stock-flashed units and of the stock-return path; touches the loader's and guards' windows | **Not usable now**; survey proposed ([F7](#8-follow-up-issues)) |
| O10 | **Single-copy sidecar** (the SLICE pattern) | half the sectors | A torn write loses the data | Only for derived data that can be rebuilt |

**Downgrade after the USR3 reclaim (destructive, documented rather than prevented).** The opt-in marker
protects only the conversion itself. Firmware built before the reclaim does not know the marker, so a
downgrade exposes USR3 again: its normal sample upload or a backup-id-34 restore writes the whole range
`0xC8000..0xDC000` and overwrites every A3-A6 object. Because each object is versioned, tagged and CRC-checked
(common rules 3 to 5), the current firmware then reads the overwritten sectors as *absent*: it never applies
foreign bytes, and the cost is lost sidecar data (patterns, timing, automation, deep patches, the FM6 library),
not a corrupted parent project. The plan accepts this and requires F1 to (a) state it in the MENU confirmation
and the release notes that ship the reclaim, (b) have the editor warn before a backup that contains USR3-region
objects is restored on older firmware, and (c) keep a full backup of the affected objects (rule 6) as the
recovery path. If this cost is not acceptable, the alternative is to hold the reclaim back until a loader or
app-side guard can refuse older sample writes into the range ([F7](#8-follow-up-issues) surveys the windows);
that is a hardware-and-loader decision, not part of this plan.

### Compression

The project payload compresses well when little is set. Measured with `zlib` level 9 on the host over
the 3,840-byte FUN10 produced by `proj_pack` in a host build (the default project, 16 + 8 notes on two
tracks, and every step of all four tracks filled with random note/velocity/time; parameters, FM6 patches
and automation stay at their defaults in all three):

| Project | Raw | zlib |
| --- | ---: | ---: |
| default | 3,840 | 136 |
| sparse (24 notes) | 3,840 | 239 |
| dense steps (256 steps) | 3,840 | 1,041 |

A fully edited project (non-default parameters, FM6 patches, 128 automation records) was **not**
measured: an attempt with random parameter values was rejected by `proj_pack` and is not reported. These
are best cases; the contract for a fixed object stays the worst case, so compression cannot create
guaranteed room in the project or the autosave. It does suit stores that can say "full" ([A8](#5-allocation-table)).
A target codec's code size and main-loop time are unmeasured.

## 5. Allocation table

Verdicts: **FITS** (inside the stated allocation, no user trade), **FITS after A9** (needs the USR3 reclaim),
**REDUCED** (fits only at a smaller scope than the issue states), **NEEDS FORMAT** (a design the owner must
still choose), **BLOCKED** (no capacity).

### Allocations

| ID | Allocation | Where | Size | Citing issues |
| --- | --- | --- | --- | --- |
| A1 | Device byte `settings_dev[13]` | settings (PER4 block) | 1 B | #204 |
| A2 | SETX: versioned TLV tail of the settings record, kept inside the 2,688 B envelope (2,688 - 1,728 B for 34 favourite rows, [3](#3-settings-headroom)) | settings `0xFC000/0xFD000` | **960 B** total: STARTUP 16, SETLIST 96, LIKES 320 (est.), GENDEV 32, **unassigned 496** | #79, #169, #200, #162/#208 |
| A3 | PRX: per-project extension objects `OBJ_PRX0..3` (types 10-13) and `OBJ_PRXAUTO` (14) | `0xC8000..0xD2000`, pairs at `0xC8000 + 0x2000 k`; autosave pair `0xD0000` | 10 sectors; **3,840 B per project** (budget below) | #63, #64, #66 (rows), #71, #162/#208, #188 |
| A4 | DEEP: deep-patch sidecars `OBJ_DEEP0/1` (15, 16), one per user-preset bank, tag-tied to the record | `0xD2000/0xD3000`, `0xD4000/0xD5000` | 4 sectors; 16 x (4 B tag + 144 B) = 2,368 B each | #188 |
| A5 | FM6 library `OBJ_FVL0/1` (17, 18): 32 voices of 112 B each (the packed layout of `fm6_vbank.c`) | `0xD6000/0xD7000`, `0xD8000/0xD9000` | 4 sectors; 3,616 B each, 64 voices | #74 |
| A6 | KITS `OBJ_KITS` (19): editable drum kit banks | `0xDA000/0xDB000` | 2 sectors; 1,464 B asserted by #141 | #141 stage C. Unassigned until that stage is promoted |
| A7 | NOINIT | no new users | #116 may extend `bootguard` by up to 16 B; #204's session choice up to 4 B; **#410's CPU1 exclusion guard takes 8 B (`fm1_c1_guard`, `FELUCCA_CPU2=1` builds only: spare 128 -> 120 B)**; **at least 100 B stays unallocated** (enforced by the build, F9) in release and standard builds; only the opt-in `FELUCCA_CRASH_CTX=1` diagnostic build (#428, the #425 soak) adds 76 B of crash registers to `fm1_crash` (44 B spare, its own 24 B floor; refused with `--release`) | #116, #204, #410, #428 |
| A8 | Pattern-bank store | none | see the row below | #62, #66 |
| A9 | **USR3 reclaim** (the sectors for A3-A6): `0xC8000..0xDC000`, 20 of 20 sectors allocated, none in reserve while A6 is assigned | an explicit user action | 20 sectors | prerequisite of A3-A6 |

The USR3 map is the only place these objects are positioned; changing it needs a change to this page.
Object types 10-19 fit under 32 (`OBJ_FM6VB` stays at 32), so the commit-record type space has room
for 12 more.

PRX payload budget per project (bytes, ceilings; every line is an **estimate** until its owner measures):

| Chunk | Consumer | Budget | Basis (est.) |
| --- | --- | ---: | --- |
| P0 | Framing: magic, ver, parent tag, chunk directory | 48 | |
| P1 | #63 note-timing events | 1,024 | about 200 events x 5 B; the 1,024-event default of the reference implementation does not fit |
| P2 | #64 native FM6 automation | 512 | 128 records x 4 B, in addition to the 128 common records |
| P3 | #66 Jam arrangement rows | 256 | about 64 rows x 4 B (12 bits of bank selection, repeat); the project's 16-row chain stays in the FUN10 record |
| P4 | #162/#208 generator configuration | 256 | the reference implementation's configuration is 180 B (from #162) |
| P5 | #162/#208 exact heard-phrase recall | 640 | four tracks x (RNG + 64 steps x 2 B) |
| P6 | #71 per-drum overrides | 128 | 4 tracks x 8 lanes x 4 B |
| P7 | #188 deep patch per track | 576 | 4 x the largest (CZ 144 B); the other sizes are 80 B (FM TONE) and 110 B (VA) |
| P8 | #141/#168 kit selection and flags | 32 | |
| | **Allocated** | **3,472** | |
| | **Unassigned** | **368** | of 3,840 |

SETX lines: STARTUP is a boot project reference and flags (#79); SETLIST an ordered list of project slots
(#169, at most 32 entries, 96 B with names reserved out); LIKES 20 likes of 16 B (#200, est.: the reference
repository could not be read for this page); GENDEV device defaults of the generators (#162).

### Consumer verdicts

| Issue | State to persist | Scope | Size (est. unless stated) | Verdict | Allocation |
| --- | --- | --- | --- | --- | --- |
| [#62](https://github.com/kmplngj/Felucca/issues/62) pattern banks (8 per track) | steps 4 x 64 x 9 B = 2,304 B, timing 20 B and a 388 B automation store per extra bank | per project and the autosave | 2,712 B per extra bank: 1 extra = 1 sector, 3 = 3 sectors, 7 = 5 sectors per copy; with A/B and 5 objects: **10 / 30 / 50 sectors**. In RAM, 7 extra banks add 18.8 KB packed (22.4 KB decoded) against 24,020 B pool above the floor | **BLOCKED** as specified | A8: needs the design issue F6 and a further trade (O5b). 3 banks (2 extra) need 20 sectors, which is USR2 as well |
| [#66](https://github.com/kmplngj/Felucca/issues/66) Jam-to-song | rows of bank references and repeats | per project | 256 B | FITS after A9 for storage; **blocked on #62** for meaning | A3/P3 |
| [#63](https://github.com/kmplngj/Felucca/issues/63) note timing | independent onset/length events | per project | 1,024 B | REDUCED (about 200 events), FITS after A9 | A3/P1 |
| [#64](https://github.com/kmplngj/Felucca/issues/64) FM6 automation | native-field events | per project | 512 B | FITS after A9 | A3/P2 |
| [#162](https://github.com/kmplngj/Felucca/issues/162) / [#208](https://github.com/kmplngj/Felucca/issues/208) generator config and exact recall | config 180 B (from #162); phrase arrays and RNG | per project, plus device defaults | 256 + 640 B; device 32 B | FITS after A9 (project); FITS (device) | A3/P4, P5; A2/GENDEV. Not a copy of the upstream map: `0x9D000/0x9E000` is project slot 4 here |
| [#200](https://github.com/kmplngj/Felucca/issues/200) Maku likes | a list of likes | device | 320 B if a like is at most 16 B; a full 111 B parameter snapshot would not fit | FITS only if compact | A2/LIKES. A full-snapshot like needs 2 sectors: assign A6, or block |
| [#204](https://github.com/kmplngj/Felucca/issues/204) remembered startup mode | one mode id | device | 1 B | FITS | A1 (no record change); session choice A7 (4 B) |
| [#212](https://github.com/kmplngj/Felucca/issues/212) favourites / MIDI Learn | PER6 extension | device | 2,116 B written today (64 rows) | **Delivered**; 1,600 B of it are rows for ids that do not exist yet | [F2](#8-follow-up-issues) trims the written rows and opens SETX |
| [#71](https://github.com/kmplngj/Felucca/issues/71) per-drum overrides | tune/decay/character per lane | per project | 128 B | FITS after A9 | A3/P6 |
| [#141](https://github.com/kmplngj/Felucca/issues/141) editable kits (stage C) | 4 banks x 16 sounds | device | 1,464 B (from #141) | FITS after A9, conditional on stage C promotion | A6 |
| [#168](https://github.com/kmplngj/Felucca/issues/168) Yama kits, per-lane edits | kit id; later per-lane edits | per project | 32 B; edits via #71 | FITS after A9 | A3/P8, P6 |
| [#188](https://github.com/kmplngj/Felucca/issues/188) deep patches | FM TONE 80 B, VA 110 B, CZ 144 B | per track in a project; per user sound | 576 B per project; 148 B per sound | FITS after A9. The current user-preset record has 29 unclaimed packed bytes: `np` uses 0–113 of 144 and category uses 143, leaving 114–142 (the dated baseline had 32). None of the three fits it | A3/P7, A4 |
| [#74](https://github.com/kmplngj/Felucca/issues/74) FM6 library, 64 voices | 64 x 112 B | device | 7,168 B in two objects | FITS after A9 | A5 |
| [#79](https://github.com/kmplngj/Felucca/issues/79) boot project / template | a slot reference and flags | device | 16 B | FITS if the template *is* a project slot; an independent template object is **BLOCKED** (2 sectors, none free) | A2/STARTUP |
| [#169](https://github.com/kmplngj/Felucca/issues/169) setlist | an order over projects | device | at most 96 B | FITS for an order over the four slots; a setlist with its own song storage is **BLOCKED** (2 sectors per song). WaveLoop's design (USR3 plus project 4) is not transplanted | A2/SETLIST |
| [#116](https://github.com/kmplngj/Felucca/issues/116) rescue state | boot decision state | retained RAM | 0 to 16 B | FITS: reuse `bootguard`; rescue writes no flash | A7 |
| [#119](https://github.com/kmplngj/Felucca/issues/119) loader resume | none | n/a | none | No allocation. This page adds no loader window; A3-A6 stay inside the protected `0x97000..0xE0000` | n/a |
| [#28](https://github.com/kmplngj/Felucca/issues/28) build profiles | none (assets live in app flash) | n/a | none | The sector map is **identical in every profile**: a profile that omits a feature keeps and ignores that feature's objects | [rule 9](#7-common-rules) |
| [#22](https://github.com/kmplngj/Felucca/issues/22) / [#20](https://github.com/kmplngj/Felucca/issues/20) RAM mirrors | none | pool / `.bss` | they would free 13.7 KB pool and up to 12.9 KB RAM | Coordination only: PRX is read through the XIP window and held in one 3,840 B working image (est.), not mirrored in NOINIT | A3 |

## 6. What the PRX sidecar needs

Facts the design follows from (the format is F3's job):

- The autosave is a FUN10 project in `OBJ_AUTOSAVE`; `autosave_sig` ([project.c:1330-1353](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/project.c#L1330-L1353))
  hashes *values*, so a sidecar field that is not in that hash is never autosaved. Every sidecar chunk
  must add itself to the signature.
- `ed_bk_commit` ([editor_backup.c:92-104](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/editor_backup.c#L92-L104))
  re-imports and re-packs every project it restores (`proj_bound`, `proj_pack`), so the stored bytes, and
  the FNV `sum` in their last 4 bytes, can differ from the archived ones (an older parameter count is mapped
  up). **A tag that is a hash of the serialized bytes does not survive a backup restore.** The tag must be
  a hash of the musical values (the `autosave_sig` function, minus the sidecar) or another association
  that F3 defines. O8's 4-byte uid no longer fits the current project's spare bytes.
- Torn-write recovery for a pair is F3's required contract, not a property supplied by two ordinary
  `st_save` calls. Stage the sidecar before committing its parent and read only a valid matching pair,
  but also specify how the last committed pair survives retries. For example, after P0/S0, an unmatched
  S1 followed by a cut can make S1 the newest sidecar; another ordinary sidecar save may erase S0
  before either new parent commits. A parent-value tag also cannot distinguish a sidecar-only edit
  when the parent is unchanged. F3 must choose the association/generation and matching-copy retention
  rules, then prove interrupted prefixes, repeated failed-save/retry sequences and unchanged-parent
  edits. Ordering alone does not establish that every pre-parent cut leaves the old complete pair.
- A project that never had sidecar content writes no sidecar (no erase): absent means defaults. A project that
  *had* one and is reset to defaults must invalidate it, because the tag does not cover sidecar content and the
  old record would still match the unchanged parent and bring the cleared fields back after a reload. The
  writer therefore stores an explicit empty (tombstone) sidecar, or an equivalent invalidation, on that
  transition; "written once, now empty" is a state the reader must see. F3 specifies it and tests it
  (set, clear, reload).
- The current FUN10 record (1.8 parameters) has **1 spare byte** before `PROJ_MIDI_OFF`:
  the body ends at byte 3,308 and MIDI routing starts at 3,309. AFTERTOUCH's three track parameters
  use 12 of the dated baseline's 13 spare bytes. No additional four-track parameter or 4-byte UID fits.
  Nothing else should be appended to FUN10; use PRX. F3 must choose an association that fits the
  current layout rather than reserving a UID in those former spare bytes.

## 7. Common rules

Every persistent object, in this order of decision:

1. **One sector, one payload.** An object is one `st_save` payload of at most 3,840 B. More data is several
   objects, each with its own commit record, as the FM6 library does (A5). A backup object is also
   capped at `ED_BK_MAX` = 3,840 B.
2. **Types are append-only and on flash.** Add to `enum` in storage.c after `OBJ_AUTOSAVE`; keep `OBJ_COUNT`
   below 32; never renumber. Give each new type its own case in `st_sector()` *before* the generic `obj >= OBJ_UPRESET0`
   branch (which would place an appended type in the user-preset banks), and update the layout assertions in
   `tests/storage_test.c` (they assume `OBJ_UPFM6 == OBJ_COUNT - 2`, that the autosave is the last object, and
   check its sectors against every earlier type). List it in the raw store export too (`editor_backup.c`
   `ED_RAW_IDS` and its classification, `web/EDITOR_PROTOCOL.md` "Raw store export", #456); a static assert there
   fails when `OBJ_COUNT` changes.
   Keep the `FL_STORE_OK` / `FL_RANGE_OK` windows and the loader windows unchanged; an object outside the
   current windows is a hardware-and-loader decision, not a map edit.
3. **Versioning.** Every payload starts with a magic, a version and the element size and count, and a
   reader treats an unknown version, size or count as *absent* without erasing it. A writer produces the oldest
   record that holds the data ("lazy upgrade": PER4 until a PER6 field is non-default; no sidecar until a
   field is non-default). Appending is by tagged chunk; unknown chunks are preserved on re-save.
4. **Commit and recovery.** Payload first, the 32-byte record last, read back; the newest valid copy wins and
   a torn write leaves the previous copy in charge ([storage.c:136-173](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/storage.c#L136-L173)).
   A multi-object update must preserve a valid matched state at every interruption, including retries;
   sidecar-before-parent ordering alone is insufficient. Specify and test the matched-copy retention
   and transaction association under [section 6](#6-what-the-prx-sidecar-needs).
   A single-copy object (the SLICE record) is allowed only for data that can be rebuilt.
5. **Ties.** A sidecar carries a tag of its parent inside its own payload (so a backup of the payload keeps
   it), is ignored when the tag does not match, and is never applied to a different parent. See [6](#6-what-the-prx-sidecar-needs).
6. **Backup and restore.** An object has a `BACKUP_LIST` id (ids 10-31 are free except 20 and 21; the existing
   ones are 0-9 and 32-34) or it is documented as rebuildable. Restore validates content before writing, refuses a
   newer version, and satisfies rule 4's matched-pair recovery contract. Staging a sidecar and committing
   its parent last must not discard the last matching pair during a retry; restore needs the same
   interruption and unchanged-parent tests as save. INFO advertises a capability tag; older
   firmware answers rc 1 and the editor skips it. Update `web/EDITOR_PROTOCOL.md`, `tests/backup_test.c` and
   the editor tests together. A new id is listed only behind an INFO capability (a manifest whose count an
   editor does not know is refused by the in-repo reader), so `BACKUP_LIST 1` (INFO `58 01`) lists the 13 objects and the
   extended ones; the plain list stays as it was. Ids: 10-14 PRX (F3), 15-16 DEEP (F4), 17-18 FVL (F5) are
   reserved by this plan; **20 is the FM6 voice bank and 21 the SLICE records** (F8, delivered in #321); 19, 22-31 are
   free. A restore never deletes: an empty object leaves what the device has. **The two gaps this page recorded
   are closed**: neither store is rebuildable (the voice bank is the user's loaded voices; MAN slices are slices set
   by hand), so both have ids. Id 21 needs the samples (ids 32-34) restored first.
7. **Downgrade.** State for every object what firmware that predates it does: ignores it, refuses it, or
   resets (PER6 resets settings on firmware <= 1.6; a FUN10 is refused before 1.2). Silent truncation
   of stored data is not allowed. A sidecar whose parent is re-saved by older firmware becomes stale and is
   dropped by newer firmware; say so in the user-facing note.
8. **Writes.** Main loop only; transport stopped and nothing sounding, no key or button held, no editor
   transfer ([`autosave_quiet`](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/project.c#L1353-L1365),
   `settings_poll` project.c:1250-1273). An erase pauses audio and scanning for about 40 ms ([project.c:1301-1302](https://github.com/kmplngj/Felucca/blob/a373657123fa50118c9e31848c21821c10f89b18/firmware/src/project.c#L1301-L1302)). Go through `persist_pending` / `autosave_poll` / `project_save`; do not add a flash call from a
   callback, an interrupt, or a knob detent; coalesce, and keep the 60 s autosave gap. New objects that are
   written on every edit are not allowed.
9. **Profile independence.** The map does not depend on which engines, effects or modes a build includes.
   A build without a feature keeps its objects as bytes, never erases them, and never reuses the sectors.
10. **Memory.** No new NOINIT users without a measured reason that flash cannot meet, and 100 B stay
    unallocated (the build fails below that). Mirrors are read through XIP where possible and cost pool, counted per copy (settings count three).
    Report the object's bytes of flash, pool, RAM and NOINIT in the PR.
11. **Tests a new object brings:** legacy and malformed input, a torn write at every step (`tests/storage_test.c`
    style), the layout and non-overlap assertions, backup list/get/put round trip and refusal, downgrade
    behavior, the autosave signature, the stopped/idle write policy, and the loader's protected window
    (`tests/ldr_test.c`). Device checks are named as pending until run.
12. **Citations.** A consumer PR that claims capacity edits the tables in [section 5](#5-allocation-table) in the
    same PR; a feature without a row there is blocked.

## 8. Follow-up issues

Proposed (F8 and F9 are implemented: #321, #322). Each carries legacy, malformed, torn-write, backup and downgrade tests
as in rule 11.

| ID | Title | Scope |
| --- | --- | --- |
| F1 | Storage: add the USR3 reclaim and the A3-A6 object map | Enum entries 10-19, `st_sector`, layout tests, an explicit "reclaim USR3" action that requires an empty or backed-up slot and a confirmation, `SMP_USER_SLOTS` 3 to 2 at runtime for that device, SLICE and SAMPLE behavior for the reclaimed slot (USR3 stays a reserved set id that plays as empty), editor sample-info text, README/MENU copy, and the downgrade warnings of section 4 (MENU confirmation, release notes, editor warning on restoring USR3-region objects to older firmware). No consumer. |
| F2 | Settings: write only the used favourite rows and add the SETX tail | Writer trims `rows`; SETX `ver` 2 tagged chunks kept inside 2,688 B; `settings_dev[13]` for #204; downgrade statement; pool unchanged. |
| F3 | Project extension (PRX) sidecar objects | Payload format and tag (compatible with the single remaining project spare byte), pair recovery rule, the tombstone for a sidecar reset to defaults (set, clear, reload test), autosave signature, `project_save` / `autosave_poll` ordering, backup ids 10-14, `proj_slot` unaffected. |
| F4 | Deep-patch sidecar (DEEP) for user sounds | Tag to the record, 148 B entries, backup ids 15-16, behavior when a record is edited or renamed (compare `upf_tag`). |
| F5 | Native FM6 voice library (FVL), 64 voices | Two 32-voice objects, names, replace/delete, backup ids 17-18, interaction with the 32-voice bank at `0xE7000`. |
| F6 | Design a variable-length pattern-bank store (#62) | Measured capacity from real projects, encoding, "bank store full" policy, RAM residency against #20, the extra trade (O5b), song references; blocks #66. |
| F7 | Survey and classify the unclaimed flash on stock-flashed FM-1s | Read-only dumps of `0x93000..0x97000`, `0xE8000..0xFC000`, `0xFF000`; erased/used map, stock-return behavior; no write. Gate for O9. |
| F8 | Backup: add the FM6 voice bank and the SLICE records to the full backup inventory | Closes the two gaps in [2.1](#21-flash-map); independent of the rest. **Done in #321**: ids 20 and 21 behind `BACKUP_LIST 1`; the WebApp follow-up is #305. |
| F9 | Build guard: fail when NOINIT spare drops below 100 B | Done (#322): `tools/build.py` `check()` fails below `NOINIT_SPARE_MIN` = 100 B, next to the RAM/POOL floors; see [performance.md](performance.md#ram-and-stack). |

## 9. Unverified and how to check it

| Item | Status | Check |
| --- | --- | --- |
| Contents of `0x93000..0x97000`, `0xE8000..0xFC000`, `0xFF000` on real units | unverified; the repository holds no flash dump | F7 |
| Whether a released firmware writes PER6 | unverified | list the releases and settings versions |
| Consumer payload sizes | estimates from the issue texts; the Maku source could not be read by this session | each owner measures |
| Compression on edited projects; target codec cost | not measured | F6 |
| The ~40 ms erase pause | taken from the source comment | device measurement in F1/F3 |
| Wear: one extra erase per sidecar-bearing save | reasoned, not measured | F3 |
| User impact of losing USR3 | not surveyed | decide with the owner; the opt-in action limits it |
| Stack high-water, CPU | out of scope | n/a |

To redo the numbers after a change: `./build.sh`, then the `objdump -h` / `-t` snippet in
[performance.md](performance.md#ram-and-stack) for `.noinit` and the pools; the struct sizes come from
`sizeof(persist_rec_t)`, `sizeof(project_store_t)`, `sizeof(up_bank_t)` and `sizeof(upf_t)` in a host build that
includes `project.c` and `upreset.c` (for example `tests/engid_test.c`).
