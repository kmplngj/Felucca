#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Collect existing Felucca CDC diagnostics. No MIDI or firmware changes."""
import argparse
import base64
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import select
import sys
import time

COMMANDS = ("status", "dbg", "inp", "crash")
MAX_RESPONSE = 65536
CLOCK_FIELDS = tuple("boot_clock_" + address for address in
                     ("10014", "1000c", "10008", "119a8", "119ac", "119a0", "119a4"))
PROMPT = re.compile(rb"(?:^|\n)> $")
COUNTERS = {
    "status": ("audio_late", "voices_shed", "voices_given_up", "usb_resets", "usb_sof",
               "usb_suspends", "usb_retries", "usb_frame_stalls", "midi_rx_pkts", "midi_tx_pkts",
               "uart_rx_bytes", "uart_rx_msgs", "uart_rx_drops", "uac_rate_sets", "uac_starts",
               "uac_pkts", "uac_underruns", "uac_overruns", "uac_missed", "uac_stalls",
               "uac_adj_up", "uac_adj_down", "isr_misuse",
               "mul64_runs", "mul64_inl_bad", "mul64_nol_bad", "mul64_ref_bad"),
    "dbg": ("halves", "nested", "late", "timer_irqs", "ui_frames"),
    "inp": ("timer_irqs", "nested"),
    "crash": ("count",),
}
SEMANTICS = {
    "cpu_pct": "Smoothed render/deadline ratio; excludes nested TIMER5 scan and main loop, not whole-chip CPU.",
    "maxima": "audio_max_us / dbg.max_us are cumulative maxima and may survive reset; never interval maxima.",
    "inp": "Reset on read except timer_irqs/nested; first window discarded; later windows checked against interval.",
    "latency": "Requires explicit confirmation of FM1_INPUT_LAT and observed key samples; otherwise UNMEASURED.",
    "snapshots": "Commands and fields are read sequentially, not an atomic device snapshot.",
    "boot_clock": "Optional seven raw clock words captured once at this boot, before normal initialization; "
                  "not live clock readings or measured MHz. Absent on older/CDC-disabled firmware.",
}


class PosixSerial:
    """Exclusive raw CDC tty; firmware ignores baud rate. No automatic port discovery."""
    def __init__(self, port):
        import array
        import fcntl
        import termios
        import tty
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.saved = None
        try:
            if not os.isatty(self.fd):
                raise OSError("selected port is not a tty")
            # Opening fails if another collector owns the tty; do not share the command stream.
            fcntl.ioctl(self.fd, termios.TIOCEXCL)
            self.saved = termios.tcgetattr(self.fd)
            tty.setraw(self.fd, termios.TCSANOW)
            attrs = termios.tcgetattr(self.fd)
            attrs[2] |= termios.CLOCAL | termios.CREAD
            attrs[2] &= ~getattr(termios, "CRTSCTS", 0)
            attrs[4] = attrs[5] = termios.B115200
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
            fcntl.ioctl(self.fd, termios.TIOCMBIS, array.array("i", [termios.TIOCM_DTR]))
        except BaseException as exc:
            self.close()
            if isinstance(exc, termios.error):
                raise OSError("CDC tty setup failed: " + str(exc)) from exc
            raise

    def read(self, timeout):
        if not select.select([self.fd], [], [], max(0, timeout))[0]:
            return None
        try:
            data = os.read(self.fd, 4096)
        except BlockingIOError:
            return None
        if not data:
            raise OSError("CDC port disconnected")
        return data

    def write(self, data, timeout):
        deadline = time.monotonic() + timeout
        while data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise TimeoutError("CDC write timed out")
            try:
                sent = os.write(self.fd, data)
            except BlockingIOError:
                continue
            if not sent:
                raise OSError("CDC write disconnected")
            data = data[sent:]

    def close(self):
        import termios
        error = None
        try:
            if self.saved is not None:
                termios.tcsetattr(self.fd, termios.TCSANOW, self.saved)
        except (OSError, termios.error) as exc:
            error = "CDC tty restoration failed: " + str(exc)
        finally:
            os.close(self.fd)
        return error


def scalar(value):
    if re.fullmatch(r"-?\d+|0[xX][0-9a-fA-F]+", value):
        # Unknown future fields can contain arbitrarily long decimal strings.
        # Bound conversion independently of Python's version-specific int limit,
        # while preserving the original value and all raw bytes.
        if len(value) <= 128:
            try:
                return int(value, 16 if value.lower().startswith("0x") else 10)
            except ValueError:
                pass
    return value


