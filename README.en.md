# Experiment-to-CPFE Pipeline

[中文](README.md)

Python tools for turning experimental and microstructure data into traceable sample packages, then preparing Abaqus inputs, extracting solver results and building machine-learning datasets as needed.

Records carry units, coordinates, tensor order, orientation conventions, sample identities and sources through processing. Model configurations record material parameters, mesh, loading conditions and the evaluation protocol.

**v0.2.0 adds the data foundation:** experimental-file context, preservation of unknown fields, named multi-target datasets, input-availability checks, source grouping, evaluation-protocol checks and handoff records. This workflow runs with the base Python installation.

**v0.2.1 repairs and verification:** merged ODB records are validated before export with row provenance and field units. The update adds CLI summaries, consistent policy propagation, a CI skip gate and CPU PyG export testing.

## Start with a small example

Python 3.12 or newer is required. From the repository root:

```text
git clone https://github.com/koocmitwho/experiment-to-cpfe-pipeline.git
cd experiment-to-cpfe-pipeline
python -m venv .venv
```

Activate the environment in Windows PowerShell:

```powershell
.venv/Scripts/Activate.ps1
```

On Linux/macOS use `source .venv/bin/activate`. Then install and run:

```text
python -m pip install -e .
python examples/data_foundation/workflow.py --run-dir runs/data-foundation-001
```

The example generates 3 synthetic specimens and 12 rows, preserves their original information, reads back HDF5, builds a dataset and checks grouping and evaluation declarations. The chosen output directory contains:

- `dataset/dataset.npz`: features, targets, sample identities and splits; this example has 8 train rows and 4 validation rows.
- `dataset/dataset.json`: units, source lineage and task-assessment records.
- `protocol/evaluation-protocol.json` and `intake/intake-status.json`: protocol and handoff checks.
- `verification.json`: synthetic workflow execution and check results.

Use a new output directory for each run. The [data-foundation guide](docs/data-foundation.md) explains individual commands, configuration and interpretation; the [example README](examples/data_foundation/README.md) provides a short rerun guide.

## Available capabilities

| Stage | What it does | Entry point |
| --- | --- | --- |
| Native data ingestion | Reads supported tables, arrays, meshes, orientations and graph data while retaining sources and conversion records | [Data formats](docs/data-modalities.md), [native adapters](docs/native-adapters.md) |
| Experimental context | Imports self-describing JSON or an explicitly configured BAM LIS profile, retaining metadata, units and known/unconfirmed information | `import-experiment-file` |
| Sample normalization | Creates and reads back canonical HDF5 from explicit data configuration | `normalize-sample` |
| Dataset construction | Selects table columns or array components, aligns row identities, and records unit conversions, target order and grouping | `build-training-dataset` |
| Basic checks | Checks future inputs, target contamination, overlapping groups, evaluation declarations and evidence; records handoff states | `check-evaluation-protocol`, `check-intake-status` |
| Abaqus integration | Checks supported input profiles, generates or stages INP, executes datacheck/analysis and extracts ODB | [Runbook](docs/runbook.md) |
| Existing learner | Runs grouped scalar CPU MLP regression with training-only normalization and validation-selected checkpoints | [Training datasets](docs/training-datasets.md) |

HDF5 is the canonical sample package. Export validates the merged experimental and simulated records and saves a stage-specific report. NPZ/PyG derive from the validated HDF5 and retain associated data and provenance; PyG uses explicit graph arrays and feature declarations. `export.formats` specifies enabled formats. See [capabilities and operating conditions](docs/limitations.md) for format and solver requirements.

Dataset construction supports v1 scalar targets and v2 ordered target lists, including train/validation development datasets. `train-surrogate` uses a scalar CPU MLP with v1 target declarations and train/validation/test splits; see the [training guide](docs/training-datasets.md).

## Existing public cases

### KupferDigital: tensile experiments, finite elements and a surrogate

