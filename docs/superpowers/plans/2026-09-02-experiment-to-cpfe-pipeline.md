# Experiment-to-CPFE Pipeline Implementation Plan

> Historical design/plan. Retained as a development archive; current operation is described in the v0.2.0 guides. Editorial update: 2026-09-27.


**Goal:** Build a solver-agnostic, provenance-preserving local pipeline that imports structured experimental and microstructure data, validates a versioned sample contract, renders a configurable Abaqus INP, runs a real Abaqus job when available, extracts ODB results through the Abaqus Python environment, and exports a cross-language HDF5 dataset.

**Architecture:** Keep the core package independent of any one local dataset, material, directory, or solver. Experiment formats, solver input generation, solver execution, result extraction, and dataset export communicate through typed contracts; Abaqus is the first backend, while DAMASK/VTI and other backends can be added without changing the normalized sample model. Use HDF5 as the canonical derived dataset and treat NPZ/PyTorch/PyG files as reproducible exports.

**Tech Stack:** Python 3.12+, `pydantic` 2.x, `numpy`, `pandas`, `PyYAML`, `h5py`, `pytest`, `build`, Python standard-library `argparse`/`subprocess`/`hashlib`; Abaqus `odbAccess` only inside the optional Abaqus extraction environment.

**Spec:** `docs/superpowers/specs/2026-09-02-experiment-to-cpfe-pipeline-design.md`


> Historical plan: the original 0/55 checkboxes were retained without backfilling. Git command blocks are historical templates.

## Global Constraints

- Core logic must not hardcode any path, sample ID, material name, grain count, loading path, local dataset, or filename from the developer machine.
- The first solver backend is Abaqus; the normalized schema and backend interfaces must not require Abaqus-specific fields.
- An ODB is valid evidence only when produced by an actual Abaqus solve; experimental observations remain labeled as measured data.
- HDF5 is the canonical project container, with explicit vendor adapters. NPZ and PyTorch/PyG are derived formats and must carry the HDF5 source hash, while original vendor files remain referenced by native layout and checksum.
- The normalized contract is modality-neutral and supports `table`, `time_series`, `orientation_map`, `image`, `voxel_grid`, `point_field`, `mesh`, `grain_graph`, and `field_sequence` assets.
- Raw, curated, solver-input, solver-output, and derived-ML layers are separate provenance layers; a conversion must record its parent asset and any lossy transformation.
- Unknown units, coordinate frames, tensor ordering, orientation convention, or required field mappings fail validation instead of being guessed.
- INP generation checks explicit material, geometry, orientation and boundary-condition declarations; experimental curves supply calibration or validation targets.
- Default commands operate on one sample and an explicitly supplied output directory; no command overwrites an existing run directory.
- Abaqus execution uses an ASCII-only staging directory and records datacheck, compile/link, and analysis status separately.
- Offline tests run in a Python environment; configured Abaqus integration tests exercise solver execution.
- Public fixtures are synthetic or redistributable; research inputs and run artifacts use local data directories.
- Every reported result is labeled as measured, inferred, input, simulated, locally rerun, historical, or synthetic.
- A task is complete only after its focused tests pass and its output is inspectable.

---

## File Map

~~~text
experiment-to-cpfe-pipeline/
├── pyproject.toml
├── .gitignore
├── README.md
├── src/experiment_to_cpfe/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── errors.py
│   ├── pipeline.py
│   ├── assets/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── registry.py
│   ├── schema/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── io.py
│   │   ├── calibration.py
│   │   └── validation.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── tabular.py
│   │   ├── ebsd.py
│   │   ├── fields.py
│   │   ├── voxel.py
│   │   └── hdf5_layout.py
│   ├── solvers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── abaqus/
│   │       ├── __init__.py
│   │       ├── inp.py
│   │       ├── static_check.py
│   │       ├── runner.py
│   │       └── extraction.py
│   ├── datasets/
│   │   ├── __init__.py
│   │   ├── package.py
│   │   ├── hdf5.py
│   │   └── asset_store.py
│   └── provenance/
│       ├── __init__.py
│       ├── hashing.py
│       └── manifest.py
├── scripts/
│   └── abaqus_extract_odb.py
├── configs/
│   ├── sample.yaml
│   ├── validation_policy.yaml
│   └── templates/minimal_abaqus.inp
├── examples/synthetic_minimal/
│   ├── sample.yaml
│   ├── experiment.csv
│   ├── grains.csv
│   └── expected_summary.json
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   ├── unit/
│   └── integration/
└── docs/
    ├── schema.md
    └── runbook.md
~~~

The local Abaqus, DAMASK, EBSD, RVE, and ODB examples discovered during reconnaissance are used only through user-local configuration or opt-in integration tests. They are not copied into the core package.

