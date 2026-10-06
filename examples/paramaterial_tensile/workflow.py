"""Reproduce three fixed tensile specimens through the installed public pipeline.

All scientific processing calls the unmodified Paramaterial 0.1.0 package.
The case starts from author-provided engineering stress/strain CSV files.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

import h5py
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
IDS = ("test_ID_055", "test_ID_056", "test_ID_057")
UNITS = {"Strain": "1", "Stress_MPa": "MPa"}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_source_files(root, manifest):
    for entry in manifest:
        path = Path(root) / entry["filename"]
        if digest(path).lower() != entry["sha256"].lower():
            raise ValueError(f"source hash mismatch: {path}")


def create_run_directory(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def analyze_curve(raw, specimen):
    """Use author ordering, original 1% window, 36 MPa preload and proof rule."""
    if list(raw.columns) != ["Strain", "Stress_MPa"]:
        raise ValueError("expected original engineering strain/stress columns")
    if len(raw) < 10 or not np.isfinite(raw.to_numpy(dtype=float)).all():
        raise ValueError("curve must contain sufficient finite numeric values")
    if importlib.metadata.version("paramaterial") != "0.1.0":
        raise ValueError("this reproduction requires paramaterial 0.1.0")
    import paramaterial as pm
    from paramaterial import processing as proc

    ds = pm.DataSet()
    ds.data_items = [pm.DataItem(specimen, raw.copy(deep=True), pd.Series({"test_id": specimen}))]
    ds = proc.find_UTS(ds)
    ds = proc.find_fracture_point(ds)

    def author_window(di):
        di.data = di.data.loc[di.data["Strain"] < 0.01].copy()
        return di

    windowed = ds.apply(author_window)
    # Restore NumPy's error mode after the upstream function changes it.
    with np.errstate(all="ignore"):
        elastic = proc.find_upl_and_lpl(windowed, preload=36, preload_key="Stress_MPa")
        corrected = proc.correct_foot(elastic, LPL_key="LPL", UPL_key="UPL")
        processed = proc.find_proof_stress(corrected, proof_strain=0.002,
                                           E_key="E", strain_key="Strain", stress_key="Stress_MPa")
    info = processed.data_items[0].info
    small = processed.data_items[0].data.copy()
    residual = info["E"] * (small["Strain"].to_numpy() - 0.002) - small["Stress_MPa"].to_numpy()
    crossings = int(np.count_nonzero(np.diff(np.sign(residual))))
    metrics = {
        "UTS_MPa": float(info["UTS_1"]), "E_MPa": float(info["E"]),
        "E_GPa": float(info["E"]) / 1000, "Rp02_MPa": float(info["PS_0.002_1"]),
        "proof_corrected_strain": float(info["PS_0.002_0"]),
        "UTS_original_strain": float(info["UTS_0"]),
        "added_strain_offset": float(info["foot correction"]),
        "LPL_corrected_strain": float(info["LPL_0"]), "LPL_MPa": float(info["LPL_1"]),
        "UPL_corrected_strain": float(info["UPL_0"]), "UPL_MPa": float(info["UPL_1"]),
        "raw_rows": len(raw), "author_window_rows": len(small), "proof_crossings": crossings,
    }
    if not np.isfinite(list(metrics.values())).all() or metrics["E_MPa"] <= 0 or crossings != 1:
        raise ValueError(f"ambiguous or nonfinite author-method output for {specimen}")
    full = raw.copy(deep=True)
    full["Strain"] = full["Strain"] + metrics["added_strain_offset"]
    return {"metrics": metrics, "corrected_full": full, "author_window": small}


def normalization_config(identity, csv_path, source_url):
    specimen = identity["sample_id"]
    return {
        "version": 1, "purpose": "Three fixed AA6061-T651 specimens: original engineering curves",
        "sample": {
            "sample_id": specimen, "experiment_id": "doi:10.17632/rd6jm9tyb6.2",
            "microstructure_id": "not-independently-characterized",
            "load_path_id": "uniaxial-tension-20C", "schema_version": "0.1",
            "coordinate": {"name": "instrument-record", "axes": ["row"], "units": "1"},
            "unit_system": UNITS, "tensor_order": ["scalar"],
            "orientation": {"representation": "not_applicable", "reason": "Scalar tensile curves"},
        },
        "sources": [{
            "path": str(csv_path), "table_name": "measured_observations",
            "source_kind": "measured", "modality": "time_series", "format": "csv",
            "delimiter": ",", "encoding": "utf-8",
            "column_map": {"Strain": "0", "Stress_MPa": "1"}, "units": UNITS,
            "coordinate_frame": "instrument-record", "axis_order": ["row"],
            "native_layout": "Author-provided engineering strain/stress; original rows and order",
            "license": "CC-BY-4.0",
            "block": {"data_start_row": 2, "data_end_row": identity["rows"] + 2,
                      "numeric_fields": ["Strain", "Stress_MPa"],
                      "header_checks": [{"row": 1, "column": 0, "value": "Strain"},
                                        {"row": 1, "column": 1, "value": "Stress_MPa"}]},
        }],
        "solver_inputs": {"source_identity": {"sample": identity, "source_url": source_url},
                          "specimen_context": {"material": "AA6061-T651", "lot": "A", "temperature_C": 20},
                          "purpose": "Context only; no solver configured"},
    }


def plot_results(run_dir, cases, results):
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    plt.style.use("default")
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"],
                         "axes.unicode_minus": False, "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "savefig.facecolor": "white"})
    colors = ["#2563A6", "#D17828", "#39856A"]
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.7), layout="constrained")
    for case, result, color in zip(cases, results, colors):
        raw = result["raw"]
        axes[0].plot(raw.Strain * 100, raw.Stress_MPa, color=color, label=case["sample_id"][-3:], lw=1.7)
        full = result["pipeline"]["corrected_full"]
        axes[1].plot(full.Strain * 100, full.Stress_MPa, color=color, label=case["sample_id"][-3:], lw=1.7)
    for ax, title in zip(axes, ["Original engineering curves", "Full curves with small-window strain correction"]):
        ax.set(title=title, xlabel="Engineering strain / %", ylabel="Engineering stress / MPa")
        ax.grid(alpha=0.18); ax.legend(title="Specimen", frameon=False)
    fig.suptitle("AA6061-T651 | 20 C | Lot A | Three specimens", fontsize=14)
    for suffix in ["png", "pdf"]:
        fig.savefig(run_dir / f"curves.{suffix}", dpi=180)
    plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.6), layout="constrained")
    for ax, case, result, color in zip(axes, cases, results, colors):
        raw, processed = result["raw"], result["pipeline"]
        small, m = processed["author_window"], processed["metrics"]
        original = raw.loc[raw.Strain < 0.01]
        ax.plot(original.Strain * 100, original.Stress_MPa, "--", color="#A0A0A0", lw=1.2, label="Original")
        ax.plot(small.Strain * 100, small.Stress_MPa, color=color, lw=1.8, label="Foot corrected")
        x = np.linspace(0.002, m["proof_corrected_strain"] + 0.0005, 100)
        ax.plot(x * 100, m["E_MPa"] * (x - 0.002), ":", color="#333333", label="0.2% offset")
        ax.plot(m["proof_corrected_strain"] * 100, m["Rp02_MPa"], "o", color=color, ms=5)
        ax.plot([m["LPL_corrected_strain"] * 100, m["UPL_corrected_strain"] * 100],
                [m["LPL_MPa"], m["UPL_MPa"]], "s", markerfacecolor="white", markeredgecolor=color, ms=5)
        ax.set(title=f'{case["sample_id"][-3:]}: Rp0.2 = {m["Rp02_MPa"]:.2f} MPa',
               xlabel="Engineering strain / %", ylabel="Engineering stress / MPa", ylim=(-10, 290))
        ax.grid(alpha=0.18); ax.legend(fontsize=8, frameon=False, loc="lower right")
    fig.suptitle("Author window: original strain < 1%; squares mark proportional limits", fontsize=13)
    for suffix in ["png", "pdf"]:
        fig.savefig(run_dir / f"proof_stress.{suffix}", dpi=180)
    plt.close(fig)


def run_case(run_dir):
    manifest = read_json(DATA / "manifest.json")
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported data manifest schema")
    identities = manifest["specimens"]
    if tuple(i["sample_id"] for i in identities) != IDS:
        raise ValueError("fixed three-specimen identities do not match")
    for number, identity in enumerate(identities, start=1):
        if (identity["temperature_C"], identity["lot"], identity["specimen_number"]) != (20, "A", number):
            raise ValueError("specimen source metadata mismatch")
        if identity["filename"] != f'{identity["sample_id"]}.csv' or identity["units"] != UNITS:
            raise ValueError("specimen filename or units do not match the fixed case")
        if identity["screening"]["rejected"] is not False:
            raise ValueError("author screening does not accept this fixed specimen")
    verify_source_files(DATA, identities)
    reference = read_json(DATA / "reference_metrics.json")
    if reference["kind"] != "independent_recalculation_not_author_truth":
        raise ValueError("reference metrics must identify independent recalculation")
    if tuple(row["sample_id"] for row in reference["specimens"]) != IDS:
        raise ValueError("reference specimen identities do not match")
    independent = {row["sample_id"]: row for row in reference["specimens"]}
    if manifest["paramaterial"]["version"] != "0.1.0" or importlib.metadata.version("paramaterial") != "0.1.0":
        raise ValueError("this reproduction requires paramaterial 0.1.0")
    processing_module = importlib.import_module("paramaterial.processing")
    processing_path = Path(inspect.getsourcefile(processing_module)).resolve()
    expected_processing = manifest["paramaterial"]["processing_sha256"]
    if digest(processing_path) != expected_processing:
        raise ValueError("upstream processing code changed")
    from experiment_to_cpfe.datasets.normalization import run_normalization
    normalization_path = Path(inspect.getsourcefile(run_normalization)).resolve()
    pipeline = {"version": importlib.metadata.version("experiment-to-cpfe"),
                "module_path": str(normalization_path),
                "normalization_sha256": digest(normalization_path)}
    source_hashes = {filename: digest(DATA / filename) for filename in
                     ["manifest.json", "reference_metrics.json", *(row["filename"] for row in identities)]}
    out = create_run_directory(run_dir)
    for folder in ["configs", "normalized", "curves", "logs"]:
        (out / folder).mkdir()
    provenance = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "status": "running",
                  "pipeline": pipeline, "paramaterial_version": "0.1.0",
                  "processing_module_path": str(processing_path), "processing_sha256": digest(processing_path),
                  "source_hashes": source_hashes, "reference_kind": reference["kind"],
                  "dataset": manifest["dataset"], "examples_commit": manifest["examples_commit"],
                  "training_executed": False, "solver_executed": False, "cases": []}
    write_json(out / "run.json", provenance)
    started = time.perf_counter()
    results, metric_rows, comparisons = [], [], []
    try:
        for identity in identities:
            specimen = identity["sample_id"]
            csv_path = DATA / identity["filename"]
            raw = pd.read_csv(csv_path, float_precision="round_trip")
            if len(raw) != identity["rows"]:
                raise ValueError(f"source row count mismatch: {specimen}")
            direct = analyze_curve(raw, specimen)
            config = normalization_config(identity, csv_path, identity["upstream_url"])
            config_path = out / "configs" / f"{specimen}.json"
            write_json(config_path, config)
            receipt = run_normalization(config_path, out / "normalized" / specimen)
            if receipt["status"] != "completed" or receipt["solver_readiness_assessed"] is not False:
                raise RuntimeError(f"normalization failed: {receipt}")
            hdf5_path = out / "normalized" / specimen / "sample.h5"
            with h5py.File(hdf5_path, "r") as handle:
                columns = handle["measured/measured_observations/columns"]
                restored = pd.DataFrame({name: columns[name][:] for name in UNITS})
            via_pipeline = analyze_curve(restored, specimen)
            np.testing.assert_array_equal(raw.to_numpy(), restored.to_numpy())
            for metric in direct["metrics"]:
                if direct["metrics"][metric] != via_pipeline["metrics"][metric]:
                    raise ValueError(f"pipeline altered {specimen}/{metric}")
            for metric in ("UTS_MPa", "E_MPa", "Rp02_MPa"):
                calculated = via_pipeline["metrics"][metric]
                reference_value = independent[specimen][metric]
                if not np.isclose(calculated, reference_value, rtol=0, atol=1e-7):
                    raise ValueError(f"independent arithmetic mismatch: {specimen}/{metric}")
                comparisons.append({"sample_id": specimen, "metric": metric,
                                    "direct_author_method": direct["metrics"][metric], "pipeline_readback_method": calculated,
                                    "pipeline_minus_direct": calculated - direct["metrics"][metric],
                                    "independent_recalculation": reference_value, "minus_independent": calculated - reference_value})
            case = {"sample_id": specimen, "csv_path": str(csv_path), "hdf5_path": str(hdf5_path),
                    "rows": len(raw), "units": UNITS, "source_filename": identity["original_filename"]}
            provenance["cases"].append(case)
            metrics = {"sample_id": specimen, "temperature_C": 20, "lot": "A", **via_pipeline["metrics"]}
            metric_rows.append(metrics)
            corrected = via_pipeline["corrected_full"]
            pd.DataFrame({"source_row": np.arange(2, len(raw) + 2), "original_strain": raw.Strain,
                          "corrected_strain": corrected.Strain, "engineering_stress_MPa": raw.Stress_MPa,
                          "in_author_window": raw.Strain < 0.01}).to_csv(out / "curves" / f"{specimen}.csv", index=False)
            results.append({"raw": raw, "direct": direct, "pipeline": via_pipeline})
        pd.DataFrame(metric_rows).to_csv(out / "metrics.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(comparisons).to_csv(out / "metrics_comparison.csv", index=False, encoding="utf-8-sig")
        write_json(out / "run.json", provenance)
        command = [sys.executable, "-I", "-X", "utf8", "-B", str(ROOT / "verify_outputs.py"), "--run-dir", str(out)]
        checked = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=60)
        (out / "logs" / "independent-readback.txt").write_text(checked.stdout + checked.stderr, encoding="utf-8")
        if checked.returncode != 0:
            raise RuntimeError("independent HDF5 readback failed; inspect verify_readback.json")
        plot_results(out, provenance["cases"], results)
        verify_source_files(DATA, identities)
        if any(digest(DATA / name) != sha256 for name, sha256 in source_hashes.items()):
            raise ValueError("source data or reference manifest changed during reproduction")
        provenance.update(status="completed", elapsed_seconds=time.perf_counter() - started,
                          source_hashes_unchanged=True, pipeline_direct_metrics_exact=True,
                          independent_readback_passed=True, cases_processed=3, total_rows=sum(x["rows"] for x in provenance["cases"]),
                          finished_at_utc=datetime.now(timezone.utc).isoformat())
        write_json(out / "run.json", provenance)
        print(json.dumps({"status": "completed", "output": str(out), "rows": provenance["total_rows"]}, ensure_ascii=False))
        return out
    except Exception as exc:
        provenance.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        write_json(out / "run.json", provenance)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_case(args.run_dir)
