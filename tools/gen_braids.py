#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Translate the pinned Braids integer DSP into the firmware's single C unit.

The original MIT sources are bundled, hashed and kept readable. This narrowly
scoped translator removes classes/overloads; it is not a general C++ compiler.
Generated code is MIT. No network, heap, C++ runtime or static constructors.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets/braids/upstream"


def read(name):
    text = (ROOT / name).read_text()
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)


def balanced(s, start, opening="{", closing="}"):
    depth = 1
    i = start + 1
    while depth:
        if s[i] == opening:
            depth += 1
        elif s[i] == closing:
            depth -= 1
        i += 1
    return i


def casts(s):
    while (m := re.search(r"static_cast<([^>]+)>\s*\(", s)):
        end = balanced(s, m.end() - 1, "(", ")")
        s = s[:m.start()] + "(" + m[1] + ")(" + s[m.end():end] + s[end:]
    return s


classes = ["Excitation", "Svf", "AnalogOscillator", "DigitalOscillator", "MacroOscillator"]
headers = dict(zip(classes, ["excitation", "svf", "analog_oscillator", "digital_oscillator", "macro_oscillator"]))
fields = {}
functions = []
types = []
constants = []
tables = {}


def capture_functions(s, cls, inline=False):
    pattern = r"\b(?:inline\s+)?(void|bool|int\d+_t|uint\d+_t)\s+" + ("" if inline else cls + "::") + r"(\w+)\s*\(([^()]*)\)\s*(?:const\s*)?\{"
    for m in list(re.finditer(pattern, s)):
        end = balanced(s, m.end() - 1)
        functions.append((cls, m[1], m[2], m[3], s[m.end():end - 1], inline))


for cls in classes:
    h = read(headers[cls] + ".h")
    prefix = h[h.index("namespace braids {") + len("namespace braids {"):h.index("class " + cls)]
    prefix = re.sub(r"static const size_t (\w+) = ([^;]+);", r"enum { \1 = \2 };", prefix)
    prefix = re.sub(r"\b(enum|struct|union) (\w+)\s*\{(.*?)\};", r"typedef \1 \2 {\3} \2;", prefix, flags=re.S)
    types.append(prefix)
    capture_functions(h[h.index("class " + cls):], cls, True)
    private = h[h.index(" private:") + len(" private:"):h.index("DISALLOW_COPY_AND_ASSIGN")]
    # Strip the private methods; retain data and the anonymous delay union.
    private = re.sub(r"(?:inline\s+)?(?:void|bool|int\d+_t|uint\d+_t)\s+\w+\s*\([^;{}]*\)\s*;", "", private)
    while (m := re.search(r"inline\s+[^;{}]+\{", private)):
        end = balanced(private, m.end() - 1)
        private = private[:m.start()] + private[end:]
    private = re.sub(r"static RenderFn fn_table_\[\];", "", private)
    fields[cls] = re.findall(r"\b(\w+_)\s*(?:\[|;)", private)
    if cls == "DigitalOscillator":
        private += "\nuint32_t rng_;\n"
    types.append("typedef struct {\n" + private + "\n} " + cls + ";\n")
    if cls in ("AnalogOscillator", "DigitalOscillator", "MacroOscillator"):
        cc = read(headers[cls] + ".cc")
        capture_functions(cc, cls)
        table = re.search(r"::fn_table_\[\] = \{(.*?)\};", cc, re.S)
        tables[cls] = re.findall(r"&" + cls + r"::(\w+)", table[1])
        # Only file-scope declarations, never const locals or argument lists.
        for m in reversed(list(re.finditer(r"\b(?:void|int\d+_t|uint\d+_t)\s+" + cls + r"::\w+\s*\([^()]*\)\s*\{", cc))):
            end = balanced(cc, m.end() - 1)
            cc = cc[:m.start()] + cc[end:]
        constants += re.findall(r"(?:static )?const [^;{}]+(?:\{[^{}]*\}\s*;|;)", cc)
        # Structs and nested table initializers used by the vowel/wavetable models.
        for m in re.finditer(r"struct (\w+)\s*\{", cc):
            end = balanced(cc, m.end() - 1)
            types.append("typedef " + cc[m.start():end] + " " + m[1] + ";\n")
        for m in re.finditer(r"(?:static )?const [^;{}]+\{", cc):
            end = balanced(cc, m.end() - 1)
            declaration = cc[m.start():end] + ";"
            if declaration not in constants:
                constants.append(declaration)

