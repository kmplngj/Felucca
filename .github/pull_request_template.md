<!-- SPDX-License-Identifier: GPL-3.0-only -->
<!-- Fill each section using .agents/skills/pr-testing/SKILL.md; remove prompts. -->

## Change

<!-- Describe the problem and resulting behavior. Link the issue (Closes #... when appropriate). -->

## Validation performed

<!-- Identify the tested revision/flags, commands and results. Separate host, target,
emulator and real FM-1 evidence; name skipped checks and remaining limitations. -->

## User test instructions

<!-- Give actionable instructions even when author checks already passed.
For documentation/tooling-only changes, explain why hardware testing is unnecessary
and supply the relevant verification procedure. -->

1. **Build/setup:** <!-- PR commit/artifact, flags/profile, prerequisites, install procedure if applicable.
   CLI handoff from a trusted caller checkout: install uv (macOS: brew install uv),
   then uv run --locked --group midi tools/fm1_pr.py NUMBER.
   Use --automatic only for the intended existing merge artifact/variant.
   Local builds: uv run --locked --group build ./build.sh.
   No manual pip setup or installer-backend flag; don't run unreviewed PR installer scripts. -->
2. **Reach the function:** <!-- Known starting state, track/engine, physical buttons,
   tap/hold/release, page/menu route, knob numbers and visible labels. -->
3. **Test and expect:** <!-- Actions and observable expected results for each relevant scenario/regression. -->
4. **Finish/report:** <!-- Relevant cleanup and what to report if a check fails. -->

**Hardware status:** <!-- Passed on the specified revision/scenarios, pending, or unnecessary with a reason. -->

## README assessment

<!-- Name updated sections or explain specifically why existing text covers the result. -->