def parse_response(command, raw):
    """Keep extensible fields and verbatim unknown lines; never invent missing zeros."""
    fields, extra, duplicates = {}, [], []
    for line in raw.decode("utf-8", errors="replace").replace("\r", "").split("\n"):
        line = line.strip()
        if not line or line in (command, ">", "> " + command):
            continue
        if re.match(r"Felucca .* console - 'help'$", line):
            extra.append(line)
            continue
        if line == "no crash record":
            fields["record_present"] = False
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            if key == "enc moves/lost/detent state":
                value = [[scalar(v) for v in item.split("/")] for item in value.split()]
            else:
                value = [scalar(v) for v in value.split()]
        else:
            match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*) (.+)", line)
            if not match:
                extra.append(line)
                continue
            key, value = match.groups()
            value = scalar(value)
        if key in fields:
            duplicates.append(key)
        fields[key] = value
    if command == "crash" and "count" in fields:
        fields["record_present"] = True
    # con_kv prints uint32 counters as signed decimal. Restore their unsigned units,
    # so crossing INT32_MAX is continuous, but actual uint32 wrap remains invalid.
    unsigned = set(COUNTERS.get(command, ()))
    if command in ("status", "dbg"):
        unsigned.add("boots")
    if command in ("status", "crash"):
        unsigned.add("uptime_ms")
    for key in unsigned:
        # Reject values below the formatter's int32 range rather than turning
        # malformed input such as -2**32 into an apparently supported zero.
        if isinstance(fields.get(key), int) and -(1 << 31) <= fields[key] < 0:
            fields[key] += 1 << 32
    required = {"status": ("felucca", "uptime_ms"), "dbg": ("magic",),
                "inp": ("window_ms",), "crash": ("record_present",)}[command]
    issues = ["missing " + key for key in required if key not in fields]
    numeric = set(COUNTERS.get(command, ()))
    if command in ("status", "dbg"):
        numeric.add("boots")
    numeric |= {"status": {"uptime_ms"}, "dbg": {"magic"}, "inp": {"window_ms"},
                "crash": {"uptime_ms"}}[command]
    if command == "status":
        numeric.update(CLOCK_FIELDS)
        if set(CLOCK_FIELDS) & fields.keys():
            issues += ["missing " + key for key in CLOCK_FIELDS if key not in fields]
    for key in numeric & fields.keys():
        value = fields[key]
        if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
            issues.append("invalid uint32 " + key)
    issues += ["duplicate " + key for key in duplicates]
    return {"fields": fields, "unknown_lines": extra, "issues": issues}


class Console:
    def __init__(self, transport, timeout=2.0, clock=time.monotonic):
        self.transport, self.timeout, self.clock = transport, timeout, clock

    def request(self, command=None):
        if command is not None and command not in COMMANDS:
            raise ValueError("command is outside the diagnostic allowlist")
        started, raw, error = self.clock(), bytearray(), None
        deadline = started + self.timeout
        try:
            if command is not None:
                self.transport.write((command + "\r").encode("ascii"), self.timeout)
            while True:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    error = "timeout"
                    break
                data = self.transport.read(remaining)
                if data is None:
                    continue
                if len(raw) + len(data) > MAX_RESPONSE:
                    raw.extend(data[:MAX_RESPONSE - len(raw)])
                    error = "response_limit"
                    break
                raw.extend(data)
                if PROMPT.search(raw):
                    break
        except KeyboardInterrupt:
            error = "interrupted"
        except OSError as exc:
            error = "disconnect: " + str(exc)
        result = {"type": "response" if command else "startup", "command": command,
                  "started_mono_s": started, "ended_mono_s": self.clock(),
                  "error": error, "raw_b64": base64.b64encode(raw).decode("ascii"),
                  "raw_text": raw.decode("utf-8", errors="replace")}
        if command:
            result.update(parse_response(command, raw))
            # Exact echoed command binds a response to its request. Stop on framing
            # errors rather than letting a late response contaminate the next command.
            lines = raw.decode("ascii", errors="replace").replace("\r", "").split("\n")
            if not any(line in (command, "> " + command) for line in lines):
                result["issues"].append("missing command echo")
        return result


def fields(snapshot, command):
    return snapshot.get("commands", {}).get(command, {}).get("fields", {})


