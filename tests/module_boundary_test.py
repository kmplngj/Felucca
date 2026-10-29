#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Module boundary check (#454, docs/modules.md): the modules are header boundaries inside felucca.c's one translation
unit, enforced here at the source level (no separate object; compare integrated target output as documented).

sound.c may reference, of the firmware's functions and objects, only what sound.h and sound_port.h declare. Types,
constants and macros of core.h are its vocabulary; but a function or static object defined by any other file (a
module's state such as trk / song / panic_req, a helper such as eng_of / fm6_set_patch / swing_step_len), and a macro
that expands to one (TSEL, TP), is another file's: it must go through sound_port.h. It may include only the headers
listed below. Fixtures: mutations of sound.c that must be rejected.

    python3 tests/module_boundary_test.py            run the check on firmware/src/sound.c and the fixtures
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "firmware" / "src"
MODULES = {"sound": {"interface": ("sound.h", "sound_port.h"), "headers": {"sound.h", "sound_port.h", "core.h",
                                                                          "felucca_tables.h", "stdint.h", "string.h"}}}
# not other files' state: C keywords/types and the libc names a module may call
OK = set("""if else for while do switch case default break continue return goto sizeof static const volatile inline
void char short int long unsigned signed float double struct union enum typedef extern defined register
uint8_t int8_t uint16_t int16_t uint32_t int32_t uint64_t int64_t size_t memcpy memset memcmp memmove NULL""".split())


def uncomment(src):
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def strip(src):
    """comments and string/char literals out; the preprocessor lines stay"""
    src = uncomment(src)
    return re.sub(r'"(\\.|[^"\\])*"|\'(\\.|[^\'\\])*\'', '""', src)


def idents(src):
    return set(re.findall(r"[A-Za-z_]\w*", src))


def defined_names(src):
    """the functions and objects a file defines or declares at file scope (column 0), and its macros with their bodies"""
    names, macros = set(), {}
    src = re.sub(r"\\\n", " ", strip(src))
    for line in src.split("\n"):
        m = re.match(r"\s*#\s*define\s+([A-Za-z_]\w*)(\([^)]*\))?\s*(.*)", line)
        if m:
            macros[m.group(1)] = m.group(3)
            continue
        if not line or line[0] in " \t#}{)":
            continue
        decl = re.sub(r"__attribute__\s*\(\(.*?\)\)", "", line)
        m = re.match(r"(?:(?:static|extern|inline|const|volatile|unsigned|signed|struct|union|enum)\s+)*"
                     r"[A-Za-z_][\w ]*?[\s\*]+\**([A-Za-z_]\w*)\s*(\(|\[|=|;|,)", decl) or \
            re.match(r"(?:static\s+)?(?:const\s+)?[A-Za-z_]\w*\s+\*?\s*([A-Za-z_]\w*)\s*(\(|\[|=|;)", decl)
        if m and not decl.startswith(("typedef", "return", "else", "if", "for", "while")):
            names.add(m.group(1))
    return names, macros


def other_files(module):
    files = [p for p in sorted(SRC.glob("*.[ch]")) + sorted((ROOT / "firmware" / "hal").glob("*.h"))
             + sorted((ROOT / "firmware" / "engines" / "src").glob("*.[ch]")) if p.name != f"{module}.c"
             and p.name not in MODULES[module]["interface"] and p.name != f"{module}_port.c"]
    return files


def forbidden_set(module):
    """names of other files' functions and objects, and macros whose body names one"""
    names, macros = set(), {}
    for p in other_files(module):
        n, m = defined_names(p.read_text(errors="replace"))
        names |= n
        macros.update(m)
    names -= OK
    for _ in range(3):                           # macros expanding to a forbidden name (TSEL -> trk, TP -> ...)
        names |= {k for k, body in macros.items() if idents(body) & names and k not in OK}
    return names


def check(module, text):
    """-> the violations of module's source text: [(what, name)]"""
    out = []
    for inc in re.findall(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', uncomment(text), flags=re.M):
        if inc not in MODULES[module]["headers"]:
            out.append(("include", inc))
    # In the single translation unit, even a repeated tentative static declaration
    # can name another owner's state. Only the interfaces may expose a name already
    # owned elsewhere; genuine local helpers/state are absent from forbidden_set.
    allowed = set()
    for h in MODULES[module]["interface"]:
        allowed |= idents(strip((SRC / h).read_text()))
    for name in sorted((idents(strip(text)) & forbidden_set(module)) - allowed):
        out.append(("use", name))
    return out


FIXTURES = [   # (name, text appended to sound.c, what must be reported)
    ("a module's state", "\nvoid leak(void) { trk[0].eng_req = 0; }\n", ("use", "trk")),
    ("another module's function", "\nvoid leak(void) { (void)eng_of(0); }\n", ("use", "eng_of")),
    ("an owner's helper", "\nvoid leak(void) { fm6_set_patch(0, 0); }\n", ("use", "fm6_set_patch")),
    ("an owner's helper with a local prototype",
     "\nstatic void fm6_set_patch(uint32_t tr, const uint8_t *v);\n"
     "void leak(void) { fm6_set_patch(0, 0); }\n", ("use", "fm6_set_patch")),
    ("an owner's state with an extern declaration",
     "\nextern volatile uint8_t panic_req;\nvoid leak(void) { panic_req = 1; }\n", ("use", "panic_req")),
    ("an owner's state with a repeated tentative declaration",
     "\nstatic volatile uint8_t panic_req;\nvoid leak(void) { panic_req = 1; }\n", ("use", "panic_req")),
    ("a core.h static function", "\nvoid leak(void) { (void)swing_step_len(0, 0, 0); }\n", ("use", "swing_step_len")),
    ("a macro that expands to state", "\nvoid leak(void) { TSEL->eng_req = 0; }\n", ("use", "TSEL")),
    ("a sequencer variable", "\nvoid leak(void) { panic_req = 1; }\n", ("use", "panic_req")),
    ("an unlisted include", '\n#include "seq.c"\n', ("include", "seq.c")),
]


def main():
    text = (SRC / "sound.c").read_text()
    bad = 0
    found = check("sound", text)
    print(f"sound.c: {'ok' if not found else 'VIOLATIONS'}")
    for what, name in found:
        print(f"  {what} {name}: not in sound.h / sound_port.h / the listed headers (docs/modules.md)")
        bad += 1
    for label, extra, want in FIXTURES:
        got = check("sound", text + extra)
        if want in got:
            print(f"  ok  fixture rejected: {label} ({want[1]})")
        else:
            print(f"  FAIL fixture not rejected: {label} ({want[1]}); reported {got}")
            bad += 1
    local = "\nstatic int local_helper(uint32_t i);\nstatic int local_helper(uint32_t i) { return i != 0; }\n" \
            "void local_use(void) { (void)local_helper(0); }\n"
    got = check("sound", text + local)
    print(f"  {'FAIL' if got else 'ok'}  local helper definition with forward declaration: {got}")
    bad += bool(got)
    local_state = "\nstatic volatile uint8_t module_local_state;\n" \
                  "void local_state_use(void) { module_local_state = 1; }\n"
    got = check("sound", text + local_state)
    print(f"  {'FAIL' if got else 'ok'}  local tentative state: {got}")
    bad += bool(got)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
