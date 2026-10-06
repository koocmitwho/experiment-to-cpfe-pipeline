# Experiment-to-CPFE Pipeline

[简体中文](README.md) | English

Current public version: **v0.3.1**. [Downloads and packages](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/tag/v0.3.1) · [Changelog](CHANGELOG.md)

**Turn experimental and microstructure data into traceable samples, then build datasets, train, predict independently and evaluate as needed.**

This Python library and command-line tool organizes tables, arrays, specimen information and source records into canonical HDF5 samples. It checks units, row identities and dataset splits, and prepares inputs for scalar regression or supported Abaqus workflows.

For example, a tensile file may store strain as a percentage and stress in MPa, with many measurement rows per specimen. The project can record the conversion from percent to dimensionless strain, keep each specimen in one partition, fit normalization on training records only, predict another specimen with a frozen model, then align truth and export CSV files and error metrics.

> Data checks and passing tests show that the software follows the declared rules. Material-model correctness, experimental independence and the accuracy required by a research task need separate design and validation.

## Who it is for and what it helps with

The project is for researchers and engineering developers organizing materials experiments, preparing finite-element inputs or building small regression baselines, especially when original files, specimen identities, unit conversions and training splits need to remain inspectable.

Its main uses are:

- **Organize different data types.** Read tables, numerical arrays, meshes, orientations and graph data through explicit configuration, retaining sources and processing relationships.
- **Preserve experimental context.** Record material, geometry, loading and measurement information; preserve original metadata and unknown fields; distinguish confirmed information from missing information.
- **Build inspectable datasets.** Align features and targets by row identity, record unit conversions, and split train, validation and test data by specimen or explicit group.
- **Run scalar regression.** Use CPU OLS (ordinary least-squares linear regression) or an MLP (multilayer perceptron), fit preprocessing and models on training records only, and use validation records for model selection.
- **Separate prediction from evaluation.** Generate predictions from a frozen checkpoint and input data, then evaluate against separate truth data, delivering readable CSV files, Chinese summaries and machine-readable records.
- **Connect supported solver stages.** Check and prepare Abaqus INP files, record datacheck, analysis and ODB extraction stages, and export HDF5/NPZ or PyG with explicit graph declarations.

The project does not automatically interpret arbitrary instrument formats, infer missing physical facts or construct a crystal-plasticity constitutive model from arbitrary experiments. Images and vendor-native files may first need conversion to supported numerical formats using other tools. Abaqus execution requires the user's own installation, model and any necessary compiler toolchain.

## Installation

Use **Python 3.12 or newer**. Base dependencies are NumPy, pandas, h5py, Pydantic and PyYAML; pip installs them according to [pyproject.toml](pyproject.toml).

The public source and packages work independently of private code, private material cards, trained weights or research data. The base example needs no PyTorch, PyG, GPU or Abaqus. Most real-case data must be downloaded separately; the small Paramaterial case includes three engineering stress-strain curves with confirmed redistribution rights.

### Recommended: get the tagged source with examples

Run these commands in a directory of your choice. If the destination already exists, inspect its version and local changes first.

```text
git clone --branch v0.3.1 --depth 1 https://github.com/koocmitwho/experiment-to-cpfe-pipeline.git
cd experiment-to-cpfe-pipeline
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli --version
```

Linux/macOS shell:

```bash
.venv/bin/python -m pip install -e .
.venv/bin/python -m experiment_to_cpfe.cli --version
```

The version command should print `pipeline 0.3.1`. These commands use the environment's interpreter directly; no PowerShell execution-policy change is required. Run subsequent commands from the repository root. They use Windows syntax; on Linux/macOS, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

Without Git, download the [Release source distribution](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/download/v0.3.1/experiment_to_cpfe-0.3.1.tar.gz), extract it, and install from the directory containing `pyproject.toml`.

### Library and CLI only: install the wheel

Install in a new or existing isolated virtual environment. For example, on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/download/v0.3.1/experiment_to_cpfe-0.3.1-py3-none-any.whl"
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli --help
```

The wheel provides the library and CLI. Example scripts, configurations and fixed case manifests are in the source repository and source distribution. To run the examples below after installing the wheel, also obtain `examples/` from the matching v0.3.1 source. This version is distributed through GitHub and has no PyPI publication.

### Add dependencies for the work you need

The following commands apply to the source directory. The base workflow does not require every extra.

| Use | Extra | Contents and conditions |
|---|---|---|
| Native MAT5/XLSX reading | `.[native]` | SciPy and openpyxl |
| Scalar training and model inference | `.[training]` | PyTorch and SciPy; the public trainer uses CPU |
| PyG graph export | `.[ml]` | PyTorch and torch-geometric; correct graph declarations are still required |
| Development and packaging | `.[dev]` | pytest, build, twine and related tools |

For example, install native-reading dependencies with:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[native]"
```