def compare(start, end):
    """Invalidate every cumulative delta across a reset, wrap or incomplete snapshot."""
    reasons = []
    for snapshot in (start, end):
        if not snapshot["complete"]:
            reasons.append("incomplete snapshot")
        status_boots = fields(snapshot, "status").get("boots")
        dbg_boots = fields(snapshot, "dbg").get("boots")
        if dbg_boots is not None and status_boots != dbg_boots:
            reasons.append("reboot during snapshot")
    a, b = fields(start, "status"), fields(end, "status")
    for key in ("felucca", "boots"):
        if key not in a or key not in b:
            reasons.append("continuity unavailable: " + key)
        elif a[key] != b[key]:
            reasons.append("device changed: " + key)
    if not isinstance(a.get("uptime_ms"), int) or not isinstance(b.get("uptime_ms"), int):
        reasons.append("uptime unavailable")
    elif b["uptime_ms"] <= a["uptime_ms"]:
        reasons.append("uptime reset/wrap/stopped")
    deltas = {}
    for command, keys in COUNTERS.items():
        old, new = fields(start, command), fields(end, command)
        deltas[command] = {}
        for key in keys:
            x, y = old.get(key), new.get(key)
            if isinstance(x, int) and isinstance(y, int):
                if y < x:
                    reasons.append("counter reset/wrap: " + command + "." + key)
                deltas[command][key] = y - x
            else:
                deltas[command][key] = None
    if reasons:
        deltas = {cmd: {key: None for key in keys} for cmd, keys in COUNTERS.items()}
    return {"validity": "INVALID" if reasons else "VALID", "reasons": sorted(set(reasons)),
            "deltas": deltas}


def input_window(snapshot, interval, first, continuous, latency):
    response = snapshot["commands"].get("inp", {})
    values = response.get("fields", {})
    reasons = []
    if first:
        reasons.append("first reset-on-read window discarded")
    if not continuous:
        reasons.append("discontinuous interval")
    if response.get("error") or response.get("issues") or not response:
        reasons.append("incomplete input response")
    window = values.get("window_ms")
    if not isinstance(window, int) or abs(window - interval * 1000) > max(20, interval * 50):
        reasons.append("unequal input window")
    presses, notes = values.get("key_presses"), values.get("key_notes")
    measured = latency == "enabled" and isinstance(presses, int) and presses > 0 and isinstance(notes, int) and notes > 0
    return {"validity": "INVALID" if reasons else "VALID", "reasons": reasons,
            "latency": "MEASURED" if measured and not reasons else "UNMEASURED",
            "instrumentation_supplied": latency, "fields": values}


def collect(console, duration, interval, metadata, emit, clock=time.monotonic, sleep=time.sleep):
    emit({"type": "session", "schema": 1, "metadata": metadata, "semantics": SEMANTICS})
    first = last = previous = None
    valid = True
    interval_count = 0
    error = None
    input_valid = input_invalid = 0
    versions = []
    started = clock()
    startup = console.request()
    emit(startup)
    if startup["error"]:
        error = startup["error"]
    else:
        anchor = clock()
        for index in range(round(duration / interval) + 1):
            try:
                sleep(max(0, anchor + index * interval - clock()))
            except KeyboardInterrupt:
                error = "interrupted"
                valid = False
                break
            snapshot = {"type": "snapshot", "index": index, "started_mono_s": clock(),
                        "commands": {}, "complete": True}
            for command in COMMANDS:
                response = console.request(command)
                emit(response)
                snapshot["commands"][command] = {k: v for k, v in response.items()
                                                if k not in ("raw_b64", "raw_text", "type")}
                if response["error"] or response["issues"]:
                    snapshot["complete"] = False
                    error = response["error"] or "; ".join(response["issues"])
                    break
            snapshot["ended_mono_s"] = clock()
            comparison = compare(previous, snapshot) if previous else None
            continuous = comparison is not None and comparison["validity"] == "VALID"
            snapshot["input_window"] = input_window(snapshot, interval, previous is None, continuous,
                                                     metadata.get("input_latency", "unknown"))
            version = fields(snapshot, "status").get("felucca")
            if version is not None and version not in versions:
                versions.append(version)
            if previous is not None:
                if snapshot["input_window"]["validity"] == "VALID":
                    input_valid += 1
                else:
                    input_invalid += 1
            emit(snapshot)
            if comparison:
                elapsed = snapshot["started_mono_s"] - previous["started_mono_s"]
                if abs(elapsed - interval) > max(0.02, interval * 0.05):
                    comparison["reasons"].append("unequal host sampling interval")
                if snapshot["input_window"]["validity"] != "VALID":
                    comparison["reasons"] += snapshot["input_window"]["reasons"]
                if comparison["reasons"]:
                    comparison["validity"] = "INVALID"
                    comparison["deltas"] = {cmd: {key: None for key in keys} for cmd, keys in COUNTERS.items()}
                comparison.update(type="interval", start_index=previous["index"], end_index=index,
                                  elapsed_s=elapsed)
                emit(comparison)
                valid = valid and comparison["validity"] == "VALID"
                interval_count += 1
            if first is None:
                first = snapshot
            last = previous = snapshot
            if error:
                valid = False
                break
    summary = compare(first, last) if first and last and interval_count else {
        "validity": "INVALID", "reasons": ["no complete measurement interval"], "deltas": {}}
    if not valid or error:
        summary["validity"] = "INVALID"
        summary["reasons"].append(error or "one or more intervening intervals invalid")
        summary["deltas"] = {cmd: {key: None for key in keys} for cmd, keys in COUNTERS.items()}
    summary.update(type="summary", metadata=metadata, semantics=SEMANTICS,
                   started_mono_s=started, ended_mono_s=clock(), intervals=interval_count,
                   device_versions=versions, input_windows={"valid": input_valid, "invalid": input_invalid,
                                                            "first_discarded": first is not None},
                   start_snapshot=first, end_snapshot=last)
    emit(summary)
    return summary


