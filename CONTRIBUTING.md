# Contributing to Felucca

For now, I manage this personal fork's development and issues on my own, following
my own priorities and wishes. Broader community input and contributions may become
part of the process once the larger tasks I want to complete are done. See the
[README development status](README.md#development-status) for the current policy.

The requirements below guide my development work and any future contributions.

## Issue notes

When recording a bug, include the build commit, Felucca version, relevant host OS
and browser, reproduction steps, and expected versus observed behavior. Include
diagnostics, photos or recordings when they help explain the problem.

## Pull requests

For engine, effect, platform or persistence work, start with the
[native extension contracts](docs/extending.md) and [development guide](AGENTS.md).

Maintainer-led pull requests and any future contributions, including AI-assisted
work, use the same requirements:

- keep it small and focused on one thing;
- make sure you understand the change and can explain it;
- test hardware-dependent changes on a real FM-1 and report any pending device checks;
- run the applicable checks in [BUILDING.md](BUILDING.md), including
  `tests/run_tests.sh` for firmware changes;
- new files carry the GPL-3.0-only SPDX header.

Include **User test instructions** in the PR description: setup, how to reach the
changed function, actions to try and expected results. For FM-1 testing, spell out
the buttons, hold/tap gestures, pages and knobs. Keep these instructions separate
from tests already run and label pending hardware checks. The
[PR testing skill](.agents/skills/pr-testing/SKILL.md) provides the detailed checklist;
the PR template includes a place for it. Explain when hardware testing is unnecessary.

By contributing you agree that your contribution is licensed under GPL-3.0-only.

The ANALOG, LOFI, TRIO, WHEEL and NOISE engines and the code they share (`firmware/engines/`, a git submodule) live in
[Felucca-Engines](https://github.com/kmplngj/Felucca-Engines), under the MIT licence: changes to them go there, as
pull requests to that repository.

New reusable GPL engines belong in the separate
[Felucca-Engines-GPL](https://github.com/kmplngj/Felucca-Engines-GPL) collection.
Its seed is published; engine implementation and firmware integration remain pending
under [#360](https://github.com/kmplngj/Felucca/issues/360). Keep host-specific
glue in Felucca and follow the [collection/profile ownership plan](docs/extending.md#planned-gpl-collection-and-mixed-profiles).
Existing native engines stay here until a separately qualified extraction. GPL additions
must not be submitted to the MIT collection under an MIT header.

The web editor and installer live in [Felucca-WebApp](https://github.com/kmplngj/Felucca-WebApp).