For Windows/Linux training examples, install CPU PyTorch first, then the training and native-reading dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install "torch>=2.6" --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e ".[training,native]"
```

See the [official PyTorch installation page](https://pytorch.org/get-started/locally/) for platform selection. Release CI covers Linux and Windows; the complete macOS workflow has not been verified.

## First run: no data download or solver execution

Complete the base source installation, then run:

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/data_foundation/workflow.py --run-dir runs/data-foundation-001
```

The script generates 3 synthetic specimens and 12 rows, imports experimental files, normalizes CSV data, reads back HDF5, builds a dataset, and checks evaluation-protocol and handoff declarations. Two specimens contribute 8 train rows; the remaining specimen contributes 4 validation rows.

Main outputs under `runs/data-foundation-001/` are:

| File | Contents |
|---|---|
| `imports/<specimen>/sample.h5` | Three canonical samples and their experimental context |
| `normalized/sample.h5` | A separate CSV-normalization demonstration |
| `dataset/dataset.npz`, `dataset/dataset.json` | Features, targets, row identities, groups, units and sources |
| `protocol/evaluation-protocol.json` | Checks of the evaluation protocol and declared evidence |
| `intake/intake-status.json` | Handoff checks |
| `verification.json` | Software-check summary for the synthetic workflow |

**This step does not train a model.** It demonstrates v2 target-list construction with two partitions. Its generated configuration cannot be passed directly to the current scalar trainer. Use the v1 example in the next section to exercise training.

Choose a directory that does not yet exist each time, such as `runs/data-foundation-002` for the next run. After changing configuration, preserve earlier results and use a new directory. Individual commands and fields are described in the [data-foundation guide](docs/data-foundation.md) and [example README](examples/data_foundation/README.md).

## Small real-data case: three tensile specimens and readback

The [Paramaterial example](examples/paramaterial_tensile/README.en.md) uses three bundled public AA6061-T651 curves from lot A at 20 C, totaling 1,889 rows. It computes UTS, E and 0.2% proof using the author's method, passes the original data through the public package's HDF5 normalization, and compares the readback and independent checks. It uses separate Python 3.12 example dependencies; no training or solver is needed.

```powershell
.\.venv\Scripts\python.exe -m pip install -r examples/paramaterial_tensile/requirements.txt
.\.venv\Scripts\python.exe -B examples/paramaterial_tensile/workflow.py --run-dir runs/paramaterial-001
```

Inputs are author-provided engineering stress-strain curves under CC BY 4.0. [Sources and processing scope](examples/paramaterial_tensile/SOURCES.md) accompany the example. This checks processing and transfer consistency, not material calibration or cross-material prediction.

## Next run: scalar training on synthetic data

After installing the CPU training dependencies above, run the table-layout example:

```powershell
.\.venv\Scripts\python.exe examples/synthetic_training/prepare.py --output-dir runs/training-inputs-001
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli build-training-dataset --config runs/training-inputs-001/table/build.yaml --run-dir runs/table-dataset-001
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli train-surrogate --config runs/table-dataset-001/training-config.json --run-dir runs/table-model-001
```

Inputs follow `y = x * gain`: four synthetic samples with 31 rows each, assigned to 2 training samples, 1 validation sample and 1 test sample. The example demonstrates kN-to-N conversion and scalar regression with samples kept in separate partitions.

Open `runs/table-model-001/training.json` for the actual settings, normalization, partition errors and training-mean baseline. `model.pt` is the frozen checkpoint; `predictions.npz` contains partition predictions from that training workflow. This synthetic software example does not establish accuracy on real materials. See the [synthetic training example](examples/synthetic_training/README.md) for the array layout, parameter changes and full instructions.

### Splits and version boundaries

