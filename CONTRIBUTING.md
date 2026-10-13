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
- test it on a real FM-1;
- run `tests/run_tests.sh` (see [BUILDING.md](BUILDING.md));
- new files carry the GPL-3.0-only SPDX header.

Include **User test instructions** in the PR description: setup, how to reach the
changed function, actions to try and expected results. For FM-1 testing, spell out
the buttons, hold/tap gestures, pages and knobs. Keep these instructions separate
from tests already run and label pending hardware checks. The
[PR testing skill](.agents/skills/pr-testing/SKILL.md) provides the detailed checklist;
the PR template includes a place for it. Explain when hardware testing is unnecessary.

By contributing you agree that your contribution is licensed under GPL-3.0-only.

The web editor and installer live in [Felucca-WebApp](https://github.com/hugelton/Felucca-WebApp).
