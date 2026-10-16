#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Failure controls for portable stress schedules and result acceptance."""
import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import stress_matrix
from stress_matrix import health, validate
import stress_replay


class StressContractTest(unittest.TestCase):
    def setUp(self):
        self.matrix = json.loads(Path(__file__).with_name("stress_scenarios.json").read_text())

    def test_checked_in_timeline(self):
        self.assertTrue({"idle", "shared_eight", "voice_pressure", "active_effects", "engine_switch_tails",
                         "dense_ratchets_modulation", "effects_throws", "usb_trs_midi"}
                        <= {s["name"] for s in validate(self.matrix)})

    def test_tempo_uses_firmware_units_not_midi_data_range(self):
        self.matrix["scenarios"][0]["events"] = [[0, "global", 0, "bpm", 180]]
        validate(self.matrix)

    def test_reject_bad_timing_and_unbounded_work(self):
        for event in ([321, "on", 0, 60, 100], [352800, "on", 0, 60, 100],
                      [320, "on", 4, 60, 100], [320, "on", 0, 60, 0],
                      [320, "on", 0, 60, 180],
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

    def test_catalogue_inputs_and_device_null_template(self):
        root = Path(__file__).parent
        catalog = json.loads((root / "stress_catalog.json").read_text())
        self.assertEqual(set(catalog["direct_scenarios"]), {s["name"] for s in validate(self.matrix)})
        for case in catalog["integrated"]:
            self.assertTrue((root / case["input"]).is_file())
        streams = [c for c in catalog["device"] if c["audio_capture_rate"]]
        self.assertEqual({c["audio_capture_rate"] for c in streams}, {44100, 48000})
        template = json.loads((root / "stress_device_result.json").read_text())
        self.assertEqual(template["status"], "unmeasured")
        self.assertTrue(all(v is None for v in template["diagnostics"]["deltas"].values()))

    def test_new_event_bounds_and_signedness(self):
        events = [[0, "step", 0, 64, {"notes": [60], "drums": 0, "ratchet": 4, "velocity": 96}],
                  [0, "step", 0, 0, {"notes": [60], "drums": 0, "ratchet": 5, "velocity": 96}],
                  [0, "step", 0, 0, {"notes": [128], "drums": 0, "ratchet": 4, "velocity": 96}],
                  [0, "transport", 1, 0, 1], [0, "perform", 0, 16, 1],
                  [0, "usb_midi", 0, 0x90, 0x80], [0, "usb_midi", 0, 0xc0, 0x100],
                  [0, "trs_byte", 0, 0, 256]]
        for event in events:
            m = copy.deepcopy(self.matrix)
            m["scenarios"][0]["events"] = [event]
            with self.subTest(event=event), self.assertRaises(ValueError):
                validate(m)

    def test_integrated_health_refuses_no_save_or_missing_load(self):
        final = dict(playing=0, active_voices=0, gated_voices=0, keys_mask=0,
                     buttons_mask=0, user_presets=1, screen_draws=12)
        manifest = {"final_state": final, "timeline_origin": {"screen_draws": 0},
                    "events": [{"state": {"gated_voices": 1}}]}
        checks = dict(min_gates=1, min_draws=3, user_presets=1)
        stress_replay.health(manifest, checks)
        for field, value in (("user_presets", 0), ("screen_draws", 2), ("active_voices", 1)):
            bad = copy.deepcopy(manifest)
            bad["final_state"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                stress_replay.health(bad, checks)
        manifest["events"][0]["state"]["gated_voices"] = 0
        with self.assertRaises(ValueError):
            stress_replay.health(manifest, checks)

    def test_stalled_compiler_metadata_and_probe_retain_failure_report(self):
        build = stress_matrix.ROOT / "build"
        build.mkdir(exist_ok=True)
        for fast_version in (False, True):
            with self.subTest(fast_version=fast_version), tempfile.TemporaryDirectory(dir=build) as directory:
                root = Path(directory)
                compiler = root / "stalled_cc.py"
                compiler.write_text("import sys, time\n"
                                    f"if {fast_version!r} and '--version' in sys.argv:\n"
                                    "    print('fake-cc')\n"
                                    "else:\n"
                                    "    time.sleep(2)\n")
                out = root / "result"
                cc = f"{shlex.quote(sys.executable)} {shlex.quote(str(compiler))}"
                cwd = Path.cwd()
                try:
                    with mock.patch.dict(os.environ, {"CC": cc}), \
                         mock.patch.object(sys, "argv", ["stress_matrix.py", "--out", str(out)]), \
                         mock.patch.object(stress_matrix, "METADATA_TIMEOUT", 1, create=True):
                        with self.assertRaises(subprocess.TimeoutExpired):
                            stress_matrix.main()
                    report = json.loads((out / "report.json").read_text())
                    self.assertEqual(report["status"], "failed")
                    self.assertIn(str(compiler), report["error"])
                    self.assertIn("timed out", report["error"])
                finally:
                    os.chdir(cwd)

    def test_replay_timeout_retains_partial_diagnostics(self):
        build = stress_matrix.ROOT / "build"
        build.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build) as directory:
            out = Path(directory) / "replay"
            error = subprocess.TimeoutExpired(["renderer"], 90, output=b"render checkpoint\n",
                                              stderr=b"stalled voice\xff\n")
            with mock.patch.object(subprocess, "run", side_effect=error):
                with self.assertRaises(subprocess.TimeoutExpired):
                    stress_matrix.run(Path("renderer"), 0, out)
            self.assertEqual((out / "stdout.txt").read_bytes(), error.stdout)
            self.assertEqual((out / "stderr.txt").read_bytes(), error.stderr)

    def test_compile_timeout_retains_bytes_text_and_empty_output(self):
        build = stress_matrix.ROOT / "build"
        build.mkdir(exist_ok=True)
        for stdout, stderr, expected in ((b"compile checkpoint\n", b"warning\xff\n", b"compile checkpoint\nwarning\xff\n"),
                                         ("compile checkpoint\n", "warning\n", b"compile checkpoint\nwarning\n"),
                                         (None, None, b"")):
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory(dir=build) as directory:
                log = Path(directory) / "build_o2.log"
                error = subprocess.TimeoutExpired(["cc"], 120, output=stdout, stderr=stderr)
                with mock.patch.object(subprocess, "run", side_effect=error):
                    with self.assertRaises(subprocess.TimeoutExpired):
                        stress_matrix.logged_run(["cc"], log, timeout=120)
                self.assertEqual(log.read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