| Operation | v0.3.1 support |
|---|---|
| `build-training-dataset` | v1 single `target`; v2 ordered `targets` list; train and validation required, test optional |
| Default `train-surrogate` mode | v1 scalar target; train, validation and test required |
| `train-surrogate` with `evaluation_mode: external_test` | v1 scalar target; exactly train and validation, with test data kept external |
| `infer-surrogate` / `evaluate-surrogate` | Current public scalar OLS/MLP checkpoints and corresponding inputs/truth; no v2 multi-target training or inference |

Do not randomly split measurement rows from one original specimen between training and test data. Group by `sample_id`, `experiment_id` or an explicit `group_id`. Distinct specimens in a shared workbook need the original identity column and corresponding provenance declarations. The software checks declaration and source conflicts across partitions, but independence still needs experimental-design evidence. Renaming files or group labels does not create independent specimens.

Normalization and OLS coefficients fit training records only; validation error selects MLP checkpoints. Configuration must also state whether inputs are available at the actual prediction time and whether they contain target-derived information. See the [training-dataset guide](docs/training-datasets.md) for rules and examples.

## Real public case: intake through independent prediction and evaluation

The [complete DOPAMICS guide](docs/real-case-workflow.en.md) covers intake, normalization, scalar dataset construction, CPU OLS/MLP, independent prediction and test evaluation using public palm-leaflet tensile data. It needs no PyG, GPU or Abaqus.

