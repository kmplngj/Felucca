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
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "firmware" / "src"
GEN = ROOT / "build" / "gen"
sys.path.insert(0, str(ROOT / "tools"))
from build_report import canonical, generated_input_hashes
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


def references(src):
    # Member names belong to the public type, not a same-spelled file-scope
    # object: pr->fx is a preset field; bare fx still names fx.c's state.
    return idents(re.sub(r"(?:->|\.)\s*[A-Za-z_]\w*", "", strip(src)))


def split_level(text, separator):
    """Split declarators/statements, keeping commas inside types, calls and initializers."""
    depth, start = 0, 0
    for i, c in enumerate(text):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == separator and not depth:
            yield text[start:i]
            start = i + 1
    yield text[start:]


def without_attributes(text):
    while match := re.search(r"__attribute__\s*\(", text):
        depth = 0
        for i in range(match.end() - 1, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if not depth:
                    text = text[:match.start()] + text[i + 1:]
                    break
        else:
            break
    return text


def declarator(text, first=False):
    text = without_attributes(text)
    # Anonymous aggregate types can contain their own comma-separated fields.
    while re.search(r"\b(?:struct|union|enum)(?:\s+\w+)?\s*\{[^{}]*\}", text):
        text = re.sub(r"\b(struct|union|enum)(?:\s+\w+)?\s*\{[^{}]*\}", r"\1 __module_aggregate_type", text)
    text = re.sub(r"\*\s*(?:(?:const|volatile)\s+)+", "*", text)
    pointer = re.search(r"\(\s*\*+\s*(?:const\s+|volatile\s+)*([A-Za-z_]\w*)", text)
    if pointer and text.find("(") == pointer.start():
        return pointer[1], False
    if not first:
        m = re.match(r"\s*\**\s*(?:(?:const|volatile)\s+)*([A-Za-z_]\w*)", text)
        return (m[1], False) if m else (None, False)
    m = re.match(r"(?:(?:static|extern|inline|const|volatile|unsigned|signed|struct|union|enum)\s+)*"
                 r"[A-Za-z_][\w ]*?[\s\*]+\**([A-Za-z_]\w*)\s*(\(|\[|=|;|,)", text)
    return (m[1], m[2] == "(") if m and m[1] != "__module_aggregate_type" else (None, False)


def defined_names(src):
    """the functions and objects a file defines or declares at file scope (column 0), and its macros with their bodies"""
    names, macros = set(), {}
    src = re.sub(r"\\\n", " ", strip(src))
    for match in re.finditer(r"^.*$", src, flags=re.M):
        line = match.group()
        m = re.match(r"\s*#\s*define\s+([A-Za-z_]\w*)(\([^)]*\))?\s*(.*)", line)
        if m:
            macros[m.group(1)] = m.group(3)
            continue
        if not line or line[0] in " \t#}{)":
            continue
        if line.startswith(("typedef", "return", "else", "if", "for", "while")):
            continue
        name, function = declarator(line, first=True)
        if function:
            names.add(name)
            continue
        statement = next(split_level(src[match.start():], ";"))
        parts = list(split_level(statement, ","))
        name, _ = declarator(parts[0] + ";", first=True)
        if name:
            names.add(name)
            names.update(n for part in parts[1:] if (n := declarator(part)[0]))
    return names, macros


def validate_inventory(report, actual):
    expected = report.get("input_sha256")
    if (report.get("kind") != "felucca-generated-inputs" or report.get("schema") != 1 or
            not isinstance(expected, dict) or not expected or
            hashlib.sha256(canonical(expected)).hexdigest() != report.get("inputs_sha256")):
        raise ValueError("missing or invalid generated-input manifest")
    for name in ("felucca_tables.h", "felucca_fm6.h", "felucca_samples.h"):
        if "build/gen/" + name not in expected:
            raise ValueError("missing generated inventory header: " + name)
    if actual != expected:
        changed = sorted(k for k in actual.keys() | expected.keys() if actual.get(k) != expected.get(k))
        raise ValueError("stale generated inventory inputs: " + ", ".join(changed[:5]))


def generated_files():
    validate_inventory(json.loads((GEN / "generated-inputs.json").read_text()), generated_input_hashes(ROOT, GEN))
    return sorted(GEN.rglob("*.h")) + sorted(GEN.rglob("*.inc"))


def inventory_fixtures():
    report = json.loads((GEN / "generated-inputs.json").read_text())
    actual = dict(report["input_sha256"])
    changes = [("missing generated header", "build/gen/felucca_fm6.h", None),
               ("stale generated header", "build/gen/felucca_samples.h", "0" * 64),
               ("stale producer", "tools/gen_fm6_patches.py", "0" * 64),
               ("extra producer input", "tools/unregistered-generator.py", "0" * 64)]
    bad = 0
    validate_inventory(report, actual)
    for label, name, value in changes:
        changed = dict(actual)
        if value is None:
            changed.pop(name)
        else:
            changed[name] = value
        try:
            validate_inventory(report, changed)
        except ValueError:
            print("  ok  inventory refused: " + label)
        else:
            print("  FAIL inventory accepted: " + label)
            bad += 1
    try:
        validate_inventory({}, actual)
    except ValueError:
        print("  ok  inventory refused: missing manifest")
    else:
        print("  FAIL inventory accepted: missing manifest")
        bad += 1
    return bad


def other_files(module):
    files = [p for p in sorted(SRC.glob("*.[ch]")) + sorted((ROOT / "firmware" / "hal").glob("*.h"))
             + sorted((ROOT / "firmware" / "engines" / "src").glob("*.[ch]")) if p.name != f"{module}.c"
             and p.name not in MODULES[module]["interface"] and p.name != f"{module}_port.c"]
    return files


def forbidden_set(module, generated=None):
    """names of other files' functions and objects, and macros whose body names one"""
    names, macros = set(), {}
    for p in other_files(module) + (generated_files() if generated is None else generated):
        n, m = defined_names(p.read_text(errors="replace"))
        names |= n
        macros.update(m)
    names -= OK
    for _ in range(3):                           # macros expanding to a forbidden name (TSEL -> trk, TP -> ...)
        names |= {k for k, body in macros.items() if references(body) & names and k not in OK}
    return names


def check(module, text, forbidden=None):
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
    for name in sorted((references(text) & (forbidden_set(module) if forbidden is None else forbidden)) - allowed):
        out.append(("use", name))
    return out


FIXTURES = [   # (name, text appended to sound.c, what must be reported)
    ("a module's state", "\nvoid leak(void) { trk[0].eng_req = 0; }\n", ("use", "trk")),
    ("another module's function", "\nvoid leak(void) { (void)eng_of(0); }\n", ("use", "eng_of")),
    ("an owner's helper", "\nvoid leak(void) { fm6_set_patch(0, 0); }\n", ("use", "fm6_set_patch")),
    ("a generated FM6 table", "\nvoid leak(void) { (void)FM6_FACTORY[0][0]; }\n", ("use", "FM6_FACTORY")),
    ("a generated sample alias", "\nvoid leak(void) { (void)SMP_SET_ORIG[0]; }\n", ("use", "SMP_SET_ORIG")),
    ("a second object in one declaration", "\nvoid leak(void) { kb_trk[0] = 1; }\n", ("use", "kb_trk")),
    ("an anonymous aggregate's object", "\nvoid leak(void) { (void)&fx; }\n", ("use", "fx")),
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
    try:
        forbidden = forbidden_set("sound", generated_files())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"module boundary inventory: {error}; rerun build.generate() for fresh host assets", file=sys.stderr)
        return 1
    text = (SRC / "sound.c").read_text()
    bad = 0
    found = check("sound", text, forbidden)
    print(f"sound.c: {'ok' if not found else 'VIOLATIONS'}")
    for what, name in found:
        print(f"  {what} {name}: not in sound.h / sound_port.h / the listed headers (docs/modules.md)")
        bad += 1
    for label, extra, want in FIXTURES:
        got = check("sound", text + extra, forbidden)
        if want in got:
            print(f"  ok  fixture rejected: {label} ({want[1]})")
        else:
            print(f"  FAIL fixture not rejected: {label} ({want[1]}); reported {got}")
            bad += 1
    local = "\nstatic int local_helper(uint32_t i);\nstatic int local_helper(uint32_t i) { return i != 0; }\n" \
            "void local_use(void) { (void)local_helper(0); }\n"
    got = check("sound", text + local, forbidden)
    print(f"  {'FAIL' if got else 'ok'}  local helper definition with forward declaration: {got}")
    bad += bool(got)
    local_state = "\nstatic volatile uint8_t module_local_state;\n" \
                  "void local_state_use(void) { module_local_state = 1; }\n"
    got = check("sound", text + local_state, forbidden)
    print(f"  {'FAIL' if got else 'ok'}  local tentative state: {got}")
    bad += bool(got)
    declarations = """static uint8_t local_a[2] = {1, 2}, *local_b, local_c[2] = {(uint8_t)sizeof(struct {uint8_t x, y;}), 3};
static void (*local_callback_a)(int, int), (*local_callback_b)(int, int);
static struct { uint8_t x, y; } local_pair_a = {1, 2}, local_pair_b = {3, 4};
static const char *const local_names_a[] = {"a,b"}, *const local_names_b[] = {"c,d"};
static uint32_t local_attr_a __attribute__((aligned(4))), local_attr_b __attribute__((aligned(4)));
"""
    want = {"local_a", "local_b", "local_c", "local_callback_a", "local_callback_b", "local_pair_a", "local_pair_b",
            "local_names_a", "local_names_b", "local_attr_a", "local_attr_b"}
    got = defined_names(declarations)[0]
    print(f"  {'ok' if got == want else 'FAIL'}  comma declarations, aggregate/callback types and initializers: {sorted(got)}")
    bad += got != want
    got = check("sound", text + "\n" + declarations, forbidden)
    print(f"  {'FAIL' if got else 'ok'}  local comma declarations: {got}")
    bad += bool(got)
    member = "\nvoid local_member(const preset_t *pr) { (void)pr->fx[0]; }\n"
    got = check("sound", text + member, forbidden)
    print(f"  {'FAIL' if got else 'ok'}  public member with a private object's spelling: {got}")
    bad += bool(got)
    bad += inventory_fixtures()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