The [CuSn8Ni2 tensile case](examples/kupfer_tensile/README.md) documents public-data preprocessing, material calibration, an Abaqus model, ODB extraction, packaging and scalar MLP training. H_08 is used for calibration, H_16 for model checking and H_18 for the final experimental comparison.

The [existing verification record](docs/verification/2026-09-06-public-tensile-surrogate.md) covers 12 finite-element cases for a homogeneous small-strain gauge model within 0–0.8% engineering strain. The recorded MLP RMSE on held-out FE cases is 0.682 MPa; FE and MLP RMSE against specimen H_18 are 4.428 MPa and 4.477 MPa. The record's date, model and specimen splits define the conditions of these results.

A [reference INP](examples/kupfer_tensile/reference/base.inp) and [result summary](docs/verification/assets/public-tensile-20260906/summary.json) accompany the case. The data and designated processed materials use CC BY 4.0; see [third-party notices](THIRD_PARTY_NOTICES.md).

### GH4169: ultrasonic parameters and mean grain size

The [GH4169 example](examples/gh4169_ultrasonic/README.md) imports 10 published specimens into HDF5 and training datasets, comparing mean, linear, ridge and MLP baselines. It demonstrates source grouping for separate physical specimens in one workbook. Linear regression outperformed the MLP in the recorded small-sample evaluation.

Obtain the CC BY-NC 3.0 data through the example's source link, then use the repository scripts to generate canonical samples, models and evaluation results locally.

## Existing solver and export workflow

The synthetic example below checks sample declarations and solver readiness, prepares an INP and exports data:

```text
pipeline validate --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001
pipeline build-inp --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001 --format hdf5
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001 --format npz
pipeline inspect --run-dir runs/synthetic-001
```

Implemented Abaqus profiles use a flat three-dimensional solid mesh, one named material and one static displacement step, with isotropic elasticity, isotropic plasticity or an explicit UMAT. Declared grain orientations can be mapped to initialized STATEV entries. See [capabilities and operating conditions](docs/limitations.md) for configuration details. With your own Abaqus installation configured, run:

```text
pipeline run-abaqus --config sample.yaml --run-dir runs/sample-001 --stage datacheck
pipeline run-abaqus --config sample.yaml --run-dir runs/sample-001 --stage analysis
pipeline extract-odb --config sample.yaml --run-dir runs/sample-001
```

Use a new run directory when configuration or inputs change. Datacheck and analysis keep separate stage records. Use `normalize-sample` for data-only validation; `validate` also checks solver readiness.

## Optional dependencies and development

```text
python -m pip install -e ".[native]"
pipeline adapt --config examples/synthetic_native/imports.yaml --run-dir runs/native-example
```

`native` adds MAT5/XLSX readers; `training` adds dependencies for the CPU MLP; `ml` supplies PyTorch/PyG export dependencies. Select extras for the commands you use.

For development:

```text
python -m pip install -e ".[dev]"
python -m pytest -q -rs --strict-markers
python -m build
```

Source and distribution files are provided through [GitHub Releases](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases). See the [changelog](CHANGELOG.md) for version contents and the [verification record](docs/verification/2026-09-27-validation-ci-hardening.md) for repair and test evidence. Stage commands print an execution summary; `pipeline --version` reports the tool version.

## Documentation and licenses

[Data foundation](docs/data-foundation.md) · [Schema](docs/schema.md) · [Data formats](docs/data-modalities.md) · [Native adapters](docs/native-adapters.md) · [Training datasets](docs/training-datasets.md) · [Runbook](docs/runbook.md) · [Operating conditions](docs/limitations.md)

Code, documentation and synthetic fixtures use [Apache-2.0](LICENSE). Third-party data and designated processed materials retain their own licenses; see [NOTICE](NOTICE), [third-party notices](THIRD_PARTY_NOTICES.md) and the [license review](docs/licensing.md). Keep research inputs, model weights and solver outputs in your own data directories with their source, license and experimental-condition records.
