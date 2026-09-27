"""Host-side bridge for Abaqus ODB extraction bundles."""

import csv
from dataclasses import dataclass
import json
import hashlib
import io
import re
from pathlib import Path

from experiment_to_cpfe.assets.models import (
    AssetKind,
    AssetRef,
    ConversionRecord,
    DataLayer,
    SourceKind,
)
from experiment_to_cpfe.schema.models import SampleMetadata, SamplePackage, SourceRef
from experiment_to_cpfe import _resources
from experiment_to_cpfe._resources.field_contract import FIELD_CONTRACT_VERSION, parse_record
from experiment_to_cpfe.provenance.hashing import sha256_file
from experiment_to_cpfe.schema.validation import _unit_is_declared


@dataclass(frozen=True)
class ExtractionRequest:
    odb_path: Path
    output_dir: Path
    fields: tuple[str, ...]
    position: str
    max_records: int = 1000000


def build_abaqus_extraction_command(
    request: ExtractionRequest,
    abaqus_command: tuple[str, ...],
) -> tuple[str, ...]:
    script = Path(_resources.__file__).resolve().with_name("abaqus_extract_odb.py")
    return (
        *abaqus_command,
        "python",
        str(script),
        "--odb",
        str(Path(request.odb_path)),
        "--output-dir",
        str(Path(request.output_dir)),
        "--fields",
        ",".join(request.fields),
        "--position",
        request.position,
        "--max-records",
        str(request.max_records),
    )


def extraction_bundle_is_complete(path: Path) -> tuple[bool, tuple[str, ...]]:
    path = Path(path)
    required = ("metadata.json", "frames.csv")
    missing = tuple(name for name in required if not (path / name).is_file())
    return not missing, missing


def load_extraction_bundle(path: Path) -> SamplePackage:
    """Load field records with source binding and explicit field units.

    Version 0.1 bundles predate the field-contract version and contain
    step-relative ``frame_time``. Current bundles declare their contract;
    ``frame_value`` retains its frame domain and TIME records carry
    ``frame_time`` separately.
    """
    path = Path(path)
    complete, missing = extraction_bundle_is_complete(path)
    if not complete:
        raise ValueError(f"incomplete extraction bundle: {', '.join(missing)}")
    metadata_bytes = (path / "metadata.json").read_bytes()
    frames_bytes = (path / "frames.csv").read_bytes()
    metadata_payload = json.loads(metadata_bytes.decode("utf-8"))
    if not isinstance(metadata_payload, dict):
        raise ValueError("extraction metadata must be an object")
    for name in ("odb_sha256", "odb_path", "sample_metadata"):
        if name not in metadata_payload:
            raise ValueError(f"missing extraction metadata field: {name}")
    odb_hash = metadata_payload["odb_sha256"]
    odb_path = metadata_payload["odb_path"]
    if not isinstance(odb_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", odb_hash):
        raise ValueError("odb_sha256 must be a SHA-256 hexadecimal digest")
    if not isinstance(odb_path, str) or not odb_path.strip():
        raise ValueError("odb_path must be a nonempty path string")
    if not isinstance(metadata_payload["sample_metadata"], dict):
        raise ValueError("sample_metadata must be an object")
    legacy = metadata_payload.get("extraction_version") == "0.1"
    contract = metadata_payload.get("field_contract_version")
    if contract != FIELD_CONTRACT_VERSION and not (legacy and contract is None):
        raise ValueError("unsupported field contract version")
    with io.StringIO(frames_bytes.decode("utf-8"), newline="") as stream:
        records = [parse_record(row) for row in csv.DictReader(stream)]
    declared_units = metadata_payload.get("field_units", {})
    if not isinstance(declared_units, dict):
        raise ValueError("field units must be an explicit name-to-unit mapping")
    used_units = {}
    for row in records:
        if legacy:
            row.setdefault("domain", "TIME")
        name = row.get("field")
        unit = declared_units.get(name)
        if not _unit_is_declared(unit):
            raise ValueError(f"missing or unresolved field unit: {name}")
        if row.get("unit") not in (None, "", unit):
            raise ValueError(f"CSV field unit contradicts declared unit: {name}")
        row["unit"] = unit
        used_units[name] = unit
    local_odb = Path(odb_path)
    if not local_odb.is_absolute():
        local_odb = path / local_odb
    source_verified = local_odb.is_file()
    if source_verified and sha256_file(local_odb).lower() != odb_hash.lower():
        raise ValueError("available source ODB hash does not match extraction metadata")
    file_hashes = {"metadata.json": hashlib.sha256(metadata_bytes).hexdigest(),
                   "frames.csv": hashlib.sha256(frames_bytes).hexdigest()}
    # Bundle identity is SHA-256 of this canonical filename->file-hash JSON map.
    bundle_hash = hashlib.sha256(json.dumps(file_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    source = SourceRef(
        kind=SourceKind.SIMULATED,
        uri=odb_path,
        sha256=odb_hash,
        role="abaqus_odb",
    )
    sample_metadata_payload = dict(metadata_payload["sample_metadata"])
    sample_metadata_payload["sources"] = [source.model_dump(mode="json")]
    metadata = SampleMetadata.model_validate(sample_metadata_payload)
    parent = AssetRef(
        asset_id=f"asset-odb-{odb_hash}", parent_asset_id=None,
        modality=AssetKind.FIELD_SEQUENCE, format="odb", uri=odb_path,
        source_kind=SourceKind.SIMULATED, layer=DataLayer.SOLVER_OUTPUT,
        units={}, coordinate_frame=None, axis_order=(), dtype=None, shape=(),
        native_layout="abaqus_odb_native", sha256=odb_hash,
        license=metadata_payload.get("license"), lossy_transformations=(),
    )
    asset = AssetRef(
        asset_id=f"asset-extracted-{bundle_hash}",
        parent_asset_id=parent.asset_id,
        modality=AssetKind.FIELD_SEQUENCE,
        format="odb-extraction-bundle",
        uri=str(path),
        source_kind=SourceKind.SIMULATED,
        layer=DataLayer.SOLVER_OUTPUT,
        units=used_units,
        coordinate_frame=metadata.coordinate.name,
        axis_order=("frame", "location", "component"),
        dtype="mixed",
        shape=(len(records),),
        native_layout=f"abaqus_odb_csv_bundle_v{metadata_payload.get('extraction_version', 'unknown')}",
        sha256=bundle_hash,
        license=metadata_payload.get("license"),
        lossy_transformations=("Only requested stored fields/positions retained; other ODB contents omitted", "ODB field components flattened to records"),
        conversion=ConversionRecord(original_format="odb", target_format="odb-extraction-bundle",
                                    source_sha256=odb_hash, target_file_hashes=file_hashes,
                                    source_hash_verified=source_verified),
        descriptive_metadata={"table_name": "simulation_records",
                              "value_units_by": "field",
                              "field_contract_version": contract or "legacy-0.1"},
    )
    for row in records:
        row["source_asset_id"] = asset.asset_id
        row["source_kind"] = SourceKind.SIMULATED.value
    return SamplePackage(
        metadata=metadata,
        tables={"simulation_records": records},
        arrays={},
        assets=(asset, parent),
        solver_inputs={"extraction": metadata_payload},
    )
