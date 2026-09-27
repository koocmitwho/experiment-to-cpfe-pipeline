"""Modality-neutral asset metadata models."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonEmptyStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class AssetKind(str, Enum):
    """Physical or logical modality represented by an asset."""

    TABLE = "table"
    TIME_SERIES = "time_series"
    ORIENTATION_MAP = "orientation_map"
    IMAGE = "image"
    VOXEL_GRID = "voxel_grid"
    POINT_FIELD = "point_field"
    MESH = "mesh"
    GRAIN_GRAPH = "grain_graph"
    FIELD_SEQUENCE = "field_sequence"


class DataLayer(str, Enum):
    """Provenance layer occupied by an asset."""

    RAW = "raw"
    CURATED = "curated"
    SOLVER_INPUT = "solver_input"
    SOLVER_OUTPUT = "solver_output"
    DERIVED_ML = "derived_ml"


class SourceKind(str, Enum):
    """Evidence class for a value or asset."""

    MEASURED = "measured"
    INFERRED = "inferred"
    INPUT = "input"
    SIMULATED = "simulated"


class ConversionRecord(BaseModel):
    """Content-level provenance for a derived asset, without inferred license."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    original_format: NonEmptyStr
    target_format: NonEmptyStr
    source_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    target_file_hashes: dict[NonEmptyStr, Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]] = Field(default_factory=dict)
    hash_scope: Literal["files", "logical_payload"] = "files"
    target_payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    source_hash_verified: bool = Field(default=False, description="Recorded digest matches the local source file")

    @model_validator(mode="after")
    def require_target_digest(self) -> "ConversionRecord":
        if self.hash_scope == "files" and (not self.target_file_hashes or self.target_payload_sha256 is not None):
            raise ValueError("file conversion requires target_file_hashes without a logical payload digest")
        if self.hash_scope == "logical_payload" and (self.target_payload_sha256 is None or self.target_file_hashes):
            raise ValueError("logical payload conversion requires only target_payload_sha256")
        return self


class AssetRef(BaseModel):
    """Immutable reference to one native or derived data asset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: NonEmptyStr
    parent_asset_id: NonEmptyStr | None
    modality: AssetKind
    format: NonEmptyStr
    uri: NonEmptyStr
    source_kind: SourceKind
    layer: DataLayer
    units: dict[NonEmptyStr, NonEmptyStr]
    coordinate_frame: NonEmptyStr | None
    axis_order: tuple[NonEmptyStr, ...]
    dtype: NonEmptyStr | None
    shape: tuple[int, ...]
    native_layout: NonEmptyStr
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    license: NonEmptyStr | None
    lossy_transformations: tuple[NonEmptyStr, ...]
    conversion: ConversionRecord | None = None
    descriptive_metadata: dict[str, object] = Field(default_factory=dict)


class AssetManifest(BaseModel):
    """Validated collection of assets and their immediate provenance links."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assets: tuple[AssetRef, ...]

    @model_validator(mode="after")
    def validate_asset_ids_and_parents(self) -> "AssetManifest":
        asset_ids = [asset.asset_id for asset in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("duplicate asset_id in asset manifest")

        known_ids = set(asset_ids)
        by_id = {asset.asset_id: asset for asset in self.assets}
        for asset in self.assets:
            dependencies = asset.descriptive_metadata.get("dependency_hashes", {})
            if not isinstance(dependencies, dict):
                raise ValueError("asset dependency_hashes must be a mapping")
            for dependency_id, digest in dependencies.items():
                dependency = by_id.get(dependency_id)
                if dependency is None or dependency.sha256 != digest:
                    raise ValueError("asset dependency hash differs from referenced asset")
            if (
                asset.parent_asset_id is not None
                and asset.parent_asset_id not in known_ids
            ):
                raise ValueError(
                    f"parent_asset_id {asset.parent_asset_id!r} is not in manifest"
                )
            if asset.conversion is not None:
                parent = by_id.get(asset.parent_asset_id)
                if parent is None:
                    raise ValueError("conversion requires a parent asset")
                if parent.sha256 is None or parent.sha256.lower() != asset.conversion.source_sha256.lower():
                    raise ValueError("conversion source hash differs from parent asset")
                if parent.format != asset.conversion.original_format or asset.format != asset.conversion.target_format:
                    raise ValueError("conversion formats differ from asset formats")
                if asset.conversion.hash_scope == "logical_payload" and asset.sha256 != asset.conversion.target_payload_sha256:
                    raise ValueError("logical payload hash differs from converted asset hash")
        finished: set[str] = set()
        for asset_id in asset_ids:
            visiting: set[str] = set()
            current: str | None = asset_id
            while current is not None and current not in finished:
                if current in visiting:
                    raise ValueError("parent_asset_id cycle in asset manifest")
                visiting.add(current)
                current = by_id[current].parent_asset_id
            finished.update(visiting)
        return self

    def get(self, asset_id: str) -> AssetRef:
        """Return an asset by stable ID, or raise ``KeyError``."""

        for asset in self.assets:
            if asset.asset_id == asset_id:
                return asset
        raise KeyError(asset_id)


class ModalitySpec(BaseModel):
    """Explicit field contract for one supported modality and format."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: AssetKind
    format: NonEmptyStr
    required_fields: tuple[NonEmptyStr, ...]
    optional_fields: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def validate_field_sets(self) -> "ModalitySpec":
        required = set(self.required_fields)
        optional = set(self.optional_fields)
        if len(required) != len(self.required_fields):
            raise ValueError("required_fields contains duplicates")
        if len(optional) != len(self.optional_fields):
            raise ValueError("optional_fields contains duplicates")
        if required & optional:
            raise ValueError("optional_fields overlap required_fields")
        return self
