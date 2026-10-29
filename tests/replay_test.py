#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Scenario validation and real native emulator capture/replay regressions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import wave

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fm1_replay", ROOT / "tools/fm1_replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)
BASE = json.loads((ROOT / "tests/scenarios/interaction.json").read_text())


class ValidationTests(unittest.TestCase):
    def test_engine_and_generated_include_changes_native_replay_inputs(self):
        paths = ("firmware/engines/src/dsp.c", "firmware/engines/src/felucca_engine.h",
                 "firmware/engines/src/eng_analog.c", "build/gen/engine_registry.inc")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in paths:
                dependency = root / name
                dependency.parent.mkdir(parents=True, exist_ok=True)
                dependency.write_text("/* original dependency */\n")
            with mock.patch.object(replay, "ROOT", root):
                original = replay.source_inputs()
                for name in paths:
                    with self.subTest(dependency=name):
                        self.assertIn(name, original)
                        dependency = root / name
                        dependency.write_text("/* changed dependency */\n")
                        changed = replay.source_inputs()
                        self.assertNotEqual(original[name], changed[name])
                        dependency.write_text("/* original dependency */\n")

    def test_changed_compile_dependency_is_not_published_or_replayed(self):
        for name in ("firmware/engines/src/dsp.c", "build/gen/engine_registry.inc"):
            with self.subTest(dependency=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                generated = root / "build/gen"
                generated.mkdir(parents=True)
                (generated / "felucca_tables.h").write_text("/* generated tables */\n")
                (generated / "build-identity.json").write_text("{}\n")
                dependency = root / name
                dependency.parent.mkdir(parents=True, exist_ok=True)
                dependency.write_text("/* original dependency */\n")

                def compile_then_change(command, **kwargs):
                    if "-o" in command:
                        Path(command[command.index("-o") + 1]).write_bytes(b"linked adapter")
                        dependency.write_text("/* dependency changed after compiler read */\n")

                with mock.patch.object(replay, "ROOT", root), \
                     mock.patch.object(replay.subprocess, "run", side_effect=compile_then_change), \
                     mock.patch.object(replay.subprocess, "check_output",
                                       side_effect=lambda command, **kwargs: "fixture cc\n" if kwargs.get("text") else b""), \
                     mock.patch.object(replay, "git", return_value=""), \
                     mock.patch.dict(os.environ, {"CC": "cc"}):
                    provenance = {"inputs": replay.source_inputs()}
                    with self.assertRaisesRegex(ValueError, "changed during native compilation"):
                        replay.build_adapter()
                    self.assertFalse(list((root / "build/replay-native").glob("adapter-*.so")))
                    out = root / "build/capture"
                    with mock.patch.object(replay, "Adapter") as adapter:
                        with self.assertRaisesRegex(ValueError, "changed before replay"):
                            replay.replay({}, b"", out, root / "unused.so", provenance, 0)
                        adapter.assert_not_called()
                    self.assertFalse(out.exists())

    def test_shared_nor_changes_native_replay_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            header = root / "tests/host_nor.h"
            header.parent.mkdir()
            header.write_text("/* first NOR implementation */\n")
            with mock.patch.object(replay, "ROOT", root):
                first = replay.source_inputs()
                self.assertIn("tests/host_nor.h", first)
                header.write_text("/* changed NOR implementation */\n")
                second = replay.source_inputs()
            self.assertNotEqual(first["tests/host_nor.h"], second["tests/host_nor.h"])

    def setUp(self):
        build = ROOT / "build"
        build.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="replay-validation-", dir=build)
        self.path = Path(self.temp.name) / "input.json"

    def tearDown(self):
        self.temp.cleanup()

    def load(self, data, **kwargs):
        self.path.write_text(json.dumps(data))
        return replay.load_scenario(self.path, **kwargs)

    def test_checked_in_sequences(self):
        for path in (ROOT / "tests/scenarios").glob("*.json"):
            replay.load_scenario(path)

    def test_bad_event_fields_and_ranges(self):
        bad_events = [
            {"sample": -1, "type": "capture"}, {"sample": True, "type": "capture"},
            {"sample": 0.5, "type": "capture"}, {"sample": 1 << 64, "type": "capture"},
            {"sample": 0, "type": "key", "id": 27, "down": True},
            {"sample": 0, "type": "key", "id": -1, "down": True},
            {"sample": 0, "type": "key", "id": 0, "down": 1},
            {"sample": 0, "type": "button", "id": "B_PLAY", "down": True},
            {"sample": 0, "type": "encoder", "id": "KNOB 5", "delta": 1},
            {"sample": 0, "type": "encoder", "id": "KNOB 1", "delta": 1025},
            {"sample": 0, "type": "midi", "status": 248, "data1": 0, "data2": 0},
            {"sample": 0, "type": "midi", "status": 144, "data1": 128, "data2": 0},
            {"sample": 0, "type": "midi", "status": 192, "data1": 2, "data2": 1},
            {"sample": 0, "type": "master", "value": 1024},
            {"sample": 0, "type": "capture", "unknown": 1},
            {"sample": 0, "type": "parameter", "id": 0, "value": 1},
            {"sample": 0, "type": "note_on"}, {},
        ]
        for event in bad_events:
            with self.subTest(event=event):
                data = copy.deepcopy(BASE)
                data["events"] = [event, {"sample": 100, "type": "end"}]
                with self.assertRaises(ValueError):
                    self.load(data)

    def test_initial_state_and_version(self):
        for key, value in (("schema", 2), ("sample_rate", 48000), ("initial", {}), ("events", [])):
            data = copy.deepcopy(BASE)
            data[key] = value
            with self.assertRaises(ValueError):
                self.load(data)
        for key, value in (("seed", 0), ("warmup_samples", 1), ("state", "saved"),
                           ("click", 3), ("usb_level", 2), ("master", -1)):
            data = copy.deepcopy(BASE)
            data["initial"][key] = value
            with self.assertRaises(ValueError):
                self.load(data)

    def test_order_and_explicit_end(self):
        for events in ([{"sample": 10, "type": "capture"}, {"sample": 9, "type": "end"}],
                       [{"sample": 1, "type": "end"}, {"sample": 1, "type": "capture"}],
                       [{"sample": 0, "type": "end"}], [{"sample": 1, "type": "capture"}]):
            data = copy.deepcopy(BASE)
            data["events"] = events
            with self.assertRaises(ValueError):
                self.load(data)

    def test_finite_limits_and_encoder_accumulation(self):
        for events in ([{"sample": 0, "type": "capture"}] * 257,
                       [{"sample": 0, "type": "master", "value": 0}] * 4096,
                       [{"sample": 0, "type": "encoder", "id": "KNOB 1", "delta": 1024}] * 65):
            data = copy.deepcopy(BASE)
            data["events"] = events + [{"sample": 10, "type": "end"}]
            with self.assertRaises(ValueError):
                self.load(data)
        with self.assertRaises(ValueError):
            self.load(BASE, max_output=1000)
        with self.assertRaises(ValueError):
            self.load(BASE, max_output=replay.MAX_OUTPUT + 1)

    def test_malformed_oversized_duplicate_and_deep_json(self):
        for raw in (b"{", b"\xff", b'{"schema":1,"schema":1}', b"[" * 2000 + b"]" * 2000,
                    b" " * (replay.MAX_INPUT + 1)):
            self.path.write_bytes(raw)
            with self.assertRaises(ValueError):
                replay.load_scenario(self.path)

    def test_output_destination(self):
        with self.assertRaises(ValueError):
            replay.output_path(ROOT / "tests/out")
        with self.assertRaises(ValueError):
            replay.output_path(ROOT / "build")
        with self.assertRaises(ValueError):
            replay.output_path(Path(self.temp.name))


