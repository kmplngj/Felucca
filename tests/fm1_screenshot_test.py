#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Screenshot CLI protocol/PNG/failure regressions with simulated serial only."""
import contextlib
import io
import json
import re
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fm1_screenshot as shot

COMMIT = "12345678" + "a" * 32
CAPS = ("SCAP CAPS version=1 enabled=1 width=240 height=240 format=RGB565BE band_bytes=3840 "
        "max_read=96 ttl_ms=120000 build=12345678 commit=" + COMMIT +
        " dirty=0 source=github.com/kmplngj/Felucca mode=stopped-static scr_state=0 led_stage=0 idle_ms=100")
PIXELS = (bytes.fromhex("F80007E0001FFFFF0000") * (shot.TOTAL // 10))


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def sleep(self, duration): self.now += duration


class Device:
    def __init__(self, fault=None, fragmented=False):
        self.clock, self.fault = Clock(), fault
        self.fragmented, self.writes, self.pending = fragmented, [], []
        self.offset, self.caps_calls, self.cancelled = 0, 0, False
        self.close_error = None
        self.closed = False
        self.ready_polls = 0

    def state(self, status, offset=None):
        offset = self.offset if offset is None else offset
        length = 3840 if status in {"pending", "ready"} else 0
        return (f"SCAP STATE token=7 state={status} offset={offset} length={length} "
                "draw_hash=1234ABCD awake=1 page=3 home=0 menu=1 scr_state=0 led_stage=0 idle_ms=100")

    def response(self, cmd):
        fields = cmd.split()
        if cmd == "screen caps":
            self.caps_calls += 1
            return CAPS
        if cmd == "screen begin":
            return self.state("pending").replace("draw_hash=1234ABCD", "draw_hash=00000000")
        if fields[1] == "status":
            return self.state("complete" if self.offset == shot.TOTAL else "ready")
        if fields[1] == "next":
            self.offset = int(fields[3])
            return self.state("complete" if self.offset == shot.TOTAL else "pending")
        if fields[1] == "cancel":
            self.cancelled = True
            return self.state("cancelled")
        if fields[1] == "read":
            at, count = int(fields[3]), int(fields[4])
            data = PIXELS[at:at + count]
            return (f"SCAP DATA token=7 offset={at} length={count} crc={zlib.crc32(data):08X} data={data.hex().upper()}")
        raise AssertionError("unexpected command: " + cmd)

    def write(self, raw, timeout):
        self.writes.append(raw)
        cmd = raw.decode().rstrip("\r")
        reply = self.response(cmd)
        if self.fault:
            reply = self.fault(self, cmd, reply)
        if isinstance(reply, BaseException):
            self.pending.append(reply)
            return
        if reply is None:
            return
        response = (cmd + "\r\n" + reply + "\r\n> ").encode()
        if len(self.writes) == 1:
            response = b"\r\nFelucca v1.6 console - 'help'\r\n> " + response
        if self.fragmented:
            self.pending.extend([response[:1], response[1:19], response[19:-1], response[-1:]])
        else:
            self.pending.append(response)

    def read(self, timeout):
        if self.pending:
            value = self.pending.pop(0)
            if isinstance(value, BaseException): raise value
            self.clock.sleep(0.0001)
            return value
        self.clock.sleep(timeout)
        return None

    def close(self):
        self.closed = True
        return self.close_error


def console(device, duration=110):
    return shot.Console(device, clock=device.clock, sleep=device.clock.sleep, duration=duration)


def first_read(change):
    fired = False
    def fault(device, cmd, reply):
        nonlocal fired
        if cmd.startswith("screen read") and not fired:
            fired = True
            return change(reply)
        return reply
    return fault


class CaptureTests(unittest.TestCase):
    def test_complete_fragmented_capture_and_allowlist(self):
        device = Device(fragmented=True)
        pixels, meta = shot.capture(console(device), COMMIT)
        self.assertEqual(pixels, PIXELS)
        self.assertEqual(meta["device"]["commit"], COMMIT)
        self.assertEqual(meta["pixel_crc32"], f"{zlib.crc32(PIXELS):08X}")
        self.assertEqual(meta["capture"]["offset"], shot.TOTAL)
        self.assertTrue(device.cancelled)
        commands = [w.decode().strip() for w in device.writes]
        self.assertEqual(sum(x.startswith("screen read") for x in commands), 1200)
        self.assertIn("screen next 7 115200", commands)
        self.assertEqual(commands[-3:], ["screen caps", "screen status 7", "screen cancel 7"])
        self.assertTrue(all(x.startswith("screen ") for x in commands))

    def test_caps_reject_before_begin(self):
        changes = [lambda r: r.replace("enabled=1", "enabled=0"),
                   lambda r: r.replace("version=1", "version=2"),
                   lambda r: r.replace("width=240", "width=241"),
                   lambda r: r.replace("max_read=96", "max_read=999"),
                   lambda r: r.replace("commit=" + COMMIT, "commit=unknown"),
                   lambda r: r.replace("source=github.com/kmplngj/Felucca", "source=other"),
                   lambda r: r + " injected=1", lambda r: r.replace("dirty=0", "dirty=2")]
        for change in changes:
            with self.subTest(change=change):
                dev = Device(lambda d, c, r: change(r) if c == "screen caps" else r)
                with self.assertRaises(shot.ProtocolError): shot.capture(console(dev))
                self.assertEqual(len(dev.writes), 1)
        dev = Device()
        with self.assertRaisesRegex(shot.ProtocolError, "expect-commit"):
            shot.capture(console(dev), "b" * 40)
        self.assertEqual(len(dev.writes), 1)

    def test_disabled_caps_terminal_begin_and_dynamic_diagnostics(self):
        dev = Device(lambda d, c, r: "SCAP CAPS version=1 enabled=0" if c == "screen caps" else r)
        with self.assertRaisesRegex(shot.ProtocolError, "disabled"): shot.capture(console(dev))
        self.assertEqual(len(dev.writes), 1)
        dev = Device(lambda d, c, r: d.state("asleep").replace("awake=1", "awake=0") if c == "screen begin" else r)
        with self.assertRaisesRegex(shot.ProtocolError, "asleep"): shot.capture(console(dev))
        self.assertTrue(dev.cancelled)
        dirty = Device(lambda d, c, r: r.replace("dirty=0", "dirty=1").replace("build=12345678", "build=12345678-dirty") if c == "screen caps" else r)
        self.assertEqual(shot.capture(console(dirty))[1]["device"]["build"], "12345678-dirty")
        def dynamic(d, c, r):
            return re.sub(r"idle_ms=[0-9]+", "idle_ms=" + str(len(d.writes)), r)
        dev = Device(dynamic)
        pixels, metadata = shot.capture(console(dev))
        self.assertEqual(pixels, PIXELS)
        self.assertNotEqual(metadata["device"]["idle_ms"], metadata["final_diagnostics"]["idle_ms"])

    def test_chunk_corruption_and_stale_or_reordered_fields(self):
        changes = [lambda r: r.replace("token=7", "token=8"),
                   lambda r: r.replace("offset=0", "offset=96"),
                   lambda r: r.replace("length=96", "length=95"),
                   lambda r: r.replace(" crc=", " token=7 crc="),
                   lambda r: r.replace("data=F", "data=f"),
                   lambda r: r[:-2],
                   lambda r: r.replace("crc=", "crc=00000000", 1),
                   lambda r: r + " extra=1"]
        for change in changes:
            with self.subTest(change=change):
                dev = Device(first_read(change))
                with self.assertRaises(shot.ProtocolError): shot.capture(console(dev))
                self.assertTrue(dev.cancelled)

    def test_unsigned_bounds_and_interrupted_pending_cleanup(self):
        for invalid in ["-1", "00", "4294967296", "1e2", "9" * 1000]:
            with self.subTest(invalid=invalid), self.assertRaises(shot.ProtocolError): shot.number(invalid)
        self.assertEqual(shot.number("4294967295"), 0xFFFFFFFF)
        dev = Device()
        fields = shot.record(dev.state("ready").replace("token=7", "token=4294967295").replace("idle_ms=100", "idle_ms=4294967295"))
        self.assertEqual(shot.state(fields)["token"], 0xFFFFFFFF)
        session = console(dev)
        session.sleep = lambda amount: (_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt): shot.capture(session)
        self.assertTrue(dev.cancelled)

    def test_real_crc_mismatch(self):
        dev = Device(first_read(lambda r: r.replace(r.split("crc=")[1][:8], "00000000", 1)))
        with self.assertRaisesRegex(shot.ProtocolError, "CRC mismatch"): shot.capture(console(dev))
        self.assertTrue(dev.cancelled)

    def test_scene_hash_and_completion_changes(self):
        for replacement in ["page=4", "awake=0", "menu=3", "draw_hash=99999999", "token=8", "offset=0"]:
            def fault(d, cmd, reply):
                if cmd == "screen next 7 3840":
                    key = replacement.split("=")[0]
                    return re.sub(key + r"=[^ ]+", replacement, reply)
                return reply
            dev = Device(fault)
            with self.subTest(replacement=replacement), self.assertRaises(shot.ProtocolError):
                shot.capture(console(dev))
        for status in ["changed", "coverage", "expired", "asleep", "unsupported"]:
            dev = Device(lambda d, c, r: d.state(status) if c.startswith("screen status") else r)
            with self.subTest(status=status), self.assertRaises(shot.ProtocolError): shot.capture(console(dev))
        dev = Device(lambda d, c, r: d.state("complete", 0) if c == "screen begin" else r)
        with self.assertRaises(shot.ProtocolError): shot.capture(console(dev))

    def test_identity_change_and_final_confirmation_are_checked(self):
        dev = Device(lambda d, c, r: r.replace("dirty=0", "dirty=1").replace("build=12345678", "build=12345678-dirty") if c == "screen caps" and d.caps_calls == 2 else r)
        with self.assertRaisesRegex(shot.ProtocolError, "identity changed"): shot.capture(console(dev))
        dev = Device(lambda d, c, r: r.replace("draw_hash=1234ABCD", "draw_hash=00000000")
                     if c == "screen status 7" and d.offset == shot.TOTAL else r)
        with self.assertRaisesRegex(shot.ProtocolError, "final state changed"): shot.capture(console(dev))

    def test_capture_becoming_unsupported_after_final_caps_never_publishes(self):
        def start_after_caps(device, cmd, reply):
            if cmd == "screen status 7" and device.caps_calls == 2:
                return device.state("unsupported")
            return reply
        dev = Device(start_after_caps)
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            out = Path(tmp) / "must-not-exist"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(shot.main(["--port", "/explicit/mock", "--output", str(out)], lambda port: dev), 1)
            self.assertFalse(out.exists())
            self.assertTrue(dev.cancelled)
            self.assertTrue(dev.closed)
            commands = [w.decode().strip() for w in dev.writes]
            self.assertEqual(commands[-3:], ["screen caps", "screen status 7", "screen cancel 7"])

    def test_busy_retries_and_bounded_pending(self):
        dev = Device(first_read(lambda r: "SCAP ERROR code=busy"))
        self.assertEqual(shot.capture(console(dev))[0], PIXELS)
        dev = Device(lambda d, c, r: d.state("pending") if c.startswith("screen status") else r)
        with self.assertRaises(TimeoutError): shot.capture(console(dev, duration=0.1))
        self.assertLess(dev.clock(), 1)
        self.assertTrue(dev.cancelled)
        dev = Device(lambda d, c, r: "SCAP ERROR code=busy" if c == "screen begin" else r)
        with self.assertRaisesRegex(shot.ProtocolError, "busy"): shot.capture(console(dev))
        self.assertEqual(len(dev.writes), 2)  # Never cancels another caller's existing session.

    def test_timeout_disconnect_and_framing_failures_stop_requests(self):
        for fault in [lambda r: None, lambda r: OSError("unplugged"), lambda r: KeyboardInterrupt(),
                      lambda r: "SCAP DATA " + "x" * 5000]:
            dev = Device(first_read(fault))
            with self.subTest(fault=fault), self.assertRaises((OSError, ValueError, KeyboardInterrupt)):
                shot.capture(console(dev))
            self.assertFalse(dev.cancelled)
        for raw in [b"other\r\nSCAP ERROR code=busy\r\n> ",
                    b"screen caps\r\n" + CAPS.encode() + b"\r\n> junk",
                    b"screen caps\r\n" + CAPS.encode() + b"\r\n" + CAPS.encode() + b"\r\n> "]:
            dev = Device()
            dev.write = lambda data, timeout: dev.pending.append(raw)
            with self.subTest(raw=raw[:30]), self.assertRaises(shot.ProtocolError):
                shot.capture(console(dev))


class OutputTests(unittest.TestCase):
    def test_png_decodes_expected_rgb_and_crc(self):
        encoded, at, compressed = shot.png(PIXELS), 8, bytearray()
        self.assertEqual(encoded[:8], b"\x89PNG\r\n\x1a\n")
        kinds = []
        while at < len(encoded):
            n = struct.unpack_from(">I", encoded, at)[0]
            kind, data = encoded[at + 4:at + 8], encoded[at + 8:at + 8 + n]
            self.assertEqual(struct.unpack_from(">I", encoded, at + n + 8)[0], zlib.crc32(kind + data))
            kinds.append(kind)
            if kind == b"IHDR": self.assertEqual(struct.unpack(">IIBBBBB", data), (240, 240, 8, 2, 0, 0, 0))
            if kind == b"IDAT": compressed.extend(data)
            at += n + 12
        self.assertEqual(kinds, [b"IHDR", b"IDAT", b"IEND"])
        rgb = zlib.decompress(compressed)
        self.assertEqual(len(rgb), 240 * (1 + 240 * 3))
        self.assertEqual(rgb[:16], b"\0" + bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255, 0, 0, 0]))
        with self.assertRaises(shot.ProtocolError): shot.png(PIXELS[:-1])

    def test_publish_cleanup_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "capture"
            with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")):
                with self.assertRaises(OSError): shot.publish(out, PIXELS, {})
            self.assertEqual(list(Path(tmp).iterdir()), [])
            shot.publish(out, PIXELS, {"device": {"commit": COMMIT}})
            self.assertEqual({p.name for p in out.iterdir()}, {"screen.png", "screen.json"})
            self.assertIn("not optical", json.loads((out / "screen.json").read_text())["evidence"])
            original = (out / "screen.png").read_bytes()
            with self.assertRaises(FileExistsError): shot.publish(out, PIXELS, {})
            self.assertEqual((out / "screen.png").read_bytes(), original)

    def test_cli_explicit_port_and_publish_only_after_close(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): shot.main([])
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            out, dev = Path(tmp) / "capture", Device()
            def factory(port):
                self.assertEqual(port, "/explicit/mock")
                return dev
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(shot.main(["--port", "/explicit/mock", "--output", str(out)], factory), 0)
            self.assertTrue(dev.closed)
            self.assertTrue(out.is_dir())
            dev = Device(); dev.close_error = "restoration failed"
            out = Path(tmp) / "failed"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(shot.main(["--port", "/explicit/mock", "--output", str(out)], factory), 1)
            self.assertFalse(out.exists())
            dev = Device(first_read(lambda r: OSError("disconnected")))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(shot.main(["--port", "/explicit/mock", "--output", str(out)], factory), 1)
            self.assertTrue(dev.closed)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
