<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Matryoshka adoption review — 2026-10-25

<!-- felucca-upstream:glvno/matryoshka@99f1149d55fa549c4202e6f5080610770399c832:selective-adoption -->
## Recommendation
Use Matryoshka as a source for exact coefficient caching, bounded partial LCD updates and performance-control semantics. Keep implementation in the existing owners below; this issue coordinates the source review and watcher registration, and does not authorize wholesale runtime/editor adoption.

**Implementation repository: kmplngj/Felucca.**
Source: [glvno/matryoshka](https://github.com/glvno/matryoshka/tree/99f1149d55fa549c4202e6f5080610770399c832), main at `99f1149d55fa549c4202e6f5080610770399c832`.
Felucca comparison SHA: `d73eb9cff185e987c1dcd8f3c2b2e3890a610693`.

## Useful work and existing owners
- **#179 / #180:** donor [per-block overhead change](https://github.com/glvno/matryoshka/commit/fc545a69aa3f9df75a5c8f29d08e32ceed6673a1) caches settings-derived envelope/resonator calculations, reduces provably bounded divisions and retains oscillator helper caches. Its moving-rates fixture is useful for stale-key regressions. Use native effective inputs and continue evolving exciter/envelope/RNG state on hits. #86 / Felucca-Engines#12 retain portable ANALOG ownership.
- **#59 / #98 / #102 / #99:** donor [partial-update rules](https://github.com/glvno/matryoshka/blob/99f1149d55fa549c4202e6f5080610770399c832/docs/ledger/device-ui.md#D-216) separate header sections, bar-end damage and preset toast restoration, and stop obsolete drawing when new input waits. [Draw timing](https://github.com/glvno/matryoshka/blob/99f1149d55fa549c4202e6f5080610770399c832/firmware/src/ui.c#L61-L103) and [rig benchmark](https://github.com/glvno/matryoshka/blob/99f1149d55fa549c4202e6f5080610770399c832/web/scripts/rig-bench.mjs) provide concrete measurement patterns. Reuse native UI, coherent submitted signatures (#95 / PR #650), DMA ownership and failure containment (#191 / PR #600).
- **#32:** [fixed-point A/B interpolation](https://github.com/glvno/matryoshka/blob/99f1149d55fa549c4202e6f5080610770399c832/firmware/src/engine.c#L1321-L1375) demonstrates octave-space interpolation for logarithmic targets and midpoint switching for choices.
- **#33:** [per-target reversed endpoint ranges and composition](https://github.com/glvno/matryoshka/blob/99f1149d55fa549c4202e6f5080610770399c832/firmware/src/engine.c#L4677-L4733) are useful macro semantics. Define replacement versus offset and native scene/motion/lock/matrix/momentary precedence through #29 / #31 / #30.
- **#662 / #94 / #46:** reuse native profiling/scenario owners rather than adding a second incompatible benchmark stack.

## Claims and limits
The deployed [changelog](https://matry0shka.pages.dev/changelog#v1.3.0) says 8–13% fewer cycles, 6x paging and 29x knob response. The [earlier detailed changelog](https://github.com/glvno/matryoshka/blob/22e7858c66752bcc5defeefaadbc6f1c09352758/CHANGELOG.md#L25-L42) explicitly identifies the 8–13% as CPU-model figures awaiting FM-1 measurement; fc545a6 likewise requests device remeasurement. Treat the current physical-device wording as unsubstantiated by the examined evidence. The calibrated RV32 instruction model is not pi32v2 physical cycle timing, and none of these percentages establishes a Felucca gain. No donor script, firmware build or device test was executed in this intake.

## Do not copy directly
- Global 128-sample Q16.16 modular graph runtime, private allocators/effects/sequencers and 64-slot flash layout: conflict with native 32-sample per-part rendering, four parts/shared voices, arenas, host services and saved data. Assemblies are editor grouping flattened before device encoding, not a ready native engine interface.
- Browser-only XL/sandbox patches, whole editor redesign, branding/fonts and community patch banks: no bounded native gap/provenance decision.
- Donor sample-rate assumption, overload thresholds or compiler/runtime helpers: require their own exact hardware/toolchain evidence; #625 already tracks the selective-O2/libcall question.
- Main-loop key-yield is not a native missing-note fix: native keyboard processing already runs in the audio sequence block.
- Row-buffer consolidation is not an automatic native RAM saving: native already shares a canvas. Measure actual lifetime-compatible candidates before proposing it.

## Acceptance / order
1. Add material pinned evidence to existing owners; avoid duplicate implementation issues.
2. Prepare pending watcher registration for repository ID **1416374163**, branch **main**, immutable initial target above. Complete non-shallow main DAG fetched and integrity checked: **841 reachable commits**, zero individually credited by this snapshot. Registration must pass ordinary review to main and state-branch integration before initialization. Use the existing schedule.
3. Capture unchanged native baselines, compare one cause at a time with JieLi Clang 4.0.1, exact SDK/profile/flags/assets, unchanged PCM and relevant future state. Report app/RAM/POOL/RAMTEXT/NOINIT/stack and hit/miss/init/switch costs. Full applicable host/target/browser checks precede retaining firmware changes.
4. Hardware acceptance stays pending: dense four-part audio with rapid panel editing, USB/TRS MIDI and UAC 44.1/48kHz; retained scenes/macros also need click/tail/manual-takeover checks. Static, host and browser evidence remain distinct.

GPL-3.0-only donor code retains attribution. Any later reusable GPL engine port belongs in Felucca-Engines-GPL with audited dependency/assets and host integration through #360; no GPL code goes to the MIT collection. Community data has separate CC BY-SA 4.0 terms. WebApp Issues is disabled; no client ticket is justified before a firmware contract exists.

README assessment: existing integration/experimentation and firmware-watch overview already covers this planning-only work; no shipped capability changes. Changelog: no entry for an unimplemented adoption plan. No diagnostic/protocol implementation changes.


## Published work

- Adoption and watcher owner: [#672](https://github.com/kmplngj/Felucca/issues/672).
- Material evidence added to [PHYS cache #179](https://github.com/kmplngj/Felucca/issues/179#issuecomment-6401204039), [synchronized envelope/LFO cache #180](https://github.com/kmplngj/Felucca/issues/180#issuecomment-6401204436), [LCD transport #59](https://github.com/kmplngj/Felucca/issues/59#issuecomment-6401204930), [A/B scenes #32](https://github.com/kmplngj/Felucca/issues/32#issuecomment-6401205317) and [assignable macros #33](https://github.com/kmplngj/Felucca/issues/33#issuecomment-6401205612).
- No new standalone optimization or client issue: these implementation owners already cover the useful gaps.

## Source review and exclusions

Full donor history is retained in an ignored bare source cache, non-shallow, with fsck passing and 841 commits reachable from the pinned main. Branch inventory was checked; registration intentionally watches main only. The source snapshot and selected optimization diffs are analysis evidence, not 841 individual commit assessments. Semantic history coverage remains zero. The deployed changelog bundle was fetched separately and checked against source; the deployed page and current main are distinct publishing snapshots.

The review inspected source and relevant complete changes for coefficient caching, arithmetic helpers, partial LCD rendering, timing counters, macro/morph composition and state lifetimes. Two read-only GPT-6.1 Sol workers contributed optimization review (high reasoning) and feature review (medium reasoning); the coordinator checked ownership, evidence and all GitHub writes.

The four-repository inventory fully paginated open/closed issues, issue comments, open/closed PRs and review comments. At intake it contained Felucca 647 issue/PR records, 184 PRs, 1,146 issue comments and 336 review comments; MIT Engines 12 issue/PR records and four PRs; GPL Engines 35 issue/PR records and two PRs; WebApp 17 PRs with Issues disabled. Relevant owner and active PR evidence was checked before publication. No repository settings changed.

Additional rejected shortcuts:

- Donor approximate idle-part skipping freezes oscillator/LFO state and periodically wakes it. It is not bit-exact future-state preservation; native #161 retains the bounded unused-preparation experiment.
- Donor always-inline multiply policy is unsuitable as a blanket adoption while native #425 investigates wide-multiply/halfword-load hardware corruption.
- Donor polyBLEP reciprocal cache removes donor widened division; the pinned MIT helper already uses 32-bit division with different Q15 edge/rounding semantics. No demonstrated native hotspot or exactness proof justifies a new ticket.
- Donor custom div64 runtime is at most a separately reviewed alternative under #625; native no-runtime-helper acceptance remains intact. Do not install global ABI helpers as routine optimization.
- Existing shared canvas, reverb unrolling, memory helpers, selective size pass and guest-PC profiling already have native implementations or owners. Donor build/release tooling does not justify replacing the current provenance and source-archive gates.

## Licensing

The reviewed implementation is GPL-3.0-only with Modular-1 and Felucca notices. Reuse ideas with native arithmetic/contracts or preserve copied notices and audit the exact closure. Community patch data has separate CC BY-SA 4.0 terms; fonts and brand assets have separate terms and are unnecessary for this adoption. The donor's statement about redistributing stock firmware is not adopted as a Felucca licensing conclusion. Existing native download-and-check behavior remains its own policy.

## Watcher state and verification

A pending local registration was added to sources.json, preserving all prior pending entries and local edits. It is not an active scheduled scan. This registration PR must be reviewed and merged to main, then integrated into automation/firmware-watch; the existing daily runner then verifies identity, branch, immutable pin and complete DAG before initializing. No new schedule, state frontier, journal assessment or completed-review credit was created.

Validation for this planning/configuration change: inspect the registry delta, run the existing ledger validator, check relative links and whitespace, and verify the created issue/comment bodies by readback. Firmware/RAM deltas are not applicable: no firmware changes or builds. Host regressions, target build, browser and physical FM-1 checks were not run. The implementation issues retain their exact-package hardware and resource gates.

The existing README already explains selective source gathering, experimentation, firmware watch and measured optimization. No README edit is needed for this proposal. No changelog entry is warranted until a meaningful capability is implemented or an optimization retained. Diagnostic capability and protocol guides need no changes because no diagnostic/protocol behavior was added.