shape = read("settings.h")
shape = shape[shape.index("enum MacroOscillatorShape"):shape.index("enum Resolution")]
types.insert(0, re.sub(r"enum (\w+)\s*\{(.*?)\};", r"typedef enum \1 {\2} \1;", shape, flags=re.S))

# C overloads use the original fixed-point helpers with explicit table types.
dsp = read("dsp.h")
helpers = []
for m in re.finditer(r"inline (int16_t|uint16_t) (\w+)\s*\(([^{};]*)\)\s*\{", dsp):
    end = balanced(dsp, m.end() - 1)
    name = m[2]
    suffix = "u8" if "uint8_t*" in m[3] else "u16" if "uint16_t*" in m[3] else "s16"
    if name in ("Mix", "Interpolate115", "Interpolate1022", "Crossfade1022", "Crossfade115"):
        if m[1] == "uint16_t" and name == "Mix":
            continue
        suffix = ""
    newname = "br_" + name + ("_" + suffix if suffix else "")
    body = casts(dsp[m.end():end])
    body = body.replace("Interpolate824(", "br_Interpolate824_" + suffix + "(")
    body = body.replace("Interpolate1022(", "br_Interpolate1022(").replace("Interpolate115(", "br_Interpolate115(")
    helpers.append("static inline " + m[1] + " " + newname + "(" + m[3] + ") {" + body + "\n")

