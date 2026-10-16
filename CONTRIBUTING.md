# Contributing to Felucca

Thanks for helping! To keep things easy to follow, please use the right place:

| What | Where |
|---|---|
| A bug you can reproduce | [Issues](https://github.com/hugelton/Felucca/issues/new/choose): one issue per bug |
| A feature idea or request | [Discussions › Ideas](https://github.com/hugelton/Felucca/discussions/categories/ideas) (no promise it will be added) |
| How to use it, or how something works | [Discussions › Q&A](https://github.com/hugelton/Felucca/discussions/categories/q-a) |
| Forks, mods, music, demos | [Discussions › Show and tell](https://github.com/hugelton/Felucca/discussions/categories/show-and-tell) |
| Anything else | [Discussions › General](https://github.com/hugelton/Felucca/discussions/categories/general) |

Feature requests posted as issues will be moved to Discussions or closed.

## Reporting a bug

Please include the Felucca version (hold HOME > ABOUT), your computer's OS and browser if the editor or
installer is involved, the steps to reproduce it, what you expected and what happened. A photo or a short
video helps.

## Pull requests

For engine, effect, platform or persistence work, start with the
[native extension contracts](docs/extending.md) and [development guide](AGENTS.md).

Pull requests are welcome, including AI-assisted ones, with the same bar for all:

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

The web editor and installer live in [Felucca-WebApp](https://github.com/hugelton/Felucca-WebApp).