class Capture:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=False)
        self.directory = directory
        self.raw = (directory / "console.raw").open("wb")
        self.jsonl = (directory / "samples.jsonl").open("w", encoding="utf-8")

    def emit(self, event):
        if "raw_b64" in event:
            raw = base64.b64decode(event["raw_b64"])
            event = dict(event, raw_offset=self.raw.tell(), raw_length=len(raw))
            self.raw.write(raw)
            self.raw.flush()
        self.jsonl.write(json.dumps(event, sort_keys=True) + "\n")
        self.jsonl.flush()
        if event["type"] == "summary":
            (self.directory / "summary.json").write_text(json.dumps(event, indent=2, sort_keys=True) + "\n")

    def close(self):
        self.raw.close()
        self.jsonl.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="explicit CDC tty, e.g. /dev/cu.usbmodem…")
    parser.add_argument("--scenario", required=True, help="workload and USB configuration label")
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--timeout", type=float, default=2)
    parser.add_argument("--output", default=None, help="new capture directory inside ignored build/")
    parser.add_argument("--firmware-revision", help="explicitly supplied device build revision, never inferred")
    parser.add_argument("--manifest", type=Path, help="explicit device build manifest (JSON)")
    parser.add_argument("--input-latency", choices=("unknown", "enabled", "disabled"), default="unknown",
                        help="explicit confirmation of connected firmware FM1_INPUT_LAT instrumentation")
    args = parser.parse_args(argv)
    if not all(math.isfinite(v) and v > 0 for v in (args.duration, args.interval, args.timeout)):
        parser.error("duration, interval and timeout must be positive finite seconds")
    if not 0.1 <= args.interval <= 120 or args.timeout > 30:
        parser.error("interval must be 0.1..120 seconds; timeout at most 30 seconds")
    if args.duration < args.interval or not math.isclose(args.duration / args.interval,
                                                       round(args.duration / args.interval), abs_tol=1e-8):
        parser.error("duration must be a positive whole number of equal intervals")
    root = Path(__file__).resolve().parents[1]
    build = (root / "build").resolve()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = Path(args.output).resolve() if args.output else build / "diagnostics" / stamp
    if build not in directory.parents:
        parser.error("output must be a new directory inside this checkout's ignored build/")
    metadata = {"host_os": platform.platform(), "scenario": args.scenario, "port": args.port,
                "duration_s": args.duration, "interval_s": args.interval, "timeout_s": args.timeout,
                "created_utc": stamp, "input_latency": args.input_latency,
                "supplied_firmware_revision": args.firmware_revision,
                "firmware_provenance": "supplied by operator; device/build match not independently verified",
                "build_manifest": None}
    try:
        if args.manifest:
            raw = args.manifest.read_bytes()
            metadata["build_manifest"] = json.loads(raw)
            metadata["build_manifest_sha256"] = hashlib.sha256(raw).hexdigest()
        capture = Capture(directory)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    transport = None
    try:
        transport = PosixSerial(args.port)
        # Defer the final summary until tty restoration has also been recorded.
        summary = collect(Console(transport, args.timeout), args.duration, args.interval, metadata,
                          lambda event: capture.emit(event) if event["type"] != "summary" else None)
    except (OSError, ImportError, KeyboardInterrupt) as exc:
        summary = {"type": "summary", "validity": "INVALID", "reasons": [str(exc) or "interrupted"], "metadata": metadata}
    finally:
        if transport:
            close_error = transport.close()
            if close_error:
                summary["validity"] = "INVALID"
                summary["reasons"].append(close_error)
                summary["deltas"] = {cmd: {key: None for key in keys} for cmd, keys in COUNTERS.items()}
        capture.emit(summary)
        capture.close()
    print(str(directory / "summary.json") + ": " + summary["validity"])
    return 0 if summary["validity"] == "VALID" else 1


if __name__ == "__main__":
    sys.exit(main())
