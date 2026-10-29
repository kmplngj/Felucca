#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline tone-evidence regressions; no USB transport or device acceptance."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / 'tools/uac_tone_check.py'


def tone(phase, count):
    frames = []
    for i in range(count):
        p = (phase + i) % 100
        frames.append(((p if p < 50 else 100 - p) * 1000 - 25000,
                       abs(50 - p) * 1000 - 25000))
    return frames


class ToneCheckTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def wav(self, name, frames, rate=48000, channels=2, width=2):
        path = self.directory / name
        with wave.open(str(path), 'wb') as w:
            w.setparams((channels, width, rate, 0, 'NONE', 'not compressed'))
            w.writeframes(b''.join(struct.pack('<hh', *frame) for frame in frames))
        return path

    def run_check(self, *paths):
        result = subprocess.run([sys.executable, str(CHECK), *map(str, paths)],
                                text=True, capture_output=True)
        self.assertEqual(result.stderr, '')
        return result

    def test_valid_rates_phases_and_leading_silence(self):
        for rate in (44100, 48000):
            for phase in (0, 24, 25, 26, 49, 50, 74, 75, 76, 99):
                for silence in (0, 17):
                    with self.subTest(rate=rate, phase=phase, silence=silence):
                        frames = [(0, 0)] * silence + tone(phase, 203)
                        path = self.wav('valid.wav', frames, rate)
                        result = self.run_check(path)
                        self.assertEqual(result.returncode, 0, result.stdout)
                        # A first zero-valued tone frame is indistinguishable from startup silence.
                        checked = 202 if phase in (25, 75) else 203
                        self.assertIn(f'{checked} frames checked', result.stdout)

    def test_unrelated_audio_and_invalid_prefix_fail(self):
        for frames in ([(1, 2)] * 100, [(1, 2)] * 100 + tone(0, 100),
                       [(0, 0)] * 10 + [(1, 2)] + tone(0, 100)):
            with self.subTest(frames=len(frames)):
                result = self.run_check(self.wav('unrelated.wav', frames))
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('no tone synchronization', result.stdout)
                self.assertIn('0 frames checked', result.stdout)

    def test_no_synchronized_pair_fails(self):
        for frames in ([], [(0, 0)] * 100, tone(0, 1)):
            with self.subTest(frames=len(frames)):
                result = self.run_check(self.wav('empty.wav', frames))
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('0 frames checked', result.stdout)

    def test_unsupported_rate_fails(self):
        result = self.run_check(self.wav('rate.wav', tone(0, 200), 32000))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('need 44100 or 48000 Hz', result.stdout)

    def test_lost_repeated_and_corrupted_frames_fail(self):
        original = tone(0, 300)
        for frames in (original[:110] + original[111:],
                       original[:110] + [original[109]] + original[110:],
                       original[:110] + [(1, 2)] + original[111:]):
            with self.subTest(frames=len(frames)):
                result = self.run_check(self.wav('break.wav', frames))
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('1 break(s)', result.stdout)
                self.assertIn('first at frame 110', result.stdout)

    def test_last_complete_frame_is_checked(self):
        frames = tone(0, 200)
        frames[-1] = (1, 2)
        result = self.run_check(self.wav('last.wav', frames))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('first at frame 199', result.stdout)
        self.assertIn('199 frames checked', result.stdout)

    def test_checked_count_excludes_unsynchronized_samples(self):
        frames = tone(0, 100) + [(1, 2)] * 10 + tone(0, 100)
        result = self.run_check(self.wav('count.wav', frames))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('200 frames checked', result.stdout)

    def test_malformed_and_truncated_files_do_not_abort_other_files(self):
        valid = self.wav('valid.wav', tone(0, 200))
        raw = valid.read_bytes()
        partial = bytearray(raw)
        # WAV data chunk declares an incomplete stereo frame, despite complete physical bytes.
        struct.pack_into('<I', partial, 40, len(raw) - 44 - 1)
        for name, data in (('empty.wav', b''), ('header.wav', raw[:20]),
                           ('truncated.wav', raw[:-1]), ('short.wav', raw[:-4]),
                           ('partial.wav', partial)):
            with self.subTest(name=name):
                bad = self.directory / name
                bad.write_bytes(data)
                result = self.run_check(bad, valid)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertRegex(result.stdout, 'invalid WAV|incomplete PCM')
                self.assertIn(f'{valid}: 48000 Hz', result.stdout)
                self.assertIn('200 frames checked', result.stdout)
        missing = self.directory / 'missing.wav'
        result = self.run_check(missing, valid)
        self.assertEqual(result.returncode, 1)
        self.assertIn('invalid WAV', result.stdout)
        self.assertIn(f'{valid}: 48000 Hz', result.stdout)

    def test_wrong_channel_and_width_fail(self):
        for channels, width in ((1, 2), (2, 1)):
            result = self.run_check(self.wav('format.wav', tone(0, 100),
                                             channels=channels, width=width))
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn('need a 16-bit stereo recording', result.stdout)


if __name__ == '__main__':
    unittest.main()