resource = read("resources.cc")
res = []
for m in re.finditer(r"const (?:u?int\d+_t)(?:\*| )+\w+\[\] = \{", resource):
    end = balanced(resource, m.end() - 1)
    declaration = resource[m.start():end] + ";\n"
    # Two source samples per output frame at 44.1 kHz. Retune the immutable
    # phase/delay tables from 96 kHz to 88.2 kHz, outside the audio interrupt.
    if "--reference" not in sys.argv and ("lut_oscillator_increments[]" in declaration or "lut_oscillator_delays[]" in declaration):
        num, den = (96000, 88200) if "increments" in declaration else (88200, 96000)
        left, values = declaration.split("{", 1)
        values = re.sub(r"\b\d+\b", lambda m: str((int(m[0]) * num + den // 2) // den), values)
        declaration = left + "{" + values
    res.append("static " + declaration)

def convert(body, cls, name):
    body = casts(body)
    body = body.replace("const WavetableDefinition& wt = wavetable_definitions[wavetable_index];", "const WavetableDefinition* wt = &wavetable_definitions[wavetable_index];")
    body = body.replace("wt.num_steps", "wt->num_steps").replace("wt.wave_index", "wt->wave_index")
    if cls == "DigitalOscillator" and name == "ComputeDelay":
        body = "if (midi_pitch < 0) midi_pitch = 0;\n" + body
    for obj, target in [("analog_oscillator_", "AnalogOscillator"), ("digital_oscillator_", "DigitalOscillator"), ("pulse_", "Excitation"), ("svf_", "Svf")]:
        body = re.sub(r"\b(" + obj + r"(?:\[[^\]]+\])?)\.(\w+)\s*\(\s*", lambda m: target + "_" + m[2] + "(&" + m[1] + ", ", body)
    body = re.sub(r",\s*\)", ")", body)
    for c, _, name, _, _, _ in functions:
        if c == cls:
            body = re.sub(r"(?<![\w.])" + name + r"\s*\(\s*", name + "(s, ", body)
            body = body.replace(name + "(s, )", name + "(s)")
            body = re.sub(r"(?<!\w)" + name + r"\(", cls + "_" + name + "(", body)
    for field in fields[cls] + (["rng_"] if cls == "DigitalOscillator" else []):
        body = re.sub(r"(?<![\w.])" + field + r"\b", "s->" + field, body)
    body = body.replace("std::min", "BR_MIN")
    body = body.replace("std::fill(&buffer[0], &buffer[size], 0)", "memset(buffer, 0, size * sizeof(*buffer))")
    body = body.replace("Random::GetWord()", "br_random(&s->rng_)").replace("Random::GetSample()", "((int16_t)(br_random(&s->rng_) >> 16))")
    if cls == "DigitalOscillator" and body.strip().startswith("memset(&s->state_"):
        body += "\n if (!s->rng_) s->rng_ = 0x21;\n"
    body = re.sub(r"\bRenderFn fn = fn_table_\[shape_\];", "", body)
    body = body.replace("RenderFn fn = fn_table_[s->shape_];", "")
    body = body.replace("(this->*fn)(", cls + "_dispatch(s, ")
    return body

prototypes = []
bodies = []
for cls, ret, name, args, body, inline in functions:
    sig = ("static inline " if inline else "static ") + ret + " " + cls + "_" + name + "(" + cls + "* s" + (", " + args if args.strip() else "") + ")"
    prototypes.append(sig + ";\n")
    bodies.append(sig + " {\n" + convert(body, cls, name) + "\n}\n")
for cls, names in tables.items():
    args = "const uint8_t* sync, int16_t* buffer, " + ("uint8_t* sync_out, " if cls == "AnalogOscillator" else "") + "size_t size"
    prototypes.append("static void " + cls + "_dispatch(" + cls + "* s, " + args + ");\n")
    passed = "s, sync, buffer, " + ("sync_out, " if cls == "AnalogOscillator" else "") + "size"
    # The firmware retains its original WAVE/FOLD/FBFM implementations and IDs.
    # Remove their duplicate upstream paths from this bank, not the models.
    omitted = set() if "--reference" in sys.argv else {"MacroOscillator": {3, 26, 39}, "DigitalOscillator": {13, 26}, "AnalogOscillator": {6, 7}}.get(cls, set())
    bodies.append("static void " + cls + "_dispatch(" + cls + "* s, " + args + ") {\n switch(s->shape_) {\n" + "".join("case " + str(i) + ": " + cls + "_" + name + "(" + passed + "); break;\n" for i, name in enumerate(names) if i not in omitted) + "default: memset(buffer, 0, size * sizeof(*buffer)); break;\n}\n}\n")

macros = read("parameter_interpolation.h")
macros = "\n".join(l for l in macros.splitlines() if not l.startswith(("#ifndef", "#define BRAIDS_", "#endif")))
for field in ("previous_parameter_", "parameter_", "previous_phase_increment_", "phase_increment_"):
    macros = re.sub(r"\b" + field + r"\b", "s->" + field, macros)
stmlib = read("stmlib.h")
clip = stmlib[stmlib.index("#define CLIP"):stmlib.index("#define CONSTRAIN")]

out = "/* SPDX-License-Identifier: MIT\n * Copyright 2012-2013 Emilie Gillet. Generated by tools/gen_braids.py.\n * Source notices and pinned inputs: assets/braids/upstream/, LICENSES/MIT-Braids.txt. */\n"
out += "\n/* The firmware supplies stdint/size_t/memset. No hosted C library on pi32v2. */\n"

out += "\n".join(l for l in read("resources.h").splitlines() if l.startswith("#define ") and not l.startswith("#define BRAIDS_")) + "\n#define SEMI * 128\n"
out += clip + "\n#define CONSTRAIN(x,a,b) x = x < a ? a : (x > b ? b : x);\n#define BR_MIN(a,b) ((a) < (b) ? (a) : (b))\n"
out += "static inline uint32_t br_random(uint32_t* s) { *s = *s * 1664525u + 1013904223u; return *s; }\n"
out += "\n".join(types) + "\n".join(res) + "\n".join(helpers)
out += "\n#define Interpolate824(t,p) _Generic((t), const uint8_t*: br_Interpolate824_u8, const uint16_t*: br_Interpolate824_u16, default: br_Interpolate824_s16)(t,p)\n"
out += "#define Interpolate88(t,p) _Generic((t), const uint16_t*: br_Interpolate88_u16, default: br_Interpolate88_s16)(t,p)\n"
out += "#define Crossfade(a,b,p,w) _Generic((a), const uint8_t*: br_Crossfade_u8, default: br_Crossfade_s16)(a,b,p,w)\n"
for name in ("Mix", "Interpolate115", "Interpolate1022", "Crossfade1022", "Crossfade115"):
    out += "#define " + name + " br_" + name + "\n"
out += macros + "\n" + "\n".join(prototypes)
# File-local constants have identical names in the two oscillator translation units.
out += "\n".join(dict.fromkeys(constants)) + "\n" + "\n".join(bodies)
out = out.replace("stmlib::", "")
out = re.sub(r"\bbool\b", "_Bool", out)
out = re.sub(r"\btrue\b", "1", out)
out = re.sub(r"\bfalse\b", "0", out)
out = re.sub(r"\bNULL\b", "0", out)
out = re.sub(r"\bsize_t\b", "uint32_t", out)
out = out.replace("kHighestNote = 140 * 128", "kDigitalHighestNote = 140 * 128")
# Digital references retain their 140-note bound; analog retains 128.
start = out.index("static uint32_t DigitalOscillator_ComputePhaseIncrement(", out.index("static uint32_t DigitalOscillator_ComputePhaseIncrement(") + 1)
out = out[:start] + out[start:].replace("kHighestNote", "kDigitalHighestNote")
# Namespacing the generated unit keeps its helpers out of the rest of Felucca.
tokens = set(re.findall(r"\b(?:br_\w+|(?:AnalogOscillator|DigitalOscillator|MacroOscillator|Svf|Excitation)_\w+|(?:OSC_|MACRO_OSC_|SVF_)\w+|k\w+|lut_\w+|wav_\w+|wt_\w+|ws_\w+|chr_\w+|intervals|PhonemeDefinition|phonemes|WavetableDefinition|wavetable_definitions|AdditiveState|PluckState|Grain|[A-Z]\w+State|DigitalOscillatorState|SvfMode|SyncMode|MacroOscillatorShape|DigitalOscillatorShape|AnalogOscillatorShape|AnalogOscillator|DigitalOscillator|MacroOscillator|Excitation|Svf)\b", out))
for token in sorted(tokens, key=len, reverse=True):
    out = re.sub(r"\b" + token + r"\b", "braids_" + token, out)
for before, after in sorted(({} if "--raw-arithmetic" in sys.argv else json.loads((ROOT.parent / "c-arithmetic.json").read_text())).items(), key=lambda p: len(p[0]), reverse=True):
    pattern = r"(?<!\w)" + re.escape(before) + r"(?!\w)"
    out = re.sub(pattern, lambda _: after, out)
out += "\n" + "\n".join("#undef " + n for n in ["CLIP", "CONSTRAIN", "BR_MIN", "SEMI", "Interpolate824", "Interpolate88", "Crossfade", "Mix", "Interpolate115", "Interpolate1022", "Crossfade1022", "Crossfade115"])
for name, expected in json.loads((ROOT / "SHA256.json").read_text()).items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
Path(sys.argv[1]).write_text(out + "\n")
print("Braids: 48 models, original resource bank, offline C translation")
