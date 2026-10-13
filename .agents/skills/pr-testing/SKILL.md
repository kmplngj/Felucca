---
name: pr-testing
description: Prepare or update actionable PR user test instructions, especially FM-1 hardware setup, panel navigation, scenarios and expected results. Use when creating/updating a PR or handing off a change for user testing.
---
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# PR user testing

Use this skill when creating or updating a PR, or handing off a change for user
testing. Keep the PR description current with the final implementation and revision.
The [PR template](../../../../.github/pull_request_template.md) has separate sections
for **Validation performed** and **User test instructions**. Fill both; commands the
author ran do not replace instructions for the user.

## Establish the scope and route

Read the changed sources, relevant tests and [README](../../../../README.md).
Check [BUILDING](../../../../BUILDING.md),
[CONTRIBUTING](../../../../CONTRIBUTING.md) and the relevant guide for setup and
validation requirements. Trace panel routing through `firmware/src/ui_input.c`,
page definitions in `firmware/src/params.c`, `ui.c`, `ui_layer.c` and
`menu_items.c` as applicable. Verify labels and gestures against the PR's code;
the upstream wiki, hosted editor and hosted emulator may describe another revision.
Do not invent an access path. If a route cannot be verified, state what is unknown
and leave that check pending.

Choose scenarios that exercise the actual change, the original bug or intended
behavior, and the relevant unchanged behavior. Include boundary values,
cancel/undo, another track or engine, save/load/restart and older data only when
they matter to this change. For internal DSP/performance fixes, explain the
audible workload and any diagnostics needed even if no new panel function exists.

## Write the user's procedure

1. **Build and prerequisites.** Identify the PR head commit, build flags/variant
   and intended device. Give an exact artifact/run link when available, or checkout
   and build commands for that revision with a link to prerequisites. Identify
   the installable `.fwsc` package; a raw `.bin` is not a user install package.
   For hardware changes, give the install command or verified installer procedure
   from [BUILDING](../../../../BUILDING.md#install). The default hosted release or
   browser demo does not establish testing of the PR. State required cables,
   headphones/output, MIDI source/channel, host OS/browser, samples or test data.
   If the test changes stored data, explain how to back up and use a disposable
   project/slot, and describe cleanup or downgrade limits that actually apply.
2. **Known starting state.** State the starting screen, selected track/engine,
   preset/pattern and transport state. Explain how to reach that state; do not
   assume the user knows the UI. Confirm the installed version using the device's
   ABOUT screen when relevant, but retain the artifact/commit identity because
   development builds can share the same display version.
3. **Reach the function.** Give numbered physical actions from the starting
   state. Name the button, whether to tap or hold and when to release it, repeated
   page cycling, menu tab/row selection, knob number and visible label/value.
   For example, a `SAVE > PRESETS` breadcrumb needs the SAVE taps required to
   reach PRESETS; `MENU > ABOUT` needs the hold, tab, row and open actions.
   A link to a manual supplements these actions; it does not replace them.
4. **Exercise and observe.** For each scenario, state input actions and an
   observable expected result: label/value, sound, note behavior, saved state,
   host MIDI/audio result or diagnostic output. Give concrete values or durations
   where needed to reproduce the behavior. A performance check needs a baseline,
   the same workload and a measurement method; host counters or target static
   estimates do not prove real-device deadlines. Avoid bare "test audio" or
   "check that it works" instructions.
5. **Finish and report.** Explain relevant stop/cancel/restore actions. Ask the
   tester to report the commit/artifact, device version, host setup if relevant,
   scenario and observed versus expected result. Request logs or a photo/recording
   only when useful to diagnose the changed path.

## Keep evidence honest and proportionate

In **Validation performed**, list checks actually run and their results, separating
host tests, target build/static budgets, emulator and real FM-1 observations.
Record skips and limitations. In **User test instructions**, label device scenarios
**Pending hardware validation** unless that exact revision and scenario were
actually tested on an FM-1. Emulator coverage does not validate USB audio/MIDI,
TRS MIDI, update/recovery, physical panel/LCD behavior or device audio deadlines.
See [BUILDING's emulator scope](../../../../BUILDING.md#browser-emulator).

For documentation-only changes, state why hardware testing is unnecessary and
give steps to verify the changed instructions, relative links and resulting PR
description. For tooling-only changes, provide the appropriate commands, inputs
and expected outputs; include hardware steps if the tooling touches a device.
Follow the [development guide's validation rules](../../../../AGENTS.md#build-and-validate)
without requiring irrelevant firmware runs. Test instructions describe actions for
the user; they do not grant the agent permission to flash or publish.

## Final PR check

- The description identifies the final revision/build and links its issue.
- Validation results and future user checks are distinct; pending checks are explicit.
- A user can reach the function without guessing a button, page, knob or prerequisite.
- Each scenario says what to do, what to observe and how to recognize success.
- The README assessment names updated sections or explains why existing text covers
  the result, as required by [AGENTS](../../../../AGENTS.md#user-facing-documentation).
- Replace every template prompt with actual instructions or a specific reason it
  does not apply. Recheck the procedure whenever the implementation changes.
