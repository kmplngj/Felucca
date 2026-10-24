<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Cold minsize call-boundary experiment

The #462 candidate saves 1,752–2,044 linked app bytes in three controlled native
target comparisons, at a cost of 16 bytes of main RAM. It also adds main-loop
calls and an 824-byte nested AUTOMATION signature frame. This is a measured
compiler experiment awaiting full regression, review and FM-1 latency/stack
qualification; the size result alone does not establish an acceptable default.

## Scope and protection

`tools/size_fns.py` keeps its existing source selection and ISR/callback analysis.
After that analysis, it adds `noinline` only to an eligible `minsize` definition
referenced by a function that does not have `minsize`. Functions reached from
either hardware ISR, flash-busy `.ram_text` roots and their complete reference
closure, and existing `alwaysinline` definitions cannot receive the new attribute.
Unknown flash-busy indirect dispatch fails closed using the existing graph checker.
Existing attribute groups are preserved, including existing `minsize`/`noinline`.
Repeated passes are identical. This does not expand `SIZE_FILES`, globally outline
functions or change the existing `minsize` selection.

The implementation is native work on the firmware host's compiler pass. No donor
code, engine source, assets, dependency pins, sound arithmetic, saved bytes, wire
IDs, memory map or safety margins are changed. The motivating donor estimate in
[#462](https://github.com/kmplngj/Felucca/issues/462) is not a Felucca measurement.

## Controlled target evidence, 2026-10-24

Unchanged source: `1523fd0e9bb1483082ba5a71834e7255c04e7ff5`, with exact Engines pin
`9630426f5c4a34a209ca851356fbe8ba3c4c6d19`. Baselines were built before modifying
tracked inputs. The actual JieLi Clang reports 4.0.1; its binary SHA-256 is
`c45189ee624de0430deb0db02e6dce171fb5538e7fe323e3964dc8ac6236240f`.
The SDK packaging inputs match the build's AC79NN_SDK_V1.2.1 reference hashes.
The Linux toolchain ran through the build's normal macOS Docker path.

Both sides use `-Os -ffunction-sections -fno-builtin -Wall -Wno-unused-function`,
selective size enabled, product `FM-1_900`, no release override and no diagnostic
flags. Standard and MACRO explicitly use `FELUCCA_CPU2=1`; the omitted-worker
variant uses `FELUCCA_CPU2=0`. MACRO uses `FELUCCA_PROFILE=macro`; the other two
use `standard`. Compiled worker support retains its runtime default OFF.

Each clean baseline was a complete fresh target/loader/package build. The
candidate then used `build_app()` to compile and link the actual firmware with
that profile's frozen baseline `build/gen` inputs. Generated assets and identity
therefore remain fixed. Raw unoptimized IR is byte-identical in every pair;
removing only the newly added definition-level `noinline` tokens makes candidate
annotated IR byte-identical to its baseline. No candidate package was produced
by this controlled experiment. These apps are measurement artifacts, not packages
for installation; a final candidate needs its own truthful fresh build identity.

| Profile | App before → candidate, B | App delta, B | Candidate app spare, B | RAM before → candidate, B | Candidate RAM spare, B |
| --- | ---: | ---: | ---: | ---: | ---: |
| Standard, CPU2 compiled | 496,316 → 494,272 | −2,044 | 87,292 | 62,392 → 62,408 | 11,320 |
| Standard, CPU2 omitted | 492,768 → 490,748 | −2,020 | 90,816 | 55,764 → 55,780 | 17,948 |
| MACRO, CPU2 compiled | 580,368 → 578,616 | −1,752 | 2,948 | 62,392 → 62,408 | 11,320 |

The app authority is 581,564 B. Main RAM capacity is 73,728 B and its minimum
spare is 4,096 B. The extra 16 B is `.bss` in every pair; `.data` sizes are
unchanged. Compiler merged-global symbols/offsets also change, but this report
does not attribute the entire allocation delta to a particular alignment cause.
No new C state was introduced. Other regions are unchanged:

| Region | Standard CPU2 compiled / MACRO | CPU2 omitted | Capacity and minimum spare |
| --- | ---: | ---: | --- |
| POOL used/spare, standard | 336,440 / 32,200 B | 336,440 / 32,200 B | 368,640 B; 8,192 B minimum spare |
| POOL used/spare, MACRO | 354,200 / 14,440 B | Not measured | Same |
| RAMTEXT used/spare | 3,152 / 21,424 B | 2,924 / 21,652 B | 24,576 B |
| NOINIT used/spare | 15,576 / 120 B | 15,564 / 132 B | 15,696 B; 100 B minimum spare |

RAMTEXT contains 2,924 B of flash-busy code and, when enabled, 228 B of worker
code. Flash-busy machine code is byte-identical in all pairs and retains its
916-instruction/no-call guard. Worker code retains 84 instructions and its
indirect-job-only call guard; its trace pointer relocates by 16 B with main RAM.

Main user/supervisor stack reservations remain 24,320/7,936 B with 256 B guards.
When compiled, the worker's 4,096 B user reservation including its guard and
256 B supervisor reservation remain accounted in RAM. CPU2-off contains none of
the worker code, stacks or mailbox. Reserved stack bytes are not live usage or
available call-chain margin.

## Call-boundary and latency audit

The candidate adds 61 boundaries to either standard build and 62 to MACRO.
Every added attribute is outside the existing ISR and flash-busy closures.
Actual IR is idempotent in all three profiles. All linked ISR-closure functions
retain their total/loop instruction, loop divide/call and weighted-cost tuples;
all target budgets pass without changing baselines. This is static evidence only.
Instructions are not universally byte-identical: global addresses and merged
field offsets relocate, and the CPU2-off audio ISR becomes 6,630 B instead of
6,634 B with 2,070 instructions on both sides, including shorter encodings and
minor scheduling changes in the buffer epilogue.

The audit covered the complete boundary/caller inventory and linked function
size/prologue differences, including these main-loop groups:

| Area | Observed changes and remaining concern |
| --- | --- |
| Graphs, panel and redraw | Standard `draw_graph` 21,904 → 20,008 B; `ui_input` 20,402 → 19,974 B; `ui_draw_page` 14,598 → 14,512 B. `pr_follow`, `ev_sig`, `slice_sig` and small page/hash/format helpers gain calls. Standard direct call sites for `graph_mode` rise 4 → 9 and `cur_page` 55 → 62. Dense automation, roll, SONG, slice and HOME/scope redraw need device latency checks. |
| Editor/USB service | `ed_handle`, `ed_begin`, `ed_send`, MIDI-LEARN listing and palette replies shrink; bounded `ed_b` stays bounds checked, with 236 → 251 direct call sites. These are call sites, not calls per second. The ISR-side USB poll keeps its static tuples, but that does not measure main-loop reply latency, USB audio errors or host behavior. |
| Settings, storage and FM6 bank | `st_read`, `st_prog` and `st_erase` keep their linked instruction counts and local prologues. CRC/sector helpers and deferred settings saves gain calls; bank validation/commit/boot code changes. Flash-busy code remains byte-identical and call-free. Check saves/transfer recovery and stopped/idle deferral separately from ordinary loaded control service. |
| Sound installation and FM6 UI | `fm6_adopt` changes from 182 → 168 B in standard while its local prologue grows 212 → 216 B. FM6 card/format helpers and `graph_fm6` change. No sound-install contract or patch bytes are edited; sound/transition oracles and real switching remain required. |
| EUCLID and undo | `eu_render`, `eu_close`, `eu_say`, parameter editing and MIDI-LEARN clear paths change through outlined common step/string/settings helpers. Preview/apply/cancel, undo ownership and loaded knob response remain checks. |
| Boot and fault path | Standard `fm1_main` shrinks 2 B; `fm1_cstart` retains its 273 instructions, 29 calls and 8 B explicit prologue allocation. Bank boot/validation and crash rendering gain boundaries. `fm1_fault` becomes a separate 364 B function in worker builds and 268 B without CPU2. Boot/rescue readiness and fault recovery are not timed here. Do not trigger a crash merely to test size policy. |

The stack tradeoff is material. In every profile, `ev_sig` becomes a separate
824 B local prologue (776 B explicit allocation plus 48 B register push), while
`draw_graph` still reserves 1,964 B plus a 52 B push. Its call to the existing
`ev_list` adds that callee's unchanged 184 B local prologue (132 B allocation
plus a 52 B push). The new 824 B frame
is nested on the AUTOMATION signature path; it is not offset by a smaller
`draw_graph` frame. The explicitly `alwaysinline` `graph_signature` remains
inlined as required by its existing shared-scratch comment.

