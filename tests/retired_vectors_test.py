#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Independent wire-identity regression for retired-sound reference vectors."""
import copy
import json
import unittest
from pathlib import Path

from retired_vectors import validate_projects


class ProjectIdentityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((Path(__file__).parent / "fixtures" / "retired_vectors.json").read_text())

    def test_committed_records_match_their_labels(self):
        validate_projects(self.data)
        self.assertEqual({case["format"] for case in self.data["projects"]}, {"FUN7", "FUN8", "FUN10"})

    def test_each_project_format_covers_each_retired_sound(self):
        for fmt in ("FUN7", "FUN8", "FUN10"):
            with self.subTest(format=fmt):
                self.assertEqual({case["retired"] for case in self.data["projects"] if case["format"] == fmt},
                                 {"DIGITAL", "PHYS", "SAMPLE PERC"})

    def test_early_phys_conversion_cannot_define_input_identity(self):
        for fmt in ("FUN7", "FUN8", "FUN10"):
            for phys in (0, 1):
                with self.subTest(format=fmt, phys=phys):
                    case = copy.deepcopy(next(c for c in self.data["projects"]
                                              if c["format"] == fmt and c["retired"] == "PHYS"
                                              and c["phys_byte"] == phys))
                    case["tracks"][2]["engine_in"] = 10
                    case["tracks"][2]["preset_in"] = 0
                    with self.assertRaisesRegex(ValueError, "track 2 input identity"):
                        validate_projects({"projects": [case]})

    def test_output_identity_also_matches_serialized_output(self):
        data, case = self.changed_case()
        case["tracks"][0]["preset_out"] += 1
        with self.assertRaisesRegex(ValueError, "output identity"):
            validate_projects(data)

    def test_missing_dropped_event_is_rejected_in_each_format(self):
        for fmt in ("FUN7", "FUN8", "FUN10"):
            with self.subTest(format=fmt):
                data, case = self.changed_case(fmt)
                self.assertTrue(case["motion_dropped"])
                case["motion_dropped"].pop()
                with self.assertRaisesRegex(ValueError, "motion_dropped"):
                    validate_projects(data)

    def test_phys_motion_is_retained_without_a_retirement_drop(self):
        for fmt in ("FUN7", "FUN8", "FUN10"):
            for phys in (0, 1):
                with self.subTest(format=fmt, phys=phys):
                    case = copy.deepcopy(next(c for c in self.data["projects"]
                                              if c["format"] == fmt and c["retired"] == "PHYS"
                                              and c["phys_byte"] == phys))
                    self.assertEqual(case["motion_dropped"], [])
                    case["motion_dropped"] = [{"track": 1, "step": 3, "param": 104, "lock": 0, "value": 30}]
                    with self.assertRaisesRegex(ValueError, "motion_dropped"):
                        validate_projects({"projects": [case]})

    def changed_case(self, fmt="FUN8"):
        case = copy.deepcopy(next(c for c in self.data["projects"] if c["format"] == fmt))
        return {"projects": [case]}, case

    def test_original_fun8_mislabeled_fun7_is_rejected(self):
        data, case = self.changed_case()
        case["format"] = "FUN7"
        with self.assertRaisesRegex(ValueError, "FUN7 input magic/size"):
            validate_projects(data)

    def test_wrong_magic_is_rejected_at_correct_length(self):
        data, case = self.changed_case()
        raw = bytearray.fromhex(case["input"])
        raw[:4] = (0x46554E37).to_bytes(4, "little")
        case["input"] = raw.hex()
        with self.assertRaisesRegex(ValueError, "input magic/size"):
            validate_projects(data)

    def test_wrong_declared_size_is_rejected(self):
        data, case = self.changed_case()
        raw = bytearray.fromhex(case["input"])
        raw[4:8] = (3388).to_bytes(4, "little")
        case["input"] = raw.hex()
        with self.assertRaisesRegex(ValueError, "input magic/size"):
            validate_projects(data)

    def test_truncated_record_is_rejected(self):
        data, case = self.changed_case()
        case["input"] = case["input"][:-2]
        with self.assertRaisesRegex(ValueError, "input magic/size"):
            validate_projects(data)

    def test_wrong_parameter_count_is_rejected(self):
        data, case = self.changed_case()
        case["np"] -= 1
        with self.assertRaisesRegex(ValueError, "parameter count"):
            validate_projects(data)

    def test_truncated_output_is_rejected(self):
        data, case = self.changed_case()
        case["output"] = case["output"][:-2]
        with self.assertRaisesRegex(ValueError, "complete FUN10"):
            validate_projects(data)


if __name__ == "__main__":
    unittest.main()
