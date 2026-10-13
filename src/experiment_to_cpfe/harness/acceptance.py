"""Independent, read-only evidence acceptance; execution is not scientific success."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import h5py
import numpy as np

from experiment_to_cpfe.harness.workflows.paramaterial import (
    IDS, ROWS, UNITS, PROCESSING_SHA256, _json, _sha, inspect_case,
)


ATOL = 1e-7
METRICS = ("UTS_MPa", "E_MPa", "Rp02_MPa")
NORMALIZATION_SHA256 = "ffc15906cbf45fd1df212268d4cdbc21fc59f91cd104ba08d0d801c5657e2b94"


def _file(root, relative):
    root, path = Path(root).resolve(), Path(root) / relative
    if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise ValueError("required regular artifact is absent or outside its root")
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("fixed-case artifact exceeds size bound")
    return path


def _table(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("invalid CSV column identity")
        return list(reader)


def _finite(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not a metric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("metric is not finite")
    return result


def _safe_hdf5(handle):
    """Do not dereference HDF5 links, VDS or external dataset storage."""
    seen = set()

    def visit(group):
        address = h5py.h5o.get_info(group.id).addr
        if address in seen:
            return
        seen.add(address)
        for name in group:
            if not isinstance(group.get(name, getlink=True), h5py.HardLink):
                raise ValueError("HDF5 links are not accepted")
            item = group[name]
            if isinstance(item, h5py.Group):
                visit(item)
            elif item.is_virtual or item.external:
                raise ValueError("HDF5 external storage is not accepted")
    visit(handle)


def accept_case(case_dir: Path, output_dir: Path) -> dict:
    """Check the fixed three-specimen evidence without trusting its pass flags.

    Uses pinned source/reference bytes, direct CSV/HDF5 readback and all nine
    numerical criteria. No scientific code is executed and no files are written.
    """
    root, output = Path(case_dir).resolve(), Path(output_dir).resolve()
    inspection = inspect_case(root)
    issues, criteria, semantic = [], [], []
    report = {
        "format": "experiment-to-cpfe-harness-acceptance-1",
        "execution_status": "unknown", "engineering_status": "passed", "data_status": "passed",
        "numerical_checks": {"status": "not_evaluated", "absolute_tolerance": ATOL,
                             "mesh_jacobian_solver_terminal": "not_applicable"},
        "protocol_status": "valid" if inspection["valid"] else "invalid",
        "criterion_results": criteria, "scientific_claim_status": "not_established",
        "overall_acceptance": "rejected", "semantic_sha256": None, "issues": issues,
        "scope_limits": ["Fixed AA6061-T651 20 C lot A three-specimen transfer and calculation reproduction.",
                         "Independent arithmetic references are not author per-specimen truth.",
                         "No solver, training, calibration, physical validation or generalization claim."],
    }

    def check(condition, layer, code, field):
        if not condition:
            report[f"{layer}_status"] = "failed"
            issues.append({"code": code, "field": field, "safe_message": "Saved evidence did not satisfy the frozen case contract."})
        return bool(condition)

    if not inspection["valid"]:
        report["data_status"] = "failed"
        issues.extend(inspection["issues"])
        return report
    manifest = _json(root / "data/manifest.json")
    reference = {row["sample_id"]: row for row in _json(root / "data/reference_metrics.json")["specimens"]}
    try:
        run = _json(_file(output, "run.json"))
        state = run.get("status")
        report["execution_status"] = state if state in ("completed", "failed", "interrupted", "running") else "unknown"
        check(state == "completed", "engineering", "EXECUTION_NOT_COMPLETED", "run.status")
        check(run.get("training_executed") is False and run.get("solver_executed") is False,
              "engineering", "EXECUTION_SCOPE_MISMATCH", "run")
        cases = run.get("cases", [])
        check(isinstance(cases, list) and [item.get("sample_id") for item in cases] == list(IDS),
              "data", "SPECIMEN_SET_MISMATCH", "run.cases")
        check(run.get("total_rows") == 1889 and run.get("cases_processed") == 3,
              "data", "ROW_COUNT_MISMATCH", "run.total_rows")
        expected_sources = {Path(name).name: value for name, value in inspection["files"].items() if name.startswith("data/")}
        check(run.get("source_hashes") == expected_sources, "data", "SOURCE_HASH_MISMATCH", "run.source_hashes")
        check(run.get("processing_sha256") == PROCESSING_SHA256 and run.get("paramaterial_version") == "0.1.0",
              "engineering", "CODE_IDENTITY_MISMATCH", "run.processing_sha256")
        check(run.get("pipeline", {}).get("normalization_sha256") == NORMALIZATION_SHA256,
              "engineering", "CODE_IDENTITY_MISMATCH", "run.pipeline.normalization_sha256")
        check(run.get("dataset") == manifest["dataset"] and run.get("examples_commit") == manifest["examples_commit"],
              "data", "SOURCE_CONTEXT_MISMATCH", "run.dataset")
        check(run.get("reference_kind") == "independent_recalculation_not_author_truth",
              "data", "REFERENCE_SCOPE_MISMATCH", "run.reference_kind")
        by_id = {item["sample_id"]: item for item in cases}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        check(False, "engineering", "RUN_EVIDENCE_INVALID", "run.json")
        return report

    # Read outputs by fixed registered locations, never follow paths from receipts.
    for identity, expected_rows in zip(manifest["specimens"], ROWS):
        sample_id = identity["sample_id"]
        try:
            case = by_id[sample_id]
            raw_path = _file(root, f"data/{sample_id}.csv")
            h5_path = _file(output, f"normalized/{sample_id}/sample.h5")
            check(Path(case["csv_path"]).resolve() == raw_path.resolve()
                  and Path(case["hdf5_path"]).resolve() == h5_path.resolve(),
                  "data", "ARTIFACT_BINDING_MISMATCH", sample_id)
            check(case["units"] == UNITS and case["rows"] == expected_rows,
                  "data", "IDENTITY_UNITS_MISMATCH", sample_id)
            receipt = _json(_file(output, f"normalized/{sample_id}/normalization.json"))
            recorded = receipt["artifacts"]["sample.h5"]
            check(receipt.get("status") == "completed" and receipt.get("solver_readiness_assessed") is False,
                  "engineering", "NORMALIZATION_NOT_COMPLETED", sample_id)
            check(recorded.get("sha256") == _sha(h5_path) and recorded.get("bytes") == h5_path.stat().st_size,
                  "engineering", "ARTIFACT_HASH_MISMATCH", sample_id)
            config_path = _file(output, f"configs/{sample_id}.json")
            check(receipt.get("configuration_sha256") == _sha(config_path),
                  "engineering", "CONFIG_HASH_MISMATCH", sample_id)
            check(receipt.get("inputs") == [{"path": str(raw_path), "sha256": identity["sha256"]}],
                  "data", "INPUT_BINDING_MISMATCH", sample_id)
            raw = _table(raw_path)
            expected = np.array([[_finite(row[name]) for name in UNITS] for row in raw])
            source_rows = np.arange(2, expected_rows + 2)
            with h5py.File(h5_path, "r") as handle:
                _safe_hdf5(handle)
                table = handle["measured/measured_observations"]
                columns = table["columns"]
                actual = np.column_stack([columns[name][:] for name in UNITS])
                check(actual.shape == (expected_rows, 2) and np.array_equal(actual, expected)
                      and np.array_equal(columns["source_row"][:], source_rows),
                      "data", "NUMERIC_READBACK_MISMATCH", sample_id)
                metadata = json.loads(handle["meta/sample_metadata_json"][()])
                check(metadata["sample_id"] == sample_id and metadata["unit_system"] == UNITS,
                      "data", "IDENTITY_UNITS_MISMATCH", sample_id)
                check(any(item.get("sha256") == identity["sha256"] and item.get("kind") == "measured"
                          and item.get("role") == "measured_observations" for item in metadata["sources"]),
                      "data", "SOURCE_BINDING_MISMATCH", sample_id)
                records = json.loads(table["records_json"][()])
                bound = {item["source_asset_id"] for item in records}
                if len(bound) != 1:
                    raise ValueError("ambiguous row source")
                source_id = next(iter(bound))
                asset = json.loads(handle["assets"][source_id].attrs["metadata_json"])
                check(asset["asset_id"] == source_id and asset["parent_asset_id"] is None
                      and asset["layer"] == "raw" and asset["source_kind"] == "measured"
                      and asset["sha256"] == identity["sha256"] and asset["units"] == UNITS,
                      "data", "SOURCE_BINDING_MISMATCH", sample_id)
                check(len(records) == expected_rows and all(item["source_kind"] == "measured" for item in records)
                      and np.array_equal([item["source_row"] for item in records], source_rows)
                      and np.array_equal([[item[name] for name in UNITS] for item in records], expected),
                      "data", "ROW_BINDING_MISMATCH", sample_id)
            semantic.append({"sample_id": sample_id, "units": UNITS, "source_sha256": identity["sha256"],
                             "source_rows": source_rows.tolist(), "values": expected.tolist()})
        except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError):
            check(False, "data", "SAMPLE_EVIDENCE_INVALID", sample_id)

    try:
        rows = _table(_file(output, "metrics.csv"))
        comparisons = _table(_file(output, "metrics_comparison.csv"))
        check([row["sample_id"] for row in rows] == list(IDS), "data", "METRIC_SET_MISMATCH", "metrics.csv")
        metrics = {row["sample_id"]: row for row in rows}
        expected_keys = {(sample_id, metric) for sample_id in IDS for metric in METRICS}
        keys = [(row["sample_id"], row["metric"]) for row in comparisons]
        check(len(keys) == 9 and set(keys) == expected_keys, "data", "METRIC_SET_MISMATCH", "metrics_comparison.csv")
        comparison = {(row["sample_id"], row["metric"]): row for row in comparisons}
        for sample_id, expected_rows in zip(IDS, ROWS):
            curve = _table(_file(output, f"curves/{sample_id}.csv"))
            raw = _table(_file(root, f"data/{sample_id}.csv"))
            offset = _finite(metrics[sample_id]["added_strain_offset"])
            check(len(curve) == expected_rows and all(
                _finite(saved["source_row"]) == index + 2
                and _finite(saved["original_strain"]) == _finite(original["Strain"])
                and _finite(saved["engineering_stress_MPa"]) == _finite(original["Stress_MPa"])
                and math.isclose(_finite(saved["corrected_strain"]), _finite(original["Strain"]) + offset,
                                 rel_tol=0, abs_tol=1e-12)
                and saved["in_author_window"] == str(_finite(original["Strain"]) < 0.01)
                for index, (saved, original) in enumerate(zip(curve, raw))),
                "data", "DERIVED_CURVE_MISMATCH", sample_id)
            for name in METRICS:
                value, expected = _finite(metrics[sample_id][name]), _finite(reference[sample_id][name])
                item = comparison[(sample_id, name)]
                direct, readback = _finite(item["direct_author_method"]), _finite(item["pipeline_readback_method"])
                bound = (_finite(item["independent_recalculation"]) == expected
                         and direct == readback == value and _finite(item["pipeline_minus_direct"]) == 0
                         and math.isclose(_finite(item["minus_independent"]), value - expected, rel_tol=0, abs_tol=1e-12))
                met = abs(value - expected) <= ATOL and bound
                criteria.append({"criterion_id": f"{sample_id}.{name}", "value": value, "reference": expected,
                                 "unit": "MPa", "absolute_tolerance": ATOL, "status": "met" if met else "not_met"})
        report["numerical_checks"]["status"] = "passed" if all(item["status"] == "met" for item in criteria) else "failed"
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        check(False, "data", "METRIC_EVIDENCE_INVALID", "metrics")
        report["numerical_checks"]["status"] = "failed"

    try:
        verifier = _json(_file(output, "verify_readback.json"))
        check(verifier["status"] == "passed" and verifier["errors"] == []
              and [item["sample_id"] for item in verifier["cases"]] == list(IDS)
              and all(item["status"] == "passed" for item in verifier["cases"]),
              "engineering", "VERIFICATION_RECEIPT_INVALID", "verify_readback.json")
        for name in ("curves.png", "proof_stress.png", "curves.pdf", "proof_stress.pdf"):
            check(_file(output, name).stat().st_size > 1000, "engineering", "REPORT_ARTIFACT_INVALID", name)
    except (OSError, ValueError, TypeError, KeyError):
        check(False, "engineering", "VERIFICATION_EVIDENCE_INVALID", "report_artifacts")

    if not issues and len(criteria) == 9 and report["numerical_checks"]["status"] == "passed":
        report["overall_acceptance"] = "accepted"
        payload = {"version": 1, "specimens": semantic, "criteria": criteria,
                   "processing_sha256": PROCESSING_SHA256, "source_files": inspection["files"]}
        report["semantic_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False,
                                                               separators=(",", ":")).encode()).hexdigest()
    return report


def evaluate_protocol_report(report: dict) -> dict:
    """Interpret existing check-evaluation-protocol evidence, independent of exit 0.

    This does not rerun or authenticate a protocol report's evidence files. The
    caller must bind it to a registered artifact and frozen protocol first.
    """
    valid = (isinstance(report, dict) and report.get("format") == "experiment-to-cpfe-evaluation-protocol-1"
             and isinstance(report.get("metric_evidence"), list)
             and report.get("holdout_status") in ("metadata_supported", "not_verified")
             and report.get("scientific_claim_status") == "not_established_by_metadata")
    metrics = report.get("metric_evidence", []) if isinstance(report, dict) else []
    criteria = []
    if valid:
        for metric in metrics:
            if not isinstance(metric, dict) or metric.get("threshold_status") not in ("met", "not_met", "not_requested"):
                valid = False
                break
            try:
                _finite(metric["value"])
                if not metric.get("metric_id") or not metric.get("unit"):
                    raise ValueError("missing metric identity")
                criteria.append({"criterion_id": metric["metric_id"], "status": metric["threshold_status"],
                                 "value": metric["value"], "unit": metric["unit"]})
            except (KeyError, ValueError, TypeError):
                valid = False
    statuses = [item["status"] for item in criteria]
    if not valid:
        outcome = "blocked"
    elif "not_met" in statuses:
        outcome = "rejected"
    elif not statuses or "not_requested" in statuses:
        outcome = "not_evaluated"
    elif report["holdout_status"] != "metadata_supported":
        outcome = "blocked"
    else:
        outcome = "criteria_met"
    return {"execution_status": "completed" if valid else "unknown", "protocol_status": "valid" if valid else "invalid",
            "criterion_results": criteria, "holdout_status": report.get("holdout_status", "unknown") if isinstance(report, dict) else "unknown",
            "scientific_claim_status": "not_established_by_metadata", "overall_acceptance": outcome,
            "evidence_authentication": "caller_must_verify_registered_artifact",
            "scope_limits": report.get("scope_limits", []) if isinstance(report, dict) else []}
