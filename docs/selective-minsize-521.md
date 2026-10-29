<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Remaining cold-helper minsize experiment (#521)

This bounded compiler-policy experiment was rejected for promotion. Production
selection remains unchanged; this is not a runtime improvement or a completed
[#521](https://github.com/kmplngj/Felucca/issues/521). The measured proposal added `ui_help.c` and
`category.c` to the existing selective pass: five read-only HELP/category helpers.
The optional candidate diff and raw evidence remain under ignored `build/`; the
other five issue files remain deferred. No `noinline`, LTO, `-Oz`, compiler,
ISR roots/contracts, API, sound, persistent data, profile or default changes are
included. The distinct [#462 noinline experiment](https://github.com/kmplngj/Felucca/issues/462)
is untouched.

## Matched target comparison

The unchanged base is `5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e`, with MIT Engines
`9630426f5c4a34a209ca851356fbe8ba3c4c6d19`. JieLi Clang 4.0.1 targets pi32v2 at
`-Os -ffunction-sections -fno-builtin`; standard profile, M8Stealth, CPU2 built in
(runtime OFF default), normal flash/OTA/CDC/UAC/UART settings, and the documented
AC79NN SDK1.2.1 files. Compiler SHA256 is
`c45189ee624de0430deb0db02e6dce171fb5538e7fe323e3964dc8ac6236240f`.
No borrowed asset/code or donor saving is included.

The default baseline is a fresh full target build. The no-size and candidate
compile/link controls use its exact generated inputs and linker script. Baseline
and candidate unoptimized LLVM IR are byte-identical; the sole annotated-IR
changes add `minsize` to `help_page`, `help_parse`, `help_row`, `cat_of_engine` and
`preset_cat`. The existing pass remains idempotent and excludes protected code.
These matched controls retain the baseline build identity to isolate compiler
policy from changed identity strings; they are not installable PR qualification
artifacts. A normal fresh build resolves its own actual source identity.

| Static resource | Existing selective pass | Five-helper candidate | No selective pass control |
| --- | ---: | ---: | ---: |
| Linked app (581,564 B capacity) | 491,876 B | 491,812 B | 510,680 B |
| App spare | 89,688 B | 89,752 B | 70,884 B |
| Main RAM / spare | 62,152 / 11,576 B | unchanged | 62,136 / 11,592 B |
| POOL / spare | 336,440 / 32,200 B | unchanged | unchanged |
| RAMTEXT total / spare | 3,152 / 21,424 B | unchanged | unchanged |
| `.ram_text` / `.c1_text` | 2,924 / 228 B | unchanged | unchanged |
| NOINIT / spare | 15,576 / 120 B | unchanged | unchanged |

Only **64 B** (about 0.013% of the baseline app) belongs to this batch. The
18,804 B default-versus-no-size difference measures the entire existing policy,
not an additional saving. RAM/POOL/NOINIT minimum spares remain 4,096/8,192/100 B.
The standard per-part engine arena remains 12,888 B (51,552 B across four parts). Reserved main user/supervisor
stacks remain 24,320/7,936 B, each with 256 B guards; worker user window (including
its guard) 4,096 B and supervisor 256 B remain accounted in main RAM. These are
static reservations, not stack watermarks.

## Calls, stack and service bounds

Only two linked function sizes change: `preset_cat` 106→84 B and
`ui_draw_page` 15,484→15,442 B. No new linked function appears.

- `preset_cat` adds one fallback call to existing 32 B leaf `cat_of_engine` instead
  of inlining it. Its existing register-save prologue remains unchanged; the leaf
  adds no stack allocation. The fallback is outside its bounded string searches.
- `help_page` and `help_parse` remain inlined; `help_row` stays 164 B with 88 B local
  stack allocation. `ui_draw_page` retains its 500 B local stack allocation, but
  gains five static callsites: `str_eq` twice, `cur_page`, `home_levels`, `sel_mode`.
  One `str_eq` site is inside the HELP_PAGE table search, so call overhead can repeat
  for each visited title. The fixed 40-entry table, finite title strings and maximum
  three hint tokens still bound work. This is extra service work, not a speed claim.
- Audited audio/TIMER5/worker `c1_parts` instruction/call counts and stack prologues
  remain unchanged; target budgets pass without baseline changes. Static counts
  cannot prove equal device time, main-loop service latency or deadline headroom.

Decision: reject promotion for now. The 64 B saving does not justify expanding
production policy and its qualification cost without measured service evidence.
The candidate is preserved as an optional reviewable choice; a matching FM-1
comparison would be required before reconsidering it. Do not infer acceptance
from host or emulator checks.

## Reachability and file disposition

The actual unoptimized target module was audited through function, global and
alias references and existing reviewed indirect-call contracts. Audio and TIMER5
roots plus the worker's explicit `fm1_c1_main`→`c1_parts` contract protect 595
functions. `C1_RUN(c1_parts, ...)` is the sole production job publication site.
The five `.ram_text` flash-busy roots transitively exclude the selected functions;
the existing no-call/worker-only-indirect build guards remain enabled. None of the
selected functions is stored in an IR global/callback table. They have no section
or protected attributes to replace. CPU2 OFF/ON/failure behavior is not changed.

The 595-function result is a separate audit of the recorded IR, including the
explicit worker and flash-busy roots. The reproduction script below rechecks ISR
reachability through `size_fns.annotate()` and the build's `.ram_text` no-call rule;
it does not recompute that broader closure or exclude helpers reached from
`c1_parts`. Exact IR hashes bind the recorded inputs and results, not a general
worker-protection guarantee. A different candidate needs a fresh complete audit.

| Issue file | Disposition and reason |
| --- | --- |
| `ui_help.c` (3 definitions) | Measured only: read-only main-loop page/layer hint rendering; at most 3 hints and finite strings; no IRQ masking, flash operation, allocation or wait. MACRO has read-only shape-dependent hints. |
| `category.c` (2 definitions) | Measured only: guarded metadata lookup and terminated category strings; eight category letters; main-loop browse/editor/user-preset callers; no mutation or callback. Existing unavailable-engine guards remain. |
| `ui_fm6op.c` (11 definitions) | Deferred: patch-copy/undo/publication and frequency-formatting latency need their own batch; parallel operator behavior work stays independent. |
| `ui_tools.c` (41 definitions) | Deferred: pattern/automation writes, bounded retries, protected motion loops and temporary arrays need separate critical-section/stack measurements. |
| `editor_learn.c` (2 definitions) | Deferred: bounded map replies/writes and save-result handling need editor service qualification. |
| `midi_learn.c` (15 definitions) | Deferred: mapping writes explicitly mask interrupts; evaluate loops, save and critical-section cost separately. |
| `fm6_vbank.c` (12 default definitions) | Deferred: mutable `fm6_bank_read` registration, packed-voice reads and staged NOR erase/program/CRC need separate callback/flash/service audit. |

All seven files had no ISR-reachable definition in the unchanged default IR;
that alone does not establish service or callback safety. The narrower selection
avoids changing mutation/flash/critical-section policy. Existing positive/negative
IR fixtures and the real JieLi smoke apply unchanged: no new annotation behavior
or relaxed protection requires another synthetic fixture.

## Remaining qualification

Sixteen existing IR fixtures and the fresh real JieLi annotation/compile smoke
passed. Default baseline, no-size control and five-helper candidate all passed
target build guards; baseline and candidate passed unchanged target budgets.
No full integrated suite, additional target profile/CPU2 variants, browser run or
hardware test was spent on the discarded policy. Those checks would be required
for a retained runtime candidate; this report does not complete the issue.
Host PCM/future-state regressions, pixel fixtures and resource reports are distinct from executing minsize-generated code on the FM-1. Host
instruction counts use the host compiler rather than this target IR pass and
cannot measure its service overhead.

This measurement-only report changes no firmware and needs no hardware test. For
any future runtime candidate, hardware remains a hard merge gate. Compare the exact baseline and final candidate
packages, equal projects/settings/notes/durations, HELP ON/OFF with repeated page
changes and dense redraws, category browsing and the same USB/editor/MIDI traffic.
Include held/released/mixed-engine/FX loads, USB audio 44.1/48 kHz, continuous panel
edits, CPU2 runtime OFF/ON and failure fallback, standard/sparse catalogs and MACRO
where selected. Record render maxima and interval late/shedding/scan/stream error
deltas alongside listening/panel response. No automatic flash is authorized by
this guide. See [performance](performance.md) and the PR's actionable test steps.

## Standalone reproduction appendix

Use a separate clean recursive checkout at the exact measured base above and a
shell with no `FELUCCA_*` overrides. Install BUILDING.md's prerequisites, then run
`uv run --locked --group build ./build.sh` with the reference SDK/toolchain paths.
That fresh full build supplies the frozen generated assets and build identity.
Save the following script as `build/issue521/reproduce.py`. It changes no tracked
source: candidate annotations are applied only to its private generated LLVM IR.
Run these commands sequentially, without regenerating assets between modes:

```sh
JIELI_TOOLCHAIN=/path/to/toolchain uv run --locked --group build python3 build/issue521/reproduce.py default
JIELI_TOOLCHAIN=/path/to/toolchain uv run --locked --group build python3 build/issue521/reproduce.py no-size
JIELI_TOOLCHAIN=/path/to/toolchain uv run --locked --group build python3 build/issue521/reproduce.py candidate
```

The original appendix was executed sequentially in a clean checkout at the
measured base, using the archived fresh full-baseline generated inputs: all three
modes passed their target guards and reproduced the table. Each app was
byte-identical to its original measured counterpart. No tracked source changed.
The later argument and recorded-output/IR gates were checked with those retained
artifacts and injected mismatches in normal and optimized Python, without a new
target build.

Validation gates use explicit failures, including under `python3 -O` or
`PYTHONOPTIMIZE`. The JSON outputs and artifacts go to separate
`build/issue521/reproduce-*`
directories. Before writing a successful summary, the script requires the exact
recorded app size/hash, complete resource/stack dictionaries and (for selective
modes) unoptimized/annotated IR hashes. It also recomputes the baseline annotation
and requires exactly the five selected additional `minsize` headers, with no
other IR changes. The no-size control compiles directly and has no LLVM IR
artifacts to compare. These expectations were checked against the retained
original artifacts and their clean reproduction; they are not new measurements.
A mismatch is a failed reproduction to investigate, not permission to update the
constants. Inspect `preset_cat` and `ui_draw_page` in each
`felucca.dis` for the extra calls described above. These raw control binaries are
not installable qualification packages.

```python
#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""After a clean full target build at5b613a, compile one policy with unchanged assets.
JIELI_TOOLCHAIN must be set. Run sequentially; no tracked sources are modified.
"""
import sys,os,json,hashlib
from pathlib import Path
def require(condition, message="validation failed"):
 if not condition:
  raise RuntimeError(message)
if len(sys.argv)!=2:raise SystemExit("usage: reproduce.py default | no-size | candidate")
mode=sys.argv[1]
if mode not in ("default","no-size","candidate"):raise SystemExit("default | no-size | candidate")
root=Path.cwd();sys.path.insert(0,str(root/"tools"))
import build as B
import size_fns as S
import build_report as R
if mode=="no-size":os.environ["FELUCCA_SIZE"]="0"
else:os.environ.pop("FELUCCA_SIZE",None)
B.OUT=root/"build"/"issue521"/("reproduce-"+mode);B.OUT.mkdir(parents=True,exist_ok=True)
original=B.tc
selected={"help_page","help_parse","help_row","cat_of_engine","preset_cat"}
# Literal expectations from the retained original comparison and its clean reproduction.
expected_app={
 "default":(491876,"4af1d9e5505aff2fd722c7a8defe8d8cd8ec5c2355341d1840e6d8e4d1f422de"),
 "no-size":(510680,"734134a23507fb2930652a6904884fb6b7a0b85a9ef2f1944cdccfa6a1e61df4"),
 "candidate":(491812,"b5a45f9549ac7ea1cc40be05e96f4c381a13b25bf35249ccc75849c1b08a3445")}
app_bytes,app_hash=expected_app[mode]
expected_resources={}
for name,origin,capacity,used,floor,authority in (
 ("app",33554720,581564,app_bytes,0,"tools/build.py APP_SLOT"),
 ("RAM",29392896,73728,62136 if mode=="no-size" else 62152,4096,"tools/build.py check"),
 ("POOL",29466624,368640,336440,8192,"tools/build.py check"),
 ("NOINIT",29868032,15696,15576,100,"tools/build.py check"),
 ("RAMTEXT",29360128,24576,3152,0,"firmware/app.ld linker region")):
 expected_resources[name]=dict(origin=origin,capacity_bytes=capacity,used_bytes=used,
  spare_bytes=capacity-used,enforced_spare_min_bytes=floor,margin_bytes=capacity-used-floor,authority=authority)
expected_resources["RAMTEXT"]["sections"]={".ram_text":2924,".c1_text":228}
expected_stacks={}
for name,origin,reserved in (
 ("main_user",29835520,24320),("main_supervisor",29860096,7936),
 ("main_user_guard",29835264,256),("main_supervisor_guard",29859840,256),
 ("worker_user_including_guard",29393408,4096),("worker_supervisor",29397504,256)):
 expected_stacks[name]=dict(origin=origin,end=origin+reserved,reserved_bytes=reserved)
for name in ("worker_user_including_guard","worker_supervisor"):
 expected_stacks[name]["accounted_in"]="RAM"
expected_ir={"default":"bfcd2a0c7a1ce0a8f85ae33a020bebece3f28ca39a09e1ef401892b27446fa30",
 "candidate":"0bc6cf5c3598677e591d74fa98e0ff8fe4074410a76226a6ffb66e4f6496077f"}
def check_ir():
 raw=(B.OUT/"felucca.ll").read_bytes()
 require(hashlib.sha256(raw).hexdigest()=="bb088879151ac90f70b245111a41226d56e07535a0422aca1228b9f1f77cd7d6", "unoptimized IR differs from recorded input")
 baseline,_,protected=S.annotate(raw.decode(),S.size_names())
 require(not selected&protected, "selected helpers are protected")
 candidate,hit,_=S.annotate(baseline,selected)
 require(hit==selected, "selected helper definitions are missing")
 def headers(text):return {m[2].strip('"'):m[0] for m in S.IR_DEF.finditer(text)}
 before,after=headers(baseline),headers(candidate)
 require(before.keys()==after.keys() and {n for n in before if before[n]!=after[n]}==selected, "expected exactly five additional minsize headers")
 actual=(B.OUT/"felucca_size.ll").read_bytes()
 require(actual.decode()==(candidate if mode=="candidate" else baseline), "unexpected annotated IR delta")
 require(hashlib.sha256(actual).hexdigest()==expected_ir[mode], "annotated IR differs from recorded result")
def tc(*args):
    ir=B.OUT/"felucca_size.ll"
    if mode=="candidate" and args[0]=="cc" and ir in args:
        text=ir.read_text();out,hit,protected=S.annotate(text,S.size_names()|selected)
        require(not selected&protected, "candidate annotates protected functions")
        require(selected<=hit, "candidate annotations were not applied")
        ir.write_text(out)
    return original(*args)
B.tc=tc
img,hdr,syms,dis,rt=B.build_app()
errors,notes=B.check(img,hdr,syms,dis,rt)
require(not errors, errors)
resources,stacks=R.resources(B,(img,hdr,syms,dis,rt))
require(len(img)==app_bytes, "app size differs from recorded result")
require(hashlib.sha256(img).hexdigest()==app_hash, "app hash differs from recorded result")
require(resources==expected_resources, "resources differ from recorded result")
require(stacks==expected_stacks, "stack reservations differ from recorded result")
if mode!="no-size":check_ir()
(B.OUT/"symbols.txt").write_text(syms)
(B.OUT/"sections.txt").write_text(hdr)
(B.OUT/"summary.json").write_text(json.dumps({"mode":mode,"resources":resources,"stack_reservations":stacks,"checks":notes,"app_sha256":hashlib.sha256(img).hexdigest()},indent=2)+"\n")
print(json.dumps({"mode":mode,"app_bytes":len(img),"checks":notes},indent=2))
```
