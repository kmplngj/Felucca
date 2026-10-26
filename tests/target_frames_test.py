#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Causal entry-frame fixtures; no target compiler or firmware generation."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_report as R
import target_frames as F


def symbol(name='f', address=0x2000100, size=4, flags='l F', section='.text'):
    return f'{address:08x} {flags} {section} {size:08x} {name}\n'


def listing(*texts, address=0x2000100):
    return ''.join(f' {address+i*2:x}: 00 00 \t{text}\n' for i, text in enumerate(texts))


class Frames(unittest.TestCase):
    def record(self, *texts, **kwargs):
        return F.inventory(symbol(size=len(texts)*2, **kwargs), listing(*texts))['functions'][0]

    def test_entry_locals_single_and_range_saves(self):
        f = self.record('[--sp] = {rets, r15-r4}', 'sp += -84', 'r0 = sp',
                        'sp += 84', '{pc, r15-r4} = [sp++]')
        self.assertEqual(f['own_entry_bytes'], 136)
        self.assertEqual(f['observed_entry_save_bytes'], 52)
        self.assertEqual(f['observed_entry_local_bytes'], 84)
        self.assertEqual(len(f['prologue']), 2)
        self.assertEqual(self.record('[--sp] = rets', 'sp += -28', 'sp += +28',
                                     'pc = [sp++]')['own_entry_bytes'], 32)
        self.assertEqual(self.record('r0 = [sp+4]', 'rts')['own_entry_bytes'], 0)
        self.assertEqual(self.record('if (sp == r0) goto 0', 'rts')['own_entry_bytes'], 0)

    def test_unknown_dynamic_and_nonentry_sp_never_become_zero(self):
        for texts in (('sp = r0',), ('sp += r0',), ('usp = r0',), ('ssp = r0',),
                      ('[--usp] = r0',), ('[--ssp] = {r1}',), ('[-- usp] = r0',),
                      ('r0 = [++ssp]',), ('r0 = [++sp]',),
                      ('sp <<= 2',), ('sp >>= 2',), ('sp %= 4',),
                      ('usp <<= 2',), ('ssp >>= 2',), ('ssp %= 4',),
                      ('sp -= 4',), ('r0 = 1', 'sp += -8'), ('r0 = 1', '[--sp] = rets'),
                      ('sp += -3',), ('[--sp] = {psr, rets}',),
                      ('[--sp] = {rets, r16-r4}',), ('[--sp] = {rets, r4, r4}',),
                      ('[--sp] = pc',), ('unknown_instruction',)):
            with self.subTest(texts=texts):
                f = self.record(*texts)
                self.assertEqual(f['status'], 'unsupported')
                self.assertIsNone(f['own_entry_bytes'])
                self.assertTrue(f['reasons'])

    def test_calls_numeric_and_indirect_and_tail_do_not_add_frames(self):
        texts = ('[--sp] = rets', 'call 10', 'call r5', '{rets} = [sp++]', 'goto 12', 'goto r0')
        f = self.record(*texts)
        self.assertEqual(f['own_entry_bytes'], 4)
        self.assertEqual(f['calls'][0]['target'], 0x200010e)
        self.assertEqual(f['calls'][1]['kind'], 'unresolved')
        self.assertIsNone(f['calls'][1]['target'])
        self.assertEqual(len(f['outgoing_branches']), 2)
        self.assertIn('not inferred', f['outgoing_branches'][0]['kind'])
        self.assertIsNone(f['outgoing_branches'][1]['target'])
        self.assertNotIn('call_chain_bytes', f)

    def test_aliases_share_exact_boundaries_but_overlap_is_unscored(self):
        syms = symbol('f') + symbol('alias') + symbol('isr_alnk0', size=0, flags='g')
        result = F.inventory(syms, listing('sp += -8', 'rts'))
        self.assertEqual(result['functions'][0]['names'], ['alias', 'f'])
        self.assertEqual(result['functions'][0]['own_entry_bytes'], 8)
        self.assertIsNone(result['unscored_code_symbols'][0]['own_entry_bytes'])
        syms += symbol('partial_alias', address=0x2000102, size=2)
        self.assertTrue(all(f['own_entry_bytes'] is None for f in F.inventory(syms, listing('sp += -8', 'rts'))['functions']))

    def test_missing_truncated_and_duplicate_evidence_fails_closed(self):
        for syms, dis in ((symbol(), listing('rts')),
                          (symbol(size=1), listing('rts'))):
            with self.subTest(syms=syms, dis=dis):
                result = F.inventory(syms, dis)
                self.assertEqual(len(result['functions']), 1)
                self.assertEqual(result['functions'][0]['status'], 'unsupported')
                self.assertIsNone(result['functions'][0]['own_entry_bytes'])
        for syms, dis in ((symbol(), listing('rts', 'rts') + listing('rts')),
                          ('garbage F .text not-a-size f\n', listing('rts')),
                          ('malformed .text alias\n', listing('rts')),
                          (symbol() + symbol(), listing('rts', 'rts'))):
            with self.subTest(syms=syms, dis=dis), self.assertRaises(ValueError):
                F.inventory(syms, dis)
        with self.assertRaisesRegex(ValueError, 'malformed instruction'):
            F.inventory(symbol(), ' 2000100: not an instruction\n')
        with self.assertRaisesRegex(ValueError, 'no sized functions'):
            F.inventory(symbol(size=0, flags='g'), listing('rts'))

    def test_inline_data_or_unknown_calls_are_explicit(self):
        self.assertIsNone(self.record('< 0 : 0x0 >')['own_entry_bytes'])
        self.assertIsNone(self.record('call unusual_target')['own_entry_bytes'])
        result = F.inventory(symbol(size=2) + symbol('other', address=0x2000110, size=2,
                                                      section='.unreviewed'), listing('rts'))
        self.assertIsNone(result['unscored_code_symbols'][0]['own_entry_bytes'])

    def test_artifact_binding_and_reservations_preserved(self):
        report = dict(build_identity={'revision': 'fixture'}, configuration_sha256='config',
                      artifact_sha256={'build/felucca.elf': 'elf', 'build/felucca.dis': 'dis'},
                      stack_reservations={'main_user': {'reserved_bytes': 24320}})
        raw = json.dumps(report).encode()
        result = F.evidence(report, raw, symbol(), listing('sp += -8', 'rts'))
        self.assertEqual(result['binding']['resource_report_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['binding']['elf_sha256'], 'elf')
        self.assertEqual(result['stack_reservations'], report['stack_reservations'])

    def test_worker_absence_and_unresolved_worker_call_are_distinct(self):
        main = symbol('main', size=2)
        dis = listing('rts')
        self.assertEqual(F.inventory(main, dis)['summary']['unresolved_call_sites'], 0)
        worker = symbol('fm1_c1_main', address=0x1c00000, size=2, section='.c1_text')
        result = F.inventory(main + worker, dis + listing('call r5', address=0x1c00000))
        self.assertEqual(result['summary']['unresolved_call_sites'], 1)
        self.assertEqual(result['functions'][0]['names'], ['fm1_c1_main'])
        self.assertEqual(result['functions'][0]['own_entry_bytes'], 0)
        self.assertIsNone(result['functions'][0]['calls'][0]['target'])


class Output(unittest.TestCase):
    def test_collision_and_symlink_aliases_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            build = root/'build'; build.mkdir()
            source = root/'source.c'; source.write_text('source')
            report_path = build/'resource-report.json'; report_path.write_text('report')
            names = ('build/felucca.elf', 'build/felucca.dis', 'build/felucca.dis.profile.json', 'build/felucca.fwsc')
            report = dict(input_sha256={'source.c': 'hash'}, artifact_sha256={name: 'hash' for name in names})
            for name in names:
                (root/name).write_text(name)
            for target in [source, report_path, *(root/name for name in names)]:
                with self.subTest(target=target), self.assertRaises(ValueError):
                    R.frame_output_path(root, target, report, report_path)
                alias = build/'alias'
                alias.symlink_to(target)
                with self.assertRaises(ValueError):
                    R.frame_output_path(root, alias, report, report_path)
                alias.unlink()
                alias.hardlink_to(target)
                with self.assertRaises(ValueError):
                    R.frame_output_path(root, alias, report, report_path)
                alias.unlink()
            with self.assertRaises(ValueError):
                R.frame_output_path(root, build/'gen/new-frames.json', report, report_path)
            result = R.frame_output_path(root, build/'analysis/frames.json', report, report_path)
            self.assertEqual(result, build/'analysis/frames.json')


if __name__ == '__main__':
    unittest.main()
