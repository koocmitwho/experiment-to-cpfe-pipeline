"""Exercise the documented case against the installed public distribution."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd


CASE = Path(__file__).resolve().parents[1]


def test_public_installed_package_runs_from_another_directory_without_changing_inputs(tmp_path):
    # A checkout injection, local-only asset, changed source or overwritten run
    # must fail this user-level test even if isolated helpers still pass.
    data = CASE / "data"
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in data.glob("*") if path.is_file()}
    run_dir = tmp_path / "portable run"
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONUTF8"] = "1"
    command = [sys.executable, "-I", "-X", "utf8", "-B", str(CASE / "workflow.py"),
               "--run-dir", str(run_dir)]
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "completed"
    assert receipt["total_rows"] == 1889
    assert receipt["cases_processed"] == 3
    assert receipt["independent_readback_passed"] is True
    assert receipt["source_hashes_unchanged"] is True
    assert "site-packages" in Path(receipt["pipeline"]["module_path"]).parts
    assert receipt["pipeline"]["version"]
    assert len(receipt["pipeline"]["normalization_sha256"]) == 64
    comparison = pd.read_csv(run_dir / "metrics_comparison.csv")
    assert len(comparison) == 9
    np.testing.assert_array_equal(comparison.pipeline_minus_direct, np.zeros(9))
    assert np.max(np.abs(comparison.minus_independent)) < 1e-7
    for filename in ["curves.png", "curves.pdf", "proof_stress.png", "proof_stress.pdf"]:
        assert (run_dir / filename).stat().st_size > 1000
    readback = json.loads((run_dir / "verify_readback.json").read_text(encoding="utf-8"))
    assert readback["status"] == "passed"
    assert len(readback["cases"]) == 3
    assert before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in data.iterdir() if path.is_file()}
    saved = {str(path.relative_to(run_dir)): path.read_bytes()
             for path in run_dir.rglob("*") if path.is_file()}
    repeated = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=180)
    assert repeated.returncode != 0
    assert saved == {str(path.relative_to(run_dir)): path.read_bytes()
                     for path in run_dir.rglob("*") if path.is_file()}
