#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Real firmware console contract, extensible fixtures and sessions; no device I/O."""
import base64
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import fm1_diagnostics as diag


STATUS = """felucca v1.6
uptime_ms 10000
cpu_pct 23
audio_max_us 900
audio_late 7
voices_shed 0
voices_given_up 2
engine FM6
preset BRASS ENSEMBLE
boots 4
usb_sof 8000
uac_underruns 0
uart_rx_drops 0
future_counter 17
"""
DBG = """magic 0x44424731
halves 0x00002000
max_us 0x00000384
nested 0x00000040
late 0x00000007
timer_irqs 0x00001000
boots 0x00000004
stage 0x00000009
"""
INP = """window_ms 1000
ticks_per_s 10000
gap_max_us 130
gap_hist <.15 .3 .6 1.2 2.4 4.8 9.6 more ms: 9999 1 0 0 0 0 0 0
tick_cost_avg_ns 7000
tick_cost_max_us 10
tick_cpu_permille 70
led_on_permille: 90 90 90
led_on_max_us: 105 103 104
enc moves/lost/detent state: 4/1/0 0/0/2
key_presses 2
key_press_avg_us 1100
key_press_max_us 1300
key_notes 2
key_noteon_avg_us 1900
key_noteon_max_us 2200
key_dac_avg_us 4000
key_dac_max_us 4800
timer_irqs 4096
nested 64
"""
CRASH = """count 2
vec 0x00000004
pc 0x02001234
rets 0x00000000
sp 0x01C60000
uptime_ms 50
early 0
"""


def reply(command, text):
    return (command + "\r\n" + text.replace("\n", "\r\n") + "> ").encode()


# The current production con_inp group; legacy replies may omit any of it.
LATENCY_FIELDS = ("key_presses", "key_press_avg_us", "key_press_max_us", "key_notes",
                  "key_noteon_avg_us", "key_noteon_max_us", "key_dac_avg_us", "key_dac_max_us")


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, amount):
        self.now += amount


class FakeTransport:
    def __init__(self, clock, responses=None, chunks=None):
        self.clock = clock
        self.responses = responses or {}
        self.pending = list(chunks or [])
        self.writes = []

    def write(self, data, timeout):
        self.writes.append(data)
        command = data.decode().strip()
        self.pending.extend(self.responses.get(command, []))

    def read(self, timeout):
        if self.pending:
            value = self.pending.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value
        self.clock.sleep(timeout)
        return None


class SessionTransport(FakeTransport):
    def __init__(self, clock, interrupt_at=None, reboot_at=None, unequal_at=None, malformed_at=None,
                 input_at=None, input_text=None, status_texts=None, command_texts=None):
        super().__init__(clock, chunks=[b"\r\nFelucca v1.6 console - 'help'\r\n> "])
        self.index = -1
        self.interrupt_at, self.reboot_at, self.unequal_at = interrupt_at, reboot_at, unequal_at
        self.malformed_at = malformed_at
        self.input_at, self.input_text = input_at, input_text
        self.status_texts = status_texts
        self.command_texts = command_texts or {}

    def write(self, data, timeout):
        self.writes.append(data)
        command = data.decode().strip()
        if command == "status":
            self.index += 1
        i = self.index
        if i == self.interrupt_at and command == "dbg":
            self.pending.extend([b"dbg\r\nmagic 0x44424731\r\n", OSError("unplugged")])
            return
        text = {"status": STATUS, "dbg": DBG, "inp": INP, "crash": CRASH}[command]
        if command == "status":
            text = text.replace("uptime_ms 10000", "uptime_ms " + str(10000 + i * 1000))
            text = text.replace("audio_late 7", "audio_late " + str(7 + i * 2))
            text = text.replace("usb_sof 8000", "usb_sof " + str(8000 + i * 1000))
            if i == self.malformed_at:
                text = text.replace("audio_late " + str(7 + i * 2), "audio_late -4294967296")
            if i == self.reboot_at:
                text = text.replace("boots 4", "boots 5")
            if self.status_texts is not None:
                text = self.status_texts[i]
        if command == "inp" and i == self.unequal_at:
            text = text.replace("window_ms 1000", "window_ms 1600")
        if command == "inp" and i == self.input_at:
            text = self.input_text
        text = self.command_texts.get((i, command), text)
        raw = text.encode() if command == "status" and text.startswith("status\r\n") else reply(command, text)
        self.pending.extend([raw[:2], raw[2:10], raw[10:-1], raw[-1:]])


def snapshot(status=STATUS, dbg=DBG, inp=INP, crash=CRASH):
    return {"complete": True, "commands": {
        cmd: diag.parse_response(cmd, text.encode()) for cmd, text in
        (("status", status), ("dbg", dbg), ("inp", inp), ("crash", crash))}}


# A deliberate counter removal must update this contract explicitly, not silently
# reduce the checks below. Other emitted fields remain extensible.
EXPECTED_COUNTERS = {
    "status": set("""audio_late voices_shed voices_given_up usb_resets usb_sof
        usb_suspends usb_retries usb_frame_stalls midi_rx_pkts midi_tx_pkts
        uart_rx_bytes uart_rx_msgs uart_rx_drops uac_rate_sets uac_starts
        uac_pkts uac_underruns uac_overruns uac_missed uac_stalls
        uac_adj_up uac_adj_down isr_misuse
        mul64_runs mul64_inl_bad mul64_nol_bad mul64_ref_bad""".split()),
    "dbg": {"halves", "nested", "late", "timer_irqs", "ui_frames"},
    "inp": {"timer_irqs", "nested"},
    "crash": {"count"},
}
# The parser's existing numeric contract, including optional legacy fields.
EXPECTED_NUMERIC = {command: names | additional for command, names, additional in (
    ("status", EXPECTED_COUNTERS["status"], {"boots", "uptime_ms"}),
    ("dbg", EXPECTED_COUNTERS["dbg"], {"boots", "magic"}),
    ("inp", EXPECTED_COUNTERS["inp"], {"window_ms", *LATENCY_FIELDS}),
    ("crash", EXPECTED_COUNTERS["crash"], {"uptime_ms"}),
)}
OPTIONAL_COUNTERS = {name for name in EXPECTED_COUNTERS["status"]
                     if name.startswith(("uart_", "uac_")) or name == "isr_misuse"}
# isr_misuse/isr_misuse_pc are `status` keys of FELUCCA_ISR_ASSERT=1 FM-1 builds only
# (FM1_ISR_ASSERT_TARGET); host fixtures and release builds must not emit them.
# mul64_* (FELUCCA_MUL64_REPRO=1, #425) and crash_ctx plus the crash registers (FELUCCA_CRASH_CTX=1, #428)
# are diagnostic-build keys: absent from release and standard builds.
DIAG_COUNTERS = {name for name in EXPECTED_COUNTERS["status"] if name.startswith("mul64_")}
OPTIONAL_COUNTERS |= DIAG_COUNTERS
DIAG_STATUS_KEYS = DIAG_COUNTERS | {"mul64_repro", "mul64_first_var", "mul64_first_run", "mul64_first_xor",
                                    "crash_ctx"}
CRASH_CTX_KEYS = {"ctx", "usp", "ssp"} | {f"r{i}" for i in range(16)}


class ConsoleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="felucca-console-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binaries = {}
        root = Path(__file__).resolve().parents[1]
        for features in (True, False):
            binary = Path(cls.directory.name) / ("console-full" if features else "console-minimal")
            command = shlex.split(os.environ.get("CC", "cc")) + [
                "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                "-DFELUCCA_UAC=" + str(int(features)), "-DFELUCCA_UART=" + str(int(features)),
                str(root / "tests/console_diagnostics.c"), "-o", str(binary)]
            subprocess.run(command, check=True, timeout=30)
            cls.binaries[features] = binary
        # the diagnostic build of #425/#428: FELUCCA_CRASH_CTX=1 FELUCCA_MUL64_REPRO=1
        binary = Path(cls.directory.name) / "console-diag"
        subprocess.run(shlex.split(os.environ.get("CC", "cc")) + [
            "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
            "-DFELUCCA_CRASH_CTX=1", "-DFELUCCA_MUL64_REPRO=1",
            str(root / "tests/console_diagnostics.c"), "-o", str(binary)], check=True, timeout=30)
        cls.binaries["diag"] = binary
        binary = Path(cls.directory.name) / "console-stage"
        subprocess.run(shlex.split(os.environ.get("CC", "cc")) + [
            "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
            "-DFELUCCA_RENDER_STAGE=1", str(root / "tests/console_diagnostics.c"),
            "-o", str(binary)], check=True, timeout=30)
        cls.binaries["stage"] = binary
        binary = Path(cls.directory.name) / "console-clock"
        subprocess.run(shlex.split(os.environ.get("CC", "cc")) + [
            "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
            "-DFELUCCA_BOOT_CLOCK=1", str(root / "tests/console_diagnostics.c"),
            "-o", str(binary)], check=True, timeout=30)
        cls.binaries["clock"] = binary

    def response(self, command, features=True, *arguments):
        raw = subprocess.check_output([str(self.binaries[features]), command, *arguments], timeout=5)
        self.assertTrue(raw.startswith((command + "\r\n").encode()), raw)
        self.assertTrue(raw.endswith(b"> "), raw)
        result = diag.parse_response(command, raw)
        self.assertEqual(result["issues"], [])
        return result["fields"]

    def test_counter_membership(self):
        self.assertEqual(set(diag.COMMANDS), set(EXPECTED_COUNTERS))
        self.assertEqual({command: set(names) for command, names in diag.COUNTERS.items()}, EXPECTED_COUNTERS)

    def test_boot_clock_reader(self):
        root = Path(__file__).resolve().parents[1]
        binary = Path(self.directory.name) / "boot-clock"
        subprocess.run(shlex.split(os.environ.get("CC", "cc")) + [
            "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
            str(root / "tests/boot_clock_test.c"), "-o", str(binary)],
            check=True, timeout=30)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("seven ordered reads", result.stdout)

    def test_real_boot_clock_and_older_firmware(self):
        expected = [0x10014, 0x1000C, 0x10008, 0x119A8, 0x119AC, 0x119A0, 0xFFFFFFFF]
        # FELUCCA_BOOT_CLOCK=0 (default): the firmware reports none of the fields, which is valid
        for features in (True, False):
            self.assertTrue(set(diag.CLOCK_FIELDS).isdisjoint(self.response("status", features)))
        fields = self.response("status", "clock")
        self.assertEqual([fields[key] for key in diag.CLOCK_FIELDS], expected)
        self.assertTrue(set(diag.CLOCK_FIELDS).isdisjoint(self.response("status", "clock", "no-clock")))
        self.assertEqual(diag.parse_response("status", STATUS.encode())["issues"], [])
        raw = STATUS + "".join(f"{key} 0x{value:08X}\n" for key, value in zip(diag.CLOCK_FIELDS, expected))
        self.assertEqual(diag.parse_response("status", raw.encode())["issues"], [])
        partial = raw.replace("boot_clock_119a4 0xFFFFFFFF\n", "")
        self.assertIn("missing boot_clock_119a4", diag.parse_response("status", partial.encode())["issues"])
        for invalid in ("-1", "0x100000000", "unknown", "1:2", ""):
            bad = raw.replace("boot_clock_119a4 0xFFFFFFFF", "boot_clock_119a4 " + invalid)
            self.assertIn("invalid uint32 boot_clock_119a4", diag.parse_response("status", bad.encode())["issues"])

    def test_real_console_packet_rate_epochs(self):
        def status(case):
            return subprocess.check_output([str(self.binaries[True]), "status", case], timeout=5).decode()
        before = status("uac-before")
        for case in ("uac-drop", "uac-overtake", "uac-back", "uac-same-request", "uac-stable"):
            with self.subTest(case=case):
                after = status(case)
                comparison = diag.compare(snapshot(status=before), snapshot(status=after))
                expected = "VALID" if case == "uac-stable" else "INVALID"
                self.assertEqual(comparison["validity"], expected)
                self.assertEqual(comparison["deltas"]["status"]["uac_pkts"],
                                 20 if expected == "VALID" else None)
                # A later good interval cannot repair a bad aggregate. The real
                # console bytes survive transport, JSONL and raw persistence.
                third = after.replace("uptime_ms 11000", "uptime_ms 12000")
                clock, events = Clock(), []
                transport = SessionTransport(clock, status_texts=[before, after, third])
                result = diag.collect(diag.Console(transport, 1, clock), 2, 1, {},
                                      events.append, clock, clock.sleep)
                self.assertEqual(result["validity"], expected)
                self.assertEqual(len(transport.writes), 12)
                intervals = [e for e in events if e["type"] == "interval"]
                self.assertEqual([e["validity"] for e in intervals], [expected, "VALID"])
                if expected == "INVALID":
                    self.assertTrue(all(value is None for group in result["deltas"].values()
                                        for value in group.values()))
                with tempfile.TemporaryDirectory() as tmp:
                    capture = diag.Capture(Path(tmp) / "capture")
                    for event in events:
                        capture.emit(event)
                    capture.close()
                    self.assertIn(after.encode(), (capture.directory / "console.raw").read_bytes())
                    saved = json.loads((capture.directory / "summary.json").read_text())
                    self.assertEqual(saved["validity"], expected)
                    records = [json.loads(line) for line in
                               (capture.directory / "samples.jsonl").read_text().splitlines()]
                    self.assertEqual(records[-1]["validity"], expected)

    def test_real_console_without_uac_has_no_packet_delta(self):
        raw = subprocess.check_output([str(self.binaries[False]), "status"], timeout=5).decode()
        result = diag.compare(snapshot(status=raw), snapshot(status=raw.replace("10000", "11000")))
        self.assertEqual(result["validity"], "VALID")
        self.assertIsNone(result["deltas"]["status"]["uac_pkts"])

    def test_stage_snapshot_is_optional_unsigned_and_fail_closed(self):
        fields = self.response("status", "stage")
        self.assertEqual((fields["stage_schema"], fields["stage_readable"], fields["stage_available"]), (1, 1, 1))
        self.assertEqual((fields["stage_halves"], fields["stage_blocks"], fields["stage_rejected"]), (1, 2, 0))
        expected = {"mix": 500, "empty": 5, "window": 1000, "nested": 100}
        timings = {f"stage_{name}_{kind}_t4" for name in expected for kind in ("last", "max")}
        for name, value in expected.items():
            for kind in ("last", "max"):
                self.assertEqual(fields[f"stage_{name}_{kind}_t4"], value)
        for features in (True, False, "diag"):
            self.assertFalse(any(key.startswith("stage_") for key in self.response("status", features)))
        for mode in ("stage-unsampled", "stage-error", "stage-rejected"):
            fields = self.response("status", "stage", mode)
            self.assertEqual(fields["stage_available"], 0)
            self.assertTrue(timings.isdisjoint(fields))
        rejected = self.response("status", "stage", "stage-rejected")
        self.assertEqual((rejected["stage_halves"], rejected["stage_rejected"], rejected["stage_error"]), (1, 1, 0))
        busy = self.response("status", "stage", "stage-busy")
        self.assertEqual(busy["stage_readable"], 0)
        self.assertTrue(timings.isdisjoint(busy))
        self.assertNotIn("stage_available", busy)
        # Unknown diagnostic fields retain full unsigned values and gain no
        # guessed delta semantics; the four-command collector stays unchanged.
        parsed = diag.parse_response("status", reply("status", STATUS + "stage_blocks 0xffffffff\n"))
        self.assertEqual(parsed["fields"]["stage_blocks"], 0xffffffff)
        self.assertNotIn("stage_blocks", diag.COUNTERS["status"])

    def test_real_console_counters(self):
        for command, names in EXPECTED_COUNTERS.items():
            fields = self.response(command)
            for name in names:
                if name == "isr_misuse" or name in DIAG_COUNTERS:
                    continue
                with self.subTest(command=command, counter=name):
                    self.assertIn(name, fields)
                    self.assertIs(type(fields[name]), int)
                    self.assertGreaterEqual(fields[name], 0)
                    self.assertLessEqual(fields[name], 0xFFFFFFFF)
        self.assertEqual(self.response("status").get("preset"), "BRASS ENSEMBLE")
        self.assertEqual(self.response("status").get("usb_resets"), 1)
        self.assertEqual(self.response("dbg").get("halves"), 8192)
        self.assertEqual(self.response("inp").get("window_ms"), 1000)
        for command in diag.COMMANDS:
            self.assertNotIn("isr_misuse", self.response(command))   # target-only, assert builds
            for features in (True, False):
                fields = self.response(command, features)
                self.assertTrue(DIAG_STATUS_KEYS.isdisjoint(fields))  # diagnostic builds only
                self.assertTrue(CRASH_CTX_KEYS.isdisjoint(fields))
        self.assertEqual(self.response("crash").get("count"), 2)

    def test_real_console_latency_group_is_complete_but_unsampled(self):
        values = self.response("inp")
        self.assertTrue(set(LATENCY_FIELDS) <= values.keys())
        self.assertTrue(all(type(values[key]) is int and values[key] == 0 for key in LATENCY_FIELDS))
        result = diag.input_window({"commands": {"inp": {"fields": values}}}, 1, False, True, "enabled")
        self.assertEqual(result["validity"], "VALID")
        self.assertEqual(result["latency"], "UNMEASURED")

    def test_diagnostic_build_keys(self):
        """FELUCCA_CRASH_CTX=1 / FELUCCA_MUL64_REPRO=1: the added keys, parsed and counted by the collector."""
        status = self.response("status", "diag")
        self.assertEqual(status["crash_ctx"], 1)
        self.assertEqual(status["mul64_repro"], 1)
        self.assertEqual(status["mul64_runs"], 4000000000)          # uint32 restored from con_kv's signed text
        self.assertEqual((status["mul64_inl_bad"], status["mul64_nol_bad"], status["mul64_ref_bad"]), (1, 0, 0))
        self.assertEqual((status["mul64_first_var"], status["mul64_first_run"]), (1, 1234))
        self.assertEqual(status["mul64_first_xor"], 0x00800000)
        for name in EXPECTED_COUNTERS["status"] - {"isr_misuse"}:
            self.assertIn(name, status)
        crash = self.response("crash", "diag")
        self.assertEqual((crash["count"], crash["pc"], crash["sp"]), (2, 0x02001234, 0x01C60000))
        self.assertEqual(crash["ctx"], 1)
        self.assertEqual([crash[f"r{i}"] for i in range(16)],
                         [0x00800012 if i == 5 else 0x01C60000 + i for i in range(16)])
        self.assertEqual((crash["usp"], crash["ssp"]), (0x01C40000, 0x01C7E000))
        raw = subprocess.check_output([str(self.binaries["diag"]), "crash"], timeout=5).decode()
        self.assertLess(raw.index("early "), raw.index("ctx "))     # the old keys first, unchanged
        stale = self.response("crash", "diag", "stale-ctx")
        self.assertEqual(stale["ctx"], 0)
        self.assertTrue((CRASH_CTX_KEYS - {"ctx"}).isdisjoint(stale))
        self.assertEqual(self.response("crash", "diag", "no-crash"), {"record_present": False})
        counters = "mul64_runs {}\nmul64_inl_bad {}\nmul64_nol_bad 0\nmul64_ref_bad 0\n"
        first = snapshot(status=STATUS + counters.format(10, 0))
        second = snapshot(status=STATUS.replace("uptime_ms 10000", "uptime_ms 15000") + counters.format(4010, 2))
        result = diag.compare(first, second)
        self.assertEqual(result["validity"], "VALID")
        self.assertEqual(result["deltas"]["status"]["mul64_runs"], 4000)
        self.assertEqual(result["deltas"]["status"]["mul64_inl_bad"], 2)

    def test_optional_features_absent(self):
        for command in diag.COMMANDS:
            fields = self.response(command, False)
            self.assertTrue(OPTIONAL_COUNTERS.isdisjoint(fields))
            self.assertNotIn("isr_misuse_pc", fields)
            for name in EXPECTED_COUNTERS[command] - OPTIONAL_COUNTERS:
                self.assertIn(name, fields)
            if command == "status":
                self.assertEqual(fields["uart_enabled"], 0)

    def test_real_console_without_crash(self):
        self.assertEqual(self.response("crash", True, "no-crash"), {"record_present": False})


