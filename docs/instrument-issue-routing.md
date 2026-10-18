<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Instrument issue routing review — 2026-10-18

Portable implementation ideas were transferred from Felucca using GitHub's issue
transfer operation, retaining their discussions and original URL redirects. These
moves do not implement, enable or qualify any instrument. The
[AGENTS ownership table](../AGENTS.md#choose-the-repository-before-implementation-or-issue-creation)
defines future implementation and issue routing; the
[firmware-watch skill](../.agents/skills/firmware-watch/SKILL.md) applies it to findings.

[Felucca #414](https://github.com/kmplngj/Felucca/issues/414) coordinates host-side
planning. Before implementing a retained candidate, create or reuse a focused host
issue for IDs/profiles/pins, voice/arena/services, native UI/MOD, storage/protocol and
FM-1 acceptance; link collection, host and any WebApp owners. Existing host-specific
requirements in transferred issues remain required integration checks.

## MIT collection

These three prototypes use MIT references and original/licensed data. Verify the
actual transitive source and asset licenses before copying. A fixed-point rewrite
cannot silently reuse GPL host helpers. Paula's Amiberry reference is comparison
only; Bouba/Kiki excludes the donor SVG and derived contour data unless separately
cleared. WAVE S already has implementation owners in MIT Engines #4/#5.

| Original Felucca issue | Collection issue | Instrument idea |
| --- | --- | --- |
| [#125](https://github.com/kmplngj/Felucca/issues/125) | [#6](https://github.com/kmplngj/Felucca-Engines/issues/6) | Explore a compact fixed-point through-zero FM instrument inspired by Maze Voice |
| [#126](https://github.com/kmplngj/Felucca/issues/126) | [#7](https://github.com/kmplngj/Felucca-Engines/issues/7) | Explore a compact fixed-point contour oscillator inspired by Bouba/Kiki |
| [#190](https://github.com/kmplngj/Felucca/issues/190) | [#8](https://github.com/kmplngj/Felucca-Engines/issues/8) | Experiment: add a native fixed-point Paula-style sample instrument |

## GPL collection

These are GPL donor ports or experiments containing GPL adapters/content, even
where individual DSP dependencies are MIT/Apache/BSD. Preserve those licenses and
notices. Placement here does not grant rights to restricted factory banks, recorded
samples, extracted tables/artwork or third-party formulas. In particular retain the
CZ/Prophet factory-bank exclusions and Orbit CLUSTER rights gate. WAVE already has
GPL Engines #1 and Felucca #354/#360; those owners were retained.

| Original Felucca issue | Collection issue | Instrument idea |
| --- | --- | --- |
| [#43](https://github.com/kmplngj/Felucca/issues/43) | [#2](https://github.com/kmplngj/Felucca-Engines-GPL/issues/2) | Prototype a JUNO engine: KR-106 oscillators and IR3109 ladder filter from fm-106 |
| [#67](https://github.com/kmplngj/Felucca/issues/67) | [#3](https://github.com/kmplngj/Felucca-Engines-GPL/issues/3) | Add a fixed-point SID engine without replacing LOFI |
| [#68](https://github.com/kmplngj/Felucca/issues/68) | [#4](https://github.com/kmplngj/Felucca-Engines-GPL/issues/4) | Prototype a native CZ-1 phase-distortion engine with original presets |
| [#72](https://github.com/kmplngj/Felucca/issues/72) | [#5](https://github.com/kmplngj/Felucca-Engines-GPL/issues/5) | Add optional circuit-inspired 808 and synthesized 909 drum kits |
| [#81](https://github.com/kmplngj/Felucca/issues/81) | [#6](https://github.com/kmplngj/Felucca-Engines-GPL/issues/6) | Prototype a single-core Prophet-style engine with measured voice limits |
| [#107](https://github.com/kmplngj/Felucca/issues/107) | [#7](https://github.com/kmplngj/Felucca-Engines-GPL/issues/7) | Experiment: integrate X0X 303, 808 and 909 instruments in staged Felucca adapters |
| [#111](https://github.com/kmplngj/Felucca/issues/111) | [#8](https://github.com/kmplngj/Felucca-Engines-GPL/issues/8) | Experiment: add selected zp12 instruments and a faithful 12-bit sampler adapter |
| [#113](https://github.com/kmplngj/Felucca/issues/113) | [#9](https://github.com/kmplngj/Felucca-Engines-GPL/issues/9) | Experiment: adapt Dinghy's polynomial sine instrument to Felucca |
| [#129](https://github.com/kmplngj/Felucca/issues/129) | [#10](https://github.com/kmplngj/Felucca-Engines-GPL/issues/10) | Experiment: adapt Ghoulbox GURDY, medieval samples and FM6 instruments in stages |
| [#132](https://github.com/kmplngj/Felucca/issues/132) | [#11](https://github.com/kmplngj/Felucca-Engines-GPL/issues/11) | Experiment: adapt Jangada ROBO and stage selected superwave, drone and percussion sounds |
| [#135](https://github.com/kmplngj/Felucca/issues/135) | [#12](https://github.com/kmplngj/Felucca-Engines-GPL/issues/12) | Experiment: add native JIANT DRUM-X and BYTE/FLOAT instruments |
| [#141](https://github.com/kmplngj/Felucca/issues/141) | [#13](https://github.com/kmplngj/Felucca-Engines-GPL/issues/13) | Experiment: adapt selected Sloop sounds, sample packs and configurable drum instruments |
| [#168](https://github.com/kmplngj/Felucca/issues/168) | [#14](https://github.com/kmplngj/Felucca-Engines-GPL/issues/14) | Experiment: adapt WaveLoop preset banks and Yama-bruh FM drum kits in stages |
| [#181](https://github.com/kmplngj/Felucca/issues/181) | [#15](https://github.com/kmplngj/Felucca-Engines-GPL/issues/15) | Experiment: adapt Hortator Plaits drums, FM percussion and ACID in stages |
| [#188](https://github.com/kmplngj/Felucca/issues/188) | [#16](https://github.com/kmplngj/Felucca-Engines-GPL/issues/16) | Experiment: adapt ChoralRoot FM TONE, VA, CZ-1 and selected native preset content |
| [#193](https://github.com/kmplngj/Felucca/issues/193) | [#17](https://github.com/kmplngj/Felucca-Engines-GPL/issues/17) | Experiment: adapt procedural one-shot sounds into native percussion and textures |
| [#199](https://github.com/kmplngj/Felucca/issues/199) | [#18](https://github.com/kmplngj/Felucca-Engines-GPL/issues/18) | Experiment: adapt Maku ambient sound recipes and PULSE/BEEP drums |
| [#220](https://github.com/kmplngj/Felucca/issues/220) | [#19](https://github.com/kmplngj/Felucca-Engines-GPL/issues/19) | Experiment: adapt Orbit SWARM, PULSE and FM4 instruments with a separate CLUSTER rights gate |
| [#235](https://github.com/kmplngj/Felucca/issues/235) | [#20](https://github.com/kmplngj/Felucca-Engines-GPL/issues/20) | Experiment: adapt Makkuro37 subharmonic drones, Papa Srapa and AS3340 instruments |
| [#241](https://github.com/kmplngj/Felucca/issues/241) | [#21](https://github.com/kmplngj/Felucca-Engines-GPL/issues/21) | Experiment: adapt Snoop37 FM jingle timbres and audition selected SLOOP instrument content |
| [#245](https://github.com/kmplngj/Felucca/issues/245) | [#22](https://github.com/kmplngj/Felucca-Engines-GPL/issues/22) | Experiment: adapt FoMni37 chord-harp strings and voicing through native Felucca engines |

## Work retained in Felucca

- Mixed adoption roadmaps and source-selection plans remain host coordination work,
  including #54, #108, #114, #115, #133/#134/#137/#142, #167/#169/#182/#189,
  #194/#202/#221/#230/#236/#242/#246/#359/#370. Their old issue links redirect.
- #163 coordinates existing SID/CZ/Prophet/kit owners; #368 selects across mixed
  MIT/Apache/GPL FM1 Open V12 sources. Do not create duplicate engines from either.
- #228 owns Araminta-specific audition/content comparisons against DRUM-X's
  transferred implementation owner, GPL Engines #12; it is not another DRUM-X port.
- #231 compares Faust piano with the firmware SAMPLE path. Its STK/helper/import/
  generated-output license audit remains unresolved; copying or MIT placement is
  blocked until that audit establishes a source closure.
- #27 is device acceptance for the already implemented MACRO bank, not a new
  portable-engine intake. Current firmware-native DSP changes (including GRAIN's
  #323–#329 roadmap and extensions) stay with their implementation until a separately
  scoped extraction; do not move a firmware bug away from the code that needs fixing.
- WAVE integration #354/#360 and WAVE S #362/#363/#365 remain firmware work. The
  GPL collection is not yet consumed by builds; the intended GPL pin is still pending.

## WebApp

The editor/installer implementation belongs to `kmplngj/Felucca-WebApp`; firmware
remains the protocol/descriptor producer and owns the browser emulator/runtime.
At this review WebApp Issues is disabled. Preserve that setting: use explicitly
prefixed `Felucca-WebApp:` tickets in Felucca naming the implementation repository
and producer dependency while disabled; create directly in WebApp when enabled.
#339 (editor typography) and #364 (WAVE S client) remain client-tracking fallbacks;
#413 (exposing the firmware browser runtime) remains firmware work.

## Ledger continuity

Historical `reviews.jsonl` and the lossless migration archive retain their original
URLs/markers and coverage. Follow GitHub redirects during deduplication and use
returned canonical URLs in new records. The helper's explicit `issue_repositories`
setting permits all four destinations without changing the primary host,
registered donor scope, immutable pins or completed coverage.
