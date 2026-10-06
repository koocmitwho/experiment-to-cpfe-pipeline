"""Exercise the independent verifier against real temporary CSV/HDF5 files."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import h5py


VERIFIER = Path(__file__).resolve().parents[1] / "verify_outputs.py"


class VerifyOutputsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="paramaterial-verify-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.csv_path = self.root / "specimen-A.csv"
        self.h5_path = self.root / "sample.h5"
        self.csv_path.write_text("Strain,Stress_MPa\n0,0\n0.001,120.5\n0.002,201\n", encoding="utf-8")
        self.digest = hashlib.sha256(self.csv_path.read_bytes()).hexdigest()
        self.units = {"Strain": "1", "Stress_MPa": "MPa"}
        self.metadata = {
            "sample_id": "specimen-A", "unit_system": self.units,
            "sources": [{"kind": "measured", "uri": str(self.csv_path),
                         "sha256": self.digest, "role": "measured_observations"}],
        }
        self.asset = {
            "asset_id": "asset-source-0000", "parent_asset_id": None,
            "source_kind": "measured", "layer": "raw", "sha256": self.digest,
            "uri": str(self.csv_path), "units": self.units,
            "descriptive_metadata": {"column_map": {"Strain": "0", "Stress_MPa": "1"}},
        }
        self.records = [
            {"Strain": 0.0, "Stress_MPa": 0.0, "source_row": 2,
             "source_asset_id": "asset-source-0000", "source_kind": "measured"},
            {"Strain": 0.001, "Stress_MPa": 120.5, "source_row": 3,
             "source_asset_id": "asset-source-0000", "source_kind": "measured"},
            {"Strain": 0.002, "Stress_MPa": 201.0, "source_row": 4,
             "source_asset_id": "asset-source-0000", "source_kind": "measured"},
        ]
        with h5py.File(self.h5_path, "w") as h:
            meta = h.create_group("meta")
            meta.create_dataset("sample_metadata_json", data=json.dumps(self.metadata))
            assets = h.create_group("assets")
            assets.create_group("asset-source-0000").attrs["metadata_json"] = json.dumps(self.asset)
            table = h.create_group("measured/measured_observations")
            table.create_dataset("records_json", data=json.dumps(self.records))
            columns = table.create_group("columns")
            columns.create_dataset("Strain", data=[0.0, 0.001, 0.002])
            columns.create_dataset("Stress_MPa", data=[0.0, 120.5, 201.0])
            columns.create_dataset("source_row", data=[2, 3, 4])
        self.manifest = {"cases": [{
            "sample_id": "specimen-A", "csv_path": str(self.csv_path),
            "hdf5_path": str(self.h5_path), "rows": 3, "units": self.units,
        }]}

    def run_verifier(self, expected_exit):
        self.assertTrue(VERIFIER.is_file(), "Independent verifier implementation is missing")
        (self.root / "run.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-B", str(VERIFIER), "--run-dir", str(self.root)],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, expected_exit, result.stdout + result.stderr)
        report = json.loads((self.root / "verify_readback.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed" if expected_exit == 0 else "failed")
        return report

    def test_correct_numeric_rows_identity_units_and_provenance_pass(self):
        self.manifest["cases"][0]["csv_path"] = self.csv_path.name
        self.manifest["cases"][0]["hdf5_path"] = self.h5_path.name
        report = self.run_verifier(0)
        self.assertEqual(report["cases"][0]["rows"], 3)
        self.assertEqual(report["cases"][0]["sample_id"], "specimen-A")

    def test_changed_numeric_hdf5_column_fails(self):
        with h5py.File(self.h5_path, "r+") as h:
            h["measured/measured_observations/columns/Stress_MPa"][1] = 999.0
        self.run_verifier(1)

    def test_changed_units_or_sample_identity_fail(self):
        for field, value in [("sample_id", "specimen-B"),
                             ("unit_system", {"Strain": "1", "Stress_MPa": "Pa"})]:
            with self.subTest(field=field):
                metadata = {**self.metadata, field: value}
                with h5py.File(self.h5_path, "r+") as h:
                    h["meta/sample_metadata_json"][()] = json.dumps(metadata)
                self.run_verifier(1)

    def test_changed_original_row_number_fails(self):
        with h5py.File(self.h5_path, "r+") as h:
            h["measured/measured_observations/columns/source_row"][1] = 9
        self.run_verifier(1)

    def test_changed_source_hash_or_source_kind_fails(self):
        for field, value in [("sha256", "0" * 64), ("source_kind", "simulated")]:
            with self.subTest(field=field):
                with h5py.File(self.h5_path, "r+") as h:
                    h["assets/asset-source-0000"].attrs["metadata_json"] = json.dumps({**self.asset, field: value})
                self.run_verifier(1)

    def test_records_binding_and_values_are_checked(self):
        for field, value in [("source_asset_id", "other-source"),
                             ("source_kind", "simulated"), ("Stress_MPa", 888.0)]:
            with self.subTest(field=field):
                rows = [dict(row) for row in self.records]
                rows[1][field] = value
                with h5py.File(self.h5_path, "r+") as h:
                    h["measured/measured_observations/records_json"][()] = json.dumps(rows)
                self.run_verifier(1)

    def test_duplicate_case_identity_fails(self):
        self.manifest["cases"].append(dict(self.manifest["cases"][0]))
        self.run_verifier(1)


if __name__ == "__main__":
    unittest.main()