class ParserTests(unittest.TestCase):
    def test_all_known_numeric_fields_reject_disguised_or_empty_values(self):
        texts = {"status": STATUS, "dbg": DBG, "inp": INP, "crash": CRASH}
        for command, names in EXPECTED_NUMERIC.items():
            for key in sorted(names):
                # Some optional counters are absent from the legacy fixture.
                base = re.sub(r"(?m)^" + key + r" .*\n?", "", texts[command])
                for suffix in ("", " ", "\t", " 1:2", "\t1:2", " : 1", " 1:", " 1 : 2", ": 1:2"):
                    with self.subTest(command=command, key=key, suffix=suffix):
                        parsed = diag.parse_response(command, reply(command, base + key + suffix + "\n"))
                        self.assertIn("invalid uint32 " + key, parsed["issues"])
                        self.assertIn(key, parsed["fields"])
                        self.assertNotIn(key + " 1", parsed["fields"])
                        if not suffix.strip():
                            self.assertEqual(parsed["fields"][key], "")
                            self.assertIn(key, parsed["unknown_lines"])
                        # A preceding valid record cannot hide malformed evidence.
                        duplicate = diag.parse_response(command, reply(command,
                            base + key + " 1\n" + key + suffix + "\n"))
                        self.assertIn("duplicate " + key, duplicate["issues"])
                        self.assertIn("invalid uint32 " + key, duplicate["issues"])

    def test_numeric_recognition_preserves_normalization_and_legacy_omissions(self):
        texts = {"status": STATUS, "dbg": DBG, "inp": INP, "crash": CRASH}
        required = {"status": {"uptime_ms"}, "dbg": {"magic"}, "inp": {"window_ms"},
                    "crash": {"count"}}
        for command, names in EXPECTED_NUMERIC.items():
            for key in sorted(names):
                base = re.sub(r"(?m)^" + key + r" .*\n?", "", texts[command])
                with self.subTest(command=command, key=key):
                    if key not in required[command]:
                        omitted = diag.parse_response(command, reply(command, base))
                        self.assertEqual(omitted["issues"], [])
                        self.assertNotIn(key, omitted["fields"])
                    signed = (key in EXPECTED_COUNTERS[command]
                              or command in ("status", "dbg") and key == "boots"
                              or command in ("status", "crash") and key == "uptime_ms")
                    for value in ("-2147483648", "-2147483649", "4294967295", "4294967296"):
                        parsed = diag.parse_response(command, reply(command, base + key + " " + value + "\n"))
                        valid = value == "4294967295" or signed and value == "-2147483648"
                        self.assertEqual("invalid uint32 " + key not in parsed["issues"], valid)
                        expected = 1 << 31 if signed and value == "-2147483648" else int(value)
                        self.assertEqual(parsed["fields"][key], expected)
            parsed = diag.parse_response(command, reply(command, texts[command]
                + "future_record: 1 2\nfuture_metric 1:2\nfuture_empty\n"))
            self.assertEqual(parsed["issues"], [])
            self.assertEqual(parsed["fields"]["future_record"], [1, 2])
            self.assertEqual(parsed["fields"]["future_metric 1"], [2])
            self.assertIn("future_empty", parsed["unknown_lines"])

    def test_packet_delta_requires_supported_unchanged_epoch_markers(self):
        for markers in ("", "uac_hz 44100\n", "uac_rate_sets 1\n",
                        "uac_hz 96000\nuac_rate_sets 1\n",
                        "uac_hz future-rate\nuac_rate_sets 1\n",
                        "uac_hz 1:2\nuac_rate_sets 1\n",
                        "uac_hz 44100\nuac_rate_sets 1\n",
                        "uac_hz 48000\nuac_rate_sets -2147483648\n"):
            with self.subTest(markers=markers):
                first = STATUS + "uac_pkts 100\n" + markers
                second = first.replace("uptime_ms 10000", "uptime_ms 11000").replace("uac_pkts 100", "uac_pkts 120")
                a, b = snapshot(status=first), snapshot(status=second)
                result = diag.compare(a, b)
                self.assertEqual(result["validity"], "VALID")
                known = "uac_hz 44100\nuac_rate_sets 1\n" == markers or "uac_hz 48000\n" in markers
                self.assertEqual(result["deltas"]["status"]["uac_pkts"], 20 if known else None)
                self.assertEqual(result["deltas"]["status"]["audio_late"], 0)
                # Missing markers must not conceal a directly observed decrease.
                b["commands"]["status"]["fields"]["uac_pkts"] = 20
                self.assertEqual(diag.compare(a, b)["validity"], "INVALID")
        for remove in ("uac_hz", "uac_rate_sets"):
            first = snapshot(status=STATUS + "uac_pkts 100\nuac_hz 44100\nuac_rate_sets 1\n")
            second = snapshot(status=STATUS.replace("10000", "11000") +
                              "uac_pkts 120\nuac_hz 44100\nuac_rate_sets 1\n")
            del second["commands"]["status"]["fields"][remove]
            result = diag.compare(first, second)
            self.assertEqual(result["validity"], "VALID")
            self.assertIsNone(result["deltas"]["status"]["uac_pkts"])
        for old_markers, new_markers in (("uac_hz 44100\n", "uac_hz 48000\n"),
                                         ("uac_rate_sets 1\n", "uac_rate_sets 2\n"),
                                         ("uac_hz 44100\nuac_rate_sets 1\n",
                                          "uac_hz 48000\nuac_rate_sets 1\n")):
            result = diag.compare(snapshot(status=STATUS + "uac_pkts 100\n" + old_markers),
                                  snapshot(status=STATUS.replace("10000", "11000") +
                                           "uac_pkts 120\n" + new_markers))
            self.assertEqual(result["validity"], "INVALID")
            self.assertTrue(all(value is None for group in result["deltas"].values() for value in group.values()))

    def test_rate_setter_malformed_values_invalidate_and_stop_with_raw(self):
        for suffix in ("", " ", " not-a-number", " -2147483649", " 4294967296", " 1:2", ": 1:2"):
            with self.subTest(suffix=suffix):
                first = STATUS + "uac_pkts 100\nuac_hz 44100\nuac_rate_sets 1\n"
                line = "uac_rate_sets" + suffix
                second = first.replace("10000", "11000").replace("uac_rate_sets 1", line)
                parsed = diag.parse_response("status", reply("status", second))
                self.assertIn("invalid uint32 uac_rate_sets", parsed["issues"])
                clock, events = Clock(), []
                transport = SessionTransport(clock, status_texts=[first, second])
                result = diag.collect(diag.Console(transport, 1, clock), 2, 1, {}, events.append, clock, clock.sleep)
                self.assertEqual(result["validity"], "INVALID")
                self.assertEqual(len(transport.writes), 5)
                self.assertTrue(all(value is None for group in result["deltas"].values() for value in group.values()))
                response = [e for e in events if e["type"] == "response"][-1]
                self.assertIn((line + "\r\n").encode(), base64.b64decode(response["raw_b64"]))
                with tempfile.TemporaryDirectory() as tmp:
                    capture = diag.Capture(Path(tmp) / "capture")
                    for event in events:
                        capture.emit(event)
                    capture.close()
                    self.assertIn((line + "\r\n").encode(), (capture.directory / "console.raw").read_bytes())
                    saved = json.loads((capture.directory / "summary.json").read_text())
                    self.assertEqual(saved["validity"], "INVALID")
                    self.assertFalse(saved["end_snapshot"]["complete"])

    def test_signed_uint32_normalization_rejects_values_below_int32(self):
        for command, text, name in (("status", STATUS, "audio_late"), ("status", STATUS, "uptime_ms"),
                                    ("dbg", DBG, "boots"), ("crash", CRASH, "count")):
            for value in (-(1 << 31), -(1 << 31) - 1, -(1 << 32), -(1 << 32) - 1):
                changed = re.sub(r"(?m)^" + name + r" .*$", name + " " + str(value), text)
                parsed = diag.parse_response(command, reply(command, changed))
                if value == -(1 << 31):
                    self.assertEqual(parsed["fields"][name], 1 << 31)
                    self.assertNotIn("invalid uint32 " + name, parsed["issues"])
                else:
                    self.assertEqual(parsed["fields"][name], value)
                    self.assertIn("invalid uint32 " + name, parsed["issues"])

    def test_real_console_shapes_and_unknowns(self):
        result = diag.parse_response("status", reply("status", STATUS + "future_words new value\n???\n"))
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["fields"]["preset"], "BRASS ENSEMBLE")
        self.assertEqual(result["fields"]["future_counter"], 17)
        self.assertEqual(result["fields"]["future_words"], "new value")
        self.assertIn("???", result["unknown_lines"])
        self.assertNotIn("uac_overruns", result["fields"])
        self.assertEqual(result["fields"]["uac_underruns"], 0)
        self.assertEqual(diag.parse_response("dbg", DBG.encode())["fields"]["magic"], 0x44424731)
        inp = diag.parse_response("inp", INP.encode())["fields"]
        self.assertEqual(inp["enc moves/lost/detent state"], [[4, 1, 0], [0, 0, 2]])
        self.assertEqual(inp["gap_hist <.15 .3 .6 1.2 2.4 4.8 9.6 more ms"], [9999, 1, 0, 0, 0, 0, 0, 0])
        self.assertEqual(diag.parse_response("crash", b"no crash record\r\n> ")["fields"], {"record_present": False})

    def test_signed_counter_boundary(self):
        start = snapshot(STATUS.replace("audio_late 7", "audio_late 2147483647"))
        end = snapshot(STATUS.replace("audio_late 7", "audio_late -2147483648").replace("10000", "11000"))
        result = diag.compare(start, end)
        self.assertEqual(result["validity"], "VALID")
        self.assertEqual(result["deltas"]["status"]["audio_late"], 1)

    def test_crash_core_is_optional_and_historic(self):
        self.assertNotIn("core", diag.parse_response("crash", CRASH.encode())["fields"])
        for core in (0, 1):
            crash = CRASH + f"core {core}\n"
            parsed = diag.parse_response("crash", reply("crash", crash))
            self.assertEqual(parsed["fields"]["core"], core)
            self.assertEqual(parsed["issues"], [])
            result = diag.compare(snapshot(crash=crash),
                                  snapshot(status=STATUS.replace("10000", "11000"), crash=crash))
            self.assertEqual(result["validity"], "VALID")
            self.assertNotIn("core", result["deltas"]["crash"])

    def test_reset_wrap_and_boots(self):
        start = snapshot()
        for change in (STATUS.replace("audio_late 7", "audio_late 0"),
                       STATUS.replace("boots 4", "boots 5"),
                       STATUS.replace("felucca v1.6", "felucca v1.7"),
                       STATUS.replace("uptime_ms 10000", "uptime_ms 9")):
            result = diag.compare(start, snapshot(change.replace("10000", "11000")))
            self.assertEqual(result["validity"], "INVALID")
            self.assertIsNone(result["deltas"]["status"]["audio_late"])
        start = snapshot(STATUS.replace("audio_late 7", "audio_late -1"))
        end = snapshot(STATUS.replace("audio_late 7", "audio_late 0").replace("10000", "11000"))
        self.assertIn("counter reset/wrap: status.audio_late", diag.compare(start, end)["reasons"])
        start = snapshot(STATUS.replace("uptime_ms 10000", "uptime_ms -1"))
        end = snapshot(STATUS.replace("uptime_ms 10000", "uptime_ms 0"))
        self.assertIn("uptime reset/wrap/stopped", diag.compare(start, end)["reasons"])
        end = snapshot(STATUS.replace("10000", "11000"), DBG.replace("boots 0x00000004", "boots 0x00000005"))
        self.assertIn("reboot during snapshot", diag.compare(snapshot(), end)["reasons"])

    def test_missing_and_duplicate_fields(self):
        result = diag.parse_response("status", b"felucca v1.6\r\n> ")
        self.assertIn("missing uptime_ms", result["issues"])
        self.assertIn("duplicate cpu_pct", diag.parse_response("status", (STATUS + "cpu_pct 9\n").encode())["issues"])

    def test_oversize_unknown_numeric_and_invalid_known_counter(self):
        number = "9" * 5000
        raw = reply("status", STATUS + "future_bigint " + number + "\n")
        self.assertLess(len(raw), diag.MAX_RESPONSE)
        result = diag.parse_response("status", raw)
        self.assertEqual(result["fields"]["future_bigint"], number)
        self.assertEqual(result["issues"], [])
        json.dumps(result)
        malformed = diag.parse_response("status", reply("status", STATUS.replace("audio_late 7", "audio_late " + number)))
        self.assertIn("invalid uint32 audio_late", malformed["issues"])

    def test_latency_present_metrics_reject_malformed_values(self):
        for key in LATENCY_FIELDS:
            for value in ("0", "4294967295", "0xFFFFFFFF"):
                text = re.sub(r"(?m)^" + key + r" .*", key + " " + value, INP)
                parsed = diag.parse_response("inp", text.encode())
                self.assertEqual(parsed["issues"], [])
                self.assertEqual(parsed["fields"][key], diag.scalar(value))
            for bad in ("", "not-a-number", "1.5", "-1", "-2147483648", "4294967296", "0x100000000", "9" * 5000):
                with self.subTest(key=key, bad=bad[:20]):
                    text = re.sub(r"(?m)^" + key + r" .*", key + " " + bad, INP)
                    parsed = diag.parse_response("inp", text.encode())
                    self.assertIn("invalid uint32 " + key, parsed["issues"])
                    self.assertEqual(parsed["fields"][key], diag.scalar(bad))
                    if bad == "":
                        self.assertIn(key, parsed["unknown_lines"])
                    window = diag.input_window({"commands": {"inp": parsed}}, 1, False, True, "enabled")
                    self.assertEqual(window["validity"], "INVALID")
                    self.assertEqual(window["latency"], "UNMEASURED")
        # Unknown future fields stay extensible, including strings and large integers.
        parsed = diag.parse_response("inp", (INP + "key_future_metric not-a-number\n").encode())
        self.assertEqual(parsed["issues"], [])
        self.assertEqual(parsed["fields"]["key_future_metric"], "not-a-number")

    def test_latency_missing_metrics_remain_valid_but_unmeasured(self):
        for omitted in LATENCY_FIELDS:
            text = "\n".join(line for line in INP.splitlines() if line.split(" ")[0] != omitted)
            parsed = diag.parse_response("inp", text.encode())
            self.assertEqual(parsed["issues"], [])
            window = diag.input_window({"commands": {"inp": parsed}}, 1, False, True, "enabled")
            self.assertEqual(window["validity"], "VALID")
            self.assertEqual(window["latency"], "UNMEASURED")
        legacy = "\n".join(line for line in INP.splitlines() if line.split(" ")[0] not in LATENCY_FIELDS)
        window = diag.input_window(snapshot(inp=legacy), 1, False, True, "enabled")
        self.assertEqual((window["validity"], window["latency"]), ("VALID", "UNMEASURED"))

    def test_latency_colon_values_cannot_hide_known_fields(self):
        for key in LATENCY_FIELDS:
            for suffix in (" 1:2", "\t1:2", " : 1", " 1:", " 1 : 2", ": 1:2"):
                with self.subTest(key=key, suffix=suffix):
                    text = "\n".join(key + suffix if line.startswith(key + " ") else line
                                     for line in INP.splitlines())
                    parsed = diag.parse_response("inp", reply("inp", text + "\n"))
                    self.assertIn("invalid uint32 " + key, parsed["issues"])
                    window = diag.input_window({"commands": {"inp": parsed}}, 1, False, True, "enabled")
                    self.assertEqual((window["validity"], window["latency"]), ("INVALID", "UNMEASURED"))
        # Existing multi-value colon records and future unknown names retain their shape.
        parsed = diag.parse_response("inp", reply("inp", INP + "key_future_metric 1:2\nfuture_record: 1 2\n"))
        self.assertEqual(parsed["issues"], [])
        self.assertEqual(parsed["fields"]["key_future_metric 1"], [2])
        self.assertEqual(parsed["fields"]["future_record"], [1, 2])
        self.assertEqual(parsed["fields"]["led_on_permille"], [90, 90, 90])
        self.assertEqual(parsed["fields"]["enc moves/lost/detent state"], [[4, 1, 0], [0, 0, 2]])

    def test_latency_zero_samples_are_unmeasured_not_invalid(self):
        for key in ("key_presses", "key_notes"):
            text = re.sub(r"(?m)^" + key + r" .*", key + " 0", INP)
            window = diag.input_window(snapshot(inp=text), 1, False, True, "enabled")
            self.assertEqual((window["validity"], window["latency"]), ("VALID", "UNMEASURED"))
        # Sub-microsecond observations can round to zero even with observed samples.
        text = re.sub(r"(?m)^(key_\w+_us) .*", r"\1 0", INP)
        window = diag.input_window(snapshot(inp=text), 1, False, True, "enabled")
        self.assertEqual((window["validity"], window["latency"]), ("VALID", "MEASURED"))

    def test_input_first_equal_latency_and_cumulative_fields(self):
        s = snapshot()
        self.assertEqual(diag.input_window(s, 1, True, False, "enabled")["validity"], "INVALID")
        self.assertEqual(diag.input_window(s, 1, False, True, "unknown")["latency"], "UNMEASURED")
        self.assertEqual(diag.input_window(s, 1, False, True, "enabled")["latency"], "MEASURED")
        s["commands"]["inp"]["fields"]["key_notes"] = 0
        self.assertEqual(diag.input_window(s, 1, False, True, "enabled")["latency"], "UNMEASURED")
        self.assertEqual(diag.input_window(s, 2, False, True, "enabled")["validity"], "INVALID")
        end = snapshot(STATUS.replace("10000", "11000"))
        end["commands"]["inp"]["fields"]["timer_irqs"] = 4100
        self.assertEqual(diag.compare(snapshot(), end)["deltas"]["inp"]["timer_irqs"], 4)


