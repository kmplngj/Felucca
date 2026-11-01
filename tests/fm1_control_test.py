#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Guarded control contract failures and reconnect evidence, without hardware."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import fm1_control as C

PREFIX = b"\xf0\x7dFL\x54"
COMMIT = "a" * 40


def number(value):
    return bytes((value >> shift) & 127 for shift in (0, 7, 14, 21, 28))


def value(data):
    return sum(byte << shift for byte, shift in zip(data, (0, 7, 14, 21, 28)))


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.now += delay


class Link:
    def __init__(self, device):
        self.device, self.inbox, self.closed = device, [], False

    def send(self, packet):
        if self.closed:
            raise AssertionError("send on closed port")
        self.device.sent.append(packet)
        if packet[:4] != PREFIX[:4] or packet[-1] != 247:
            raise AssertionError("wrong wire framing")
        if packet[4] == 1:
            if self.device.info_response is not None:
                response = self.device.info_response
            else:
                response = (b"FELUCCA test\0\1\x6f\x1b\x40\x67ANALOG\0\4\x10"
                            b"\x55\1\1\x49\1\x40\x7f" + b"\0" * 10
                            + bytes((0x5A, 1, self.device.caps)))
            self.inbox.append(PREFIX[:4] + b"\1" + response + b"\xf7")
            return True
        if packet[4] != 84:
            raise AssertionError("unexpected command")
        args = packet[5:-1]
        op, request = args[0], args[1:6]
        if op == 0:
            # Real firmware cancels a pending restart on a new control query.
            if self.device.restart_at is not None and self.device.clock.now < self.device.restart_at:
                self.device.restart_at = None
            if self.device.unsupported:
                return True
            dev = self.device
            dev.challenge += 1
            dev.last_challenge = dev.challenge
            response = (bytes((0, 0)) + request + number(dev.generation) + number(dev.challenge)
                        + number(dev.uptime) + number(dev.busy) + bytes((dev.dirty,))
                        + dev.commit.encode() + b"\0" + dev.version.encode() + b"\0")
            if len(args) == 7:
                if args[-1] != 1 or not dev.caps & 4:
                    raise AssertionError("extended query sent without advertised format")
                response += dev.pr.encode() + b"\0" + dev.profile.encode() + b"\0"
            elif len(args) != 6:
                raise AssertionError("incorrect query length")
            if dev.response_transform:
                response = dev.response_transform(response)
            self.inbox.append(PREFIX + response + b"\xf7")
        elif op in (1, 2):
            if len(args) != 16:
                raise AssertionError("guarded operation must have request, generation and challenge")
            generation, challenge = value(args[6:11]), value(args[11:16])
            if (generation, challenge) != (self.device.generation, self.device.last_challenge):
                raise AssertionError("host did not echo queried generation/challenge")
            if not self.device.send_ok:
                return False
            status = self.device.status
            if self.device.ack:
                self.inbox.append(PREFIX + bytes((op, status)) + request + number(generation) + b"\xf7")
            if op == 1 and status == 0:
                self.device.restart_at = self.device.clock.now + self.device.restart_delay
            if op == 2 and status == 0:
                self.device.busy &= ~8
        else:
            raise AssertionError("unexpected command")
        return True

    def read(self, timeout):
        if self.inbox:
            return self.inbox.pop(0)
        self.device.clock.sleep(timeout)
        return None

    def drain(self):
        self.inbox.clear()

    def close(self):
        self.closed = True


