"""Check actual name geometry, RTL layout, rejection and color assignments."""
import io
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import stencils as s


class ShareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.noga = s.make_name("נגה")

    def test_reviewed_noga_geometry_is_preserved(self):
        meta = self.noga["metadata"]
        self.assertAlmostEqual(meta["width_mm"], 86.76363808339977)
        self.assertEqual(meta["height_mm"], 52)
        self.assertAlmostEqual(meta["letter_placements"][0]["translation_mm"][1], -11.402631578947371)
        self.assertEqual([p["char"] for p in meta["letter_placements"]], list("נגה"))
        self.assertGreater(meta["letter_placements"][0]["translation_mm"][0],
                           meta["letter_placements"][-1]["translation_mm"][0])

    def test_floor_and_volumes(self):
        base, fill = self.noga["base"], self.noga["fill"]
        self.assertEqual(len(base.split()), 1)
        self.assertTrue(base.is_watertight and fill.is_watertight)
        np.testing.assert_allclose(fill.bounds[:, 2], [1.2, 1.8], atol=1e-6)
        self.assertAlmostEqual(base.volume + fill.volume, self.noga["body"].area * 1.8, delta=.03)

    def test_bad_inputs_cannot_produce_files(self):
        for value in ["", "abc", "נֹגה", "../נגה", "נ-ג", "נ" * 41]:
            with self.assertRaises(ValueError):
                s.validate_name(value)
        for thickness in [0, 1, float("nan"), float("inf"), 4]:
            with self.assertRaises(ValueError):
                s.load_design(thickness)
        with self.assertRaises(ValueError):
            s.make_name("תפארת תפארת תפארת")

    def test_dual_and_single_projects_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = s.export_item(self.noga, Path(tmp) / "model")
            for file, expected in [("DUAL_COLOR.3mf", ["1", "2"]), ("SINGLE_COLOR.3mf", ["1"])]:
                with ZipFile(out / file) as z:
                    self.assertIsNone(z.testzip())
                    config = ET.fromstring(z.read("Metadata/model_settings.config"))
                    colors = [p.find("metadata[@key='extruder']").get("value") for p in config.findall("object/part")]
                    self.assertEqual(colors, expected)
                    settings = json.loads(z.read("Metadata/project_settings.config"))
                    self.assertEqual(settings["enable_prime_tower"], "1" if len(expected) == 2 else "0")
            archive = s.archive_output(out, Path(tmp) / "result.zip")
            with ZipFile(archive) as z:
                self.assertIn("single.stl", z.namelist())
                self.assertFalse(any(n.endswith(".gcode") for n in z.namelist()))

    def test_final_letter_and_word_space(self):
        item = s.make_name("חן אור")
        placements = item["metadata"]["letter_placements"]
        self.assertEqual([p["char"] for p in placements], list("חןאור"))
        self.assertTrue(item["metadata"]["body_connected"])


if __name__ == "__main__":
    unittest.main()
