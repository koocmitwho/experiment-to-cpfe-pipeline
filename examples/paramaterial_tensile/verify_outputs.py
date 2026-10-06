"""Independently compare saved HDF5 output with the original CSV and run manifest."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np


FIELDS = ("Strain", "Stress_MPa")
UNITS = {"Strain": "1", "Stress_MPa": "MPa"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_case(case, run_dir):
    sample_id = case["sample_id"]
    units = case["units"]
    require(units == UNITS, "run.json units must declare Strain=1 and Stress_MPa=MPa")
    csv_path = (run_dir / case["csv_path"]).resolve()
    hdf5_path = (run_dir / case["hdf5_path"]).resolve()
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames is not None and set(FIELDS) <= set(reader.fieldnames),
                "original CSV lacks the two expected numeric fields")
        raw_rows = list(reader)
    expected = np.asarray([[float(row[name]) for name in FIELDS] for row in raw_rows])
    require(len(raw_rows) == case["rows"] and len(raw_rows) > 0, "original CSV row count mismatch")
    require(np.isfinite(expected).all(), "original CSV contains nonfinite values")
    source_rows = np.arange(2, len(raw_rows) + 2)
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()

    with h5py.File(hdf5_path, "r") as handle:
        table = handle["measured/measured_observations"]
        columns = table["columns"]
        actual = np.column_stack([columns[name][:] for name in FIELDS])
        np.testing.assert_array_equal(actual, expected, err_msg="numeric columns changed")
        np.testing.assert_array_equal(columns["source_row"][:], source_rows,
                                      err_msg="original source row numbers changed")

        metadata = json.loads(handle["meta/sample_metadata_json"][()])
        require(metadata["sample_id"] == sample_id, "HDF5 sample identity mismatch")
        require(metadata["unit_system"] == units, "HDF5 sample unit_system mismatch")
        sources = metadata["sources"]
        require(any(source.get("sha256") == digest and source.get("kind") == "measured"
                    and source.get("role") == "measured_observations" for source in sources),
                "sample provenance lacks the original measured CSV hash")

        records = json.loads(table["records_json"][()])
        require(len(records) == len(raw_rows), "records_json row count mismatch")
        bound_ids = {row["source_asset_id"] for row in records}
        require(len(bound_ids) == 1, "records must bind to one original source asset")
        source_id = next(iter(bound_ids))
        require(source_id in handle["assets"], "records refer to a missing source asset")
        asset = json.loads(handle["assets"][source_id].attrs["metadata_json"])
        require(asset["asset_id"] == source_id, "asset identity does not match record binding")
        require(asset["parent_asset_id"] is None and asset["layer"] == "raw",
                "records do not bind to the original raw asset")
        require(asset["sha256"] == digest, "source asset hash differs from original CSV")
        require(asset["source_kind"] == "measured", "source asset is not marked measured")
        require(asset["units"] == units, "source asset units mismatch")
        require(all(row["source_kind"] == "measured" for row in records),
                "records are not marked measured")
        np.testing.assert_array_equal([row["source_row"] for row in records], source_rows,
                                      err_msg="records_json source rows changed")
        np.testing.assert_array_equal(
            [[row[name] for name in FIELDS] for row in records], expected,
            err_msg="records_json numeric values changed",
        )

    return {
        "sample_id": sample_id, "status": "passed", "rows": len(raw_rows),
        "csv_path": str(csv_path), "hdf5_path": str(hdf5_path), "units": units,
        "source_sha256": digest, "numeric_readback_exact": True,
        "source_rows_exact": True, "identity_units_and_source_binding_verified": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    run_dir = args.run_dir.resolve()
    report = {"status": "failed", "cases": [], "errors": [],
              "checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8-sig"))
        cases = manifest["cases"]
        require(isinstance(cases, list) and len(cases) > 0, "run.json must contain cases")
        identities = [case["sample_id"] for case in cases]
        require(all(isinstance(value, str) and value.strip() for value in identities),
                "every case requires a nonempty sample identity")
        require(len(identities) == len(set(identities)), "duplicate case sample identities")
        for case in cases:
            try:
                report["cases"].append(verify_case(case, run_dir))
            except Exception as exc:
                report["cases"].append({"sample_id": case.get("sample_id"),
                                         "status": "failed", "error": str(exc)})
                report["errors"].append(f"{case.get('sample_id')}: {type(exc).__name__}: {exc}")
        if not report["errors"]:
            report["status"] = "passed"
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    (run_dir / "verify_readback.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
