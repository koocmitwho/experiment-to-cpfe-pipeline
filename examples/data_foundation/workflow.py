"""Small synthetic data workflow; no training library, solver or external dataset."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from experiment_to_cpfe.cli import main as pipeline
from experiment_to_cpfe.datasets.hdf5 import read_hdf5
from experiment_to_cpfe.datasets.training import build_training_dataset


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return path


def reference(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def declared(value):
    return {"status": "confirmed", "value": value, "evidence": "Explicit synthetic fixture declaration"}


def run_stage(command, config, output):
    if pipeline([command, "--config", str(config), "--run-dir", str(output)]) != 0:
        raise RuntimeError(f"{command} failed; inspect {output}")


def prepare_raw(root, name, index):
    units = {"row_id": "1", "command": "1", "force": "N"}
    sample = {"sample_id": name, "experiment_id": f"batch-{index}",
              "microstructure_id": "not-characterized", "load_path_id": "synthetic-ramp",
              "schema_version": "0.1", "coordinate": {"name": "scalar", "axes": ["row"], "units": "1"},
              "unit_system": units, "tensor_order": ["scalar"],
              "orientation": {"representation": "not_applicable", "reason": "Synthetic scalar formula"}}
    raw = save(root / "inputs" / f"{name}.json", {
        "format": "self-describing-experiment-1", "sample": sample,
        "context": {"sample_id": declared(name), "batch_id": declared(f"batch-{index}"),
                    "preload": {"status": "not_applicable", "evidence": "Algebraic fixture has no preload"}},
        "measurements": {"units": units, "rows": [
            {"row_id": str(i), "command": float(i), "force": 2.0 * i + 0.1 * index} for i in range(4)]},
        "unknown_header": {"fixture": "preserved"},
    })
    config = save(root / "configs" / f"{name}.json", {
        "version": 1, "purpose": "Preserve a synthetic file and its explicit declarations",
        "profile": "self_describing_json_v1", "source": reference(raw), "license": "synthetic",
        "evidence_scope": "synthetic_mechanism_only",
    })
    return config, sample


def task_contract():
    return {
        "version": 1, "purpose": "Check synthetic force data declarations", "data_kind": "synthetic",
        "prediction_time": {"value": 0.0, "unit": "s", "reference": "loading start"},
        "inputs": {"command": {"source": "prescribed command", "role": "predictor", "availability": "confirmed",
                               "available_at": 0.0, "evidence": "Command schedule is defined before loading"}},
        "targets": {"force": {"quantity": "force", "unit": "N", "entity": "specimen",
                              "spatial_support": "whole specimen", "coordinate_frame": "scalar",
                              "component_convention": "scalar axial force",
                              "time_window": {"start": 0.0, "stop": 3.0, "unit": "s", "reference": "loading start"},
                              "basis": "Algebraic fixture: force = 2 * command + 0.1 * specimen_index"}},
        "context_requirements": {"preload": ["not_applicable"]},
        "independence_axes": {"batch": "/sample_metadata/experiment_id"},
    }


def expect_rejection(config, root, message):
    try:
        build_training_dataset(config, base_dir=root)
    except ValueError as exc:
        if message not in str(exc):
            raise
        return True
    raise AssertionError(f"Invalid declaration was accepted: {message}")


def run(root):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    names = ["specimen-a", "specimen-b", "specimen-c"]
    inputs, cases = [], []
    for index, name in enumerate(names):
        config, sample = prepare_raw(root, name, index)
        imported = root / "imports" / name
        run_stage("import-experiment-file", config, imported)
        restored = read_hdf5(imported / "sample.h5")
        assert restored.solver_inputs["experiment_context"]["raw_metadata"]["unknown_header"] == {"fixture": "preserved"}
        split = "train" if index < 2 else "validation"
        inputs.append({"path": str(imported / "sample.h5"), "sample_id": name, "layout": "table", "split": split})
        cases.append({"case_id": name, "identity": {"specimen": name, "load": "synthetic-ramp"},
                      "group_id": sample["experiment_id"], "split": split,
                      "axes": {"batch": sample["experiment_id"]}, "records": [str(i) for i in range(4)]})

    # Demonstrate the ordinary declared-file path independently of the JSON adapter.
    rows = root / "inputs" / "declared-table.csv"
    rows.write_text("row_id,command,force\n0,0,0\n1,1,2\n", encoding="utf-8")
    normal = save(root / "configs" / "normalize.json", {
        "version": 1, "purpose": "Synthetic table normalization without a solver", "sample": sample,
        "sources": [{"path": str(rows), "table_name": "measured_observations", "source_kind": "input",
                     "modality": "time_series", "format": "csv", "delimiter": ",", "encoding": "utf-8",
                     "column_map": {key: key for key in ("row_id", "command", "force")},
                     "units": {"row_id": "1", "command": "1", "force": "N"}, "coordinate_frame": "scalar",
                     "axis_order": ["row"], "native_layout": "synthetic named CSV rows", "license": "synthetic"}],
    })
    run_stage("normalize-sample", normal, root / "normalized")

    build = {"version": 2, "features": [{"name": "command", "unit": "1"}],
             "targets": [{"name": "force", "unit": "N"}], "group_by": "experiment_id",
             "grouping_evidence": "Three separately generated synthetic batches; no physical independence claim",
             "layouts": {"table": {"alignment_evidence": "Explicit row_id within each specimen", "columns": {
                 name: {"kind": "table", "table": "measured_observations", "column": name,
                        "source_unit": unit, "id_columns": ["row_id"]} for name, unit in [("command", "1"), ("force", "N")]
             }}}, "inputs": inputs, "task_contract": task_contract()}
    build_path = save(root / "configs" / "build.json", build)
    run_stage("build-training-dataset", build_path, root / "dataset")
    invalid_time = copy.deepcopy(build)
    invalid_time["task_contract"]["inputs"]["command"]["available_at"] = 1.0
    invalid_group = copy.deepcopy(build)
    invalid_group["group_by"] = "explicit"
    for item in invalid_group["inputs"]:
        item["group_id"] = "same-group"
    checks = {"future_input_rejected": expect_rejection(invalid_time, root, "prediction time"),
              "group_overlap_rejected": expect_rejection(invalid_group, root, "multiple dataset splits")}

    protocol = save(root / "configs" / "protocol.json", {
        "version": 1, "purpose": "Count the generated synthetic data", "claim": "Declared batch separation only",
        "population": "Three synthetic specimens", "data_kind": "synthetic", "declaration_timing": "retrospective",
        "identity_definition": "Specimen plus synthetic loading programme", "group_definition": "Declared batch identity",
        "record_unit": "scalar row", "holdout_axes": ["batch"],
        "scope_limits": ["Algebraically generated specimens for data-processing and grouping checks"], "cases": cases,
    })
    run_stage("check-evaluation-protocol", protocol, root / "protocol")
    review = save(root / "synthetic-review.json", {"scope": "synthetic_mechanism_only",
        "basis": "Generated declarations and HDF5 readback checked by the automated synthetic workflow"})
    intake = save(root / "configs" / "intake.json", {
        "version": 1, "handoff_id": "synthetic-data-foundation", "purpose": "Demonstrate explicit handoff declarations",
        "evidence_scope": "synthetic_mechanism_only", "checkpoints": [{"id": "raw_to_semantics", "status": "ready",
            "reviewer": "Automated synthetic demonstration", "basis": "Generated declarations and readback checked",
            "conditions": [], "blockers": [], "evidence": [reference(review)]}],
    })
    run_stage("check-intake-status", intake, root / "intake")
    with np.load(root / "dataset" / "dataset.npz", allow_pickle=False) as dataset:
        assert dataset["features"].shape == (12, 1)
        assert dataset["targets"].shape == (12, 1)
    summary = {"status": "completed", "evidence_scope": "synthetic_mechanism_only", "specimens": 3, "rows": 12,
               "training_executed": False, "solver_executed": False, "checks": checks,
               "scientific_validity": "not_established_by_software_checks"}
    save(root / "verification.json", summary)
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True, help="New output directory; existing results are never replaced")
    run(parser.parse_args().run_dir)
