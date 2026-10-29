#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Source check of the stored record kinds' boundary (#310, firmware/src/store_kind.h; the header pattern of
project_codec.h / docs/modules.md for #454).

The handlers of the full backup and the raw store export in firmware/src/editor_backup.c (ed_bk_commit, ed_bk_write,
ed_backup_handle, ed_raw_kind, ed_raw_handle) only iterate the descriptor table SK_KINDS: none of them names a
storage type (OBJ_*), a backup id constant (ED_BK_ID_*), a kind's own function (sk_* other than the table's lookups)
or the owner of a kind's layout (the project codec, the settings record, the user preset banks, the FM6 stores, the
SLICE records, the sample slots), and none compares a backup or storage id against a number. A kind's lengths,
validation, install and export are its row; tests/backup_test.c checks the rows against the wire contract.

Self-test: mutations of the real source (an id chain back in the commit, a storage type in the raw export, a codec
call in the commit, a kind's check called by the write path, a length list in BEGIN) must each be rejected.
  python3 tests/store_kind_boundary_test.py"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "firmware" / "src" / "editor_backup.c"
HANDLERS = ("ed_bk_commit", "ed_bk_write", "ed_backup_handle", "ed_raw_kind", "ed_raw_handle")
LOOKUPS = {"sk_of_bk", "sk_of_obj", "sk_bk_count", "sk_accepts"}
OWNERS = re.compile(r"\b(?:proj_(?!wire_gen\b)\w+|project_\w+|settings_\w+|persist_(?:ext_ok|len)|palette_\w+|up_bank\w*|upf\w*|"
                    r"fm6_bank\w*|fvb_\w+|ed_bk_fvb_\w+|slc_\w+|smp_user_\w+|ed_bk_panel_valid)\b")
ID_CMP = re.compile(r"\b(?:ed_bk_id|id)\s*(?:==|!=|<=|>=|<|>)\s*\d|\d+u?\s*(?:==|!=|<=|>=|<|>)\s*(?:ed_bk_id|id)\b"
                    r"|\ba\[1\]\s*(?:==|!=|<=|>=|<|>)")


def strip(text):
    """the code without comments and string literals"""
    text = re.sub(r"/\*.*?\*/|//[^\n]*", " ", text, flags=re.S)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


def body(text, name):
    """the body of function name (from its definition's '{' to the matching '}'), or None"""
    m = re.search(r"^static\s+[^\n;(]*\b%s\s*\([^;{]*\)\s*\{" % re.escape(name), text, re.M)
    if not m:
        return None
    i, depth = m.end() - 1, 0
    while i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
        if depth == 0:
            return text[m.end():i - 1]
    return None


def check(source):
    bad = []
    code = strip(source)
    if "SK_KINDS[]" not in code:
        bad.append("editor_backup.c defines no SK_KINDS table")
    for h in HANDLERS:
        b = body(code, h)
        if b is None:
            bad.append(f"{h} not found")
            continue
        for name in sorted(set(re.findall(r"\bOBJ_\w+|\bED_BK_ID_\w+", b))):
            bad.append(f"{h} names {name}: a storage type / backup id belongs in its kind's row (SK_KINDS)")
        for name in sorted(set(re.findall(r"\bsk_\w+", b)) - LOOKUPS):
            bad.append(f"{h} names the kind function {name}: reach it through its row")
        for name in sorted(set(OWNERS.findall(b))):
            bad.append(f"{h} names {name}, a kind's own layout or install: put it in that kind's row")
        for m in ID_CMP.finditer(b):
            bad.append(f"{h} compares an id with a number ({m.group(0).strip()}): iterate the kinds instead")
    return bad


def main():
    source = SRC.read_text()
    bad = check(source)
    for b in bad:
        print("FAIL", b)
    mutations = [
        ("an id chain back in the commit", "static uint32_t ed_bk_commit(void)\n{",
         "static uint32_t ed_bk_commit(void)\n{\n    if (ed_bk_id == 8u) return 0;"),
        ("a storage type in the raw export", "static int ed_raw_handle(uint32_t cmd, const uint8_t *a, uint32_t n)\n{",
         "static int ed_raw_handle(uint32_t cmd, const uint8_t *a, uint32_t n)\n{\n    (void)OBJ_SETTINGS;"),
        ("a codec call in the commit", "static uint32_t ed_bk_commit(void)\n{",
         "static uint32_t ed_bk_commit(void)\n{\n    (void)proj_decode;"),
        ("a kind's check called by the write path",
         "static uint32_t ed_bk_write(const uint8_t *a, uint32_t n)\n{",
         "static uint32_t ed_bk_write(const uint8_t *a, uint32_t n)\n{\n    (void)sk_set_check;"),
        ("a length list in BEGIN", "if (len > ED_BK_MAX || !sk_accepts(s, len)) return 1;",
         "if (len > ED_BK_MAX || !sk_accepts(s, len) || (a[1] == 9u && len != sizeof(upf_t))) return 1;"),
    ]
    rejected = 0
    for what, old, new in mutations:
        assert old in source, (what, old)
        if len(check(source.replace(old, new, 1))) > len(bad):
            rejected += 1
        else:
            print("FAIL the check does not reject:", what)
    ok = not bad and rejected == len(mutations)
    print(f"store kind boundary: {len(bad)} violations, {rejected}/{len(mutations)} mutations rejected: "
          f"{'ok' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
