#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read FM-1 control identity, or explicitly request one guarded warm restart.

No arguments performs a read-only info query. Port names are exact; differently
named endpoints require --input and --output. No settings, transport, notes or
stored data are changed to make a restart eligible. A timeout never retries it.
"""
import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import secrets
import sys
import time

from fm1_install import MidoBackend, midi_dependency_message

HEADER = bytes((0xF0, 0x7D, 0x46, 0x4C, 84))
INFO_HEADER = bytes((0xF0, 0x7D, 0x46, 0x4C, 1))
# QUERY invalidates a pending restart. Let its 2 s firmware window expire before
# probing again, even when the ACK arrived before the USB endpoint completed.
RESTART_QUIET = 2.1
EXIT = {"usage": 2, "ports": 3, "transport": 4, "timeout": 5,
        "identity": 6, "unsupported": 7, "busy": 8, "protocol": 9}
BUSY = ("transport", "notes/input", "UI/learn", "transfer ownership", "writes",
        "USB/audio/update", "capture", "pending MIDI/RX")


class ControlError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ExactMidoBackend(MidoBackend):
    # Duplicate names cannot unambiguously select a physical endpoint.
    def input_names(self):
        return self.mido.get_input_names()

    def output_names(self):
        return self.mido.get_output_names()


@dataclass(frozen=True)
class Identity:
    generation: int
    challenge: int
    uptime: int
    busy: int
    dirty: bool
    commit: str
    version: str
    pr: str | None = None
    profile: str | None = None


def u32(value):
    return bytes((value >> shift) & 127 for shift in range(0, 35, 7))


def read_u32(data):
    if len(data) != 5 or data[4] > 15:
        raise ControlError("protocol", "Invalid control u32 encoding")
    return sum(byte << shift for byte, shift in zip(data, range(0, 35, 7)))


def frame(arguments):
    return HEADER + bytes(arguments) + b"\xf7"


def control_caps(data):
    """Read INFO's positional prefix and tag-specific blocks, never scan strings."""
    try:
        version_end = data.index(0)
        if version_end > 24 or not data[:version_end].startswith(b"FELUCCA "):
            raise ValueError("not Felucca INFO")
        position = version_end + 1
        engines = data[position]
        position += 5
        for _ in range(engines):
            end = data.index(0, position)
            if end - position > 8:
                raise ValueError("engine name too long")
            position = end + 1
        position += 2  # NTRK and CHAIN_ROWS precede tagged features.
        lengths = {0x55: 1, 0x4D: 2, 0x42: 1, 0x46: 2, 0x53: 1, 0x50: 1,
                   0x4E: 1, 0x52: 1, 0x4C: 1, 0x41: 2, 0x54: 1, 0x57: 1,
                   0x56: 1, 0x43: 1, 0x4B: 1, 0x45: 1, 0x58: 1, 0x59: 1, 0x5A: 1}
        while position < len(data):
            tag, version = data[position:position + 2]
            position += 2
            if version != 1:
                return 0
            if tag == 0x49:
                length = 2 + (data[position] + 6) // 7
            elif tag in lengths:
                length = lengths[tag]
            else:
                return 0  # Unknown tags have no generic length field.
            if position + length > len(data):
                raise ValueError("truncated feature")
            if tag == 0x5A:
                return data[position]
            position += length
    except (IndexError, ValueError) as error:
        raise ControlError("protocol", "Malformed editor INFO capabilities") from error
    return 0


def select_pair(backend, port=None, input_name=None, output_name=None):
    if port is not None:
        if input_name is not None or output_name is not None:
            raise ControlError("usage", "Use --port or both --input and --output")
        input_name = output_name = port
    if (input_name is None) != (output_name is None):
        raise ControlError("usage", "Both --input and --output are required")
    inputs, outputs = list(backend.input_names()), list(backend.output_names())
    if input_name is None:
        pairs = [name for name in inputs if name in outputs and
                 re.search(r"felucca|fm-?1", name, re.I)]
        if len(pairs) != 1:
            raise ControlError("ports", "Select one exact --port NAME or --input NAME --output NAME; "
                               f"inputs={inputs!r}, outputs={outputs!r}")
        input_name = output_name = pairs[0]
    for name, names, direction in ((input_name, inputs, "input"), (output_name, outputs, "output")):
        if names.count(name) != 1:
            raise ControlError("ports", f"Exact {direction} {name!r} must occur once; available={names!r}")
    return input_name, output_name


