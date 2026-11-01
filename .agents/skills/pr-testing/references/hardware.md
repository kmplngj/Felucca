<!-- SPDX-License-Identifier: GPL-3.0-only -->
# FM-1 user procedure

Verify navigation against the candidate's code, tracing `ui_input.c`, `params.c`,
`ui.c`, `ui_layer.c` and `menu_items.c` only as relevant. Match visible labels and
gestures; hosted guides may describe another revision. Leave an unverifiable route
pending. Select the changed behavior, original bug and relevant regression; include
boundaries, cancel, another track/engine and older data only when affected.

For early hardware iteration, `tools/fm1_pr.py NUMBER --validation target` omits
host/browser validation; keep those gates pending. For a final standard-profile
artifact, prefer `--automatic` when its tested merge revision is intended, avoiding
an extra exact-head build. Installation still requires the current request's scope.

For a live FM-1 session or a retry after a tooling failure, apply
[bounded hardware sessions](../../../../docs/ai-workflows.md#finish-bounded-hardware-sessions)
when selecting checkpoints and reusing completed evidence. Keep the full repeatable
PR procedure available; guide the current tester through only its remaining checks.

1. **Build and prerequisites.** Identify the tested firmware commit, PR head, build flags/variant
   and intended device. Give an exact artifact/run link when available, or checkout
   and build commands for that revision with a link to prerequisites. Identify
   the installable `.fwsc` package; a raw `.bin` is not a user install package.
   For hardware changes, give the install command or verified installer procedure
   from [BUILDING](../../../../BUILDING.md#install). Give the uv setup and an executable
   command from a trusted caller checkout, for example `brew install uv` on macOS,
   then `uv run --locked --group midi tools/fm1_pr.py NUMBER` (or append `--automatic`
   only when the existing automatic artifact is the intended revision/variant).
   No installer-backend flag or manual pip setup is needed. The caller's locked
   environment and installer must not come from unreviewed PR scripts. For local
   builds use `uv run --locked --group build ./build.sh`; image-dependent tests
   use the same `build` group. Preserve explicit build-profile/variant requirements;
   the standard artifact does not establish testing of a different profile.
   The default hosted release or
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
   Use the label printed on the physical panel: the FM-1 button for the firmware's
   `SCL` pages is **SEL**, between FX and ENV; distinguish it from the SELECT knob.
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
