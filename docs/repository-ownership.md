<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Repository ownership

Choose the repository before implementing work or creating an issue. Felucca work spans
four repositories; this guide decides which one owns a change.

## Choose the repository

| Repository | Implementation and issue ownership |
| --- | --- |
| [kmplngj/Felucca-Engines](https://github.com/kmplngj/Felucca-Engines) (MIT) | Portable engines, engine-exclusive presets/assets/generators, reusable DSP/interface and collection tests with an MIT-compatible source/dependency closure. Maze, original-data Bouba/Kiki, Paula and WAVE S belong here. |
| [kmplngj/Felucca-Engines-GPL](https://github.com/kmplngj/Felucca-Engines-GPL) (GPL) | GPL-derived portable engines, their exclusive content/generators and collection tests, including DUELL WAVE, JUNO, SID, CZ, Prophet and other GPL fork ports. Retain permissive dependencies' own notices. |
| [kmplngj/Felucca](https://github.com/kmplngj/Felucca) | Firmware host: global stable IDs, registration/profiles, exact dependency pins, voice/arena and service hooks, hardware, native panel/MOD, effects, storage, firmware-produced protocol/descriptors, emulator/runtime, integration and FM-1 qualification. Cross-repository adoption plans stay here. Existing firmware-native engine work stays here until an explicitly scoped extraction. |
| [kmplngj/Felucca-WebApp](https://github.com/kmplngj/Felucca-WebApp) | Editor/installer client code, UI/assets, client tests and consumption of firmware descriptors/protocol. This repository does not own the firmware protocol or engine registry. |

## Find existing work first

Check the selected repository's live Issues setting and open/closed issues, relevant
comments and PRs across all four repositories before creating work. Reuse existing
owners and follow transferred URLs. If WebApp Issues is enabled, create client tickets
there. While disabled, track them in Felucca with a `Felucca-WebApp:` title and an
explicit **implementation repository: kmplngj/Felucca-WebApp** line; leave repository
settings unchanged when filing a ticket. Client implementation and PRs still go
to WebApp. Resolve inaccessible or disabled engine destinations as a blocker rather
than filing portable engine work in firmware.

## Place code by license

Choose the collection from the actual copied files, transitive dependencies and
asset licenses, not the donor's root license or the final firmware's GPL license.
GPL code and host helpers stay labelled GPL. Retain Apache/BSD/MIT and asset notices
individually; GPL placement does not clear restricted factory banks, samples or artwork.
Unresolved provenance blocks copying; keep mixed-license source-selection work in
a Felucca coordination issue until the implementation boundary is established.

## Split engine, host and client work

Split portable engine work from host integration and client work into linked issues
and PRs. Put source pins, provenance, portable controls/contracts and engine tests
in the collection issue; link a Felucca host owner for global IDs, profiles, memory,
services, persistence/protocol and hardware acceptance, plus a client owner if needed.
Reserve global firmware IDs only in Felucca. Commit/review collection changes there
first, then update Felucca to an exact commit and validate integration; dependency
edits are complete only once committed in the collection, not inside a submodule
checkout. `firmware/engines/` is the current MIT pin. The GPL collection and intended
`firmware/engines-gpl/` pin are still pending
[#360](https://github.com/kmplngj/Felucca/issues/360), not a working build input.
The [instrument routing review](instrument-issue-routing.md) records the moved ideas
and retained integration owners.