class Controller:
    def __init__(self, backend, clock=time, query_timeout=1.0, reconnect_timeout=15.0,
                 poll=0.2, request_seed=None):
        self.backend, self.clock = backend, clock
        self.query_timeout, self.reconnect_timeout, self.poll = query_timeout, reconnect_timeout, poll
        self.sequence = secrets.randbits(32) if request_seed is None else request_seed
        self.evidence = {"restart_attempted": False, "restart_sent": False,
                         "acknowledged": False, "disconnect_observed": False,
                         "restart_verified": False}

    def request_id(self):
        self.sequence = (self.sequence + 1) & 0xFFFFFFFF
        return self.sequence

    def capabilities(self, link):
        link.drain()
        if not link.send(INFO_HEADER + b"\xf7"):
            raise ControlError("transport", "Editor INFO send failed")
        end = self.clock.monotonic() + self.query_timeout
        while (left := end - self.clock.monotonic()) > 0:
            packet = link.read(left)
            if packet is None:
                break
            if packet.startswith(INFO_HEADER) and packet.endswith(b"\xf7"):
                data = packet[len(INFO_HEADER):-1]
                if any(byte > 127 for byte in data):
                    raise ControlError("protocol", "Non-7-bit INFO reply")
                return control_caps(data)
        raise ControlError("unsupported", "No editor INFO response")

    def reply(self, link, op, request, timeout):
        end = self.clock.monotonic() + timeout
        while (left := end - self.clock.monotonic()) > 0:
            packet = link.read(left)
            if packet is None:
                return None
            if not packet.startswith(HEADER) or not packet.endswith(b"\xf7"):
                continue
            data = packet[len(HEADER):-1]
            if any(byte > 127 for byte in data):
                raise ControlError("protocol", "Non-7-bit control reply")
            if len(data) < 7 or data[0] != op:
                continue
            if read_u32(data[2:7]) != request:
                continue
            return data
        return None

    def query(self, link, timeout=None):
        request = self.request_id()
        link.drain()
        extended = bool(self.evidence.get("capabilities", 0) & 4)
        if not link.send(frame(b"\0" + u32(request) + (b"\1" if extended else b""))):
            raise ControlError("transport", "Control query send failed")
        data = self.reply(link, 0, request, self.query_timeout if timeout is None else timeout)
        if data is None:
            raise ControlError("unsupported", "No guarded control reply; old/unsupported firmware or unavailable port")
        if data[1] != 0:
            raise ControlError("unsupported", f"Control query refused (rc={data[1]})")
        if len(data) < 30 or data[27] not in (0, 1):
            raise ControlError("protocol", "Invalid control identity length/dirty state")
        try:
            strings = data[28:].split(b"\0")
            bounds = (40, 24, 32, 64) if extended else (40, 24)
            if len(strings) != len(bounds) + 1 or strings[-1] or not strings[1]:
                raise ValueError("trailing data or empty version")
            if any(len(value) > bound for value, bound in zip(strings, bounds)):
                raise ValueError("identity string too long")
            values = [value.decode("ascii") for value in strings[:-1]]
            if any(ord(char) < 32 or ord(char) > 126 for char in "".join(values)):
                raise ValueError("nonprinting identity")
            commit, version = values[:2]
            pr, profile = values[2:] if extended else (None, None)
            if extended and ((pr and not re.fullmatch(r"PR #[1-9][0-9]{0,6} (head|merge)", pr)) or
                             not re.fullmatch(r"[a-z0-9-]{1,64}", profile)):
                raise ValueError("invalid verified PR label or canonical profile")
        except (ValueError, UnicodeError) as error:
            raise ControlError("protocol", "Malformed control build identity") from error
        values = [read_u32(data[offset:offset + 5]) for offset in (7, 12, 17, 22)]
        if not values[0] or not values[1]:
            raise ControlError("protocol", "Missing boot generation or challenge")
        return Identity(*values, bool(data[27]), commit, version, pr, profile)

    def open(self, pair):
        try:
            return self.backend.open(*pair)
        except Exception as error:
            raise ControlError("transport", f"Cannot open exact MIDI pair: {error}") from error

    def run(self, action="info", port=None, input_name=None, output_name=None):
        pair = select_pair(self.backend, port, input_name, output_name)
        self.evidence.update(action=action, input=pair[0], output=pair[1])
        link = self.open(pair)
        try:
            caps = self.capabilities(link)
            self.evidence["capabilities"] = caps
            required = 3 if action == "restart" else 1
            if caps & required != required:
                raise ControlError("unsupported", f"Firmware does not advertise {action} support")
            before = self.query(link)
            self.evidence["before"] = asdict(before)
            if action == "info":
                return self.evidence
            if action not in ("restart", "transfer-complete"):
                raise ControlError("usage", "Unknown control action")
            if not re.fullmatch(r"[0-9a-f]{40}", before.commit):
                raise ControlError("identity", f"{action} requires a full 40-hex build commit")
            blocked = before.busy if action == "restart" else before.busy & ~(1 << 3)
            if blocked:
                reasons = [name for bit, name in enumerate(BUSY) if before.busy & (1 << bit)]
                raise ControlError("busy", f"{action} refused: busy mask 0x{before.busy:x} ({', '.join(reasons)})")
            # Recheck uniqueness immediately before the only mutating send.
            select_pair(self.backend, input_name=pair[0], output_name=pair[1])
            request = self.request_id()
            op = 1 if action == "restart" else 2
            self.evidence.update(request_id=request)
            self.evidence["restart_attempted" if op == 1 else "transfer_complete_attempted"] = True
            if not link.send(frame(bytes((op,)) + u32(request) + u32(before.generation) + u32(before.challenge))):
                raise ControlError("transport", f"{action} send failed; outcome uncertain, never retried")
            if op == 1:
                self.evidence["restart_sent"] = True
            data = self.reply(link, op, request, self.query_timeout)
            if data is not None:
                if len(data) != 12 or read_u32(data[7:12]) != before.generation:
                    raise ControlError("protocol", f"Invalid {action} acknowledgement")
                self.evidence["ack_rc"] = data[1]
                if data[1] != 0:
                    code = {2: "identity", 3: "busy", 4: "unsupported"}.get(data[1], "protocol")
                    raise ControlError(code, f"{action} refused (rc={data[1]}); never retried")
                self.evidence["acknowledged"] = True
            if op == 2:
                if data is None:
                    raise ControlError("timeout", "Transfer-complete unverified; never retried")
                self.evidence["transfer_complete_verified"] = True
                return self.evidence
        finally:
            link.close()
        self.evidence["quiet_seconds"] = RESTART_QUIET
        quiet_end = self.clock.monotonic() + RESTART_QUIET
        while self.clock.monotonic() < quiet_end:
            inputs, outputs = list(self.backend.input_names()), list(self.backend.output_names())
            if inputs.count(pair[0]) > 1 or outputs.count(pair[1]) > 1:
                raise ControlError("ports", "Selected MIDI pair became ambiguous after restart")
            if pair[0] not in inputs or pair[1] not in outputs:
                self.evidence["disconnect_observed"] = True
            self.clock.sleep(min(self.poll, max(0, quiet_end - self.clock.monotonic())))
        return self.reconnect(pair, before)

    def reconnect(self, pair, before):
        end = self.clock.monotonic() + self.reconnect_timeout
        expected = 1 if before.generation == 0xFFFFFFFF else before.generation + 1
        while self.clock.monotonic() < end:
            inputs, outputs = list(self.backend.input_names()), list(self.backend.output_names())
            if inputs.count(pair[0]) > 1 or outputs.count(pair[1]) > 1:
                raise ControlError("ports", "Selected MIDI pair became ambiguous after restart")
            if pair[0] not in inputs or pair[1] not in outputs:
                self.evidence["disconnect_observed"] = True
            else:
                link = None
                try:
                    link = self.open(pair)
                    after = self.query(link, min(self.query_timeout, max(0, end - self.clock.monotonic())))
                    self.evidence["after"] = asdict(after)
                    if ((after.commit, after.dirty, after.version, after.pr, after.profile) !=
                            (before.commit, before.dirty, before.version, before.pr, before.profile)):
                        raise ControlError("identity", "Build identity changed after restart")
                    if after.generation != before.generation:
                        if after.generation != expected:
                            raise ControlError("identity", "Unexpected boot generation; more than one reset or another device")
                        self.evidence["restart_verified"] = True
                        return self.evidence
                except ControlError as error:
                    if error.code not in ("transport", "unsupported"):
                        raise
                finally:
                    if link is not None:
                        link.close()
            self.clock.sleep(min(self.poll, max(0, end - self.clock.monotonic())))
        raise ControlError("timeout", "Restart unverified: no exact successor generation with unchanged build; never retried")


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("info", "restart", "transfer-complete"), default="info",
                        help="Default info. transfer-complete: exclusive owner only, after its transfer completed/cancelled")
    parser.add_argument("--port", help="Exact identical input/output name")
    parser.add_argument("--input", dest="input_name", help="Exact input name; requires --output")
    parser.add_argument("--output", dest="output_name", help="Exact output name; requires --input")
    parser.add_argument("--json", action="store_true", help="Print structured evidence, including failures")
    options = parser.parse_args(arguments)
    controller = None
    result = {"action": options.action, "restart_attempted": False, "restart_verified": False}
    try:
        try:
            backend = ExactMidoBackend()
        except ImportError as error:
            raise ControlError("usage", midi_dependency_message(Path(__file__), arguments)) from error
        controller = Controller(backend)
        result = controller.run(options.action, options.port, options.input_name, options.output_name)
        result.update(ok=True)
        code = 0
    except (ControlError, OSError) as error:
        if controller is not None:
            result = controller.evidence
        category = error.code if isinstance(error, ControlError) else "transport"
        result.update(ok=False, error=category, message=str(error))
        code = EXIT[category]
    if options.json:
        print(json.dumps(result, sort_keys=True))
    elif result["ok"]:
        identity = result.get("after", result["before"])
        print(f"{result['input']} -> {result['output']}: {identity['commit']} "
              f"dirty={int(identity['dirty'])} version={identity['version']} generation={identity['generation']}")
        if options.action == "restart":
            print("Restart verified by exact successor boot generation; "
                  f"disconnect observed: {str(result['disconnect_observed']).lower()}")
    else:
        print(f"{result['error']}: {result['message']}", file=sys.stderr)
        if result.get("restart_attempted"):
            print("Restart was attempted once. Do not infer success from an ACK; inspect --json evidence.", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
