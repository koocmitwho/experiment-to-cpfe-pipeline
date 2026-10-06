"""Regressions for the three-specimen reproduction, with independent values."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

import importlib.util

CASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tensile_workflow", CASE / "workflow.py")
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)
analyze_curve = workflow.analyze_curve
create_run_directory = workflow.create_run_directory
verify_source_files = workflow.verify_source_files

ROOT = CASE


@pytest.mark.parametrize("specimen,uts,modulus,proof", [
    ("test_ID_055", 277.080919182671, 63702.735621, 251.965967),
    ("test_ID_056", 277.834142, 54345.384124, 252.887487),
    ("test_ID_057", 280.209188, 65257.004794, 254.024472),
])
def test_full_curve_peak_and_author_window_match_independent_calculation(specimen, uts, modulus, proof):
    raw = pd.read_csv(ROOT / "data" / f"{specimen}.csv")
    before = raw.copy(deep=True)
    result = analyze_curve(raw, specimen)
    assert result["metrics"]["UTS_MPa"] == pytest.approx(uts, abs=1e-6)
    assert result["metrics"]["E_MPa"] == pytest.approx(modulus, abs=1e-5)
    assert result["metrics"]["Rp02_MPa"] == pytest.approx(proof, abs=1e-6)
    # Cropping the source or silently changing stress must break this test.
    pd.testing.assert_frame_equal(raw, before)
    assert len(result["corrected_full"]) == len(raw)
    np.testing.assert_array_equal(result["corrected_full"]["Stress_MPa"], raw["Stress_MPa"])
    assert result["metrics"]["proof_crossings"] == 1


def test_nonfinite_input_does_not_become_a_plausible_material_property():
    raw = pd.read_csv(ROOT / "data" / "test_ID_055.csv")
    raw.loc[3, "Stress_MPa"] = np.nan
    with pytest.raises(ValueError, match="finite"):
        analyze_curve(raw, "invalid")


def test_changed_input_is_rejected_before_reproduction(tmp_path):
    import hashlib
    source = tmp_path / "curve.csv"
    source.write_bytes(b"Strain,Stress_MPa\n0,0\n")
    manifest = [{"filename": "curve.csv", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]
    verify_source_files(tmp_path, manifest)
    source.write_bytes(b"Strain,Stress_MPa\n0,999\n")
    with pytest.raises(ValueError, match="hash"):
        verify_source_files(tmp_path, manifest)


def test_rerun_never_overwrites_existing_results(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "user-result.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_run_directory(target)
    assert marker.read_text(encoding="utf-8") == "keep"
