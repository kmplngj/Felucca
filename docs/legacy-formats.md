<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Stored formats, legacy conversions and the supported schema

Inventory for [#456](https://github.com/kmplngj/Felucca/issues/456) (remove legacy firmware migrations while keeping
stored data recoverable) and handover for its WebApp companion [#457](https://github.com/kmplngj/Felucca/issues/457).
It lists every historical stored format the firmware still reads or converts, where that happens, what it becomes,
which fixtures cover it, and whether it can be on a device that was updated from a released version. It then proposes
the supported current-schema contract and the conversion rules and fixtures the web editor needs.

**Rollout order (owner's decision):** inventory and raw export first (this page and the raw store export, protocol
commands 82/83); historical readers are removed only after the web editor's download, migrate and upload workflow
(#457) is available. **Nothing on this page removes or changes a reader, a converter or the way stored data loads.**
When this page and the source disagree, the source wins and this page needs a fix.

| Item | Value |
| --- | --- |
| Source revision | refreshed against `main` at `6379cf4` (2026-10-21), including the opt-in MACRO profile (#503) |
| Raw recovery path | `STORE_LIST` / `STORE_GET` (82, 83; INFO `59 01`): [EDITOR_PROTOCOL.md "Raw store export"](../web/EDITOR_PROTOCOL.md#raw-store-export-82-83-456), `firmware/src/editor_backup.c` `ed_raw_handle` |
| Flash map and capacity | [flash-capacity.md](flash-capacity.md) (#213), allocations A2 (SETX, #315) and A3 (PRX, #316) |
| Related | #299 (retired sounds), #300 (project codec), #310 (backup kinds), #422 (engine ids), #455 (settings model) |

"Released" below means a version named in the source comments (upstream 0.x to 1.6.1, which this fork builds on).
This repository has no release tags, so a version-to-format mapping is taken from those comments and is marked
"(source comment)"; where a comment names only development builds, the format is marked as such.

Flash survives firmware updates: the update loader never erases the user-data window `0x97000..0xE0000`, the settings
pair `0xFC000/0xFD000` or (since #418) the autosave/voice-bank sectors `0xE5000..0xE8000`
([flash-capacity.md 2.2](flash-capacity.md#22-areas-felucca-must-not-touch)). So any format a device once wrote stays
there until that object is written again, through any number of updates. Projects are also kept in `.noinit` RAM
(`proj_slot`), which survives a warm reset; RAM copies are derived from flash at power-on.

## 1. Storage objects

Every object below is a payload behind a 32-byte commit record (`storage.c` `st_hdr_t`: `FELU`, type, copy, seq, len,
payload CRC-32, header CRC-32), A/B copies, the newest intact copy wins (`st_current`). The raw store export lists
them by type in this order.

| Type | Object | Payload (current) | Reader on boot / load | Backup id (what it exports) |
| --- | --- | --- | --- | --- |
| 0 | settings | PER4 572 B, PER6 672..2688 B | `project.c persist_boot` -> `settings_persist.c settings_import` | 1: re-exported from RAM (`settings_export_rec`) |
| 1..4 | project slots | FUN10 3840 B | `project.c proj_fetch` -> `proj_import` | 2..5: the RAM slot re-packed as FUN10; a slot it cannot read lists 0 B |
| 5, 6 | user preset banks | `UPB1` 3080 B | `upreset.c up_boot` -> `up_bank_check` | 6, 7: the RAM mirror (a bank of another shape: empty; PHYS MODEL 4 / PERC records already migrated) |
| 7 | retired FM6 patch bank | `FM6B` 3472 B (read only) | `up_fm6.c upf_boot` (once, while type 8 is missing) | 8: always empty |
| 8 | user presets' FM6 patches | `UPF6` 3728 B | `up_fm6.c upf_boot` | 9: the RAM copy |
| 9 | autosave | FUN10 3840 B | `project.c autosave_boot` -> `proj_import` | none (id 0 is the live music, re-packed) |
| 32 | FM6 voice bank (`0xE7000`, payload at +224) | `FM6V` 3616 B | `fm6_vbank.c fvb_boot` / `fvb_valid` | 20: from flash |

Outside the commit-record store: the user sample slots (`FSMP` version 1, header 480 B + ADPCM, `eng_sample.c
smp_user_scan`; backup ids 32..34 export header + data from flash) and the SLICE records (`SLM1`, 152 B in each slot's
last sector, `slice_store.c`; backup id 21 rebuilds them from the slices in use). Neither has an older version or a
firmware conversion, so neither is in the legacy inventory; both are already exported as stored bytes (samples) or
reproducibly (slices).

## 2. Legacy inventory

Columns: **identify** (what the reader matches), **size** (stored bytes), **path** (file:function that reads or
converts), **becomes** (the result), **fixtures** (host tests that build or read it), **on a device?** (can an
updated device still hold it).

### 2.1 Projects (types 1..4; the autosave, type 9, is always FUN10)

All formats: u32 magic, u32 size (= stored length), ..., u32 FNV-1a of the preceding bytes last. Entry point
`project.c proj_import` -> `proj_import_any` (FUN7..FUN10: `proj_unpack`; FUN5/FUN6: `proj_import_old`;
FUN1..FUN4: `proj_from_v4` .. `proj_from_v1`), then always `proj_engines_ok`, `proj_fm4`, `proj_perc`; callers add
`proj_bound` (`proj_fetch`, `project_load`, `autosave_boot`, `ed_bk_commit`). `project_restore_runtime` runs
`proj_drums_to_part`, `proj_phys`, `proj_fm4`, `proj_perc` again (idempotent) and handles `PROJ_DEF_SOUND` /
`PROJ_DEF_KEEP` presets (`proj_legacy_drums`). The result is the runtime `project_t`; a save writes FUN10.

| Format | Identify | Size | Path | Becomes | Fixtures | On a device? |
| --- | --- | ---: | --- | --- | --- | --- |
| FUN1 | `FUN1` 0x46554E31, one instrument, 53 params (P_E0 45), 27 globals | 688 | `proj_from_v1` | track 1 from it (by count); tracks 2..4 power-on sounds (`PROJ_DEF_SOUND`), no steps; `proj_phys`, `proj_grid`, `proj_fm6_init`, G_RTYPE ROOM | `tests/project_test.c` | yes, from 0.5 beta and before (source comment) |
| FUN2 | `FUN2`, 4 tracks x 53 params, track 4 the GM drum part (`parts` 0) | 2552 | `proj_from_v2` | by count; `proj_drums_to_part` (track 4 -> DRUM, `PROJ_DEF_KEEP`, level/reverb from G_DRLVL/G_DRREV); `proj_phys`, `proj_grid` | `project_test.c` | yes, until 0.9 (source comment) |
| FUN3 | `FUN3`, 57 params (P_E0 49, the SLICER) | 2584 | `proj_from_v3` | as FUN2 | `project_test.c`, `fm4_div0_test.c` | yes, 0.9 .. 1.0 (source comment) |
| FUN4 | `FUN4`, 69 params (P_E0 61, the matrix), `phys` byte | 2680 | `proj_from_v4` | as FUN3, `phys` kept | `project_test.c` | only from 1.0 development builds (source comment) |
| FUN5 | `FUN5`, 69 params, 10-byte steps (the grid), 40 B lane reserve per track, no chain | 3352 | `proj_import_old` | by count, steps flags `& 3` (x1), chain defaults, `proj_drums_to_part`, `proj_phys`, init patches | `project_test.c`, `persistence_test.c`, `robust_test.c` | unverified ("read only" in the source; no release named) |
| FUN6 | `FUN6`, FUN5 + 36 B chain (`chain_v9_t`) | 3388 | `proj_import_old`, `song_chain.c chain_from_v9` | as FUN5, chain rows -> sections | `backup_test.c`, `motion_test.c`, `ratchet_test.c`, `ui_test.c` | yes, before FUN7 (source comment; 1.0 era) |
| FUN7 | `FUN7`, serialized: np at byte 66 (89 before the chord keys, 91), biased byte params, 9-byte steps, chain v9, 260 B motion (64 x 4 B) | 3388 | `proj_unpack` (v7), `proj_motion_v9`, `proj_motion_ids`, `chain_from_v9` | by count; init FM6 patches; G_RTYPE ROOM if out of range; motion ids moved with P_E0 | `tests/old_pack.h`, `fun10_test.c`, `project_test.c`, `backup_test.c` | yes, before 1.0 (source comment) |
| FUN8 | `FUN8`, FUN7 + 4 x 128 B FM6 patches at name - 512; np 91 | 3584 | `proj_unpack` (v8) | by count (DRUM lane levels 100 %); its patches | `old_pack.h`, `fun10_test.c`, `backup_test.c` | yes, 1.0.x (source comment) |
| FUN9 | `FUN9`, FUN8 + 64 B; np 99 (DRUM lane levels) | 3648 | `proj_unpack` (v9) | by count (LFO 2 SYNC OFF, TRIG NOTE, POL BI, QUANTIZE ON, SPREAD 0), nudges 0 | `old_pack.h`, `fun10_test.c`, `backup_test.c` | yes, 1.1 (source comment) |
| FUN10 np 103 | `FUNA` 0x46554E41, byte 66 = 103 (before SPREAD) | 3840 | `proj_unpack` (v10), `core.h params_by_count` | SPREAD 0, engine values and their motion ids up by one (then by seven) | `fun10_test.c` | only from 1.2 development builds before SPREAD (source comment) |
| FUN10 np 104 | `FUNA`, byte 66 = 104 | 3840 | as above | INSERT OFF, filter TYPE LP, ENV SYNC OFF; engine values / motion ids up by seven | `fun10_test.c`, `insert_test.c` | yes, 1.2 .. 1.4 (source comment) |
| FUN10 np 111 | `FUNA`, byte 66 = 111 = P_COUNT | 3840 | `proj_unpack` | **current** | all project suites | current writer |
| (retained RAM) | a `.noinit` slot holding a shorter older record inside 3840 B | n/a | `proj_import_any` (size word < 3840) | as its format; RAM only, refilled from flash otherwise | `project_test.c`, `fun10_test.c` | after a warm reset across an update |

Conversions inside any project format (applied on every import; the stored record keeps what it holds until it is
saved again):

| Rule | Identify | Path | Becomes | Fixtures |
| --- | --- | --- | --- | --- |
| GM drum part | `parts` (byte 63) != NPART (FUN1..FUN6, any pre-1.0 record) | `proj_drums_to_part`; runtime `proj_legacy_drums` | track 4 DRUM kit 0, LEVEL/REV from G_DRLVL/G_DRREV, PAN MUTE LEN DIV SWING GATE SLICER kept, arp/scale defaults | `project_test.c`, `engid_test.c`, `ui_test.c` |
| PHYS MODEL 2 = DUST | `phys` (byte 64) 0 and a PHYS track | `proj_phys` -> `eng_phys.c phys_legacy` | MODAL bowed values | `project_test.c`, `ui_test.c` |
| PHYS MODEL 4 = DRUM | `phys` < 2, PHYS track with E0 = 4 | `proj_phys` -> `core.h drum_from_phys` | DRUM engine, preset 0, E values mapped (`e[7] >> 5` -> KIT, KICK from e[6]) | `project_test.c`, `motion_test.c` |
| Old drum notes as grid | FUN1..FUN4 DRUM tracks | `proj_grid` -> `eng_drum.c step_to_grid` | lane notes -> lane hits | `project_test.c` |
| DIGITAL (engine 1) | track engine byte 1 | `proj_fm4` -> `fm4_convert.c fm4_convert`, `eng_fm6.c fm6_pack` | FM6 with the converted patch as the track's own, preset `FM4_TO_FM6`; motion on EDIT (>= P_E0) and OP ENV (`P_FM1_ATK..P_FM4_LEVEL`) dropped | `fm4_test.c`, `fm4_div0_test.c`, `project_test.c` |
| SAMPLE PERC (SET 4) | SAMPLE track with E0 = 4 | `proj_perc` -> `core.h drum_from_perc` | DRUM default kit (`DRUM_KIT_E`), preset 0; motion on EDIT dropped | `project_test.c`, `ui_test.c` |
| Retired DRUM kits | KIT 1..3 (HAND CYM H+CYM, after 1.0.4) | `proj_bound` / restore -> `params.c param_fit`, `eng_drum.c DK_PLAYS` | 66, 10, 77 | `drum_test.c`, `ui_test.c`, `editor_test.c` |
| FM6 SLOT bank slots | SLOT 8..34 (1.0..1.0.2 B1..B27) or 9..40 (1.4.1 B1..B32) | `param_fit`, `eng_fm6.c fm6_adopt` | 8 (OWN); the patch is the project's own (FUN8+; FUN7 and older: init voice) | `fm6bank_test.c`, `persistence_test.c`, `backup_test.c` |
| SAMPLE / GRAIN aliases | SET / SRC 1 (TRANH), 4 (PERC) | `params.c enum_orig`, `sound.c preset_orig` | play PIANO (value kept) | `ui_test.c` |
| Reverb type | G_RTYPE was G_DRCH (pre-FUN7) | `proj_rtype_room` | 0 ROOM | `project_test.c` |
| Unavailable engine (#212) | engine id < 64 the build lacks, including MACRO id 14 on standard/reduced profiles | `proj_engines_ok`, `engines.c ENG_NONE` | kept as stored, plays nothing (not a conversion; keep) | `engid_test.c`, `backup_test.c` raw MACRO fixture |

The merged opt-in [MACRO profile](macro-engine.md#persistence-and-compatibility) uses stable engine id **14**,
models 0..47 and presets 0..50 without changing FUN10's magic, size or parameter count. A project carrying MACRO is
therefore CURRENT even on a profile that cannot play it. The same rule applies to a CURRENT `UPB1` container holding
a MACRO preset: its stored engine id and values remain the source of truth. Earlier experimental three-model builds
cannot represent models 3..47; this is an engine-content limitation, not a new project container schema.

### 2.2 User presets (types 5, 6; records inside a `UPB1` bank)

A bank (`upreset.c up_bank_t`): u32 `UPB1` 0x31425055, u16 record size 192, u16 slots 16, 16 records. A bank of another
magic, record size or count reads as **empty** (`up_bank_check` zeroes the RAM mirror; flash is kept). A record
(`up_rec_t`, 192 B): used 0xA5, ver, engine, np, name[12], values (144 B), note[16], flags[16].

| Record | Identify | Path | Becomes | Fixtures | On a device? |
| --- | --- | --- | --- | --- | --- |
| ver 1 | int16 values; PHYS MODEL 2 meant DUST | `up_valid`, `up_values` -> `phys_legacy` | MODAL bowed | `upreset_test.c` | yes, before 1.0 (source comment) |
| ver 2 | int16 values (note pattern) | `up_values`, `up_params` -> `params_by_count` | by count | `upreset_test.c` | yes, since 1.0 |
| ver 3 | int16 values, drum grid pattern | `up_grid` | by count, grid | `upreset_test.c` | yes (grid era) |
| ver 4 / 5 | byte-packed values (+64), category at byte 143; 5 = grid | `up_value`, `up_cat_of` | **current** (np = P_COUNT) | `upreset_test.c`, `robust_test.c` | current writer |
| np 53..104 | `np` < P_COUNT (111) | `params_by_count` | by count, new parameters at defaults | `upreset_test.c`, `fun10_test.c` | yes |
| ver > 5 or invalid | `up_valid` fails | kept as inert bytes in the bank | not listed (EMPTY slot) | `backup_test.c` ("future record version") | from later firmware |
| PHYS MODEL 4 | engine PHYS, E0 = 4 | `up_migrate` (RAM mirror, at boot and `UP_PUT`) -> `drum_from_phys` | DRUM; **written back** at the bank's next write | `upreset_test.c` | yes |
| SAMPLE PERC | engine SAMPLE, E0 = 4 | `up_migrate` -> `drum_from_perc` | DRUM default kit; written back as above | `upreset_test.c` | yes, before 1.0.3 |
| DIGITAL | engine 1 | kept as stored; every load converts (`ui.c fm4_apply`, `fm4_convert`); lists count it as FM6 (`up_engine`) | FM6 sound with its own patch | `upreset_test.c`, `fm4_test.c` | yes, before 1.0 |
| category | ver 1..3 have none | `up_to_v4` on rename / category set (a write) | ver 4 / 5 | `upreset_test.c` | yes |
| FM6 patch link | FM6 record + `UPF6` entry whose `upf_tag` (FNV-1a of the record without its name) matches | `up_fm6.c upf_get` | its patch; no match: SLOT F n factory, OWN init voice (pre-1.0.3 behaviour) | `fm6bank_test.c`, `backup_test.c` | yes |

### 2.3 FM6 patch stores (types 7, 8, 32)

| Object | Identify | Size | Path | Becomes | Fixtures | On a device? |
| --- | --- | ---: | --- | --- | --- | --- |
| Retired FM6 patch bank (type 7) | `FM6B` 0x42364D46, ver 1, 27 slots | 3472 | `up_fm6.c upf_boot` (only while no valid type 8) -> `upf_migrate`; backup PUT id 8 -> `upf_migrate` | the B-slot patches of FM6 user presets whose stored SLOT is 8..34 and have none; written as type 8 into the sector that does not hold the bank's newest copy | `persistence_test.c`, `backup_test.c`, `fm6bank_test.c` | yes, 1.0 .. 1.0.2, until type 8's second save erases its sector |
| User presets' FM6 patches (type 8) | `UPF6` 0x36465055, ver 1, 32 slots | 3728 | `upf_boot`, `upf_valid` | current | `fm6bank_test.c`, `backup_test.c` | since 1.0.3 |
| FM6 voice bank (type 32) | `FM6V` 0x56364D46, ver 1, 32 voices | 3616 | `fm6_vbank.c fvb_boot`, `fvb_valid` | current | `backup_test.c`, `fm6bank_test.c` | since 1.4.1 |

### 2.4 Settings (type 0)

Entry point `settings_persist.c settings_import` (boot: `persist_boot`; restore: `ed_bk_commit`). It normalizes the PER4
block in place and applies it to the runtime (`settings`, `panel`, `favorites`, `settings_ml`, `settings_dev`).

| Format | Identify | Size | Becomes | Fixtures | On a device? |
| --- | --- | ---: | --- | --- | --- |
| PER1 | `PER1` 0x50455231, magic + palette + panel | 40 | panel moved, low-cut / zoom 0, bold 0, no favourites | `settings_test.c` | yes, upstream early (source comment) |
| PER2 | `PER2`, + low-cut, zoom | 48 | bold 0, no favourites | `settings_test.c` | yes |
| PER3 | `PER3`, + bold | 52 | no favourites | `settings_test.c`, `ui_test.c` | yes |
| PER4 | `PER4` 0x50455234, + favourites (16 rows x 32 B, user, filter) | 572 | **current** (written while every favourite is below engine id 14) | all settings suites | current writer, firmware up to 1.6 |
| PER5 | `PER5`, PER4 + MACRO's row | 604 | that row -> engine 14 | `settings_test.c`, `backup_test.c` | historical experimental MACRO branch (#27); the merged MACRO profile does not write it |
| PER6 ver 1 | `PER6` 0x50455236, PER4 + extension (ver 1, rows 1..64, ml 32, dev 32) | 672..2688 | **current**, including MACRO favourites in row 14 (a distinct row from PER4's MIDI LEARN map) | `settings_test.c`, `engid_test.c`, `backup_test.c` | this fork after #212; written by the merged MACRO profile when a factory favourite uses id 14 |
| PER6 other ext | `PER6`, extension version or counts unknown | <= 2688 | read by its PER4 block (rows 0..13, map, device bytes); written back as this firmware's record at the next save | `settings_test.c` | from later firmware |

Field-level migrations inside the PER4 block (all in `settings_import`, all on every boot):

| Field | Rule | Becomes |
| --- | --- | --- |
| palette | an old id below 20 (`gfx.c palette_from_stored`) | the tagged id |
| bold | not a HOLD tag (`panel.c hold_from_stored`) | HOLD default 0.4 s (the old font weight kept until written) |
| zoom | not a LEDS tag (`panel.c leds_from_stored`) | LEDS DIM |
| dev[29] STYLE | 2 (retired PIXEL) / unknown | LINE / FLAT |
| dev[28] CLICK etc. | a 2-bit field of 3 | 0 (default) |
| dev[27] SCREEN OFF | > 7 | 0 |
| dev[11] LIST category | > 8 | 0 |
| dev[0..9], [12] CUSTOM | flag bit 0 clear | colours cleared |
| favourites row 1 (DIGITAL) | `FM4_TO_FM6` | stars on the FM6 presets; row cleared |
| favourites SAMPLE preset 4 (PERC) | `drum_from_perc` rule | DRUM preset 0 starred; bit cleared |
| panel | `PANEL_MAGIC` | the learned panel table (**calibration**, device-specific) |

The standard profile also preserves PER6 favourite rows for unavailable engines when settings are re-exported.
PER5 remains LEGACY input. A CURRENT PER6 containing MACRO favourites remains CURRENT on every current profile;
raw export does not migrate PER5, normalize the PER4 prefix, or discard a future PER6 extension.

### 2.5 Backup archives (web/fm1backup.js, not flash)

Archives of 11 objects (before FM6), 12 (1.0 .. 1.0.2: id 8 the FM6 bank) and 13 (1.0.3+: id 9), optionally ids 20/21
behind `LIST 1`. `BACKUP_PUT` converts on restore: projects FUN6..FUN9 -> FUN10 (`ed_bk_commit`: `proj_import`,
`proj_bound`, `proj_pack`; FUN1..FUN5 have no accepted length: `proj_store_len`), settings via `settings_import`, id 8
via `upf_migrate`. Fixtures: `backup_test.c`, `web/test_backup.mjs`.

### 2.6 Where today's firmware can still overwrite content it cannot read

Found while taking this inventory; **not changed here** (#456's later stages own them). Each needs an explicit user
action or a save of another object; boot and the raw export themselves write nothing over them (host evidence:
`backup_test.c` "boot over objects it cannot read writes nothing").

| Object | What happens today |
| --- | --- |
| Project slot UNKNOWN / DAMAGED | shows EMPTY (RENAME and ERASE refuse it). A SAVE into an UNKNOWN slot writes the other copy and the next SAVE replaces the unread one; with no intact copy (DAMAGED) `st_save` writes copy A, so the first SAVE can replace it. No "incompatible" warning. The same A/B rule applies to every row below |
| Settings UNKNOWN | defaults at boot; the next settings change writes this firmware's record into the other copy, the one after that replaces the unread copy. A PER6 of another extension version loses its extension on the next save |
| User preset bank UNKNOWN | empty mirror; storing a preset into that bank writes a whole new bank (twice: the unread copy is gone) |
| User preset records | PHYS MODEL 4 and SAMPLE PERC records are written back migrated at the bank's next write; a rename rewrites ver 1..3 as ver 4/5 |
| `UPF6` UNKNOWN | treated as none; the next patch save writes a fresh one |
| Autosave UNKNOWN | ignored; two autosaves replace it (a derived object: acceptable, but not recoverable) |
| Retired FM6 bank | after type 8 exists, type 8's next save may erase the bank's sector (by design, 1.0.3) |
| Calibration | the panel table travels inside the settings record; a settings restore from another device applies that device's calibration |

## 3. Proposed supported current schema (contract)

A proposal for #456's next stages; nothing here is implemented beyond the raw export. Identifiers are the stored ones;
the firmware validates exactly these and treats anything else as UNKNOWN (kept, never decoded, never overwritten
implicitly).

| Type | Schema id | Length | Validation the firmware keeps | Growth budget |
| --- | --- | ---: | --- | --- |
| 1..4, 9 | `FUNA` + size 3840 + byte 66 = P_COUNT (111) | 3840 | storage CRC, FNV-1a, `proj_unpack` ranges, `proj_engines_ok`, chain/motion validity | **none in the object** (3840 B = `ST_PAYLOAD_MAX`); 13 spare bytes before `PROJ_MIDI_OFF` (3 track parameters). Further project data goes to PRX sidecars (types 10..14, A3, #316), tagged to the parent by value hash or uid ([flash-capacity.md 6](flash-capacity.md#6-what-the-prx-sidecar-needs)) |
| 0 | `PER4` (572) or `PER6` ext ver 1 (672..2688) | as stored | storage CRC, `persist_ext_ok`, the field checks of `ed_bk_commit` | SETX tail (`ver` 2, tagged chunks) inside the 2,688 B envelope: 960 B (A2, #315). Calibration (`panel_t`) to be split from preferences: never imported from another device's record |
| 5, 6 | `UPB1`, rsize 192, 16 slots; records ver 4 / 5, np = P_COUNT | 3080 | storage CRC, bank shape, `up_valid` | 32 packed value bytes per record unused (np 111 of 144, the category at 143); deep patches go to DEEP sidecars (A4, #317) |
| 8 | `UPF6` ver 1, 32 slots | 3728 | storage CRC, `upf_valid`, tag match | 112 B |
| 32 | `FM6V` ver 1, 32 voices | 3616 | storage CRC, `ed_bk_fvb_check` | tail kept erased (SPL record scan) |

Removing compatibility frees **no sector and no NOINIT**: every object keeps its size and its sectors, and `proj_slot`
stays 4 x 3840 B. What removal saves is app flash (code), which is reported when it happens. No automatic sample-slot
reclamation follows from it.

Explicit schema descriptors: the web editor must choose its output schema from the connected firmware's contract, not
its version string (#457). INFO already carries P_COUNT, P_E0, the engine id bitmap (`49 01`) and the capability tags;
the remaining per-type identifiers (magic, version, length, record size and count, as in the table above) are
proposed as a read-only descriptor command behind another bit of INFO `59 01` (not implemented; open question).

Upload rule for the later stage: accept only the current schema, validate the whole object (as `ed_bk_commit` does
today) before the existing `st_save` commit, never into a slot whose current content is UNKNOWN or DAMAGED without an
explicit replace request, and leave prior data intact on any refusal or interruption.

## 4. Handover to the web editor (#457)

The client reads the raw export (`STORE_LIST` / `STORE_GET`, reference reader `web/fm1backup.js captureRawStore`) and
keeps the stored bytes as the source. For conversion it needs these rules, each with its firmware reference
implementation and the fixtures that pin today's result. For the retired sounds the results are captured from the
current firmware as reference vectors (below), **before** any reader is removed.

| Rule set | Firmware reference | Fixtures to port / compare |
| --- | --- | --- |
| Project FUN1..FUN9 -> FUN10 | `project.c` `proj_from_v1..v4`, `proj_import_old`, `proj_unpack`, `proj_motion_v9`, `proj_motion_ids`, `song_chain.c chain_from_v9`, `proj_bound`, `proj_pack` | `tests/project_test.c`, `tests/fun10_test.c`, `tests/old_pack.h`, `tests/backup_test.c` |
| Parameter count remap (projects, presets) | `core.h params_by_count` (first np-8 in order, last 8 at P_E0.., new ones at their defaults) | `fun10_test.c`, `insert_test.c`, `upreset_test.c` |
| Retired sounds | `core.h drum_from_phys`, `drum_from_perc`, `eng_phys.c phys_legacy`, `fm4_convert.c fm4_convert` + `FM4_TO_FM6`, `project.c proj_fm4` / `proj_perc` motion drops, `ui.c fm4_apply` | `fm4_test.c`, `fm4_div0_test.c`, `project_test.c`, `upreset_test.c`, `ui_test.c` |
| GM drum part, grid | `proj_drums_to_part`, `proj_legacy_drums`, `eng_drum.c step_to_grid`, `DRUM_PRESETS[0]` | `project_test.c` |
| Enum aliases | `params.c enum_orig`, `param_fit`, `eng_drum.c DK_PLAYS`, `SMP_SET_ORIG` | `drum_test.c`, `engid_test.c` |
| FM6 patches | `eng_fm6.c fm6_pack` / `fm6_unpack`, `fm6_adopt`, `FM6_INIT`; `up_fm6.c upf_tag`, `upf_migrate` (a migrated record changes its tag: recompute the `UPF6` entry) | `fm6bank_test.c`, `persistence_test.c`, `backup_test.c` |
| User preset records | `upreset.c up_valid`, `up_values`, `up_to_v4`, `up_migrate`, `up_pat_norm` | `upreset_test.c`, `robust_test.c` |
| Settings | `settings_persist.c settings_import` (PER1..PER6, field rules in 2.4), `gfx.c palette_from_stored`, `panel.c hold_from_stored` / `leds_from_stored` | `settings_test.c`, `engid_test.c` |

### Retired-sound reference vectors (#299)

`tests/fixtures/retired_vectors.json` holds input bytes, output bytes and what a conversion drops, for DIGITAL
(engine 1), PHYS MODEL 2 (DUST) and MODEL 4 (DRUM) and SAMPLE PERC (SET 4), in each store that can carry them. It is
generated by `tests/retired_vectors.c`, which runs the firmware's own code (nothing is re-implemented), and
`tests/run_tests.sh` (unit `retired_vectors`) regenerates it and fails on any difference. A deliberate change of a
conversion changes the file: review the diff, then `python3 tests/retired_vectors.py --update build/host/retired_vectors`
(the binary is built by that unit; `cc -O1 -w -Ibuild/gen -Ifirmware/src -o build/host/retired_vectors tests/retired_vectors.c -lm`).
Bytes are lower-case hex, int16 values little-endian. The vectors do not change what loads; they record it.

| Section | Store and firmware path run | Input | Output | Dropped / moved |
| --- | --- | --- | --- | --- |
| `projects` | FUN10 (`phys` byte 0, 1, 2) and FUN7 (np 91): `proj_import`, `proj_bound`, `proj_pack` (what `proj_fetch` does) | the whole image | the whole FUN10 image; per track engine and preset before and after | `motion_dropped`: motion events on EDIT (>= P_E0) and OP ENV values of a converted DIGITAL track or SAMPLE PERC track (track, step, parameter, lock, value) |
| `presets` | `UPB1` record: `up_bank_check` (boot: PHYS MODEL 4 and SAMPLE PERC become DRUM in the RAM mirror), then `up_load` | the 192-byte record as stored | `record_out` (the mirror's record); `loaded`: engine, preset, 111 values (int16) and the FM6 patch (155 B + 1) the track gets | a DIGITAL record is kept as stored (`record_out` equals `input`) and converts on every load; version 1 PHYS MODEL 2 reads as MODAL bowed in `loaded` |
| `favourites` | PER4 (572 B) and PER6 (ext ver 1, 64 rows): `settings_import` | `rows_in`: the non-zero favourites rows (row = engine id, 32 B, preset bits LSB first) | `rows_out`: the runtime rows | `moved` (DIGITAL preset k to FM6 preset `FM4_TO_FM6[k]`; SAMPLE PERC, bit 4 of row 4, to DRUM preset 0) and `dropped` (row 1 bits past the 8 DIGITAL presets) |
| `load` | `fm4_load_preset` (a stored DIGITAL preset number) and `fm4_apply` (DIGITAL values: `up_load`, `project_restore_runtime`, the editor) | the preset number, or 111 int16 values | the track afterwards: engine, preset, values and FM6 patch; `p_after_convert` is the caller's array as `fm4_convert` leaves it | n/a |

`constants` lists the ids the vectors use (P_COUNT, P_E0, the OP ENV range, engine ids, `FX_DEF`, `FM4_TO_FM6`,
`DRUM_KIT_E`). **How the WebApp compares** (Felucca-WebApp `test_legacy.mjs`): load the file, for each `projects` case
feed `input` to its FUN1..FUN10 converter (the stored image, with `phys_byte` as stored) and compare its FUN10 bytes
with `output`, and its list of dropped motion events with `motion_dropped`; for `presets` feed `input` to the record
converter and compare with `record_out` (PHYS MODEL 4 and SAMPLE PERC) and, for DIGITAL, its converted patch and
values with `loaded`; for `favourites` compare its rows with `rows_out`. The comparison is on bytes; a difference is a
bug on one side or a deliberate firmware change that the update of the file records. The file is a copy of the firmware
side: the WebApp may vendor it or fetch it from the firmware repository at a pinned commit. PER settings other than
the favourites rows, the FM6 bank (type 7) and the `UPF6` relink are not covered (#299 part B and #457).

The raw checks in `backup_test.c` additionally pin byte-for-byte export and no flash writes for PER5, PER6 with MACRO
favourites, a future PER6 extension, FUN10 / `UPB1` carrying MACRO's stable id, unsupported serialized-project counts,
and `FM6V` with a voice count other than 32. Classification is based on container identification, not full semantic
validation; clients must validate content separately before conversion or upload. A second manifest detects changed
commit metadata, but is not an atomic snapshot and cannot detect damage changing elsewhere in a payload while its
commit record and identification bytes remain unchanged.

Client obligations from #456/#457, restated: keep the original file; never convert or upload on connect; report losses
(retired-engine motion on EDIT/OP ENV values, PERC/PHYS DRUM E values, unavailable engines, patches of FUN7 and older,
favourites, MIDI routing, settings fields) before upload; never apply another device's calibration; preserve stable
engine ids and unavailable-engine bytes (#422).
