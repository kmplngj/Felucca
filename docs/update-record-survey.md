<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Offline update-record survey

`tools/fm1_update_records.py` inspects an already saved raw flash file for byte
sequences matching **the native loader's record predicate**. It supports private
investigation of the saved-data exposure described in
[flash capacity §2.2](flash-capacity.md#22-areas-felucca-must-not-touch) and
[#438](https://github.com/kmplngj/Felucca/issues/438). It does not establish the
external SPL's scan bounds, required fields, selection order or failure behavior.

Run from the repository root with standard-library Python; no MIDI dependencies
or build are needed:

```sh
python3 tools/fm1_update_records.py --raw /path/to/already-saved-flash.bin
python3 tests/update_records_test.py
```

`--raw` is required: it is the operator's assertion that file byte zero represents
flash address zero. The tool cannot verify that provenance. Input must be a regular
file, 4 KiB to 1 MiB inclusive, containing complete 4 KiB sectors from address zero.
Symlinks, directories, devices, FIFOs, empty files, partial sectors and oversized
files are rejected. The size limit is checked before reading and reads are bounded.
A shorter prefix is accepted, with the missing higher-address range explicitly
reported. Do not pass an extracted storage payload or a slice from a nonzero flash
address as `--raw`: its offsets would be wrong. File extensions are ignored.

The tool reads supplied bytes unchanged. It does not detect or unpack `.fwsc`/UFW
packages, decrypt bytes, convert to a logical flash view, open hardware or network
connections, acquire dumps, execute a loader, or rewrite the input. A package or
nonzero-origin slice that happens to meet the size/alignment checks remains the
operator's incorrect raw-file assertion. Keep the source of a saved file and its
raw/ciphered/logical interpretation with any investigation; geometry and a hash
cannot establish those facts. No vendor dump or package data is checked into the
tests.

## Output and interpretation

The only output mode is deterministic JSON on stdout. Exit **0** means the survey
completed, whether there are zero or several matches. Exit **2** means invalid
arguments, an unreadable/special file, malformed size/extent, or an input that was
observed changing during the read; errors go to stderr without a JSON result.

The JSON contains:

- `sha256`: SHA-256 of all supplied input bytes, including areas outside record
  tails. Paths and timestamps are omitted so identical bytes produce identical
  output.
- `coverage`: start zero, exclusive end, byte count, 4,096-byte sector size,
  complete-sector count and `not_supplied` ranges up to the parser's 1 MiB limit
  (the existing native flash map, not a measurement of physical chip capacity).
  All offsets and field integers in the JSON are decimal.
- `predicate`: at each sector's `+0xF00`, little-endian u16 at `+0` is nonzero,
  equals CRC16-XMODEM (initial value zero) over bytes `2..79`, and u16 at `+6`
  equals `0x5441`.
- `candidates`, in ascending sector order: sector and record offsets, stored
  CRC16, words at `+2`/`+4`, marker at `+6`, twelve name bytes at `+8..19` as hex,
  u32 at `+72`, and the complete observed 80 bytes as hex. These are field values,
  not additional acceptance requirements or validated addresses/names.
- `limitations`: interpretation constraints included in every successful result,
  including a result with no candidates.

The [production cleanup predicate](../firmware/loader/ldr_core.c) reads 80 bytes.
The [native record writer](../firmware/src/ota.c) writes 112 bytes; this survey
neither requires nor validates the extra 32 bytes. The existing
[native-style host fixture](../tests/update_record_fixture.h) supplies context for
those fields, and the survey tests independently cross-check CRC with Python's
`binascii.crc_hqx`. Synthetic tests include arbitrary crafted fields and sectors
protected by the loader, plus nonmatching CRC, marker, zero-CRC and alignment
controls.

Every supplied sector tail is examined, including the boot area and protected
saved-data sectors. This deliberately does **not** reproduce the native loader's
cleanup windows, skip rules, descending traversal or erase behavior. Candidate
order is output formatting, not an inferred boot-time priority.

A match does not authenticate data, establish bootability or authorize installation.
A no-match result does not prove SPL safety, even for a complete 1 MiB file: the
external SPL's predicate and view of flash remain unverified. Ciphered raw bytes
may differ from the logical bytes seen by a reader; no decryption is attempted.
A missing range is also unexamined. Do not treat either result as a save/refusal
policy, a capacity allocation decision or evidence that an update or reboot will
succeed. The tool adds no runtime storage guard or format change.

Reports include the candidate's literal bytes and can contain private saved data.
Keep them local unless deliberately sharing that evidence. No physical FM-1 check
is needed to validate this file-only tool. Qualifying actual SPL behavior remains
separate pending hardware/source evidence.