class Device:
    def __init__(self):
        self.clock = Clock()
        self.inputs = ["Felucca"]
        self.outputs = ["Felucca"]
        self.sent, self.links = [], []
        self.generation, self.challenge, self.last_challenge = 7, 100, 0
        self.uptime, self.busy, self.dirty = 10000, 0, 0
        self.commit, self.version = COMMIT, "3.22-test"
        self.pr, self.profile = "PR #790 head", "standard"
        self.unsupported, self.response_transform = False, None
        self.caps, self.info_response = 3, None
        self.ack, self.send_ok, self.status = True, True, 0
        self.restart_at, self.restart_delay, self.disappear_duration = None, 0.2, 0
        self.next_generation, self.next_commit, self.next_dirty = 8, COMMIT, 0
        self.next_pr, self.next_profile = self.pr, self.profile
        self.next_inputs, self.next_outputs, self.reopen_failures = None, None, 0

    def update(self):
        if self.restart_at is not None and self.clock.now >= self.restart_at:
            self.generation, self.commit, self.dirty = self.next_generation, self.next_commit, self.next_dirty
            self.uptime = 2
            self.pr, self.profile = self.next_pr, self.next_profile
            if self.next_inputs is not None:
                self.inputs = self.next_inputs
            if self.next_outputs is not None:
                self.outputs = self.next_outputs

    def names(self, names):
        self.update()
        if self.restart_at is not None and self.restart_at <= self.clock.now < self.restart_at + self.disappear_duration:
            return []
        return list(names)

    def input_names(self):
        return self.names(self.inputs)

    def output_names(self):
        return self.names(self.outputs)

    def open(self, input_name, output_name):
        if self.links and not self.links[-1].closed:
            raise AssertionError("must close before reopening")
        if (input_name, output_name) != (self.inputs[0], self.outputs[0]):
            raise AssertionError("wrong selected pair")
        if self.links and self.reopen_failures:
            self.reopen_failures -= 1
            raise OSError("endpoint not ready")
        link = Link(self)
        self.links.append(link)
        return link

    def controller(self):
        return C_REAL(self, clock=self.clock, query_timeout=0.1,
                            reconnect_timeout=2, poll=0.1, request_seed=10)

    def operations(self):
        return [packet[5] for packet in self.sent if packet[4] == 84]