## Task 1: Create the package skeleton and public project conventions

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/experiment_to_cpfe/__init__.py`
- Create: `src/experiment_to_cpfe/errors.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_package.py`

**Interfaces:**
- Package import `experiment_to_cpfe` exposes `__version__ == "0.1.0"`.
- Exception classes are `PipelineError`, `ConfigurationError`, `ValidationError`, `ArtifactError`, and `SolverError`.
- Pytest fixture `synthetic_example_dir` returns `Path("examples/synthetic_minimal")`.

- [ ] **Step 1: Write the failing import test**

~~~python
def test_package_imports_with_version():
    import experiment_to_cpfe

    assert experiment_to_cpfe.__version__ == "0.1.0"


def test_synthetic_fixture_path_is_repo_relative(synthetic_example_dir):
    assert synthetic_example_dir.name == "synthetic_minimal"
~~~

- [ ] **Step 2: Run the focused test to verify it fails**

~~~powershell
python -m pytest tests/unit/test_package.py -q
~~~

Expected: FAIL because the package and fixture are not present.

- [ ] **Step 3: Add package metadata and minimal modules**

Declare Python `>=3.12`, runtime dependencies `numpy`, `pandas`, `pydantic>=2,<3`, `PyYAML`, and `h5py`, optional development dependencies `pytest` and `build`, and console entry point `pipeline = "experiment_to_cpfe.cli:main"`. Define the five exception classes, with the four specific classes directly inheriting from `PipelineError`.

The `.gitignore` must exclude Python caches, virtual environments, build output, `runs/`, solver outputs, local secrets, checkpoints, all large Abaqus files, and the local-only `docs/research/` working directory. It must not exclude source code, synthetic fixtures, schema, configuration templates, or the sanitized public documentation under `docs/`.

- [ ] **Step 4: Run the focused test to verify it passes**

~~~powershell
python -m pytest tests/unit/test_package.py -q
~~~

Expected: PASS with 2 tests.

- [ ] **Step 5: Commit the skeleton**

~~~powershell
~~~

## Task 2: Define the normalized sample contract and JSON serialization

**Files:**
- Create: `src/experiment_to_cpfe/assets/__init__.py`
- Create: `src/experiment_to_cpfe/assets/models.py`
- Create: `src/experiment_to_cpfe/schema/__init__.py`
- Create: `src/experiment_to_cpfe/schema/models.py`
- Create: `src/experiment_to_cpfe/schema/io.py`
- Create: `tests/unit/test_schema_models.py`
- Create: `tests/unit/test_schema_io.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- `SourceKind`: `measured`, `inferred`, `input`, `simulated`, defined in `experiment_to_cpfe.assets.models` and re-exported by `schema.models`.
- `SourceRef(kind, uri, sha256, role)`.
- `AssetKind` and `DataLayer` enums from `experiment_to_cpfe.assets.models`.
- `AssetRef(asset_id, parent_asset_id, modality, format, uri, source_kind, layer, units, coordinate_frame, axis_order, dtype, shape, native_layout, sha256, license, lossy_transformations)` from `experiment_to_cpfe.assets.models`.
- `ModalitySpec(name, format, required_fields, optional_fields)` from `experiment_to_cpfe.assets.models`.
- `CoordinateSpec(name, axes, units)`.
- `OrientationSpec(representation, convention, angle_units, crystal_symmetry)`.
- `SampleMetadata(sample_id, experiment_id, microstructure_id, load_path_id, schema_version, coordinate, unit_system, tensor_order, orientation, sources)`.
- `SamplePackage(metadata, tables, arrays, assets=())`; `tables` and `arrays` may be empty when the sample consists of another modality.
- `dump_sample_json(sample, path) -> None`.
- `load_sample_json(path) -> SamplePackage`.

Reserved table names are `grains`, `grain_boundaries`, `mesh_nodes`, `mesh_elements`, `load_history`, `measured_observations`, and `simulation_records`. Keep large numerical arrays outside Pydantic metadata models.

- [ ] **Step 1: Write the valid-model test**

~~~python
import numpy as np

from experiment_to_cpfe.assets.models import AssetKind, AssetRef, DataLayer, SourceKind
from experiment_to_cpfe.schema.models import (
    CoordinateSpec,
    OrientationSpec,
    SampleMetadata,
    SamplePackage,
    SourceRef,
)


def make_metadata():
    return SampleMetadata(
        sample_id="synthetic-001",
        experiment_id="demo-exp",
        microstructure_id="micro-001",
        load_path_id="uniaxial-z",
        schema_version="0.1",
        coordinate=CoordinateSpec(name="sample", axes=("x", "y", "z"), units="m"),
        unit_system={"length": "m", "stress": "Pa", "time": "s"},
        tensor_order=("11", "22", "33", "12", "13", "23"),
        orientation=OrientationSpec(
            representation="quaternion",
            convention="scalar_first",
            angle_units=None,
            crystal_symmetry="cubic",
        ),
        sources=(
            SourceRef(
                kind=SourceKind.MEASURED,
                uri="examples/synthetic_minimal/experiment.csv",
                sha256=None,
                role="stress_strain_observation",
            ),
        ),
    )


def test_sample_package_preserves_evidence_labels_and_assets():
    sample = SamplePackage(
        metadata=make_metadata(),
        tables={
            "measured_observations": [{"increment_id": "i0", "stress": 0.0}],
            "simulation_records": [{"increment_id": "i0", "stress": 0.0}],
        },
        arrays={"demo": np.array([1.0, 2.0])},
        assets=(
            AssetRef(
                asset_id="asset-curated-001",
                parent_asset_id=None,
                modality=AssetKind.TIME_SERIES,
                format="csv",
                uri="examples/synthetic_minimal/experiment.csv",
                source_kind=SourceKind.MEASURED,
                layer=DataLayer.CURATED,
                units={"stress_33": "Pa", "time": "s"},
                coordinate_frame="sample",
                axis_order=("time",),
                dtype="float64",
                shape=(3, 3),
                native_layout="comma_delimited_columns",
                sha256=None,
                license="synthetic",
                lossy_transformations=(),
            ),
        ),
    )

    assert sample.metadata.sources[0].kind is SourceKind.MEASURED
    assert "simulation_records" in sample.tables
    assert sample.assets[0].modality is AssetKind.TIME_SERIES
~~~

- [ ] **Step 2: Run the model test to verify it fails**

~~~powershell
python -m pytest tests/unit/test_schema_models.py -q
~~~

Expected: FAIL because the schema modules do not exist.

- [ ] **Step 3: Implement strict metadata models**

Use Pydantic v2. Reject empty IDs, unknown orientation representations, empty coordinate axes, empty unit values, duplicate tensor components, and invalid source kinds. Implement `SamplePackage` as a dataclass that checks table names and verifies every array is a NumPy array.

Add a `make_sample` pytest factory to `tests/conftest.py`. It must return the exact metadata from the test above, one `measured_observations` row, one `simulation_records` row, `arrays={"demo": numpy.array([1.0, 2.0])}`, and the `asset-curated-001` time-series asset so later tests share one small, deterministic multimodal package.

- [ ] **Step 4: Write and run the JSON round-trip test**

~~~python
def test_sample_json_round_trip(tmp_path, make_sample):
    from experiment_to_cpfe.schema.io import dump_sample_json, load_sample_json

    source = make_sample()
    output = tmp_path / "sample.json"

    dump_sample_json(source, output)
    restored = load_sample_json(output)

    assert restored.metadata.sample_id == source.metadata.sample_id
    assert restored.metadata.tensor_order == source.metadata.tensor_order
    assert restored.tables == source.tables
    assert restored.arrays["demo"].tolist() == [1.0, 2.0]
~~~

Run:

~~~powershell
python -m pytest tests/unit/test_schema_models.py tests/unit/test_schema_io.py -q
~~~

Expected: PASS.

- [ ] **Step 5: Commit the normalized contract**

~~~powershell
~~~

## Task 3A: Add the modality-neutral asset registry and format inspection

Execute this task before Task 3. It turns the research finding that experimental data arrive as tables, maps, images, voxel grids, point fields, meshes, graphs, and sequences into a first-class interface.

