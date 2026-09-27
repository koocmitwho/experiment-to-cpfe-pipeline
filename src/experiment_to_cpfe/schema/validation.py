"""Pure validation and solver-readiness gates."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
from numbers import Real
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

from experiment_to_cpfe.assets.models import AssetKind, AssetManifest
from experiment_to_cpfe._resources.field_contract import record_identity
from experiment_to_cpfe.schema.models import SamplePackage


Severity = Literal["error", "warning", "info"]


def _unit_is_declared(value: object) -> bool:
    unresolved = {"", "unknown", "unspecified", "native", "native units", "tbd", "?", "none", "null", "n/a"}
    return isinstance(value, str) and value.strip().lower() not in unresolved


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: Severity
    message: str
    location: str


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "message": issue.message,
                    "location": issue.location,
                }
                for issue in self.issues
            ],
        }


class ValidationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    quaternion_tolerance: float = Field(default=1.0e-6, gt=0)
    require_finite: bool = True
    missing_units_severity: Severity = "error"
    required_tables_by_profile: dict[str, tuple[str, ...]] = {}
    required_assets_by_solver: dict[str, tuple[str, ...]] = {}


@dataclass(frozen=True)
class SolverReadinessReport:
    missing: tuple[str, ...]
    warnings: tuple[str, ...]
    ready: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "missing": list(self.missing),
            "warnings": list(self.warnings),
        }


def load_validation_policy(path: Path) -> ValidationPolicy:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ValidationPolicy.model_validate(payload)


def _issue(
    code: str,
    message: str,
    location: str,
    severity: Severity = "error",
) -> ValidationIssue:
    return ValidationIssue(code, severity, message, location)


def validate_asset_links(
    sample: SamplePackage,
    policy: ValidationPolicy,
) -> tuple[ValidationIssue, ...]:
    del policy
    issues: list[ValidationIssue] = []
    try:
        AssetManifest(assets=sample.assets)
    except ValueError as exc:
        issues.append(_issue("INVALID_ASSET_LINK", str(exc), "assets"))

    sample_frame = sample.metadata.coordinate.name
    for asset in sample.assets:
        if (
            asset.coordinate_frame
            and asset.coordinate_frame != sample_frame
        ):
            issues.append(
                _issue(
                    "REGISTRATION_REQUIRED",
                    f"asset frame {asset.coordinate_frame!r} is not registered "
                    f"to sample frame {sample_frame!r}",
                    f"assets.{asset.asset_id}.coordinate_frame",
                )
            )
    return tuple(issues)


def validate_sample(
    sample: SamplePackage,
    policy: ValidationPolicy,
) -> ValidationReport:
    issues: list[ValidationIssue] = list(validate_asset_links(sample, policy))
    if not sample.metadata.unit_system:
        issues.append(
            _issue(
                "MISSING_UNIT",
                "sample unit_system is empty",
                "metadata.unit_system",
                policy.missing_units_severity,
            )
        )

    for quantity, unit in sample.metadata.unit_system.items():
        if not _unit_is_declared(unit):
            issues.append(_issue(
                "MISSING_UNIT", f"unit for {quantity} is unresolved",
                f"metadata.unit_system.{quantity}", policy.missing_units_severity,
            ))

    assets_by_id = {asset.asset_id: asset for asset in sample.assets}
    bound_tables = {asset.descriptive_metadata.get("table_name") for asset in sample.assets
                    if isinstance(asset.descriptive_metadata.get("table_name"), str)}
    for table_name, rows in sample.tables.items():
        for index, row in enumerate(rows):
            location = f"tables.{table_name}[{index}]"
            if table_name not in bound_tables and "source_asset_id" not in row and "source_kind" not in row:
                continue
            source_id = row.get("source_asset_id")
            source = assets_by_id.get(source_id) if isinstance(source_id, str) else None
            if source is None:
                issues.append(_issue("INVALID_ROW_SOURCE", "row source_asset_id is missing or unregistered", location))
                continue
            if row.get("source_kind") != source.source_kind.value:
                issues.append(_issue("CONTRADICTORY_EVIDENCE", "row source_kind differs from its source asset", location))
            if table_name == "simulation_records" and source.source_kind.value != "simulated":
                issues.append(_issue("CONTRADICTORY_EVIDENCE", "simulation_records requires simulated source evidence", location))
            if table_name == "measured_observations" and source.source_kind.value == "simulated":
                issues.append(_issue("CONTRADICTORY_EVIDENCE", "simulated evidence cannot enter measured_observations", location))
            if source.descriptive_metadata.get("table_name") != table_name:
                issues.append(_issue("INVALID_ROW_SOURCE", "row table differs from its source table declaration", location))
            if source.format == "odb-extraction-bundle":
                for column in ("step", "frame", "increment_id", "field", "component", "value"):
                    if column not in row:
                        issues.append(_issue("MISSING_COLUMN", f"field record requires {column!r}", location))
                value = row.get("value")
                if not isinstance(value, Real) or isinstance(value, bool):
                    issues.append(_issue("INVALID_FIELD_VALUE", "field value must be real numeric data", location + ".value"))
                field_name = row.get("field")
                unit = source.units.get(field_name) if isinstance(field_name, str) else None
                if not _unit_is_declared(unit):
                    issues.append(_issue("MISSING_UNIT", f"source unit for field {field_name!r} is unresolved",
                                         location, policy.missing_units_severity))
                elif row.get("unit") != unit:
                    issues.append(_issue("CONTRADICTORY_EVIDENCE", "field unit differs from its source asset", location))
                continue
            columns = source.descriptive_metadata.get("column_map")
            if not isinstance(columns, dict) or not columns:
                issues.append(_issue("INVALID_ROW_SOURCE", "bound tabular source requires an explicit column mapping", location))
                continue
            for column in columns:
                if column not in row:
                    issues.append(_issue("MISSING_COLUMN", f"mapped column {column!r} is missing", location))
                if not _unit_is_declared(source.units.get(column)):
                    issues.append(_issue("MISSING_UNIT", f"source unit for mapped column {column!r} is unresolved", location,
                                         policy.missing_units_severity))

    if policy.require_finite:
        for name, array in sample.arrays.items():
            if np.issubdtype(array.dtype, np.number) and not np.isfinite(array).all():
                issues.append(
                    _issue(
                        "NONFINITE_VALUE",
                        f"array {name!r} contains NaN or infinity",
                        f"arrays.{name}",
                    )
                )
        for table_name, rows in sample.tables.items():
            for index, row in enumerate(rows):
                for column, value in row.items():
                    if isinstance(value, Real) and not math.isfinite(value):
                        issues.append(_issue(
                            "NONFINITE_VALUE", "table contains NaN or infinity",
                            f"tables.{table_name}[{index}].{column}",
                        ))

    grains = sample.tables.get("grains", [])
    grain_ids = {row.get("grain_id") for row in grains if "grain_id" in row}
    if len(grain_ids) != len([row for row in grains if "grain_id" in row]):
        issues.append(
            _issue("DUPLICATE_GRAIN_ID", "grain IDs must be unique", "tables.grains")
        )
    for index, row in enumerate(sample.tables.get("mesh_elements", [])):
        if "grain_id" in row and row["grain_id"] not in grain_ids:
            issues.append(
                _issue(
                    "UNKNOWN_GRAIN_ID",
                    f"element references unknown grain {row['grain_id']!r}",
                    f"tables.mesh_elements[{index}].grain_id",
                )
            )

    for index, row in enumerate(grains):
        quaternion_keys = ("q0", "q1", "q2", "q3")
        if all(key in row for key in quaternion_keys):
            try:
                norm = math.hypot(*(float(row[key]) for key in quaternion_keys))
            except (ValueError, TypeError):
                norm = math.nan
            if not math.isfinite(norm) or abs(norm - 1.0) > policy.quaternion_tolerance:
                issues.append(
                    _issue(
                        "INVALID_QUATERNION",
                        f"quaternion norm is {norm}",
                        f"tables.grains[{index}]",
                    )
                )

    for table_name in ("load_history", "measured_observations", "simulation_records"):
        rows = sample.tables.get(table_name, [])
        clocks: dict[tuple[object, ...], float] = {}
        for index, row in enumerate(rows):
            time = row.get("time")
            if time is not None:
                if not isinstance(time, Real) or isinstance(time, bool) or not math.isfinite(time):
                    issues.append(_issue("INVALID_TIME", "time must be finite numeric data", f"tables.{table_name}[{index}].time"))
                    continue
                clock_key = tuple(row.get(key) for key in ("step", "load_case", "load_path_id", "asset_id", "source_asset_id"))
                previous = clocks.get(clock_key)
                if previous is not None and time < previous:
                    issues.append(_issue("NONMONOTONIC_TIME", "time decreases within a step/load path", f"tables.{table_name}[{index}].time"))
                clocks[clock_key] = float(time)
        if table_name == "simulation_records":
            field_rows = [row for row in rows if "field" in row]
            locations = [(row.get("source_asset_id"), record_identity(row)) for row in field_rows]
            if len(locations) != len(set(locations)):
                issues.append(_issue("DUPLICATE_FIELD_RECORD", "duplicate field location/component", "tables.simulation_records"))
            issues.extend(_validate_field_frames(rows))
            rows = [row for row in rows if "field" not in row]
        increments = [(row.get("source_asset_id"), row.get("step"), row.get("load_case"), row.get("increment_id")) for row in rows if "increment_id" in row]
        if len(increments) != len(set(increments)):
            issues.append(
                _issue(
                    "DUPLICATE_INCREMENT",
                    f"{table_name} contains duplicate increment IDs",
                    f"tables.{table_name}",
                )
            )
    return ValidationReport(tuple(issues))


def _validate_field_frames(rows: list[dict[str, object]]) -> list[ValidationIssue]:
    """Check frame clocks and increment-to-frame identity for field records.

    ``frame_time`` is step-relative and meaningful only in the TIME domain.
    ``frame_value`` retains the frame's domain (e.g. frequency or mode), and
    ordinary ``time`` is checked independently by ``validate_sample``. Legacy
    0.1 loading supplies the TIME domain explicitly. Clocks are grouped by
    source/step/load path and ordered by frame index, independently of CSV row
    order. All locations/components of one frame share its time. Within a
    source/step/load path, increments and frames correspond one-to-one; full field,
    location and component identity determines row uniqueness in that frame.
    """
    issues: list[ValidationIssue] = []
    increments: dict[tuple[object, ...], object] = {}
    frame_increments: dict[tuple[object, ...], object] = {}
    clocks: dict[tuple[object, ...], dict[int, tuple[float, str]]] = {}
    for index, row in enumerate(rows):
        if "field" not in row or ("frame" not in row and "frame_time" not in row):
            continue
        location = f"tables.simulation_records[{index}]"
        frame = row.get("frame")
        if not isinstance(frame, Real) or isinstance(frame, bool) or not math.isfinite(frame) or frame < 0 or int(frame) != frame:
            issues.append(_issue("INVALID_TIME", "frame index must be a nonnegative integer", location + ".frame"))
            continue
        scope = tuple(row.get(key) for key in ("source_asset_id", "asset_id", "step", "load_case", "load_path_id"))
        if "increment_id" in row:
            increment = (*scope, row["increment_id"])
            if increment in increments and increments[increment] != frame:
                issues.append(_issue("DUPLICATE_INCREMENT", "increment ID identifies multiple frames", location + ".increment_id"))
            increments[increment] = frame
            frame_key = (*scope, frame)
            if frame_key in frame_increments and frame_increments[frame_key] != row["increment_id"]:
                issues.append(_issue("INCONSISTENT_INCREMENT", "frame records have different increment IDs", location + ".increment_id"))
            frame_increments[frame_key] = row["increment_id"]
        if "frame_time" not in row and "domain" not in row:
            continue
        time = row.get("frame_time")
        if row.get("domain") != "TIME":
            if time not in (None, ""):
                issues.append(_issue("INVALID_TIME", "frame_time requires the TIME domain", location + ".frame_time"))
            continue
        if not isinstance(time, Real) or isinstance(time, bool) or not math.isfinite(time):
            issues.append(_issue("INVALID_TIME", "TIME frame_time must be finite numeric data", location + ".frame_time"))
            continue
        times = clocks.setdefault(scope, {})
        if frame in times and times[frame][0] != time:
            issues.append(_issue("INCONSISTENT_FRAME_TIME", "field records in one frame have different times", location + ".frame_time"))
        else:
            times[int(frame)] = (float(time), location + ".frame_time")
    for times in clocks.values():
        previous = None
        for frame in sorted(times):
            time, location = times[frame]
            if previous is not None and time < previous:
                issues.append(_issue("NONMONOTONIC_TIME", "frame_time decreases within a step/load path", location))
            previous = time
    return issues


def check_solver_readiness(
    sample: SamplePackage,
    solver_name: str,
    policy: ValidationPolicy | None = None,
) -> SolverReadinessReport:
    if solver_name != "abaqus_cpfe":
        return SolverReadinessReport(
            missing=(f"unsupported solver profile: {solver_name}",),
            warnings=(),
            ready=False,
        )

    replacements = sample.solver_inputs.get("inp_replacements")
    order = ("HEADING", "NODES", "ELEMENTS", "MATERIALS", "BOUNDARY_CONDITIONS", "OUTPUT_REQUESTS")
    if isinstance(replacements, dict) and all(isinstance(value, str) for value in replacements.values()):
        deck_text = "*HEADING\n" + "\n".join(replacements.get(key, "") for key in order)
    else:
        deck_text = ""
    return check_deck_readiness(sample, deck_text, policy)


def check_deck_readiness(
    sample: SamplePackage, deck_text: str, policy: ValidationPolicy | None = None,
) -> SolverReadinessReport:
    """Check normalized declarations against an expanded, actual input deck.

    Native bundle callers resolve and hash includes before supplying the text.
    The caller's policy governs data issues in this readiness report.
    """
    from experiment_to_cpfe.schema.solver_contract import solver_contract_errors

    modalities = {asset.modality for asset in sample.assets}
    inputs = sample.solver_inputs
    missing: list[str] = []
    units = sample.metadata.unit_system
    for quantity in ("length", "stress", "time"):
        value = units.get(quantity)
        if not _unit_is_declared(value):
            missing.append(f"explicit unit_system.{quantity} unit")
    supported_units = {
        "length": {"m", "cm", "mm", "um", "µm", "nm"},
        "stress": {"Pa", "kPa", "MPa", "GPa"},
        "time": {"s", "ms", "us", "min", "h"},
    }
    for quantity, symbols in supported_units.items():
        if units.get(quantity) not in symbols:
            missing.append(f"supported explicit {quantity} unit required for v1 adapter")
    if sample.metadata.tensor_order != ("11", "22", "33", "12", "13", "23"):
        missing.append("explicit Abaqus tensor mapping required for tensor_order")
    if sample.metadata.coordinate.axes != ("x", "y", "z"):
        missing.append("v1 flat solid adapter requires explicit x,y,z coordinate axes")
    length_unit = units.get("length")
    if length_unit and sample.metadata.coordinate.units != length_unit:
        missing.append("coordinate.units must match declared unit_system.length; normalize explicitly")
    if AssetKind.MESH not in modalities:
        missing.append("geometry/mesh asset")
    if not (inputs.get("microstructure_mapping") or inputs.get("material_region_mapping")):
        missing.append("microstructure-to-mesh or material-region mapping")
    if not inputs.get("material_model"):
        missing.append("material model")
    if not (
        inputs.get("material_parameters") or inputs.get("calibration_result")
    ):
        missing.append("material parameters or explicit calibration result")
    if inputs.get("orientation_required", True) and AssetKind.ORIENTATION_MAP not in modalities:
        missing.append("orientation data")
    if not inputs.get("boundary_conditions"):
        missing.append("boundary conditions")
    if not inputs.get("load_steps"):
        missing.append("loading definition")
    if not inputs.get("output_variables"):
        missing.append("output-variable contract")
    validation = validate_sample(sample, policy if policy is not None else ValidationPolicy())
    missing.extend(issue.message for issue in validation.errors)
    missing.extend(solver_contract_errors(sample, deck_text))
    missing_tuple = tuple(f"MISSING_SOLVER_INPUT: {item}" for item in missing)
    return SolverReadinessReport(
        missing=missing_tuple,
        warnings=tuple(f"{issue.code}: {issue.message}" for issue in validation.warnings),
        ready=not missing_tuple,
    )


def write_validation_report(
    report: ValidationReport,
    json_path: Path,
    markdown_path: Path,
) -> None:
    json_path = Path(json_path)
    markdown_path = Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = ["# Validation Report", "", f"Passed: `{report.passed}`", ""]
    for issue in report.issues:
        lines.append(
            f"- **{issue.severity.upper()} {issue.code}** "
            f"at `{issue.location}`: {issue.message}"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
