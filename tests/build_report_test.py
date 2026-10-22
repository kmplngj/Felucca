#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exact resource extraction, authoritative boundary failures and stale-evidence refusal."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build as B
import build_report as R


def symbols(values):
    return ''.join(f'{value:08x} g .bss 00000000 {name}\n' for name, value in values.items())


class ResourceReport(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {'FELUCCA_CRASH_CTX': '0'})
        environment.start()
        self.addCleanup(environment.stop)
        cpu = patch.object(B, 'CPU2', False)
        cpu.start()
        self.addCleanup(cpu.stop)
        regions = B.ld_regions()
        self.values = {'_start': B.APP_XIP, '_bss_end': regions['RAM'][0] + 256,
                       '_pool_start': regions['POOL'][0], '_pool_end': regions['POOL'][0] + 256,
                       '_rt_start': regions['RAMTEXT'][0], '_rt_end': regions['RAMTEXT'][0] + 100,
                       '_c1_start': regions['RAMTEXT'][0] + 100, '_c1_end': regions['RAMTEXT'][0] + 100,
                       '_guard0': 0x01C74000, '_ustack_lo': 0x01C74100, '_ustack_top': 0x01C7A000,
                       '_guard1': 0x01C7A000, '_sstack_lo': 0x01C7A100, '_sstack_top': 0x01C7C000}
        self.noinit = regions['NOINIT'][1] - 100
        self.image = bytes.fromhex('04818000') + bytes(12)

    def evidence(self, *, tail=0, worker=False):
        used = self.noinit + tail
        hdr = f' 5 .noinit {used:08x} 01c7c000 01c7c000 00040000 2**2\n'
        syms = symbols(self.values) + f'01c7c000 g .noinit {self.noinit:08x} retained\n'
        rt = 'Disassembly of section .ram_text:\n 1c00000: 00 00 \tret\n'
        if worker:
            rt += 'Disassembly of section .c1_text:\n 1c00064: 00 00 \tcall r0\n'
        return self.image, hdr, syms, ' 2000120: 00 00 \tr0 = 0\n', rt

    def test_exact_spans_margins_and_reserved_stacks(self):
        measured, stacks = R.resources(B, self.evidence())
        self.assertEqual(set(measured), {'app', 'RAM', 'POOL', 'RAMTEXT', 'NOINIT'})
        self.assertEqual(measured['RAM']['used_bytes'], 256)
        self.assertEqual(measured['RAM']['margin_bytes'], 73728 - 256 - B.RAM_SPARE_MIN)
        self.assertEqual(measured['NOINIT']['spare_bytes'], 100)
        self.assertEqual(measured['NOINIT']['margin_bytes'], 0)
        self.assertEqual(measured['RAMTEXT']['used_bytes'], 100)
        self.assertEqual(stacks['main_user']['reserved_bytes'], 24320)
        self.assertEqual(stacks['main_supervisor']['reserved_bytes'], 7936)
        self.assertEqual(stacks['main_user_guard']['reserved_bytes'], 256)
        self.assertNotIn('worker_supervisor', stacks)

    def test_authoritative_one_byte_floors_and_anonymous_tail(self):
        for region, symbol_name, floor in (('RAM', '_bss_end', B.RAM_SPARE_MIN),
                                            ('POOL', '_pool_end', B.POOL_SPARE_MIN)):
            origin, size = B.ld_regions()[region]
            self.values[symbol_name] = origin + size - floor
            self.assertEqual(R.resources(B, self.evidence())[0][region]['margin_bytes'], 0)
            self.values[symbol_name] += 1
            with self.assertRaisesRegex(ValueError, 'headroom'):
                R.resources(B, self.evidence())
            self.values[symbol_name] = origin + 256
        with self.assertRaisesRegex(ValueError, 'NOINIT headroom 99 B'):
            R.resources(B, self.evidence(tail=1))
        with patch.dict(os.environ, FELUCCA_CRASH_CTX='1'):
            self.noinit += B.CRASH_CTX_NOINIT
            self.assertEqual(R.resources(B, self.evidence())[0]['NOINIT']['enforced_spare_min_bytes'], 24)
            with self.assertRaisesRegex(ValueError, 'NOINIT headroom 23 B'):
                R.resources(B, self.evidence(tail=1))

    def test_missing_reversed_overlap_or_overflow_evidence_refused(self):
        for name in ('_bss_end', '_rt_start', '_c1_end', '_ustack_lo'):
            value = self.values.pop(name)
            with self.subTest(name=name), self.assertRaises(ValueError):
                R.resources(B, self.evidence())
            self.values[name] = value
        for name, value in (('_rt_end', 0), ('_c1_start', self.values['_rt_start']),
                            ('_c1_end', self.values['_rt_start'] + 0x6001), ('_ustack_top', 0)):
            original = self.values[name]
            self.values[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                R.resources(B, self.evidence())
            self.values[name] = original
        evidence = list(self.evidence())
        evidence[1] = ''
        with self.assertRaisesRegex(ValueError, 'missing .noinit'):
            R.resources(B, evidence)
        evidence = list(self.evidence())
        evidence[-1] = ' 1c00000: 00 00 \tcall r0\n'
        with self.assertRaisesRegex(ValueError, 'contains calls'):
            R.resources(B, evidence)

    def test_worker_stacks_are_already_in_ram_allocation(self):
        self.values.update(_c1_ustack=0x01C09000, _c1_ustack_top=0x01C0A000,
                           _c1_sstack=0x01C0A000, _c1_sstack_top=0x01C0A100)
        self.values['_c1_end'] += 20
        with patch.object(B, 'CPU2', True):
            _, stacks = R.resources(B, self.evidence(worker=True))
        self.assertEqual(stacks['worker_user_including_guard']['reserved_bytes'], 4096)
        self.assertEqual(stacks['worker_supervisor']['reserved_bytes'], 256)
        self.assertEqual(stacks['worker_supervisor']['accounted_in'], 'RAM')

    def test_stale_artifact_inventory_configuration_and_measurements_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = 'felucca.fwsc'
            for name in R.artifact_paths(package):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}\n' if 'build-identity' in name else name)
            source = root / 'source.c'
            source.write_text('source')
            inputs = {'source.c': R.digest(source)}
            config = {'actual': 'flags'}
            measured = R.resources(B, self.evidence())
            with patch.object(B, 'SRC', root), patch.object(B, 'OUT', root / 'build'), \
                    patch.object(B, 'BUILD_IDENTITY', {}), patch.object(R, 'input_hashes', return_value=inputs), \
                    patch.object(R, 'configuration', return_value=config):
                before = R.write(B, self.evidence(), package, inputs, config)
                first = (root / 'build/resource-report.json').read_bytes()
                R.write(B, self.evidence(), package, inputs, config)
                self.assertEqual(first, (root / 'build/resource-report.json').read_bytes())
                R.verify(root, before, config=config, measured=measured)
                for mutate in (
                        lambda r: r['artifact_sha256'].pop('build/felucca.elf'),
                        lambda r: r['resources']['RAM'].update(used_bytes=-1),
                        lambda r: r.pop('resources'), lambda r: r.pop('stack_reservations'),
                        lambda r: r.update(build_identity={'revision': 'false'}),
                        lambda r: r['configuration'].update(actual='other')):
                    changed = copy.deepcopy(before)
                    mutate(changed)
                    with self.assertRaises(ValueError):
                        R.verify(root, changed, config=config, measured=measured)
                with self.assertRaisesRegex(ValueError, 'configuration'):
                    R.verify(root, before, config={'actual': 'different'}, measured=measured)
                elf = root / 'build/felucca.elf'
                elf.write_text('stale')
                with self.assertRaisesRegex(ValueError, 'felucca.elf'):
                    R.verify(root, before, config=config, measured=measured)
                elf.write_text('build/felucca.elf')
                source.write_text('changed dirty input')
                with self.assertRaisesRegex(ValueError, 'source.c'):
                    R.verify(root, before, config=config, measured=measured)

    def test_initial_source_inventory_excludes_stale_generated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.c'
            source.write_text('source')
            generated = root / 'build/gen/generated.h'
            generated.parent.mkdir(parents=True)
            generated.write_text('old generated')
            def inventory(command):
                return b'source.c\0' if '--recurse-submodules' in command else b''
            with patch.object(R.subprocess, 'check_output', side_effect=inventory):
                initial = R.input_hashes(root, include_generated=False)
                generated.write_text('freshly generated')
                self.assertEqual(initial, R.input_hashes(root, include_generated=False))
                self.assertEqual(set(initial), {'source.c'})
                self.assertEqual(set(R.input_hashes(root)), {'source.c', 'build/gen/generated.h'})
                source.write_text('changed during generation')
                self.assertNotEqual(initial, R.input_hashes(root, include_generated=False))

    def test_effective_flags_preprocess_only_and_normalize_compiler_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            tc = Path(folder)
            for name in ('pi32v2/bin/clang', 'pi32v2/bin/ld', 'common/bin/objdump', 'common/bin/objcopy'):
                path = tc / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            def command(tool, *args):
                if tool == 'cc':
                    self.assertIn('-E', args)
                    self.assertIn('-dM', args)
                    self.assertNotIn('-c', args)
                    self.assertIn('-Os', args)
                    return ('#define FELUCCA_ENGINE_H\n#define FELUCCA_CPU2 1\n'
                            '#define FELUCCA_ID "FM-1_900"\n#define FELUCCA_SLICE 1\n#define FELUCCA_FM4 0\n')
                return 'clang version 4.0.1\nInstalledDir: /different/workspace\n'
            with patch.object(B, 'tc', side_effect=command), patch.object(B, 'toolchain', return_value=tc), \
                    patch.object(B.fm1pkg_make, 'sdk_file', return_value=b'sdk'):
                result = R.configuration(B)
            self.assertEqual(result['effective_defines']['FELUCCA_CPU2'], '1')
            self.assertEqual(result['effective_defines']['FELUCCA_ENGINE_H'], '')
            self.assertNotIn('InstalledDir', result['compiler']['version'])


if __name__ == '__main__':
    unittest.main()
