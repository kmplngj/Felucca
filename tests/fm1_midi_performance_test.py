#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Hardware sender checks without opening a physical MIDI port."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import fm1_midi_performance as runner


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


class SenderTests(unittest.TestCase):
    def test_channel_packets_note_balance_and_midi_file_timing(self):
        # Round-trip the actual player files, including two-byte PC and markers.
        for name in runner.CASES:
            for channel in (1, 16):
                with self.subTest(name=name, channel=channel), tempfile.TemporaryDirectory() as temp:
                    events = runner.scenario(name, channel)
                    held = set()
                    for event in events:
                        if "bytes" not in event: continue
                        msg = mido.Message.from_bytes(event["bytes"])
                        self.assertEqual(msg.channel, channel - 1)
                        if msg.type == "note_on" and msg.velocity: held.add(msg.note)
                        elif msg.type == "note_off" or msg.type == "note_on": held.discard(msg.note)
                    self.assertFalse(held)
                    path = Path(temp) / "case.mid"
                    runner.export_midi(events, path, mido)
                    parsed = list(mido.MidiFile(path))
                    messages = [msg for msg in parsed if not msg.is_meta]
                    self.assertEqual([msg.bytes() for msg in messages],
                                     [e["bytes"] for e in events if "bytes" in e])
                    self.assertAlmostEqual(sum(msg.time for msg in parsed), events[-1]["at_s"] + 0.5)

    def run_sender(self, send):
        clock = Clock()
        with contextlib.redirect_stdout(io.StringIO()):
            result = runner.transmit(runner.scenario("keys", 16), send, 16, clock, clock.sleep)
        self.assertEqual(result["audio_acceptance"], "unverified")
        return result

    def test_success_is_delivery_only_with_timed_events(self):
        sent = []
        result = self.run_sender(sent.append)
        self.assertEqual(result["status"], "sent")
        self.assertTrue(all(e["actual_s"] >= e["at_s"] - 1e-6 for e in result["events"]))
        self.assertIn([0xBF, 120, 0], sent)
        self.assertEqual(sent[-1], [0xBF, 98, 127])

    def test_disconnect_attempts_all_cleanup_without_claiming_success(self):
        sent = []
        def send(raw):
            sent.append(raw)
            if len(sent) >= 4: raise OSError("disconnected")
        result = self.run_sender(send)
        self.assertEqual(result["status"], "send_failed")
        self.assertEqual(len(result["cleanup_errors"]), len(runner.scenario_cleanup(16)))
        self.assertEqual(sent[-1], [0xBF, 98, 127])

    def test_interrupt_sends_cleanup(self):
        sent = []
        def send(raw):
            sent.append(raw)
            if len(sent) == 4: raise KeyboardInterrupt
        result = self.run_sender(send)
        self.assertEqual(result["status"], "interrupted")
        self.assertIn([0xBF, 120, 0], sent[4:])
        self.assertEqual(result["cleanup_errors"], [])


if __name__ == "__main__": unittest.main()
