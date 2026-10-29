#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only diagnostic-loader capture. CLI never installs or changes firmware.

TracingUpdater is an explicit maintainer integration seam for the existing
package validator/updater; it preserves validation, serving and final verify.
It must only be used with an independently reviewed/pinned diagnostic package.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time

import fm1_install as install

CMD = 0x3E
NOMINAL_HZ = 24_000_000
CAP = 128


def packet(body):
    raw = bytes((0, 0x59, CMD, len(body), 0, 0)) + body
    return b'\xf0' + install.pack7(raw + bytes((~sum(body) & 255,))) + b'\xf7'


def decode(wire):
    if len(wire) < 3 or wire[0] != 0xF0 or wire[-1] != 0xF7 or any(x > 127 for x in wire[1:-1]):
        raise ValueError('Invalid diagnostic MIDI frame')
    raw = install.unpack7(wire[1:-1])
    if raw[:3] != bytes((0, 0x59, CMD)):
        if raw[:3] == b'\x00\x59\x30':
            raise ValueError('Package read request during observation; not an idle readout window')
        return None
    if len(raw) != 39 or raw[3:6] != b'\x20\x00\x00' or raw[-1] != (~sum(raw[6:-1]) & 255):
        raise ValueError('Invalid diagnostic length/checksum')
    if packet(raw[6:-1]) != wire:
        raise ValueError('Noncanonical diagnostic framing')
    return raw[6:-1]


