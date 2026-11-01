<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Software test routes

Choose by the behavior being proved. Combine layers when their gaps differ; the
matrix supplements the required CI selection, rather than reducing its coverage.

| Behavior | Existing software evidence | Residual FM-1 evidence when affected |
| --- | --- | --- |
| Documentation or independent tools | Link/instruction checks or focused fixtures; use the [CI selection](../../../../.github/CI.md#change-based-validation) | Device access only if the tool uses it |
| DSP, engines, effects, transitions | Affected host goldens, engine-switch/union and mixed-load regressions; native/Wasm parity where relevant | Listening on physical outputs, deadlines under the declared workload |
| Native UI, gestures, sequencing | UI/render regressions and deterministic [interaction replay](../../../../docs/interaction-replay.md); browser gate for actual browser input/audio | Physical panel timing, LCD readability and loaded-device responsiveness |
| Browser UI/AudioWorklet | Fresh emulator plus [Chromium gate](../../../../docs/cloud-testing.md); add a targeted assertion/replay for behavior absent from smoke | Device paths only when affected; browser scheduling is not target timing |
| Projects, presets, settings, backup | Existing round-trip, old-format, malformed-input and NOR-model fixtures; replay/browser simulated persistence | Real flash durability/timing, power-cycle recall, interrupted-write behavior |
| Editor/protocol/capabilities | Firmware producer harness plus matching WebApp Node and mock-browser fixtures, including old/missing capabilities and relevant errors | Real Web MIDI/SysEx connection, transfer/reconnect and device-applied state |
| Installer, loader, recovery | Existing simulated installer/updater, package/CRC and loader target guards | Real install/recovery, enumeration and retained user data |
| Resource use or scheduling | Fresh target resource/stack reservations and static budgets, host workload comparisons | Live stack/deadlines, interrupt nesting and USB/TRS load |

## Firmware host, replay and browser

Use named units from the existing runner/CI map with prerequisite closure; commands
and prerequisites live in [BUILDING](../../../../BUILDING.md#tests). A replay uses
the real integrated emulator's panel/UI/DSP and simulated NOR, with PCM/LCD/state
provenance. Reuse `tests/scenarios/` and the existing comparison tool before adding
a harness. Replay supports panel and channel MIDI, not SysEx/editor/update traffic.
Native capture needs neither a browser nor Emscripten. Static renderer scenes and
replay remain complementary when their assertions cover different behavior.
If a supported path lacks a scenario, a bounded one-off replay/probe under ignored
`build/` can close that gap within testing scope. Give it an observable expected
state, pixel or signal result; repeating the same output only proves determinism.
Promote a lasting regression in the owning repository within implementation scope.

Run the real-browser gate after a fresh emulator build when the changed path needs
browser evidence. It checks actual Wasm/AudioWorklet output, selected input/UI paths
and simulated save/reload. Read its named checks before deciding coverage: a green
smoke cannot establish an arbitrary new feature. Reuse deterministic signal/pixel/
state assertions; open selected images/audio only for a concrete unresolved question.
Keep subjective listening and physical display acceptance explicit.

Record source/dirty identity, generated assets, profile, flags and relevant toolchain
with each result. The hosted demo can lag the candidate or use another profile;
use matching local/CI artifacts. Firmware changes still need fresh target guards
and the complete applicable final CI plan.

## Companion WebApp

The editor/installer lives in **Felucca-WebApp**, outside this repository's Chromium
gate. Locate its authorized checkout and read its `AGENTS.md`, `README.md` and
`ci/check.py` at the selected client revision. Use those maintained commands and
fixture lists rather than a copied inventory. Record **both** producer and consumer
revisions, dirty inputs and fixture provenance; a client pin is not automatically
the firmware candidate.

Its current full gate is `python3 ci/check.py --firmware /absolute/firmware/checkout`
from the WebApp root. It generates descriptors/MENU fixtures from real firmware C,
runs both editor protocol variants and Node suites, then headless-browser menu
fixtures using simulated MIDI. Read `build/ci/summary.json` first, including skips;
expand only the affected logs or failure DOM. Required producer comparisons need
fresh candidate inputs, not stale `desc.json`/`menu.json` or mock-derived expectations.
Verify that each required fixture-fed comparison actually ran. For example, the
current full gate strips `FELUCCA_BUILD_IDENTITY_FIXTURE` and allows its absence;
run the documented `test_build_identity.mjs` separately with that variable when
the changed contract needs actual producer identity frames. A green full gate
does not close that optional comparison's gap.

Normal WebApp CI uses its reviewed `ci/firmware.json` pin and a clean producer
checkout. For an unmerged producer comparison, the current helper supports
`--firmware-revision FULL_SHA` with a clean checkout of that exact SHA; label this
**test-only candidate comparison**. Reuse an existing suitable checkout and apply
the local storage preflight before creating one. Preserve dirty work. When no
suitable checkout is available, use documented focused producer-backed checks with
explicit partial scope or leave the full comparison pending. Updating the pin or
opening a companion PR requires the appropriate requested scope.

For a visual/interactive editor flow, serve the matching WebApp locally and use
`app/index.html?mock=1` or the relevant existing browser fixture. Exercise the changed
control, expected state, capability fallback and error/reconnect behavior as relevant.
Use an existing fixture/driver for repeatable checks; add a focused regression in
the owning repository only within implementation scope. Separate mock-only results
from checks fed with real producer output.

These are complementary systems: the firmware emulator does **not** currently
expose an editor SysEx endpoint. WebApp mock-browser tests and firmware replay are
not an end-to-end WebApp-to-emulator test. Leave that integration gap visible rather
than introducing a new bridge as part of routine PR testing.
