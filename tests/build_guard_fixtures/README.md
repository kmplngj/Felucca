<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Firmware safety guard fixtures

`python3 tests/build_guard_test.py` runs 19 portable tests with positive/negative
subcases. They call the production `tools/build.py` guards against temporary
images, symbols, disassembly and synthetic firmware/linker trees under ignored
`build/`. No working firmware or SDK files are modified. The host runner includes
these tests, independently of SDK/toolchain availability.

Coverage includes entry/stub and app-slot boundaries, exact RAM/POOL minimum
margins and one-byte failures (including the 100 B NOINIT spare floor), missing/malformed/reversed symbols and regions,
ROM range neighbors in signed/unsigned/hex assignments and annotated calls,
missing disassembly and RAM-text calls, loader sections/symbols at RAM-window
boundaries, HAL register/window literals, volatile casts, inline assembly and
transitive/continued register macros. C-object read-once casts, linker symbols,
comments, neighboring address ranges and the empty publication barrier remain
accepted. Loader metadata and zero-sized nonresident sections are distinct from
allocated code/data/BSS.

Fixtures exposed two previous acceptance gaps: missing POOL symbols could appear
as extra headroom, and unannotated ROM-address assignments were ignored. Missing
symbols now fail explicitly. The loader check also validates complete allocated
section extents and startup/BSS symbols against its existing load/decompressed
image window; it no longer merely rejects starts in XIP. No linker or runtime
memory layout changes are made. Continued HAL macro definitions are resolved.

These are syntax/link-layout checks, not a full C/ELF/ISA verifier. The ROM scan
conservatively rejects immediate assignments in the ROM range (even a hypothetical
numeric value used as data); call destinations require objdump annotations.
An explicit empty RAM-text disassembly header is accepted, while missing/malformed
input and undecoded RAM-text rows are errors. App disassembly also contains scalar
and ASCII table rows; their displayed values must match the bytes before they
can be skipped. Data-only output cannot stand in for app instructions. The loader entry is bound to the actual text start. Actual link/objdump failures remain failures in the build process.

`python3 tests/build_guard_target_test.py` separately compiles/links with JieLi
Clang 4.0.1 and actual build flags. Variable unsigned/signed 64-bit division and
unsigned remainder require unavailable runtime helpers; a widened 32-bit product
and constant 64-bit shifts link successfully. This is compiler/link evidence,
not a ban on all 64-bit arithmetic, target execution or device timing.

Missing toolchain means a named unittest skip; a configured but broken compiler,
Docker runtime or unexpected link result is a failure. Actual sources, objects,
disassemblies, linker diagnostics and compiler/flag provenance are retained in
`build/host/build_guard_target/`. No host-policy or system-permission changes are
performed. #45 owns DSP cost fixtures, #55 package extents and #35 CI skip policy.