After installing the source and CPU training dependencies, download **only** `2025-04-08_Mechanical_data_tensile_test_laser_ALES.zip` (about 622 KB) from [Zenodo 15343816](https://zenodo.org/records/15343816). Store it outside the repository at `../cpfe-data/dopamics/`, then run:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 examples/external_cases/workflow.py --case dopamics --source-root ../cpfe-data/dopamics --run-dir ../cpfe-results/dopamics-001
```

The script checks fixed file digests, original specimen identities, headers and units; it does not download or execute upstream scripts. Inputs are measured laser strain, and the target is instrument-reported stress. The fixed split is 3 training specimens (424 rows), 1 validation specimen (181 rows) and 1 external test specimen (182 rows), with each specimen kept in one role. OLS/MLP selection uses validation data only, followed by test-specimen evaluation.

Start with `REPORT.md` in the output directory, then inspect:

- `inference/predictions.csv`: row predictions, identities, sources and units, without truth.
- `evaluation/evaluation.csv` and `evaluation/SUMMARY.md`: aligned truth, residuals, metrics and Chinese explanations.
- `baseline-comparison.csv` and `model-selection.json`: the training mean, OLS and selected model, plus the validation-selection basis.
- `configs/`, `commands/` and `verification.json`: actual configurations, stage commands and result records.

For standalone prediction, prepare the frozen `model.pt`, input-only HDF5 and an inference configuration, then call `infer-surrogate --config ... --run-dir ...`. Evaluation calls `evaluate-surrogate --config ... --run-dir ...` with the prediction artifact and its completion receipt, plus truth-only HDF5; it does not need to reopen the model or original training files. The guide provides executable commands after configuration generation. `template-config` can produce a draft from a dataset-build configuration for you to complete.

Inference and evaluation check names, units, specimens and row identities. HDF5 integrity checks read the entire listed package, so keep sealed truth in a separate file. Leaving a target column unselected in a mixed file does not establish isolation.

### Interpreting the case results

The fixed v0.3.0 case produced these results on one test specimen:

| Method | RMSE (MPa) | MAE (MPa) | R² |
|---|---:|---:|---:|
| Training-mean baseline | 2.245313 | 1.810683 | -1.090530 |
| OLS | 3.140684 | 2.839127 | -3.090262 |
| Validation-selected MLP | 2.071353 | 1.923316 | -0.779143 |

The MLP has lower RMSE than the mean baseline but higher MAE, so it is not superior on every metric. Negative R² means its squared error exceeds the variance reference defined by the test-truth mean. That test mean is a statistical reference, not a deployable training baseline. The 182 rows are not 182 independent specimens.

No scientific accuracy threshold was specified, and the case establishes no material-calibration, crystal-plasticity or cross-material validation claim. Source checks have read public test responses; this is retrospective conditional regression, not a new blind test. The task and scientific validity remain unassessed. See the [full guide](docs/real-case-workflow.en.md) for metric definitions and source-data conventions.

## Other examples

| Example | Demonstrates | Conditions and limits |
|---|---|---|
| [FAIR Train / PCL](examples/external_cases/README.md) | FAIR original workbook-channel import; numerical packaging of PCL's twelve channels, including preheating records | Download public source data separately; these two fixed cases do not train models |
| [GH4169 ultrasonic data](examples/gh4169_ultrasonic/README.md) | Scalar mean-grain-size regression on ten specimens, comparing mean, linear, ridge and MLP methods | Original data use CC BY-NC 3.0; linear regression outperformed MLP in the recorded small-sample results |
| [KupferDigital tensile case](examples/kupfer_tensile/README.md) | CuSn8Ni2 small-strain uniform-gauge model, calibration, finite-element and surrogate comparisons | Complete solving needs your own Abaqus; historical results are limited to 0–0.8% engineering strain and the specified specimens/model |
| [Synthetic native-import configuration](examples/synthetic_native/imports.yaml) | Explicitly declared native numerical import | Uses `native` dependencies; no real solver execution |

Historical KupferDigital records cover 12 finite-element cases: MLP RMSE on held-out FE cases was 0.682 MPa; FE/MLP RMSE in the H_18 experimental comparison was 4.428/4.477 MPa. These values belong only to the [specified model and historical verification conditions](docs/verification/2026-09-06-public-tensile-surrogate.md). They do not represent arbitrary crystal-plasticity experiments or a new real-Abaqus verification for v0.3.0.

## Inputs, outputs and solver entry points

JSON/YAML configurations explicitly declare file paths, sample/specimen identities, table columns or array components, source units and conversions, coordinate and orientation conventions, grouping and required provenance. Examples are starting points: changing filenames alone is insufficient to adapt them to your own raw data.

| Stage | Main inputs | Main outputs |
|---|---|---|
| Experimental-file import / normalization | Self-describing JSON, configured BAM LIS context, or supported numerical files and mappings | `sample.h5`, original context, source and processing records |
| Dataset construction | Canonical HDF5, feature/target selections, row alignment and grouping configuration | `dataset.npz`, `dataset.json`, `training-config.json` |
| Scalar training | v1 training bundle and training parameters | `model.pt`, `training.json`, partition predictions and mean baseline |
| Independent inference | Frozen checkpoint, input-only HDF5 and inference configuration | `predictions.npz`, `predictions.csv`, `inference.json`, Chinese summary |
| Independent evaluation | Prediction NPZ and completion receipt, truth-only HDF5 and evaluation configuration | `evaluation.npz`, `evaluation.csv`, `evaluation.json`, Chinese summary |
| Solving / extraction / export | Supported INP, material/loading configuration, solver and ODB | Stage records, extracted fields, HDF5/NPZ, and PyG when graph declarations are satisfied |

HDF5 is the canonical sample format. General sample NPZ preserves sample data; training NPZ contains explicitly selected features, targets and splits. They are not interchangeable. Graph export uses declared nodes, graph arrays and features; it does not automatically generate graphs from arbitrary images. See [data formats](docs/data-modalities.md) and [native adapters](docs/native-adapters.md) for formats and selectors.

With the base installation, run validation, INP preparation and export without launching Abaqus:

```powershell
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli validate --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli build-inp --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli export --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001 --format hdf5
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli export --config examples/synthetic_minimal/sample.yaml --run-dir runs/synthetic-001 --format npz
.\.venv\Scripts\python.exe -m experiment_to_cpfe.cli inspect --run-dir runs/synthetic-001
```

These commands are consecutive stages of one run, so they share a directory and should run in order. Use a different directory for a new run. Training, independent inference, evaluation and complete examples each use new output directories; preserve existing results rather than deleting them to permit an overwrite.

Current Abaqus checks cover supported three-dimensional solid elements, one material and one static displacement step, with declared isotropic elasticity, isotropic plasticity or an explicit UMAT. Users supply subroutines, material parameters, compiler toolchains and real execution. Declared orientation mappings can initialize STATEV; this does not complete or validate a crystal-plasticity model automatically. For execution, first prepare configuration according to the [runbook](docs/runbook.md), then use `run-abaqus --stage datacheck`, `run-abaqus --stage analysis` and `extract-odb`.

## Current verification scope and limitations

v0.3.1 adds the Paramaterial case, with dependencies, tests and results documented in its [case guide](examples/paramaterial_tensile/README.en.md). The v0.3.0 numbers below remain historical release evidence.

The v0.3.0 release audit checked independent public-package installation, source examples, CPU training/inference/evaluation and package contents. Final isolated Windows verification had **831 passed and 1 skipped**, with the only skip being real Abaqus, which was not enabled. The tag [CI](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/actions/runs/36811952722) passed all four jobs: Ubuntu/Windows base workflows, CPU training and CPU ML. Base jobs also checked wheel installation; CPU ML included actual PyG serialization/readback.

Those results do not cover or establish:

- Real Abaqus, GPU, optional plotting, a complete macOS workflow or every dependency-version combination.
- Arbitrary vendor formats or crystal-plasticity experiments, constitutive accuracy, numerical convergence or cross-material generalization.
- Real FAIR/PCL data reruns in the v0.3.0 audit; their public synthetic regressions were covered.
- The root cause of the historical Windows native crash. Failure to reproduce it under constrained CPU runs does not explain the original fault.

See [capabilities and operating conditions](docs/limitations.md) for detailed conditions. The [release-audit snapshot](docs/verification/2026-09-30-public-usability.md) and [Release](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/tag/v0.3.0) retain installation, command, metric and distribution evidence.

## Project layout and documentation

```text
src/experiment_to_cpfe/  Python library, CLI, adapters, datasets, learning and solver interfaces
configs/                 Example configurations, policies and INP templates
examples/                Synthetic examples, public-case scripts and fixed source manifests
docs/                    Format, training, operating and case guides
tests/                   Public unit and integration tests
scripts/                 ODB extraction and run-artifact checksum tools
```

Choose the documentation for your task:

- First intake and field declarations: [data foundation](docs/data-foundation.md), [schema](docs/schema.md).
- Original-file reading: [data formats](docs/data-modalities.md), [native adapters](docs/native-adapters.md).
- Training and grouping: [training datasets](docs/training-datasets.md), [synthetic training example](examples/synthetic_training/README.md).
- Real data through independent prediction: [DOPAMICS English guide](docs/real-case-workflow.en.md).
- Solvers and exports: [runbook](docs/runbook.md), [capability boundaries](docs/limitations.md).

Some detailed technical documents are in English; the Chinese README and Chinese real-case guide provide the main Chinese introduction. The linked DOPAMICS guide also has an English edition.

## Tests and contributions

In a base environment without PyTorch, install development dependencies to run base tests and build packages:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q -rs --strict-markers
.\.venv\Scripts\python.exe -m build
```

The default `offline` test profile allows registered missing-PyTorch tests and disabled real-Abaqus/wheel-install opt-ins to skip; other unexpected skips fail the session. If PyTorch was already installed for training, the complete suite also checks PyG; `.[training]` alone is insufficient. First install CPU PyTorch as above, then add ML development dependencies and run:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ml]"
$env:EXP2CPFE_TEST_PROFILE = "ml"
.\.venv\Scripts\python.exe -m pytest -q -rs --strict-markers
```

On Linux, set the profile with `export EXP2CPFE_TEST_PROFILE=ml`. For the wheel-install check, build the package first, then set `EXP2CPFE_WHEEL_DIR` according to the [release checklist](docs/release_checklist.md). Test counts from different dependencies or opt-in settings are not directly comparable.

Report problems through [Issues](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/issues), or contribute a Pull Request. Include the version, relevant command, a minimal reproducible configuration and redacted diagnostics. For format adapters or features, explain their scope and add appropriate verification. Use small public synthetic samples or inputs with clear redistribution rights; do not upload private experiments, credentials, model weights or machine configuration.

## Licenses and data sources

Project code, documentation and synthetic fixtures use [Apache-2.0](LICENSE). Data and source-derived materials retain their own licenses:

- Designated KupferDigital case materials and source-derived DOPAMICS, FAIR Train and PCL manifests: CC BY 4.0.
- Separately obtained GH4169 raw data: CC BY-NC 3.0. The project-code license does not change its noncommercial terms.
- The three Paramaterial engineering curves, source-derived manifest and reference calculations: CC BY 4.0; upstream method/example MIT notices are retained separately.
- Other optional sources: their respective manifests and upstream conditions.

See [NOTICE](NOTICE), [third-party notices](THIRD_PARTY_NOTICES.md) and the [license record](docs/licensing.md) for authors, original records, processing changes and scope. The source distribution includes the three explicitly attributed Paramaterial case curves. Other original archives, trained weights and solver results remain in users' local working directories.