@unittest.skipUnless((ROOT / "build/gen/felucca_tables.h").exists(), "run ./build.sh for native replay fixtures")
class NativeReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="replay-native-test-", dir=ROOT / "build")
        cls.directory = Path(cls.temp.name)
        cls.serial = 0

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_consumed_dependencies_are_fingerprinted(self):
        compiler = shlex.split(os.environ.get("CC", "cc"))
        output = subprocess.check_output([*compiler, *replay.FLAGS, "-MM", "tools/replay_native.c"],
                                         cwd=ROOT, text=True)
        dependencies = shlex.split(output.replace("\\\n", " ").split(":", 1)[1])
        consumed = {str((ROOT / name).resolve().relative_to(ROOT)) for name in dependencies}
        missing = consumed - replay.source_inputs().keys()
        self.assertTrue(consumed)
        self.assertFalse(missing, f"unfingerprinted compiler inputs: {sorted(missing)}")

    def run_scenario(self, data, success=True):
        type(self).serial += 1
        out = self.directory / f"out-{self.serial}"
        source = self.directory / f"scenario-{self.serial}.json"
        source.write_text(json.dumps(data))
        result = subprocess.run([sys.executable, str(ROOT / "tools/fm1_replay.py"), str(source),
                                 "--out", str(out)], cwd=ROOT, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return out, json.loads((out / "manifest.json").read_text())
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        return out, result

    def test_repeatability_held_octave_release_and_engine_switch(self):
        first, a = self.run_scenario(BASE)
        second, b = self.run_scenario(BASE)
        self.assertEqual(a["audio"], b["audio"])
        self.assertEqual(a["events"], b["events"])
        self.assertEqual(a["screen"]["frames"], b["screen"]["frames"])
        for path in first.glob("frame-*.ppm"):
            self.assertEqual(path.read_bytes(), (second / path.name).read_bytes())
        # ENV's graph panel: tempo only changes the header; attack changes the
        # real envelope drawing. Keep this independent of font/header pixels.
        graphs = [(first / f"frame-{n:04d}.ppm").read_bytes()[15 + 76 * 240 * 3:15 + 198 * 240 * 3]
                  for n in (3, 4, 5)]
        self.assertEqual(graphs[0], graphs[1])
        self.assertNotEqual(graphs[1], graphs[2])
        final = a["final_state"]
        self.assertEqual((final["keys_mask"], final["buttons_mask"], final["gated_voices"], final["active_voices"]),
                         (0, 0, 0, 0))
        self.assertEqual(final["octave"], 1)
        self.assertNotEqual(final["engine_requested"], a["timeline_origin"]["engine_requested"])
        self.assertNotEqual(final["engine_active"], a["timeline_origin"]["engine_active"])
        self.assertEqual(final["engine_active"], final["engine_requested"])
        with wave.open(str(first / "audio.wav"), "rb") as audio:
            self.assertEqual((audio.getnframes(), audio.getsampwidth(), audio.getnchannels(), audio.getframerate()),
                             (132301, 3, 2, 44100))
            self.assertTrue(any(audio.readframes(132301)))

    def test_capturing_does_not_change_pcm_or_firmware_state(self):
        _, captured = self.run_scenario(BASE)
        stripped = copy.deepcopy(BASE)
        stripped["events"] = [e for e in stripped["events"] if e["type"] != "capture"]
        _, plain = self.run_scenario(stripped)
        self.assertEqual(captured["audio"], plain["audio"])
        self.assertEqual(captured["final_state"], plain["final_state"])

    def test_equal_timestamp_file_order_and_final_partial_half(self):
        data = copy.deepcopy(BASE)
        data["events"] = [
            {"sample": 0, "type": "key", "id": 0, "down": True},
            {"sample": 0, "type": "capture"},
            {"sample": 0, "type": "key", "id": 0, "down": False},
            {"sample": 0, "type": "capture"},
            {"sample": 129, "type": "end"},
        ]
        out, manifest = self.run_scenario(data)
        frames = manifest["screen"]["frames"]
        self.assertEqual([f["state"]["keys_mask"] for f in frames], [1, 0])
        self.assertEqual([f["order"] for f in frames], [1, 3])
        self.assertEqual(frames[0]["actual_device_ms"], frames[1]["actual_device_ms"])
        self.assertEqual(frames[0]["sha256"], frames[1]["sha256"])
        self.assertEqual((out / "audio.wav").stat().st_size, 44 + 129 * 6)
        state = manifest["final_state"]
        self.assertEqual(state["produced_samples"] % 128, 0)
        self.assertEqual(state["consumed_samples"], data["initial"]["warmup_samples"] + 129)

    def test_channel_midi_overflow_fails_loudly(self):
        data = copy.deepcopy(BASE)
        data["events"] = [{"sample": 0, "type": "midi", "status": 144, "data1": 60, "data2": 96}] * 300
        data["events"].append({"sample": 100, "type": "end"})
        out, result = self.run_scenario(data, success=False)
        self.assertIn("MIDI queue full", result.stderr)
        self.assertFalse((out / "manifest.json").exists())

    def test_metronome_fixed_level_dac_contract(self):
        data = json.loads((ROOT / "tests/scenarios/metronome-fixed.json").read_text())
        _, with_click = self.run_scenario(data)
        data["initial"]["click"] = 0
        _, without_click = self.run_scenario(data)
        self.assertNotEqual(with_click["audio"]["pcm_sha256"], without_click["audio"]["pcm_sha256"])
        self.assertEqual(with_click["timeline_origin"]["usb_level"], 1)
        self.assertIn("post metronome", with_click["audio"]["tap"])
        self.assertTrue(any(e["state"]["playing"] for e in with_click["events"]))
        self.assertEqual(with_click["final_state"]["playing"], 0)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow unavailable for #58 pixel comparator")
    def test_existing_ui_comparator_accepts_replay_and_rejects_mixed_workloads(self):
        before, _ = self.run_scenario(BASE)
        after, manifest = self.run_scenario(BASE)
        report = self.directory / "comparison"
        command = [sys.executable, str(ROOT / "tests/ui_compare.py"), str(before), str(after),
                   "--out", str(report), "--strict"]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads((report / "summary.json").read_text())
        self.assertEqual(summary["changed_pixels"], 0)
        self.assertEqual(len(summary["scenes"]), 8)
        manifest["scenario_sha256"] = "different-workload"
        (after / "manifest.json").write_text(json.dumps(manifest))
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        summary = json.loads((report / "summary.json").read_text())
        self.assertIn("scenario_sha256", summary["errors"][0])
        manifest["scenario_sha256"] = replay.digest(json.dumps(BASE).encode())
        manifest["screen"]["frames"][0]["file"] = "../escape.ppm"
        (after / "manifest.json").write_text(json.dumps(manifest))
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("escapes", json.loads((report / "summary.json").read_text())["errors"][0])


if __name__ == "__main__":
    unittest.main()
