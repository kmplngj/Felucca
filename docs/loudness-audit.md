<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Native host loudness audit

`tools/loudness_audit.py` renders explicitly selected factory sounds through the
native host simulator and writes a digital-level report plus audition WAVs. It
never changes presets, trim tables, samples, generators or golden baselines.
This is the measurement-tool stage of [#679](https://github.com/kmplngj/Felucca/issues/679).
Role assignment, percussion comparisons, stereo/mono listening and a recorded
retain/reject decision for each candidate remain separate acceptance work.

The tool adapts the deterministic role phrases and report approach from
[Optimist](https://github.com/w0ts/optimist/tree/2ab989d5a2012160d6488bf56f23d89000d9f855)
at `2ab989d5a2012160d6488bf56f23d89000d9f855`, under GPL-3.0-only. The phrase
manifest records the donor files and native drum adaptation. It imports no donor
engine or sample bank. Existing native engine and asset licenses remain in place;
see [LICENSING](../LICENSING.md).

## Run a selected audit

Use a recursive Git checkout with the native CC0 samples, Python 3.12, `uv` and a
host C compiler with its signed-integer-overflow UBSan runtime (Clang or GCC).
No JieLi toolchain or connected FM-1 is needed. The optional,
locked `audit` dependency group includes the build generators, NumPy, SciPy and
the independent pyloudnorm test reference. See [BUILDING](../BUILDING.md) for
environment setup. Apply the local storage preflight/test wrapper where required
by the checkout's development instructions before running these commands.

Run from the repository root. List supported engine IDs and roles first:

```sh
uv run --locked --group audit python tools/loudness_audit.py --list
```

Create a selection JSON, for example `build/loudness-selected.json`, after creating
`build/`. Start with one case; add cases only for a deliberate comparison:

```json
{
  "schema": 1,
  "cases": [
    {
      "id": "analog-bass-0",
      "engine_id": 0,
      "preset": 0,
      "role": "bass",
      "reverb": "hall"
    }
  ]
}
```

Choose a fresh output name for each run:

```sh
uv run --locked --group audit python tools/loudness_audit.py \
  --cases build/loudness-selected.json --out build/audit-run-first
```

The output must be a nonexistent, direct child of the repository's ignored
`build/` directory named `audit-run-*`. Existing directories, nested destinations
and source-tree destinations are rejected. The tool generates its own standard
profile and native tables/samples in that directory and compiles a private host
probe; it does not reuse `build/gen/` or a previously built hostsim. Generator
sample output and cache are also private to the run. Failed runs retain available
logs and evidence; use another fresh name when retrying.

`--cc clang` selects a host compiler command; otherwise `CC`, then `cc`, is used.
Explicit additional flags use repeated `--cflag=-DNAME=value`. Compiler version,
argv and logs are retained. Flags are part of the evidence identity; do not compare
results across different flags as if the runs were identical.

The compiler always receives `-ffp-contract=off`,
`-fsanitize=signed-integer-overflow` and
`-fno-sanitize-recover=signed-integer-overflow` after caller flags. A missing
compiler/runtime fails preparation. Signed overflow in the unchanged native mixer,
DSP or master path terminates the child and leaves that case unavailable; it must
not be bypassed to obtain level metrics. Retained stderr identifies the failing
operation. An overflow is a finding about that workload, not a successful audit.

## Selection and timing contract

The initial slice uses the canonical 13-engine `standard` profile: IDs
`0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13`, with FM4 disabled and SLICE enabled.
Retired DIGITAL ID 1, MACRO ID 14 and omitted engines are outside this slice.
Names and stable keys are checked against the native catalog. Preset indices are
zero based and validated by the compiled native engine; actual preset names and
parameter snapshots appear in each report.
The probe also enumerates its actual compiled engine IDs; an omission or selection
override that differs from all 13 canonical IDs rejects the capture, even when
the selected case's own engine is present.

Each case requires a unique `id`, `engine_id`, `preset`, `role` and explicit
`reverb` (`room` or `hall`). IDs contain at most 48 letters, digits, underscores
or hyphens. Unknown fields, duplicate JSON keys and duplicate case IDs fail.
Synth roles are manual choices: `bass`, `held`, `comp`, `melody` and
`one-key-chord`. The tool does not infer a role from a preset name. Choose a role
that represents the intended use before interpreting a level difference.

DRUM uses engine ID 10 and separates factory `preset` from the stored `kit` ID:

```json
{
  "schema": 1,
  "cases": [
    {
      "id": "kit0-kick",
      "engine_id": 10,
      "preset": 0,
      "role": "drum-hit",
      "reverb": "room",
      "kit": 0,
      "lane": 0
    },
    {
      "id": "kit0-beat",
      "engine_id": 10,
      "preset": 0,
      "role": "drum-beat",
      "reverb": "room",
      "kit": 0
    }
  ]
}
```

Canonical kit IDs are `0, 4, 5, 6, 7, 8, 9, 10, 11`; retired aliases 1–3 are
rejected. Individual hits require lane 0–7, mapping to native notes
`36, 38, 39, 42, 46, 45, 37, 56`. The mixed beat has no `lane` field. Individual
hits and the mixed beat answer different questions and must be reviewed separately.

The reviewed manifest, [loudness-phrases.json](../tools/loudness-phrases.json),
declares note/velocity schedules at 100 BPM. Synth bodies span 32 sixteenth notes
(4.8 seconds) plus a 250 ms tail cap. The native mixed beat spans 16 sixteenths
(2.4 seconds) plus a two-second tail cap; an individual hit captures two seconds.
Note events round down to the 32-frame control boundary, with note-offs before
note-ons at a shared boundary. Capture length rounds up to a whole control block.
Reports contain the resulting events, body and tail frame counts. A capped tail
does not establish that a sound or reverb has fully decayed.

Budgets are checked before compilation: 1–8 cases, at most 12 seconds per case
and 60 seconds total, at 44,100 frames/second. Each frame retains two stereo
32-bit raw captures (16 bytes total) and one stereo 16-bit WAV (4 bytes, plus its
header). The provenance records selected byte/frame budgets. At most eight
audition WAVs are written; this is intentionally not a full-catalog sweep.

## Read the evidence

Each case starts in a fresh child process, initializes native defaults and loads
its factory sound through `host_preset`/`sound_load_factory`. Factory voice mode,
LEVEL and sends are preserved. The declared reverb replaces hostsim's historical
ROOM setting. Master is 4096, USB-fixed and LOWCUT are off, and performance FX
must remain inactive. This policy is recorded with track/global parameter arrays.

The two raw files are interleaved little-endian signed 32-bit stereo:

| Artifact | Meaning |
| --- | --- |
| `pre.i32le` | Exact quantized input to `master_out`, after track/INSERT/sends/buses/stereo-side processing and master scaling; before DC removal, LOWCUT, limiter and soft clipping |
| `post.i32le` | Actual stereo `mix_block` output after `master_out` |
| `post-master.wav` | Actual post-master audio at the same fixed Q15 scale for every case; no per-file normalization |
| `events.txt`, `render.*`, `report.json` | Rounded event schedule, child command/logs, actual names/policy and metrics |

The pre-master input is copied immediately after **each** control block, before
the next block reuses the mixer buffers. Its native expression is
`(((mix_[lr] + wet) >> 2) * 4096) >> 10`; discarded low bits remain discarded.
For every block, the probe replays native `master_out` in stereo sample order
from its saved DC/remainder/limiter state, compares the actual output, and restores
the actual post-state. Unsupported performance mode, tap overflow or a replay
mismatch fails capture. Attenuating then rescaling the post-master signal cannot
undo DC removal, quantization, limiting or soft clipping.

Metrics divide raw values by 32768: full scale is a named virtual Q15 digital
scale. Negative headroom and overrange counts can therefore remain visible in
pre-master evidence. An out-of-range post-master sample fails rather than being
clipped into the audition WAV. Sample peaks and Q15 rail counts do not diagnose
analogue clipping. Hardware DAC scaling, USB packing/resampling, physical master
pot calibration and analogue loudness are outside these host measurements.

Stereo and arithmetic mono fold-down are metered separately. Stereo loudness sums
the K-weighted channel energies; it cannot cancel merely because L and R are in
opposite polarity. The mono fold-down can cancel and helps identify that separate
compatibility concern.

`integrated_lufs` uses rate-appropriate K filters, complete 400 ms windows at
100 ms hops, a strict greater-than −70 LKFS absolute gate and a relative gate
10 LU below the absolute-gated power mean. Incomplete trailing windows are ignored.
`loudest_100ms_lkfs` is the maximum complete 100 ms K-weighted window, evaluated
at every sample position. This custom transient metric is useful for percussion;
it is separate from gated integrated loudness and standard 400 ms momentary
loudness. `tail_energy` is unweighted summed squared stereo amplitude after the
declared body boundary, not a loudness or decay-time measurement.

Statuses distinguish `ok`, `empty`, `silence`, `short` and `all_gated`. Unavailable
measurements are JSON `null`; nonfinite samples and malformed captures fail.
`true_peak` is always `null` with `not_implemented`: sample peak is not intersample
true peak. The meter is not a certification or a perceptual-equality claim.

At the run root, `provenance.json`, `resolved-profile.json`, command records and
compiler logs identify source revisions, dirty state, dependency versions,
profile, flags and budgets. `source-before.json` and `source-after.json` hash the
tracked input closure (including native assets and baselines) plus audit sources;
a change during the run fails. `probe.json` hashes the renderer and `manifest.json`
hashes retained generated files, raw captures, WAVs, reports and logs. The manifest
does not hash itself. Preserve the whole run when comparing or sharing findings.

## Qualification and listening

Run the focused fixtures with the same locked environment:

```sh
uv run --locked --group audit python tests/loudness_audit_test.py
```

These fixtures cover published filter coefficients, a separately installed
`pyloudnorm==0.2.0` DeMan reference on aligned complete inputs, channel-energy
invariants, gate/window boundaries, strict JSON and invalid selections. Native
fixtures exercise the actual compiled master path and repeated/reordered/subset
captures, retain raw evidence under `build/audit-run-*`, and check source hashes.
They also exercise fixed expected tap quantization/bounds, actual compiled-profile
omission rejection and fatal native arithmetic overflow despite earlier caller
flags that attempt to disable recovery protection.
Reference agreement does not override explicit window/gate boundary rules or
establish full BS.1770 conformance. See the dedicated Host loudness audit CI job
for remote fixture results and retained artifacts; instructions alone are not a
passing run.

For a listening review, keep playback gain fixed across the selected WAVs, inspect
the stereo and mono results, and audition both individual drum lanes and their
mixed beat. Record the source/run identity, manual role, transient/tail behavior,
audible level jumps and a per-candidate retain/reject rationale. Every generated
case initially says `review_required` and `not_performed`; the tool makes no trim
recommendation or automatic acceptance decision. Keep listening decisions beside
the immutable run evidence rather than editing its hashed reports.

No FM-1 flashing is needed to qualify this host tool. Real-device DAC/USB listening
and any later approved sound/default/trim changes require their own exact-content
validation under [CONTRIBUTING](../CONTRIBUTING.md). This tooling stage alone does
not close #679.
