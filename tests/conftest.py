from pathlib import Path
import os

import numpy as np
import pytest


class _SkipGate:
    """Fail sessions with skips outside the explicit job-specific allowance."""

    def __init__(self, profile):
        self.profile = profile
        self.unexpected = []

    def _observe(self, report):
        if not report.skipped:
            return
        reason = str(report.longrepr[2]).removeprefix("Skipped: ")
        node = report.nodeid.replace("\\", "/")
        opt_ins = {
            "tests/integration/test_abaqus_optional.py::test_user_supplied_real_abaqus_roundtrip": (
                os.environ.get("EXP2CPFE_RUN_ABAQUS") != "1",
                "real Abaqus integration is opt-in via EXP2CPFE_RUN_ABAQUS=1",
            ),
            "tests/integration/test_installed_wheel.py::test_wheel_installation_outside_checkout": (
                not os.environ.get("EXP2CPFE_WHEEL_DIR"),
                "set EXP2CPFE_WHEEL_DIR after building the wheel",
            ),
        }
        disabled, expected_reason = opt_ins.get(node, (False, ""))
        if disabled and reason == expected_reason:
            return
        if self.profile == "offline" and reason == "could not import 'torch': No module named 'torch'":
            return
        self.unexpected.append((node, reason))

    def pytest_runtest_logreport(self, report):
        self._observe(report)

    def pytest_collectreport(self, report):
        self._observe(report)

    def pytest_sessionfinish(self, session, exitstatus):
        if self.unexpected and exitstatus in (0, 1, 5):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter):
        if self.unexpected:
            terminalreporter.section("Unexpected skips: test session failed", red=True)
            for node, reason in self.unexpected:
                terminalreporter.write_line(f"{node}: {reason}", red=True)


def pytest_configure(config):
    profile = os.environ.get("EXP2CPFE_TEST_PROFILE", "offline")
    if profile not in {"offline", "cpu-training", "ml"}:
        raise pytest.UsageError("EXP2CPFE_TEST_PROFILE must be offline, cpu-training or ml")
    config.pluginmanager.register(_SkipGate(profile), "exp2cpfe-skip-gate")


@pytest.fixture
def synthetic_example_dir() -> Path:
    return Path("examples/synthetic_minimal")


