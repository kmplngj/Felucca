<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Offline FM-1 boot-area survey

`tools/fm1_bootarea.py` surveys saved bytes for the read-only part of
[#619](https://github.com/kmplngj/Felucca/issues/619). It reports the SPL format,
boot-record/header CRCs, SPL container/payload CRCs, chip key and the clock fields
stored in `isd_config.ini`. It uses only Python's standard library. It does not
open MIDI/USB devices, execute a loader, or write files or firmware.

## Procedure

1. Leave the FM-1 disconnected. Use an existing private dump starting at flash
   address zero, or an already obtained `.fwsc` package. Retain its original
   bytes, source, acquisition date, full SHA-256 and any backup receipt privately.
   This command does not acquire or verify a device backup. See the
   [FM-1 Transporter recovery project](https://github.com/kurogedelic/FM-1-transporter)
   for the separate backup/recovery path.
2. From this checkout's root, select the saved file's actual format explicitly:

   ```sh
   python3 tools/fm1_bootarea.py --raw /private/flash-at-zero.bin
   python3 tools/fm1_bootarea.py --package /private/official.fwsc
   ```

   `--raw` accepts at least the first 16 KiB (`0x4000`) from flash address zero;
   a complete 1 MiB dump also works. A partial 16 KiB head is enough for this
   survey, but is not a recoverable full-flash backup. Saved files are limited to
   2 MiB; package `flash.bin` entries must be 16 KiB through 1 MiB. These are
   parser limits, not measurements of the device's flash capacity.
3. Retain the output and exit status. Exit **0** means a recognized SPL format
   and checked boot-area fields passed; **1** means unknown/damaged boot-area
   content (read the findings); **2** means unreadable, oversized or malformed
   input. Multiple paths of the same format may be supplied. A malformed input
   stops processing with exit 2; an unknown/damaged head still prints its bounded
   findings and allows the next path to be inspected.
4. Report the exact checkout revision, format flag, dump provenance, output and
   expected versus observed result. Output includes paths and chip keys; review
   it before sharing. Keep raw dumps and vendor packages private.

Without a selector, recognizable AC791N UFW headers or FM-1 package markers select
package parsing; other bytes select raw parsing. Filename extensions never select
a format. A damaged package can lose both identifying patterns: use `--package`
for any file known to be a package. Explicit selectors never fall back to another
format. To check the tool without private inputs, run:

```sh
python3 tests/bootarea_test.py
```

Expect synthetic CRC, extent, truncation, board and clock-field cases to pass.
Optional official V15/V16 checks print explicit skips unless the private files
are already in `build/recovery-inputs/FM-1_v15.fwsc` and `FM-1_v16.fwsc`.
No firmware build or hardware installation is needed for this tooling check.

## Interpret the findings

- **M-VAVE V15 / V16** names are SPL CRC16/size hints. **m-bootloader** is an
  `AC79BLID`/board hint; a board other than `fm1` returns exit 1. These identifiers
  and CRCs are not authentication. Only the separate **identical to the official
  FM-1_015 / FM-1_016 package's** line means the entire 16 KiB head matches its
  recorded SHA-256. It does not identify the rest of a raw dump or package.
- **UNKNOWN** can still have intact record headers, SPL CRCs and readable config.
  The tool prints those useful findings and returns 1. Unsupported SPL containers
  (including unciphered SDK SPL bytes) are reported as damaged/unsupported for
  this survey; this does not decide whether an installer accepts the package.
- **isd_config.ini declares SYS_CLK / OSC_FREQ** describes saved 32-bit field
  values only; HSB/LSB divider fields are printed as stored integers. Historical
  V15/V16 references declare 360/320 MHz respectively. Missing fields are omitted;
  no clock register is read or decoded. m-bootloader configures the clock itself.
  Live clock evidence remains [#618](https://github.com/kmplngj/Felucca/issues/618).
- Package parsing checks the AC791N UFW header, declared saved size, 1..11 entry
  count, entry-list CRC, all listed file extents/data CRCs and nonoverlap, then
  requires one type-0 `flash.bin`. It does not apply the installer loader allowlist
  or whole-package stock pins. Unknown loaders and boot areas remain surveyable.
  An arbitrary `FELUCCA-LOADER-1` string never bypasses these checks.
- Raw parsing checks only the 16 KiB head. It checks record-header CRCs before
  `0xA0`, the single-bank encrypted BANKCB SPL at `0xA0`, its load address
  `0x01C02000`, size, header/payload and boot-record CRCs. It does not verify app
  data or external region descriptors. Config extent/nonoverlap, full config
  record CRC and the key-blob CRC are checked before using values. Recognized
  clock markers must have four value bytes and may not repeat. This is a bounded
  field survey, not a complete `isd_config.ini` grammar validator.

A successful survey does not prove bootability, loader compatibility, successful
installation, preservation of user data or a live USB route. Package bytes cannot
establish which boot area a device currently has. This slice leaves firmware,
loader, Python/browser installer policy and their accepted package matrix
unchanged. V16/cross-bootloader returns, m-bootloader operation, Open firmware,
physical recovery, live clocks and #619's backup-first device survey retain their
separate review, CI and FM-1 qualification gates.

## Source provenance

The utility and original synthetic tests were extracted from
[PR #622](https://github.com/kmplngj/Felucca/pull/622), exact source commit
[`a2481789d8b7e588eca7b988710ada9e20e294ac`](https://github.com/kmplngj/Felucca/commit/a2481789d8b7e588eca7b988710ada9e20e294ac)
by Jan Kampling, co-authored by Claude Opus 5.5, under GPL-3.0-only. The known
SPL/head identifiers and BANKCB survey follow that implementation. This extraction
adds bounded package/config parsing, explicit format selection and causal malformed
input tests; it removes the marker-based package shortcut. Existing pure format
helpers in `fm1_install.py` and `fm1pkg_make.py` are reused without changing them.

The donor cites felucca-bsp `afd83ede` and m-bootloader as format references and
states it copied no felucca-bsp MPL code. No vendor or m-bootloader binary data is
included here; all checked-in fixtures synthesize their contents.