class TransportTests(unittest.TestCase):
    def console(self, chunks=None, responses=None):
        clock = Clock()
        return diag.Console(FakeTransport(clock, responses, chunks), timeout=1, clock=clock)

    def test_banner_echo_prompt_partial_reads(self):
        console = self.console(chunks=[b"\r\nFelucca v1.6 console - 'help'\r\n>", b" "],
                               responses={"status": [reply("status", STATUS)[:10], reply("status", STATUS)[10:-1], b" "]})
        self.assertIsNone(console.request()["error"])
        result = console.request("status")
        self.assertIsNone(result["error"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(base64.b64decode(result["raw_b64"]), reply("status", STATUS))

    def test_timeout_truncation_disconnect_and_limit(self):
        for chunks, error in (([], "timeout"), ([b"status\r\nfelucca v"], "timeout"),
                              ([b"status\r\n", OSError("gone")], "disconnect"),
                              ([b"x" * (diag.MAX_RESPONSE + 1)], "response_limit"),
                              ([KeyboardInterrupt()], "interrupted")):
            result = self.console(responses={"status": chunks}).request("status")
            self.assertTrue(result["error"].startswith(error), result)
            self.assertLessEqual(len(base64.b64decode(result["raw_b64"])), diag.MAX_RESPONSE)

    def test_strict_allowlist_and_missing_echo(self):
        console = self.console(responses={"status": [(STATUS + "> ").encode()]})
        for command in ("uboot yes", "status\ruboot yes", "params", "memr 0x1", "STATUS", "inp ", ""):
            with self.assertRaises(ValueError):
                console.request(command)
        self.assertEqual(console.transport.writes, [])
        self.assertIn("missing command echo", console.request("status")["issues"])

    def test_posix_termios_setup_and_restore_errors(self):
        import termios
        with mock.patch("os.open", return_value=97), mock.patch("os.isatty", return_value=True), \
                mock.patch("fcntl.ioctl"), mock.patch("os.close") as close, \
                mock.patch("termios.tcgetattr", side_effect=termios.error("setup unplug")):
            with self.assertRaisesRegex(OSError, "setup failed"):
                diag.PosixSerial("fake tty")
            close.assert_called_once_with(97)
        transport = diag.PosixSerial.__new__(diag.PosixSerial)
        transport.fd, transport.saved = 97, [0] * 7
        with mock.patch("termios.tcsetattr", side_effect=termios.error("restore unplug")), \
                mock.patch("os.close") as close:
            self.assertIn("restoration failed", transport.close())
            close.assert_called_once_with(97)

    def test_posix_pseudo_tty_roundtrip_and_restore(self):
        import os
        import pty
        import termios
        import threading
        master, slave = pty.openpty()
        transport = None
        try:
            # Pseudo ttys have no modem-control lines; all data uses real OS I/O.
            with mock.patch("fcntl.ioctl"):
                transport = diag.PosixSerial(os.ttyname(slave))
            original = transport.saved
            console = diag.Console(transport, timeout=1)
            os.write(master, b"\r\nFelucca v1.6 console - 'help'\r\n> ")
            self.assertIsNone(console.request()["error"])
            received = []
            def peer():
                command = b""
                while not command.endswith(b"\r"):
                    command += os.read(master, 128)
                received.append(command)
                os.write(master, reply("status", STATUS))
            thread = threading.Thread(target=peer, daemon=True)
            thread.start()
            result = console.request("status")
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(received, [b"status\r"])
            self.assertEqual(result["issues"], [])
            self.assertIsNone(result["error"])
            self.assertIsNone(transport.close())
            transport = None
            restored = termios.tcgetattr(slave)
            # Darwin may set its pending-input retype flag when canonical mode returns.
            restored[3] &= ~getattr(termios, "PENDIN", 0)
            original[3] &= ~getattr(termios, "PENDIN", 0)
            self.assertEqual(restored, original)
        finally:
            if transport:
                transport.close()
            os.close(master)
            os.close(slave)


class SessionTests(unittest.TestCase):
    def run_session(self, input_latency="unknown", **kwargs):
        clock, events = Clock(), []
        transport = SessionTransport(clock, **kwargs)
        console = diag.Console(transport, timeout=1, clock=clock)
        summary = diag.collect(console, 2, 1, {"scenario": "simulated", "input_latency": input_latency},
                               events.append, clock=clock, sleep=clock.sleep)
        return summary, events, transport

    def test_malformed_known_scalars_stop_and_persist_invalid_session(self):
        cases = (("status", "audio_late", STATUS), ("status", "boots", STATUS),
                 ("status", "uptime_ms", STATUS), ("dbg", "halves", DBG),
                 ("dbg", "magic", DBG), ("inp", "timer_irqs", INP),
                 ("inp", "window_ms", INP), ("crash", "count", CRASH),
                 ("crash", "uptime_ms", CRASH))
        for command, key, text in cases:
            for index in (1, 2):
                for suffix in (" 1:2", ""):
                    with self.subTest(command=command, key=key, index=index, suffix=suffix):
                        line = key + suffix
                        bad = re.sub(r"(?m)^" + key + r" .*$", line, text)
                        summary, events, transport = self.run_session(
                            command_texts={(index, command): bad})
                        self.assertEqual(summary["validity"], "INVALID")
                        self.assertFalse(summary["end_snapshot"]["complete"])
                        self.assertTrue(all(value is None for group in summary["deltas"].values()
                                            for value in group.values()))
                        self.assertEqual(len(transport.writes), index * 4 + diag.COMMANDS.index(command) + 1)
                        response = [e for e in events if e["type"] == "response"][-1]
                        self.assertIn("invalid uint32 " + key, response["issues"])
                        malformed_bytes = (line + "\r\n").encode()
                        self.assertIn(malformed_bytes, base64.b64decode(response["raw_b64"]))
                        intervals = [e for e in events if e["type"] == "interval"]
                        self.assertEqual(intervals[-1]["validity"], "INVALID")
                        with tempfile.TemporaryDirectory() as tmp:
                            capture = diag.Capture(Path(tmp) / "capture")
                            for event in events:
                                capture.emit(event)
                            capture.close()
                            raw = (capture.directory / "console.raw").read_bytes()
                            self.assertIn(malformed_bytes, raw)
                            saved = json.loads((capture.directory / "summary.json").read_text())
                            self.assertEqual(saved, summary)
                            samples = [json.loads(item) for item in
                                       (capture.directory / "samples.jsonl").read_text().splitlines()]
                            saved_response = [e for e in samples if e["type"] == "response"][-1]
                            offset, length = saved_response["raw_offset"], saved_response["raw_length"]
                            self.assertEqual(raw[offset:offset + length], base64.b64decode(response["raw_b64"]))
                            self.assertEqual(saved_response["fields"][key], "1:2" if suffix else "")

    def test_invalid_latency_invalidates_session_and_preserves_evidence(self):
        for instrumentation in ("enabled", "unknown", "disabled"):
            bad = INP.replace("key_noteon_avg_us 1900", "key_noteon_avg_us not-a-number")
            summary, events, transport = self.run_session(input_at=1, input_text=bad, input_latency=instrumentation)
            self.assertEqual(summary["validity"], "INVALID")
            self.assertIsNone(summary["deltas"]["status"]["audio_late"])
            self.assertFalse(summary["end_snapshot"]["complete"])
            self.assertEqual(summary["end_snapshot"]["input_window"]["latency"], "UNMEASURED")
            self.assertEqual(len(transport.writes), 7)
            response = [e for e in events if e["type"] == "response"][-1]
            self.assertIn("invalid uint32 key_noteon_avg_us", response["issues"])
            self.assertIn(b"key_noteon_avg_us not-a-number", base64.b64decode(response["raw_b64"]))
            # The actual writer keeps raw bytes, parsed values and invalid summary.
            with tempfile.TemporaryDirectory() as tmp:
                capture = diag.Capture(Path(tmp) / "capture")
                for event in events:
                    capture.emit(event)
                capture.close()
                self.assertIn(b"key_noteon_avg_us not-a-number", (capture.directory / "console.raw").read_bytes())
                saved = json.loads((capture.directory / "summary.json").read_text())
                self.assertEqual(saved["validity"], "INVALID")
                self.assertEqual(saved["end_snapshot"]["commands"]["inp"]["fields"]["key_noteon_avg_us"], "not-a-number")

    def test_empty_latency_value_invalidates_session_not_legacy_absence(self):
        for suffix in ("", " ", "\t"):
            bad = INP.replace("key_press_max_us 1300", "key_press_max_us" + suffix)
            summary, events, transport = self.run_session(input_at=1, input_text=bad, input_latency="enabled")
            self.assertEqual(summary["validity"], "INVALID")
            self.assertIsNone(summary["deltas"]["status"]["audio_late"])
            self.assertFalse(summary["end_snapshot"]["complete"])
            self.assertEqual(summary["end_snapshot"]["input_window"]["latency"], "UNMEASURED")
            self.assertEqual(len(transport.writes), 7)
            response = [e for e in events if e["type"] == "response"][-1]
            self.assertIn("invalid uint32 key_press_max_us", response["issues"])
            self.assertEqual(response["fields"]["key_press_max_us"], "")
            self.assertIn("key_press_max_us", response["unknown_lines"])
            self.assertIn(("key_press_max_us" + suffix + "\r\n").encode(), base64.b64decode(response["raw_b64"]))
        parsed = diag.parse_response("inp", (INP + "key_future_empty\n").encode())
        self.assertEqual(parsed["issues"], [])
        self.assertIn("key_future_empty", parsed["unknown_lines"])

    def test_colon_latency_value_invalidates_session_and_preserves_raw(self):
        for suffix in (" 1:2", "\t1:2", " : 1", " 1:", " 1 : 2", ": 1:2"):
            with self.subTest(suffix=suffix):
                line = "key_press_max_us" + suffix
                bad = INP.replace("key_press_max_us 1300", line)
                summary, events, transport = self.run_session(input_at=1, input_text=bad, input_latency="enabled")
                self.assertEqual(summary["validity"], "INVALID")
                self.assertTrue(all(value is None for group in summary["deltas"].values() for value in group.values()))
                self.assertFalse(summary["end_snapshot"]["complete"])
                self.assertEqual(summary["end_snapshot"]["input_window"]["latency"], "UNMEASURED")
                self.assertEqual(len(transport.writes), 7)
                response = [e for e in events if e["type"] == "response"][-1]
                self.assertIn("invalid uint32 key_press_max_us", response["issues"])
                self.assertIn((line + "\r\n").encode(), base64.b64decode(response["raw_b64"]))

    def test_partial_legacy_latency_keeps_continuous_session_unmeasured(self):
        old = "\n".join(line for line in INP.splitlines()
                        if line.split(" ")[0] not in {"key_press_max_us", "key_noteon_max_us", "key_dac_avg_us"}) + "\n"
        summary, events, _ = self.run_session(input_at=1, input_text=old, input_latency="enabled")
        self.assertEqual(summary["validity"], "VALID")
        self.assertEqual(summary["deltas"]["status"]["audio_late"], 4)
        windows = [e["input_window"] for e in events if e["type"] == "snapshot"]
        self.assertEqual([w["latency"] for w in windows], ["UNMEASURED", "UNMEASURED", "MEASURED"])
        self.assertEqual([w["validity"] for w in windows], ["INVALID", "VALID", "VALID"])

    def test_malformed_signed_counter_invalidates_session_and_preserves_raw(self):
        summary, events, transport = self.run_session(malformed_at=1)
        self.assertEqual(summary["validity"], "INVALID")
        self.assertIsNone(summary["deltas"]["status"]["audio_late"])
        self.assertFalse(summary["end_snapshot"]["complete"])
        self.assertEqual(len(transport.writes), 5)
        response = [e for e in events if e["type"] == "response"][-1]
        self.assertIn("invalid uint32 audio_late", response["issues"])
        self.assertIn(b"audio_late -4294967296", base64.b64decode(response["raw_b64"]))

    def test_deterministic_session_and_raw_artifacts(self):
        summary, events, transport = self.run_session()
        self.assertEqual(summary["validity"], "VALID")
        self.assertEqual(summary["deltas"]["status"]["audio_late"], 4)
        self.assertEqual(summary["deltas"]["status"]["usb_sof"], 2000)
        self.assertIsNone(summary["deltas"]["status"]["uac_overruns"])
        self.assertEqual(summary["start_snapshot"]["commands"]["crash"]["fields"]["uptime_ms"], 50)
        self.assertEqual(summary["intervals"], 2)
        self.assertEqual(summary["device_versions"], ["v1.6"])
        self.assertEqual(transport.writes, [cmd.encode() + b"\r" for cmd in diag.COMMANDS] * 3)
        snapshots = [e for e in events if e["type"] == "snapshot"]
        self.assertEqual([s["input_window"]["validity"] for s in snapshots], ["INVALID", "VALID", "VALID"])
        self.assertTrue(all(s["input_window"]["latency"] == "UNMEASURED" for s in snapshots))
        self.assertEqual(summary["end_snapshot"]["commands"]["status"]["fields"]["audio_max_us"], 900)
        with tempfile.TemporaryDirectory() as tmp:
            capture = diag.Capture(Path(tmp) / "capture")
            for event in events:
                capture.emit(event)
            capture.close()
            raw = (capture.directory / "console.raw").read_bytes()
            saved = [json.loads(line) for line in (capture.directory / "samples.jsonl").read_text().splitlines()]
            for event in saved:
                if "raw_b64" in event:
                    self.assertEqual(raw[event["raw_offset"]:event["raw_offset"] + event["raw_length"]],
                                     base64.b64decode(event["raw_b64"]))
            self.assertEqual(json.loads((capture.directory / "summary.json").read_text())["validity"], "VALID")

    def test_interrupted_interval_retains_partial_and_stops(self):
        summary, events, transport = self.run_session(interrupt_at=1)
        self.assertEqual(summary["validity"], "INVALID")
        self.assertIsNone(summary["deltas"]["status"]["audio_late"])
        self.assertFalse(summary["end_snapshot"]["complete"])
        self.assertEqual(len(transport.writes), 6)
        failed = [e for e in events if e["type"] == "response" and e["error"]]
        self.assertIn("magic 0x44424731", failed[0]["raw_text"])

    def test_intervening_reboot_never_restores_aggregate_validity(self):
        summary, events, _ = self.run_session(reboot_at=1)
        self.assertEqual(summary["validity"], "INVALID")
        self.assertIsNone(summary["deltas"]["status"]["usb_sof"])
        self.assertEqual([e["validity"] for e in events if e["type"] == "interval"], ["INVALID", "INVALID"])

    def test_unequal_input_window_rejected(self):
        summary, _, _ = self.run_session(unequal_at=1)
        self.assertEqual(summary["validity"], "INVALID")
        self.assertEqual(summary["input_windows"]["invalid"], 1)

    def test_startup_failure_has_summary(self):
        clock, events = Clock(), []
        console = diag.Console(FakeTransport(clock), 1, clock)
        summary = diag.collect(console, 2, 1, {}, events.append, clock, clock.sleep)
        self.assertEqual(summary["validity"], "INVALID")
        self.assertIsNone(summary["start_snapshot"])
        self.assertEqual(events[-1]["type"], "summary")

    def test_long_numeric_session_retains_raw_and_summary(self):
        number = "9" * 5000
        for known in (False, True):
            clock, events = Clock(), []
            transport = SessionTransport(clock)
            original_write = transport.write
            def write(data, timeout):
                original_write(data, timeout)
                if data == b"status\r":
                    text = STATUS.replace("audio_late 7", "audio_late " + number) if known else STATUS + "future_bigint " + number + "\n"
                    text = text.replace("uptime_ms 10000", "uptime_ms " + str(10000 + transport.index * 1000))
                    transport.pending = [reply("status", text)]
            transport.write = write
            summary = diag.collect(diag.Console(transport, 1, clock), 2, 1, {}, events.append, clock, clock.sleep)
            self.assertEqual(summary["validity"], "INVALID" if known else "VALID")
            self.assertTrue(any(number in e.get("raw_text", "") for e in events))
            self.assertEqual(events[-1]["type"], "summary")
            json.dumps(events)

    def test_keyboard_interrupt_between_snapshots(self):
        clock, events = Clock(), []
        console = diag.Console(SessionTransport(clock), 1, clock)
        def sleep(amount):
            if amount > 0:
                raise KeyboardInterrupt()
        summary = diag.collect(console, 2, 1, {}, events.append, clock, sleep)
        self.assertEqual(summary["validity"], "INVALID")
        self.assertIn("interrupted", summary["reasons"])
        self.assertTrue(summary["start_snapshot"]["complete"])

    def test_cli_rejects_bad_bounds_paths_and_command_options(self):
        base = ["--port", "fake tty", "--scenario", "simulated"]
        for extra in (["--duration", "nan"], ["--interval", "0"], ["--duration", "3", "--interval", "2"],
                      ["--timeout", "31"], ["--interval", "121"], ["--output", "/tmp/outside-build"],
                      ["--command", "uboot yes"]):
            with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as raised:
                diag.main(base + extra)
            self.assertEqual(raised.exception.code, 2)

    def test_cli_setup_restore_failure_and_explicit_provenance(self):
        build = Path(__file__).resolve().parents[1] / "build"
        build.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build) as tmp:
            directory = Path(tmp) / "capture"
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text('{"revision": "explicit-device-build", "FM1_INPUT_LAT": 0}')
            args = ["--port", "fake tty", "--scenario", "simulated", "--duration", "2", "--interval", "1",
                    "--output", str(directory), "--manifest", str(manifest),
                    "--firmware-revision", "explicit-device-build"]
            with mock.patch.object(diag, "PosixSerial", side_effect=OSError("tty setup failed")), \
                    mock.patch("builtins.print"):
                self.assertEqual(diag.main(args), 1)
            summary = json.loads((directory / "summary.json").read_text())
            self.assertEqual(summary["validity"], "INVALID")
            self.assertEqual(summary["metadata"]["supplied_firmware_revision"], "explicit-device-build")
            self.assertEqual(summary["metadata"]["input_latency"], "unknown")
            self.assertEqual(summary["metadata"]["build_manifest"]["FM1_INPUT_LAT"], 0)
            self.assertNotIn("local_revision", summary["metadata"])
            args[args.index(str(directory))] = str(Path(tmp) / "restore")
            fake = mock.Mock()
            fake.close.return_value = "CDC tty restoration failed"
            with mock.patch.object(diag, "PosixSerial", return_value=fake), \
                    mock.patch.object(diag, "collect", return_value={"type": "summary", "validity": "VALID", "reasons": []}), \
                    mock.patch("builtins.print"):
                self.assertEqual(diag.main(args), 1)
            saved = json.loads((Path(tmp) / "restore" / "summary.json").read_text())
            self.assertIn("CDC tty restoration failed", saved["reasons"])
            self.assertIsNone(saved["deltas"]["status"]["audio_late"])


if __name__ == "__main__":
    unittest.main()