@pytest.fixture
def make_sample():
    from experiment_to_cpfe.assets.models import (
        AssetKind,
        AssetRef,
        DataLayer,
        SourceKind,
    )
    from experiment_to_cpfe.schema.models import (
        CoordinateSpec,
        OrientationSpec,
        SampleMetadata,
        SamplePackage,
        SourceRef,
    )

    def factory() -> SamplePackage:
        metadata = SampleMetadata(
            sample_id="synthetic-001",
            experiment_id="demo-exp",
            microstructure_id="micro-001",
            load_path_id="uniaxial-z",
            schema_version="0.1",
            coordinate=CoordinateSpec(
                name="sample",
                axes=("x", "y", "z"),
                units="m",
            ),
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
        asset = AssetRef(
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
        )
        return SamplePackage(
            metadata=metadata,
            tables={
                "measured_observations": [
                    {"increment_id": "i0", "stress": 0.0}
                ],
                "simulation_records": [
                    {"increment_id": "i0", "stress": 0.0}
                ],
            },
            arrays={"demo": np.array([1.0, 2.0], dtype=np.float64)},
            assets=(asset,),
        )

    return factory


@pytest.fixture
def validation_policy():
    from experiment_to_cpfe.schema.validation import ValidationPolicy

    return ValidationPolicy(
        quaternion_tolerance=1.0e-6,
        require_finite=True,
        missing_units_severity="error",
        required_tables_by_profile={},
        required_assets_by_solver={"abaqus_cpfe": ("mesh", "orientation_map")},
    )


@pytest.fixture
def multimodal_sample_config(tmp_path):
    import yaml

    experiment = tmp_path / "experiment.csv"
    experiment.write_text(
        "increment,time,stress,strain\ni0,0,0,0\ni1,1,1000,0.001\n",
        encoding="utf-8",
    )
    orientations = tmp_path / "orientations.csv"
    orientations.write_text(
        "grain,phase,q0,q1,q2,q3\n1,1,1,0,0,0\n2,1,1,0,0,0\n",
        encoding="utf-8",
    )
    dic = tmp_path / "dic.csv"
    dic.write_text(
        "x,y,u,v\n0,0,0,0\n1,0,0.1,0\n0,1,0,0.1\n1,1,0.1,0.1\n",
        encoding="utf-8",
    )
    voxel = tmp_path / "voxel.npy"
    np.save(voxel, np.arange(8, dtype=np.uint8).reshape(2, 2, 2))
    mesh = tmp_path / "mesh.inp"
    mesh.write_text(
        "*NODE\n1,0,0,0\n2,1,0,0\n3,1,1,0\n4,0,1,0\n"
        "5,0,0,1\n6,1,0,1\n7,1,1,1\n8,0,1,1\n"
        "*ELEMENT, TYPE=C3D8\n1,1,2,3,4,5,6,7,8\n*STEP\n*END STEP\n",
        encoding="utf-8",
    )
    template = tmp_path / "template.inp"
    template.write_text(
        "*HEADING\n{{HEADING}}\n{{NODES}}\n{{ELEMENTS}}\n{{MATERIALS}}\n"
        "{{BOUNDARY_CONDITIONS}}\n{{OUTPUT_REQUESTS}}\n",
        encoding="utf-8",
    )
    replacements = {
        "HEADING": "Synthetic multimodal model",
        "NODES": "*NODE\n1,0,0,0\n2,1,0,0\n3,1,1,0\n4,0,1,0\n5,0,0,1\n6,1,0,1\n7,1,1,1\n8,0,1,1",
        "ELEMENTS": "*ELEMENT, TYPE=C3D8, ELSET=ALL\n1,1,2,3,4,5,6,7,8",
        "MATERIALS": "*MATERIAL, NAME=SYNTHETIC\n*ELASTIC\n1.0,0.3\n*SOLID SECTION, ELSET=ALL, MATERIAL=SYNTHETIC",
        "BOUNDARY_CONDITIONS": "*BOUNDARY\n1,1,3,0\n2,2,3,0\n4,3,3,0",
        "OUTPUT_REQUESTS": "*STEP, NAME=SMOKE\n*STATIC\n0.1,1\n*BOUNDARY\n5,3,3,0.001\n6,3,3,0.001\n7,3,3,0.001\n8,3,3,0.001\n*OUTPUT, FIELD\n*ELEMENT OUTPUT\nS,LE\n*END STEP",
    }
    payload = {
        "sample": {
            "sample_id": "multimodal-001",
            "experiment_id": "exp-001",
            "microstructure_id": "micro-001",
            "load_path_id": "load-001",
            "schema_version": "0.1",
            "coordinate": {"name": "sample", "axes": ["x", "y", "z"], "units": "m"},
            "unit_system": {"length": "m", "stress": "Pa", "time": "s"},
            "tensor_order": ["11", "22", "33", "12", "13", "23"],
            "orientation": {"representation": "quaternion", "convention": "scalar_first", "angle_units": None, "crystal_symmetry": "cubic"},
        },
        "sources": [
            {
                "path": "experiment.csv", "table_name": "measured_observations",
                "source_kind": "measured", "modality": "time_series", "format": "csv",
                "delimiter": ",", "encoding": "utf-8",
                "column_map": {"increment_id": "increment", "time": "time", "stress_33": "stress", "strain_33": "strain"},
                "units": {"increment_id": "1", "time": "s", "stress_33": "Pa", "strain_33": "1"},
                "coordinate_frame": "sample", "axis_order": ["time"],
                "native_layout": "columns", "license": "synthetic",
            },
            {
                "path": "orientations.csv", "table_name": "grains",
                "source_kind": "measured", "modality": "orientation_map", "format": "csv",
                "delimiter": ",", "encoding": "utf-8",
                "column_map": {"grain_id": "grain", "phase_id": "phase", "q0": "q0", "q1": "q1", "q2": "q2", "q3": "q3"},
                "units": {"grain_id": "1", "phase_id": "1", "q0": "1", "q1": "1", "q2": "1", "q3": "1"},
                "coordinate_frame": "sample", "axis_order": ["grain"],
                "native_layout": "columns", "license": "synthetic",
            },
        ],
        "assets": [
            {
                "asset_id": "dic-points", "path": "dic.csv", "parent_asset_id": None,
                "source_kind": "measured", "layer": "raw", "modality": "point_field", "format": "csv",
                "units": {"x": "m", "y": "m", "u": "m", "v": "m"},
                "coordinate_frame": "sample", "axis_order": ["point", "component"],
                "native_layout": "point_records", "license": "synthetic", "lossy_transformations": [],
                "adapter_config": {"format": "csv", "delimiter": ",", "coordinate_columns": ["x", "y"], "field_columns": ["u", "v"], "units": {"x": "m", "y": "m", "u": "m", "v": "m"}, "coordinate_frame": "sample", "axis_order": ["point", "component"]},
            },
            {
                "asset_id": "ct-voxels", "path": "voxel.npy", "parent_asset_id": None,
                "source_kind": "measured", "layer": "raw", "modality": "voxel_grid", "format": "npy",
                "units": {"spacing": "m"}, "coordinate_frame": "sample", "axis_order": ["z", "y", "x"],
                "native_layout": "numpy_c_order", "license": "synthetic", "lossy_transformations": [],
                "adapter_config": {"format": "npy", "origin": [0, 0, 0], "spacing": [1, 1, 1], "axis_order": ["z", "y", "x"], "units": "m", "coordinate_frame": "sample"},
            },
            {
                "asset_id": "mesh-raw", "path": "mesh.inp", "parent_asset_id": None,
                "source_kind": "input", "layer": "raw", "modality": "mesh", "format": "inp",
                "units": {"length": "m"}, "coordinate_frame": "sample", "axis_order": ["record"],
                "native_layout": "abaqus_keywords", "license": "synthetic", "lossy_transformations": [], "adapter_config": {},
            },
            {
                "asset_id": "mesh-input", "path": "mesh.inp", "parent_asset_id": "mesh-raw",
                "source_kind": "input", "layer": "solver_input", "modality": "mesh", "format": "inp",
                "units": {"length": "m"}, "coordinate_frame": "sample", "axis_order": ["record"],
                "native_layout": "abaqus_keywords", "license": "synthetic", "lossy_transformations": ["assigned solver sets"], "adapter_config": {},
            },
        ],
        "solver_inputs": {
            "microstructure_mapping": {"1": [1]}, "material_model": "isotropic_elastic",
            "material_parameters": {"E": 1.0, "nu": 0.3}, "orientation_required": False,
            "boundary_conditions": [
                {"target": "1", "first_dof": 1, "last_dof": 3, "value": 0.0},
                {"target": "2", "first_dof": 2, "last_dof": 3, "value": 0.0},
                {"target": "4", "first_dof": 3, "last_dof": 3, "value": 0.0},
                *[{"target": str(node), "first_dof": 3, "last_dof": 3, "value": 0.001} for node in (5, 6, 7, 8)],
            ],
            "load_steps": [{"name": "SMOKE", "procedure": "static", "initial_increment": 0.1, "time_period": 1.0}],
            "output_variables": ["S", "LE"], "inp_replacements": replacements,
        },
        "abaqus": {"command": ["abaqus"], "job_name": "synthetic", "template_path": "template.inp"},
        "export": {"formats": ["hdf5", "npz"]},
    }
    config = tmp_path / "sample.yaml"
    config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return config
