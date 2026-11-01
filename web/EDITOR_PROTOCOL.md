# Felucca editor protocol (SysEx over USB-MIDI)

The firmware side is `firmware/src/editor.c`. Commands 1-15, track selection, dumps, step reads
and parameter writes (27, 29, 30, 31) were checked on hardware. `tests/editor_test.c` also exercises the real C
handler, malformed transfers and stop timeouts against simulated flash. User-preset
flash writes and live pushes (16-26, 32) have host coverage; that does not establish
their hardware behavior. The step chance byte, motion (64) and the full backup (65-67) have host
coverage only (`tests/editor_test.c`, `tests/backup_test.c`, `web/test_backup.mjs`), as has the raw store export (82, 83:
`tests/backup_test.c`, `web/test_backup.mjs`).

This firmware repository owns the wire protocol and stored formats. The
[Felucca-WebApp](https://github.com/kmplngj/Felucca-WebApp) repository owns clients
that consume them; client behavior described here is compatibility guidance.
This reference describes the current source, with optional/versioned suffixes
called out explicitly. Historical hardware observations above remain scoped to
the commands and revisions actually exercised.

- [Framing and encodings](#framing)
- [Step record](#step-record)
- [Commands 1..32](#commands), [SONG 33](#cmd-33), [preferences 34..38](#tagged-device-preferences-v1)
- [MOTION 64](#cmd-64), [backup 65..67](#v7-full-backup-65-67), [FM6 68..71](#fm6-patches-68-71)
- [MENU 72..73](#menu-settings-72-73-104), [voice bank 74..77](#fm6-voice-bank-74-77-141)
- [MIDI LEARN 78..79](#midi-learn-78-79-15), [palette 80..81](#custom-palette-80-81-16), [raw export 82..83](#raw-store-export-82-83-456)
- [Parameter reference](#parameter-and-engine-reference), [project containers](#project-containers), [protocol changelog](#protocol-changelog)

## Framing

A request is `F0 7D 46 4C <cmd> <args...> F7`:

- `7D` is the non-commercial SysEx ID.
- `46 4C` is "FL".

A supported, well-formed request normally gets one reply with the same header and
command. Invalid requests either get no reply or a command-specific error; the
entries below distinguish these cases. Commands 23, 24, 26 and 32 are device pushes
only. IDs 39..63 and all unlisted IDs have no handler and get no reply.

Every data byte is 7 bit. MIDI realtime bytes may occur inside SysEx; another status
aborts the partial frame. Pushes may arrive while a request is outstanding. Send
one request at a time, including PING; see [editor notes](#notes-for-the-editor).
The [shared Editor/updater dispatch investigation](../docs/sysex-dispatch-race.md)
records the regression, device evidence and qualification scope for retained replies.

All request and reply lengths below count **argument bytes only**, excluding the
six framing bytes. A v14 consumes two bytes; a u32 consumes five; a string includes
its final NUL. `pack7(d)` takes `d + ceil(d / 7)` bytes for `d > 0`.
Step payload lengths are defined once in [Step record](#step-record).

| Item | Encoding |
| --- | --- |
| value (v14) | 2 bytes, LSB first, holding value + 8192, so the range is -8192..8191. `[lo, hi]`: value = (lo \| hi << 7) − 8192 |
| u32 (v7) | 5 bytes, 7 bits each, LSB first; the last byte is 0..15. Used by the backup commands |
| string | ASCII bytes, ended by a 0 byte |
| scope | 0 = parameter of the selected track (`P_*`, 0..P_COUNT−1); 1 = global parameter (`G_*`, 0..G_COUNT−1) |
| track | 0..3: tracks 1..4 (synth parts) |
| engine byte | an engine id 0..63 (#212: the id space, whatever engines a build has; firmware before 1.0: NENGINES = its drum track, no engine). The numbers are fixed, new engines are appended: 0 ANALOG, 1 reserved (DIGITAL before 1.0: see below), 2 PHASE, 3 LOFI, 4 SAMPLE, 5 VOICE, 6 TRIO, 7 WHEEL, 8 GRAIN, 9 PHYS, 10 DRUM, 11 NOISE, 12 FM6, 13 SLICE, 14 MACRO (optional `macro` profile; see [MACRO](#optional-macro-profile-27)). Standard NENGINES is 14 (including with `FELUCCA_SLICE=0`, which omits id 13 from the catalog); MACRO profile NENGINES is 15. Before #212, a build without SLICE reported NENGINES 13. A build plays the ids INFO's `49 01` block marks; an id it lacks is kept where it is stored and reported as it is (see "Engine ids" below). The device and the editor list them in another order (ANALOG FM6 PHASE LOFI SAMPLE VOICE TRIO WHEEL GRAIN PHYS NOISE SLICE DRUM: `ENGINE_ORDER`); the numbers stay |

## Step record

This section is the canonical definition of a step in editor messages, project
files and user-preset patterns. These are three different encodings; do not copy
one directly into another. Source: `editor.c` (`ed_args_ok`, `ed_step_put`,
`ed_step_reply`), `project.c` (`proj_pack`, `proj_unpack`), `upreset.c`
(`up_pat_from`, `up_pat_norm`, `up_parse`) and `core.h` (step helpers).

<a id="v5-the-drum-grid"></a>
<a id="ratchet"></a>
<a id="155-conditions"></a>
### Editor wire payload

STEP_GET/STEP_SET prefix the payload with an index; TRACK_STEP prefixes it with
track, index. Current firmware replies with all 15 payload bytes. Earlier replies
end after the last feature they support; inspect INFO before sending extensions.

| Payload offset | Field | Accepted write / returned value |
| --- | --- | --- |
| 0 | n | 0..4 notes; larger writes clamp to 4 |
| 1..4 | note0..note3 | MIDI notes 0..127, including unused entries |
| 5 | time | 0 NOTE, 1 TIE, 2 REST; larger writes clamp to REST |
| 6 | flags | bit 0 accent, bit 1 slide; other wire bits ignored |
| 7 | vel | 0..127; 0 plays at the default velocity 96 |
| 8 | hit low | lanes 0..6, one bit per lane |
| 9 | acc low | accents for lanes 0..6 |
| 10 | high bits | bit 0 = hit lane 7, bit 1 = acc lane 7; other bits ignored; accents are masked by hits |
| 11 | chance | 0..100 percent; returned as 100 when a condition is set |
| 12 | ratchet | 1..4 |
| 13 | nudge + 8 | 0..15 represents −8..+7 sixteenths of a step; 8 is on time |
| 14 | condition | 0 none; 1..11 in the condition table below |

| Payload bytes | STEP_SET argument bytes | TRACK_STEP write argument bytes | Added feature |
| --- | --- | --- | --- |
| 8 | 9 | 10 | original notes |
| 11 | 12 | 13 | v5 grid |
| 12 | 13 | 14 | v7 chance; INFO `4D 01` |
| 13 | 14 | 15 | ratchet; INFO `52 01` (1.0.5) |
| 14 | 15 | 16 | nudge; INFO `54 01` (1.2) |
| 15 | 16 | 17 | condition; INFO `4B 01` (1.5.5) |

These are the only accepted write lengths. Any other length or supplied chance
above 100, ratchet outside 1..4, nudge above 15 or condition above 11 gets no reply
and changes nothing. Even when a nonzero condition supersedes chance, the supplied
chance must pass validation. Omitting an extension preserves its stored fields.
Send three zero grid bytes to clear hits. Ratchet and nudge never travel in wire
flags: a write preserves them unless their own extension bytes are supplied.

With an explicit condition 1..11 the condition applies and chance is ignored;
condition 0 clears it and applies chance. Without a condition byte, chance 100
preserves an existing condition, while chance below 100 replaces it. An older
editor therefore preserves a condition when writing back the 100 it read.

| Condition | Name | Plays when |
| --- | --- | --- |
| 0 | none | the chance roll passes |
| 1, 2 | 1:2, 2:2 | loop 1 or 2 of every 2 |
| 3..5 | 1:3, 2:3, 3:3 | the named loop of every 3 |
| 6..9 | 1:4, 2:4, 3:4, 4:4 | the named loop of every 4 |
| 10 | FILL | FILL is held (device: GLO + E4) |
| 11 | !FILL | FILL is not held |

Loops count from PLAY and each SONG section. A step has chance or a condition,
never both. Chance is rolled once for the whole step (notes, hits, TIE and ratchet
parts); failure releases the previous notes and applies no locks. A NOTE ratchet
divides the swung step into equal retriggered parts, each held for GATE of its
part. Slide affects its first part; it never slides or ties into the next step.
TIE and REST ignore ratchet and play no hits. Nudge plays with QNTZ OFF, except on
ratcheted steps; −8 is half a step early and +7 is 7/16 late.

The eight lanes are KICK 36, SNARE 38, CLAP 39, HAT CL 42, HAT OP 46, TOM 45,
RIM 37 and BELL 56 (MIDI notes). A NOTE plays its notes and then its hits on any
engine. Accented hits play at velocity 127, others at the step’s velocity (0 = 96).
VA kits may use another piece on a lane: kit 66 conga on lane 5, 77 claves on
lane 6, 10/77 cymbal on lane 7. The device maps other GM drum notes to lanes
(GM 35..81, other notes folded to octave 36..47); editing a lane turns notes
on it into the lane’s hit. Sound loads preserve notes and hits. Pattern loads
into DRUM and pre-grid DRUM projects convert matching notes to hits.

Device edits push STEP_CHANGED. SEQ > STEP shows the piano roll or DRUM grid;
SEQ > AUTOMATION edits CHANCE/COND, RATCH and NUDGE (before 1.2: SEQ > CHANCE).
Live recording captures nudge; held steps + PRESETS also edit it. The roll/grid
draw ratchet parts and mark locks; AUTOMATION shows lock count.

### Project-file step (9 bytes)

FUN7..FUN10 store 64 steps per track using this packed record. These bytes are
8-bit file data; backup transport wraps them in pack7. FUN10 adds nudge without
changing the record size. The RAM `step_t` layout is not this file layout.

| File offset | Encoding |
| --- | --- |
| 0..3 | low 7 bits: four MIDI notes; FUN10 bit 7 of note j = bit j of the signed 4-bit nudge |
| 4 | n in bits 0..2 (0..4), time in bits 3..4 (0..2), accent/slide in bits 5..6, bit 7 must be zero |
| 5 | velocity in bits 0..6; bit 7 = bit 0 of ratchet − 1 |
| 6 | 8-bit hit mask |
| 7 | 8-bit accent mask; any accent outside hit makes the project invalid |
| 8 | probability code in bits 0..6; bit 7 = bit 1 of ratchet − 1 |

Probability code 0 means 100%, 1..100 means that percentage (100 is also accepted),
101 means never, and 102..112 means condition `code − 101`; 113..127 is invalid.
FUN10 nudge is two’s complement: 0..7 = 0..+7, 8..15 = −8..−1 (unlike the
wire’s +8 bias). FUN7..FUN9 require note high bits zero and load nudge 0.
Packing clamps notes/velocity to 127 and masks accents to hits; unpacking rejects
invalid n/time, meta bit 7, probability or accent bits. A project containing a
ratchet is refused by pre-ratchet firmware; one containing a condition is refused
by firmware before 1.5.5 (slot appears empty until overwritten).

FUN1..FUN4 have 8-byte steps without hits, chance or nudge; FUN5/FUN6 have
10-byte steps with hits/accents. The legacy readers supply chance 100%, ratchet
1 and nudge 0. See [project containers](#project-containers) for the outer layout.

### User-preset pattern (16 pairs)

Presets keep a reduced pattern, not 16 complete steps. In a note pattern each
pair is `(note, flags)`: note 0 is rest; flag 1 accent, 2 slide, 4 tie, bits 3..4
ratchet − 1. A tie normalizes to `(0, 4)` and loses ratchet; a rest loses all
flags. UP_STORE takes the first note of each NOTE step, a TIE as flag 4, REST
as note 0, and strips nudge before normalizing. Chords, velocity, chance,
conditions and nudge are not retained. Pre-ratchet firmware drops ratchet bits.

A DRUM preset whose first 16 steps strike any lane stores a grid instead.
Each pair contains the low seven bits of `(hits, accents)`; a separate high
byte for each pair has bit 0 = hit lane 7, bit 1 = accent lane 7. Accents are
masked to hits. Grid patterns have no ratchet and load x1.

- UP_GET sends the 16 pairs, then kind 0 (note) or kind 1 (grid); only kind 1
  adds 16 high bytes. Since 1.2, category follows that suffix.
- UP_PUT accepts the pairs alone (legacy note pattern), or exactly 17 more
  bytes (kind 0/1 **and 16 high bytes**, ignored for kind 0), or 18 more bytes
  (that extension plus category 0..8). Unknown kind, incomplete extension or
  extra bytes returns rc 1. A category cannot follow pairs alone.
- Older pre-grid firmware treats grid records as empty. A preset load applies
  its sound, keeping the current steps; SAVE > PHRASES loads its pattern and
  stored LEN (at most 16), DIV, SWING and GATE.

## Commands

Commands on scope 0 and the v1/v2 sound, preset and step commands use the selected
track. TRACK selects one; TRACK_MIX, TRACK_DUMP, TRACK_STEP and TRACK_PARAM address
a track without changing selection. All four tracks are synth parts; see
[track semantics](#track-semantics) for compatibility with the old drum track.

<a id="cmd-1"></a>
### 1 INFO

Available: v1. Request length (argument bytes): **0**.

- Request: —.
- Reply: version string, NENGINES, P_COUNT, G_COUNT, NSTEP, P_E0, NENGINES engine-name strings, optional NTRK, optional CHAIN_ROWS, then the [capability blocks](#info-capability-blocks).

### INFO capability blocks

The prefix is positional, not tagged. NENGINES is the name-list length, not the
number of playable engines. Version text is at most 24 characters, engine names
at most 8. Current standard counts are P_COUNT 111, G_COUNT 27, NSTEP 64, P_E0 103,
NTRK 4 and CHAIN_ROWS 16. Prefer the returned counts over these examples.
Older replies end earlier; ignore trailing features you do not consume. Blocks
have tag-specific lengths: the byte `01` is the block version, not a generic
payload length. Do not parse them as a generic TLV stream.

| Hex tag/version | Following bytes | Meaning / reference |
| --- | --- | --- |
| `55 01` | uiCaps | [Preferences 34..38](#tagged-device-preferences-v1) |
| `4D 01` | 64, 1 | Legacy motion capacity and chance support |
| `42 01` | caps | bit 0 backup read, bit 1 restore (current 3) |
| `46 01` | nfactory, nbank | FM6 patches; current 8, 0 |
| `53 01` | caps | bit 0 WATCH preserves pending changes; bit 1 no own PRESET/G_ENGSEL RELOAD (current 3) |
| `50 01` | caps | FM6 v2: bit 0 retired patch bank, bit 1 user-preset patch target (current 3) |
| `4E 01` | count | MENU settings count (33, or 34 with CPU2) |
| `52 01` | 4 | Step ratchet maximum |
| `4C 01` | 1 | Parameter locks |
| `41 01` | capacity lo, hi | Full motion capacity, 128 = `00 01` |
| `54 01` | 16 | Step nudge divisor |
| `57 01` | 4 | Song section track count |
| `56 01` | 32 | FM6 voice bank capacity |
| `43 01` | 16 | MIDI LEARN capacity |
| `4B 01` | 11 | Step condition count |
| `45 01` | 5 | CUSTOM palette color count |
| `49 01` | 64, 127, 10 bitmap bytes | Engine ID space, user favorite marker, playable IDs; [engine catalog](#engine-ids-212) |
| `58 01` | caps | bit 0 extended backup list, bit 1 object 20, bit 2 object 21; current 7, 3 without SLICE, 0 without flash |
| `59 01` | caps | bit 0 raw store export; current 1, 0 without flash |

<a id="cmd-2"></a>

### 2 GET

Available: v1. Request length (argument bytes): **2**.

- Request: scope, id.
- Reply: scope, id, v14.

An unknown scope or id gets no reply.

<a id="cmd-3"></a>
### 3 SET

Available: v1. Request length (argument bytes): **4**.

- Request: scope, id, v14.
- Reply: scope, id, v14 (the value after clamping). Setting global `G_ENGSEL` (id from DESC label "ENG") changes the engine: its defaults, then its first preset (as on the device).

An unknown scope or id gets no reply. Fixed-range parameters retain their value; retired enum aliases resolve to their current value. An unavailable engine requested through G_ENGSEL leaves the current engine unchanged and returns its current value.

<a id="cmd-4"></a>
### 4 DUMP

Available: v1. Request length (argument bytes): **0**.

- Request: —.
- Reply: engine, preset, then P_COUNT × v14 (the selected track), then G_COUNT × v14 (globals).

<a id="cmd-5"></a>
### 5 DESC

Available: v1. Request length (argument bytes): **2**.

- Request: scope, id.
- Reply: scope, id, fmt, min v14, max v14, def v14, label string, unit string, then for an enum (fmt 8) one name string per value (at most 24, or 48 for MACRO SHAPE; firmware before the matrix: at most 16).

An unknown scope or id gets no reply. Labels and units are at most 8 characters. Enum names are at most 8 characters, except MACRO SHAPE (12). See [parameter formats](#parameter-formats) and [MACRO](#optional-macro-profile-27).

<a id="cmd-6"></a>
### 6 STEP_GET

Available: v1. Request length (argument bytes): **1**.

- Request: index.
- Reply: index, [Step payload](#step-record).

An index ≥ NSTEP gets no reply. The reply has 16 argument bytes on current firmware, including its index.

<a id="cmd-7"></a>
### 7 STEP_SET

Available: v1. Request length (argument bytes): **9, 12, 13, 14, 15 or 16**.

- Request: index, Step payload.
- Reply: index, [Step payload](#step-record).

See [Step record](#step-record) for all accepted payloads, validation and omitted-field behavior. Invalid index, length, chance, ratchet, nudge or condition gets no reply. While a song plays the write is ignored and the playing step is returned.

<a id="cmd-8"></a>
### 8 PRESET

Available: v1. Request length (argument bytes): **2**.

- Request: engine, preset.
- Reply: engine, preset (applies the preset's sound to the selected track and sends; the steps and the track's own parameters stay, see "Sound loads and undo"). For another track, select it with `TRACK` first.

An unavailable engine gets no reply, except DIGITAL (1), which is accepted for conversion. A preset byte is 0..127: it wraps modulo the engine’s preset count, then resolves aliases. An engine with no presets keeps its preset number. The reply reports the resulting engine and preset; it need not echo the request. See [sound loads and undo](#notes-for-the-editor).

<a id="cmd-9"></a>
### 9 PROJECT

Available: v1. Request length (argument bytes): **2**.

- Request: op (0 load, 1 save, 2 query), slot 0..3.
- Reply: op, slot, used (1/0). Save writes flash: allow ~2 s; it stops the transport first (see "Saves while playing").

An unknown op or slot gets no reply. A failed save also gets no reply; the reply has no failure bit. A load/query returns whether the slot is used.

<a id="cmd-10"></a>
### 10 NAMES

Available: v1. Request length (argument bytes): **1**.

- Request: engine.
- Reply: engine, count, count preset-name strings, then the two edit-page titles.

Engine must be below INFO’s NENGINES; otherwise no reply. Unavailable entries in that name list have no presets. Preset names are at most 12 characters and page titles at most 8.

<a id="cmd-11"></a>
### 11 SMP_BEGIN

Available: v1. Request length (argument bytes): **1**.

- Request: slot 0..2.
- Reply: slot, rc (0 ok). Erases the slot's header sector: the slot is empty from now on.

Invalid slot or no flash: no reply. rc 1 means erase failure or transport stop timeout.

<a id="cmd-12"></a>
### 12 SMP_WRITE

Available: v1. Request length (argument bytes): **4 + pack7 length; 1..256 decoded bytes (6..297 total)**.

- Request: slot, offset (3 × 7 bit, LSB first), pack7 data (≤ 256 bytes).
- Reply: slot, offset (3 × 7 bit), rc: 0 ok, 1 arguments or stop timeout, 2 erase, 3 write, 4 slot in use (send SMP_BEGIN first).

A frame shorter than 5 argument bytes, invalid slot or no flash gets no reply. Otherwise malformed pack7/size/offset returns rc 1. Offsets must be at least 512, aligned to 256 and remain inside the 80 KiB slot. Send in increasing order to avoid erasing previously written bytes: the handler does not enforce ordering and erases whenever a write starts at a 4 KiB boundary.

<a id="cmd-13"></a>
### 13 SMP_END

Available: v1. Request length (argument bytes): **1 + pack7(480) = 550**.

- Request: slot, pack7 header (480 bytes).
- Reply: slot, rc: 0 ok, 1 size or stop timeout, 2 header, 3 data CRC, 4 flash, 5 zones.

A frame shorter than 2 argument bytes, invalid slot or no flash gets no reply. Other decoded sizes return rc 1. See [sample storage](#sample-storage) and the published-header retry rule in [editor notes](#notes-for-the-editor).

<a id="cmd-14"></a>
### 14 SMP_ERASE

Available: v1. Request length (argument bytes): **1**.

- Request: slot.
- Reply: slot, rc (erases the whole slot, ~1 s).

Slot 0..2. Invalid slot or no flash: no reply. rc 1 means erase failure or transport stop timeout.

<a id="cmd-15"></a>
### 15 SMP_INFO

Available: v1. Request length (argument bytes): **0**.

- Request: —.
- Reply: slots, slot KiB, then per slot: zone count (0 = empty), name string, data KiB.

Current reply begins 3, 80. Names are at most 8 characters; data KiB is rounded up.

<a id="cmd-16"></a>
### 16 UP_LIST

Available: v2. Request length (argument bytes): **2**.

- Request: start, count (1..16).
- Reply: start, count, total slots, then per slot: used (0/1), engine, name string ("" if unused); 1.2: then one category byte per slot listed (below; 0 if unused).

start and count are 7-bit bytes; count 0 is accepted, values above 16 clamp to 16, then to the remaining slots. start ≥ 32 returns count 0. See [user preset storage](#user-preset-storage).

<a id="cmd-17"></a>
### 17 UP_GET

Available: v2. Request length (argument bytes): **1**.

- Request: slot.
- Reply: slot, used, engine, name, P_COUNT × v14, 16 × (note, flags), then (v5) kind (0 a note pattern, 1 a drum grid) and for kind 1 16 × hi; 1.2: then the category.

Slot 0..31; otherwise no reply. Note and grid pair encodings are defined once in [Step record](#step-record).

<a id="cmd-18"></a>
### 18 UP_PUT

Available: v2. Request length (argument bytes): **B, B + 17 or B + 18, where B = 3 + name length + 2 × P_COUNT + 32 (name length 1..12)**.

- Request: slot, engine, name, P_COUNT × v14, 16 × (note, flags) [, kind 0 or 1, 16 × hi (v5) [, category (1.2)]].
- Reply: slot, rc (0 ok, 1 args, 2 flash/no flash or stop timeout). Writes flash: allow 1 s.

No slot byte: no reply. Other malformed payloads return rc 1. Name must be NUL-terminated ASCII 32..126, 1..12 characters; values must be −64..127 before descriptor clamping. See [Step record](#step-record) for the exact pattern extension (the GET and PUT suffixes differ).

<a id="cmd-19"></a>
### 19 UP_STORE

Available: v2. Request length (argument bytes): **1 + name length, optionally followed by a NUL (1..14 total; name length 0..12)**.

- Request: slot, name.
- Reply: slot, rc (0 ok, 1 arguments, 2 flash/stop failure or no flash).

No slot byte: no reply. Empty name (slot alone or slot, 0) uses the automatic name. A nonempty printable ASCII name may omit its terminal NUL. Invalid slot/name/length returns rc 1. This stores the base sound and a reduced 16-step pattern; see [Step record](#step-record).

<a id="cmd-20"></a>
### 20 UP_LOAD

Available: v2. Request length (argument bytes): **1**.

- Request: slot.
- Reply: slot, rc (0 ok, 1 empty/invalid). Applies its sound (not its pattern; the steps stay).

Slot 0..31; invalid or empty slot returns rc 1.

<a id="cmd-21"></a>
### 21 UP_ERASE

Available: v2. Request length (argument bytes): **1**.

- Request: slot.
- Reply: slot, rc (0 ok, 1 arguments, 2 flash/stop failure or no flash).

Slot 0..31; invalid slot returns rc 1; transport stop failure, flash failure or absent flash returns rc 2.

<a id="cmd-22"></a>
### 22 WATCH

Available: v2. Request length (argument bytes): **1**.

- Request: on (0/1; v4: 3 = also `TRACK_CHANGED`).
- Reply: on (0/1; v4 firmware: 3 when 3 was asked for). While on, the device pushes cmds 23, 24, 26 (and 32 with bit 1).

Only bits 0 and 1 are interpreted: bit 0 enables watching; bit 1 requests TRACK_CHANGED only when bit 0 is set. Other bits are ignored. Reply is 0, 1 or 3. See [live sync](#live-sync).

<a id="cmd-23"></a>
### 23 CHANGED

Available: v2. Request length (argument bytes): **push only**.

- Request: —.
- Reply: scope, id, v14.

Device-to-host only; sending command 23 gets no reply. See [live sync](#live-sync).

<a id="cmd-24"></a>
### 24 RELOAD

Available: v2. Request length (argument bytes): **push only**.

- Request: —.
- Reply: engine, preset, then (v3) the selected track.

Device-to-host only; sending command 24 gets no reply. See [live sync](#live-sync).

<a id="cmd-25"></a>
### 25 PING

Available: v2. Request length (argument bytes): **0**.

- Request: —.
- Reply: 0.

<a id="cmd-26"></a>
### 26 STEP_CHANGED

Available: v2. Request length (argument bytes): **push only**.

- Request: —.
- Reply: index, then (v3) the selected track.

Device-to-host only; sending command 26 gets no reply. Read the step with STEP_GET or TRACK_STEP.

<a id="cmd-27"></a>
### 27 TRACK

Available: v3. Request length (argument bytes): **0 or 1**.

- Request: — (query), or track (select it).
- Reply: selected track, NTRK, then per track: engine byte, preset, level v14, mute (0/1), armed (0/1, live recording).

An out-of-range track byte leaves selection unchanged and still returns the track summary. Each track contributes 6 bytes, so the current reply has 26 argument bytes. See [track semantics](#track-semantics).

<a id="cmd-28"></a>
### 28 TRACK_MIX

Available: v3. Request length (argument bytes): **1 or 4**.

- Request: track (get), or track, level v14 (0..127), mute (set).
- Reply: track, level v14, mute: the track's `P_LEVEL` and `P_MUTE`.

Invalid track: no reply. Level clamps to 0..127; any nonzero mute byte becomes 1.

<a id="cmd-29"></a>
### 29 TRACK_DUMP

Available: v3. Request length (argument bytes): **1**.

- Request: track.
- Reply: track, engine byte, preset, P_COUNT × v14 (that track's parameters; no globals).

Invalid track: no reply. Values are the sound’s base values, including while motion plays.

<a id="cmd-30"></a>
### 30 TRACK_STEP

Available: v3. Request length (argument bytes): **2 (read); 10, 13, 14, 15, 16 or 17 (write)**.

- Request: track, index [, Step payload].
- Reply: track, index, [Step payload](#step-record).

Invalid track/index or malformed write: no reply. See [Step record](#step-record). Current replies contain 17 argument bytes; song playback returns the playing step and ignores writes.

<a id="cmd-31"></a>
### 31 TRACK_PARAM

Available: v4. Request length (argument bytes): **2 or 4**.

- Request: track, id (get), or track, id, v14 (set); id = `P_*` (0..P_COUNT−1).
- Reply: track, id, v14 (the value after clamping, as `SET`). The selection does not change; no push about the editor's own write.

Invalid track or id: no reply. Values clamp to that track’s descriptor; fixed ranges retain the current value. See [track parameter behavior](#v4-any-tracks-parameters).

<a id="cmd-32"></a>
### 32 TRACK_CHANGED

Available: v4. Request length (argument bytes): **push only**.

- Request: —.
- Reply: track, id, v14: `P_LEVEL`, `P_PAN` or `P_MUTE` of a track that is not selected changed on the device (only while `WATCH` was sent with bit 1).

Device-to-host only; sending command 32 gets no reply. Requires WATCH bit 1; see [live sync](#live-sync).

## Sample storage

Without flash (no flash part found at boot) `SMP_BEGIN`, `SMP_WRITE`, `SMP_END` and `SMP_ERASE` get no
reply.

**pack7:** groups of up to 7 bytes, each preceded by one byte holding their top bits
(bit j = bit 7 of byte j). A mask must have at least one following data byte;
unused mask bits in the last group must be zero. Oversized or incomplete transfers
are rejected; SMP_WRITE decodes at most 256 bytes, SMP_END exactly 480 bytes.

**User sample slot** (80 KiB each, SAMPLE engine sets USR1..USR3; reference uploader
`tools/fm1_sample_upload.py`, slot builder `sampleio.user_slot`; the editor's port of it is
checked byte for byte by `web/test_web.mjs`): header at 0, ADPCM data at 512.

| Offset | Field |
| --- | --- |
| 0 | magic `"FSMP"` (u32 0x504D5346), u16 version 1, u8 zone count 1..16, u8 0 |
| 8 | name, 8 ASCII bytes (0-padded) |
| 16 | u32 data length (bytes), u32 CRC-32 (zlib) of the data, 8 bytes 0 |
| 32 | 16 zones × 28 bytes: u32 off (in the data), n (samples), loop start, loop end, rate (Hz / 44100 × 65536); i16 root × 16 (MIDI note), ADPCM predictor at the loop start; u8 step index at the loop start, lo note, hi note, looped (0/1) |

Data is IMA ADPCM, 4 bit, low nibble first, starting from predictor 0 and step index 0.
All little endian.

The slot's last 4 KiB sector (offset 0x13000) holds SLICE's slices set by hand on the device (`src/slice_store.c`:
magic `"SLM1"`, the sample's length and data CRC, the slice starts) when the data leaves it free (at most 77,312
bytes). An upload writes over it like any other data; a record that is not the slot's sample's is ignored.
The full backup carries these records as object 21 ([extended backup objects](#the-fm6-voice-bank-and-the-slice-records-321-ids-20-21)); the sample
objects 32..34 do not (their size is the header and the data only).

<a id="v2-user-presets"></a>
## User preset storage

Slots 0..31 (U01..U32 on the device) store an engine ID, a printable ASCII
name, P_COUNT v14 values in DUMP order and a [16-pair pattern](#step-record).
Loading applies its sound and preserves the track’s steps and own parameters.

- `UP_GET` of an empty slot has the same shape with used 0, engine 0, name "" and all values 0.
  Used-slot values come back in the current parameter order, inside their ranges.
- `UP_PUT`: rc 1 for a slot ≥ 32, an engine this build cannot play (#212: INFO's `49 01` bitmap; 1, DIGITAL, is
  taken and converts as below), a name that is empty, longer than 12 or has
  bytes outside 32..126, or an incomplete or oversized frame. Values are clamped to their ranges for that
  engine. A note with flag 4 is stored as a tie (note 0); flags on a rest are dropped.
- **DRUM** (engine 10) was PHYS's MODEL 4 (DRUM) before 1.0. A record of PHYS with E1 (MODEL) = 4,
  stored then or sent by `UP_PUT` from an older editor, is the DRUM engine: the device rewrites it (engine
  10; E1..E8 {MODEL, TUNE, TONE, DECY, SNAP, ACC, KICK 0..127, PERC 0..127} become {KIT = PERC / 32, TUNE,
  TONE, DECY, SNAP, ACC, KICK 0 PUNCH / 1 ROUND (old ≥ 64), DRV 0}), and `UP_GET` / `UP_LIST` give it so.
  Projects do the same. PHYS's MODEL is 0..3 (MODAL STRNG MEMB SYMP) now.
- **SAMPLE SET 4** was PERC, the General MIDI drum kit, until 1.0.2. A record of SAMPLE (engine 4) with E1 (SET)
  = 4, stored then or sent by `UP_PUT`, is the DRUM engine with its default kit: the device rewrites it (engine 10,
  E1..E8 = DRUM KIT's {0, 64, 70, 64, 64, 100, 0, 0}, the other values and the pattern as they were). Projects
  and `PRESET` 4 / 4 do the same (a project's track keeps its steps). SET 4 itself stays (`DESC` names it "PIANO":
  an alias, as SET 1; a `SET` of 4 lands on 0), and USR1..USR3 stay 5..7; GRAIN's SRC 4 plays PIANO.
- **DRUM KIT 1..3** were HAND, CYM and H+CYM until 1.0.4 (STD with a conga / claves, a cymbal, both). Since 1.0.5
  they play the VA kits 66, 10 and 77, and a record holding one loads as that kit: `UP_GET` / `UP_LOAD` give KIT 6, 5
  or 8 (the record itself is not rewritten). Projects, motion events and `SET` do the same.
- `UP_STORE`: name "" stores with the automatic name the device uses (engine name + slot number,
  "ANALOG 07"). rc 1 for a bad slot or name.
- rc 2 = the flash write failed or there is no flash. A failed flash write keeps the previous
  record in RAM and flash, including its name. Without flash, a valid change is RAM-only until power-off.
  (`UP_PUT` / `UP_STORE` / `UP_ERASE` stop the transport first, see "Saves while playing"; a device
  that cannot stop it in 100 ms answers rc 2 and writes nothing.)
- Frames stay below the 640-byte incoming buffer; maximum UP_PUT size is 287 argument bytes (293 with framing) with P_COUNT 111 and a 12-character name.
- **Categories (1.2, Discussion #90).** A user preset has a sound category: 0 none, 1 BASS, 2 LEAD, 3 PAD, 4 PLUCK,
  5 KEYS, 6 DRUM, 7 FX, 8 OTHER (append-only; the device's PRESETS > LIST filters by it, its NAME screen sets it).
  `UP_LIST` sends one byte per listed slot after all the slot entries (0 for an empty slot); `UP_GET` ends with it
  (after kind 0, or after kind 1's 16 bytes). A record saved without one (before 1.2, or by an editor that sends none)
  reports its engine's: 6 DRUM for DRUM and SLICE, else 8 OTHER. `UP_PUT` takes it as one byte after the kind and its
  16 bytes (send kind 0 and 16 zeros for a note pattern); 0 stores none, 9 or more is rc 1. An older editor reads up to
  where it knows and ignores the rest; firmware before 1.2 rejects an `UP_PUT` with the category (rc 1), so send it
  only to a device that answers `UP_GET` with it. The device keeps it in a byte of the record no value uses (the
  record's layout is unchanged; older firmware keeps it). The factory presets' categories are the device's
  (`src/category.c`), not sent.

**On the device:** SAVE > USER page: KNOB 1 picks the slot, KNOB 2 LOAD, KNOB 3 ERASE, KNOB 4 SAVE;
OCT+ executes the selected action, OCT- goes back. SAVE over a used slot asks
"OVERWRITE U07?" with OCT+ / OCT-. SAVE uses the automatic name. The PRESETS knob and the SAVE > PRESETS browser continue past the factory presets into the used user
presets.

**Flash** (`firmware/src/upreset.c`): two storage objects (`OBJ_UPRESET0/1`, A/B sector pairs at
0xDC000..0xDFFFF), 16 records of 192 bytes each, behind a bank header (magic "UPB1", record size,
slot count; a mismatch reads as an empty bank). A record keeps its layout version (versions 1..5 are read; another: empty)
and the P_COUNT it was stored with; another count is mapped by count (last 8 values = P_E0..P_E7, the
first ones = P_LEVEL.. in order, missing ones = defaults). Versions 4 (a note pattern) and 5 (a drum grid)
store each value as one byte, value + 64, so P_COUNT can reach 127; versions 1..3 stored 16-bit values.
The wire format is unchanged: `UP_GET` / `UP_PUT` still carry v14 values, and `UP_PUT` now answers rc 1
for a value outside −64..127. See [parameter-count history](#parameter-count-history) for mapping older counts. Missing values take descriptor defaults (SLICER/matrix/chord keys off, VOIC CLOSE and DRUM lane levels 127).

<a id="v2-live-sync"></a>
## Live sync

- `WATCH 1` starts the pushes. Watching ends by itself 3 s after the last request of any kind (send
  `PING` about every 1 s), on a USB reset, and when the host goes away; `WATCH 0` ends it at once.
- **CHANGED** (scope, id, v14): a parameter changed on the device (knob, menu, sequencer edit of a
  `P_*`), not by the editor's own `SET`. Coalesced: each (scope, id) at most every 20 ms, with the
  latest value.
- **RELOAD** ([payload](#cmd-24)): the engine, a preset, a user preset or a project was loaded; re-read
  `DESC` of the engine parameters, `DUMP` and the steps. It is also sent after loads the editor asked
  for with `PROJECT` load and `UP_LOAD`. After the editor's own `PRESET` and `SET` of G_ENGSEL it is not
  (firmware with INFO `53 01`, bit 1): the device takes the load as known (the engine, the preset and the
  parameters the load changed), since the editor re-reads `DUMP` after the reply; a device change still
  pending at that moment (a load or another track selected on the device, a knob turned) is pushed as before.
  Older firmware sends `RELOAD` after those too; an editor that skips its own echoes should do so only when
  bit 1 is clear.
- **WATCH while watching** (firmware with INFO `53 01`, bit 0): `WATCH 1` (or 3) while already watching on
  the same USB connection keeps what has not been pushed yet, so a change made just before is still pushed.
  Older firmware takes everything as known again (re-read `DUMP` after a re-`WATCH` there). `WATCH 0`, the 3 s
  timeout and a USB reset end watching; the next `WATCH` starts from the values as they are.
- **STEP_CHANGED** ([payload](#cmd-26)): a sequencer step changed on the device (record, clear, step edit,
  pattern load); not after the editor's own `STEP_SET`.
- Push frames have the normal header. Accept them at any time, also while waiting for a reply:
  match replies by cmd (23, 24, 26 and 32 are never replies). The device sends at most a few per
  ~5 ms pass, and only when its USB send queue has room, so a push never delays a reply.

<a id="v3-tracks"></a>
## Track semantics

- **Track 4 since 1.0** is a synth part like tracks 1..3: `DUMP` / `RELOAD` / `TRACK` / `TRACK_DUMP`
  give its real engine byte (power-on: DRUM, preset DRUM KIT, the General MIDI map), and `PRESET`, `SET` of
  `G_ENGSEL`, `UP_LOAD` and `UP_STORE` work on it; its level is its `P_LEVEL`. The commands are byte for
  byte as before; only the meaning changed. Firmware before 1.0 had a GM drum track there: engine byte
  NENGINES, no presets (`UP_LOAD` / `UP_STORE` rc 1), its level the global `G_DRLVL`. Drums are now the
  DRUM engine on any part: the first C key is the kick (C2 = 36), notes are GM numbers.
- The globals `G_DRCH`, `G_DRLVL`, `G_DRREV` (ids 24..26: the old drum track's MIDI channel, level and
  reverb send) keep their ids, and `G_COUNT` stays 27. `G_DRLVL` and `G_DRREV` are inert: `DESC` gives
  label "-", range 0..0, and no page shows them. Id 24 (`G_DRCH`, never read since 1.0) is `G_RTYPE`
  since 1.0: the reverb's model, `DESC` label "TYPE", enum ROOM (0) / SPRING (1) / HALL (2, since 1.2), on the
  REVERB page (FX). The power-on value (`DESC` def) is HALL since 1.2, ROOM before; a project keeps its own, and
  projects of formats before FUN7 load it as ROOM. MIDI channel 10 is no longer special (channels 1..4 play
  tracks 1..4, channels 5..16 are ignored since 1.0.3; with ROUT SEL every channel the selected track).
- Selecting a track with `TRACK` does not push `RELOAD` (the editor re-reads `DUMP`, the steps and the
  engine `DESC` itself); selecting one on the device does (`RELOAD` with the new track).
- Pushes are about the selected track only: `CHANGED` (scope 0) and `STEP_CHANGED` refer to it, and
  changes to other tracks push TRACK_CHANGED only for level, pan and mute with WATCH bit 1; other parameter and step changes are not pushed. The editor’s own TRACK_* writes have no echo push.
- Level and mute are also `P_LEVEL` / `P_MUTE` of the selected track (`SET`); `TRACK_MIX` reaches the
  others. Presets and user presets change a part's sound but keep its `P_LEVEL`, `P_PAN`, `P_MUTE`.
- Projects (`PROJECT`) save and load all four tracks, the selection, the song sections and motion (FUN10; see [project containers](#project-containers)). Formats 9..1 are converted; a format 1 project loads into track 1. A project saved before
  1.0 loads its drum track as track 4 with DRUM's kit (SAMPLE PERC until 1.0.2), its steps kept.
- Older firmware (no NTRK in `INFO`): one instrument; skip the track UI.

<a id="v4-any-tracks-parameters"></a>
## Track parameter behavior

- **Finding out:** send `WATCH 3`. v4 firmware answers 3; v3 (0.8) firmware answers 1, does not know
  cmds 31 / 32 (no reply) and never pushes `TRACK_CHANGED`. `WATCH 1` behaves exactly as in v2 / v3
  (reply 1, no `TRACK_CHANGED`). Match the `WATCH` reply by bit 0.
- `TRACK_PARAM` clamps like `SET` scope 0: to the range of that parameter; the engine parameters
  `P_E0..P_E7` to the ranges of that track's engine. A parameter
  with a fixed range (min = max) keeps its value. A track ≥ NTRK or an id ≥ P_COUNT gets no reply.
  For the selected track it is the same as `SET` scope 0.
- `TRACK_CHANGED` is never about the selected track (its changes stay `CHANGED` scope 0). Coalesced like
  `CHANGED` (each track and id at most every 20 ms, latest value), and not sent for the editor's own
  `TRACK_PARAM` / `TRACK_MIX` writes. After a selection change (`RELOAD`, or the editor's `TRACK`) the
  device takes the current values as known.

## Notes for the editor

- **One request at a time.** Wait for the reply, about 10–50 ms, before sending the next, from one queue
  for every request, keep-alive `PING` included. The device holds one incoming SysEx frame until the main
  loop has answered it; a frame that arrives before then is dropped whole (no reply). A frame is never
  taken in part: USB delivers every packet (acknowledged, retried), and a dropped frame leaves nothing.
  A 256-byte `BACKUP_PUT` piece is 306 bytes on the wire (`SMP_WRITE`: 303); the incoming buffer is 640 bytes. Requests are safe at full speed; pacing between bytes is not needed. With a second
  request in flight (pipelined, or a keep-alive from another thread) the second is lost: no reply, and a
  following `BACKUP_PUT` piece is then refused (rc 1, the offset). SMP_WRITE does not check continuity: abort and restart an interrupted upload so missing data cannot be mistaken for a successful transfer. Measured on an FM-1 with
  1.0 over USB: 256-byte pieces one at a time, the next sent from the reply callback, 560 of 560 taken
  (about 10 ms each); with the next piece sent before the reply, every second piece was dropped.
- **Following the device.** With v2 firmware, `WATCH` and `PING` (above). Older firmware pushes
  nothing (no reply to `PING`): poll `DUMP` about every 300–500 ms while the page is visible.
- **Port.** The device's MIDI port is named "Felucca" (USB 1209:0001). Updates use the same
  port with other SysEx (the `F0 22 24 35 …` keys, `00 59 …` frames); never send those
  from the editor. Since 1.0 the same USB device also has an audio input ("Felucca",
  44.1 kHz stereo; bcdDevice 3.11; since 1.1 44.1 or 48 kHz, the host's choice, bcdDevice 3.21
  (3.20 with MENU > USB SERIAL OFF)); the MIDI port and this protocol are unchanged, and both
  work while the computer records.
- **Global ids.** `G_ROUTE` (id 14, label "ROUT"; on the device MENU > MIDI > MIDI IN since 1.2, up to 1.1.5
  GLO > SYSTEM ROUT) was a placeholder ("--", range 0..0);
  since 1.0 it is the MIDI IN routing: 0 "CH1-4" (channels 1..4 → tracks 1..4; what projects stored
  before. Until 1.0.2 every other channel played the selected track; since 1.0.3 channels 5..16 are
  ignored: notes, bend, CCs, aftertouch, panic and reset), 1 "SEL" (every channel → the selected track); since 1.2
  (append-only) 2 "CH5-8", 3 "CH9-12", 4 "CH13-16": channels 5..8, 9..12 or 13..16 → tracks 1..4, the others
  ignored as with CH1-4, and the keys' MIDI out on the track's channel of that block. `DESC` of id 14 gives range
  0..4 and the five names; firmware before 1.2 clamps 2..4 to 1 (SEL) when it loads such a project.
  1.5.5 (#202, append-only): 5 "TRACK", each track on its own channel, set by MENU settings 26..29 (T1..T4 CHANNEL:
  1..16, OMNI = any channel no track has, OFF = none; 1..4 by default, so TRACK with the defaults is CH1-4). A channel
  two tracks have plays the first; a channel no track has is ignored as outside a block. Notes, bend, CCs (the CC
  map, CC1, the panic CCs), aftertouch and Program Change follow it; MIDI LEARN's CCs still set their own track (from
  any channel a track hears); the keys' MIDI out goes on the track's channel (OMNI / OFF: its CH1-4 one). `DESC` gives
  range 0..5. The channels are the project's, in FUN10's spare bytes (below: "MIDI IN TRACK in a project"); a project
  with TRACK stores id 14 as the block its channels make (channels 5..8 in order: CH5-8 ..), else CH1-4, so 1.5.1 and
  earlier (which never read those bytes) open it with that block.
  Neither setting affects this SysEx protocol or MIDI clock. The
  id, `G_COUNT` (27) and the project format are unchanged; it is saved and loaded with the project like
  the other globals. The editor shows it under GLOBAL > MIDI. 1.2: the GLO > GLOBAL and GLO > SYSTEM pages are
  gone; BPM, SWG and CLK (ids 0..2) are HOME > CLOCK's, TUNE (id 3) and ROUT (id 14) are edited in the MENU (AUDIO >
  TUNE, MIDI > MIDI IN; also MENU settings 22 and 21, below). Their ids, ranges, names and storage (the project) are
  unchanged. `G_MIDI`, `G_SYNC`, `G_INFO` (12, 13, 15) are on no page any more (MIDI's value was never read: the
  SYSTEM page's card showed the USB state; SYNC a placeholder; CPU a reading): the device's MENU > SYSTEM > INFO shows
  the USB state and the CPU load; `DESC` of them is unchanged.
- **Sound loads and undo.** A load that changes a track's sound (`PRESET`, `SET` of `G_ENGSEL`, `UP_LOAD`,
  and the same on the device) changes the sound only: the engine and the parameters of the sound. It
  never changes the steps, nor the track's own parameters: `P_LEVEL`, `P_PAN`, `P_MUTE` (0, 39, 40), the
  ARP pages, SCL and LEN / DIV / SWING / GATE (17..32), the SLICER (45..48). Since 1.1.5 it keeps motion when the engine stays the same; an engine change drops engine-specific records and keeps the others (see [MOTION](#cmd-64)). (Before 1.0 a preset also
  set the arp and replaced the steps with its pattern; a factory preset turned the SLICER off.) The byte
  layout of every command is unchanged. Patterns are loaded on the device (SAVE > PHRASES) or written by
  the editor with `STEP_SET` / `TRACK_STEP`.
  The device keeps one copy of the track from before the last load (any track); SAVE held 0.7 s on the
  device swaps back what the load changed (the sound; after a SAVE > PHRASES load, the steps and LEN / DIV
  / SWING / GATE). Loads in a row on one track with nothing changed between them keep the copy from before
  the first; `SET` (scope 0) within 1.5 s of a load on the selected track counts as part of that load, so
  an audition (`G_ENGSEL`, then the patch's values by `SET`, the track's own parameters skipped as
  `UP_LOAD` skips them) and the next one still undo to the state before the first. `PROJECT` load takes no
  copy.
- **Saves while playing.** A flash erase silences the audio and stalls the sequencer for a moment. The
  device refuses its own saves while the transport plays ("STOP TO SAVE"); `PROJECT` save, `UP_PUT`,
  `UP_STORE`, `UP_ERASE`, `BACKUP_LIST`, `BACKUP_PUT` and sample BEGIN / WRITE / END / ERASE from the editor stop the transport
  first (`BACKUP_GET` does not: it answers rc 3 while the transport runs). If it does not stop within 100 ms, no flash operation starts: user-preset commands
  return rc 2, sample commands a nonzero rc, backup commands rc 3. PROJECT retains its existing reply shape
  (op, slot, used); a failed PROJECT save gets no reply, allowing the editor to report
  a timeout instead of confirming the previous used slot. The previous slot is kept.
  A pending PLAY or SONG start also prevents a device save.
- **Published samples.** SMP_END repeated with an identical committed header succeeds without
  another write or zone scan. A different header is rejected (rc 2) until SMP_BEGIN,
  so sounding sample voices cannot see their zone table change.
- **Safety.** `PROJECT` save, sample-slot commands, `UP_PUT` / `UP_STORE` / `UP_ERASE`, and the tagged preference writes below write flash, and only in
  Felucca's own storage; never the app or the update area.

<a id="v6-song-chain"></a>
## Song playback

INFO appends CHAIN_ROWS (16) after NTRK. Earlier INFO bytes and command numbers
stay where they were. No trailing byte means no SONG command: hide its controls.

<a id="cmd-33"></a>
### 33 SONG

Available: v6. Request length (argument bytes): **1 for ops 0, 2..4, 6, 7; 2 + 2 × count for op 1; 2 + 5 × count for op 5**.

- Request: op 0 query; op 1 set, count 0..16, count × (slot 0..3, repeat 1..16); op 2 start; op 3 stop; op 4 query sections; op 5 set, count 0..16, count × (slot T1..T4 0..4, repeat 1..16); op 6 start; op 7 stop.
- Reply: op, rc, count, running 0/1, row 0..15, remaining repeats, count × (slot, repeat) for ops 0..3; count × (slot T1..T4, repeat) for ops 4..7.

An op 1 legacy-row set must have exactly `2 + count × 2` argument bytes. rc 0 = accepted,
1 = invalid rows (or an empty chain on start), 2 = busy, 3..6 = source slot 0..3
is empty. Rejected sets keep every previous row. Set edits RAM; PROJECT save
persists it, PROJECT load recalls it. A stop/start is acknowledged before the
next audio block; query reports the actual running state. `row` and `remaining`
are meaningful only while running. Legacy rows always start from 0, with track 1's
loop as the repeat and transition boundary; the last row stops.

A legacy row selects one project slot for all four tracks; current sections can select one per track. The
four sources are copied before starting, with no flash operation in playback.
Original editable patterns and timing are restored on stop. Sources are shared
project slots; overwriting a slot changes its uses on the next start.

STEP_GET / TRACK_STEP and WATCH report the playing source. During chain
playback, STEP_SET / TRACK_STEP writes, SET / TRACK_PARAM writes to
LEN / DIV / SWING / GATE and MOTION edits (rc 3) are ignored, returning the current value. Other
sound and mix parameters remain editable. Recording and panel pattern edits
also require STOP. Older editors keep working; older firmware gets no SONG
requests from the new editor.

A chain row also plays the motion of its source project (events for an FM operator parameter are skipped
when the track's engine is not the saved one).

<a id="12-song-sections"></a>
INFO advertises `57 01 4` (after `54 01 16`): `SONG` (33) has ops 4..7, ops 0..3 with sections instead of rows. A section
names the PROJECT slot each of the four tracks plays (0..3 = A..D, 4 = "-": the track plays nothing there) and its
repeats (1..16); up to 16 sections.

An op 5 section set must have exactly `2 + count × 5` argument bytes; rc as for ops 0..3 (1 = invalid sections, 2 = busy, 3..6 = a
slot a lane plays is empty; a silent lane needs none, a song of "-" only plays silence). Ops 0..3 keep their meaning: a
set (op 1) makes each row a section with the four tracks on its slot (a slot of 4 there is invalid, rc 1); their replies
list a row per section, the slot of its clock lane (below; every lane "-": 0) and its repeats, so an editor of before
sees the song's order but not its lanes, and a set from it makes the song lane-less again.

Playback: each track reads its own slot's steps (CHANCE, RATCH, NUDGE), automation and locks, LEN / DIV / SWING / GATE
and QUANTIZE, for that track only; the sounds stay current. Sections keep one boundary for all four tracks: a section
lasts `repeat` loops of its clock lane, the first track not "-" there (track 1 when it plays: every song of rows counts
as before); every lane "-": a 4/4 bar (16 × 1/16). At each section all four start together from their step 1. A "-"
lane releases its sequenced notes at the section's start and its automation goes back to the sound's own values; live
keys still play it. While a song plays, `SET` / `TRACK_PARAM` writes to LEN / DIV / SWING / GATE and QNTZ (94) are
ignored (the slots set them; STOP restores the editable values).

Unknown op or wrong non-set length: no reply. Malformed op 1/5 sets return rc 1 with the unchanged configuration.

<a id="tagged-device-preferences-v1"></a>
## Device preferences

INFO appends `0x55, 1, uiCaps` after the existing `NTRK, CHAIN_ROWS` bytes.
Only this complete tagged extension enables commands 34–38. An untagged byte
from an experimental firmware is not a SONG or preference capability.
Command 33 remains SONG. Older editors can ignore the additional INFO bytes.

`uiCaps`: bit 0 palette, bit 1 font weight (retired: firmware since the 1.0 UI has one
weight and no longer sets it), bit 2 MIDI monitor when compiled in, bit 3 favorites, bit 4 unified native UI, bit 5 one
native style. The standard build advertises 57 (palette, favorites, unified UI, one style). Bits 4 and 5 are
informational, not `UI_SET` slots: hide legacy MENU id 2 (LARGE) when bit 4 is present and legacy MENU id 1 (STYLE)
when bit 5 is present. Without them, retain the older firmware's controls. Unknown capability bits must be ignored.

<a id="cmd-34"></a>
### 34 UI_STATE

Available: INFO `55 01`. Request length (argument bytes): **0**.

- Request: none.
- Reply: caps, palette, font, monitor, filter, favoriteSig u28, bankSig u28.

<a id="cmd-35"></a>
### 35 UI_SET

Available: INFO `55 01`. Request length (argument bytes): **2**.

- Request: id, value.
- Reply: rc, id, value, UI_STATE payload.

Bad lengths are handled with rc 1, followed by echoed id/value (127 for absent fields) and the current state.

<a id="cmd-36"></a>
### 36 UI_PALETTES

Available: INFO `55 01`. Request length (argument bytes): **0**.

- Request: none.
- Reply: count, count × name string.

<a id="cmd-37"></a>
### 37 FAV_GET

Available: INFO `55 01`. Request length (argument bytes): **4**.

- Request: engine, start v14, count 1..32.
- Reply: rc; on success: engine, start v14, count, count × on/off.

Invalid range, engine or length: rc 1 only. Feature absent: rc 2 only. A range must fit entirely within that engine’s presets (user slots: 32).

<a id="cmd-38"></a>
### 38 FAV_SET

Available: INFO `55 01`. Request length (argument bytes): **4**.

- Request: engine, preset v14, on/off.
- Reply: rc; when applied: engine, preset v14, on/off.

Invalid engine/preset/length or on/off above 1: rc 1 only. Feature absent: rc 2 only. Clearing an empty user slot is allowed; marking one is not.

UI_SET ids: 0 palette (0..count-1, the order of UI_PALETTES: GREY GREEN AMBER ICE VIOLET ROSE PAPER
HI-CON NIGHT MONO; 1.0.2: GREY is the MONO of 1.0.1, MONO a new black and white palette; 1.6: CUSTOM last while one is stored), 1 font (retired: rc 2), 2 monitor (optional compile-time capability, values 0..2; unsupported in the standard build), 3 preset filter (0 all, 1 favorites). Unsupported state
fields are 127.
Both u28 signatures are four least-significant-first 7-bit bytes; compare them
to refresh changed favorites and user slots. Factory references use stable
engine/preset ids; engine 127 (#212: INFO's `49 01` block says it) denotes a user slot, and so does the old
marker, NENGINES (the count in INFO's prefix: standard 14, MACRO profile 15), which editors before #212 send. An empty user slot
cannot be marked. Factory DRUM sounds use the same favorite path. A reply echoes the engine byte as asked (127 or
the old marker). An engine id this build cannot play (DIGITAL's 1, an id past its table or left out of its catalog)
answers rc 1; its favourites stay in the settings, as stored.

rc 0 = applied and saved; 1 = invalid arguments; 2 = unsupported feature;
3 = applied in RAM but not saved (no flash or a failed write);
4 = applied and queued to save after STOP. A failed settings write is retried
by the same persistence path as the panel. These changes never stop playback.
Unchanged writes do not erase flash. Replies echo preference ids/values and
favorite ranges so the editor rejects replies to a different request.

<a id="v7-chance-motion-midi-clock"></a>
## Motion and parameter locks

<a id="cmd-64"></a>
### 64 MOTION

Available: v7. Request length (argument bytes): **1 (query); op 1: 3; ops 2, 7, 8: 2; ops 3, 5: 6; op 4: 4; op 6: 3**.

- Request: track (query); track, 1, on 0/1 (play on / off); track, 2 (clear); track, 3, step, id, v14 (set an event); track, 4, step, id (delete an event or a lock); (1.1) track, 5, step, id, v14 (set a lock); track, 6, step (clear the step's locks; step 127: every step's); track, 7 (query with the kinds); (1.2) track, 8 (every record, with the kinds).
- Reply: track, rc, on (0/1), count (this track's events and locks), max (64), then count × (step, id, v14); after ops 5..7 (1.1) then count × kind (0 automation, 1 lock), in the same order. 1.2: ops 1..7 list at most the track's first 64 records (count ≤ 64, max 64: as before); op 8 answers track, rc, on, count lo, count hi, max lo, max hi (two 7-bit bytes each, LSB first; max 128), count × (step, id, v14), count × kind.

- **Motion** is knob moves recorded per step: 128 records shared by the four tracks. An event is (track, step
  0..63, parameter id, value). While a track plays its motion, the step sets the value at the step and it
  holds until another step changes it; the loop restarts from the sound's own value, and stopping puts the
  sound's own values back. Parameters that can be recorded (`motion_param`): ids 0..16 (LEVEL, ENV, LFO),
  33..36 (DIST, CHO, DLY, REV), 38 (GLIDE), 39 (PAN), 44 (DETUNE), 61..80 (the FM operator parameters) and
  83..90 (the DRUM lane levels), 95 (SPREAD), 96..100 (INSERT) and P_E0..P_E7 (103..110; not the chord keys 81, 82). The device records them while the track is armed, playing and selected, from its knobs
  and from `SET` / `TRACK_PARAM` alike.
  - `MOTION` with the track alone is the query. `on` 0 keeps the data and stops playing it; 1 plays it. Clear
    drops the track's events and turns it off; on the device it is undone by SAVE held.
  - Set: `value` must be inside the parameter's range for that track's engine (and −64..127); a
    new event when the 128 are used gets rc 2 ("MOTION FULL" on the device), an event that already exists is
    updated. A set turns the track's motion on. A delete of an event that does not exist succeeds.
  - rc: 0 ok, 1 invalid (step ≥ 64, an id that cannot be recorded, a value outside its range), 2 full, 3 a song is playing.
    A track ≥ NTRK, `on` above 1 or any other length gets no reply.
  - Events come back in the order they are stored. The device does not push motion changes: poll `MOTION`
    (the web editor does, while the sequencer tab shows).
  - `DUMP`, `TRACK_DUMP`, a user preset store and a project save give the sound's own (base) values;
    `GET`, `SET` and the pushes give what is sounding now, which differs while a motion event is in effect.
  - A pattern load and a pattern clear on the device drop the track's motion; the device's UNDO brings it back.
    `MOTION` clear does the same through the same undo copy. A sound load (a preset, `PRESET`, `G_ENGSEL`, `UP_LOAD`,
    INIT SOUND) keeps it since 1.1.5 when the engine stays the same; when the engine changes the records on the
    engine's own ids (E1..E8 `P_E0..P_E7`, DIGITAL's 61..80, the DRUM lane levels) go and the rest (both kinds)
    stays, PLAY as it was (until 1.1 a sound load dropped the whole motion). Poll `MOTION` after a load.
  - The device's own lock edits (a step held + a knob, SEQ > AUTOMATION (1.1.5's AUTO LIST)) go through its UNDO; `MOTION` ops
    3..7 do not (the protocol is unchanged in 1.1.5).

### Parameter locks

INFO advertises `4C 01 1` after the ratchet tag (`52 01 4`). Firmware without it has no locks.

- A **lock** is a motion record (the same 128 shared by the four tracks, one per track, step and id, of either kind)
  whose value sounds on its step only. When the step plays (its chance passed; a step that does not play applies
  none of its locks) the value is set at the step's start, before its notes, and lasts the whole step (its ratchet
  parts too); the next step puts back what sounds without it: the latest automation event of that id at a step up
  to that one in this pass, else the sound's own value. An **automation event** (what the device records with REC
  armed) sets its value at its step and holds it, as before. The ids that can be locked are the ones motion can
  record (`motion_param`, see above); AUTOMATION's PLAY OFF bypasses locks too, its CLEAR clears them.
- `MOTION` 5 sets a lock (track, 5, step, id, v14): as op 3, the value inside the parameter's range for the track's
  engine, rc 2 when the 128 are used. A lock and an automation event on the same step and id are one record: op 3
  over a lock makes it an automation event, op 5 over an automation event makes it a lock. Op 4 deletes either
  kind. Op 6 (track, 6, step) removes that step's locks (step 127: every step's), its automation events stay.
  Op 7 (track, 7) is the query. Ops 5..7 reply as the query and then one kind byte per record, in the same order
  (0 automation, 1 lock); the query and ops 1..4 reply as before 1.1, where a lock reads as an automation event.
- Stored locks use bit 7 of a motion record’s id, with the parameter ID below it;
  see [project containers](#project-containers). Older parameter counts map IDs
  to current positions while preserving the lock bit. Every project before 1.1
  has no locks, though FUN7/FUN8 from 1.1 development builds may hold them.
  Firmware before 1.1 refuses records with locks, as it refuses newer formats.
- On the device: on SEQ > STEP hold a step and turn KNOB 1..4. The knobs lock the four parameters of the sound
  page shown last before (HOME's four, ENV, LFO, FX, EDIT 1 / 2, ..; the cards show them while a step is held). On
  the DRUM grid a step is its white key (several held: each gets the lock; a key pressed on a hit takes it away
  only when let go without a knob turned); on the piano roll the step being entered (its note keys held). [EDIT]
  tapped with a step held clears its locks; EDIT alone clears the step and its locks. The roll and the grid mark
  the steps that hold a lock; AUTOMATION shows the count (LOCK).

<a id="v7-full-backup-65-67"></a>
## Full backup (65-67)

<a id="cmd-65"></a>
### 65 BACKUP_LIST

Available: v7. Request length (argument bytes): **0, or 1 with argument 1 when INFO `58 01` bit 0 is set**.

- Request: — ; (#321, INFO `58 01` bit 0) 1.
- Reply: 1, rc, count (13 since 1.0.3, 12 up to 1.0.2, 11 before; with the argument 1: those 13 and the objects of #321, up to 15), then per object: id, size u32, crc u32. Any other argument: rc 1, count 0.

Other arguments return 1, 1, 0. Snapshot and restore rules follow below.

<a id="cmd-66"></a>
### 66 BACKUP_GET

Available: v7. Request length (argument bytes): **8**.

- Request: id, offset u32, count lo, count hi (≤ 256).
- Reply: id, rc, offset u32, count lo, count hi, pack7 data.

On error count is 0 and no data follows. With no id, the echoed id is 127. Stale/playing checks precede argument errors; see rc table below.

<a id="cmd-67"></a>
### 67 BACKUP_PUT

Available: v7. Request length (argument bytes): **op 0: 12; op 1: 7 + pack7 length (1..256 decoded bytes, 9..300 total); ops 2, 3: 2**.

- Request: op 0 begin: 0, id, size u32, crc u32; op 1 data: 1, id, offset u32, pack7 data; op 2 commit: 2, id; op 3 abort: 3, id.
- Reply: op, id, rc.

Malformed arguments return rc 1 unless an existing transfer’s stale check takes precedence for non-begin ops. Missing op or id is echoed as 127. See transaction rules below.

INFO advertises `42 01 caps`: bit 0 = `BACKUP_LIST` / `BACKUP_GET` (read), bit 1 = `BACKUP_PUT` (restore);
this firmware sends 3. Requests name objects, never flash addresses.

| id | object | size |
| --- | --- | --- |
| 0 | runtime: the music being played now, as a FUN10 project (1.1: FUN9, 3648; 1.0.x: FUN8, 3584; firmware before FM6: FUN7, 3388) | 3840 |
| 1 | settings (palette, speaker, HOLD time, favorites, panel calibration, ...) | the settings record's size: PER4's, or PER6's while a favourite is on an engine id from 14 (#212, "Engine ids") |
| 2..5 | PROJECT slots 1..4 (FUN10; 1.1: FUN9, 3648; 1.0.x: FUN8, 3584) | 3840, or 0 if empty |
| 6, 7 | user preset banks (slots 1..16, 17..32) | the bank's size, or 0 if empty |
| 8 | the FM6 patch bank of 1.0..1.0.2 (B1..B27). Since 1.0.3 always listed empty (see below) | 3472, or 0 if empty |
| 9 | the user presets' FM6 patches (1.0.3; `up_fm6.c`: per slot a tag and the packed patch) | 3728, or 0 if none |
| 32..34 | user sample slots 1..3: header (512 bytes) then ADPCM data | 512 + data length, or 0 if empty |
| 20 | (#321, `BACKUP_LIST 1` only) the FM6 voice bank (1.4.1, "FM6 voice bank"), as stored at 0xE7000: see below | 3616, or 0 if there is no bank |
| 21 | (#321, `BACKUP_LIST 1` only) the SLICE records of the user slots 1..3 (MAN slices, `src/slice_store.c`): see below | 472, or 0 if no slot has slices |

Reading: `BACKUP_LIST` (no arguments) stops the transport, then takes a snapshot of the runtime object and
answers `1, rc, count` (13 since 1.0.3, 12 with FM6 up to 1.0.2, 11 before) and, per object in the order above, `id, size u32, crc u32` (CRC-32, zlib). The other objects are read as
they are in RAM or flash. Then `BACKUP_GET` reads an object in pieces: `id, offset u32, count lo, count hi`
(count 1..256, LSB first 7 bit pair) answers `id, rc, offset u32, count lo, count hi` and the data as pack7. Check each object's CRC
against the list; if it differs the device changed, so start again.

Restoring: `BACKUP_PUT` takes ids 0..9 (firmware before 1.0.3: 0..8, id 9 answers rc 1 at begin and nothing is written) (the samples are written with `SMP_BEGIN` / `SMP_WRITE` / `SMP_END`,
or `SMP_ERASE` for an empty slot). Begin: `0, id, size u32, crc u32`: size is 3840 (FUN10), 3648 (FUN9), 3584 (FUN8) or 3388 (FUN7, FUN6) for id 0,
the settings record's size for id 1 (PER4's, or a PER6 of 64 rows or fewer: "Engine ids"), 3840, 3648, 3584, 3388 or 0 (empty the slot) for ids 2..5, the bank's size or 0 for 6 and 7,
3472 or 0 for 8 (the FM6 bank: its magic, layout and every byte below 128 are checked), 3728 or 0 for 9 (its magic,
version and slot count checked; 0 clears the patches). FUN9, FUN8, FUN7 and FUN6 become FUN10 (1.2; firmware before
1.2 refuses a 3840-byte project at begin, rc 1).
An archive without id 8 (written before FM6) still restores; the web editor reads all three kinds (11, 12, 13 objects).
Since 1.0.3 an id 8 with data (an archive of 1.0..1.0.2) is not stored: like the first boot after the update, every FM6
user preset whose stored SLOT is a B slot (8..34) and has no patch yet gets that bank slot's patch, and id 9 is written.
So restore ids 6 and 7 before 8 (the web editor does); an empty id 8 is taken and ignored (rc 0). Old archives
therefore restore on both old and new firmware; a 1.0.3 archive on older firmware loses only id 9 (the web editor
skips it when the device answers rc 1). Data: `1, id, offset u32, pack7` with the next offset (they must follow each other)
and at most 256 decoded bytes (256-byte pieces are fine at full speed, one request at a time: see "Notes for
the editor"; a piece that gets no reply was not taken: abort and begin the object again). Commit: `2, id`: the device checks the length and the CRC, validates the
content, and then writes. Abort: `3, id`. Id 0 replaces the music now playing (RAM only, no flash);
ids 1..9 are written to flash (settings and presets are applied too). Nothing is written before the commit.
The web editor sends ids 2..7 and the samples first, then 1, then 0 last (for the objects of #321, ids 20 and 21, see below: 21
after the samples). A failed restore can leave earlier objects restored; the file is still the source.

| rc | Meaning |
| --- | --- |
| 0 | ok |
| 1 | invalid: arguments, id, size, offset, count, or an id `BACKUP_PUT` does not take |
| 2 | validation failed: CRC, length or content at commit (and a runtime object that cannot be packed) |
| 3 | stop playback first (`LIST` and `PUT` stop it themselves, and answer 3 if it does not stop in 100 ms; `GET` answers 3 while it plays) |
| 4 | flash write failed |
| 5 | stale: no `LIST` yet, the USB bus was reset, 15 s with no `PUT` request, or a project save / load reused the staging RAM (for `GET`, of id 0 only). Start again with `LIST` / `BACKUP_PUT` begin |

`BACKUP_LIST` answers `1, rc, 0` when rc is not 0. `GET` and `PUT` answer id 127 when they got no arguments.
A `LIST` replaces the snapshot, and a `PUT` begin ends it: a `GET` after a begin gets rc 5.

### The FM6 voice bank and the SLICE records (#321, ids 20, 21)

Two stores that were outside the full backup are in it, behind a new capability so that existing editors see exactly
the list they know. INFO advertises `58 01 caps` (after the `49 01` block; #456's `59 01` follows it): bit 0 = `BACKUP_LIST` takes the
argument `1`, bit 1 = backup id 20, bit 2 = id 21. This firmware sends 7 (3 in a build without SLICE; 0 without the
flash store, which then answers like older firmware). `BACKUP_LIST` without an argument is unchanged: the 13 objects
of 1.0.3, ids 0..9 and 32..34, in that order. `BACKUP_LIST 1` takes the same snapshot and lists those 13 and then, in
this order, 20 and 21 (count 15). Ids 10..19 and 22..31 stay free (10..18 are planned for other objects,
[flash-capacity.md](../docs/flash-capacity.md)); an id without an object in this build answers rc 1. `GET`, `PUT` and the rc codes
are those above; both objects are at most 3840 bytes, and `PUT` begin takes exactly the size below or 0.

**Id 20, the FM6 voice bank** (`firmware/src/fm6_vbank.c`; the editor's own transfer is `FM6B_BEGIN / WRITE / END`,
cmds 74..77): the payload of the bank's commit record, byte for byte: the header at offset 0 (u32 `"FM6V"`
0x56364D46, u16 version 1, u16 voices 32, u32 used mask (bit k: voice B k+1 is there), 12 bytes of name (10 ASCII
bytes, space padded, then 0 0), two reserved u32 = 0; 32 bytes) and 32 voice slots of 112 bytes (a voice's 128-byte
packed record, 7-bit bytes, 8 to 7). A slot of a voice that is not there is 0xFF. The CRC is the CRC-32 of the 3616
bytes (the commit record's). `GET` reads the bank from flash, a piece at a time; if the
bank is replaced after the `LIST` (an `FM6B_END`, a restore) the next `GET` answers rc 5.
Restore (`PUT` 20, any time in the restore order) checks the whole object before it writes: size 3616, CRC, magic,
version 1 (a newer version is refused, rc 2), 32 voices, reserved words 0, a printable name, the slots of unused voices
erased. It then writes through the same path as `FM6B_BEGIN / WRITE / END`: the voices into the autosave's older
sector (the one `st_save` writes next, never the one the power-on restore reads), the commit record there last and only
after the voices' CRC matches, then the copy to 0xE7000 (erase, payload, commit record, read back). A power cut leaves
the old bank (nothing committed) or the new one (committed: the next power-on finishes the copy); never half of one,
and the autosave's current copy is never touched. The restore is one request on the main loop, so the autosave cannot
take the stage in between; an `FM6B` transfer that was open ends (its next `WRITE` / `END` answers rc 5). The tracks
that play a bank slot keep their voice as their own patch (SLOT OWN), as after `FM6B_END`. rc: 1 at begin for another
size, 2 for a refused object or a CRC that does not match, 4 for a flash error (the old bank stays).
**An empty object (size 0) is accepted and changes nothing**: the bank can only be replaced, not deleted, so an
archive without a bank never removes the device's.

**Id 21, the SLICE records**: SLICE's MAN slices (the slice starts set by hand on the SLICES page of the EDIT family) are the user's
work, kept per user slot in the last sector of the slot (`src/slice_store.c`). They are not rebuilt from the sample: the
AUTO slices are, the MAN ones are not, so they are backed up. The object is a header (16 bytes: u32 `"SLB1"`
0x31424C53, u16 version 1, u16 record size 152, u32 count 3, u32 0) and three 152-byte records, one per slot, little
endian, each as stored: u32 `"SLM1"` 0x314D4C53, u32 material length (samples), u32 the slot header's data CRC, u32 n
(1..32; 0 = none), u32 end (0 = the material's end), 32 × u32 slice starts (0 past n), u32 CRC-32 of the 148 bytes
before. A slot without slices, or whose sample leaves no room for the record (more than 77,312 bytes of ADPCM: its
slices only live until the power goes, "TOO LONG TO SAVE"), has the empty record (n 0, every field 0). The object is 0
bytes when no slot has slices. It is built from the slices in use, so it also holds edits not yet written to flash.
Restore (`PUT` 21) needs the samples first: **restore ids 32..34 (`SMP_BEGIN / WRITE / END`) before id 21.** The
whole object is checked before anything is written: size 472, CRC, header (a newer version is refused), every record's
CRC, and for each record with slices the sample that is in its slot now (same length and data CRC, room for the record)
and starts that fit it (sorted, 64 samples apart, inside the material). Any failure (rc 2, also a slot whose sample is
not there yet or is another) writes nothing and applies nothing. Then each record with slices is written to its slot's
last sector (erase, program; skipped if the flash already holds it) and put in use. Each record stands alone: a power
cut loses that slot's slices (the CRC fails), never its sample, and no sample byte is touched. rc: 1 at begin for
another size, 2 refused, 4 flash error (slots before it are done). **An empty object, or an empty record, changes
nothing**: slices are never deleted by a restore.

**Older firmware.** Firmware without this change does not send `58 01`, answers `BACKUP_LIST` with an argument rc 1
(`1, 1, 0`: send the plain `LIST`, as the web editor does for any capability it lacks), and answers `BACKUP_PUT` begin
of 20 / 21 rc 1 (nothing written; firmware before 1.4.1 has no voice bank at all). An editor skips the two objects of
an archive on rc 1, as it skips id 9 on firmware before 1.0.3. Nothing in flash changes format: the bank has been
at 0xE7000 since 1.4.1 and the records in the slots' last sectors since SLICE's MAN slices, so a downgrade keeps both,
and older firmware reads them as it always did. An archive with ids 20 / 21 restored there loses only those two objects.

**Felucca-WebApp (follow-up, #305).** Existing clients are unaffected: they send `LIST` without an argument and
get the 13 objects. The in-repo reader (`web/fm1backup.js`) refuses a manifest with a count other than 11, 12 or 13,
which is why the new ids are behind `LIST 1` rather than appended to every list. A client that wants the two objects
reads INFO's `58 01` (bit 0 for `LIST 1`, bits 1 and 2 for the ids), asks `LIST 1`, reads 15 (or 14) objects with
`GET` as the others, and keeps them in the archive under their ids; an archive may have 13, 14 or 15 objects. On restore
it sends 20 any time and 21 after the samples, and skips an object on rc 1. The client does not need to understand the
bytes (they are kept as they are); the device validates them.

## FM6 patches (68-71)

The FM6 engine (12) plays a 6-operator patch per track; its eight EDIT parameters are macros on top of it
(ALG 0 = the patch's algorithm, 1..32 another; FB, MLVL, MRAT, MEG, VMOD offsets; DTUN; SLOT). The patch itself
only travels through these commands. INFO advertises `46 01 nfactory nbank` after the backup tag (1.0.3:
`46 01 08 00`; 1.0..1.0.2: `46 01 08 1B`); firmware without it has no FM6 and does not answer 68..71.
After it, `53 01 caps` (live sync, v2 above): bit 0 = `WATCH` while watching keeps what is not pushed yet,
bit 1 = no `RELOAD` after the editor's own `PRESET` / `SET` of G_ENGSEL. This firmware sends 3.
Then (1.0.3) `50 01 caps`, FM6 v2: bit 0 = no patch bank (SLOT is F1..F8 = 0..7 and 8 = OWN; the bank target
answers rc 3), bit 1 = user presets carry their patch (target 3; backup id 9). This firmware sends 3. Firmware
without the tag has the bank and SLOT 0..34 (F1..F8, B1..B27): an editor should not offer the bank either way.

SLOT (P_E0 + 7), since 1.0.3: 0..7 load that factory patch into the track; 8 (OWN) is the track's own patch (what
a project, a user preset, a converted DIGITAL sound or an FM6_PUT to the track put there). Every such load sets SLOT
to F n when the patch is that factory patch unchanged, else OWN, and nothing reloads over it. Setting SLOT from OWN
to F n keeps the own patch aside; setting it back to OWN brings it back. 1.4.1: 9..40 (B1..B32) load a voice of
the voice bank (below) the same way; a `SET` to a bank slot without a voice is refused (SLOT goes back to the value
it had: a `GET` or the `CHANGED` push shows it), and the device's knob passes over such slots. SLOT is never stored as
a bank slot: a stored 9..40 (in a project, a user preset or a motion record; 1.0.2 wrote 8..34 for its B1..B27) loads
as 8, OWN, with the patch that came with it (DESC: SLOT max 40; firmware before 1.4.1: 8).

Since 1.2 the device edits the patch too (EDIT > OPERATOR, OP ENV, OPERATOR 2: an operator's coarse / fine
frequency, output level, mode, detune, velocity sensitivity, R1..R4 and L1..L4). Each such edit writes that byte of
the track's patch and sets SLOT to 8 (OWN), which the editor sees as any SLOT change; the patch it holds for the
track may then be stale: read it again with `FM6_GET` (target 0). Nothing new on the wire: no command, parameter
id or INFO tag (the operator values are the patch, not parameters: no `SET`, no automation).

A patch is the 128-byte packed record of the generic 6-operator voice (the 32-voice bank's record; every byte is
7-bit, so it travels as it is, no pack7). Operators come sixth first: per operator 17 bytes (R1..R4, L1..L4,
break point, left / right depth, curves `LC | RC << 2`, `RS | DET << 3`, `AMS | KVS << 2`, output level,
`MODE | FC << 1`, fine), then pitch EG rates and levels (102..109), algorithm 0..31 (110), `FB | OKS << 3`,
LFO speed, delay, PMD, AMD, `SYNC | WAVE << 1 | PMS << 4`, transpose (24 = none), the name (10 ASCII bytes).
The device stores every value clamped into its range.

<a id="cmd-68"></a>
### 68 FM6_GET

Available: INFO `46 01`. Request length (argument bytes): **2**.

- Request: target, index.
- Reply: target, index, rc, then (rc 0) the 128 bytes.

Wrong length returns rc 1 with target/index echoed as 127 if absent. Success has 131 reply bytes; errors have 3.

<a id="cmd-69"></a>
### 69 FM6_PUT

Available: INFO `46 01`. Request length (argument bytes): **130**.

- Request: target, index, the 128 bytes.
- Reply: target, index, rc.

Wrong length returns rc 1. Target 2 is read-only and returns rc 1 for PUT.

<a id="cmd-70"></a>
### 70 FM6_LIST

Available: INFO `46 01`. Request length (argument bytes): **0**.

- Request: —.
- Reply: nfactory, nbank, then per slot (factory first): used (0/1), name string ("" if empty); 1.0.3: nbank 0, the factory patches only.

A nonempty request gets no reply.

<a id="cmd-71"></a>
### 71 FM6_ERASE

Available: INFO `46 01`. Request length (argument bytes): **1**.

- Request: bank index.
- Reply: index, rc (1.0.3: 3, no bank).

Any one-byte index returns rc 3 (retired bank); wrong length returns rc 1, with index 127 if absent.

target:
- 0 a track's own patch (index 0..3: what it plays and what its project saves). A PUT is heard at once; SLOT becomes
  OWN (F n if it is that factory patch unchanged), and the device does not reload a factory patch over it.
  A PUT to a track that runs another engine is accepted and kept as the track's latent FM6 patch (no format or
  reply change); whenever the track plays FM6 again, the audio side builds its copy from the patch published at
  that time, however many PUTs came meanwhile (#419).
- 1 the patch bank. 1.0..1.0.2: index 0..26 = B1..B27 in flash (A 0x9F000, B 0xFE000; backup id 8). Since 1.0.3:
  GET, PUT and ERASE answer rc 3 ("no bank") and change nothing; LIST reports nbank 0.
- 2 a factory patch (0..7, GET only).
- 3 a user preset's patch (1.0.3; index 0..31 = U01..U32). It is kept beside the record and counts only for an FM6
  record as it was when the patch was stored (a rename keeps it; an `UP_PUT` that changes the record, `UP_ERASE` or another store
  drops it). `UP_STORE` / SAVE of an FM6 track stores the track's patch with it; `UP_LOAD` plays it. GET: rc 2 when
  the slot has none (not an FM6 sound, or stored without one: it then loads SLOT's factory patch, or the init voice
  for OWN). PUT (after an `UP_PUT` of the record): rc 1 when the slot is not a used FM6 record; it writes flash (stops
  the transport, allow 1 s).

rc: 0 ok, 1 arguments (an unknown target, an index out of range, a record that is not 128 bytes), 2 empty (GET) or a
flash error / transport that did not stop (PUT), 3 no bank (1.0.3, target 1 and ERASE). A target-3 PUT without flash keeps its patch in RAM and reports rc 0; this reply does not establish durability.

The web editor (6-OP FM tab) imports the generic SysEx files of the format: a single voice `F0 43 0n 00 01 1B`, the
155-byte unpacked voice, checksum, `F7` (163 bytes), and 32 voices `F0 43 0n 09 20 00`, 32 x 128 packed, checksum,
`F7` (4104 bytes); the checksum is the two's complement of the data's sum, 7 bits. Raw 155 / 4096-byte files are
read too. Pick a voice, edit it, send it to a track (target 0); to keep it, SAVE it as a user preset (or save the
project) on the device. It exports single voices. Its librarian reads and writes a user preset's patch (target 3)
with the record when the firmware has FM6 v2 bit 1, and keeps it in library files as `fm6` (128 numbers).

## MENU settings (72, 73; 1.0.4)

The device describes the settings of its MENU (HOME held) to the editor, which builds its settings from what it
is told: no list of settings is fixed in the editor. INFO advertises `4E 01 count` after the FM6 v2 tag
(`50 01 caps`): `count` items, MENU_DESC index 0..count−1. Firmware without the tag answers neither command.

<a id="cmd-72"></a>
**Retired native style choice (#572):** MENU index/id 1 remains STYLE with its historical FLAT/LINE values, clamp
behaviour and settings byte (`settings_dev[29]`). Both values now draw the same native rule style, and the native
DISPLAY tab skips that row. `MENU_SET` still stores the value; downgrading restores the last saved style. Current
clients use tagged `uiCaps` bit 5 to hide this control.

**GRAPH (#572, id 34):** what the panel shows where the live scope is drawn (HOME's SCOPE view and engine pages
without a graph of their own). SCOPE always the scope; TURN the turned knob's filter or envelope curve while it turns
and about a second after, then the scope; CURVE the focused knob's curve (else the filter's, else the amplifier
envelope) with a small scope strip; STILL the same curve without the scope. Stored in bits 1–2 of `settings_dev[10]`
(ANIM IDLE's byte, bit 0 unchanged) with 0 meaning TURN, so every older setting reads TURN. Older firmware ignores
the bits and keeps them as saved.

**Retired native size choice (#578):** MENU index/id 2 remains LARGE with its
historical OFF/ON values, clamp behavior and settings bit (`settings_dev[30]`
bit 5). Both values now draw the same native UI, and the native DISPLAY tab skips
that row. Legacy `MENU_SET` still stores the requested bit through the same
coalesced/deferred settings path; it never assigns focus or changes another ID.
Imports/exports retain this bit and all other settings bytes. Downgrading restores
the last saved historical size choice. Current clients use tagged `uiCaps` bit 4
to hide this retired control; older clients can still read/write it harmlessly.
The client display adaptation is tracked separately in
[#582](https://github.com/kmplngj/Felucca/issues/582).

### 72 MENU_DESC

Available: INFO `4E 01` (1.0.4). Request length (argument bytes): **1**.

- Request: index (0..count−1).
- Reply: index, id, kind, value v14, min v14, max v14, name string, then for kind 0 (max−min+1) value-name strings, for kind 1 a unit string; then (1.0.5) tab, tab-name string. An index past the list: index, 127 (no more bytes).

Out-of-range index returns index, 127. Wrong length gets no reply.

<a id="cmd-73"></a>
### 73 MENU_SET

Available: INFO `4E 01` (1.0.4). Request length (argument bytes): **3**.

- Request: id, value v14.
- Reply: rc, id, value v14: the device's value after the write (clamped to min..max).

Unknown id returns rc 1 and echoes the requested id/value. Other values clamp to the item’s range. Conflicting AUTO OFF / ALL DARK timer order returns rc 2 and the unchanged actual value; no setting is applied or saved. Wrong length gets no reply.

- **index** is the position in the device's list: up to 1.0.5 the menu's order; from 1.1 a new setting is appended
  (index = id), whatever tab it shows in, so an index keeps the setting it had and an older editor lists the ones it
  knew where they were. Shown by tab (below), each tab's items in index order, they appear as on the device. **id**
  names the setting and never changes its meaning: a new setting takes a new id (append-only), wherever it shows in
  the menu. Ids are 0..126; 127 means "no item". Remember settings by id, not by index.
- **kind**: 0 an enum (the value is an index into the names, min..max), 1 a number (min..max, its unit after the
  name; 1.2: TUNE, id 22, -50..50 "ct", the first). An editor shows a kind it does not know read-only, or not at all.
- Values are v14 like the rest of the protocol, so a setting may go past 127 or below 0; up to 1.2's TUNE every value
  was 0..9.
- **rc** as `UI_SET`: 0 applied and saved, 3 applied in RAM only (no flash or a failed write; retried by the
  settings path), 4 applied and saved after STOP; 1 an unknown id (the request's id and value are echoed,
  nothing changes); 2 rejects an inconsistent AUTO OFF / ALL DARK timer order and returns the unchanged actual value. A value out of range is not refused: it is clamped and the reply says which value the device
  took. A wrong argument length gets no reply. 1.2: MIDI IN (21) and TUNE (22) answer rc 0: they are not settings
  but the current project's `G_ROUTE` and `G_TUNE` (global ids 14 and 3), set as a `SET` of that global sets them
  (a `GET` / `DUMP` reads the same value, the device pushes `CHANGED` for it while WATCHing); they are kept with the
  project (PROJECT SAVE, the autosave), not in the settings record, and a project load brings its own values.
- A MENU_SET is applied exactly as the menu's KNOB 1 / OCT+ applies it (`src/menu_items.c` `menu_put`, shared by
  both), and saved through the same settings record (`settings_save`; unchanged values write nothing; MIDI IN and
  TUNE: the project's, above). If the
  device shows the MENU page, it redraws with the new value. There is no push: an editor that wants to follow
  changes made on the device reads MENU_DESC again (for instance when its settings page opens).
- CALIBRATION, INFO (1.2) and ABOUT have no value and are not offered. COLOR (id 0) is the same setting as `UI_SET` id 0.
- **tab** (1.0.5): the MENU shows its settings in tabs (ALGORITHM steps between them on the device). After the
  names (kind 0) or the unit (kind 1) the reply carries the item's tab: its index (0.., the device's tab order,
  left to right) and its name (≤ 12 characters). An editor that wants the device's grouping shows the items by tab,
  in tab-index order, each tab's items in index order; the tab names come from the device, as the item names do.
  Firmware 1.0.4 ends the reply after the names: no tab (show the items as one list). An editor written for 1.0.4
  reads exactly the names and ignores what follows, so the tab changes nothing for it. Tab indexes are not ids: an
  item may move to another tab in a later firmware, and tabs may be added (1.2: MIDI, index 3, came in before SYSTEM,
  whose index went from 3 to 4); remember settings by id and show the tabs by the names the device gives.
  A tab may hold items with no value that are not offered (this firmware: SYSTEM also holds CALIBRATION, INFO and
  ABOUT).
  For a kind it does not know, an editor cannot find the tab (it does not know that kind's bytes).

This firmware (count 33; tabs 0 DISPLAY, 1 CONTROL, 2 AUDIO, 3 MIDI, 4 SYSTEM (1.2; before: 3 SYSTEM); 1.0.5 had the
first 12, 1.1 the first 15, 1.2 before SCALE LEDS the first 16, before SCREEN OFF the first 17, 1.1.5 the first 18, 1.2
before MIDI IN the first 21, 1.2 the first 23, 1.3 / 1.4 the first 24, 1.5 / 1.5.1 the first 25, 1.5.5 .. 1.6 the first
32; a FELUCCA_CPU2=0 build of 1.6.1 too):

| index | id | name | kind | values (min 0) | default | tab |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 | COLOR | 0 | 0..9: GREY GREEN AMBER ICE VIOLET ROSE PAPER HI-CON NIGHT MONO (the order of `UI_PALETTES`); 1.6: 10 CUSTOM while one is stored (CUSTOM palette, cmds 80, 81) | GREY | 0 DISPLAY |
| 1 | 1 | STYLE | 0 | 0 FLAT, 1 LINE (#572: retired; both draw the one native rule style, see below) | FLAT | 0 DISPLAY |
| 2 | 2 | LARGE | 0 | 0 OFF, 1 ON | OFF | 0 DISPLAY |
| 3 | 3 | ANIM | 0 | 0 ON, 1 OFF, 2 IDLE (1.2: ON plus the LEDs' idle animation; firmware before: max 1) | ON | 0 DISPLAY |
| 4 | 4 | LEDS | 0 | 0 OFF, 1 DIM LO, 2 DIM HI, 3 INV (darkest first, as the menu steps them); 1.5.6 (#212): 4 INV LO, 5 INV HI (INV with the idle LEDs at a steady low level: appended) | DIM HI | 0 DISPLAY |
| 5 | 5 | HOLD | 0 | 0 "0.3 s", 1 "0.4 s", 2 "0.5 s", 3 "0.6 s" | 0.4 s | 1 CONTROL |
| 6 | 6 | KNOB ACCEL | 0 | 0 OFF, 1 ON | OFF | 1 CONTROL |
| 7 | 7 | FX LATCH | 0 | 0 OFF, 1 ON | OFF | 1 CONTROL |
| 8 | 8 | BPM LOCK | 0 | 0 OFF, 1 ON | OFF | 1 CONTROL |
| 9 | 9 | SPEAKER EQ | 0 | 0 FLAT, 1 LOWCUT, 2 BASS+ | FLAT | 2 AUDIO |
| 10 | 10 | USB LEVEL | 0 | 0 MASTER, 1 FIXED | MASTER | 2 AUDIO |
| 11 | 11 | USB SERIAL | 0 | 0 ON, 1 OFF | ON | 4 SYSTEM (up to 1.2's MIDI tab: 3) |
| 12 | 12 | CLICK | 0 | 0 OFF, 1 REC, 2 ON (1.1) | OFF | 2 AUDIO |
| 13 | 13 | CLICK LEVEL | 0 | 0 LOW, 1 MID, 2 HIGH (1.1) | MID | 2 AUDIO |
| 14 | 14 | COUNT-IN | 0 | 0 OFF, 1 "1 BAR", 2 "2 BARS" (1.1) | OFF | 2 AUDIO |
| 15 | 15 | RESTORE LAST | 0 | 0 ON, 1 OFF (1.2) | ON | 4 SYSTEM (up to 1.2's MIDI tab: 3) |
| 16 | 16 | SCALE LEDS | 0 | 0 OFF, 1 ON (1.2) | OFF | 1 CONTROL |
| 17 | 17 | AUTO OFF | 0 | 0 NEVER; 1–4 SCREEN 5m/15m/30m/60m; 5–8 LEDS 5m/15m/30m/60m; 9–12 BOTH 5m/15m/30m/60m | NEVER | 0 DISPLAY |
| 18 | 18 | SCOPE | 0 | 0 OUT, 1 MIX (1.2) | OUT | 0 DISPLAY |
| 19 | 19 | STEP PREVIEW | 0 | 0 OFF, 1 ON (1.2) | OFF | 1 CONTROL |
| 20 | 20 | CHORD ENTRY | 0 | 0 HOLD, 1 ADD (1.2) | HOLD | 1 CONTROL |
| 21 | 21 | MIDI IN | 0 | 0 CH1-4, 1 SEL, 2 CH5-8, 3 CH9-12, 4 CH13-16 (1.2: the project's `G_ROUTE`, global 14), 5 TRACK (1.5.5) | CH1-4 | 3 MIDI |
| 22 | 22 | TUNE | 1 | -50..50, unit "ct" (1.2: the project's `G_TUNE`, global 3, cents) | 0 | 2 AUDIO |
| 23 | 23 | HOME | 0 | 0 SCOPE, 1 TRACKS (1.3), 2 LEVELS (1.5; before: max 1) | SCOPE | 0 DISPLAY |
| 24 | 24 | HELP | 0 | 0 OFF, 1 ON (1.5) | OFF | 4 SYSTEM |
| 25 | 25 | SELECT | 0 | 0 BPM, 1 PAGE (1.5.5); 1.5.6 (#84): 2 MODW (the selected track's mod wheel, CC1 out), 3 VEL (the keys' velocity) | BPM | 1 CONTROL |
| 26 | 26 | T1 CHANNEL | 0 | 0..15 "1".."16", 16 OMNI, 17 OFF (1.5.5: the project's, MIDI IN TRACK's) | 1 | 3 MIDI |
| 27 | 27 | T2 CHANNEL | 0 | as T1 CHANNEL | 2 | 3 MIDI |
| 28 | 28 | T3 CHANNEL | 0 | as T1 CHANNEL | 3 | 3 MIDI |
| 29 | 29 | T4 CHANNEL | 0 | as T1 CHANNEL | 4 | 3 MIDI |
| 30 | 30 | AUTO SELECT | 0 | 0 OFF, 1 ON (1.5.5) | OFF | 3 MIDI |
| 31 | 31 | WAKE | 0 | 0 +MIDI, 1 PANEL (1.5.5; formerly SCREEN WAKE) | +MIDI | 0 DISPLAY |
| 32 | 32 | 2ND CORE | 0 | 0 OFF, 1 ON (BETA) (1.6.1, Discussion #141: the second core renders some of the parts; from the next power-on) | OFF | 4 SYSTEM |
| 33 (32 without CPU2) | 33 | ALL DARK | 0 | 0 NEVER; 1–4 5 MIN/15 MIN/30 MIN/60 MIN | NEVER | 0 DISPLAY |
| 34 (33 without CPU2) | 34 | GRAPH | 0 | 0 SCOPE, 1 TURN, 2 CURVE, 3 STILL (#572) | TURN | 0 DISPLAY |

The device's AUDIO tab shows SPEAKER EQ, USB LEVEL, CLICK, CLICK LEVEL, COUNT-IN and (1.2) TUNE (index 9, 10, 12, 13,
14, 22).
CLICK: the metronome while the transport runs: OFF, REC (while a track is armed), ON (always); CLICK LEVEL its
level; COUNT-IN: PLAY from stop with a track armed counts in that many bars first (internal clock only). The click
goes to the headphones / speaker, never into USB audio or a recording (README: Metronome and count-in). Applied at
once, as on the device.

RESTORE LAST (id 15, 1.2; the SYSTEM tab shows USB SERIAL and RESTORE LAST, index 11 and 15, then CALIBRATION, INFO
and ABOUT): ON (the default)
keeps the music as it is in an autosave while the device is stopped and idle, and brings it back at power-on; OFF
writes no autosave and starts with the power-on sounds (README: Restore the last session).

SCALE LEDS (id 16, 1.2, Discussion #127; the CONTROL tab shows HOLD, KNOB ACCEL, FX LATCH, BPM LOCK and SCALE LEDS,
index 5..8 and 16): ON shows the selected track's scale on the key LEDs outside the layers (README: Key LEDs).
Applied at once.

AUTO OFF (id 17, originally SCREEN OFF) retains its combined enum: values 0–4
mean NEVER and SCREEN 5/15/30/60m; 5–8 mean LEDS and 9–12 BOTH at those delays.
The native AUTO OFF detail page splits time and target into IDLE AFTER / IDLE MODE;
clients can keep the compatible combined row. WAKE (id 31) moves from MIDI to
DISPLAY without changing values. ALL DARK (id 33) adds an independent threshold,
0 NEVER or 1–4 for 5/15/30/60 MIN. ID 32 remains reserved for 2ND CORE: in a CPU2-off
build descriptor index 32 returns id 33. Discover by index, then write by returned ID.

Both thresholds count total time since the same last qualifying input, not an
additional delay after stage 1. When both are nonzero, ALL DARK must be later;
a conflicting MENU_SET to id 17 or 33 returns rc 2 and the unchanged actual value,
with no save. Either stage may independently be NEVER. A successful timer/mode
change restarts inactivity and wakes obsolete LCD sleep.

Panel button/key presses or holds and encoder turns count as activity, excluding
MASTER and ordinary editor traffic. WAKE +MIDI (id 31, default) also counts routed
MIDI IN note-ons; PANEL ignores those notes for wake. Clock/CC/SysEx do not count.
Audio, sequencing, MIDI, USB and input scanning continue. LEDS-only first-stage
wake acts normally; a sleeping LCD consumes its panel wake gesture through release
and 0.3 s encoder rest. MIDI notes continue sounding normally. Dialogs, count-in,
update and emergency visibility retain their existing safeguards.

First-stage LED darkness overrides ANIM IDLE and all ordinary LED maps, leaving
one low-level 120 ms rotating piano-key pulse every 30 s, starting 30 s after entry.
ALL DARK suppresses that pulse too and sleeps the LCD regardless of IDLE MODE.
This candidate requests optional LCD-controller backlight-off without disabling
PA2. Physical backlight darkness and wake reliability remain unverified; no
power-saving claim follows from host/emulator results.

Settings byte [15][27] keeps historic timer codes 0,2,1,4,7 in bits 0–2 and target
SCREEN=0/LEDS=1/BOTH=2 in bits 3–4. Bits 5–7 store ALL DARK index 0–4. A target can
be remembered while its timer is NEVER; unknown target/timer combinations normalize
safely and unknown/conflicting ALL DARK disables that stage. Historical bytes 0–7
retain their interpretation. Record/backup sizes are unchanged; older readers
without ALL DARK reject its high bits and fall back to NEVER. See the
[control and combined test guide](../docs/display-idle.md).

SCOPE (id 18, 1.2, Discussion #165; DISPLAY now shows COLOR, STYLE, LARGE, ANIM, LEDS, SCREEN OFF and SCOPE, index
0..4, 17, 18): what HOME's oscilloscope draws. OUT (the default, as before) the sound after MASTER, so it shrinks with
the volume; MIX the mix before MASTER (and before the FX layer, SPEAKER EQ and the limiter), drawn at the size MASTER
at its top would give, whatever the knob. The metronome's click is in neither. Applied at once.

STEP PREVIEW (id 19, 1.2, Discussion #169) and CHORD ENTRY (id 20, 1.2, #155; CONTROL now shows HOLD, KNOB ACCEL, FX
LATCH, BPM LOCK, SCALE LEDS, STEP PREVIEW and CHORD ENTRY, index 5..8, 16, 19, 20). STEP PREVIEW ON: on SEQ > STEP
(the piano roll and the DRUM grid) with the transport stopped, moving the cursor with KNOB 1 or PRESETS (or the
grid's page keys) plays the step it lands on once on the selected track, through its sound (a 1/16 at the track's
GATE); never while playing, and it never writes. CHORD ENTRY ADD: in step recording (STEP, stopped, the track armed)
each key adds its notes to the cursor step (up to 4) or takes them out when its note is there already, and letting
go does not move the cursor (KNOB 1 / PRESETS move it); HOLD (the default) is the keys held together writing the step
and moving on, as before. The editor's own step editing (`STEP_SET`) is not affected by either. Applied at once.

MIDI IN (id 21, 1.2; the MIDI tab, its only row) and TUNE (id 22, 1.2; AUDIO's last row): the project's MIDI IN
routing and tuning, edited up to 1.1.5 on GLO > SYSTEM (ROUT) and GLO > GLOBAL (TUNE), the same values as globals 14
and 3 (see Global ids and rc above). TUNE is the first kind 1 item: value, min -50 (`4E 3F`), max 50 (`32 40`), the
name, then the unit "ct" (no value names), then the tab. Applied at once (MIDI IN: a block that changes lets go of the
notes it held, as the knob did; TUNE: the next block of sound).

T1..T4 CHANNEL (ids 26..29, 1.5.5, #202; the MIDI tab after MIDI IN): MIDI IN TRACK's channel of each track, the
project's like MIDI IN (rc 0: kept with the project, not in the settings record). Values 0..15 are channels 1..16, 16
OMNI (any channel no track has), 17 OFF (the track hears none); the default of track k is channel k (value k - 1).
They only route with MIDI IN TRACK (value 5); the device shows them dim otherwise. Applied at once: what the old
channel held is let go.

AUTO SELECT (id 30, 1.5.5, #208; the MIDI tab after T4 CHANNEL; a setting, saved as the others): ON, MIDI IN notes into a
track that is not selected select it, unless the selected track had notes in the last 250 ms (two tracks played
together, a chord across tracks: the selection stays) or the last such switch was less than 250 ms ago; never with MIDI
IN SEL, nor while the device's menu or a layer is up. The editor is told as for any track change. Whatever the setting,
a MIDI IN note lights its track's number cushion for about 90 ms (the header, HOME TRACKS / LEVELS, the MIXER).

WAKE (id 31, formerly SCREEN WAKE) is displayed in AUTO OFF's native detail page
and descriptor group DISPLAY. Values remain +MIDI (0, default) and PANEL (1), using
bit 5 of the existing flags byte, set for PANEL. Older records read +MIDI; older
firmware keeps the bit. It applies to both inactivity stages, including ALL DARK,
without changing MIDI note playback. Accepted routed USB/TRS note-ons count;
clock, CC, pitch bend, aftertouch, note-offs, Program Change, SysEx and unheard
channels do not. With both stages at NEVER there is no timed darkness to wake.

MIDI IN TRACK in a project (FUN10, no format change): the last 3 of the 16 spare bytes before the FM6 patches
(`PROJ_MIDI_OFF` = 3309), 24 bits little-endian. Bits 5k..5k+4: track k's channel as stored, 0..15 = the channel
(k + v) mod 16 (so 0, what every older project holds, is channel k + 1), 16 OMNI, 17 OFF (18..31: read as 0); bit 23:
MIDI IN is TRACK (then global 14 holds the fallback block, see Global ids). Covered by the project's hash as the rest.

Historical example (1.0.5 layouts, bytes in hex; current names/ranges come from MENU_DESC): `F0 7D 46 4C 48 04 F7` asks for index 4; the reply
`F0 7D 46 4C 48 04 04 00 02 40 00 40 03 40 4C 45 44 53 00 4F 46 46 00 44 49 4D 20 4C 4F 00 44 49 4D 20 48 49 00 49 4E 56 00 00 44 49 53 50 4C 41 59 00 F7`
is index 4, id 4, kind 0, value 2 (`02 40`), min 0 (`00 40`), max 3 (`03 40`), "LEDS", then "OFF" "DIM LO"
"DIM HI" "INV", then tab 0 "DISPLAY" (1.0.4 firmware: the same reply without `00 44 49 53 50 4C 41 59 00`). `F0 7D 46 4C 49 04 03 40 F7` sets LEDS to INV and answers `F0 7D 46 4C 49 00 04 03 40 F7` (rc 0).
`F0 7D 46 4C 49 00 32 40 F7` (COLOR 50) answers `F0 7D 46 4C 49 00 00 09 40 F7` (clamped to 9, MONO).
`F0 7D 46 4C 49 0E 01 40 F7` sets COUNT-IN to 1 BAR and answers `F0 7D 46 4C 49 00 0E 01 40 F7` (1.1).
`F0 7D 46 4C 49 16 74 3F F7` (TUNE -12) answers `F0 7D 46 4C 49 00 16 74 3F F7` (rc 0, 1.2).
`F0 7D 46 4C 48 22 F7` answers `F0 7D 46 4C 48 22 7F F7` (no index 34; without CPU2 the list ends at index 33, with ALL DARK id33 at index32; before ALL DARK, index33 did not exist and index32 existed only with FELUCCA_CPU2; 1.5.5 before SCREEN WAKE: none past 30, `1F`; 1.5 / 1.5.1: none past 24, `19`; 1.3 / 1.4: none past 23, `18`; 1.2: none past 22, `17`; before MIDI IN: none past 20, `15`; before SCOPE: none past 17, `12`; before SCREEN OFF: none past 16, `11`; 1.2 before SCALE LEDS: none past 15, `10`; 1.1 firmware: none past 14, `0F`; 1.0.5: none past 11, `0C`).

HOME (id 23, 1.3, Discussions #112 / #134; DISPLAY now shows COLOR, STYLE, LARGE, ANIM, LEDS, SCREEN OFF, SCOPE and
HOME, index 0..4, 17, 18, 23): what the device's HOME page shows under its four cards. SCOPE (the default, as before)
the oscilloscope; TRACKS the four tracks as rows: each track's cushion, engine icon and sound name, the 16 steps of its
pattern's page that plays (LEN > 16: the play head's page, stopped the selected track's cursor page; a pip per page),
a MUTE badge, the output meter; the selected track's row highlighted. Only the look changes: HOME's knobs, ALGORITHM
and the HOME button do what they do on SCOPE. Kept in the settings record (its own byte; a value an older firmware does
not know reads as SCOPE there). Applied at once. 1.5 (#134): LEVELS (2), the rows of TRACKS with KNOB 1..4 the LEVEL
of T1..T4 (the GLO layer's knobs) in place of the selected track's engine's four; firmware before 1.5 reads it as SCOPE.

HELP (id 24, 1.5, Discussion #156; SYSTEM now shows USB SERIAL, RESTORE LAST and HELP, index 11, 15, 24, then
CALIBRATION, INFO and ABOUT): ON shows a short hint (key caps and a few words) in the footer for about 2 s when a page
opens, and a second footer row under a quick layer's map. OFF (the default) shows none. A bit of the settings record
(MENU's 1.2 flags byte, bit 3; older firmware keeps it and ignores it). Applied at once.

SELECT (id 25, 1.5.5, Discussion #188; CONTROL now shows HOLD, KNOB ACCEL, FX LATCH, BPM LOCK, SCALE LEDS, STEP
PREVIEW, CHORD ENTRY and SELECT, index 5..8, 16, 19, 20, 25): what the SELECT knob does. BPM (the default, as before)
sets the tempo (BPM LOCK as it says); PAGE steps the pages of the family shown, as a tap of its button does (right) or
back (left), round; HOME, MIXER and CLOCK are one round. With PAGE the tempo is GLO + SELECT, HOME > CLOCK's KNOB 1 and
GLO's TAP; BPM LOCK does nothing then. A bit of the settings record (MENU's 1.2 flags byte, bit 4; older firmware keeps
it and ignores it). Applied at once.

**USB SERIAL (id 11).** The menu applies it when it closes; a MENU_SET applies it about 200 ms after its reply
(`usb_serial_apply`), so the reply leaves first (if the device shows the MENU at that moment: when it closes).
A change (ON <-> OFF; setting the value it already has does nothing) re-enumerates the whole device: it drops off
the bus (its D+ pull-up off) and comes back with the other descriptors, so USB-MIDI, USB audio and the serial
console all go away and come back. On the device the gap is about 25 ms plus one main-loop pass (`usb_retry`,
`usb_start`), or up to 1 s when it re-enumerated in the second before; the host then debounces the attach
(>= 100 ms), resets and enumerates the device. Measured on macOS (CoreMIDI): OFF -> ON, the reply at ~0.04 s, the
device gone at ~0.3 s, the MIDI port gone at ~0.57 s and back at ~1.15 s; ON -> OFF, the serial port goes
at ~0.6 s while the MIDI port was not seen to disappear at all (so do not wait for a disconnect event: after
a real change, wait ~1.5 s and open again). What the editor sends in that window is lost, `WATCH` ends with the
bus reset (send `INFO` and `WATCH` again after reconnecting), and a backup in progress answers rc 5 (stale).

## FM6 voice bank (74-77; 1.4.1)

32 voices in flash, written whole from the editor (a 32-voice SysEx file: its 128-byte packed records, the format
`FM6_PUT` takes), picked on the device with SLOT B1..B32 (9..40). Loading one copies it into the track's patch as F1..F8
do: the patch is the track's from then on, saved with projects and user presets (`FM6_GET` target 0 reads it), so a
project made with a bank voice sounds the same after the bank was replaced. INFO advertises `56 01 32` (32 voices)
after `57 01 4`; firmware without the tag answers none of 74..77 and has SLOT 0..8.

<a id="cmd-74"></a>
### 74 FM6B_BEGIN

Available: INFO `56 01` (1.4.1). Request length (argument bytes): **0**.

- Request: —.
- Reply: rc. Starts a transfer (stops the transport; erases a sector: allow 1 s).

A nonempty request returns rc 1.

<a id="cmd-75"></a>
### 75 FM6B_WRITE

Available: INFO `56 01` (1.4.1). Request length (argument bytes): **129**.

- Request: index 0..31, the 128 bytes.
- Reply: index, rc. Each index at most once per transfer; voices not written are empty in the new bank.

Wrong length returns index, rc 1 (index 127 if absent).

<a id="cmd-76"></a>
### 76 FM6B_END

Available: INFO `56 01` (1.4.1). Request length (argument bytes): **15**.

- Request: name (10 bytes, space-padded; nonprintable bytes normalize to spaces), CRC-32 (zlib's) of the written records, 128 bytes each in index order (5 × 7 bits, LSB first: bits 0..6, 7..13, .., 28..31).
- Reply: rc, voices (how many the bank the device holds now has). rc 0: the new bank replaced the old one (allow 1 s).

The last CRC byte must be 0..15. Wrong length or an oversized CRC returns rc 1 and the currently stored voice count.

<a id="cmd-77"></a>
### 77 FM6B_LIST

Available: INFO `56 01` (1.4.1). Request length (argument bytes): **0**.

- Request: —.
- Reply: 32, bank (1 there is one, 0 none), its name string, then per voice: used (0/1), name string ("" if empty).

A nonempty request gets no reply.

rc: 0 ok, 1 arguments (an index past 31 or written twice, a record that is not 128 bytes, an END that is not 15
bytes), 2 the CRC did not match (nothing changed: the old bank stays; start again with `FM6B_BEGIN`), 3 playback did
not stop, 4 flash (no flash, an erase or a write failed), 5 no transfer (no `FM6B_BEGIN`, an END already answered, or
the device's autosave took the transfer's flash between two requests, after 10 s without one: start again).

- An END with no WRITE (the CRC of nothing: 0) writes an empty bank: every B slot is empty.
- The old bank stays until END answers rc 0; a power cut at any point leaves the old bank or the new one, never a mix.
- A track on a bank slot when a new bank arrives keeps the voice it played, as its own patch: SLOT becomes OWN.
- The editor's import (6-OP FM tab): a 32-voice file's voices, each packed as for a single voice (every value into
  its range); an empty slot of a shorter file is not written. Flash: the bank is at 0xE7000; a transfer is staged in
  the autosave's older sector first (0xE5000 / 0xE6000), which the next autosave writes over anyway.
- A full backup carries the bank as object 20 (#321, `BACKUP_LIST 1`; [full backup](#v7-full-backup-65-67)); its restore uses this same
  staged transfer inside one request.

## MIDI LEARN (78-79; 1.5)

The device can set a controller's CC to any knob's parameter of a track (Discussion #170): GLO + D4 turns MIDI LEARN
on, a knob turned picks its parameter on the selected track (GLO's KNOB 1..4: T1..T4 LEVEL), the next CC that comes is
set to it. Up to 16 CCs, each to one parameter of one track (0..3), whatever channel it comes on (a channel MIDI IN /
ROUT ignores stays ignored) and whichever track that channel plays; a CC 0..127 over the parameter's range, as a knob
(and as AUTOMATION records a knob). A learned CC no longer reaches the standard CC map (CC74 learned is no longer
T1's CUT on channel 1). One CC sets one parameter and a parameter has one CC: learning either again replaces the old
entry. Never learned: CC0, 1, 6, 11, 32, 38, 64, 96..101, 120..127 (their meaning: bank select, MODW, RPN data, EXPR,
the pedal, data increment / NRPN / RPN, channel mode). The map is part of the settings (kept across power-off, not in
projects or user presets; a full backup carries it with the settings object); empty in every older setting. An engine
parameter is learned by its place (P_E0 + k): on a track that changes engine the CC sets that engine's k-th value.
INFO advertises `43 01 16` (16 entries) after `56 01 32`; firmware without the tag answers neither command. The
device's MENU > MIDI > LEARN CLEAR (OCT+: every entry cleared) is an action, not a setting: `MENU_DESC` does not offer
it (the MENU settings' count stays); `LEARN_SET` op 2 does the same.

<a id="cmd-78"></a>
### 78 LEARN_GET

Available: INFO `43 01` (1.5). Request length (argument bytes): **0**.

- Request: —.
- Reply: 16, then 16 × (used 0/1, CC, track, parameter id); an empty entry `0 0 0 0`.

<a id="cmd-79"></a>
### 79 LEARN_SET

Available: INFO `43 01` (1.5). Request length (argument bytes): **op 0: 4; op 1: 2; op 2: 1**.

- Request: op 0 learn: 0, CC, track, parameter id; op 1 clear a CC: 1, CC; op 2 clear all: 2.
- Reply: rc, then LEARN_GET's reply.

Wrong length/op or invalid learn target returns rc 1 and the map. Other rc values and mapping rules follow below.

The parameter id is this firmware's (`P_*`, P_E0 from `INFO`). rc: 0 applied and saved, 1 arguments (an unknown op, a
CC that is never learned (op 0), a track past 3, an id past P_COUNT − 1), 3 applied in RAM only (no flash, a
failed write), 4 applied, saved when the transport stops, 5 full (16 others: clear one first). Op 1 accepts any 7-bit CC, including a reserved or unassigned CC; it clears its entry if one exists. Op 2 clears the map. Both use the shared settings-save result even when unchanged (pending unsaved settings can therefore return rc 3 or 4). The device does not tell the editor when it learns: read the map
again (LEARN_GET) when it matters (e.g. with the settings, or after the user says so). Example: `F0 7D 46 4C 4F 00 4A
03 69 F7` (op 0: CC74, T4, id 105: P_E0 + 2, DRUM's TONE, with current P_E0 103) answers `F0 7D 46 4C 4F 00 10 01 4A 03 69 ...
F7` (rc 0, 16 entries, the first CC74 on T4 id 105).

## CUSTOM palette (80-81; 1.6)

COLOR (MENU > DISPLAY, Discussion #239, #244) has a palette of the user's as its 11th value, CUSTOM. A palette is five
stored colours, BG SURF TEXT THEME ACCENT; the device derives the other tokens (MID, DIM, LINE, SEL, TINT, INK, RAISE, KEY,
LANE, GRID, REC) from them with fixed blends, as for the built-in palettes (`firmware/src/gfx.c palette_set`,
`tools/gen_ui_palettes.py`), CUSTOM is not GREY and not MONO (the channels blend as they are). The colours are RGB565,
sent as three 7-bit bytes each: red 0..31, green 0..63, blue 0..31. CUSTOM is part of the settings (kept across
power-off, not in projects or user presets; a full backup carries it with the settings object, id 1: bytes 0..9 and 12 of
the device bytes, the PER4 record's 16th favourites row and PER6's `dev`). Firmware before 1.6 keeps the bytes (a round trip through it does not lose the palette) and shows
the built-in palette that was in use before CUSTOM was chosen (the settings' palette field is never CUSTOM). INFO
advertises `45 01 5` (five colours) after `4B 01 NCOND`; firmware without the tag answers neither command.

While one is stored, CUSTOM is the 11th name of `UI_PALETTES` (cmd 36: count 11, the last "CUSTOM"), `UI_SET` id 0 takes
10, `UI_STATE`'s palette byte is 10 while it is in use, and MENU's COLOR (id 0 in `MENU_DESC` / `MENU_SET`) has 11 values
(max 10, the last "CUSTOM"). With none stored: 10 values as before, and `UI_SET` 0 with 10 answers rc 1.

<a id="cmd-80"></a>
### 80 PALETTE_GET

Available: INFO `45 01` (1.6). Request length (argument bytes): **0**.

- Request: —.
- Reply: flags (bit 0 stored, bit 1 in use), 5, then 5 × (r, g, b): the stored colours, or with none stored the palette in use (a place to start from).

<a id="cmd-81"></a>
### 81 PALETTE_SET

Available: INFO `45 01` (1.6). Request length (argument bytes): **ops 0, 1: 16; ops 2, 3: 1**.

- Request: op 0 preview: 0, 5 × (r, g, b); op 1 store: 1, 5 × (r, g, b); op 2 remove: 2; op 3 drop the preview: 3.
- Reply: rc, then PALETTE_GET's reply.

Wrong length/op or RGB component out of range returns rc 1 and the current palette payload.

Op 0 shows the colours at once and stores nothing (RAM only; the device's own COLOR or op 3 brings back the palette in
use; a power cycle too). Op 1 stores them, makes CUSTOM the palette in use and saves like `UI_SET` (rc 0 saved, 3 applied in
RAM only, 4 saved when the transport stops). Op 2 removes the stored palette (the built-in palette from before is in use
again). rc 1: arguments (a value past its range, an unknown op, a wrong length). **The device accepts any colours**, readable
or not; it is the editor that warns. The rule the editor warns by (the lightness 0..255 as in `firmware/src/gfx.c ux_luma`: (54 R + 183 G +
19 B) / 256 of the colour at full scale): TEXT against BG at least 128 apart, TEXT against SURF 96, THEME against BG 80,
ACCENT against BG 64; every built-in palette keeps 195, 171, 135 and 147 at the least. With colours nobody can read the way
back is the editor's op 2, or the device's MENU: hold HOME for the menu, COLOR is the first row of the first tab (DISPLAY), a
knob turn picks a built-in palette. A preview by the slider is op 0 sent at most every few tens of ms; the value in the
settings changes only with op 1. Example: `F0 7D 46 4C 51 01 01 02 05 03 04 0A 06 ...` is op 1 with BG = (r 1, g 2, b 5),
SURF = (3, 4, 10), ...

## Raw store export (82-83; #456)

The full backup (65-67) exports what the firmware *decoded*: a project slot is its RAM copy re-packed as FUN10, a slot
it cannot read lists as 0 bytes, the settings are re-exported from RAM, a user preset bank of another shape is empty.
The raw store export is the recovery path for everything the firmware keeps on flash **whether or not it can load
it** (an older or later format, a retired kind, a damaged copy): each storage object as flash holds it, byte for byte,
with the length, CRC and sequence of its commit record. It is **read only**: no command here writes, erases, restores,
converts or stops the transport, and nothing it does changes what boot, settings saves or the autosave do. Restoring
or migrating these bytes is the web editor's (Felucca-WebApp, #457); the inventory of formats and the conversion rules
it needs are in [docs/legacy-formats.md](../docs/legacy-formats.md).

INFO advertises `59 01 caps` after `58 01` (the last tagged block): bit 0 = `STORE_LIST` / `STORE_GET`. This firmware
sends 1 (0 in a build without the flash store, `FELUCCA_FLASH=0`). Firmware without the tag answers neither command.

<a id="cmd-82"></a>
### 82 STORE_LIST

Available: INFO `59 01` bit 0 (#456). Request length (argument bytes): **0**.

- Request: —.
- Reply: 1 (this reply's layout), rc, count (11), then per object: type, state, copy, size u32, crc u32, seq u32, magic u32 (23 bytes).

Any argument returns 1, 1, 0.

<a id="cmd-83"></a>
### 83 STORE_GET

Available: INFO `59 01` bit 0 (#456). Request length (argument bytes): **8**.

- Request: type, offset u32, count lo, count hi (count 1..256).
- Reply: type, rc, offset u32, count lo, count hi, pack7 data (as `BACKUP_GET`).

On error count is 0 and no data follows; missing type is echoed as 127. Argument validation precedes transport/no-flash errors.

u32 is five 7-bit bytes, LSB first, as in the full backup. The objects are named by their **storage type** (the
`type` of the commit record on flash, `firmware/src/storage.c` `OBJ_*`), not by backup id, in this order:

| type | object | flash (copy A / B) | its current schema (this firmware) | backup id |
| --- | --- | --- | --- | --- |
| 0 | settings | `0xFC000` / `0xFD000` | PER4 (572 B) or PER6 (672..2688 B) | 1 (re-exported from RAM) |
| 1..4 | PROJECT slots 1..4 | `0x97000 + 0x2000 k` / `+ 0x1000` | FUN10, 3840 B, P_COUNT at byte 66 | 2..5 (re-packed RAM copy) |
| 5, 6 | user preset banks 1, 2 | `0xDC000 + 0x2000 k` / `+ 0x1000` | `UPB1`, 3080 B (16 records of 192 B) | 6, 7 (RAM copy) |
| 7 | the FM6 patch bank of 1.0 .. 1.0.2 (retired; its patches moved into the user presets once) | `0x9F000` / `0xFE000` (shared with 8) | none: read only, `FM6B` 3472 B | 8 (always empty) |
| 8 | the user presets' FM6 patches | `0x9F000` / `0xFE000` (shared with 7) | `UPF6` ver 1, 3728 B | 9 (RAM copy) |
| 9 | the autosave (the music at power-off, 1.2) | `0xE5000` / `0xE6000` | FUN10, 3840 B | none (id 0 is the live music) |
| 32 | the FM6 voice bank (1.4.1) | `0xE7000` only (payload at `+224`) | `FM6V` ver 1, 3616 B | 20 (from flash) |

A future storage type (the PRX sidecars, types 10-14 in [flash-capacity.md](../docs/flash-capacity.md)) is appended
to this list; `count` says how many follow, and a client skips types it does not know. The user sample slots
(backup ids 32-34) and the SLICE records (id 21) are not storage objects of this kind (no commit record): the full
backup already exports the sample slots' stored bytes, and their formats (`FSMP` 1, `SLM1`) have no older version.

**The copy.** Each type has an A/B pair (the voice bank one copy). `STORE_LIST` takes the copy the firmware's own
reader takes (`st_current`: the newest copy whose commit record and payload CRC are intact, A on a tie of sequence
numbers); `copy` says which (0 A, 1 B; 127 none). If no copy is intact but a commit record is valid, it takes the
newest such copy and reports it DAMAGED: its bytes as stored, and the record's CRC, which they fail. The older copy of
a pair is not exported (open question in #456).

**state** (one byte; what this firmware would do with the object, from its identification only: magic, length,
version and count fields and a project's own FNV-1a hash; the bytes are never decoded for the export):

| state | meaning |
| --- | --- |
| 0 EMPTY | no valid commit record (never written, erased, a torn first write, or a stock-firmware area), or one of 0 bytes (an erased project slot): size 0. `copy` 127 when there is no record |
| 1 CURRENT | the schema this firmware writes: PER4 / PER6, FUN10 with today's P_COUNT, `UPB1` 192-byte records x 16, `UPF6` 1, `FM6V` 1 with 32 voices |
| 2 LEGACY | an older schema this firmware still converts when it loads it: FUN1..FUN9, a FUN10 of fewer parameters (mapped by count), PER1/2/3/5, a PER6 whose extension it cannot read (its PER4 block is read), the retired FM6 bank |
| 3 UNKNOWN | intact on flash but no supported container identification: a later format, a serialized project count outside 8..P_COUNT or beyond its layout's extent, a project whose own hash fails, another bank shape. The firmware does not load it (a project slot shows EMPTY; see docs/legacy-formats.md for which writes can still replace it) |
| 4 DAMAGED | a valid commit record whose payload fails the record's CRC on every copy |

The state describes the container. Records inside it are the client's to read: a CURRENT user preset bank can hold
records of older versions or retired engines (each record's `ver`, `np` and `engine`), and a CURRENT FUN10 can hold
a DIGITAL or SAMPLE PERC track. FUN10 / `UPB1` with stable MACRO id 14 and PER6 with its favourites are CURRENT even
when this profile cannot play MACRO. The historical PER5 settings format remains LEGACY input.
`magic` is the first four payload bytes as stored (little endian; 0 for fewer than 4).

`STORE_GET` reads `count` bytes from `offset` of the object `STORE_LIST` describes, chosen again for each request by
the same rule. rc: 0 ok; 1 arguments (the length, an argument byte, a count of 0 or above 256), a type that is not in
the list, an EMPTY object, or a range past its size; 3 the transport is running (`LIST` and `GET` answer 3 and leave it
running: stop first); 4 no flash. `STORE_LIST` with any argument answers `1, 1, 0`; `GET` without arguments answers
type 127. There is no snapshot and no stale rc: check each object's bytes against the listed CRC (an object that
changed between `LIST` and `GET` fails it); for a DAMAGED object, which fails it anyway, send `STORE_LIST` again
afterwards and compare its `copy`, `size`, `crc`, `seq` and `magic`. This detects changed commit metadata and
identification bytes, not damage changing elsewhere in the payload under an unchanged commit record; it does not
provide an atomic snapshot. Keep the device stopped and avoid concurrent editors or storage operations.
The firmware holds the autosave off while these requests
come in, as for the backup transfers. The reference reader is `captureRawStore` in `web/fm1backup.js`
(`web/test_backup.mjs`); no page uses it yet.

**What a client keeps** (#457): per object the type, state, copy, size, crc, seq, magic and the bytes, with the
firmware's `INFO` version string and P_COUNT. The bytes are the source of truth; a later firmware may list more types
or report another state for the same bytes. Nothing in this export can be uploaded back as it is: a restore of a
migrated object goes through a current-schema upload path that does not exist yet (#456).

## Parameter and engine reference

The engine parameters are `P_E0..P_E7`: P_COUNT−8 .. P_COUNT−1 (103..110 since 1.5; 96..103 in 1.2 .. 1.4; 91..98 in
1.1), and `INFO` gives `P_E0`.
Their meaning, range and names depend on the current engine, so re-read `DESC` for them
after an engine change.

The modulation matrix (the MOD page, `firmware/src/mod.c`) is twelve track parameters at ids 49..60 (since
P_COUNT 69): slot k (1..4) is `SRCk`, `DSTk`, `AMTk` at ids 49 + 3 (k − 1) .. 51 + 3 (k − 1).

| id | label | values |
| --- | --- | --- |
| 49, 52, 55, 58 | SRC1..SRC4 | enum: 0 OFF, 1 LFO, 2 ENV, 3 VEL, 4 KEY, 5 RAND, 6 MODW (CC1), 7 AT (channel aftertouch), 8 EXPR (CC11), 9 S&H (a random value held for one cycle of the track LFO), 10 SLEW (S&H gliding from the cycle before's value) |
| 50, 53, 56, 59 | DST1..DST4 | enum (23 names; 21 before 1.5.6): 0 OFF, 1 PITCH, 2 CUT, 3 SHP, 4 AMP (per voice); 5 PAN, 6 DIST, 7 CHO, 8 DLY, 9 REV, 10 RATE (LFO rate), 11 VIB (LFO pitch depth), 12..19 E1..E8 = `P_E0..P_E7`, 20 DEPTH (the track LFO's depth: a gain on LFO DEST and the matrix's LFO source) (per block); 1.5.6 (#213), at the note: 21 VEL (the note-on velocity, AMT 64 = +-127, 1..127), 22 TIME (a sequencer step late, 0..30 ms at AMT 64, at most 7/16 of the step). Firmware before 1.5.6 clamps 21 / 22 to 20 (DEPTH) when it loads them |
| 51, 54, 57, 60 | AMT1..AMT4 | −64..63 (fmt BIPCT) |

`DESC` names E1..E8 as such; the device shows the engine's label of that parameter instead (`DESC` of
`P_E0 + n`), and so does the editor. A slot with SRC, DST or AMT at 0 does nothing; every default is 0
(a factory preset sets all twelve to 0). The modulation never changes the stored values: `GET`,
`DUMP` and the pushes report what was set.

**DIGITAL (engine 1) was replaced by FM6 (Dexed-based)** in 1.0. The number stays reserved: `INFO` names it
"-" (a build with `FELUCCA_FM4=1` has DIGITAL back, named "DIGITAL"), `NAMES 1` lists no presets, its EDIT
descriptors are "-" with DIGITAL's ranges, and no track ever has it. Whatever brings a DIGITAL sound plays it as
FM6 with a patch converted from its values (`firmware/src/fm4_convert.c`; the patch is the track's own, `FM6_GET`
reads it, a project keeps it): `SET` of `G_ENGSEL` = 1 (DIGITAL's first preset), `PRESET` 1 k (its preset k),
`UP_LOAD` of a slot stored with engine 1 (`UP_PUT` still takes engine 1: the record keeps the DIGITAL values, every
load converts them), projects with DIGITAL tracks (their motion on E1..E8 and ids 61..80 is dropped). The track
reports engine 12 (FM6) and the FM6 preset that covers the sound. The editor converts DIGITAL patches of library
files the same way (it equals the firmware's, `test_web.mjs`).

The four FM operator envelopes (the DIGITAL engine's OP1..OP4 ENV and OP LEVEL pages, `eng_digital.c`) are
twenty track parameters at ids 61..80, five per operator: operator k (1..4) has `ATK`, `DEC`, `SUS`, `REL`,
`LVL` at ids 61 + 5 (k − 1) .. 65 + 5 (k − 1). Since DIGITAL was retired they are inert: no page and no editor
layout shows them, only the conversion of a DIGITAL sound reads them (its FM6 tracks hold the defaults). The ids
and labels stay (library files key values by label).

| id | label | fmt, range, default |
| --- | --- | --- |
| 61, 66, 71, 76 | ATK | TIME, 0..127, 0 |
| 62, 67, 72, 77 | DEC | TIME, 0..127, 0 |
| 63, 68, 73, 78 | SUS | PCT, 0..127, 127 |
| 64, 69, 74, 79 | REL | TIME, 0..127, 0 |
| 65, 70, 75, 80 | LVL | PCT, 0..127, 127 |

The defaults change nothing: the sound is the same as before the parameters existed. The master `ENV`
(ids 1..4) shapes the whole voice; these shape each operator on top of it. Other engines ignore them, and the
device shows the pages for DIGITAL only. Descriptors are the same for every engine.

The chord keys (SCL > CHORD on the device, `firmware/src/chord.c`) are two track parameters at ids 81, 82:

| id | label | values |
| --- | --- | --- |
| 81 | CHRD | enum: 0 OFF, 1 DIA3, 2 DIA7 (the triad / seventh of the track's ROOT and SCALE on the key: every tone in key), 3 MAJ, 4 MIN, 5 DOM7, 6 MAJ7, 7 MIN7, 8 SUS4, 9 POW (fixed shapes) |
| 82 | VOIC | enum: 0 CLOSE, 1 OPEN (1-5-3), 2 INV1, 3 INV2, 4 +OCT (the root an octave down; a seventh drops its fifth) |

With CHRD on, a key, a MIDI note of that track and so the arp's held notes play the chord (at most 4 notes),
and live recording writes it into one step; MONO / LEGATO / UNISON play its root; a kit (DRUM, SLICE)
ignores it. Both defaults are 0: nothing changes until CHRD is set. They are the track's, like ARP and SCL: a
sound load (a factory preset, `UP_LOAD`, an audition) keeps them, and motion never records them.

The DRUM lane levels (EDIT > LANES / LANES 2 on the device, `firmware/src/eng_drum.c`) are eight track parameters at
ids 83..90, one per lane: 83 KICK, 84 SNARE, 85 CLAP, 86 HATCL, 87 HATOP, 88 TOM, 89 RIM, 90 BELL. Percent (`F_PCT`),
0..127, default 127 = 100 % (the kit as designed), square law (64: about −12 dB). Only the DRUM engine reads them; the
editor shows them on a DRUM track only (the device's pages). They are the sound's (not the track's): a factory preset
sets them back to 127, user presets and projects store them (older ones load at 127), motion records them.

Other enums that grew: `P_SDIV` (DIV, id 30) has 10 names (1/4, 1/8, 1/16, 1/32, 8T, 16T, 1/2, 1/1, 2BAR,
4BAR; the first six keep their numbers), `P_AMODE` (id 17) 15 (OFF, UP, DN, UPDN, RND, ORD, REPEAT, and since 1.2 DNUP, UP+8, CONV, DIVG, PINKY, THUMB, WALK,
CHORD: values 7..14, appended; an editor that knows only 7 names shows the value by `DESC`'s name) and the
global `G_CLOCK` (id 2, label "CLK") 3 (INT, USB, TRS). `G_MIDI` (id 12) is an enum of USB / TRS that nothing reads.
Since 1.5.1 the delay's `G_DTIME` (global id 4, label "TIME") has 13 names: P_SDIV's ten at the same values, then
1/8D, 1/16D, 1/4D (values 10..12, dotted: 3/4, 3/8, 3/2 of a quarter); `DESC` sends all 13, max 12. P_SDIV, P_ARATE
and the LFO's SYNC keep their lists. The device's knob steps TIME by length, longest first (4BAR 2BAR 1/1 1/2 1/4D
1/4 1/8D 1/8 1/16D 8T 1/16 16T 1/32); an editor sorting by the names' lengths reads "n/mD" as 1.5 x n/m. An editor
that knows only ten names shows 10..12 by `DESC`'s names; a `SET` of 10..12 to a 1.5 device is clamped to 9 (4BAR).
Since 1.5.6 (#218) `P_QUANT` (id 27, label "QNT") has 5 names: OFF SNAP WHITE SEQ, then SEQ+T (value 4, appended:
SEQ, and the sequence's notes moved by TRN before they snap, as the keys are). An editor that knows four names shows 4
by `DESC`'s name; older firmware clamps a stored or `SET` 4 to 3 (SEQ: the sequence snaps, not transposed).
The FX layer's REV THROW and ECHO THROW (1.5.1) are performance only: no parameter, nothing in the protocol.

**Retired enum values (aliases).** A value that no longer exists keeps its number, so stored sounds stay valid:
`DESC` names it like the value it now plays (an alias), the device never holds it (a `SET` of it lands on that value
and the reply says so) and its knob steps over it. Of a repeated name, the original is the first value when that has
the name, else the last one with it; an editor should list only the originals and show an alias by its name when
it ever sees one. Today: SAMPLE SET and GRAIN SRC 1 and 4 (once TRANH, PERC) = 0 PIANO; DRUM KIT (engine 10, E1)
1, 2, 3 (once HAND, CYM, H+CYM; 1.0.5) = 6 (66), 5 (10), 8 (77): its names are STD 66 10 77 80 10 66 55 77 (1.5.6,
#216: then 9 DEEP, 10 TIGHT, 11 PERC, appended; firmware before clamps them to 8, 77), the device's knob steps STD 80 10
66 55 77 DEEP TIGHT PERC. An editor of before 1.0.5 (first of a name = original) offers 66 10 77
at 1..3 and hides 6 5 8: what it sets still plays the right kit, and the device answers with 6 5 8.

## Parameter-count history

INFO supplies both P_COUNT and P_E0; clients must not hardcode them. Preset
imports map by count; project imports also move motion IDs with the engine
parameters. New common values are inserted before the last eight engine values.

| Stage | P_COUNT | P_E0 | Added common parameters |
| --- | --- | --- | --- |
| early | 53 | 45 | original common set |
| SLICER | 57 | 49 | 45..48 |
| modulation matrix | 69 | 61 | 49..60 |
| v7 | 89 | 81 | legacy FM operator controls 61..80 |
| 1.0 | 91 | 83 | CHRD, VOIC 81..82 |
| 1.1 | 99 | 91 | DRUM lane levels 83..90 |
| early 1.2 | 103 | 95 | LFO SYNC/TRIG/POL, QNTZ 91..94 |
| 1.2..1.4 | 104 | 96 | SPREAD 95 |
| 1.5 onward | 111 | 103 | INSERT 96..100, TYPE 101, ESYNC 102 |

## Parameter formats

`fmt` values (`firmware/src/core.h`):

| Value | Name | Value | Name | Value | Name |
| --- | --- | --- | --- | --- | --- |
| 0 | INT | 5 | CUTOFF | 10 | NOTE |
| 1 | PCT | 6 | DB | 11 | ONOFF |
| 2 | BIPCT | 7 | SEMI | 12 | OCT |
| 3 | TIME | 8 | ENUM | 13 | STEPS |
| 4 | LFOHZ | 9 | BPM | | |

The editor should show the value with the unit; formatting it exactly like the device does
is not required.

<a id="12-lfo-2-nudge-128-records-fun10"></a>
## LFO sync and SPREAD

- **Parameters** (from `INFO` / `DESC` as always): 91 `SYNC` (enum OFF 4BAR 2BAR 1/1 1/2 1/4 1/8 8T 1/16 16T 1/32,
  default OFF: one LFO cycle per note value of the tempo, internal or the external clock's), 92 `TRIG` (NOTE FREE,
  default NOTE: restart at PHS on a fresh phrase, or never), 93 `POL` (BI UNI, default BI: −1..+1, or 0..+1 with the
  same depths reaching as far, one way), 94 `QNTZ` (OFF ON, default ON: every step on its start; OFF plays the
  nudges). The defaults play as before 1.2. `SYNC` `TRIG` `POL` are the sound's (a sound load sets them; user presets
  store them); `QNTZ` is the track's (like LEN DIV SWING GATE: a sound load keeps it; an editor's audition must not
  send it, as for the other track-own ids). None of the four can be recorded as motion (`MOTION` 3 / 5 answer rc 1)
  and no MIDI CC sets them. 95 `SPRD` (0..127, PCT, default 0: every voice on PAN, as before): a POLY / UNISON
  track's voices alternate left and right of PAN by SPRD / 2 (127: hard left / right); MONO and LEGATO ignore it. It is
  the sound's (a factory preset sets 0, user presets store it) and can be recorded as motion. The engine parameters are
  96..103. ANALOG's `WAVE` (E0) gained 5 SYNC (OSC 2 hard-synced to OSC 1, DTN its interval, the SHP routings sweep it)
  and 6 SUB (OSC 2 a square an octave below, MIX its level); `DESC` keeps DTN / MIX's labels (the device relabels them).

<a id="15-the-insert"></a>
## Insert effect parameters

Five track parameters before the engine parameters, ahead of 1.5's TYPE and ESYNC (below; with them P_COUNT 111, P_E0
103; take both from `INFO` as always):

| id | label | values |
| --- | --- | --- |
| 96 | INSRT | enum (append-only): 0 OFF, 1 SOFT, 2 HARD, 3 FOLD, 4 FUZZ, 5 CRUSH, 6 PHASR, 7 FLANG, 8 CHOR; default OFF |
| 97 | INS A | 0..127, default 64: SOFT .. FUZZ DRIVE (PCT), CRUSH BITS (1 + v / 8: 1..16), PHASR / FLANG / CHOR RATE (LFOHZ) |
| 98 | INS B | 0..127, default 96: SOFT .. FUZZ TONE (CUTOFF), CRUSH RATE (v / 8 picks 689 919 1.1k 1.4k 1.8k 2.2k 2.8k 3.7k 4.4k 5.5k 7.4k 8.8k 11k 15k 22k 44k Hz), the swept ones DEPTH (PCT) |
| 99 | INS C | 0..127, default 96: SOFT .. FUZZ LEVEL (DB, as LVL: 112 = 0 dB), CRUSH LPF (CUTOFF), the swept ones FDBK (PCT) |
| 100 | MIX | 0..127 (PCT), default 127: dry / wet; 0 = the dry track, bit for bit |

`DESC` gives the generic labels and formats above (`INS A` .. `INS C`, PCT): the meaning of 97..99 depends on 96, as
the engine parameters' on the engine; an editor that shows them by TYPE uses the table (the device does:
`params.c ins_desc`). All five are the sound's (a factory preset sets OFF and the defaults, a user preset stores them,
an audition sends them) and can be recorded as motion and locks (`MOTION` 3 / 5: rc 0). With TYPE OFF (or MIX 0) a
track plays exactly as before 1.5. Older stores load by count: a FUN10 of 104 (1.2 .. 1.4) or 103 parameters, FUN9 and
older, user presets of 104 and fewer: the INSERT OFF, their engine values and motion moved up to 103..110. Firmware
before 1.5 shows a FUN10 of 111 parameters as EMPTY and refuses it in a backup `PUT` (its P_COUNT is larger than its
own); a user preset record of 111 already in its flash it maps by count (the INSERT dropped, the engine values
found). `UP_PUT` takes the device's own P_COUNT values, as always.

<a id="15-filter-type-env-sync"></a>
## Filter TYPE and ENV SYNC parameters

No new command or INFO tag: P_COUNT 111 and P_E0 103 (from `INFO`, with the INSERT) say it, and `DESC` describes the two as always.

| id | label | values |
| --- | --- | --- |
| 101 | `TYPE` | enum LP BP HP, default LP. ANALOG's filter (Discussion #104): the state-variable filter's low-pass (as before, bit for bit), band-pass or high-pass output, CUT / RES / KTR and every cutoff routing as they are. Other engines ignore it. On the device: EDIT > FILTER (TYPE CUT RES KTR), an ANALOG track's page after EDIT 2 |
| 102 | `ESYNC` | enum OFF ON, default OFF. ENV SYNC (Discussion #175): ON, the amp envelope's ATK DEC REL (ids 1, 2, 4) are note values of the tempo (BPM, or the external clock's measured tempo) instead of 1 ms .. 10 s. On the device: ENV DEST's KNOB 4 |

Both are the sound's (a factory preset or TOOLS INIT sets LP / OFF; user presets and library files store them). Neither can
be recorded as motion (`MOTION` 3 / 5 answer rc 1) and no MIDI CC sets them.

With `ESYNC` ON the stored values of ATK DEC REL stay 0..127; `DESC` still describes them as times (TIME), but they mean a
note value: value v is name `ESYNC_NAMES[v × 25 / 128]` (integer division) of the 25, shortest first:

`0` `1/64T` `1/64` `1/32T` `1/64D` `1/32` `1/16T` `1/32D` `1/16` `1/8T` `1/16D` `1/8` `1/4T` `1/8D` `1/4` `1/2T` `1/4D`
`1/2` `1/1T` `1/2D` `1/1` `1/1D` `2BAR` `3BAR` `4BAR`

(T a triplet, D dotted; in 1/384 of a 4/4 bar: 0 4 6 8 9 12 16 18 24 32 36 48 64 72 96 128 144 192 256 288 384 576 768 1152
1536; the time is that × a quarter / 96.) `0` is the shortest time, as ATK / DEC / REL 0 with SYNC OFF. The device shows
these names and its knob steps one name a detent, landing on the first value of each: `(k × 128 + 24) / 25` for name k
(params.c `param_turn`). An editor should show and step them the same way while the track's `ESYNC` is ON (and keep the
raw value when it goes OFF: the same number is a time again). The attack reaches the top after that time, the decay
(to SUS) and the release fall 40 dB in it.

Projects: FUN10 unchanged; one written by 1.5 holds 111 at byte 66 (16 bytes to spare before the FM6 patches, room for 4
more). A FUN10 of 104 (1.2 .. 1.4) loads by count (the INSERT OFF, TYPE LP, ESYNC OFF; engine values and their motion
moved up by seven). Firmware 1.2 .. 1.4 refuses a FUN10 of 111 (more parameters than it has: its slot shows EMPTY, a
backup PUT of one answers rc 1); user presets of 111 load there by count (the seven left out). Library files of 104 map
by label: the INSERT, TYPE and ESYNC unset.

## Engine ids (#212)

Engine ids are a stable, append-only namespace 0..63, independent of the engines a build has and of their count
(a build profile may leave engines out, a later firmware has more). The device stores and sends an id as it is:

- **INFO** keeps its old prefix for existing editors (Felucca-WebApp): NENGINES, then NENGINES names for ids
  0..NENGINES−1, `-` for an id this build cannot play (1, DIGITAL, without `FELUCCA_FM4`; one its catalog leaves out). Then the tagged
  block `49 01 64 7F b0..b9`: the id space (64), FAV_GET / FAV_SET's user marker (127) and a bit per id this build
  plays: id 7i + k is bit k of b<sub>i</sub> (ten 7-bit bytes, ids 0..69, 64..69 always 0). A catalog with gaps (a
  build profile, #28) is only meant for an editor that reads this block; an older one shows the `-` names as before.
- **An id this build lacks** (in a project, a user preset, a backup, a later firmware's or a build profile's) is kept: the
  track shows N/A, has no presets, plays nothing and keeps its preset number and E1..E8 values (their stored range
  −64..127). `DUMP`, `TRACK`, `RELOAD`, `UP_LIST` and `UP_GET` report the id as stored, never another engine.
  `PRESET` to it gets no reply, `SET G_ENGSEL` returns the unchanged value, and `UP_PUT` returns rc 1; `NAMES` of it answers no presets (no
  reply past the name list). Saving a project or the music keeps the id. A byte past the id space (64..255) is no
  project or user preset (as a byte past the engines was before).
- **FAV_GET / FAV_SET**: engine 127 is a user slot; the old marker (INFO's prefix count) is taken too. It is never
  an engine id of the same build, since the name list ends below it. An editor that has 14 built in rather than
  taken from INFO addresses engine 14 on a build that has one.
- **Settings (backup id 1)**: the favourites have a row per id (64 rows), MIDI LEARN's map and the device bytes
  (palette CUSTOM, MENU flags, the FX key map, ...) moved out of the favourites rows. The record is **PER4** (as up to
  1.6, byte for byte) while no favourite is on an id from 14, else **PER6**: the PER4 record (its rows 0..13, the map in
  row 14, the device bytes in row 15, as PER4 has them; magic `PER6`), then `ver 1, rows, 32, 32`, the map (32 bytes),
  the device bytes (32), and `rows` × 32 bytes of favourites (ids 0..rows−1, preset bit p of id r in byte p / 8, bit p
  % 8). This firmware writes rows 64 and reads 1..64; a PER6 whose extension it cannot read (another version, other
  counts) is read by its PER4 part. A PER5 record (PER4 + 32 bytes, an unreleased MACRO build, #27) is read: its
  row is engine 14's.
- **Downgrade limits:** firmware up to 1.6 reads a PER4 record only. While the settings stay PER4 (no favourite past id
  13: always on builds without such an engine) a downgrade keeps every setting. A PER6 record in flash is not read by
  older firmware, which starts with default settings (palette, calibration, favourites, MIDI LEARN, ...) until it saves its
  own; its backup object is refused by older firmware's `BACKUP_PUT` (rc 1). The first sizeof(PER4) bytes of a PER6
  record with the magic constant `PER4` (`0x50455234`, file bytes `34 52 45 50`) are the PER4 record those firmwares take: everything but
  the favourites of ids from 14. Favourites, projects and user presets of an id the older firmware lacks are as they
  were there (a project or user preset with such an id is no project / an empty slot there).
- **Felucca-WebApp:** existing clients keep working against this firmware unchanged (old prefix, old marker,
  PER4 settings objects, ids 0..13). A client should take the user marker and the catalog from the `49 01` block when
  it is there, show ids it does not know as unavailable rather than another engine, and keep backup objects byte
  for byte (a PER6 settings object restores here, not on firmware up to 1.6).

## Optional MACRO profile (#27)

The `macro` build profile adds engine 14; the standard profile leaves it unavailable.
Use INFO's engine catalog bitmap to discover availability. Its SHAPE enum retains
WAVE/FOLD/FBFM at values 0/1/2 and appends 45 Braids models at 3..47. DESC returns all
48 model names, up to 12 characters each; other descriptors keep the existing limits
(24 values, eight-character value names). The bounded 664-byte reply buffer accommodates
the complete model descriptor. The canonical SHAPE/TIMBRE/COLOR labels and 0..127
TIMBRE/COLOR values stay unchanged even where the panel uses model-specific words
or displays FBFM COLOR as semitones.

NAMES keeps the six original preset indices and appends 45 starter sounds (51 total).
Projects, user presets and backups keep engine 14 and the model value. Firmware that
lacks MACRO cannot load those sounds; old three-model builds cannot represent models
3..47. Keep a backup before downgrading.

## Project containers

File integers are little endian. Labels FUN7..FUN10 describe the numeric magic
constants as displayed in source; the file-byte column below gives the actual
little-endian bytes. FUN10’s displayed magic is `0x46554E41` (FUNA).
Step records are defined only in [Step record](#step-record).

| Format | File magic bytes (hex) | Bytes | FM6 patches offset | Name offset | Chain / motion bytes |
| --- | --- | --- | --- | --- | --- |
| FUN7 | `37 4E 55 46` | 3388 | none (init patches on import) | 3372 | 36 / 260 |
| FUN8 | `38 4E 55 46` | 3584 | 3056 | 3568 | 36 / 260 |
| FUN9 | `39 4E 55 46` | 3648 | 3120 | 3632 | 36 / 260 |
| FUN10 | `41 4E 55 46` | 3840 | 3312 | 3824 | 84 / 388 |

All four formats begin with magic u32, size u32, 27 i16 globals (bytes 8..61),
selected track, parts, phys (62..64), reserved byte 65, stored parameter count
`np` (66) and reserved byte 67. From byte 68 each of four tracks stores `np`
values (value + 64), engine, preset, then 64 packed 9-byte steps. The final
eight values map to the current engine-parameter IDs; earlier common values
keep their IDs, missing values take defaults. Engine IDs must be below 64;
unavailable IDs remain stored. Values outside −64..127 are invalid.

The chain follows the tracks, then motion, then spare bytes and the FM6 patches
(four 128-byte packed records, except FUN7). FUN10 writes 111 parameters:
`68 + 4 × (111 + 2 + 576) + 84 + 388 = 3296`, leaving 16 bytes before patches.
The last three spare bytes (3309..3311) hold MIDI IN TRACK routing; see the
[MENU reference](#menu-settings-72-73-104). The name is 12 ASCII bytes, uppercase,
NUL-padded; the reader stops at the first NUL. All zero, or a nonprintable byte
before the first NUL, reads as no name. The last four
bytes are the FNV-1a hash of every preceding byte, including name and spares.
PROJECT save keeps the current name; the device’s SAVE > PROJECT NAME sets it.

FUN7..FUN9 chains have count, three reserved bytes, then 16 `(slot, repeat)`
rows (36 bytes). FUN10 chains use count, three reserved bytes and 16
`(slot T1, slot T2, slot T3, slot T4, repeat)` sections (84 bytes). Older rows
load as sections with all tracks on the row’s slot. See [SONG](#cmd-33).

Motion starts with count, on mask and two reserved bytes. FUN7..FUN9 then
hold 64 records `(track << 6 | step, id, i16 value)` (260 bytes total);
FUN10 holds 128 `(place, id, i8 value)` records (388 total). Bit 7 of id marks
a lock. Values must be −64..127. When importing fewer parameters, engine
parameter IDs move with the final eight values; the lock bit stays set.

FUN7/FUN8 preceded the DRUM lane levels; FUN9 adds their capacity. FUN10 adds
LFO sync, QUANTIZE, SPREAD, 128 motion records, nudge and song sections. Earlier
FUN10 builds stored 103 or 104 parameters; current readers map them by count
(INSERT OFF, TYPE LP, ESYNC OFF, engine values/motion moved up). FUN9 imports
with LFO SYNC OFF, TRIG NOTE, POL BI, QUANTIZE ON and SPREAD 0; earlier formats
also default missing lane levels to 127, chord keys to OFF/CLOSE and newer
parameters to their descriptor defaults. FUN6..FUN1 import with no project name.

Magic, size, FNV hash, `8 <= np <= P_COUNT`, array extents, step fields, chain
and motion are checked before loading. Firmware before 1.2 refuses FUN10;
1.2..1.4 refuses a FUN10 with 111 parameters. The slot appears empty there;
its flash data remains until overwritten. Backup begin accepts 3840 (FUN10),
3648 (FUN9), 3584 (FUN8) and 3388 (FUN7/FUN6), with content checked at commit.
Firmware before FM6 imports init patches; stored bank-slot choices become OWN
with the saved patch. [Legacy format inventory](../docs/legacy-formats.md)
describes older containers and their recovery paths.

## MIDI transport

- **MIDI clock** has no SysEx. `G_CLOCK` selects the source: 0 INT, 1 USB, 2 TRS. With 1 or 2 the sequencer
  steps on that port's Clock pulses (the other port's are ignored), Start (0xFA) restarts from step 0,
  Continue (0xFB) resumes and Stop (0xFC) stops; BPM follows the incoming tempo (40..240), and 500 ms
  without a pulse stops the transport. Changing `G_CLOCK` stops it.
- Pitch bend, sustain (CC64), RPN 0 (bend range, ±0..24 semitones), CC120 / 121 / 123 are MIDI only and
  have no parameters, protocol or saved state. The standard CC map (1.1: CC5 7 10 71..75 91 93 94, README "MIDI
  in") sets parameters as a knob does: the editor sees those changes as `CHANGED` / `TRACK_CHANGED` pushes.

## Protocol changelog

Release notes below describe additions; the linked reference entries define the wire
contract. Protocol v1..v7 labels and firmware release versions are separate histories.
Discover features from INFO and descriptor replies rather than the version string.

| Protocol / firmware | Change and canonical reference |
| --- | --- |
| v1 | Selected-track parameters, steps, projects and samples: [commands 1..15](#commands) |
| v2 | [User presets 16..21](#user-preset-storage), [live sync 22..26](#live-sync) |
| v3 | [Four-track commands 27..30](#cmd-27); [historical track 4 conversion](#track-semantics) |
| v4 | [TRACK_PARAM 31](#cmd-31), [TRACK_CHANGED 32](#cmd-32), WATCH capability negotiation |
| v5 | [Step grid and preset grid encodings](#step-record) |
| v6 | [SONG 33](#cmd-33) and INFO chain capacity |
| v7 | [Chance](#step-record), [MOTION 64](#cmd-64), [backup 65..67](#v7-full-backup-65-67), [parameter-count evolution](#parameter-count-history) |
| 1.0 | [FM6 patch commands 68..71](#fm6-patches-68-71), chord keys and FUN8; track 4 becomes a synth part |
| 1.0.3 | [FM6 targets and per-preset patches](#fm6-patches-68-71); live-sync capability bits |
| 1.0.4 | [MENU_DESC / MENU_SET 72..73](#menu-settings-72-73-104) |
| 1.0.5 | [Ratchet](#step-record); MENU descriptors append tabs |
| 1.1 | [Parameter locks](#parameter-locks); DRUM lane levels, FUN9 |
| 1.1.5 | Same-engine sound loads preserve motion; SCREEN OFF setting |
| 1.2 | [LFO and SPREAD parameters](#lfo-sync-and-spread), [nudge](#step-record), [128 motion records](#cmd-64), [song sections](#cmd-33), FUN10 |
| 1.3 | MENU HOME setting |
| 1.4.1 | [FM6 voice bank 74..77](#fm6-voice-bank-74-77-141) |
| 1.5 / 1.5.1 | [INSERT](#15-the-insert), [filter TYPE and ENV SYNC](#15-filter-type-env-sync), [MIDI LEARN 78..79](#midi-learn-78-79-15); dotted delay values |
| 1.5.5 / 1.5.6 | [Conditions](#step-record); MENU MIDI routing, SELECT, screen wake and enum additions |
| 1.6 | [CUSTOM palette 80..81](#custom-palette-80-81-16) |
| 1.6.1 | Optional MENU 2ND CORE setting |
| #212 | [Stable engine IDs and catalog](#engine-ids-212) |
| #321 | [Extended backup objects](#the-fm6-voice-bank-and-the-slice-records-321-ids-20-21) |
| #456 | [Raw store export 82..83](#raw-store-export-82-83-456) |
| Optional #27 | [MACRO profile descriptors and presets](#optional-macro-profile-27) |

## Debug screen capture (CDC)

This optional diagnostic transport is ASCII over USB SERIAL, separate from MIDI
SysEx. It adds no MIDI command IDs or persistent settings. Build with
`FELUCCA_SCREEN_CAPTURE=1`; the normal/default build reports only
`SCAP CAPS version=1 enabled=0`. See the [capture guide](../docs/screen-capture.md)
for scope, installation and the host PNG/JSON tool.

Commands end with CR; the console echoes the command, emits one SCAP record and
returns its normal `> ` prompt. Numbers are decimal uint32, hashes/CRC and raw
pixel bytes are uppercase hexadecimal. Arguments, token, state and bounds are
validated before data access. Only one session owns the bounded capture band.

| Command | Response/meaning |
| --- | --- |
| `screen caps` | `SCAP CAPS` capability and actual compiled-build metadata |
| `screen begin` | New nonzero token and `SCAP STATE`; busy if a live capture owns the band |
| `screen begin wake` | Protocol 2: explicitly wake a supported stopped view, await redraw, hold awake for the bounded session |
| `screen status TOKEN` | Current state and scene diagnostics, without advancing |
| `screen read TOKEN OFFSET LENGTH` | `SCAP DATA` for 1–96 bytes within the current ready band |
| `screen next TOKEN OFFSET` | Release the band and request exactly the next 3,840-byte offset; final offset 115,200 completes |
| `screen cancel TOKEN` | Cancel ownership; stale tokens fail |

An enabled CAPS record carries `version=2 enabled=1 width=240 height=240
format=RGB565BE band_bytes=3840 max_read=96 ttl_ms=120000`, plus `build`, full
40-character `commit`, `dirty`, `source`, `mode=stopped-static` and read-only
`scr_state`, `led_stage`, `idle_ms`. Unknown provenance must not be replaced with
a locally supplied commit. A dirty flag identifies modified inputs; its commit
does not identify those modifications. Protocol 1 diagnostic builds have the same
default capture grammar but no `begin wake`; new clients retain default protocol 1
support and reject an explicit wake before BEGIN unless CAPS advertises version2.

STATE carries `token state offset length draw_hash awake page home menu
scr_state led_stage idle_ms`. States are `idle`, `pending`, `ready`, `complete`,
`changed`, `expired`, `cancelled`, `coverage`, `asleep`, `unsupported`, and protocol 2
`waking`. WAKING has offset/length/draw_hash 0 and awake 0: no band is readable.
The normal SLPIN/SLPOUT settling and a complete redraw/DISPON precede PENDING;
the first captured band is a subsequent frame. Acquisition
supports awake, stopped static HOME and MENU views; INFO/other editing pages, held input,
overlays and unsafe states are rejected. Changing HOME scopes, levels or transient
indicators invalidate the draw stream. Default BEGIN leaves LCD/input state
unchanged. Explicit BEGIN WAKE validates scene eligibility before waking,
touches inactivity once and restores LCD/LED visibility independently of MIDI
WAKE policy, without synthetic notes/controls, navigation or transport changes.
It inhibits AUTO OFF through final verification until CANCEL, terminal failure
or fixed expiry. Normal inactivity resumes from the wake interaction afterwards;
neither polling nor lease cleanup refreshes it. Screen state and LED stage describe commanded
firmware state, not optical brightness or hardware readback.

DATA carries `token offset length crc data`. CRC is IEEE CRC32 of the raw bytes
in `data`; pixels are big-endian RGB565. The host must validate every absolute
offset/length/token, compare scene/draw identity across all bands, receive all
115,200 bytes, advance to complete and recheck status/build identity before
publishing an image. Firmware permits rereads within a ready band; client-side
completion checks prevent skipped or duplicate chunks becoming a valid PNG.

The fixed session lifetime is 120 seconds from BEGIN, including host stalls;
requests do not extend it. Unsigned elapsed-time checks handle timer wrap.
Failed commands emit `SCAP ERROR code=argument|stale|state|bounds|busy|unsupported`
as appropriate. Native LCD transfer failure also terminates as `coverage` rather
than publishing READY; its explicit wake hold is released. This does not add a
state or change the protocol version.
Missing coverage or a changed repeated full draw aborts the
session; no partial frame is a successful screenshot. `draw_hash` is an ordered
draw-operation FNV32 fingerprint, **not** the final image CRC. The host computes
the latter after complete assembly. This transport captures intended LCD pixels,
not physical panel colours, controller interpretation or backlight glow.
