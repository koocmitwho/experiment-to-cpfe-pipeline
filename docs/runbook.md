# Pipeline runbook

## 1. Validate

```text
pipeline validate --config sample.yaml --run-dir runs/sample-001
```

Creates a new, non-empty-protected run directory and writes the normalized
sample, `input/input_lock.json`, and the four reports under `reports/`:
`validation.json`, `solver_readiness.json`, `qa_report.md`, and `run_manifest.json`.
The input lock binds configuration, source files and the effective validation
policy to SHA-256 hashes. Later stages check that their prerequisites and
artifacts still match. Use a new run when inputs change.

Data validation and solver readiness are distinct results. A valid experimental
sample can have `validation.passed=true` while `solver_readiness.ready=false`.
The combined validate stage then reports incomplete solver inputs, but data
export remains possible. Inspect both reports before choosing the next stage.

The authoritative default policy is the installed package resource
`experiment_to_cpfe/_resources/validation_policy.yaml`.
`configs/validation_policy.yaml` is a human-readable template. Data validation,
readiness, INP generation and preflight all use the loaded package policy.
Python API callers may pass an explicit `ValidationPolicy` to readiness and
`build_solver_input`.

## 2. Build INP

```text
pipeline build-inp --config sample.yaml --run-dir runs/sample-001
```

Requires a solver-ready sample. The template path writes `input/model.inp` and a
static-check report. Native input bundles use the explicit `abaqus.input_bundle`
configuration described below. Each build uses a fresh output. The readiness
report records agreement between declared inputs and the rendered deck.

### Checked solver profiles

The initial checked profile is a flat three-dimensional solid model, one named
material and one named static step with explicit displacement loading. Supported
connectivity types are C3D4, C3D8, C3D8R, C3D10, C3D20 and C3D20R. The declared
grain mapping must assign every actual element once, and declared nodes,
connectivity, sections, material constants, boundaries and output requests must
agree with the deck. The gate also checks rigid-body constraint rank.

`solver_inputs.material_model` selects one of:

- `isotropic_elastic`: `material_parameters: {E: ..., nu: ...}` must match the
  plain `*ELASTIC` definition. Request the stress, strain, displacement and
  reaction fields supplied by the model.
- `isotropic_plastic`: supply `material_parameters: {E: ..., nu: ..., plastic:
  [[stress0, 0.0], [stress1, plastic_strain1]]}`. At least two stress/plastic-strain
  pairs must match one plain `*PLASTIC` block exactly. Stress is positive and
  nondecreasing; plastic strain starts at zero and increases strictly.
  Elastic constants also match one plain `*ELASTIC` block.
- `umat`: explicitly supply `constants`, one `constant_units` entry per constant,
  and positive `depvar` under `material_parameters`. These must match
  `*USER MATERIAL` and `*DEPVAR`; separately configure an authorized
  `abaqus.user_subroutine`.

Use `orientation_required: false` with an orientation-independent material
declaration. For a UMAT that expects orientation in
STATEV, set `orientation_required: true` and explicitly map grain-table columns
to one-based state-variable indices:

```yaml
solver_inputs:
  orientation_required: true
  orientation_state_variables:
    columns: [q0, q1, q2, q3]
    indices: [1, 2, 3, 4]
```

The actual deck must supply `*INITIAL CONDITIONS, TYPE=SOLUTION` values for every
element through explicit element labels or sets, with every DEPVAR value
provided. The first row supplies a target and up to seven values; continuation
rows supply up to eight values each. The gate verifies complete, non-overlapping
coverage and exact agreement of the selected STATEV values with mapped grain
orientations. Euler, quaternion and rotation-matrix representations require
their explicit source conventions; quaternion norm and proper matrix rotations
are checked. The supplied UMAT interprets these entries using the declared
conventions and constitutive equations.

The synthetic example demonstrates the isotropic profile. Crystalline models
provide their constitutive model, parameters, grain assignments and orientation
initialization through the explicit UMAT contract.

The Python API `check_deck_readiness(sample, deck_text, policy=None)` checks declarations
against expanded actual deck text; the native-bundle path resolves and hashes
INCLUDE files before calling it. `check_solver_readiness(sample, "abaqus_cpfe",
policy=None)` checks the configured template blocks. Both return readiness,
missing requirements and warnings under the selected validation policy.

### Native INCLUDE bundles

An existing native deck must declare a source root, entrypoint, original
submission directory, required auxiliary files and license. Relative
`source_root` is resolved against the YAML file. Entrypoint, submission directory
and auxiliary file paths are resolved against that source root.

