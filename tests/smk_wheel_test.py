#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run main.c's real SMK wheel consumer with a controlled clock and ADC inputs.

CC may contain a compiler and flags. This models scheduling and raw readings;
it does not establish physical wheel drift, noise or calibration quality.
"""
import os
import shlex
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/smk-wheel-tests'


def wheel_consumer(source):
    start = source.index('static void smk_wheels(void)')
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += {'{': 1, '}': -1}.get(source[end], 0)
        end += 1
    return source[start:end]


class WheelTiming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        # Compile the actual production consumer: settle gate, bend/mod
        # mapping, and its call to the production elapsed-time helper.
        source = wheel_consumer((ROOT / 'firmware/src/main.c').read_text())
        fixture = OUT / 'main_wheels.c'
        fixture.write_text('''#include <stdint.h>
#include <stdio.h>
#include "smk_wheel.h"
static struct { uint32_t frames; uint16_t wheel[2]; } fm1_in;
static uint32_t fm1_ms;
static int16_t smk_bend14;
static uint8_t smk_modw;
static int32_t clamp(int32_t v, int32_t lo, int32_t hi)
{ return v < lo ? lo : v > hi ? hi : v; }
''' + source + '''
int main(void)
{
    unsigned frames, ms, pitch, mod;
    while (scanf("%u %u %u %u", &frames, &ms, &pitch, &mod) == 4) {
        fm1_in.frames = frames; fm1_ms = ms;
        fm1_in.wheel[0] = pitch; fm1_in.wheel[1] = mod;
        smk_wheels();
        printf("%d %u\\n", smk_bend14, smk_modw);
    }
    return 0;
}
''')
        cls.binary = OUT / 'main_wheels'
        subprocess.run(shlex.split(os.environ.get('CC', 'cc')) +
                       ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(ROOT / 'firmware/src'), str(fixture), '-o', str(cls.binary)], check=True)

    def run_readings(self, readings, base=0):
        data = ''.join(f'{frames} {(base + ms) & 0xFFFFFFFF} {p} {m}\n'
                       for ms, p, m, frames in readings)
        result = subprocess.run([str(self.binary)], input=data, text=True, capture_output=True, check=True)
        return [tuple(map(int, line.split())) for line in result.stdout.splitlines()]

    def drift(self, times, finish=1000, p=510, probe=530, repeats=1, base=0):
        readings = [(0, 500, 615, 300), (0, p, 615, 300)]
        readings.extend((ms, p, 615, 300) for ms in times for _ in range(repeats))
        readings.append((finish, probe, 485, 300))
        outputs = self.run_readings(readings, base)
        self.assertTrue(all(bend == 0 for bend, _ in outputs[:-1]))
        return outputs[-1]

    def test_fast_sparse_and_repeated_polls(self):
        # All schedules observe the same 250ms qualification times. Extra
        # calls inside each interval (including same-ms calls) do no work.
        fast = self.drift(range(1, 1001))
        sparse = self.drift([137, 250, 387, 500, 637, 750, 887, 1000])
        repeated = self.drift([250, 500, 750, 1000], repeats=401)
        self.assertEqual(fast, (14 * 8191 // 64, 127))
        self.assertEqual(sparse, fast)
        self.assertEqual(repeated, fast)

    def test_same_ms_never_accumulates_drift(self):
        self.assertEqual(self.drift([0], finish=0, repeats=10000), (18 * 8191 // 68, 127))

    def test_uint32_wrap(self):
        self.assertEqual(self.drift([250, 500, 750, 1000], base=0xFFFFFF9B),
                         self.drift(range(1, 1001)))

    def test_delayed_poll_moves_only_one_count_and_resets_time(self):
        self.assertEqual(self.drift([1000000], finish=1000000, repeats=10000), (17 * 8191 // 67, 127))
        samples = [(0, 500, 615, 300), (1000000, 510, 615, 300),
                   (1000249, 510, 615, 300), (1000249, 530, 485, 300)]
        self.assertEqual(self.run_readings(samples)[-1], (17 * 8191 // 67, 127))

    def test_negative_drift(self):
        self.assertEqual(self.drift([250, 500, 750, 1000], p=490, probe=470), (-14 * 8192 // 64, 127))

    def test_out_of_band_resets_elapsed_time(self):
        for bent in (488, 512, 470, 530):
            prefix = [(0, 500, 615, 300), (0, 510, 615, 300), (240, bent, 615, 300)]
            for end, expected in [(489, 18 * 8191 // 68), (490, 17 * 8191 // 67)]:
                samples = prefix + [(241, 510, 615, 300), (end, 510, 615, 300), (end, 530, 615, 300)]
                self.assertEqual(self.run_readings(samples)[-1], (expected, 0))

    def test_settle_gate_dead_band_and_mod_mapping(self):
        samples = [(0, 100, 0, 299), (1000, 500, 615, 300), (1249, 510, 485, 300),
                   (1249, 530, 615, 300), (1250, 420, 485, 300), (1251, 580, 615, 300)]
        self.assertEqual(self.run_readings(samples), [(0, 0), (0, 0), (0, 127),
                                                     (18 * 8191 // 68, 0), (-8192, 127), (8191, 0)])


if __name__ == '__main__':
    unittest.main()