**Files:**
- Create: `src/experiment_to_cpfe/assets/registry.py`
- Create: `src/experiment_to_cpfe/adapters/ebsd.py`
- Create: `src/experiment_to_cpfe/adapters/fields.py`
- Create: `src/experiment_to_cpfe/adapters/voxel.py`
- Create: `src/experiment_to_cpfe/adapters/hdf5_layout.py`
- Create: `tests/unit/test_asset_registry.py`
- Create: `tests/unit/test_modality_adapters.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- `AssetKind`: `table`, `time_series`, `orientation_map`, `image`, `voxel_grid`, `point_field`, `mesh`, `grain_graph`, `field_sequence`.
- `DataLayer`: `raw`, `curated`, `solver_input`, `solver_output`, `derived_ml`.
- `AssetInspection(path, modality, format, size_bytes, dtype, shape, axis_order, units, native_layout, warnings)`.
- `inspect_asset(path: Path, modality_hint: AssetKind | None = None) -> AssetInspection`.
- `register_asset(path: Path, inspection: AssetInspection, source_kind: SourceKind, layer: DataLayer, parent_asset_id: str | None, license: str | None) -> AssetRef`.
- `load_ebsd_text(path: Path, profile: str, column_map: dict[str, str]) -> list[dict[str, object]]`.
- `load_point_field(path: Path, config: dict[str, object]) -> tuple[dict[str, object], numpy.ndarray]`.
- `load_voxel_array(path: Path, config: dict[str, object]) -> tuple[dict[str, object], numpy.ndarray]`.
- `inspect_hdf5_layout(path: Path, layout_name: str | None) -> AssetInspection`.

The first implementation must recognize the following families without pretending their layouts are interchangeable:

- EBSD text: `.ang`, `.ctf`, or generic delimited text with explicit column mapping;
- EBSD binary/HDF5: `.osc`, `.crc`, `.cpr`, `.h5`, `.hdf5`, and `.dream3d`, registered with their native layout and parsed only through an explicit layout profile;
- DIC/DVC point or regular-grid tables and NumPy/HDF5 arrays;
- voxel arrays from `.npy` and HDF5, with a later extension point for VTK/VTI/TIFF stacks;
- existing meshes and solver inputs as `mesh`/`solver_input` assets.

Never overwrite a vendor file. A normalized asset receives a new asset ID and points to the original asset through `parent_asset_id`. Every adapter records whether it performed interpolation, resampling, aggregation, coordinate transformation, or unit conversion.

- [ ] **Step 1: Write failing inspection and registry tests**

~~~python
def test_registry_preserves_native_layout_and_parent_asset(tmp_path):
    from experiment_to_cpfe.assets.models import AssetKind, DataLayer, SourceKind
    from experiment_to_cpfe.assets.registry import inspect_asset, register_asset

    source = tmp_path / "vendor.h5"
    source.write_bytes(b"not-a-universal-layout")
    inspection = inspect_asset(source, AssetKind.ORIENTATION_MAP)
    asset = register_asset(
        source,
        inspection,
        SourceKind.MEASURED,
        DataLayer.RAW,
        parent_asset_id=None,
        license="user-supplied",
    )

    assert asset.modality is AssetKind.ORIENTATION_MAP
    assert asset.layer is DataLayer.RAW
    assert asset.native_layout
    assert asset.parent_asset_id is None


def test_ebsd_text_requires_explicit_column_mapping(tmp_path):
    import pytest
    from experiment_to_cpfe.adapters.ebsd import load_ebsd_text

    path = tmp_path / "map.ang"
    path.write_text("1,2,3,1,0.0,0.0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="column mapping"):
        load_ebsd_text(path, profile="generic", column_map={})
~~~

- [ ] **Step 2: Run the focused tests to verify failure**

~~~powershell
python -m pytest tests/unit/test_asset_registry.py tests/unit/test_modality_adapters.py -q
~~~

Expected: FAIL because the asset models and adapters do not exist.

- [ ] **Step 3: Implement inspection and explicit-layout adapters**

`inspect_asset` reads file metadata without loading large arrays. It reports extension, byte size, array shape when cheaply available, and unknown-layout warnings. `load_ebsd_text` maps only configured columns to coordinates, phase, orientation, and quality fields. `inspect_hdf5_layout` requires a named layout profile for vendor/HDF5 data and records the selected HDF5 path hierarchy. `load_point_field` preserves point coordinates or grid axes, and `load_voxel_array` preserves origin, spacing, axis order, dtype, and shape.

Add fixtures to `tests/conftest.py` for a three-row generic EBSD table, a four-point DIC displacement field, and a `2 x 2 x 2` voxel array. Add adapter tests that verify units and axes are metadata, not guessed from filenames.

- [ ] **Step 4: Run modality tests**

~~~powershell
python -m pytest tests/unit/test_asset_registry.py tests/unit/test_modality_adapters.py -q
~~~

Expected: PASS.

- [ ] **Step 5: Commit the modality layer**

~~~powershell
~~~

## Task 3: Implement generic table ingestion and configuration loading

**Files:**
- Create: `src/experiment_to_cpfe/config.py`
- Create: `src/experiment_to_cpfe/adapters/__init__.py`
- Create: `src/experiment_to_cpfe/adapters/tabular.py`
- Create: `configs/sample.yaml`
- Create: `examples/synthetic_minimal/sample.yaml`
- Create: `examples/synthetic_minimal/experiment.csv`
- Create: `examples/synthetic_minimal/grains.csv`
- Create: `examples/synthetic_minimal/expected_summary.json`
- Create: `tests/unit/test_config.py`
- Create: `tests/unit/test_tabular_adapter.py`

**Interfaces:**
- `TabularSourceConfig(path, table_name, source_kind, delimiter, encoding, column_map)`.
- `PipelineConfig(sample, sources, abaqus, export)`.
- `load_pipeline_config(path) -> PipelineConfig`.
- `load_tabular_source(config) -> list[dict[str, object]]`.
- `assemble_sample(config) -> SamplePackage`.

The generic adapter accepts CSV and delimiter-separated TXT. It must use explicit column mappings and must not infer units from column names.

- [ ] **Step 1: Write the failing config-loading test**

~~~python
from pathlib import Path


def test_load_synthetic_config_resolves_paths():
    from experiment_to_cpfe.config import load_pipeline_config

    config = load_pipeline_config(Path("examples/synthetic_minimal/sample.yaml"))

    assert config.sample.sample_id == "synthetic-001"
    assert config.sources[0].table_name == "measured_observations"
    assert config.sources[0].path.name == "experiment.csv"
~~~

- [ ] **Step 2: Run it to verify it fails**

~~~powershell
python -m pytest tests/unit/test_config.py -q
~~~

Expected: FAIL because configuration models and fixture files are absent.

- [ ] **Step 3: Implement safe YAML loading and relative path resolution**

Use `yaml.safe_load`. Resolve relative paths against the directory containing the YAML file, never against the process working directory. Require explicit unit, coordinate, tensor-order, orientation, and source-kind blocks. Include an `abaqus` block and an `export` block now so later stages use the same configuration shape. Use a list for `abaqus.command`, for example `["abaqus.bat"]`, so a test command can be represented as `["python", "tests/fixtures/fake_solver.py"]` without shell parsing ambiguity.

- [ ] **Step 4: Write ingestion tests and synthetic fixtures**

~~~python
def test_tabular_adapter_does_not_guess_units():
    from experiment_to_cpfe.adapters.tabular import load_tabular_source
    from experiment_to_cpfe.config import load_pipeline_config

    config = load_pipeline_config(Path("examples/synthetic_minimal/sample.yaml"))
    rows = load_tabular_source(config.sources[0])

    assert rows[0]["increment_id"] == "i0"
    assert rows[0]["stress_33"] == 0.0
    assert "unit" not in rows[0]


def test_assemble_sample_preserves_tables():
    from experiment_to_cpfe.adapters.tabular import assemble_sample
    from experiment_to_cpfe.config import load_pipeline_config

    config = load_pipeline_config(Path("examples/synthetic_minimal/sample.yaml"))
    sample = assemble_sample(config)

    assert set(sample.tables) == {"measured_observations", "grains"}
    assert sample.metadata.sources[0].kind.value == "measured"
~~~

Run:

~~~powershell
python -m pytest tests/unit/test_config.py tests/unit/test_tabular_adapter.py -q
~~~

Expected: PASS.

Write `examples/synthetic_minimal/expected_summary.json` with this exact content:

~~~json
{
  "sample_id": "synthetic-001",
  "table_counts": {
    "measured_observations": 3,
    "grains": 2
  }
}
~~~

- [ ] **Step 5: Commit generic ingestion**

~~~powershell
~~~

## Task 4: Add validation, reports, hashing, and provenance

**Files:**
- Create: `src/experiment_to_cpfe/schema/validation.py`
- Create: `src/experiment_to_cpfe/schema/calibration.py`
- Create: `src/experiment_to_cpfe/provenance/__init__.py`
- Create: `src/experiment_to_cpfe/provenance/hashing.py`
- Create: `src/experiment_to_cpfe/provenance/manifest.py`
- Create: `configs/validation_policy.yaml`
- Create: `tests/unit/test_validation.py`
- Create: `tests/unit/test_provenance.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- `ValidationIssue(code, severity, message, location)`.
- `ValidationReport(issues)` with `errors`, `warnings`, `passed`, and `to_dict()`.
- `ValidationPolicy(quaternion_tolerance, require_finite, missing_units_severity, required_tables_by_profile, required_assets_by_solver)`; modality-specific tables are optional unless the selected profile requires them.
- `load_validation_policy(path) -> ValidationPolicy`.
- `validate_sample(sample, policy) -> ValidationReport`.
- `validate_asset_links(sample, policy) -> tuple[ValidationIssue, ...]`.
- `SolverReadinessReport(missing: tuple[str, ...], warnings: tuple[str, ...], ready: bool)`.
- `check_solver_readiness(sample, solver_name: str) -> SolverReadinessReport`.
- `CalibrationTarget(source_asset_id: str, response_kind: str, observation_table: str, split_role: str)`.
- `make_calibration_target(sample) -> CalibrationTarget`.
- `write_validation_report(report, json_path, markdown_path) -> None`.
- `sha256_file(path, chunk_size=1048576) -> str`.
- `create_run_directory(root, sample_id, run_id) -> Path`.
- `build_run_manifest(run_dir, config_path, stage_records) -> dict[str, object]`.
- `write_manifest(manifest, path) -> None`.

