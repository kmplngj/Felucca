#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Source check of the project codec's header boundary (#300, docs/modules.md's pattern for #454).

- Outside project_codec.c and project_legacy.c, no firmware file names a function the codec defines but
  project_codec.h does not declare (the readers, proj_bound, proj_import, the retired-sound passes, ...): every caller
  decodes through proj_decode and stores through proj_encode, none combines the steps by hand.
- project_codec.c names nothing project_legacy.c defines except the one hook, proj_decode_legacy, called once, and
  includes project_legacy.c once: #456 stage 2b deletes that file, the include and the call.
- The codec's host tests (tests/project_test.c, tests/fuzz_proj.c) include neither ui.c, panel.c, gfx.c nor
  menu_items.c, directly or through the files they include.

Self-test: mutations of the real sources (a caller bounding by hand, a caller using a reader, the codec reaching
into the legacy file, a second hook call, a UI include in a codec test) must each be rejected.
  python3 tests/project_codec_boundary_test.py"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "firmware" / "src"
CODEC, LEGACY, HEADER = "project_codec.c", "project_legacy.c", "project_codec.h"
CODEC_TESTS = ("project_test.c", "fuzz_proj.c")
UI_FILES = {"ui.c", "panel.c", "gfx.c", "menu_items.c"}
DEF = re.compile(r"^(?:static\s+|PROJ_API\s+)?(?:__attribute__\(\([^)]*\)\)\s+)?(?:const\s+)?[A-Za-z_]\w*[\s*]+"
                 r"([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:/\*.*?\*/\s*)?\{", re.M | re.S)
DECL = re.compile(r"^PROJ_API\s+[^;(]*?\b([A-Za-z_]\w*)\s*\(", re.M)
INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.M)


def strip(text):
    """the code without comments and string literals"""
    text = re.sub(r"/\*.*?\*/|//[^\n]*", " ", text, flags=re.S)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


def defined(text):
    return {m.group(1) for m in DEF.finditer(strip(text))} - {"if", "for", "while", "switch", "return", "sizeof"}


def uses(text, name):
    return len(re.findall(r"\b%s\b" % re.escape(name), strip(text)))


def check(files, tests):
    """files: name -> text of firmware/src; tests: name -> text of tests/. A list of violations"""
    bad = []
    public = set(DECL.findall(strip(files[HEADER])))
    legacy = defined(files[LEGACY])
    private = (defined(files[CODEC]) | legacy) - public
    if "proj_decode_legacy" not in public or "proj_decode_legacy" not in legacy:
        bad.append("the hook proj_decode_legacy must be declared in project_codec.h and defined in project_legacy.c")
    for name, text in files.items():
        if name in (CODEC, LEGACY, HEADER) or not name.endswith((".c", ".h")):
            continue
        for f in sorted(private):
            if uses(text, f):
                bad.append(f"{name} names the codec's private {f}: use proj_decode / proj_encode (project_codec.h)")
    codec = files[CODEC]
    for f in sorted(legacy - {"proj_decode_legacy"}):
        if uses(codec, f):
            bad.append(f"{CODEC} names {f} of the legacy seam: only proj_decode_legacy crosses it")
    if uses(codec, "proj_decode_legacy") != 1:
        bad.append(f"{CODEC} must call the legacy hook exactly once")
    if INCLUDE.findall(strip_keep_includes(codec)).count(LEGACY) != 1:
        bad.append(f"{CODEC} must include {LEGACY} exactly once")
    for t in CODEC_TESTS:
        reached = closure(t, files, tests)
        for f in sorted(UI_FILES & reached):
            bad.append(f"tests/{t} includes {f}: the codec tests build without the UI")
    return bad


def strip_keep_includes(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", " ", text, flags=re.S)


def closure(test, files, tests):
    """the base names of every file test includes, transitively (quoted includes: "../firmware/src/x.c" from the
    firmware, a bare name from tests/ first)"""
    seen, todo = set(), [tests[test]]
    while todo:
        for inc in INCLUDE.findall(strip_keep_includes(todo.pop())):
            base = Path(inc).name
            if base in seen:
                continue
            seen.add(base)
            text = files.get(base) if "firmware/src" in inc or "/" in inc else tests.get(base, files.get(base))
            if text is not None:
                todo.append(text)
    return seen


def load():
    files = {p.name: p.read_text() for p in SRC.iterdir() if p.suffix in (".c", ".h")}
    gen = ROOT / "build" / "gen" / "engine_includes.inc"
    if gen.exists():
        files[gen.name] = gen.read_text()
    tests = {p.name: p.read_text() for p in (ROOT / "tests").iterdir() if p.suffix in (".c", ".h")}
    return files, tests


def main():
    files, tests = load()
    bad = check(files, tests)
    for b in bad:
        print("FAIL", b)
    mutations = [
        ("project.c bounds by hand", "project.c", "static int project_used(uint32_t slot) {",
         "static void mut1(project_t *q) { proj_bound(q); }\nstatic int project_used(uint32_t slot) {"),
        ("editor_backup.c uses a reader", "editor_backup.c", "static uint32_t ed_bk_commit(void)\n{",
         "static uint32_t ed_bk_commit(void)\n{\n    (void)proj_import;"),
        ("the codec reaches into the seam", CODEC, None, None),
        ("a second hook call", CODEC, "#include \"project_legacy.c\"",
         "static int mut2(project_t *q) { return proj_decode_legacy(q, 0, 0); }\n#include \"project_legacy.c\""),
        ("a codec test includes the UI", "tests:fuzz_proj.c", "#include \"old_pack.h\"",
         "#include \"old_pack.h\"\n#include \"../firmware/src/gfx.c\""),
    ]
    rejected = 0
    for what, where, old, new in mutations:
        f2, t2 = dict(files), dict(tests)
        if where == CODEC and new is None:            # the codec calls a legacy reader directly
            name, text = CODEC, files[CODEC]
            text = text.replace("int proj_decode(project_t *q, const void *b, int n)\n{",
                                "int proj_decode(project_t *q, const void *b, int n)\n{\n    (void)proj_import_old;", 1)
            f2[name] = text
        elif where.startswith("tests:"):
            name = where[6:]
            assert old in t2[name], (what, old)
            t2[name] = t2[name].replace(old, new, 1)
        else:
            assert old in f2[where], (what, old)
            f2[where] = f2[where].replace(old, new, 1)
        got = check(f2, t2)
        if len(got) > len(bad):
            rejected += 1
        else:
            print("FAIL the check does not reject:", what)
    ok = not bad and rejected == len(mutations)
    print(f"project codec boundary: {len(bad)} violations, {rejected}/{len(mutations)} mutations rejected: "
          f"{'ok' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
