#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""The musical frame (#297) has one implementation: main.c's music_frame_sense / music_frame_run / music_frame_poll.
The firmware loop (main.c fm1_main) and the emulator (web/emu/felucca_web.c web_ms, which native replay and the
partition tests drive) must call them in the same places and must not copy their steps. tests/frame_test.c runs the
emulator's side; this checks the firmware's loop, which cannot run on a host, against the same calls."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "firmware" / "src" / "main.c"
WEB = ROOT / "web" / "emu" / "felucca_web.c"
STEPS = ("ui_input", "settings_poll", "autosave_poll", "ui_leds", "ui_draw", "master_poll")


def strip(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", " ", text, flags=re.S)


def body(text, start):
    """the brace-balanced block that opens at or after index start"""
    i = text.index("{", start)
    depth = 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[i + 1:j]
    raise ValueError("unbalanced block")


def function(text, name):
    m = re.search(r"^static void " + name + r"\(void\)\s*\{", text, re.M)
    if not m:
        raise AssertionError(f"{name} not defined")
    return body(text, m.end() - 1)


def calls(text, names):
    return [m[1] for m in re.finditer(r"\b(" + "|".join(names) + r")\s*\(", text)]


class MusicalFrameSource(unittest.TestCase):
    main = strip(MAIN.read_text())
    web = strip(WEB.read_text())

    def test_shared_frame_order(self):
        run = function(self.main, "music_frame_run")
        self.assertEqual(calls(run, STEPS), ["ui_input", "settings_poll", "autosave_poll", "ui_leds", "ui_draw"])
        stages = re.findall(r"felucca_dbg\.stage\s*=\s*(\d+)", run)
        self.assertEqual(stages, ["1", "2", "9"])
        self.assertLess(run.index("felucca_dbg.ui_frames++"), run.index("ui_input"))
        sense = function(self.main, "music_frame_sense")
        self.assertIn("FM1_ADC_BATT", sense)
        self.assertEqual(calls(sense, STEPS), ["master_poll"])
        self.assertEqual(calls(function(self.main, "music_frame_poll"), STEPS), ["ui_input"])

    def test_firmware_loop(self):
        fm1_main = function(self.main, "fm1_main")
        loop = body(fm1_main, fm1_main.index("for (;;)"))
        order = calls(loop, ("music_frame_sense", "music_frame_run", "music_frame_poll"))
        self.assertEqual(order, ["music_frame_sense", "music_frame_run", "music_frame_poll"])
        self.assertEqual(calls(loop, STEPS), [], "fm1_main's loop copies a step of the shared frame")
        self.assertNotIn("FM1_ADC_BATT", loop)
        sense, run = loop.index("music_frame_sense"), loop.index("music_frame_run")
        # platform services keep their place between MASTER and the frame's input (#297: no reorder)
        for service in ("usb.uboot_req", "ed_service", "cdc_task"):
            self.assertTrue(sense < loop.index(service) < run, service)
        for service in ("fm1_wdt_feed", "usb_retry"):
            self.assertLess(loop.index(service), sense, service)
        wait = loop.index("while (fm1_ms - m < 15u)")
        self.assertTrue(run < wait < loop.index("music_frame_poll"))
        self.assertIn("music_frame_poll", body(loop, wait))

    def test_emulator(self):
        frame = function(self.web, "web_frame")
        self.assertEqual(calls(frame, ("music_frame_sense", "music_frame_run")), ["music_frame_sense", "music_frame_run"])
        self.assertEqual(re.sub(r"\s+", "", frame), "music_frame_sense();music_frame_run();")
        ms = function(self.web, "web_ms")
        steady = ms[ms.index("fm1_ms - web_last_frame >= 15u"):]
        self.assertEqual(calls(steady, ("web_frame", "music_frame_poll") + STEPS), ["web_frame", "music_frame_poll"])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False, verbosity=1).result.wasSuccessful() else 1)
