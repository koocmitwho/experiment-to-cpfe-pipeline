"""Execution exit codes and scientific findings remain independently observable."""

import json
import subprocess
import sys

import pytest

from test_evaluation_protocol import add_metric, fixture_config, write_config


@pytest.mark.parametrize("finding", ["met", "not_met", "missing_axis"])
def test_completed_protocol_audit_returns_zero_and_preserves_findings(tmp_path, finding):
    config = fixture_config()
    add_metric(tmp_path, config, value=4.0 if finding == "not_met" else 2.5)
    if finding == "missing_axis":
        del config["cases"][-1]["axes"]["lot"]
    config_path = write_config(tmp_path, config)
    destination = tmp_path / "report"
    result = subprocess.run(
        [sys.executable, "-m", "experiment_to_cpfe.cli", "check-evaluation-protocol",
         "--config", str(config_path), "--run-dir", str(destination)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report == json.loads((destination / "evaluation-protocol.json").read_text())
    assert report["metric_evidence"][0]["threshold_status"] == ("not_met" if finding == "not_met" else "met")
    assert report["holdout_status"] == ("not_verified" if finding == "missing_axis" else "metadata_supported")
    assert report["scientific_claim_status"] == "not_established_by_metadata"


@pytest.mark.parametrize("failure", ["missing_config", "changed_evidence"])
def test_protocol_execution_errors_return_one_without_a_report(tmp_path, failure):
    config = fixture_config()
    evidence = add_metric(tmp_path, config)
    config_path = write_config(tmp_path, config)
    if failure == "missing_config":
        config_path = tmp_path / "missing.json"
    else:
        evidence.write_text("{}")
    destination = tmp_path / "report"
    result = subprocess.run(
        [sys.executable, "-m", "experiment_to_cpfe.cli", "check-evaluation-protocol",
         "--config", str(config_path), "--run-dir", str(destination)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert result.stderr.strip()
    assert not destination.exists()
