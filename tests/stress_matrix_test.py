#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Failure controls for portable stress schedules and result acceptance."""
import copy
import json
from pathlib import Path
import unittest

from stress_matrix import health, validate


class StressContractTest(unittest.TestCase):
    def setUp(self):
        self.matrix = json.loads(Path(__file__).with_name("stress_scenarios.json").read_text())

    def test_checked_in_timeline(self):
        self.assertTrue({"idle", "shared_eight", "voice_pressure", "active_effects", "engine_switch_tails"}
                        <= {s["name"] for s in validate(self.matrix)})

    def test_reject_bad_timing_and_unbounded_work(self):
        for event in ([321, "on", 0, 60, 100], [352800, "on", 0, 60, 100],
                      [320, "on", 4, 60, 100], [320, "on", 0, 60, 0],
                      [320, "param", 0, "unrecognized", 1], [320, "preset", 0, True, 0]):
            with self.subTest(event=event):
                m = copy.deepcopy(self.matrix)
                m["scenarios"][0]["events"] = [event]
                with self.assertRaises(ValueError):
                    validate(m)
        m = copy.deepcopy(self.matrix)
        m["scenarios"][0]["events"] = [[0, "on", 0, 60, 100]] * 513
        with self.assertRaises(ValueError):
            validate(m)

    def test_reject_out_of_order_and_unsafe_names(self):
        m = copy.deepcopy(self.matrix)
        m["scenarios"][0]["events"] = [[64, "on", 0, 60, 100], [32, "off", 0, 60, 0]]
        with self.assertRaises(ValueError):
            validate(m)
        for name in ("../escape", 'quote"', "shared_eight"):
            m = copy.deepcopy(self.matrix)
            m["scenarios"][0]["name"] = name
            with self.assertRaises(ValueError):
                validate(m)

    def test_health_detects_missing_load_hang_and_tail(self):
        s = self.matrix["scenarios"][1]
        result = {"frames": s["frames"], "playing": 0, "peak": 1000, "max_voices": 8,
                  "voice_starts": 8, "tail_peak": 0,
                  "parts": [{"engine": 0, "requested": 0, "active": 0, "gated": 0,
                             "held": 0, "fading": 0} for _ in range(4)]}
        health(s, result)
        for key, value in (("peak", 0), ("max_voices", 7), ("voice_starts", 7),
                           ("tail_peak", 100), ("playing", 1), ("frames", 32)):
            with self.subTest(key=key):
                bad = copy.deepcopy(result)
                bad[key] = value
                with self.assertRaises(ValueError):
                    health(s, bad)
        for key in ("active", "gated", "held", "fading", "engine", "requested"):
            with self.subTest(key=key):
                bad = copy.deepcopy(result)
                bad["parts"][0][key] = 1
                with self.assertRaises(ValueError):
                    health(s, bad)
        result["parts"].pop()
        with self.assertRaises(ValueError):
            health(s, result)


if __name__ == "__main__":
    unittest.main()
