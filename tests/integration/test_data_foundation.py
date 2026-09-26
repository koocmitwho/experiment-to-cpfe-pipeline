"""A data-only release must run without training libraries or local research inputs."""

import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest


@pytest.mark.parametrize("command", [
    "normalize-sample", "import-experiment-file", "check-evaluation-protocol", "check-intake-status",
])
def test_data_commands_report_missing_configuration_as_an_execution_failure(command, tmp_path, capsys):
    from experiment_to_cpfe.cli import main

    result = main([command, "--config", str(tmp_path / "missing.json"),
                   "--run-dir", str(tmp_path / "run")])
    assert result == 1
    assert "missing.json" in capsys.readouterr().err


def test_synthetic_data_workflow_preserves_values_and_audits_declarations_without_torch(tmp_path):
    script = Path("examples/data_foundation/workflow.py").resolve()
    code = """
import importlib.abc, runpy, sys
class DataOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'torch_geometric', 'torchvision'}:
            raise AssertionError('data demonstration imported a training library: ' + fullname)
sys.meta_path.insert(0, DataOnly())
sys.argv = [sys.argv[1], '--run-dir', sys.argv[2]]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    env = {**os.environ, "PYTHONPATH": str(Path("src").resolve()), "PYTHONUTF8": "1"}
    run = tmp_path / "data-demo"
    result = subprocess.run([sys.executable, "-B", "-c", code, str(script), str(run)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((run / "verification.json").read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    assert summary["evidence_scope"] == "synthetic_mechanism_only"
    assert summary["training_executed"] is False
    assert summary["solver_executed"] is False
    assert summary["checks"]["future_input_rejected"] is True
    assert summary["checks"]["group_overlap_rejected"] is True
    with np.load(run / "dataset/dataset.npz", allow_pickle=False) as arrays:
        np.testing.assert_array_equal(arrays["features"].ravel(), [0, 1, 2, 3] * 3)
        np.testing.assert_allclose(arrays["targets"].ravel(), [0, 2, 4, 6, .1, 2.1, 4.1, 6.1, .2, 2.2, 4.2, 6.2])
        assert arrays["splits"].tolist() == ["train"] * 8 + ["validation"] * 4
    protocol = json.loads((run / "protocol/evaluation-protocol.json").read_text(encoding="utf-8"))
    assert protocol["counts"]["unique_conditions"] == 3
    assert protocol["counts"]["statistical_groups"] == 3
    assert protocol["counts"]["expanded_records"] == 12
    assert protocol["scientific_claim_status"] == "not_established_by_metadata"
    intake = json.loads((run / "intake/intake-status.json").read_text(encoding="utf-8"))
    assert intake["scientific_validity"] == "not_assessed"
    assert intake["downstream_execution"] == "not_started"
    from experiment_to_cpfe.datasets.hdf5 import read_hdf5
    sample = read_hdf5(run / "imports/specimen-a/sample.h5")
    assert sample.solver_inputs["experiment_context"]["raw_metadata"]["unknown_header"] == {"fixture": "preserved"}
    assert all(asset.source_kind.value == "input" for asset in sample.assets)
    # A second call must leave the first complete result untouched.
    before = (run / "verification.json").read_bytes()
    repeated = subprocess.run([sys.executable, "-B", str(script), "--run-dir", str(run)],
                              cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
    assert repeated.returncode != 0
    assert (run / "verification.json").read_bytes() == before