Validation must check IDs, units, coordinate metadata, quaternion norm within `1e-6`, finite numeric values, increment continuity, table names, grain references, explicit evidence labels, and required STATEV presence. Cross-modal validation must also check experiment/specimen/microstructure IDs, parent-asset chains, spatial registration, coordinate transforms, time/load alignment, phase/grain references, axis order, and native layout declarations. It must never fill missing values.

`check_solver_readiness` must require, for Abaqus CPFE, a geometry/mesh asset, a microstructure-to-mesh mapping, a material model and parameters or an explicit calibration result, orientation data when the model requires it, loading/boundary conditions, and an output-variable contract. A measured stress-strain curve without the other requirements returns `ready=False` with `MISSING_SOLVER_INPUT` items.

- [ ] **Step 1: Write failing validation tests**

~~~python
def test_synthetic_sample_passes_validation(make_sample, validation_policy):
    from experiment_to_cpfe.schema.validation import validate_sample

    report = validate_sample(make_sample(), validation_policy)

    assert report.passed
    assert report.errors == ()


def test_missing_units_is_an_error(make_sample, validation_policy):
    from experiment_to_cpfe.schema.validation import validate_sample

    sample = make_sample()
    sample.metadata = sample.metadata.model_copy(update={"unit_system": {}})

    report = validate_sample(sample, validation_policy)

    assert not report.passed
    assert any(issue.code == "MISSING_UNIT" for issue in report.errors)


def test_curve_only_sample_is_not_solver_ready(make_sample, validation_policy):
    from experiment_to_cpfe.schema.validation import check_solver_readiness

    readiness = check_solver_readiness(make_sample(), "abaqus_cpfe")

    assert not readiness.ready
    assert any("geometry" in item for item in readiness.missing)
    assert any("material" in item for item in readiness.missing)


def test_measured_curve_is_registered_as_calibration_target(make_sample):
    from experiment_to_cpfe.schema.calibration import make_calibration_target

    target = make_calibration_target(make_sample())

    assert target.response_kind == "stress_strain"
    assert target.observation_table == "measured_observations"
    assert target.split_role == "calibration_or_validation"
~~~

- [ ] **Step 2: Run them to verify failure**

~~~powershell
python -m pytest tests/unit/test_validation.py -q
~~~

Expected: FAIL because validation and provenance modules are absent.

- [ ] **Step 3: Implement pure validation and deterministic reports**

