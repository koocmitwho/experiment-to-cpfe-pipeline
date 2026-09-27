"""Configuration models and safe YAML loading."""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from experiment_to_cpfe.assets.models import AssetKind, DataLayer, SourceKind
from experiment_to_cpfe.errors import ConfigurationError
from experiment_to_cpfe.schema.models import CoordinateSpec, OrientationSpec, OrientationNotApplicable
from experiment_to_cpfe.adapters.table_blocks import TableBlock, UnitConversion
from experiment_to_cpfe.adapters.native_models import NativeImportConfig


NonEmptyStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class SampleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_id: NonEmptyStr
    experiment_id: NonEmptyStr
    microstructure_id: NonEmptyStr
    load_path_id: NonEmptyStr
    schema_version: NonEmptyStr
    coordinate: CoordinateSpec
    unit_system: dict[NonEmptyStr, NonEmptyStr]
    tensor_order: tuple[NonEmptyStr, ...] = Field(min_length=1)
    orientation: OrientationSpec | OrientationNotApplicable


class TabularSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    table_name: Literal[
        "grains",
        "grain_boundaries",
        "mesh_nodes",
        "mesh_elements",
        "load_history",
        "measured_observations",
        "simulation_records",
    ]
    source_kind: SourceKind
    modality: AssetKind
    format: Literal["csv", "txt", "json", "xlsx"]
    delimiter: str | None
    encoding: NonEmptyStr
    column_map: dict[NonEmptyStr, NonEmptyStr] = Field(min_length=1)
    units: dict[NonEmptyStr, NonEmptyStr] = Field(min_length=1)
    coordinate_frame: NonEmptyStr | None
    axis_order: tuple[NonEmptyStr, ...]
    native_layout: NonEmptyStr
    license: NonEmptyStr | None
    block: TableBlock | None = None
    conversions: dict[NonEmptyStr, UnitConversion] = Field(default_factory=dict)


class ExternalAssetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: NonEmptyStr
    path: Path
    parent_asset_id: NonEmptyStr | None
    source_kind: SourceKind
    layer: DataLayer
    modality: AssetKind
    format: NonEmptyStr
    units: dict[NonEmptyStr, NonEmptyStr]
    coordinate_frame: NonEmptyStr | None
    axis_order: tuple[NonEmptyStr, ...]
    native_layout: NonEmptyStr
    license: NonEmptyStr | None
    lossy_transformations: tuple[NonEmptyStr, ...]
    adapter_config: dict[str, object]


class InputBundleConfig(BaseModel):
    """Native Abaqus input tree with an explicit source root and submission cwd."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_root: Path
    entrypoint: Path
    submission_dir: Path
    auxiliary_files: tuple[Path, ...] = ()
    license: NonEmptyStr
    max_files: int = Field(default=4096, ge=1)
    max_total_bytes: int = Field(default=32 * 1024 * 1024, ge=1)


class AbaqusConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command: tuple[NonEmptyStr, ...] = Field(min_length=1)
    job_name: NonEmptyStr
    template_path: Path | None = None
    ascii_temp_root: Path | None = None
    user_subroutine: Path | None = None
    cpus: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=3600, ge=1)
    version_probe_args: tuple[NonEmptyStr, ...] = ()
    required_fields: tuple[NonEmptyStr, ...] = ("S", "LE", "PEEQ", "SDV")
    extraction_position: Literal["integration_point", "nodal", "element_nodal", "element_face", "centroid", "native"] = "integration_point"
    extraction_max_records: int = Field(default=1000000, ge=1)
    field_units: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    input_bundle: InputBundleConfig | None = None


class ExportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    formats: tuple[Literal["hdf5", "npz", "pyg"], ...] = Field(min_length=1)


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample: SampleConfig
    sources: tuple[TabularSourceConfig, ...]
    assets: tuple[ExternalAssetConfig, ...] = ()
    imports: tuple[NativeImportConfig, ...] = ()
    solver_inputs: dict[str, object] = {}
    abaqus: AbaqusConfig
    export: ExportConfig
    config_path: Path | None = Field(default=None, exclude=True)


def _resolve_optional_path(value: Path | None, base_dir: Path) -> Path | None:
    if value is None or value.is_absolute():
        return value
    return (base_dir / value).resolve()


def _resolve_input_bundle(value: InputBundleConfig | None, base_dir: Path) -> InputBundleConfig | None:
    if value is None:
        return None
    root = value.source_root if value.source_root.is_absolute() else (base_dir / value.source_root).resolve()
    def under_root(path: Path) -> Path:
        return path if path.is_absolute() else (root / path).absolute()
    return value.model_copy(update={
        "source_root": root,
        "entrypoint": under_root(value.entrypoint),
        "submission_dir": under_root(value.submission_dir),
        "auxiliary_files": tuple(under_root(path) for path in value.auxiliary_files),
    })


def load_pipeline_config(path: Path) -> PipelineConfig:
    """Load YAML safely and resolve file paths against the YAML directory."""

    path = Path(path).resolve()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        config = PipelineConfig.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError, TypeError) as exc:
        raise ConfigurationError(f"invalid configuration {path}: {exc}") from exc

    base_dir = path.parent
    sources = tuple(
        source.model_copy(
            update={
                "path": (
                    source.path
                    if source.path.is_absolute()
                    else (base_dir / source.path).resolve()
                )
            }
        )
        for source in config.sources
    )
    assets = tuple(
        asset.model_copy(
            update={
                "path": (
                    asset.path
                    if asset.path.is_absolute()
                    else (base_dir / asset.path).resolve()
                )
            }
        )
        for asset in config.assets
    )
    abaqus = config.abaqus.model_copy(
        update={
            "template_path": _resolve_optional_path(
                config.abaqus.template_path,
                base_dir,
            ),
            "ascii_temp_root": _resolve_optional_path(
                config.abaqus.ascii_temp_root,
                base_dir,
            ),
            "user_subroutine": _resolve_optional_path(
                config.abaqus.user_subroutine,
                base_dir,
            ),
            "input_bundle": _resolve_input_bundle(config.abaqus.input_bundle, base_dir),
        }
    )
    return config.model_copy(
        update={
            "sources": sources,
            "assets": assets,
            "imports": tuple(item.model_copy(update={"files": {
                key: source.model_copy(update={"path": source.path if source.path.is_absolute()
                                              else (base_dir / source.path).resolve()})
                for key, source in item.files.items()}}) for item in config.imports),
            "abaqus": abaqus,
            "config_path": path,
        }
    )
