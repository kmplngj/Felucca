#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Strict offline client/clock/failure tests. No device backend is instantiated."""
import argparse
import json
from pathlib import Path
import struct
import sys
import tempfile
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fm1_loader_trace as trace


class Clock:
    def __init__(self): self.now = 1.0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


def record(kind, state, lo, hi, rows, stop=0, us=95000):
    start = 0xFFFF0000
    return struct.pack('<6I', start, (start+us*24) & 0xFFFFFFFF,
                       kind | state << 8 | lo << 16 | hi << 24, rows | stop << 8, 0, 0)


def records():
    return [record(1, state, 0, 240, 240) for state in range(5)] + [record(3, 0, 0, 0, 0, us=100), record(2, 2, 164, 182, 18, us=7000)]


class Link:
    def __init__(self, clock, rows=None, hz=24_000_000, flags=0, stale=False):
        self.clock, self.rows, self.hz, self.flags, self.stale = clock, records() if rows is None else rows, hz, flags, stale
        self.pending, self.sent = [], []
    def send(self, wire):
        raw = trace.install.unpack7(wire[1:-1]); assert raw[:6] == b'\x00\x59\x3e\x04\x00\x00'
        request = raw[6:-1]; assert trace.packet(request) == wire  # only read-only query frames
        index = request[3]; self.sent.append(wire)
        payload = bytes((1, index, len(self.rows), self.flags, request[1] ^ int(self.stale), request[2], 24, 0))
        if index == 255:
            data = struct.pack('<6I', int((self.clock.now+.0005)*self.hz) & 0xFFFFFFFF, 24, 0, 0, 0, 0)
        else:
            data = self.rows[index]
        self.pending.append(trace.packet(payload+data)); return True
    def read(self, timeout):
        self.clock.now += .001 if self.pending else timeout
        return self.pending.pop(0) if self.pending else None


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--wire-hex', required=True); args = parser.parse_args()
    wire = bytes.fromhex(args.wire_hex); payload = trace.decode(wire)
    assert payload[:8] == bytes((1, 0, 4, 0, 0x34, 0x12, 24, 0)), 'Real C encoder and Python decoder disagree'
    corrupt = bytearray(wire); corrupt[-2] ^= 1
    try: trace.decode(bytes(corrupt))
    except ValueError: pass
    else: raise AssertionError('Corrupt C-frame fixture accepted')
    with tempfile.TemporaryDirectory(prefix='trace-client-', dir=ROOT/'build'/'ldr-trace') as work:
        work = Path(work)
        def capture(name, **kwargs):
            clock = Clock(); link = Link(clock, **kwargs)
            result = trace.capture(link, work/name, 'success', clock=clock, sleep=clock.sleep)
            return result, link
        result, link = capture('good')
        assert result['status'] == 'ACCEPTED_DIAGNOSTIC_OBSERVATION' and result['count'] == 7
        assert all(row['ticks'] > 0 for row in result['records'])  # records cross TIMER4 wrap
        result, _ = capture('wrong-clock', hz=12_000_000)
        assert result['status'] == 'INCONCLUSIVE' and not result['timer_calibration']['within_nominal_1pct']
        rows = records(); rows[0] = record(1, 0, 0, 240, 200)
        result, _ = capture('partial', rows=rows); assert result['status'] == 'INCONCLUSIVE'
        result, _ = capture('missing-states', rows=[records()[0], records()[5]])
        assert result['status'] == 'INCONCLUSIVE' and not result['required_coverage']
        rows = records(); rows[0] = record(1, 0, 0, 240, 240, us=260000)
        result, _ = capture('slow', rows=rows); assert result['status'] == 'INCONCLUSIVE'
        for name, kwargs, error in [('overflow', {'flags': 1}, ValueError), ('stale', {'stale': True}, TimeoutError)]:
            try: capture(name, **kwargs)
            except error: pass
            else: raise AssertionError(name+' accepted')
            saved = json.loads((work/name/'trace.json').read_text()); assert saved['status'] == 'INCOMPLETE' and saved['error']
            assert saved['events'][0]['request_hex'] and 'sent' in saved['events'][0]
        class Writer:
            def __init__(self): self.sent = []; self.closed = False
            def send(self, packet): self.sent.append(packet); return True
            def close(self): self.closed = True
        class Device: pass
        writer = Writer(); device = Device(); device.link = writer
        updater = trace.TracingUpdater(None, work/'writer'); updater.serve = lambda *args: (1, True, False)
        with patch.object(trace, 'capture', return_value={'status': 'INCONCLUSIVE'}):
            try: updater.write(device, b'abcd', lambda *args: None)
            except trace.install.InstallError: pass
            else: raise AssertionError('Incomplete startup did not stop app-writing phase')
        assert not writer.sent and writer.closed
        writer = Writer(); device.link = writer
        def observations(*args):
            if args[2] == 'startup': return {'status': 'ACCEPTED_DIAGNOSTIC_OBSERVATION'}
            raise TimeoutError('injected post-success read failure')
        with patch.object(trace, 'capture', side_effect=observations), patch.object(trace.time, 'sleep'):
            updater.write(device, b'abcd', lambda *args: None)
        assert writer.sent == [trace.install.UPGRADE] and writer.closed
        assert updater.trace_results['success']['status'] == 'INCOMPLETE'  # inherited verify can still run
    print('loader trace client: real C wire fixture, calibrated bounds, partial/malformed/stale refusal and updater failure policy PASS')


if __name__ == '__main__': main()
