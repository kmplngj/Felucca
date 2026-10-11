#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Leo Kuroshita (@kurogedelic), Hügelton Instruments
"""tools/fm1pkg_make.py flash_image(): the app region (header, padded app, cfg_tool.bin,
nested cfg directory with eq_cfg_hw.bin) must fit FLASH_SIZE, with synthetic SDK files
(no SDK, no device). The checks are exceptions, so they hold under `python3 -O` too.
Run from the repo root:  python3 tests/pkg_make_test.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import fm1pkg_make as pm

CFG_FIT = 3812          # cfg_tool.bin size at which the region ends exactly at FLASH_SIZE (32 B boot blob, empty EQ)
fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += not ok


def build(cfg=CFG_FIT, eq=0, app=4, boot=32):
    files = {"uboot.boot": b"\x5A" * boot, "cfg_tool.bin": b"\xC3" * cfg, "cfg/eq_cfg_hw.bin": b"\xE1" * eq}
    saved = pm.sdk_file
    pm.sdk_file = lambda rel: files[rel]
    try:
        return pm.flash_image(b"\xA5" * app, pm.KEY)
    finally:
        pm.sdk_file = saved


def rejects(what, **kw):
    try:
        build(**kw)
    except SystemExit as e:
        return what in str(e.code), str(e.code)
    return False, "accepted"


img = build()
check("exact fit is accepted", len(img) == pm.FLASH_SIZE == 0x93000)
check("exact fit: region reaches the end of the image (not FF-filled there)", img[-32:] != b"\xFF" * 32)
check("smaller cfg_tool.bin: image is exactly FLASH_SIZE", len(build(cfg=100)) == pm.FLASH_SIZE)
check("full app slot, small cfg: image is exactly FLASH_SIZE", len(build(app=pm.APP_SLOT, cfg=100)) == pm.FLASH_SIZE)
check("padding after the region stays 0xFF", build(cfg=100)[-64:] == b"\xFF" * 64)

for name, kw, over in (("cfg_tool.bin +1 B", dict(cfg=CFG_FIT + 1), 1),
                       ("cfg_tool.bin +4096 B", dict(cfg=7908), 4096),
                       ("eq_cfg_hw.bin +1 B", dict(cfg=CFG_FIT, eq=1), 1),
                       ("eq_cfg_hw.bin +4096 B", dict(cfg=CFG_FIT, eq=4096), 4096),
                       ("cfg_tool.bin and eq_cfg_hw.bin grow", dict(cfg=CFG_FIT - 10, eq=11), 1)):
    ok, msg = rejects("app region", **kw)
    check(f"{name}: rejected", ok)
    check(f"{name}: reports {over} B too much, extent and available bytes",
          f"{over} B too much" in msg and f"{pm.FLASH_SIZE - 0x4000} B available" in msg
          and f"ends at {pm.FLASH_SIZE + over:#x}" in msg and "cfg_tool.bin" in msg and "eq_cfg_hw.bin" in msg)

ok, msg = rejects("the slot is", app=pm.APP_SLOT + 1, cfg=100)
check("app slot overflow still rejected", ok and f"{pm.APP_SLOT + 1} B" in msg)
check("app exactly the slot size is accepted", len(build(app=pm.APP_SLOT, cfg=100)) == pm.FLASH_SIZE)

print("PKG MAKE TESTS PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