Other standard local prologue changes include `pr_follow` newly 52 B,
`slice_sig` newly 20 B, `cpal_store` newly 12 B, `eu_say` 40 → 48 B,
`fop_dec` 12 → 16 B and `fvb_end` 312 → 316 B; MIDI-LEARN/palette listing and
bank boot frames shrink. These numbers describe local prologues, not cumulative
maximum stacks. No stack watermark, nested-interrupt qualification or remaining
live stack margin is claimed.

## Validation and remaining gates

At this experiment stage:

- Unchanged size-pass fixtures: 16/16 pass. Expanded fixtures: 22/22 pass,
  including positive boundary selection, candidate-only call chains, protected
  callback tables, flash closure, existing/grouped attributes, quoted names,
  `alwaysinline`, unknown flash dispatch and repeated passes.
- Three full clean baseline builds and three candidate app compile/link checks
  pass existing resource/flash/worker guards. All six target budget runs pass.
  The only compiler warning on both sides is the inherited unused `x` in
  `ui_draw.c:728`; no new warning was observed.
- Full applicable host/UI/editor/storage/sound-transition suite, fresh final
  candidate build/package, browser gate where applicable, and review remain
  separate delivery gates. This focused experiment does not report them passed.
- FM-1 measurements are unperformed: no flash, playback, panel, transport,
  latency, boot or live stack test was run. No device CPU or speed claim follows.