Load thresholds from `validation_policy.yaml`; default quaternion tolerance to `1e-6`, finite-number enforcement to true, missing units to error, and solver readiness requirements to the explicit list in this task. Add a `validation_policy` fixture to `tests/conftest.py` that returns those defaults. `make_calibration_target` must register a measured curve as a calibration/validation observation and never turn it into a complete material card. Render stable JSON and Markdown. Keep issue codes deterministic so tests and downstream tools can rely on them.

Implement streaming SHA-256, safe run-directory creation with fixed `input`, `solver`, `dataset`, and `reports` subdirectories, and manifests that record hashes, commands, timestamps, statuses, artifacts, and limitations without secret environment values.

- [ ] **Step 4: Write and run provenance tests**

~~~python
def test_sha256_file_matches_known_digest(tmp_path):
    from experiment_to_cpfe.provenance.hashing import sha256_file

    path = tmp_path / "input.txt"
    path.write_text("abc", encoding="utf-8")

    assert sha256_file(path) == (
        "ba7816bf8f01cfea414140de5dae2223"
        "b00361a396177a9cb410ff61f20015ad"
    )


def test_run_directory_rejects_existing_nonempty_path(tmp_path):
    import pytest
    from experiment_to_cpfe.provenance.manifest import create_run_directory

    target = tmp_path / "synthetic-001" / "run-001"
    target.mkdir(parents=True)
    (target / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_run_directory(tmp_path, "synthetic-001", "run-001")
~~~

Run:

~~~powershell
python -m pytest tests/unit/test_validation.py tests/unit/test_provenance.py -q
~~~

Expected: PASS.

- [ ] **Step 5: Commit validation and provenance**

~~~powershell
~~~

## Task 5: Implement the template-driven Abaqus INP adapter

**Files:**
- Create: `src/experiment_to_cpfe/solvers/__init__.py`
- Create: `src/experiment_to_cpfe/solvers/base.py`
- Create: `src/experiment_to_cpfe/solvers/abaqus/__init__.py`
- Create: `src/experiment_to_cpfe/solvers/abaqus/inp.py`
- Create: `src/experiment_to_cpfe/solvers/abaqus/static_check.py`
- Create: `configs/templates/minimal_abaqus.inp`
- Create: `tests/unit/test_abaqus_inp.py`
- Create: `tests/unit/test_abaqus_static_check.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- `SolverInputRequest(template_path, output_path, replacements)`.
- `InpBuildResult(output_path, sha256, replacements)`.
- `build_inp(request) -> InpBuildResult`.
- `build_solver_input(sample, template_path, output_path) -> InpBuildResult`.
- `StaticCheckReport(errors, warnings, counts)`.
- `static_check_inp(path) -> StaticCheckReport`.

Use explicit markers `{{HEADING}}`, `{{NODES}}`, `{{ELEMENTS}}`, `{{MATERIALS}}`, `{{BOUNDARY_CONDITIONS}}`, and `{{OUTPUT_REQUESTS}}`. The renderer rejects unknown markers, missing required replacements, null bytes, and an existing output path.

The static checker counts nodes, elements, sets, materials, steps, and output blocks; detects duplicate labels in generated blocks; checks referenced set names; and treats missing steps or empty node/element blocks as errors. The low-level renderer may render a template fixture, but `build_solver_input` must call `check_solver_readiness(sample, "abaqus_cpfe")` first and refuse to create an INP when readiness is false. A curve-only sample produces the missing-input report and no solver input.

- [ ] **Step 1: Write the failing renderer test**

~~~python
def test_build_inp_replaces_all_known_markers(tmp_path, synthetic_replacements):
    from experiment_to_cpfe.solvers.abaqus.inp import SolverInputRequest, build_inp

    template = tmp_path / "template.inp"
    output = tmp_path / "model.inp"
    template.write_text(
        "*HEADING\n{{HEADING}}\n{{NODES}}\n{{ELEMENTS}}\n"
        "{{MATERIALS}}\n{{BOUNDARY_CONDITIONS}}\n{{OUTPUT_REQUESTS}}\n",
        encoding="utf-8",
    )

    result = build_inp(
        SolverInputRequest(
            template_path=template,
            output_path=output,
            replacements=synthetic_replacements,
        )
    )

    assert result.output_path == output
    assert "{{" not in output.read_text(encoding="utf-8")
    assert len(result.sha256) == 64
~~~

- [ ] **Step 2: Run it to verify failure**

~~~powershell
python -m pytest tests/unit/test_abaqus_inp.py -q
~~~

Expected: FAIL because the Abaqus adapter is absent.

- [ ] **Step 3: Implement generic rendering and static checks**

Keep the renderer unaware of EBSD, CPFE, a specific material, and local paths. Generate the synthetic template with a two-element cube. Have the static checker return structured counts and errors without launching Abaqus.

Add a `synthetic_replacements` fixture to `tests/conftest.py` with non-empty strings for all six markers, including eight unique node labels and two unique element labels. This fixture is the only input used by the renderer unit test.

- [ ] **Step 4: Add the solver-readiness gate test**

~~~python
def test_build_solver_input_rejects_curve_only_sample(tmp_path, make_sample):
    import pytest
    from pathlib import Path

    from experiment_to_cpfe.solvers.abaqus.inp import build_solver_input

    with pytest.raises(ValueError, match="MISSING_SOLVER_INPUT"):
        build_solver_input(
            make_sample(),
            Path("configs/templates/minimal_abaqus.inp"),
            tmp_path / "should-not-exist.inp",
        )
~~~

- [ ] **Step 5: Write and run static-check tests**

~~~python
def test_static_check_accepts_minimal_fixture():
    from pathlib import Path

    from experiment_to_cpfe.solvers.abaqus.static_check import static_check_inp

    report = static_check_inp(Path("configs/templates/minimal_abaqus.inp"))

    assert report.errors == ()
    assert report.counts["nodes"] > 0
    assert report.counts["elements"] > 0


def test_static_check_rejects_empty_nodes(tmp_path):
    from experiment_to_cpfe.solvers.abaqus.static_check import static_check_inp

    path = tmp_path / "empty.inp"
    path.write_text(
        "*NODE\n*ELEMENT, TYPE=C3D8\n1, 1,2,3,4,5,6,7,8\n",
        encoding="utf-8",
    )

    report = static_check_inp(path)

    assert any("empty node block" in error for error in report.errors)
~~~

Run:

~~~powershell
python -m pytest tests/unit/test_abaqus_inp.py tests/unit/test_abaqus_static_check.py -q
~~~

Expected: PASS.

- [ ] **Step 6: Commit the INP adapter**

~~~powershell
~~~

## Task 6: Implement staged Abaqus execution

**Files:**
- Create: `src/experiment_to_cpfe/solvers/abaqus/runner.py`
- Create: `tests/unit/test_abaqus_runner.py`
- Create: `tests/fixtures/fake_solver.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- `SolverStage`: `datacheck`, `analysis`.
- `AbaqusRunRequest(abaqus_command: tuple[str, ...], job_name, inp_path, work_dir, stage, user_subroutine, cpus, timeout_seconds)`.
- `SolverRunResult(stage, status, command, return_code, stdout_path, stderr_path, artifacts, limitations)`.
- `run_abaqus(request) -> SolverRunResult`.
- `expected_artifacts(job_name, stage) -> tuple[str, ...]`.

The runner uses bounded `subprocess.run`, writes stdout/stderr, uses `cmd.exe /d /c` for Windows batch commands, never removes files, and keeps datacheck and analysis separate. A zero return code without expected artifacts is `failed`. Missing command, compiler, or license evidence is `blocked`.

- [ ] **Step 1: Write the fake-solver tests**

~~~python
def test_runner_records_completed_stage(tmp_path):
    import sys
    from pathlib import Path

    from experiment_to_cpfe.solvers.abaqus.runner import (
        AbaqusRunRequest,
        SolverStage,
        run_abaqus,
    )

    work_dir = tmp_path / "solver"
    work_dir.mkdir()
    inp = work_dir / "model.inp"
    inp.write_text("*HEADING\n", encoding="utf-8")

    result = run_abaqus(
        AbaqusRunRequest(
            abaqus_command=(sys.executable, str(Path("tests/fixtures/fake_solver.py").resolve())),
            job_name="synthetic",
            inp_path=inp,
            work_dir=work_dir,
            stage=SolverStage.ANALYSIS,
            user_subroutine=None,
            cpus=1,
            timeout_seconds=10,
        )
    )

    assert result.status == "completed"
    assert result.return_code == 0
    assert (work_dir / "synthetic.odb").exists()


def test_runner_marks_missing_output_as_failure(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    from experiment_to_cpfe.solvers.abaqus.runner import (
        AbaqusRunRequest,
        SolverStage,
        run_abaqus,
    )

    work_dir = tmp_path / "solver"
    work_dir.mkdir()
    inp = work_dir / "model.inp"
    inp.write_text("*HEADING\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_SOLVER_NO_OUTPUT", "1")

    result = run_abaqus(
        AbaqusRunRequest(
            abaqus_command=(sys.executable, str(Path("tests/fixtures/fake_solver.py").resolve())),
            job_name="synthetic",
            inp_path=inp,
            work_dir=work_dir,
            stage=SolverStage.ANALYSIS,
            user_subroutine=None,
            cpus=1,
            timeout_seconds=10,
        )
    )

    assert result.status == "failed"
    assert any("expected artifact" in item for item in result.limitations)
~~~

The fake solver accepts `job=<name>`, `input=<file>`, and `stage=<datacheck|analysis>`. For analysis it writes small fixture files; it omits them when `FAKE_SOLVER_NO_OUTPUT=1`.

- [ ] **Step 2: Run tests to verify failure**

~~~powershell
python -m pytest tests/unit/test_abaqus_runner.py -q
~~~

Expected: FAIL because the runner and fixture do not exist.

- [ ] **Step 3: Implement command construction and artifact evidence**

Represent commands as tuples in manifests. For a Python fake executable, pass `(sys.executable, script_path)`; for a real `.bat` command whose first tuple item ends in `.bat`, prepend `cmd.exe /d /c` and preserve the remaining arguments. Stage the INP only when it is outside the work directory and record source/staged hashes. Do not infer material validity from a successful process exit.

- [ ] **Step 4: Run the focused runner suite**

~~~powershell
python -m pytest tests/unit/test_abaqus_runner.py -q
~~~

Expected: PASS.

- [ ] **Step 5: Commit the staged runner**

~~~powershell
~~~

## Task 7: Add the ODB extraction bridge and canonical HDF5 export

**Files:**
- Create: `src/experiment_to_cpfe/solvers/abaqus/extraction.py`
- Create: `scripts/abaqus_extract_odb.py`
- Create: `src/experiment_to_cpfe/datasets/__init__.py`
- Create: `src/experiment_to_cpfe/datasets/package.py`
- Create: `src/experiment_to_cpfe/datasets/hdf5.py`
- Create: `src/experiment_to_cpfe/datasets/asset_store.py`
- Create: `tests/unit/test_abaqus_extraction.py`
- Create: `tests/unit/test_hdf5_roundtrip.py`
- Create: `tests/fixtures/odb_extract_fixture/metadata.json`
- Create: `tests/fixtures/odb_extract_fixture/frames.csv`

**Interfaces:**
- `ExtractionRequest(odb_path, output_dir, fields, position)`.
- `build_abaqus_extraction_command(request, abaqus_command: tuple[str, ...]) -> tuple[str, ...]`.
- `load_extraction_bundle(path) -> SamplePackage`.
- `extraction_bundle_is_complete(path) -> tuple[bool, tuple[str, ...]]`.
- `write_hdf5(sample, path, source_manifest=None) -> str`.
- `read_hdf5(path) -> SamplePackage`.
- `write_asset_store(sample, path, source_manifest=None) -> str`.
- `read_asset_store(path) -> SamplePackage`.
- `write_npz(sample, path, source_hdf5_sha256) -> None`.
- `dataset_summary(sample) -> dict[str, object]`.

The host bridge must not import `odbAccess`. The Abaqus-side script runs through `abaqus python`, opens the ODB read-only, preserves step/frame/element/integration-point labels and original field names, reports missing fields, never replaces missing STATEV with zeros, closes the ODB in `finally`, and writes JSON/CSV intermediate files. HDF5 writing occurs in the standard Python environment.

HDF5 groups are `/meta`, `/assets`, `/geometry`, `/mesh`, `/grains`, `/grain_boundaries`, `/load_history`, `/measured`, `/simulation`, `/macro_response`, `/derived`, `/provenance`, and `/quality`. Each asset group stores its modality, native format/layout, layer, units, axis order, shape, dtype, source hash, parent asset ID, and lossy-transform record. Arrays may be chunked/compressed and may be ragged through offset/value datasets. NPZ/PyG exports require a non-empty HDF5 source hash.

- [ ] **Step 1: Write extraction and HDF5 round-trip tests**

~~~python
def test_extraction_command_preserves_paths(tmp_path):
    from pathlib import Path

    from experiment_to_cpfe.solvers.abaqus.extraction import (
        ExtractionRequest,
        build_abaqus_extraction_command,
    )

    request = ExtractionRequest(
        odb_path=tmp_path / "job.odb",
        output_dir=tmp_path / "extracted",
        fields=("S", "LE", "SDV"),
        position="integration_point",
    )

    command = build_abaqus_extraction_command(request, ("abaqus.bat",))
    text = " ".join(command)

    assert "job.odb" in text
    assert "extracted" in text
    assert "S,LE,SDV" in text


def test_hdf5_round_trip_preserves_sample(tmp_path, make_sample):
    from experiment_to_cpfe.datasets.hdf5 import read_hdf5, write_hdf5

    source = make_sample()
    output = tmp_path / "sample.h5"

    digest = write_hdf5(source, output)
    restored = read_hdf5(output)

    assert len(digest) == 64
    assert restored.metadata.sample_id == source.metadata.sample_id
    assert restored.tables == source.tables
    assert restored.arrays["demo"].tolist() == [1.0, 2.0]
~~~

- [ ] **Step 2: Run tests to verify failure**

~~~powershell
python -m pytest tests/unit/test_abaqus_extraction.py tests/unit/test_hdf5_roundtrip.py -q
~~~

Expected: FAIL because extraction and dataset modules do not exist.

- [ ] **Step 3: Implement the Abaqus-side bundle and host loader**

Use only standard-library JSON/CSV in `scripts/abaqus_extract_odb.py`. The host loader converts the bundle into `SamplePackage`. Missing requested fields become explicit issue records rather than zero-filled arrays. Include extraction version, ODB hash, step/frame metadata, field list, and missing-field list.

- [ ] **Step 4: Implement canonical HDF5 and derived NPZ output**

Store metadata attributes and normalized JSON under `/provenance`. Preserve numeric dtype, shape, axis labels, spacing, and origin. Store table columns as typed datasets where possible and JSON strings only for metadata objects. Keep original vendor files outside the canonical file and store their URI/path, native layout, license, and checksum as references. Reject existing output paths and empty HDF5 source hashes.

- [ ] **Step 5: Run the focused extraction and dataset suite**

~~~powershell
python -m pytest tests/unit/test_abaqus_extraction.py tests/unit/test_hdf5_roundtrip.py -q
~~~

Expected: PASS.

- [ ] **Step 6: Commit the extraction and dataset layers**

~~~powershell
~~~

## Task 8: Add orchestration, offline example, documentation, and optional integration

**Files:**
- Create: `src/experiment_to_cpfe/pipeline.py`
- Create: `src/experiment_to_cpfe/cli.py`
- Create: `tests/unit/test_pipeline.py`
- Create: `tests/integration/test_offline_pipeline.py`
- Create: `tests/integration/test_abaqus_optional.py`
- Create: `docs/schema.md`
- Create: `docs/data-modalities.md`
- Create: `docs/runbook.md`
- Create: `.github/workflows/tests.yml`
- Create: `README.md`
- Modify: `tests/conftest.py`

**Interfaces:**
- `run_validate(config_path, run_dir) -> dict[str, object]`.
- `run_build_inp(config_path, run_dir) -> dict[str, object]`.
- `run_abaqus_stage(config_path, run_dir, stage) -> dict[str, object]`.
- `run_extract_odb(config_path, run_dir) -> dict[str, object]`.
- `run_export(config_path, run_dir, format_name) -> dict[str, object]`.
- `main(argv: list[str] | None = None) -> int`.

CLI commands:

~~~text
pipeline validate --config <path> --run-dir <path>
pipeline build-inp --config <path> --run-dir <path>
pipeline run-abaqus --config <path> --run-dir <path> --stage datacheck|analysis
pipeline extract-odb --config <path> --run-dir <path>
pipeline export --config <path> --run-dir <path> --format hdf5|npz
pipeline inspect --run-dir <path>
~~~

Every stage writes a stage record and `reports/run_manifest.json`. `validate` also writes `reports/solver_readiness.json` and fails the requested stage when cross-modal asset links or required solver inputs are invalid. The offline stages do not require Abaqus. The runner stage refuses to reuse a completed stage in the same run directory.

- [ ] **Step 1: Write the CLI and offline-pipeline tests**

~~~python
def test_validate_and_export_commands_write_artifacts(tmp_path):
    from experiment_to_cpfe.cli import main

    run_dir = tmp_path / "offline-run"
    config = "examples/synthetic_minimal/sample.yaml"

    assert main(["validate", "--config", config, "--run-dir", str(run_dir)]) == 0
    assert main(["build-inp", "--config", config, "--run-dir", str(run_dir)]) == 0
    assert main([
        "export", "--config", config, "--run-dir", str(run_dir), "--format", "hdf5"
    ]) == 0

    assert (run_dir / "reports" / "validation.json").exists()
    assert (run_dir / "input" / "model.inp").exists()
    assert (run_dir / "dataset" / "sample.h5").exists()


def test_unknown_command_returns_usage_error():
    from experiment_to_cpfe.cli import main

    assert main(["not-a-command"]) == 2
~~~

- [ ] **Step 2: Add multimodal offline fixtures and assertions**

Extend `examples/synthetic_minimal/sample.yaml` and its fixture factory with one orientation-map table, one four-point DIC displacement grid, one `2 x 2 x 2` voxel array, one two-grain mesh/INP asset, and one three-row stress-strain time series. Add a `multimodal_sample_config` fixture to `tests/conftest.py` that writes these tiny files into pytest's `tmp_path` and returns the generated YAML path. The test must assert that the pipeline preserves each modality, its units, axis order, and parent asset links through the HDF5 export. It must not reference developer-machine drives, user-home directories, or local installation paths.

~~~python
def test_offline_export_preserves_multiple_modalities(tmp_path, multimodal_sample_config):
    from experiment_to_cpfe.adapters.tabular import assemble_sample
    from experiment_to_cpfe.config import load_pipeline_config
    from experiment_to_cpfe.datasets.hdf5 import read_hdf5, write_hdf5

    config = load_pipeline_config(multimodal_sample_config)
    sample = assemble_sample(config)
    output = tmp_path / "multimodal.h5"

    write_hdf5(sample, output)
    restored = read_hdf5(output)

    modalities = {asset.modality.value for asset in restored.assets}
    assert {"orientation_map", "point_field", "voxel_grid", "mesh", "time_series"} <= modalities
    assert any(asset.axis_order == ("z", "y", "x") for asset in restored.assets)
    assert any(asset.parent_asset_id for asset in restored.assets)
~~~

- [ ] **Step 3: Run tests to verify failure**

~~~powershell
python -m pytest tests/unit/test_pipeline.py tests/integration/test_offline_pipeline.py -q
~~~

Expected: FAIL because orchestration and CLI modules do not exist.

- [ ] **Step 4: Implement stage orchestration and CLI**

Keep each stage callable without the CLI. `validate` calls both `validate_asset_links` and `check_solver_readiness`. `build-inp` calls `build_solver_input` and never emits an INP for a curve-only or otherwise incomplete sample. `inspect` prints statuses, artifact paths, modality counts, and limitations. Return exit code 0 only for a passed/completed stage, 2 for usage/configuration errors, and 1 for a failed or blocked requested stage.

- [ ] **Step 5: Add optional Abaqus integration**

Gate the test with `EXP2CPFE_RUN_ABAQUS=1`, `EXP2CPFE_ABAQUS_CONFIG`, and `EXP2CPFE_ABAQUS_RUN_DIR`. Skip clearly when these are absent; never reference a hardcoded local fixture. A user-supplied small INP/config may produce completed or blocked evidence.

- [ ] **Step 6: Write generic documentation and CI**

`docs/schema.md` documents fields, units, coordinate frames, evidence labels, asset layers, and HDF5 groups without local paths or material-specific assumptions. `docs/data-modalities.md` documents EBSD `.ang/.ctf`, vendor HDF5/DREAM.3D, DIC/DVC fields, CT/voxel arrays, diffraction/grain tables, mechanical time series, Neper/FE meshes, and the loss/registration rules for each adapter. `docs/runbook.md` documents the six CLI stages and explains that solver artifacts and manifests are evidence. `README.md` explains installation, the synthetic multimodal example, adapter extension points for EBSD/DIC/DAMASK, and the public-data boundary. The YAML key `abaqus.command` is a list of command tokens, such as `["abaqus"]`, so the same configuration model can also run a test command such as `["python", "tests/fixtures/fake_solver.py"]`.

The GitHub Actions workflow installs development dependencies, runs `python -m pytest -q`, and runs `python -m build` without Abaqus or local files. The offline integration test must exercise at least an orientation table, a point/grid field, a voxel array, a mesh/INP asset, and a mechanical time series before exporting HDF5.

- [ ] **Step 7: Run the complete local no-solver verification**

~~~powershell
python -m pytest -q
python -m build
pipeline validate --config examples/synthetic_minimal/sample.yaml --run-dir runs/qa-synthetic-001
pipeline inspect --run-dir runs/qa-synthetic-001
~~~

Expected: all no-solver tests pass; the optional Abaqus test is skipped unless enabled; the synthetic manifest reports validation as passed.

- [ ] **Step 8: Commit orchestration and documentation**

~~~powershell
~~~

## Task 9: Release audit and GitHub publication gate

**Files:**
- Modify: `.gitignore` only when the release audit identifies a missing exclusion.
- Modify: `README.md` only when installation or limitation text is inaccurate.
- Create: `docs/release_checklist.md`.

**Publication gate:** Do not create a remote repository or push until the user confirms the exact repository destination and chooses public/private visibility. A local Git committer identity must be configured before committing or pushing.

- [ ] **Step 1: Run tracked-file privacy and portability checks**

~~~powershell
git ls-files --cached --others --exclude-standard
rg -l -i "[a-z]:[\\/]|password|token|secret|private[_-]?key|id_rsa|\.odb|\.cae" .
~~~

Review both tracked and non-ignored untracked candidates, including design and plan documents. The search emits filenames only; inspect any potential credentials privately without copying their values into reports. Expected: no developer-machine paths, credentials, raw ODB/CAE files, or private manifests in public candidates. Generic format mentions, prohibition rules and synthetic rejection tests must be reviewed in context. Scan reachable Git history separately; a clean worktree scan does not erase past disclosures.

- [ ] **Step 2: Run the package and synthetic release checks**

~~~powershell
python -m pytest -q
python -m build
pipeline validate --config examples/synthetic_minimal/sample.yaml --run-dir runs/release-synthetic-001
pipeline build-inp --config examples/synthetic_minimal/sample.yaml --run-dir runs/release-synthetic-001
pipeline export --config examples/synthetic_minimal/sample.yaml --run-dir runs/release-synthetic-001 --format hdf5
~~~

Expected: tests pass, wheel and source archive exist, and the synthetic HDF5 package is readable.

- [ ] **Step 3: Verify GitHub authentication without mutating the remote**

~~~powershell
git status --short --branch
gh auth status
~~~

Expected: clean local branch and clear authentication result. If GitHub CLI is not authenticated, stop and ask the user to authenticate; do not embed tokens in remotes.

- [ ] **Step 4: Publish only after the user confirms destination and visibility**

For the planned repository name, use the command matching the user's confirmed visibility:

~~~powershell
# Public repository:

# Private repository:
~~~

Verify:

~~~powershell
git remote -v
git status --short --branch
gh repo view --web
~~~

Expected: origin points to the confirmed repository, the published branch contains only validated project files, and no private artifact was pushed.

## Final Verification Matrix

| Area | Command | Required evidence |
|---|---|---|
| Package | `python -m pytest -q` | All no-solver tests pass; optional Abaqus test is explicit skip or pass |
| Build | `python -m build` | Wheel and source archive exist under `dist/` |
| Schema | `pipeline validate ...` | JSON and Markdown reports show reasons and evidence labels |
| Modalities | `pytest tests/unit/test_asset_registry.py tests/unit/test_modality_adapters.py` | EBSD, DIC/DVC, voxel, mesh, graph, and time-series assets retain native layout and provenance |
| Readiness | `pipeline validate ...` | Curve-only or missing-input sample produces `ready=false` and a missing-input report |
| INP | `pipeline build-inp ...` | Generated INP and static-check counts exist |
| Provenance | `pipeline inspect ...` | Manifest contains config/source/artifact hashes and stage statuses |
| Dataset | `pipeline export ... --format hdf5` | HDF5 round trip restores IDs, units, arrays, and source labels |
| Abaqus | opt-in integration command | Real ODB plus STA/DAT/MSG, or explicit blocked evidence |
| Public release | tracked-file audit and CI | No local/private artifacts; CI passes without Abaqus |

The first release is complete only when the synthetic sample passes the offline stages and a user-supplied, not hardcoded, Abaqus-compatible sample can be routed through the optional real-solver stages with an auditable result or an explicit data/environment block.
