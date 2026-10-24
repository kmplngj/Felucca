<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Disabled engine-arena checker: release-target proof (#139)

On 2026-10-23, fresh matched JieLi release builds at
`5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e` produced **byte-identical complete
ELFs and app images** with the default-off owner-check accessors present versus
removed. This closes the target-footprint evidence gap in
[#139](https://github.com/kmplngj/Felucca/issues/139), supplementing the host
checks introduced by [PR #255](https://github.com/kmplngj/Felucca/pull/255).
No runtime source, build policy, defaults or firmware dependency pins change here.

## Method and boundary

The baseline is a clean recursive checkout of that exact firmware revision with
MIT Engines `9630426f5c4a34a209ca851356fbe8ba3c4c6d19`. It uses the ordinary
selective-minsize pass, JieLi Clang 4.0.1 (compiler SHA-256
`c45189ee624de0430deb0db02e6dce171fb5538e7fe323e3964dc8ac6236240f`),
and SDK `AC79NN_SDK_V1.2.1_2023-12-13`. The SDK inputs have SHA-256 values:

| Input | SHA-256 |
| --- | --- |
| `cfg/eq_cfg_hw.bin` | `41167491bffed4651750719c973d2758adeb9021a5670d02d6a53c85ed80ea7d` |
| `cfg_tool.bin` | `276579954f076886a6a7694f65dc71c034a63a2c204b76749065c0ac7b010d1b` |
| `uboot.boot` | `4e3b4c220dc96641cb5a723f41e68ce41d5261ae9434bb33fbd7f2c59976ded4` |

A separate ignored source archive removes the checker definition, failure handler,
scratch, accessor and wrappers. Its six consumers expand directly to `ENG_MEM`
with the **same expressions and guards**: GRAIN retains `gr_part(t)`, SLICE
retains `p`, MACRO retains its unsigned part conversion, and PHYS/DRUM/FM6 retain
`t - trk`. Independent GRAIN/SLICE IDs remain. Exactly eight C/header files differ;
no allocator, ownership transition, clearing size, engine ID or persistent data changes.
The appendix constructs the full control diff from the pinned source.

Each control reuses its baseline's generated inputs and release identity and
checks actual build configuration (flags, effective defines, selective pass,
product/version and compiler/toolchain/SDK fingerprints). The only allowed difference
is the control's intentional removal of the unused `FELUCCA_ARENA_CHECK=0` default
definition; its absence is asserted, not replaced in the recorded configuration.
Both compile at the same relative
`build/` path inside the compiler mount. This matters: an earlier control used
`build/control-standard/`, adding 34 bytes of file-name strings to ELF metadata
while leaving its app image unchanged. The final comparison uses no path
normalization or section exclusions. A second link with the real linker's
`-Map` option is required to reproduce the original complete ELF before its map
is accepted. Generated files also match byte for byte.

## Results

Each pair passed the build's app/RAM/pool/NOINIT margins, HAL register boundary,
RAM-only flash-code check and worker-call check. All six artifacts match literally:
`felucca.bin`, `felucca.elf`, raw `felucca.dis`, section table, symbol table and real
`link.map`. The full resource dictionaries and stack reservation dictionaries match.
No `eng_mem_of`, `eng_arena_trap`, `eng_arena_fail` or `eng_arena_scratch` symbol
exists in either linked result.

| Release configuration | Product | App bytes | RAM | Pool | NOINIT | RAM text | A/B delta |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| standard, CPU2 compiled | FM-1_916 | 491,856 | 62,152 | 336,440 | 15,576 | 3,152 | 0 B |
| standard, `FELUCCA_CPU2=0` | FM-1_916 | 488,136 | 55,556 | 336,440 | 15,564 | 2,924 | 0 B |
| MACRO, CPU2 compiled | FM-1_900 | 576,080 | 62,152 | 354,200 | 15,576 | 3,152 | 0 B |

All use explicit release version `1.6.1` (`v1.6.1` in the binary). The standard
product is `FM-1_916`; MACRO uses the required distinct product `FM-1_900`.
CPU2 compiled does not mean its runtime beta is enabled. Main user/supervisor
stacks reserve 24,320/7,936 B with a 256 B guard each. CPU2-compiled variants also
reserve 4,096 B for worker user stack including its guard and 256 B worker
supervisor stack, accounted in RAM. These reservations are unchanged, not measured
stack high-water values.

| Configuration | App SHA-256 | Complete ELF SHA-256 |
| --- | --- | --- |
| standard | `31d6d566b03514687fe8baed2507fc8d4dc61d222bab3520b9f6056dc0cf0d3a` | `f09313050ce9abe7acffd1ed0085048668003b335e1939ee0e72417d365761de` |
| cpu2off | `b1dc153a9e5936290bef9f5904a8d91fa89b6bab2322b183d7cadac6c4b56702` | `173a7582ae8dd0d6fe07bd9fd624dc68f351f433a2b9486dfd36f8aee8e98bd9` |
| macro | `deb18562af087355d18a8e93e199d86e7de0571dd20f65b73ccb7e780541a1d7` | `6e273e57885195c6d9d18af9a20df602da3e9a827ad769eded2ec337e60c7b8e` |

Unoptimized IR is not claimed byte-identical: removing the wrappers changes LLVM
source-location metadata. Identical complete linked machine code and symbols
establish the disabled target footprint directly. This is a configuration-specific
result for the pinned source/toolchain, not a promise about future compilers,
profiles or enabling `FELUCCA_ARENA_CHECK` on a target.

[CI run 40000737789](https://github.com/kmplngj/Felucca/actions/runs/40000737789)
at the same source revision passed the existing enabled host checker coverage:
720 ordinary/checked union transitions, 48 fixed-seed random cases, 12 sanitizer
random cases and the checked union under ASan/UBSan, plus the integrated suite.
Those are separate host results; the local release pairs above supply the missing
actual-target static proof. No new host checker, full host-suite rerun, emulator
or real-device run was needed for this documentation-only supplement. No hardware
qualification, runtime speedup, live stack measurement, global memory-safety proof
or flash/install operation is claimed.

## Reproduce

Use the [build prerequisites](../BUILDING.md), including the documented SDK and
toolchain overrides and Docker on macOS ARM. Allocate a separate clean recursive
checkout at the exact source revision, not the documentation commit:

```sh
git worktree add --detach ../felucca-139-repro 5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e
cd ../felucca-139-repro
git submodule update --init --recursive
mkdir -p build/issue139
```

Save the four Python appendices below under their indicated `build/issue139/`
filenames. They use only Python's standard library and the pinned repository's
build modules. Keep this checkout tracked-clean. Configure `AC79_SDK` and
`JIELI_TOOLCHAIN` as appropriate for your installation; do not copy machine-specific
paths from another checkout. The commands below clear inherited CPU2/size settings
and select each profile explicitly. Other `FELUCCA_*` overrides must be unset.
Capture checks verify the variant and require the current configuration to match
the captured build. Run sequentially from
the checkout root:

```sh
python3 build/issue139/prepare-control.py
env -u FELUCCA_CPU2 -u FELUCCA_SIZE FELUCCA_PROFILE=standard uv run --locked --group build ./build.sh --release 1.6.1
env -u FELUCCA_CPU2 -u FELUCCA_SIZE FELUCCA_PROFILE=standard python3 build/issue139/capture-baseline.py standard
```

For each archived baseline, copy its generated inputs into the control and run
these commands (initially `variant=standard`):

```sh
variant=standard
python3 - "$variant" <<'PYGEN'
import shutil, sys
from pathlib import Path
p = Path('build/issue139')
dest = p / 'control-source/build'
shutil.rmtree(dest / 'gen', ignore_errors=True)
shutil.copytree(p / sys.argv[1] / 'baseline/gen', dest / 'gen')
shutil.copy2(p / 'capture-control.py', dest / 'capture-control.py')
PYGEN
(cd build/issue139/control-source && env -u FELUCCA_CPU2 -u FELUCCA_SIZE python3 build/capture-control.py "../$variant/baseline" "$variant")
python3 build/issue139/compare.py "$variant"
```

Then build/archive the second baseline and repeat that control block with
`variant=cpu2off`:

```sh
env -u FELUCCA_SIZE FELUCCA_PROFILE=standard FELUCCA_CPU2=0 uv run --locked --group build ./build.sh --release 1.6.1
env -u FELUCCA_SIZE FELUCCA_PROFILE=standard FELUCCA_CPU2=0 python3 build/issue139/capture-baseline.py cpu2off
```

Finally build/archive MACRO and repeat the control block with `variant=macro`:

```sh
env -u FELUCCA_CPU2 -u FELUCCA_SIZE FELUCCA_PROFILE=macro uv run --locked --group build ./build.sh --release 1.6.1 --product FM-1_900
env -u FELUCCA_CPU2 -u FELUCCA_SIZE FELUCCA_PROFILE=macro python3 build/issue139/capture-baseline.py macro
```

The host font generator emitted the existing Pillow warning that Raqm was unavailable
and used basic layout in each baseline; the matching control reused those exact
generated fonts. There were no compiler warnings or build-check failures.

The original capture/relink/control/compare steps were executed for these three
variants. The later configuration checks were verified by preprocessing the exact
pinned baseline/control inputs, without rebuilding. The historical control summary
copied the baseline configuration; corrected metadata-only copies now record the
actual control configuration, which omits only the removed checker default. All
18 literal artifact pairs, generated inputs, resources and stack reservations were
rechecked with the stricter comparison. No target size/result above changed. `compare.py` prints literal equality and writes a per-variant
`comparison.json`; a byte difference or resource/stack change fails. Archived
controls can be rechecked without recompiling using
`python3 build/issue139/compare.py standard build/issue139/standard/control`
(and the corresponding other two labels). The documented source/control scripts
are included here, so reproduction does not depend on the author's ignored logs.
Retain the generated control diff and all baseline/control artifacts for review.
Preparation and fresh captures refuse existing destination directories, including
empty ones or symlinks; choose a fresh ignored `build/issue139` location in a new
checkout for another build run. Archive-only rechecks read existing pairs and
rewrite only their `comparison.json`; they do not rebuild or alter input artifacts.
Do not install or flash control outputs: they reuse the baseline identity solely
for a matched build comparison.

## Reproduction scripts

Validation gates raise explicit errors and remain active with `python3 -O` or
`PYTHONOPTIMIZE`; a failed gate cannot write a new successful comparison.

### `build/issue139/prepare-control.py`

```python
#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
import subprocess,tarfile,io,json
from pathlib import Path
def require(condition, message="validation failed"):
 if not condition:
  raise RuntimeError(message)
root=Path.cwd();out=root/"build/issue139";control=out/"control-source"
require(not (root/"build").is_symlink() and not out.is_symlink(), "use a confined ignored build directory")
require(subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()=="5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e", "wrong baseline revision")
require(not subprocess.check_output(["git","status","--porcelain"]), "baseline checkout is dirty")
require(not control.exists() and not control.is_symlink(), "control-source already exists; use a fresh checkout")
control.mkdir(parents=True)
for source,dest in((root,control),(root/"firmware/engines",control/"firmware/engines")):
 dest.mkdir(parents=True,exist_ok=True)
 blob=subprocess.check_output(["git","archive","--format=tar","HEAD"],cwd=source)
 with tarfile.open(fileobj=io.BytesIO(blob))as archive:archive.extractall(dest,filter="data")
changed=[]
def replace(file,old,new):
 p=control/file;s=p.read_text();require(old in s, (file,old));p.write_text(s.replace(old,new));changed.append(file)
replace("firmware/src/core.h",'#ifndef FELUCCA_ARENA_CHECK\n#define FELUCCA_ARENA_CHECK 0    /* 1: host tests check engine-arena owners (engines.c ENG_MEM_OF); never on the target */\n#endif\n',"")
p=control/"firmware/src/engines.c";s=p.read_text();start=s.index("/* Host/test-only owner check");end=s.index("/* Engine-local control code",start)
p.write_text(s[:start]+"#define ENGI_GRAIN 8u\n#define ENGI_SLICE 13u\n\n"+s[end:]);changed.append("firmware/src/engines.c")
for file,old,new in(
 ("eng_grain.c","ENG_MEM_OF(t, ENGI_GRAIN, gr_part(t))","ENG_MEM(gr_part(t))"),
 ("eng_phys.c","ENG_MEM_OF(t, ENGI_PHYS, t - trk)","ENG_MEM(t - trk)"),
 ("eng_drum.c","ENG_MEM_OF(t, ENGI_DRUM, t - trk)","ENG_MEM(t - trk)"),
 ("eng_fm6.c","ENG_MEM_OF(t, ENGI_FM6, t - trk)","ENG_MEM(t - trk)"),
 ("eng_slice.c","ENG_MEM_OF(t, ENGI_SLICE, p)","ENG_MEM(p)"),
 ("eng_macro.c","ENG_MEM_OF(t, ENGI_MACRO, (uint32_t)(t - trk))","ENG_MEM((uint32_t)(t - trk))")):
 replace("firmware/src/"+file,old,new)
(out/"control-files.json").write_text(json.dumps(changed,indent=2)+"\n")
with(out/"control-source.diff").open("w")as f:
 for file in changed:
  r=subprocess.run(["diff","-u","--label","a/"+file,"--label","b/"+file,str(root/file),str(control/file)],stdout=f)
  require(r.returncode==1, "control file did not differ as expected")
print("prepared8exactcontrolfiles; no tracked source changes")
```

### `build/issue139/capture-baseline.py`

```python
#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
import sys,json,shutil,hashlib,subprocess
from pathlib import Path
def require(condition, message="validation failed"):
 if not condition:
  raise RuntimeError(message)
sys.path.insert(0,"tools");import build as B;import build_report as R
label=sys.argv[1]
profile,cpu2,product={"standard":("standard",True,"FM-1_916"),"cpu2off":("standard",False,"FM-1_916"),"macro":("macro",True,"FM-1_900")}[label]
out=B.SRC/"build/issue139"/label/"baseline"
require(not any(p.is_symlink() for p in (B.OUT,B.SRC/"build/issue139",out.parent)), "use confined build directories")
r=json.loads((B.OUT/"resource-report.json").read_text())
require(r["build_identity"]["revision"]=="5b613a595d6d6a9a218278c5ae38f00cfa8e9c6e", "wrong captured baseline revision")
require(not r["build_identity"]["dirty"], "captured baseline is dirty")
cfg=r["configuration"];defines=cfg["effective_defines"]
require(cfg["cpu2"] is cpu2 and cfg["selective_minsize"] is True, "CPU2/size variant mismatch")
require(B.CPU2 is cpu2 and B.os.environ.get("FELUCCA_SIZE")!="0", "inherited CPU2/size override")
require(cfg["product"]==product and cfg["version_override"]=="v1.6.1", "release identity mismatch")
require(defines["FELUCCA_PROFILE_NAME"]==json.dumps(profile) and defines["FELUCCA_CPU2"]==str(int(cpu2)), "effective variant mismatch")
expected_flags=["-target","pi32v2",*B.CFLAGS,"-Ifirmware/hal","-Ifirmware/src","-Ibuild/gen"]
if not cpu2:expected_flags.append("-DFELUCCA_CPU2=0")
expected_flags += [f'-DFELUCCA_ID="{product}"','-DFELUCCA_VERSION="v1.6.1"']
require(cfg["compile_flags"]==expected_flags, "unexpected compiler overrides")
B.PRODUCT=product;B.VERSION="v1.6.1"
require(R.configuration(B)==cfg, "current environment/toolchain differs from captured build")
out.mkdir(parents=True)  # refuse reuse, including empty directories and symlinks
for name in ("felucca.bin","felucca.elf","felucca.dis","felucca.dis.profile.json","felucca.ll","felucca_size.ll","resource-report.json","build-identity.json"):
 shutil.copy2(B.OUT/name,out/name)
shutil.copytree(B.GEN,out/"gen",dirs_exist_ok=True)
objects=[B.OUT/x for x in ("crt0.o","fm1_vec.o","fm1_isr.o")]+([B.OUT/"fm1_cpu1.o"]if B.CPU2 else[])+[B.OUT/"felucca.o"]
B.tc("pi32v2/bin/ld","-T",B.FW/"app.ld",*objects,"-Map",B.OUT/"link.map","-o",B.OUT/"map.elf")
require((B.OUT/"map.elf").read_bytes()==(out/"felucca.elf").read_bytes(), '(B.OUT/"map.elf").read_bytes()==(out/"felucca.elf").read_bytes()')
shutil.copy2(B.OUT/"map.elf",out/"map.elf");shutil.copy2(B.OUT/"link.map",out/"link.map")
for name,args in (("sections.txt",("-h",)),("symbols.txt",("-t",))):
 (out/name).write_text(B.tc("common/bin/objdump",*args,B.OUT/"felucca.elf"))
require(not any(x in(out/"symbols.txt").read_text()for x in("eng_mem_of","eng_arena_trap","eng_arena_fail","eng_arena_scratch")), 'not any(x in(out/"symbols.txt").read_text()for x in("eng_mem_of","eng_arena_trap","eng_arena_fail","eng_arena_scratch"))')
print(label,len((out/"felucca.bin").read_bytes()),"baseline archived; real linker map reproduces exactELF")
```

### `build/issue139/capture-control.py`

```python
#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
import sys,json,os,hashlib
from pathlib import Path
def require(condition, message="validation failed"):
 if not condition:
  raise RuntimeError(message)
baseline=Path(sys.argv[1]).resolve();label=sys.argv[2]
r=json.loads((baseline/"resource-report.json").read_text());cfg=r["configuration"]
os.environ["FELUCCA_CPU2"]="1"if cfg["cpu2"]else"0"
# Preserve explicit compiler flags: the default baseline omits an explicit CPU2 define.
if not any(x.startswith("-DFELUCCA_CPU2=")for x in cfg["compile_flags"]):os.environ.pop("FELUCCA_CPU2",None)
sys.path.insert(0,"tools");import build as B;import build_report as R
B.OUT=B.SRC/"build";B.OUT.mkdir(parents=True,exist_ok=True)
B.PRODUCT=cfg["product"];B.VERSION=cfg["version_override"]
actual_cfg=R.configuration(B)
expected_cfg=json.loads(json.dumps(cfg))
require(expected_cfg["effective_defines"].pop("FELUCCA_ARENA_CHECK")=="0", "baseline checker must be disabled")
require(actual_cfg==expected_cfg, "control differs beyond the removed checker default")
img,hdr,syms,dis,rt=B.build_app();errors,notes=B.check(img,hdr,syms,dis,rt);require(not errors, errors)
resources,stacks=R.resources(B,(img,hdr,syms,dis,rt))
require(not any(x in syms for x in("eng_mem_of","eng_arena_trap","eng_arena_fail","eng_arena_scratch")), 'not any(x in syms for x in("eng_mem_of","eng_arena_trap","eng_arena_fail","eng_arena_scratch"))')
objects=[B.OUT/x for x in("crt0.o","fm1_vec.o","fm1_isr.o")]+([B.OUT/"fm1_cpu1.o"]if B.CPU2 else[])+[B.OUT/"felucca.o"]
B.tc("pi32v2/bin/ld","-T",B.FW/"app.ld",*objects,"-Map",B.OUT/"link.map","-o",B.OUT/"map.elf")
require((B.OUT/"map.elf").read_bytes()==(B.OUT/"felucca.elf").read_bytes(), '(B.OUT/"map.elf").read_bytes()==(B.OUT/"felucca.elf").read_bytes()')
(B.OUT/"sections.txt").write_text(hdr);(B.OUT/"symbols.txt").write_text(syms)
(B.OUT/"summary.json").write_text(json.dumps({"configuration":actual_cfg,"resources":resources,"stack_reservations":stacks,"checks":notes},indent=2)+"\n")
print(label,len(img),"control built; hooks absent; release flags identical")
```

### `build/issue139/compare.py`

```python
#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
import sys,json,hashlib,shutil
from pathlib import Path
def require(condition, message="validation failed"):
 if not condition:
  raise RuntimeError(message)
p=Path("build/issue139");label=sys.argv[1];a=p/label/"baseline";b=Path(sys.argv[2]) if len(sys.argv)>2 else p/"control-source/build";archive=p/label/"control"
require(not any(d.is_symlink() for d in (p.parent,p,p/label,archive)), "use confined archive directories")
def hashes(directory):
 return {str(f.relative_to(directory)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(directory.rglob("*")) if f.is_file()}
require(hashes(a/"gen")==hashes(b/"gen"), "generated inputs")
out={}
for n in("felucca.bin","felucca.elf","felucca.dis","sections.txt","symbols.txt","link.map"):
 x=(a/n).read_bytes();y=(b/n).read_bytes();require(x==y, n)
 out[n]={"identical":True,"bytes":len(x),"sha256":hashlib.sha256(x).hexdigest()}
r=json.loads((a/"resource-report.json").read_text());c=json.loads((b/"summary.json").read_text())
expected_cfg=json.loads(json.dumps(r["configuration"]))
require(expected_cfg["effective_defines"].pop("FELUCCA_ARENA_CHECK")=="0", "baseline checker must be disabled")
require(expected_cfg==c["configuration"], "configuration differs beyond the removed checker default")
require(r["resources"]==c["resources"], "resource mismatch")
require(r["stack_reservations"]==c["stack_reservations"], "stack reservation mismatch")
hook_names={"eng_mem_of","eng_arena_trap","eng_arena_fail","eng_arena_scratch"}
def symbols(directory):
 return {line.split()[-1] for line in (directory/"symbols.txt").read_text().splitlines() if line.split()}
hooks_absent=all(not hook_names & symbols(directory) for directory in (a,b))
require(hooks_absent, "checker hook symbols present")
if b.resolve()!=archive.resolve():
 archive.mkdir(parents=True)  # refuse an existing archive instead of overlaying it
 for n in("felucca.bin","felucca.elf","felucca.dis","felucca.dis.profile.json","felucca.ll","felucca_size.ll","sections.txt","symbols.txt","link.map","map.elf","summary.json"):
  shutil.copy2(b/n,archive/n)
 shutil.copytree(b/"gen",archive/"gen",dirs_exist_ok=True)
out.update(resources=r["resources"],stack_reservations=r["stack_reservations"],configuration=r["configuration"],control_configuration=c["configuration"],hooks_absent=hooks_absent)
(p/label/"comparison.json").write_text(json.dumps(out,indent=2)+"\n")
print(label,"literal app/ELF/disassembly/map/section/symbol/resource/stack equality")
```