class ControlContract(unittest.TestCase):
    def setUp(self):
        self.device = Device()
        self.control = self.device.controller()

    def fails(self, code, action="restart", **kwargs):
        with self.assertRaises(C.ControlError) as error:
            self.control.run(action, **kwargs)
        self.assertEqual(error.exception.code, code)
        self.assertTrue(all(link.closed for link in self.device.links))

    def test_legacy_query_shape_is_unchanged(self):
        result = self.control.run()
        self.assertEqual(len(self.device.sent[1][5:-1]), 6)
        self.assertIsNone(result["before"]["pr"])
        self.assertIsNone(result["before"]["profile"])

    def test_extended_query_requires_capability_and_preserves_metadata(self):
        self.device.caps = 7
        result = self.control.run()
        self.assertEqual(self.device.sent[1][5:-1], b"\0" + number(11) + b"\1")
        self.assertEqual(result["before"]["pr"], "PR #790 head")
        self.assertEqual(result["before"]["profile"], "standard")
        self.assertEqual(self.device.operations(), [0])
        self.assertFalse(result["restart_attempted"])

    def test_extended_metadata_can_honestly_omit_verified_pr(self):
        self.device.caps = 5
        self.device.pr = ""
        result = self.control.run()
        self.assertEqual((result["before"]["pr"], result["before"]["profile"]), ("", "standard"))

    def test_extended_metadata_rejects_malformed_strings_without_mutation(self):
        for suffix in (b"", b"PR\0standard", b"PR\0standard\0extra\0",
                       b"P" * 33 + b"\0standard\0", b"PR\0" + b"s" * 65 + b"\0",
                       b"PR\0bad\nprofile\0", b"\0\0", b"invented\0standard\0",
                       b"PR #790 head\0Bad Profile\0", b"PR #0 head\0standard\0"):
            with self.subTest(suffix=suffix):
                self.setUp()
                self.device.caps = 7
                self.device.response_transform = lambda data: data[:28] + COMMIT.encode() + b"\0v1\0" + suffix
                self.fails("protocol", action="info")
                self.assertEqual(self.device.operations(), [0])

    def test_restart_rejects_changed_extended_metadata(self):
        for field, value in (("next_profile", "reduced-lofi"), ("next_pr", "PR #791 head")):
            with self.subTest(field=field):
                self.setUp()
                self.device.caps = 7
                setattr(self.device, field, value)
                self.fails("identity")
                self.assertEqual(self.device.operations(), [0, 1, 0])
                self.assertFalse(self.control.evidence["restart_verified"])

    def test_info_is_default_and_never_releases_or_restarts(self):
        self.device.busy = 255
        result = self.control.run()
        self.assertEqual(result["before"]["commit"], COMMIT)
        self.assertEqual(self.device.operations(), [0])
        self.assertFalse(result["restart_attempted"])

    def test_success_proves_exact_successor_without_claiming_disconnect(self):
        result = self.control.run("restart")
        self.assertTrue(result["restart_verified"])
        self.assertFalse(result["disconnect_observed"])
        self.assertEqual(result["after"]["generation"], 8)
        self.assertEqual(self.device.operations().count(1), 1)
        self.assertNotIn(2, self.device.operations())
        self.assertGreater(len(self.device.links), 1)

    def test_observed_port_absence_is_recorded_separately(self):
        self.device.disappear_duration = 0.5
        self.assertTrue(self.control.run("restart")["disconnect_observed"])

    def test_query_waits_out_pending_restart_and_reopen_can_recover(self):
        self.device.restart_delay = 1.5
        self.device.reopen_failures = 1
        self.assertTrue(self.control.run("restart")["restart_verified"])
        self.assertEqual(self.device.operations().count(1), 1)

    def test_renamed_or_ambiguous_returning_port_never_uses_another_endpoint(self):
        self.device.next_inputs = self.device.next_outputs = ["Felucca 2"]
        self.fails("timeout")
        self.assertEqual(len(self.device.links), 1)
        self.setUp()
        self.device.next_inputs = ["Felucca", "Felucca"]
        self.fails("ports")
        self.assertFalse(self.control.evidence["restart_verified"])

    def test_ack_and_uptime_drop_without_new_generation_fail(self):
        self.device.next_generation = 7
        self.fails("timeout")
        self.assertTrue(self.control.evidence["acknowledged"])
        self.assertEqual(self.control.evidence["after"]["uptime"], 2)
        self.assertFalse(self.control.evidence["restart_verified"])
        self.assertEqual(self.device.operations().count(1), 1)

    def test_missing_ack_can_still_verify_restart_and_never_retries(self):
        self.device.ack = False
        result = self.control.run("restart")
        self.assertTrue(result["restart_verified"])
        self.assertFalse(result["acknowledged"])
        self.assertEqual(self.device.operations().count(1), 1)

    def test_busy_refuses_before_mutation_including_transfer_latch_and_unknown_bits(self):
        for busy in (1, 2, 4, 8, 16, 32, 64, 128, 1 << 20):
            with self.subTest(busy=busy):
                self.setUp()
                self.device.busy = busy
                self.fails("busy")
                self.assertEqual(self.device.operations(), [0])

    def test_old_firmware_never_receives_restart(self):
        self.device.unsupported = True
        self.fails("unsupported")
        self.assertEqual(self.device.operations(), [0])

    def test_missing_query_or_restart_capability_never_sends_mutating_request(self):
        for caps in (0, 1, 2):
            self.setUp()
            self.device.caps = caps
            self.fails("unsupported")
            self.assertEqual(self.device.operations(), [])

    def test_info_strings_cannot_impersonate_capability_block(self):
        self.device.info_response = b"FELUCCA Z\1\3\0\0\0\0\0\0\4\x10"
        self.fails("unsupported")
        self.assertEqual(self.device.operations(), [])

    def test_wrong_build_dirty_or_extra_reset_fail_after_reconnect(self):
        for setting, value_ in (("next_commit", "b" * 40), ("next_dirty", 1), ("next_generation", 9)):
            with self.subTest(setting=setting):
                self.setUp()
                setattr(self.device, setting, value_)
                self.fails("identity")
                self.assertFalse(self.control.evidence["restart_verified"])

    def test_generation_wrap_skips_zero(self):
        self.device.generation, self.device.next_generation = 0xFFFFFFFF, 1
        self.assertTrue(self.control.run("restart")["restart_verified"])

    def test_unknown_or_short_commit_cannot_restart(self):
        for commit in ("unknown", "a" * 8, "g" * 40):
            self.setUp()
            self.device.commit = commit
            self.fails("identity")
            self.assertEqual(self.device.operations(), [0])

    def test_stale_busy_or_unsupported_ack_is_final_and_never_retried(self):
        for status, code in ((1, "protocol"), (2, "identity"), (3, "busy"), (4, "unsupported")):
            self.setUp()
            self.device.status = status
            self.fails(code)
            self.assertEqual(self.device.operations(), [0, 1])

    def test_send_failure_reports_uncertain_attempt_and_does_not_retry(self):
        self.device.send_ok = False
        self.fails("transport")
        self.assertTrue(self.control.evidence["restart_attempted"])
        self.assertFalse(self.control.evidence["restart_sent"])
        self.assertEqual(self.device.operations(), [0, 1])

    def test_duplicate_similar_or_unpaired_names_never_open_any_port(self):
        cases = [(["Felucca", "Felucca"], ["Felucca"], {}),
                 (["Felucca A", "Felucca B"], ["Felucca A", "Felucca B"], {}),
                 (["Felucca A"], ["Felucca B"], {"port": "Felucca"}),
                 (["Felucca"], ["Other device"], {}),
                 (["Felucca"], ["Felucca", "Felucca"], {"port": "Felucca"})]
        for inputs, outputs, options in cases:
            self.setUp()
            self.device.inputs, self.device.outputs = inputs, outputs
            self.fails("ports", **options)
            self.assertEqual(self.device.links, [])

    def test_explicit_different_names_pair_exactly(self):
        self.device.inputs, self.device.outputs = ["Felucca IN"], ["Felucca OUT"]
        result = self.control.run("restart", input_name="Felucca IN", output_name="Felucca OUT")
        self.assertEqual((result["input"], result["output"]), ("Felucca IN", "Felucca OUT"))

    def test_malformed_and_wrong_request_identity_never_authorize_restart(self):
        transforms = [lambda data: data[:-1], lambda data: data + b"x",
                      lambda data: data[:27] + b"\2" + data[28:],
                      lambda data: data[:11] + b"\x10" + data[12:],
                      lambda data: data[:2] + number(99) + data[7:]]
        for transform in transforms:
            self.setUp()
            self.device.response_transform = transform
            with self.assertRaises(C.ControlError):
                self.control.run("restart")
            self.assertEqual(self.device.operations(), [0])

    def test_transfer_complete_is_explicit_and_does_not_restart_or_reconnect(self):
        self.device.busy = 8
        result = self.control.run("transfer-complete")
        self.assertTrue(result["transfer_complete_verified"])
        self.assertFalse(result["restart_attempted"])
        self.assertEqual(self.device.operations(), [0, 2])
        self.assertEqual(len(self.device.links), 1)

    def test_transfer_complete_refuses_known_busy_or_stale_token(self):
        self.device.busy = 8 | 16
        self.fails("busy", action="transfer-complete")
        self.assertEqual(self.device.operations(), [0])
        self.setUp()
        self.device.status = 2
        self.fails("identity", action="transfer-complete")
        self.assertEqual(self.device.operations(), [0, 2])

    def test_transfer_complete_timeout_is_not_success(self):
        self.device.ack = False
        self.fails("timeout", action="transfer-complete")
        self.assertFalse(self.control.evidence.get("transfer_complete_verified", False))
        self.assertEqual(self.device.operations(), [0, 2])


