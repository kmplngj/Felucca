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
key_notes 2
key_noteon_avg_us 1900
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
    def __init__(self, clock, interrupt_at=None, reboot_at=None, unequal_at=None, malformed_at=None):
        super().__init__(clock, chunks=[b"\r\nFelucca v1.6 console - 'help'\r\n> "])
        self.index = -1
        self.interrupt_at, self.reboot_at, self.unequal_at = interrupt_at, reboot_at, unequal_at
        self.malformed_at = malformed_at

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
        if command == "inp" and i == self.unequal_at:
            text = text.replace("window_ms 1000", "window_ms 1600")
        raw = reply(command, text)
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
        uac_adj_up uac_adj_down isr_misuse lcd_faults lcd_recoveries
        mul64_runs mul64_inl_bad mul64_nol_bad mul64_ref_bad""".split()),
    "dbg": {"halves", "nested", "late", "timer_irqs", "ui_frames"},
    "inp": {"timer_irqs", "nested"},
    "crash": {"count"},
}
OPTIONAL_COUNTERS = {name for name in EXPECTED_COUNTERS["status"]
                     if name.startswith(("uart_", "uac_", "lcd_")) or name == "isr_misuse"}
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

    def response(self, command, features=True, *arguments):
        raw = subprocess.check_output([str(self.binaries[features]), command, *arguments], timeout=5)
        self.assertTrue(raw.startswith((command + "\r\n").encode()), raw)
        self.assertTrue(raw.endswith(b"> "), raw)
        result = diag.parse_response(command, raw)
        self.assertEqual(result["issues"], [])
        return result["fields"]

    def test_lcd_failure_fields(self):
        status = self.response("status")
        self.assertEqual((status["lcd_fault"], status["lcd_owned"]), (1, 1))
        self.assertEqual(status["lcd_faults"], 4000000000)
        self.assertEqual(status["lcd_recoveries"], 3)

    def test_lcd_counter_deltas_and_older_firmware(self):
        start = snapshot(status=STATUS + "lcd_faults 2\nlcd_recoveries 1\n")
        end = snapshot(status=STATUS.replace("uptime_ms 10000", "uptime_ms 15000") +
                       "lcd_faults 5\nlcd_recoveries 3\n")
        result = diag.compare(start, end)
        self.assertEqual(result["deltas"]["status"]["lcd_faults"], 3)
        self.assertEqual(result["deltas"]["status"]["lcd_recoveries"], 2)
        self.assertEqual(diag.parse_response("status", reply("status", STATUS))["issues"], [])

    def test_counter_membership(self):
        self.assertEqual(set(diag.COMMANDS), set(EXPECTED_COUNTERS))
        self.assertEqual({command: set(names) for command, names in diag.COUNTERS.items()}, EXPECTED_COUNTERS)

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
    def run_session(self, **kwargs):
        clock, events = Clock(), []
        transport = SessionTransport(clock, **kwargs)
        console = diag.Console(transport, timeout=1, clock=clock)
        summary = diag.collect(console, 2, 1, {"scenario": "simulated", "input_latency": "unknown"},
                               events.append, clock=clock, sleep=clock.sleep)
        return summary, events, transport

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
