<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Developer-only loader LCD observations

This opt-in diagnostic variant records completed LCD work in loader RAM. It is
for reviewed maintainer measurements, not a release or a declaration that the
normal loader has passed hardware qualification. It changes code generation,
adds timer reads/stores and delays a successful restart by approximately three
seconds. Active-probe timing must stay separate from production timing.

## Build and software checks

From the reviewed source revision with the [build prerequisites](../BUILDING.md):

```sh
FELUCCA_LDR_LCD_TRACE=1 uv run --locked --group build ./build.sh
SANITIZE=1 uv run --locked --group build python tests/ldr_trace_test.py
```

Unset the flag for the ordinary build; only `0` and `1` are accepted by the
loader builder. `--release` refuses the enabled flag. The app compiler also
receives the explicit flag so the build configuration records it; app behavior
does not consume it. Retain the revision, resource report, profile, toolchain,
loader ELF/listing and installable `build/felucca.fwsc` hash. A loader-only link
does not establish a complete package or its application/resource provenance.

The tests compile the actual renderer and service, production native OTA
framing/dispatch and the readout adapter. They cover completed versus submitted
rows, partial frames, transfer failure, a pre-existing failure latch, overflow,
unsigned timer wrap, passive reads, a bounded watchdog/USB read window, client
correlation and calibrated interval bounds. Default/explicit-zero host objects
are compared. Matching a previous production target binary requires a separate
controlled target comparison; host equality alone does not establish it.

## RAM record and native diagnostic query

The loader keeps at most 128 records of six 32-bit words, plus seven control
words: 3100 B of additional static state before target alignment. Only completed
records become visible. Overflow is latched; there is no wrap or overwrite.
The array lives in the loader image's normal zeroed RAM, not retained app state.
Reset loses it. No allocation, formatting, flash operation or transport send
occurs inside a measured callback.

Each record contains raw entry/exit TIMER4 ticks; kind/state/first/last row;
completed-row count, stop reason and display-failed flag; signed native error;
and progress percent. A row increments only after its actual LCD data transfer
completed. Kind 1 measures the status callback from its first C-level timer read;
kind 2 includes the admission calculation of a progress callback that actually
draws; kind 3 covers fresh DISPON arming and its command. Compiler prologues and
probe effects require disassembly assessment. Coalesced/no-draw progress calls
do not produce a record.

Stop reasons are 0 complete, 1 aggregate-budget stop, 2 new transfer failure and 3
an already latched failure. Existing transfer deadlines, pending/CS/source
ownership, failure latching and flash decisions are preserved. No completion
bit is fabricated or suppressed, no SPI clock/register is changed, and no
source-ownership fault is injected.

Only the enabled **loader** accepts native M-UPGRADE command`0x3E` in its outer
handshake service. The normal app and disabled loader retain their old behavior.
Requests use the existing native pack7/checksum framing with four body bytes:
`version1, nonce_low, nonce_high, record_index`. Replies contain exactly 32 body
bytes: `version1, index, count, flags, nonce_low, nonce_high, declared_ticks_per_us,
reserved0`, followed by the six little-endian record words.

Flags bit 0=overflow, bit 1=active callback, bit 2=invalid index. A client must reject
any nonzero flag. Index 255 samples the raw timer in word 0 and repeats the
declared ticks/us in word 1; the remaining words are zero. Queries do not consume
or clear records. Malformed size/schema receives no diagnostic reply. The
reply is bounded by the existing native 32-byte send capacity.

Queries are not decoded from nested LCD/watchdog polls or during erase/program.
They are served while idle before an install, after failure in the ordinary
retry loop, or during the enabled variant's approximately three-second
post-success read window. That window feeds the watchdog and services USB and
handshakes/diagnostic reads, but starts no new installation. It ends without a
host and then follows the ordinary detach/reset path. Its millisecond clock
introduces up to 1 ms endpoint quantization.

## Read-only client and controlled installation seam

With a **known, already running diagnostic loader** and a single connected FM-1,
the standalone command is read-only:

```sh
uv run --locked --group midi tools/fm1_loader_trace.py \
  --port "Felucca Update" --phase startup --out build/lcd-startup
```

Use the exact MIDI name reported by the host. This command does not enter update
mode, upload a package, install firmware or trigger REC/ROM recovery. It refuses
an ordinary app identity. A normal completed installation resets too soon for
a human to launch a post-success capture; do not race it manually.

For a separately authorized maintainer install, `TracingUpdater` extends the
existing `fm1_install.Updater` only at its write-phase observation boundary.
The inherited `install()` still performs package-family/model validation and
post-install identity verification. The maintainer must bind the exact reviewed
package hash/resource report before opening MIDI, preserve current data/recovery
backups, and retain one transport owner. Call that validated `install()` entry
point, never the internal `write()` method directly. No new automatic retry or
fallback to ROM is introduced.

Startup observation must be accepted before app-writing starts. A post-success
observation failure is retained as INCOMPLETE and must not suppress normal
firmware verification or trigger another flash attempt. The caller must check
both `trace_results` statuses; successful firmware verification alone is not a
successful diagnostic run. The regular installer remains unchanged.

## Timing interpretation and pending FM-1 acceptance

The client bounds each timer sample between host time before send and after
receipt. Two samples at least 0.5 s apart provide conservative frequency bounds,
including host/USB delays and unsigned wrap. The declared 24 MHz source is not
itself calibration. Both frequency bounds must lie within 1% of 24 MHz, the record
set must remain unchanged, all required rows must complete, and conservative
duration upper bounds must be at most 250 ms per redraw and 2 ms for DISPON.
Insufficient coverage or loose/failed bounds are INCONCLUSIVE, not proof of a
production deadline failure or permission to change thresholds after a run.

Startup requires WAITING and DISPON. A successful full-session observation also
requires VALIDATING, WRITING, FINISHING, SUCCESS and at least one 18-row progress
strip. Partial/error records remain visible and are never counted as completed
frames. Per-query and whole-capture deadlines are 0.7 s and 2.5 s, without retries.

**Pending real-device validation:** after exact-candidate full applicable CI,
review and package/resource checks, run the maintainer-controlled install from
normal HOME, PLAY/REC off, USB connected and other clients closed. Observe the
panel: normal waiting/checking/writing progress and completion, followed by
normal Felucca startup. Keep power/USB connected. Retain both trace reports and
normal installer verification. Independently reread all backed-up objects/MENU
and check display and sound after normal power cycling. Restore the known-good
normal firmware and data after the diagnostic session.

This procedure does not qualify slow/stuck SPI, source reuse after a real
in-flight timeout, native 250 ms late recovery, interruption/power-loss retention,
whole-chip CPU or live stack. It also does not prove physical pixel correctness
from completed row counts. Those gates remain separately pending; in particular,
an instrumented healthy run must not silently clear unmodified-production timing
or fault-ownership requirements.