Before retaining the policy, compare the same baseline/candidate profiles,
runtime CPU2 setting, banks, settings and workload. Follow the
[performance procedure](performance.md#device-timing-and-stress-procedure) and
[diagnostics setup](diagnostics.md), keeping audio lateness, render maxima,
nested scan cost, shedding and USB/MIDI error deltas separate. Include dense
AUTOMATION/roll/SONG redraw with sustained knob turns and four-part audio,
editor reply/backup/palette/LEARN traffic with USB audio at both rates, normal
boot/rescue entry, and stopped/idle save plus FM6-bank recovery. Confirm the
additional AUTOMATION frame has acceptable live stack margin. Reject or
separately refine boundaries if service latency, audio behavior or stack margin
regresses; app savings are not sufficient acceptance.

## Reproduction and artifact map

Raw evidence is under ignored `build/issue462/` in the experiment worktree:
`baseline/{standard,cpu2off,macro}` holds clean full-build logs, resource reports,
IR, ELF, app, packages, listing sidecars and frozen generation; the corresponding
`candidate/` directories hold actual target app/ELF/IR/listings, guard logs and
`measurement.json`, without a candidate package. `candidate.diff` preserves the
two-file compiler/fixture patch. `comparison.json`, `boundary-audit.json` and
`ramcode-check.json` retain complete sizes, boundary callers/call sites,
prologue changes and flash/worker code hashes. `env.json` records only the two
SDK/toolchain paths. `capture_baseline.py`, `app_trial.py` and `analyze.py` retain
the executed procedure.

### Executable standard-profile reproduction

The local scripts above are an artifact inventory, not prerequisites for this
recipe. The following complete script reproduces one standard/CPU2-compiled pair
from a checkout containing the reviewed candidate `tools/size_fns.py`. Install the
[build prerequisites](../BUILDING.md#prerequisites-macos), select the matching
JieLi toolchain, and set `AC79_SDK` and `JIELI_TOOLCHAIN` to absolute local paths.
Run from that candidate checkout's root. It creates a separate local clone under
ignored `build/`, changes only that clone, initializes the exact engine pin and
runs one full baseline build plus one candidate app compile/link. It needs GitHub
access to initialize the engine submodule. Logs and artifacts remain in the
printed directory even if a check fails.

The candidate directory is explicitly **NOT-INSTALLABLE**. Its app intentionally
retains the baseline identity to isolate code generation; the script creates no
candidate package and removes stale active baseline packages/resource reports
after archiving them. Do not install either raw measurement app. A normal fresh
final candidate build/package with truthful identity remains a separate gate.

```sh
rtk proxy uv run --locked --group build python - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

BASE = "1523fd0e9bb1483082ba5a71834e7255c04e7ff5"
ENGINES = "9630426f5c4a34a209ca851356fbe8ba3c4c6d19"
CLANG = "c45189ee624de0430deb0db02e6dce171fb5538e7fe323e3964dc8ac6236240f"
reviewed = Path.cwd()
candidate_pass = (reviewed / "tools/size_fns.py").read_bytes()
assert b"noinline" in candidate_pass and b"boundary" in candidate_pass
(reviewed / "build").mkdir(exist_ok=True)
trial = Path(tempfile.mkdtemp(prefix="issue462-repro-", dir=reviewed / "build"))
source, before, after = trial / "source", trial / "baseline", trial / "candidate-NOT-INSTALLABLE"
before.mkdir()
after.mkdir()
print("Evidence directory:", trial, flush=True)
(trial / "candidate-size_fns.py").write_bytes(candidate_pass)

# Fix feature/CI inputs before importing build helpers or launching subprocesses.
for key in list(os.environ):
    if key.startswith(("FELUCCA_", "GITHUB_")) or key in ("GOLDEN_UPDATE", "BUDGET_UPDATE"):
        del os.environ[key]
for key in ("AC79_SDK", "JIELI_TOOLCHAIN"):
    assert key in os.environ, f"set {key} to the matching absolute local path"
    os.environ[key] = str(Path(os.environ[key]).expanduser().resolve())
os.environ.update(FELUCCA_PROFILE="standard", FELUCCA_CPU2="1", FELUCCA_SIZE="1")

def run(*args, cwd=source, log=None):
    if log is None:
        return subprocess.check_output(args, cwd=cwd, text=True).strip()
    with log.open("w") as output:
        subprocess.run(args, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, check=True)

run("git", "clone", "--no-hardlinks", "--no-checkout", str(reviewed), str(source), cwd=reviewed)
# Preserve the original repository identity despite cloning locally.
run("git", "remote", "set-url", "origin", "https://github.com/kmplngj/Felucca.git")
run("git", "checkout", "--detach", BASE)
run("git", "submodule", "update", "--init", "firmware/engines")
assert run("git", "rev-parse", "HEAD") == BASE
assert run("git", "rev-parse", "HEAD", cwd=source / "firmware/engines") == ENGINES
assert run("git", "status", "--porcelain") == ""
run("uv", "run", "--locked", "--group", "build", "./build.sh", log=before / "build.log")
out = source / "build"
artifacts = ("felucca.bin", "felucca.elf", "felucca.dis", "felucca.dis.profile.json",
             "felucca.ll", "felucca_size.ll")
for name in (*artifacts, "resource-report.json", "build-identity.json", "felucca.fwsc"):
    shutil.copy2(out / name, before / name)
shutil.copy2(source / "tools/size_fns.py", before / "size_fns.py")
shutil.copy2(out / "loader/ota.bin", before / "ota.bin")
shutil.copytree(out / "gen", before / "gen")
baseline_report = json.loads((before / "resource-report.json").read_text())
assert baseline_report["configuration"]["compiler"]["sha256"] == CLANG
run("python", "tests/target_budget.py", str(before / "felucca.dis"),
    "tests/target_budget.txt", log=before / "budget.log")

# Only the compiler pass changes; no fixture, source, asset or identity regeneration.
(source / "tools/size_fns.py").write_bytes(candidate_pass)
assert run("git", "diff", "--name-only") == "tools/size_fns.py"
(trial / "candidate.diff").write_text(run("git", "diff", "--binary", "HEAD") + "\n")
for stale in (out / "resource-report.json", *out.glob("felucca*.fwsc")):
    stale.unlink(missing_ok=True)
shutil.rmtree(out / "gen")
shutil.copytree(before / "gen", out / "gen")
os.chdir(source)
sys.path.insert(0, str(source / "tools"))
import build as B
import build_report as R
import size_fns as S
assert baseline_report["configuration"]["sdk_sha256"] == B.SDK_SHA256

# Capture the baseline ELF's actual section/symbol evidence, then compile/link.
headers, symbols = B.tc_all(("common/bin/objdump", "-h", before / "felucca.elf"),
                            ("common/bin/objdump", "-t", before / "felucca.elf"))
(before / "sections.txt").write_text(headers)
(before / "symbols.txt").write_text(symbols)
with (after / "build.log").open("w") as log:
    # build_app's compiler child diagnostics inherit stdout/stderr; retain them too.
    saved = os.dup(1), os.dup(2)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        evidence = B.build_app()
        errors, notes = B.check(*evidence)
        print("\n".join(notes), flush=True)
        assert not errors, errors
        resources, stacks = R.resources(B, evidence)
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        os.close(saved[0])
        os.close(saved[1])
for name in artifacts:
    shutil.copy2(out / name, after / name)
for name, text in zip(("sections.txt", "symbols.txt", "ram-disassembly.txt"),
                      (evidence[1], evidence[2], evidence[4])):
    (after / name).write_text(text)

assert (before / "felucca.ll").read_bytes() == (after / "felucca.ll").read_bytes()
old, new = [(d / "felucca_size.ll").read_text() for d in (before, after)]
def attrs(ir):
    groups = dict(re.findall(r"^attributes (#\d+) = (.*)$", ir, re.M))
    return {m[2].strip('"'): m[3] + " " + " ".join(
        groups.get(g, "") for g in re.findall(r"#\d+", m[3])) for m in S.IR_DEF.finditer(ir)}
old_attrs, new_attrs = attrs(old), attrs(new)
added = {name for name in new_attrs if re.search(r"\bnoinline\b", new_attrs[name])
         and not re.search(r"\bnoinline\b", old_attrs[name])}
assert added and not added & S.isr_reach((before / "felucca.ll").read_text())
stripped = S.IR_DEF.sub(lambda m: m[0].replace(" noinline", "", 1)
                       if m[2].strip('"') in added else m[0], new)
assert stripped == old, "annotation delta contains more than selected noinline tokens"
assert S.annotate(new, S.size_names())[0] == new, "annotation is not idempotent"
assert {str(p.relative_to(out / "gen")): p.read_bytes() for p in (out / "gen").rglob("*") if p.is_file()} == {
    str(p.relative_to(before / "gen")): p.read_bytes() for p in (before / "gen").rglob("*") if p.is_file()}
(after / "measurement.json").write_text(json.dumps({
    "kind": "isolated-target-app-trial-NOT-INSTALLABLE", "resources": resources,
    "stack_reservations": stacks, "compiler_flags": B.app_flags(),
    "raw_ir_matches_baseline": True, "only_added_noinline": sorted(added),
    "annotated_ir_idempotent": True}, indent=2) + "\n")
run("python", "tests/target_budget.py", str(after / "felucca.dis"),
    "tests/target_budget.txt", log=after / "budget.log")
manifest = {str(p.relative_to(trial)): hashlib.sha256(p.read_bytes()).hexdigest()
            for directory in (before, after) for p in sorted(directory.rglob("*")) if p.is_file()}
(trial / "SHA256SUMS.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Used-byte deltas:", {name: value["used_bytes"] - baseline_report["resources"][name]["used_bytes"]
                           for name, value in resources.items()})
print("Stack reservations equal:", stacks == baseline_report["stack_reservations"])
print("Candidate app is NOT INSTALLABLE; evidence:", trial)
PY
```

This script deliberately asserts the original compiler and SDK input hashes.
Changing the profile/CPU2 configuration, toolchain, source or engine revision is
a new comparison and must be recorded separately. Expected original standard
result: app −2,044 B, RAM +16 B, POOL/RAMTEXT/NOINIT unchanged. This recipe does
not run the full regression suite or establish device acceptance.

README assessment: its introduction and “Development direction and process”
already cover CPU/RAM/size experiments, baseline comparison, responsive controls,
audio deadlines and pending hardware checks. No engine, installation,
compatibility or product-overview change needs a README edit. Changelog adds one
grouped Optimized entry linking this evidence with pending device qualification.
Diagnostic activation, defaults, transport and output are unchanged; diagnostic
guides need no command or capability inventory update.