```yaml
abaqus:
  command: [abaqus]
  job_name: sample_001
  input_bundle:
    source_root: native_inputs
    entrypoint: model/main.inp
    submission_dir: model
    auxiliary_files: []
    license: user-supplied-authorized-input
```

Add this fragment to a complete sample configuration and replace
the license description with the actual source terms. INCLUDE
references are resolved with the explicitly declared submission-directory
semantics. Missing dependencies, cycles, paths escaping the source root,
excessive file count/size and existing destinations are rejected.

```text
pipeline stage-input-bundle --config sample.yaml --run-dir runs/sample-001
```

This optional stage makes a byte-preserving, hash-recorded copy under
`input/native_bundle/` with `reports/native_bundle.json`. For a non-ASCII run
path, an explicitly configured ASCII temporary root holds the prepared bundle;
the report records its actual location. `build-inp` and `run-abaqus` then check
the declared units, materials, mesh, loading and expanded deck.

## 3. Abaqus datacheck

```text
pipeline run-abaqus --config sample.yaml --run-dir runs/sample-001 --stage datacheck
```

The Abaqus command is read from configuration or `EXP2CPFE_ABAQUS_COMMAND`.
Use command tokens such as `command: [abaqus]`; machine-specific compiler setup
belongs in a local wrapper referenced by configuration/environment, outside the
public source tree. An unavailable executable or an invalid staging path is
reported as blocked. Solver errors and missing evidence are reported with the
captured logs. Completion requires both the process result and stage artifacts.

Datacheck and analysis use separate stage directories. Default execution is one
CPU with a configured timeout; the chosen staging directory must be ASCII-only.
Run datacheck first and inspect its status before analysis.

Set `abaqus.ascii_temp_root` to a local ASCII-only directory when execution needs
to occur outside the run directory. Each stage creates a fresh temporary job
directory beneath that root, runs there, then archives outputs into
`solver/<stage>/` under the run. Native bundles preserve their relative
submission directory inside that archive. Each stage has its own output directory.
Temporary inputs and native source originals remain separate, and the recorded
command keeps the actual execution location for provenance.

## 4. Abaqus analysis

```text
pipeline run-abaqus --config sample.yaml --run-dir runs/sample-001 --stage analysis
```

Analysis requires ODB, STA, DAT, and MSG artifacts plus a successful STA completion statement. Datacheck, optional user-subroutine compile/link status, and analysis are recorded separately.

## 5. Extract ODB

```text
pipeline extract-odb --config sample.yaml --run-dir runs/sample-001
```

The packaged extraction script runs under `abaqus python` and imports
`odbAccess` there. The host environment reads JSON/CSV output and writes HDF5.
Extraction requires a successful recorded analysis and unchanged registered
solver artifacts. ODB access is read-only.

Declare the requested fields and their physical units individually:

```yaml
abaqus:
  required_fields: [S, E, U, RF]
  extraction_position: native
  extraction_max_records: 1000000
  field_units: {S: MPa, E: '1', U: mm, RF: N}
```

Set these units to the actual model's conventions. This small-strain example requests
`E`; a suitable finite-strain model may request logarithmic strain `LE`. If
Abaqus replaces an unavailable request with a different field, the extractor
reports the requested field as missing rather than silently aliasing E and LE.
Available position selections are
`integration_point`, `nodal`, `element_nodal`, `element_face`, `centroid`, and
`native`; `native` retains stored locations without interpolating new values.
For user-material state variables, declare units individually for the actual
names, such as `SDV1` and `SDV2`.
Only request PEEQ/SDV when the model provides those outputs.

Missing fields/locations are recorded per frame. Original field/component names,
available location labels and numerical precision are retained in the extracted
records; field units are bound in the host metadata.

`frame_value` retains the ODB frame domain; `frame_time` is step-relative for
TIME frames. Ordinary table `time` has its own clock. Validation checks frame
times in frame order for each source/step/load case. Each increment identifies
one frame, with multiple field/component/location rows sharing that frame.
Extracted rows bind to the simulated extraction asset. Current bundles declare
`field_contract_version`; the legacy extraction-version 0.1 fixture is also read.

## 6. Export

```text
pipeline export --config sample.yaml --run-dir runs/sample-001 --format hdf5
pipeline export --config sample.yaml --run-dir runs/sample-001 --format npz
pipeline export --config sample.yaml --run-dir runs/sample-001 --format pyg
```

HDF5 is canonical. NPZ and PyG read the completed HDF5 export and verify its
recorded source hash. Run HDF5 export before either derived export. NPZ uses
non-pickled arrays plus JSON metadata and can be opened with
`numpy.load(path, allow_pickle=False)`.

