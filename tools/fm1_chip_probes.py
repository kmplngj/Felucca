#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Explicit stopped developer probes; requires the default-off diagnostic image.

Select the CDC tty yourself. This client only sends `probe caps` and `probe run`;
it does not alter transport/settings, upload code, flash or convert ticks to cycles.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
import time

from fm1_diagnostics import PosixSerial

PROMPT = re.compile(rb"(?:^|\r\n)> $")
CAPS = re.compile(r"PROBE CAPS version=1 reps=256 passes=2 kinds=9 footprint=1024 limit_ticks=2400000 irq=enabled clock=unavailable commit=([0-9a-f]{40})")
SAMPLE = re.compile(r"PROBE SAMPLE kind=([0-8]) pass=([01]) ticks=([0-9A-F]{8}) checksum=([0-9A-F]{8}) reference=([0-9A-F]{8})")
MAX_RESPONSE = 8192


class Console:
    def __init__(self, transport, raw, timeout=2, clock=time.monotonic):
        self.transport, self.raw, self.timeout, self.clock = transport, raw, timeout, clock

    def request(self, command=None):
        if command not in (None, "probe caps", "probe run"):
            raise ValueError("command outside chip-probe allowlist")
        received = bytearray()
        deadline = self.clock() + self.timeout
        if command:
            self.transport.write((command + "\r").encode("ascii"), self.timeout)
        while True:
            left = deadline - self.clock()
            if left <= 0:
                raise TimeoutError("probe reply timed out")
            data = self.transport.read(left)
            if data is None:
                continue
            self.raw.write(data)
            self.raw.flush()
            received.extend(data)
            if len(received) > MAX_RESPONSE:
                raise ValueError("probe reply exceeded byte limit")
            if PROMPT.search(received):
                break
        lines = received.decode("ascii").replace("\r", "").split("\n")
        if lines[-1] != "> ":
            raise ValueError("invalid probe prompt")
        lines = [line for line in lines[:-1] if line]
        if command is None:
            if len(lines) != 1 or not re.fullmatch(r"Felucca [ -~]+ console - 'help'", lines[0]):
                raise ValueError("unexpected startup; reconnect the selected tty")
            return []
        if not lines or lines[0] != command:
            raise ValueError("missing or unexpected probe command echo")
        return lines[1:]


def expected_checksums():
    mask = 0xFFFFFFFF
    a = 12345
    for i in range(256):
        a = ((((a + i) & mask) * 679 & mask) // 679) ^ 0xA5A5A5A5
    values = [0, 256, a]
    for stride in (1, 8, 32):
        values.append(sum(((i * stride % 256) * 0x9E3779B9 + 0x01234567) & mask
                          for i in range(256)) & mask)
    return values + values[3:]


def parse_samples(lines):
    if len(lines) != 20 or lines[0] != "PROBE BEGIN version=1" or lines[-1] != "PROBE END complete":
        raise ValueError("incomplete or refused probe run: " + "; ".join(lines[:1]))
    samples = []
    expected = expected_checksums()
    for i, line in enumerate(lines[1:-1]):
        match = SAMPLE.fullmatch(line)
        if not match:
            raise ValueError("malformed probe sample")
        kind, sample_pass = int(match[1]), int(match[2])
        ticks, checksum, reference = (int(match[j], 16) for j in (3, 4, 5))
        if (kind, sample_pass) != divmod(i, 2) or checksum != reference or checksum != expected[kind]:
            raise ValueError("probe order/reference mismatch")
        samples.append({"kind": kind, "pass": sample_pass, "raw_timer4_ticks": ticks,
                        "checksum": checksum, "reference": reference})
    return samples


def main(argv=None, transport_factory=PosixSerial):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--firmware-revision", required=True, help="full installed image source commit; operator supplied")
    parser.add_argument("--manifest", type=Path, required=True, help="JSON build/artifact provenance supplied by operator")
    parser.add_argument("--runs", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--output", type=Path, help="new directory inside this checkout's build/")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.firmware_revision):
        parser.error("firmware revision must be a full lowercase commit hash")
    build = (Path(__file__).resolve().parents[1] / "build").resolve()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = args.output.resolve() if args.output else build / "chip-probes" / stamp
    if build not in directory.parents:
        parser.error("output must be a new directory inside this checkout's build/")
    try:
        manifest_raw = args.manifest.read_bytes()
        manifest = json.loads(manifest_raw)
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
        directory.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    summary = {"complete": False, "runs": [], "host": platform.platform(), "port": args.port,
               "created_utc": stamp, "supplied_firmware_revision": args.firmware_revision,
               "manifest": manifest, "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
               "provenance": "operator supplied; device/artifact identity not independently verified",
               "clock_identity": "unavailable", "irq": "enabled", "errors": []}
    transport = None
    try:
        with (directory / "console.raw").open("wb") as raw:
            transport = transport_factory(args.port)
            console = Console(transport, raw)
            console.request()
            caps = console.request("probe caps")
            match = CAPS.fullmatch(caps[0]) if len(caps) == 1 else None
            if not match or match[1] != args.firmware_revision:
                raise ValueError("missing/unexpected probe capability or source revision")
            summary["device_caps"] = caps[0]
            for _ in range(args.runs):
                summary["runs"].append(parse_samples(console.request("probe run")))
            summary["complete"] = True
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        summary["errors"].append(str(exc) or "interrupted")
    finally:
        if transport:
            try:
                error = transport.close()
                if error:
                    summary["errors"].append(error)
            except OSError as exc:
                summary["errors"].append(str(exc))
        if summary["errors"]:
            summary["complete"] = False
        path = directory / "summary.json"
        path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(str(path) + (": COMPLETE" if summary["complete"] else ": INVALID"))
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