class CliEvidence(unittest.TestCase):
    def test_default_info_and_json_timeout_evidence(self):
        device = Device()
        with patch.object(C, "ExactMidoBackend", return_value=device), \
                patch.object(C, "Controller", side_effect=lambda backend: device.controller()), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(C.main(["--json"]), 0)
        self.assertFalse(json.loads(output.getvalue())["restart_attempted"])
        device = Device()
        device.next_generation = 7
        with patch.object(C, "ExactMidoBackend", return_value=device), \
                patch.object(C, "Controller", side_effect=lambda backend: C_REAL(backend, clock=device.clock,
                             query_timeout=0.1, reconnect_timeout=1, request_seed=1)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(C.main(["restart", "--json"]), 5)
        result = json.loads(output.getvalue())
        self.assertTrue(result["restart_sent"])
        self.assertFalse(result["ok"])
        self.assertFalse(result["restart_verified"])

    def test_missing_dependency_message_preserves_arguments_and_never_discovers(self):
        with patch.object(C, "ExactMidoBackend", side_effect=ImportError("mido")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(C.main(["restart", "--port", "FM-1 ' exact", "--json"]), 2)
        result = json.loads(output.getvalue())
        self.assertIn("--locked --group midi", result["message"])
        self.assertIn("fm1_control.py", result["message"])
        self.assertFalse(result["restart_attempted"])


C_REAL = C.Controller

if __name__ == "__main__":
    unittest.main()