PyG requires the optional `ml` dependencies, explicit graph node IDs/features,
integer edge indices and a graph contract with names, units and directedness.
The exported `Data` object embeds a portable package for the accompanying
sample tables and metadata. Supplied graph arrays define the node/feature
correspondence. Load serialized PyTorch objects from a trusted source.

Formal exports require the hash-bound `validation.json` to report `passed: true`.
This is separate from solver readiness: valid experimental data may be exported
without a mesh or material model, even when the combined validate stage reports
incomplete solver inputs. The two reports record their respective checks.

`export.formats` enables the requested format. HDF5 export validates the complete
merged SamplePackage immediately before writing and saves
`reports/export-hdf5_validation.json` and `reports/export-hdf5_qa.md` in the export
stage's artifact list. Errors produce a `blocked` export and a validation report.
`reports/validation.json` remains the original input receipt. Derived exports
read the completed, hash-verified canonical HDF5.

Once an `extract-odb` attempt is recorded in the run manifest, export requires its
successful completion and unchanged, registered `metadata.json` and `frames.csv`.
The recorded extraction remains a prerequisite throughout the run. Missing
evidence produces `blocked`; use a new run directory for a different workflow.

## Build a training collection

```text
pipeline build-training-dataset --config build.yaml --run-dir runs/training-data-001
pipeline train-surrogate --config runs/training-data-001/training-config.json --run-dir runs/model-001
```

The build configuration lists canonical HDF5 inputs, layouts, scalar quantities
and a grouping policy. The command writes dataset.npz, dataset.json,
training-config.json and build-manifest.json into a new directory. Source paths
are relative to the build configuration. The generated training configuration
uses a dataset-relative path and can include the existing MLP settings.

The [training dataset guide](training-datasets.md) gives complete table and array
selectors. The [synthetic training example](../examples/synthetic_training/README.md)
generates both layouts without a solver. Training requires the `training` extra.

## Inspect

```text
pipeline inspect --run-dir runs/sample-001
```

Prints the manifest with stage statuses, hashes, artifacts, commands and
diagnostics. The runtime record contains tool/Python/dependency versions and a
fingerprint of package source and resource files. Other stage commands print a
completion or failure summary; `pipeline --version` reports the package version.

To create sorted checksums for an existing run:

```text
python scripts/hash_run_artifacts.py runs/sample-001
```

The command reads artifact bytes and writes `SHA256SUMS.txt` with relative paths.
It excludes its own output, so repeated runs over unchanged artifacts produce
the same contents. The [retry proposal](retry-design.md) describes a future
attempt-directory workflow for maintainer review.

## Verification and scope

```text
python -m pytest -q -rs --strict-markers
python -m build
```

The offline suite uses synthetic inputs. The installed-wheel integration test is
enabled by `EXP2CPFE_WHEEL_DIR`; the opt-in solver test requires
`EXP2CPFE_RUN_ABAQUS=1`, `EXP2CPFE_ABAQUS_CONFIG` and
`EXP2CPFE_ABAQUS_RUN_DIR`. It starts from a nonexistent run directory and runs
validate, build-inp, datacheck, analysis, extraction, HDF5 export and NPZ export.
The user-supplied configuration must already declare a complete solver-ready,
authorized model, one CPU, a timeout of at most 600 seconds per stage, and
nonempty requested output fields with their units. The test enforces at most
1000 elements and 10000 nodes before launching Abaqus.

For a local PowerShell session, after preparing that small configuration:

```powershell
$env:EXP2CPFE_RUN_ABAQUS = "1"
$env:EXP2CPFE_ABAQUS_CONFIG = "my-authorized-smoke.yaml"
$env:EXP2CPFE_ABAQUS_RUN_DIR = "runs/real-integration-new"
python -m pytest -q -rs tests/integration/test_abaqus_optional.py
Remove-Item Env:EXP2CPFE_RUN_ABAQUS
```

The test verifies a nonempty ODB, read-only ODB hash stability, nonempty simulated
HDF5 records with finite values and units, NPZ agreement, all seven completed
stage receipts and recorded artifact hashes. The skip gate permits the two
disabled opt-in checks and missing Torch imports in the offline profile. Every
other skip fails the session, including an enabled solver check that encounters
an unavailable command/license. `EXP2CPFE_TEST_PROFILE` selects `offline`
(default), `cpu-training` or `ml`. CI retains Ubuntu/Windows offline checks,
wheel verification, CPU training checks and a CPU ML job with actual PyG
serialization/readback. See [capabilities and operating conditions](limitations.md).
