# Experiment-to-CPFE Pipeline

[中文](README.md)

Python tools for turning experimental and microstructure data into traceable sample packages, then preparing Abaqus inputs, extracting solver results and building machine-learning datasets as needed.

Records carry units, coordinates, tensor order, orientation conventions, sample identities and sources through processing. Whether data support a material model depends on the declared material parameters, mesh, loading conditions and evaluation protocol.

**v0.2.0 adds the data foundation:** experimental-file context, preservation of unknown fields, named multi-target datasets, input-availability checks, source grouping, evaluation-protocol checks and handoff records. This workflow runs with ordinary Python, without Torch or Abaqus.

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
- `verification.json`: the demonstration summary, explicitly recording that no model was trained and no solver was run.

Use a new output directory for each run. The [data-foundation guide](docs/data-foundation.md) explains individual commands, configuration and interpretation; the [example README](examples/data_foundation/README.md) provides a short rerun guide. These detailed guides are currently in Chinese.

## Available capabilities

| Stage | What it does | Entry point |
| --- | --- | --- |
| Native data ingestion | Reads supported tables, arrays, meshes, orientations and graph data while retaining sources and conversion records | [Data formats](docs/data-modalities.md), [native adapters](docs/native-adapters.md) |
| Experimental context | Imports self-describing JSON or an explicitly configured BAM LIS profile, retaining metadata, units and known/unconfirmed information | `import-experiment-file` |
| Sample normalization | Creates and reads back canonical HDF5 from explicit configuration without requiring a solver configuration | `normalize-sample` |
| Dataset construction | Selects table columns or array components, aligns row identities, and records unit conversions, target order and grouping | `build-training-dataset` |
| Basic checks | Checks future inputs, target contamination, overlapping groups, evaluation declarations and evidence; records handoff states | `check-evaluation-protocol`, `check-intake-status` |
| Abaqus integration | Checks supported input profiles, generates or stages INP, executes datacheck/analysis and extracts ODB | [Runbook](docs/runbook.md) |
| Existing learner | Runs grouped scalar CPU MLP regression with training-only normalization and validation-selected checkpoints | [Training datasets](docs/training-datasets.md) |

HDF5 is the canonical sample package. NPZ/PyG exports retain associated data and provenance; PyG export requires explicit graph arrays and feature declarations. See [operating conditions](docs/limitations.md) for supported formats and solver requirements.

Dataset construction supports v1 scalar targets and v2 ordered target lists, including development datasets containing only train/validation splits. **The existing `train-surrogate` retains its scalar MLP and original train/validation/test interface. It cannot directly train from the new example's v2, two-split configuration.** Multi-target dataset construction does not imply multi-target model training is available in this release.

## Existing public cases

### KupferDigital: tensile experiments, finite elements and a surrogate

The [CuSn8Ni2 tensile case](examples/kupfer_tensile/README.md) documents public-data preprocessing, material calibration, an Abaqus model, ODB extraction, packaging and scalar MLP training. H_08 is used for calibration, H_16 for model checking and H_18 for the final experimental comparison.

The [existing verification record](docs/verification/2026-09-06-public-tensile-surrogate.md) covers 12 finite-element cases for a homogeneous small-strain gauge model within 0–0.8% engineering strain. The recorded MLP RMSE on held-out FE cases is 0.682 MPa; FE and MLP RMSE against specimen H_18 are 4.428 MPa and 4.477 MPa. These are the case's previously recorded results. This data-feature release does not rerun the solver or extend that validation scope.

A [reference INP](examples/kupfer_tensile/reference/base.inp) and [result summary](docs/verification/assets/public-tensile-20260906/summary.json) accompany the case. The data and designated processed materials use CC BY 4.0; see [third-party notices](THIRD_PARTY_NOTICES.md).

### GH4169: ultrasonic parameters and mean grain size

The [GH4169 example](examples/gh4169_ultrasonic/README.md) imports 10 published specimens into HDF5 and training datasets, comparing mean, linear, ridge and MLP baselines. It demonstrates source grouping for separate physical specimens in one workbook. Linear regression outperformed the MLP in the recorded small-sample evaluation.

Obtain the original data separately under CC BY-NC 3.0. The repository contains scripts and source references, without the raw workbook or model weights. Results apply to the example's stated inputs and splits.

## Existing solver and export workflow

The synthetic example below checks sample declarations and solver readiness, prepares an INP and exports data. These commands do not start Abaqus:

```text
pipeline validate --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001
pipeline build-inp --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001 --format hdf5
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001 --format npz
pipeline inspect --run-dir runs/synthetic-001
```

Supported Abaqus profiles include explicitly supported combinations of geometry, material and boundary conditions, with isotropic elasticity, isotropic plasticity or an explicit UMAT. Declared grain orientations can be mapped to initialized STATEV entries. See [operating conditions](docs/limitations.md) for the precise scope. With your own Abaqus installation configured, run:

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

`native` adds MAT5/XLSX readers; `training` adds the dependencies for the existing CPU MLP; `ml` supplies optional PyTorch/PyG export dependencies. The data-foundation example needs none of these extras.

For development:

```text
python -m pip install -e ".[dev]"
python -m pytest -q
python -m build
```

Source and distribution files are provided through [GitHub Releases](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases). This release is not published to PyPI. See the [changelog](CHANGELOG.md) for version contents and the [validation record](docs/verification/2026-09-26-data-foundation.md) for local test scope.

## Documentation and licenses

[Data foundation](docs/data-foundation.md) · [Schema](docs/schema.md) · [Data formats](docs/data-modalities.md) · [Native adapters](docs/native-adapters.md) · [Training datasets](docs/training-datasets.md) · [Runbook](docs/runbook.md) · [Operating conditions](docs/limitations.md)

Code, documentation and synthetic fixtures use [Apache-2.0](LICENSE). Third-party data and designated processed materials retain their own licenses; see [NOTICE](NOTICE), [third-party notices](THIRD_PARTY_NOTICES.md) and the [license review](docs/licensing.md). Keep research inputs, model weights and solver outputs in your own data directories with their source, license and experimental-condition records.