def capture(link, directory, phase='startup', *, clock=time.monotonic, sleep=time.sleep):
    """Read an already owned loader link; never open/close it or send upgrade/data.

    Requires an idle startup window, or the diagnostic post-success window.
    Readiness uses at most three bounded polls; calibration/records are one-shot.
    Failed/partial captures remain on disk and are rejected; no flash retries.
    """
    if phase not in ('startup', 'success'):
        raise ValueError('Unknown observation phase')
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=False)
    events, replies = [], []
    started = clock()
    count = None
    nonce = int(started * 1_000_000) & 65535
    report = {'phase': phase, 'status': 'INCOMPLETE', 'events': events, 'records': replies,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'limits': ['Instrumented variant, not unmodified production timing',
                         'No physical LCD pixel/readability, DMA-source, live-stack or fault proof']}

    def query(index, purpose='record'):
        nonlocal nonce, count
        if clock() - started >= 2.5:
            raise TimeoutError('Whole diagnostic capture deadline')
        nonce = (nonce + 1) & 65535
        request = bytes((1, nonce & 255, nonce >> 8, index))
        request_wire = packet(request)
        sent = clock()                              # before synchronous transport send
        event = {'index': index, 'purpose': purpose, 'nonce': nonce, 'sent': sent, 'request_hex': request_wire.hex()}
        events.append(event)
        if not link.send(request_wire):
            raise ConnectionError('Diagnostic send failed')
        deadline = min(started + 2.5, sent + .7)
        while clock() < deadline:
            wire = link.read(max(0, deadline - clock()))
            received = clock()                      # later receipt is conservative
            if wire is None:
                continue
            if len(wire) > 512:
                raise ValueError('Oversized diagnostic frame')
            payload = decode(wire)
            if payload is None:
                continue
            if payload[4:6] != request[1:3]:
                continue                           # stale nonce, never accepted as current
            if payload[0] != 1 or payload[1] != index or payload[3] or payload[6:8] != b'\x18\x00':
                raise ValueError('Invalid schema/index/status/timebase')
            if not 0 < payload[2] <= CAP:
                raise ValueError('Invalid/empty trace count')
            if count is None:
                count = payload[2]
            if count != payload[2]:
                raise ValueError('Trace changed during readout')
            event.update(received=received, wire_hex=wire.hex())
            return payload, sent, received
        event['timed_out'] = True
        raise TimeoutError('Diagnostic query deadline')

    try:
        # FINISH_WRITE can arrive before SUCCESS has finished drawing. A
        # separate round trip establishes the outer-loop readout window; its
        # wait and timer sample must never enter the calibration interval.
        # A request sent while the previous native reply is pending may be
        # dropped. Only readiness may poll again, always with a fresh nonce.
        for attempt in range(3):
            try:
                query(255, 'readiness')
                break
            except TimeoutError:
                if attempt == 2:
                    raise
        first, tx0, rx0 = query(255, 'calibration-start')
        for index in range(count):
            payload, _, _ = query(index)
            start, end, meta, outcome, code, percent = struct.unpack('<6I', payload[8:])
            kind, state, lo, hi = (meta >> (8*i) & 255 for i in range(4))
            rows, stop, failed, reserved = (outcome >> (8*i) & 255 for i in range(4))
            if kind not in (1, 2, 3) or state > 5 or hi < lo or hi > 240 or rows > hi-lo or stop > 3 or failed > 1 or reserved or percent > 100:
                raise ValueError('Malformed trace record')
            if kind == 3 and (lo or hi or rows):
                raise ValueError('Malformed DISPON record')
            replies.append(dict(index=index, kind=kind, state=state, first=lo, last=hi, rows=rows,
                                stop=stop, failed=failed, code=code if code < 2**31 else code-2**32,
                                percent=percent, ticks=(end-start) & 0xFFFFFFFF))
        gap = .5 - (clock() - rx0)
        if gap > 0:
            sleep(gap)
        last, tx1, rx1 = query(255, 'calibration-end')
        ticks0, declared0 = struct.unpack('<2I', first[8:16])
        ticks1, declared1 = struct.unpack('<2I', last[8:16])
        if declared0 != 24 or declared1 != 24 or any(first[16:]) or any(last[16:]):
            raise ValueError('Malformed calibration payload')
        elapsed = (ticks1-ticks0) & 0xFFFFFFFF
        low_dt, high_dt = tx1-rx0, rx1-tx0
        if not elapsed or low_dt <= 0 or high_dt <= 0:
            raise ValueError('Invalid timer calibration interval')
        low_hz, high_hz = elapsed/high_dt, elapsed/low_dt
        calibration = .99*NOMINAL_HZ <= low_hz <= high_hz <= 1.01*NOMINAL_HZ
        report['timer_calibration'] = {'frequency_hz_bounds': [low_hz, high_hz], 'within_nominal_1pct': calibration,
                                       'method': 'two unsigned timer samples bracketed by before-send/after-receipt host times'}
        complete = all(not r['stop'] and not r['failed'] and r['rows'] == r['last']-r['first'] for r in replies)
        states = {r['state'] for r in replies if r['kind'] == 1 and r['first'] == 0 and r['last'] == 240}
        expected = {0} if phase == 'startup' else {0, 1, 2, 3, 4}
        coverage = expected <= states and any(r['kind'] == 3 for r in replies)
        if phase == 'success':
            coverage &= any(r['kind'] == 2 and (r['first'], r['last']) == (164, 182) for r in replies)
        for record in replies:
            record['duration_us_bounds'] = [record['ticks']/high_hz*1e6, record['ticks']/low_hz*1e6]
        within = all(r['duration_us_bounds'][1] <= (2000 if r['kind'] == 3 else 250000) for r in replies)
        report.update(status='ACCEPTED_DIAGNOSTIC_OBSERVATION' if calibration and complete and coverage and within else 'INCONCLUSIVE',
                      trace_complete=complete, required_coverage=bool(coverage), duration_upper_bounds_within_limits=within,
                      count=count, elapsed_s=clock()-started)
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        (out / 'trace.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


class TracingUpdater(install.Updater):
    """Explicit maintainer seam. Existing install() still validates and verifies."""
    def __init__(self, backend, trace_directory, port=None):
        super().__init__(backend, port)
        self.trace_directory = Path(trace_directory)
        self.trace_results = {}

    def write(self, ota, image, step):
        try:
            self.trace_results['startup'] = capture(ota.link, self.trace_directory / 'startup', 'startup')
            if self.trace_results['startup']['status'] != 'ACCEPTED_DIAGNOSTIC_OBSERVATION':
                raise install.InstallError('trace', 'Startup observation incomplete; app-writing phase was not started')
            step('write', 0)
            if not ota.link.send(install.UPGRADE):
                raise install.InstallError('lost', 'Loader start failed')
            time.sleep(install.DELAY['start'])
            served, finished, lost = self.serve(ota.link, image, install.FINISH_WRITE, install.DELAY['idle_write'],
                                               lambda k, end: step('write', min(99, end*100//len(image))))
            if not finished:
                raise install.InstallError('lost' if lost else 'stopped', f'Loader ended after {served} requests; trace not complete')
            try:
                self.trace_results['success'] = capture(ota.link, self.trace_directory / 'success', 'success')
            except Exception as error:
                # A diagnostic observation failure must not suppress ordinary
                # post-install verification or trigger another flash attempt.
                self.trace_results['success'] = {'status': 'INCOMPLETE', 'error': str(error)}
            step('write', 100)
        finally:
            ota.link.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, help='exact already-running diagnostic loader MIDI name')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--phase', choices=('startup', 'success'), default='startup')
    args = parser.parse_args()
    backend = install.MidoBackend()
    if backend.input_names().count(args.port) != 1 or backend.output_names().count(args.port) != 1:
        parser.error('Requested MIDI pair unavailable or ambiguous')
    link = backend.open(args.port, args.port)
    try:
        identity = install.handshake(link, 1)
        if not identity or not identity.loader:
            parser.error('Requested endpoint is not an already-running loader')
        report = capture(link, args.out, args.phase)
        print(json.dumps({key: report[key] for key in ('phase', 'status', 'count', 'elapsed_s')}))
        return 0 if report['status'] == 'ACCEPTED_DIAGNOSTIC_OBSERVATION' else 1
    finally:
        link.close()


if __name__ == '__main__':
    raise SystemExit(main())
