#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Capture supported, stopped/static FM-1 HOME or MENU pixels over an explicitly selected CDC tty.

This reads firmware-rendered RGB565 pixels, not the physical LCD or its colours.
Explicit --wake silently wakes and holds the display for this bounded capture.
It never navigates the panel, changes settings/transport/sound or flashes firmware.
"""
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import time
import zlib

from fm1_diagnostics import PosixSerial

WIDTH, HEIGHT, BAND, MAX_READ = 240, 240, 3840, 96
TOTAL = WIDTH * HEIGHT * 2
SOURCE = "github.com/kmplngj/Felucca"
MAX_REPLY = 4096
PROMPT = re.compile(rb"(?:^|\r?\n)> ")
STATES = {"waking", "pending", "ready", "complete", "changed", "expired", "cancelled", "coverage", "asleep", "unsupported"}


class ProtocolError(ValueError):
    pass


def number(value, maximum=0xFFFFFFFF):
    if not re.fullmatch(r"0|[1-9][0-9]{0,9}", value) or int(value) > maximum:
        raise ProtocolError("invalid decimal field")
    return int(value)


def checksum(value):
    if not re.fullmatch(r"[0-9A-F]{8}", value):
        raise ProtocolError("invalid CRC/hash field")
    return int(value, 16)


def record(line):
    words = line.split(" ")
    if len(words) < 3 or words[0] != "SCAP" or words[1] not in {"CAPS", "STATE", "DATA", "ERROR"}:
        raise ProtocolError("unexpected screenshot record")
    fields = {}
    for word in words[2:]:
        if not re.fullmatch(r"[a-z_]+=[!-~]+", word):
            raise ProtocolError("malformed screenshot field")
        key, value = word.split("=", 1)
        if key in fields:
            raise ProtocolError("duplicate screenshot field: " + key)
        fields[key] = value
    return words[1], fields


def exact(fields, names):
    if fields.keys() != set(names.split()):
        raise ProtocolError("missing or unexpected screenshot fields")


class Console:
    """Strict request/echo/prompt binding; a framing error ends this serial session."""
    def __init__(self, transport, timeout=2.0, duration=110.0, clock=time.monotonic, sleep=time.sleep):
        self.transport, self.timeout, self.clock, self.sleep = transport, timeout, clock, sleep
        self.deadline = clock() + duration
        self.synchronized = True
        self.first = True

    def remaining(self):
        left = self.deadline - self.clock()
        if left <= 0:
            raise TimeoutError("screenshot overall deadline exceeded")
        return left

    def request(self, command, retry_busy=True):
        if not re.fullmatch(r"screen (caps|begin(?: wake)?|(?:status|cancel) [0-9]+|next [0-9]+ [0-9]+|read [0-9]+ [0-9]+ [0-9]+)", command):
            raise ProtocolError("command outside screenshot allowlist")
        while True:
            self.remaining()
            if not self.synchronized:
                raise ProtocolError("serial framing was lost")
            deadline = min(self.deadline, self.clock() + self.timeout)
            raw = bytearray()
            self.synchronized = False
            self.transport.write((command + "\r").encode("ascii"), max(0, deadline - self.clock()))
            while True:
                left = deadline - self.clock()
                if left <= 0:
                    raise TimeoutError("screenshot command timed out: " + command)
                data = self.transport.read(left)
                if data is None:
                    continue
                raw.extend(data)
                if len(raw) > MAX_REPLY:
                    raise ProtocolError("screenshot reply limit exceeded")
                match = PROMPT.search(raw)
                if match:
                    # Opening DTR may produce an initial prompt before the command echo.
                    if self.first and (not raw[:match.start()].strip(b"\r\n") or re.fullmatch(
                            rb"Felucca [ -~]+ console - 'help'", raw[:match.start()].strip(b"\r\n"))):
                        if match.end() == len(raw):
                            continue
                        match = PROMPT.search(raw, match.end())
                        if match is None:
                            continue
                    if match.end() != len(raw):
                        raise ProtocolError("unexpected bytes after screenshot prompt")
                    break
            try:
                lines = bytes(raw).decode("ascii").replace("\r", "").split("\n")
            except UnicodeDecodeError as exc:
                raise ProtocolError("non-ASCII screenshot reply") from exc
            lines = [line for line in lines if line and line != "> "]
            if self.first:
                lines = [line for line in lines if not re.fullmatch(r"Felucca [ -~]+ console - 'help'", line)]
            if len(lines) != 2 or lines[0] not in (command, "> " + command):
                raise ProtocolError("unexpected screenshot echo or reply framing")
            self.first = False
            self.synchronized = True
            kind, fields = record(lines[1])
            if kind != "ERROR":
                return kind, fields
            exact(fields, "code")
            if fields["code"] != "busy" or not retry_busy:
                raise ProtocolError("device screenshot error: " + fields["code"])
            self.sleep(min(0.02, self.remaining()))


def capabilities(reply, expected_commit=None):
    kind, f = reply
    if kind != "CAPS":
        raise ProtocolError("expected screenshot capabilities")
    if f == {"version": "1", "enabled": "0"}:
        raise ProtocolError("device screenshot feature is disabled")
    exact(f, "version enabled width height format band_bytes max_read ttl_ms build commit dirty source mode scr_state led_stage idle_ms")
    if f["version"] not in {"1", "2"} or any(f[k] != v for k, v in {"enabled": "1", "width": "240", "height": "240",
                                "format": "RGB565BE", "band_bytes": "3840", "max_read": "96",
                                "source": SOURCE, "mode": "stopped-static"}.items()):
        raise ProtocolError("unsupported or unexpected screenshot device/capability")
    if not re.fullmatch(r"[0-9a-f]{40}", f["commit"]) or f["build"] != f["commit"][:8] + ("-dirty" if f["dirty"] == "1" else "") or f["dirty"] not in {"0", "1"}:
        raise ProtocolError("missing or invalid device build provenance")
    if expected_commit and f["commit"] != expected_commit:
        raise ProtocolError("device commit differs from --expect-commit")
    if number(f["ttl_ms"]) != 120000:
        raise ProtocolError("unsupported screenshot TTL")
    diagnostics(f)
    return dict(f)


def diagnostics(fields):
    if number(fields["scr_state"]) > 4 or number(fields["led_stage"]) > 3:
        raise ProtocolError("invalid screenshot power diagnostics")
    number(fields["idle_ms"])


def state(reply, token=None, offset=None, scene=None, allow_waking=False):
    kind, f = reply
    if kind != "STATE":
        raise ProtocolError("expected screenshot state")
    exact(f, "token state offset length draw_hash awake page home menu scr_state led_stage idle_ms")
    s = {key: number(f[key]) for key in ("token", "offset", "length", "awake", "page", "home", "menu")}
    diagnostics(f)
    s.update({key: number(f[key]) for key in ("scr_state", "led_stage", "idle_ms")})
    s["state"], s["draw_hash"] = f["state"], checksum(f["draw_hash"])
    if not s["token"] or s["state"] not in STATES or s["awake"] > 1 or any(s[k] > 255 for k in ("page", "home", "menu")):
        raise ProtocolError("invalid screenshot state")
    if token is not None and s["token"] != token:
        raise ProtocolError("stale screenshot token")
    if s["state"] not in {"pending", "ready", "complete", "cancelled"} and not (allow_waking and s["state"] == "waking"):
        raise ProtocolError("device capture stopped: " + s["state"])
    expected_length = 0 if s["state"] in {"waking", "complete", "cancelled"} else BAND
    if s["length"] != expected_length or s["offset"] > TOTAL or s["offset"] % BAND:
        raise ProtocolError("invalid screenshot band extent")
    if s["state"] == "complete" and s["offset"] != TOTAL:
        raise ProtocolError("premature screenshot completion")
    if offset is not None and s["offset"] != offset:
        raise ProtocolError("out-of-order screenshot band")
    if s["state"] not in {"waking", "cancelled"} and (s["awake"] != 1 or not (s["menu"] in {1, 2, 4} or (s["menu"] == 0 and s["home"] == 1))):
        raise ProtocolError("unexpected or sleeping device scene")
    if s["state"] == "waking" and (s["awake"] != 0 or s["offset"] != 0 or s["draw_hash"] != 0 or
                                    not (s["menu"] in {1, 2, 4} or (s["menu"] == 0 and s["home"] == 1))):
        raise ProtocolError("unexpected waking device scene")
    if scene is not None and any(s[k] != scene[k] for k in ("page", "home", "menu")):
        raise ProtocolError("device scene changed during screenshot")
    return s


def chunk(reply, token, offset, length):
    kind, f = reply
    if kind != "DATA":
        raise ProtocolError("expected screenshot data")
    exact(f, "token offset length crc data")
    if number(f["token"]) != token or number(f["offset"]) != offset or number(f["length"]) != length:
        raise ProtocolError("stale or out-of-order screenshot chunk")
    if not re.fullmatch(r"[0-9A-F]{" + str(length * 2) + "}", f["data"]):
        raise ProtocolError("malformed screenshot pixel bytes")
    data = bytes.fromhex(f["data"])
    if zlib.crc32(data) != checksum(f["crc"]):
        raise ProtocolError("screenshot chunk CRC mismatch")
    return data


def capture(console, expected_commit=None, wake=False):
    caps = capabilities(console.request("screen caps"), expected_commit)
    if wake and caps["version"] != "2":
        raise ProtocolError("device firmware does not support --wake (screenshot protocol 2 required)")
    token, image, draw_hash = None, bytearray(), None
    try:
        begun = console.request("screen begin wake" if wake else "screen begin", retry_busy=False)
        if begun[0] == "STATE" and "token" in begun[1]:
            candidate = number(begun[1]["token"])
            if candidate:
                token = candidate
        current = state(begun, token, offset=0, allow_waking=wake)
        if current["state"] not in ({"pending", "waking"} if wake else {"pending"}) or current["draw_hash"] != 0:
            raise ProtocolError("unexpected initial screenshot state")
        token, scene = current["token"], current
        while current["state"] == "waking":
            console.sleep(min(0.02, console.remaining()))
            current = state(console.request(f"screen status {token}"), token, 0, scene, allow_waking=True)
        scene = current
        for offset in range(0, TOTAL, BAND):
            if draw_hash is not None and current["draw_hash"] != draw_hash:
                raise ProtocolError("incoherent screenshot draw hash")
            while current["state"] == "pending":
                console.sleep(min(0.02, console.remaining()))
                current = state(console.request(f"screen status {token}"), token, offset, scene)
            if current["state"] != "ready":
                raise ProtocolError("screenshot band was not ready")
            if draw_hash is None:
                draw_hash = current["draw_hash"]
            elif current["draw_hash"] != draw_hash:
                raise ProtocolError("incoherent screenshot draw hash")
            for at in range(offset, offset + BAND, MAX_READ):
                length = min(MAX_READ, offset + BAND - at)
                image.extend(chunk(console.request(f"screen read {token} {at} {length}"), token, at, length))
            current = state(console.request(f"screen next {token} {offset + BAND}"), token, offset + BAND, scene)
        if current["state"] != "complete" or current["draw_hash"] != draw_hash or len(image) != TOTAL:
            raise ProtocolError("incomplete or incoherent screenshot")
        final_caps = capabilities(console.request("screen caps"), expected_commit)
        if any(final_caps[k] != caps[k] for k in caps.keys() - {"scr_state", "led_stage", "idle_ms"}):
            raise ProtocolError("device identity changed during screenshot")
        # Live state is the last content acceptance operation, after identity verification.
        final = state(console.request(f"screen status {token}"), token, TOTAL, scene)
        if any(final[k] != current[k] for k in ("token", "state", "offset", "length", "draw_hash", "awake", "page", "home", "menu")):
            raise ProtocolError("screenshot final state changed")
        result = bytes(image), {"device": caps, "capture": final, "scene": {k: scene[k] for k in ("awake", "page", "home", "menu")},
                                "final_diagnostics": {k: final[k] for k in ("scr_state", "led_stage", "idle_ms")},
                                "wake_requested": wake,
                                "pixel_crc32": f"{zlib.crc32(image):08X}", "pixel_sha256": hashlib.sha256(image).hexdigest()}
    finally:
        # Never send another command after a timeout/lost framing; firmware TTL releases its small buffer.
        if token is not None and console.synchronized:
            # Preserve a bounded cleanup opportunity after the capture deadline/interruption.
            console.deadline = max(console.deadline, console.clock() + min(console.timeout, 2.0))
            cancelled = state(console.request(f"screen cancel {token}", retry_busy=False), token)
            if cancelled["state"] != "cancelled":
                raise ProtocolError("screenshot cancellation was not acknowledged")
    return result


def png(rgb565):
    if len(rgb565) != TOTAL:
        raise ProtocolError("PNG requires a complete 240x240 RGB565 image")
    raw = bytearray()
    for y in range(HEIGHT):
        raw.append(0)
        for x in range(WIDTH):
            at = (y * WIDTH + x) * 2
            p = (rgb565[at] << 8) | rgb565[at + 1]
            r, g, b = p >> 11, (p >> 5) & 63, p & 31
            raw.extend(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)))
    def block(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + block(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)) + block(b"IDAT", zlib.compress(raw)) + block(b"IEND", b"")


def publish(directory, pixels, metadata):
    """Publish one complete PNG/JSON directory, cleaning staging files on every failure."""
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError("screenshot output already exists")
    encoded = png(pixels)
    metadata = dict(metadata, format_version=1, width=WIDTH, height=HEIGHT, pixel_format="RGB565BE",
                    png_sha256=hashlib.sha256(encoded).hexdigest(),
                    evidence="Firmware-rendered intended pixels; not optical LCD/controller/backlight verification.")
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".screenshot-", dir=directory.parent))
    try:
        (staging / "screen.png").write_bytes(encoded)
        (staging / "screen.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if directory.exists():
            raise FileExistsError("screenshot output appeared during capture")
        staging.rename(directory)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv=None, transport_factory=PosixSerial):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="explicit CDC tty; never selected automatically")
    parser.add_argument("--output", type=Path, help="new directory inside this checkout's ignored build/")
    parser.add_argument("--timeout", type=float, default=2.0, help="per-command timeout, seconds (maximum 10)")
    parser.add_argument("--duration", type=float, default=110.0, help="capture deadline, seconds (maximum 115; cleanup at most 2 more)")
    parser.add_argument("--expect-commit", help="required exact device-reported 40-character commit")
    parser.add_argument("--wake", action="store_true", help="silently wake, await redraw and hold awake for this capture (protocol 2 firmware)")
    args = parser.parse_args(argv)
    if not all(math.isfinite(v) and 0 < v <= limit for v, limit in ((args.timeout, 10), (args.duration, 115))):
        parser.error("timeouts must be positive finite seconds within their limits")
    if args.expect_commit and not re.fullmatch(r"[0-9a-f]{40}", args.expect_commit):
        parser.error("--expect-commit must be a lowercase full commit SHA")
    build = (Path(__file__).resolve().parents[1] / "build").resolve()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = args.output.resolve() if args.output else build / "screenshots" / stamp
    if build not in output.parents:
        parser.error("output must be a new directory inside this checkout's ignored build/")
    if output.exists():
        parser.error("output directory already exists")
    transport, result, error = None, None, None
    try:
        transport = transport_factory(args.port)
        result = capture(Console(transport, args.timeout, args.duration), args.expect_commit, wake=args.wake)
    except (OSError, ValueError, ImportError, KeyboardInterrupt) as exc:
        error = str(exc) or "interrupted"
    finally:
        if transport:
            close_error = transport.close()
            if close_error:
                error = close_error
    if error:
        print("Screenshot failed: " + error, file=sys.stderr)
        return 1
    pixels, metadata = result
    metadata.update(created_utc=stamp, port=args.port, timeout_s=args.timeout, duration_s=args.duration)
    try:
        publish(output, pixels, metadata)
    except (OSError, ValueError) as exc:
        print("Screenshot failed: " + str(exc), file=sys.stderr)
        return 1
    print(str(output / "screen.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
