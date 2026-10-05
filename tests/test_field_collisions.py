import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "patch_field_collisions.py"
SPEC = importlib.util.spec_from_file_location("patch_field_collisions", TOOL)
repair = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = repair
SPEC.loader.exec_module(repair)


class FieldCollisionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source"
        self.output = self.root / "overlay"
        self.manifest = json.loads(repair.MANIFEST_PATH.read_text(encoding="utf-8"))
        self.primary = bytes.fromhex(self.manifest["primary_geometry_hex"]["0001"])
        # Synthetic geometry and distinct per-record bytes, without game assets.
        old_primary = struct.pack("<I", 1) + b"\x77" * 48
        bone_records = b"".join(bytes([index]) * 204 for index in range(13))
        self.original = struct.pack("<I", 210) + old_primary + struct.pack("<I", 13) + bone_records
        for row in self.manifest["files"]:
            character = row["path"].split("/")[6]
            primary = bytes.fromhex(self.manifest["primary_geometry_hex"][character])
            expected = self.original[:4] + primary + self.original[56:]
            row["before_sha256"] = repair.digest(self.original)
            row["after_sha256"] = repair.digest(expected)
            path = self.source / row["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.original)

    def test_repair_preserves_version_count_and_every_bone_record(self):
        patched = repair.patch_bytes(self.original, self.primary)
        self.assertEqual(patched[:4], self.original[:4])
        self.assertEqual(patched[4:56], self.primary)
        self.assertEqual(patched[56:], self.original[56:])
        self.assertEqual(len(patched), len(self.original))

    def test_truncated_unknown_and_incompatible_layouts_are_refused(self):
        bad_inputs = [
            b"",
            self.original[:58],
            self.original[:-1],
            self.original + b"\x00",
            struct.pack("<I", 211) + self.original[4:],
            self.original[:4] + struct.pack("<I", 2) + self.original[8:],
            self.original[:56] + struct.pack("<I", 12) + self.original[60:],
        ]
        for data in bad_inputs:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                repair.patch_bytes(data, self.primary)

    def test_invalid_primary_geometry_is_refused(self):
        for primary in (self.primary[:-1], struct.pack("<I", 2) + self.primary[4:]):
            with self.assertRaises(ValueError):
                repair.patch_bytes(self.original, primary)

    def test_manifest_covers_only_the_reviewed_32_field_resources(self):
        manifest = json.loads(repair.MANIFEST_PATH.read_text(encoding="utf-8"))
        repair.validate_manifest(manifest)
        paths = {row["path"] for row in manifest["files"]}
        self.assertEqual(len(paths), 32)
        self.assertTrue(all("/FIELD.CPK/" in path and path.endswith("_F.DCL") for path in paths))
        self.assertFalse(any("_500_" in path or "/BATTLE.CPK/" in path for path in paths))

    def test_dry_run_does_not_write_source_or_output(self):
        result = repair.run(self.source, None, self.manifest)
        self.assertEqual(result["files_needing_repair"], 32)
        self.assertEqual(result["exported_files"], 0)
        self.assertFalse(self.output.exists())
        for row in self.manifest["files"]:
            self.assertEqual((self.source / row["path"]).read_bytes(), self.original)

    def test_export_is_exact_and_preserves_every_input_file(self):
        repair.run(self.source, self.output, self.manifest)
        for row in self.manifest["files"]:
            data = (self.output / row["path"]).read_bytes()
            self.assertEqual(repair.digest(data), row["after_sha256"])
            self.assertEqual(data[56:], self.original[56:])
            self.assertEqual((self.source / row["path"]).read_bytes(), self.original)

    def test_already_patched_resources_and_repeated_export_are_idempotent(self):
        repair.run(self.source, self.output, self.manifest)
        result = repair.run(self.output, None, self.manifest)
        self.assertEqual(result["files_needing_repair"], 0)
        self.assertEqual(result["already_patched_files"], 32)
        self.assertEqual(repair.run(self.source, self.output, self.manifest)["exported_files"], 32)

    def test_one_unreviewed_input_prevents_all_exports(self):
        row = self.manifest["files"][-1]
        (self.source / row["path"]).write_bytes(self.original[:-1])
        with self.assertRaisesRegex(ValueError, "unreviewed resource"):
            repair.run(self.source, self.output, self.manifest)
        self.assertFalse(self.output.exists())

    def test_different_existing_output_prevents_overwriting_any_files(self):
        row = self.manifest["files"][-1]
        path = self.output / row["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"newer manual edit")
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            repair.run(self.source, self.output, self.manifest)
        self.assertEqual(path.read_bytes(), b"newer manual edit")
        self.assertEqual(list(self.output.rglob("*.DCL")), [path])

    def test_overlapping_input_and_output_directories_are_refused(self):
        for output in (self.source, self.source / "overlay", self.root):
            with self.assertRaisesRegex(ValueError, "separate from the input"):
                repair.run(self.source, output, self.manifest)
        self.assertFalse((self.source / "overlay").exists())

    def test_escaping_and_duplicate_manifest_paths_are_refused(self):
        for path in ("../outside.DCL", self.manifest["files"][1]["path"]):
            manifest = copy.deepcopy(self.manifest)
            manifest["files"][0]["path"] = path
            with self.assertRaisesRegex(ValueError, "32 reviewed field DCL paths"):
                repair.run(self.source, self.output, manifest)
        self.assertFalse(self.output.exists())

    def test_contained_paths_reject_traversal_and_absolute_escape(self):
        for relative in ("../escape", str(self.root / "outside.DCL")):
            with self.assertRaises(ValueError):
                repair.contained_path(self.source, relative)


if __name__ == "__main__":
    unittest.main()
