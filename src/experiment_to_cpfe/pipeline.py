"""Callable orchestration for each pipeline stage."""

import json
import os
from pathlib import Path
import shlex
import subprocess
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from dataclasses import replace
import shutil
import tempfile
from experiment_to_cpfe.errors import PipelineError

from experiment_to_cpfe.adapters.tabular import assemble_sample
from experiment_to_cpfe.config import load_pipeline_config
from experiment_to_cpfe.datasets.hdf5 import write_hdf5
from experiment_to_cpfe.datasets.package import write_npz, write_pyg
from experiment_to_cpfe.provenance.hashing import sha256_file
from experiment_to_cpfe.provenance.binding import (
    binding_issues, capture_inputs, changed_inputs, verify_recorded_file,
)
from experiment_to_cpfe.provenance.manifest import build_run_manifest, write_manifest
from experiment_to_cpfe.provenance.solver_fingerprint import capture_solver_fingerprint
from experiment_to_cpfe.schema.io import dump_sample_json, load_sample_json
from experiment_to_cpfe.schema.models import SamplePackage
from experiment_to_cpfe.schema.validation import (
    check_solver_readiness,
    check_deck_readiness,
    load_validation_policy,
    validate_sample,
    write_validation_report,
    ValidationIssue, ValidationReport,
)
from experiment_to_cpfe.solvers.abaqus.extraction import (
    ExtractionRequest,
    build_abaqus_extraction_command,
    extraction_bundle_is_complete,
    load_extraction_bundle,
)
from experiment_to_cpfe.solvers.abaqus.bundle import stage_input_bundle, snapshot_input_bundle
from experiment_to_cpfe.solvers.abaqus.inp import build_solver_input
from experiment_to_cpfe.solvers.abaqus.runner import (
    AbaqusRunRequest,
    SolverStage,
    run_abaqus,
    wrap_batch_command,
    _execute_process as execute_process,
    _output_text,
)
from experiment_to_cpfe.solvers.abaqus.static_check import static_check_inp


RUN_SUBDIRECTORIES = ("input", "solver", "dataset", "reports")
_started_at = ContextVar("pipeline_stage_started_at", default=None)


def _effective_abaqus_command(config):
    override = os.environ.get("EXP2CPFE_ABAQUS_COMMAND")
    if not override:
        return config.abaqus.command
    # Windows paths use backslashes literally; quote paths containing spaces.
    parts = shlex.split(override, posix=os.name != "nt")
    if os.name == "nt":
        parts = [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
    if not parts:
        raise ValueError("Abaqus environment command is empty")
    return tuple(parts)


def _timed_stage(function):
    @wraps(function)
    def execute(*args, **kwargs):
        token = _started_at.set(datetime.now(timezone.utc).isoformat())
        try:
            return function(*args, **kwargs)
        finally:
            _started_at.reset(token)
    return execute


def _configured_solver_fingerprint(config, cwd):
    try:
        command = _effective_abaqus_command(config)
    except ValueError as exc:
        fingerprint = capture_solver_fingerprint((), cwd=cwd)
        fingerprint["resolution_error"] = f"command_parse_error: {exc}"
        return fingerprint
    return capture_solver_fingerprint(command, cwd=cwd,
                                      version_probe_args=config.abaqus.version_probe_args)


def _create_new_run(run_dir: Path) -> None:
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"run directory is non-empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in RUN_SUBDIRECTORIES:
        (run_dir / name).mkdir()


def _require_validated_run(run_dir: Path) -> None:
    required = (
        run_dir / "reports" / "validation.json",
        run_dir / "reports" / "solver_readiness.json",
        run_dir / "reports" / "qa_report.md",
        run_dir / "reports" / "run_manifest.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "run must be validated first; missing: " + ", ".join(missing)
        )


def _stage_records(run_dir: Path) -> list[dict[str, object]]:
    path = run_dir / "reports" / "run_manifest.json"
    if not path.is_file():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("stages", []))


def _record_stage(
    run_dir: Path,
    config_path: Path,
    record: dict[str, object],
) -> dict[str, object]:
    record = dict(record)
    record.setdefault("started_at", _started_at.get())
    record.setdefault("finished_at", datetime.now(timezone.utc).isoformat())
    stages = _stage_records(run_dir)
    if any(
        stage.get("stage") == record.get("stage")
        and stage.get("status") == "completed"
        for stage in stages
    ):
        raise FileExistsError(
            f"completed stage already exists: {record.get('stage')}"
        )
    manifest_path = run_dir / "reports/run_manifest.json"
    if manifest_path.is_file():
        # Never re-hash past artifacts or re-sign a changed configuration.
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts = dict(manifest["artifacts"])
        for raw_path in record.get("artifacts", []):
            path = Path(raw_path)
            if str(path) in artifacts:
                if not path.is_file() or sha256_file(path) != artifacts[str(path)]["sha256"]:
                    raise ValueError(f"recorded artifact integrity changed: {path}")
                continue
            if path.is_file():
                artifacts[str(path)] = {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}
        manifest["stages"] = [*stages, record]
        manifest["artifacts"] = artifacts
        manifest["limitations"] = [*manifest.get("limitations", []), *record.get("limitations", [])]
    else:
        manifest = build_run_manifest(run_dir, config_path, [record])
    write_manifest(manifest, run_dir / "reports" / "run_manifest.json")
    return record


def _stage_guard(config_path: Path, run_dir: Path, stage_name: str,
                 prerequisites: tuple[str, ...] = ()) -> dict | None:
    manifest = json.loads((run_dir / "reports/run_manifest.json").read_text(encoding="utf-8"))
    stages = manifest.get("stages", [])
    if any(s.get("stage") == stage_name for s in stages):
        raise FileExistsError(f"stage already recorded: {stage_name}; create a new run")
    issues = binding_issues(run_dir, config_path, manifest)
    for prerequisite in prerequisites:
        previous = next((s for s in stages if s.get("stage") == prerequisite and s.get("status") == "completed"), None)
        if previous is None:
            issues.append(f"completed prerequisite required: {prerequisite}")
        else:
            for raw_path in previous.get("artifacts", []):
                issues.extend(verify_recorded_file(Path(raw_path), manifest))
    if not issues:
        return None
    return _blocked_stage(config_path, run_dir, stage_name, issues)


def _blocked_stage(config_path: Path, run_dir: Path, stage_name: str, issues: list[str]) -> dict:
    path = run_dir / "reports" / f"{stage_name}_blocked.json"
    if path.exists():
        raise FileExistsError(path)
    record = {"stage": stage_name, "status": "blocked", "command": [],
              "artifacts": [str(path)], "limitations": issues}
    write_manifest(record, path)
    return _record_stage(run_dir, config_path, record)


def _default_policy_path() -> Path:
    return Path(__file__).resolve().parent / "_resources" / "validation_policy.yaml"


def _native_snapshot(config):
    bundle = config.abaqus.input_bundle
    auxiliary = (*bundle.auxiliary_files, *((config.abaqus.user_subroutine,) if config.abaqus.user_subroutine else ()))
    return snapshot_input_bundle(bundle.entrypoint, source_root=bundle.source_root,
        submission_dir=bundle.submission_dir, auxiliary_files=auxiliary,
        max_files=bundle.max_files, max_total_bytes=bundle.max_total_bytes)


def _readiness(sample, config, policy):
    if config.abaqus.input_bundle is not None:
        return check_deck_readiness(sample, _native_snapshot(config).expanded_text(), policy)
    return check_solver_readiness(sample, "abaqus_cpfe", policy)


@_timed_stage
def run_validate(config_path: Path, run_dir: Path) -> dict[str, object]:
    config_path = Path(config_path).resolve()
    run_dir = Path(run_dir).resolve()
    _create_new_run(run_dir)
    normalized_path = run_dir / "input" / "normalized_sample.json"
    lock_path = run_dir / "input/input_lock.json"
    try:
        config = load_pipeline_config(config_path)
        binding = capture_inputs(config, config_path, _default_policy_path())
        sample = assemble_sample(config)
        dump_sample_json(sample, normalized_path)
        if changed_inputs(binding):
            raise ValueError("input integrity changed during validation; create a new run")
        write_manifest(binding, lock_path)
        policy = load_validation_policy(_default_policy_path())
        report = validate_sample(sample, policy)
        readiness = _readiness(sample, config, policy)
    except (PipelineError, OSError, ValueError, TypeError) as exc:
        validation = run_dir / "reports/validation.json"
        qa = run_dir / "reports/qa_report.md"
        ready = run_dir / "reports/solver_readiness.json"
        write_validation_report(ValidationReport((ValidationIssue("INPUT_ERROR", "error", str(exc), "configuration/inputs"),)), validation, qa)
        write_manifest({"ready": False, "missing": [str(exc)], "warnings": []}, ready)
        return _record_stage(run_dir, config_path, {"stage": "validate", "status": "failed",
            "artifacts": [str(validation), str(qa), str(ready)], "limitations": [str(exc)]})
    validation_path = run_dir / "reports" / "validation.json"
    qa_path = run_dir / "reports" / "qa_report.md"
    write_validation_report(report, validation_path, qa_path)
    readiness_path = run_dir / "reports" / "solver_readiness.json"
    readiness_path.write_text(
        json.dumps(readiness.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    status = "completed" if report.passed and readiness.ready else "failed"
    record = {
        "stage": "validate",
        "status": status,
        "artifacts": [
            str(normalized_path),
            str(lock_path),
            str(validation_path),
            str(readiness_path),
            str(qa_path),
        ],
        "limitations": list(readiness.missing),
        "solver_fingerprint": _configured_solver_fingerprint(config, run_dir / "solver"),
    }
    return _record_stage(run_dir, config_path, record)


def _stage_native_bundle(config, run_dir: Path) -> dict[str, object]:
    """Stage or reuse a validated native INCLUDE bundle in the run input area."""
    if config.abaqus.input_bundle is None:
        raise ValueError("native input bundle is not configured")
    report_path = run_dir / "reports/native_bundle.json"
    destination = run_dir / "input/native_bundle"
    if report_path.is_file():
        destination = Path(json.loads(report_path.read_text(encoding="utf-8"))["bundle_root"])
    elif not str(destination).isascii():
        scratch = config.abaqus.ascii_temp_root
        if scratch is None or not str(scratch.resolve()).isascii():
            raise ValueError("native preparation requires ASCII run path or explicit ASCII ascii_temp_root")
        scratch.mkdir(parents=True, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix="exp2cpfe-input-",dir=scratch)) / "bundle"
    if report_path.is_file() and destination.is_dir():
        manifest = json.loads((run_dir / "reports/run_manifest.json").read_text(encoding="utf-8"))
        issues = verify_recorded_file(report_path, manifest)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for name in report.get("artifacts", []):
            issues.extend(verify_recorded_file(Path(name), manifest))
        if issues:
            raise ValueError("; ".join(issues))
        manifest_path = destination / ".pipeline-bundle-manifest.json"
        if not manifest_path.is_file():
            raise ValueError("native bundle report exists but its manifest is missing")
        return report
    bundle_config = config.abaqus.input_bundle
    lock = json.loads((run_dir / "input/input_lock.json").read_text(encoding="utf-8"))
    auxiliary = (*bundle_config.auxiliary_files, *((config.abaqus.user_subroutine,) if config.abaqus.user_subroutine else ()))
    staged = stage_input_bundle(
        bundle_config.entrypoint,
        source_root=bundle_config.source_root,
        submission_dir=bundle_config.submission_dir,
        destination=destination,
        license=bundle_config.license,
        auxiliary_files=auxiliary,
        max_files=bundle_config.max_files,
        max_total_bytes=bundle_config.max_total_bytes,
        expected_hashes=lock.get("native_bundle_files", {}),
    )
    receipt = json.loads(staged.manifest_path.read_text(encoding="utf-8"))
    staged_files = [
        asset["uri"] for asset in receipt["assets"]
        if asset["parent_asset_id"] is not None and asset["uri"] != str(staged.entrypoint)
    ]
    report = {
        "entrypoint": str(staged.entrypoint),
        "submission_dir": str(staged.submission_dir),
        "manifest": str(staged.manifest_path),
        "source_root": str(bundle_config.source_root),
        "bundle_root": str(destination),
        "assets": receipt["assets"],
        "include_edges": receipt["include_edges"],
        "artifacts": [str(staged.manifest_path), str(staged.entrypoint), *staged_files, str(report_path)],
        "input_sha256": sha256_file(staged.manifest_path),
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


@_timed_stage
def run_stage_input_bundle(config_path: Path, run_dir: Path) -> dict[str, object]:
    config_path = Path(config_path).resolve()
    run_dir = Path(run_dir).resolve()
    _require_validated_run(run_dir)
    blocked = _stage_guard(config_path, run_dir, "stage-input-bundle")
    if blocked is not None:
        return blocked
    config = load_pipeline_config(config_path)
    try:
        report = _stage_native_bundle(config, run_dir)
    except (OSError, ValueError) as exc:
        return _blocked_stage(config_path, run_dir, "stage-input-bundle", [str(exc)])
    return _record_stage(run_dir, config_path, {
        "stage": "stage-input-bundle", "status": "completed",
        "artifacts": report["artifacts"], "input_sha256": report["input_sha256"],
        "limitations": ["Native INCLUDE bundle staged byte-for-byte; readiness is checked by build-inp and run-abaqus"],
    })


@_timed_stage
def run_build_inp(config_path: Path, run_dir: Path) -> dict[str, object]:
    config_path = Path(config_path).resolve()
    run_dir = Path(run_dir).resolve()
    _require_validated_run(run_dir)
    prerequisites = ("validate",)
    if any(s.get("stage") == "stage-input-bundle" for s in _stage_records(run_dir)):
        prerequisites += ("stage-input-bundle",)
    blocked = _stage_guard(config_path, run_dir, "build-inp", prerequisites)
    if blocked is not None:
        return blocked
    config = load_pipeline_config(config_path)
    sample = load_sample_json(run_dir / "input/normalized_sample.json")
    policy = load_validation_policy(_default_policy_path())
    if config.abaqus.input_bundle is not None:
        readiness = _readiness(sample, config, policy)
        if not readiness.ready:
            return _blocked_stage(config_path, run_dir, "build-inp", list(readiness.missing))
        try:
            report = _stage_native_bundle(config, run_dir)
        except (OSError, ValueError) as exc:
            return _blocked_stage(config_path, run_dir, "build-inp", [str(exc)])
        return _record_stage(run_dir, config_path, {
            "stage": "build-inp", "status": "completed",
            "artifacts": report["artifacts"],
            "limitations": ["Native INCLUDE bundle staged byte-for-byte from the expanded input deck"],
            "input_sha256": report["input_sha256"],
            "solver_input": report["entrypoint"],
        })
    if config.abaqus.template_path is None:
        return _blocked_stage(config_path, run_dir, "build-inp", ["MISSING_SOLVER_INPUT: Abaqus template_path"])
    output = run_dir / "input" / "model.inp"
    try:
        result = build_solver_input(sample, config.abaqus.template_path, output, policy)
    except (OSError, ValueError) as exc:
        return _blocked_stage(config_path, run_dir, "build-inp", [str(exc)])
    static_report = static_check_inp(output)
    static_path = run_dir / "reports" / "inp_static_check.json"
    static_path.write_text(
        json.dumps(
            {
                "errors": list(static_report.errors),
                "warnings": list(static_report.warnings),
                "counts": static_report.counts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    record = {
        "stage": "build-inp",
        "status": "completed" if not static_report.errors else "failed",
        "artifacts": [str(result.output_path), str(static_path)],
        "limitations": list(static_report.errors),
        "input_sha256": result.sha256,
    }
    return _record_stage(run_dir, config_path, record)


@_timed_stage
def run_abaqus_stage(
    config_path: Path,
    run_dir: Path,
    stage: str,
) -> dict[str, object]:
    config_path = Path(config_path).resolve()
    run_dir = Path(run_dir).resolve()
    _require_validated_run(run_dir)
    requested_stage = SolverStage(stage)
    prerequisites = ("build-inp",) if requested_stage is SolverStage.DATACHECK else ("build-inp", "abaqus-datacheck")
    blocked = _stage_guard(config_path, run_dir, f"abaqus-{stage}", prerequisites)
    if blocked is not None:
        return blocked
    config = load_pipeline_config(config_path)
    sample = load_sample_json(run_dir / "input/normalized_sample.json")
    policy = load_validation_policy(_default_policy_path())
    validation = validate_sample(sample, policy)
    readiness = _readiness(sample, config, policy)
    preflight_path = run_dir / "reports" / f"abaqus_{stage}_preflight.json"
    if preflight_path.exists():
        raise FileExistsError(preflight_path)
    write_manifest(
        {"validation": validation.to_dict(), "solver_readiness": readiness.to_dict()},
        preflight_path,
    )
    if not validation.passed or not readiness.ready:
        return _record_stage(run_dir, config_path, {
            "stage": f"abaqus-{stage}", "status": "blocked",
            "command": [], "return_code": None,
            "compile_status": "unverified", "link_status": "unverified",
            "compile_link_status": "unverified",
            "artifacts": [str(preflight_path)],
            "limitations": [*readiness.missing, *(
                f"{issue.code}: {issue.message}" for issue in validation.errors
            )],
        })
    command = _effective_abaqus_command(config)
    stage_dir = run_dir / "solver" / stage
    if stage_dir.exists():
        return _blocked_stage(config_path, run_dir, f"abaqus-{stage}", ["solver stage directory already exists; create a new run"])
    input_path = run_dir / "input/model.inp"
    launch_root = stage_dir
    if config.abaqus.ascii_temp_root is not None:
        scratch = config.abaqus.ascii_temp_root
        if not str(scratch.resolve()).isascii():
            return _blocked_stage(config_path, run_dir, f"abaqus-{stage}", ["ascii_temp_root must be ASCII-only"])
        scratch.mkdir(parents=True, exist_ok=True)
        launch_root = Path(tempfile.mkdtemp(prefix=f"{config.abaqus.job_name}-{stage}-",dir=scratch)) / "job"
    work_dir = launch_root
    bundle_root = None
    bundle_manifest = None
    user_subroutine = config.abaqus.user_subroutine
    if config.abaqus.input_bundle is not None:
        native_report = json.loads((run_dir / "reports/native_bundle.json").read_text(encoding="utf-8"))
        input_path = Path(native_report["entrypoint"])
        bundle_root = Path(native_report["bundle_root"])
        bundle_manifest = bundle_root / ".pipeline-bundle-manifest.json"
        submission_rel = config.abaqus.input_bundle.submission_dir.relative_to(config.abaqus.input_bundle.source_root)
        work_dir = launch_root / submission_rel
        if user_subroutine is not None:
            user_subroutine = bundle_root / user_subroutine.relative_to(config.abaqus.input_bundle.source_root)
    result = run_abaqus(
        AbaqusRunRequest(
            abaqus_command=command,
            job_name=config.abaqus.job_name,
            inp_path=input_path,
            work_dir=work_dir,
            stage=requested_stage,
            user_subroutine=user_subroutine,
            cpus=config.abaqus.cpus,
            timeout_seconds=config.abaqus.timeout_seconds,
            input_bundle_root=bundle_root,
            input_bundle_manifest=bundle_manifest,
            input_bundle_destination=launch_root if bundle_root else None,
            version_probe_args=config.abaqus.version_probe_args,
        )
    )
    if launch_root != stage_dir and launch_root.exists():
        shutil.copytree(launch_root, stage_dir)
        def archived(path):
            return stage_dir / Path(path).relative_to(launch_root)
        result = replace(result, stdout_path=archived(result.stdout_path), stderr_path=archived(result.stderr_path),
                         artifacts=tuple(archived(p) for p in result.artifacts))
    manifest = json.loads((run_dir / "reports/run_manifest.json").read_text(encoding="utf-8"))
    post_issues = binding_issues(run_dir, config_path, manifest)
    post_issues.extend(verify_recorded_file(input_path, manifest))
    if bundle_root is not None:
        build = next(s for s in manifest["stages"] if s["stage"] == "build-inp")
        for artifact in build["artifacts"]:
            post_issues.extend(verify_recorded_file(Path(artifact), manifest))
    record = {
        "stage": f"abaqus-{stage}",
        "status": "failed" if post_issues else result.status,
        "command": list(result.command),
        "return_code": result.return_code,
        "work_dir": str(work_dir),
        "archived_stage_dir": str(stage_dir),
        "compile_link_status": result.compile_link_status,
        "compile_status": result.compile_status,
        "link_status": result.link_status,
        "solver_fingerprint": result.solver_fingerprint,
        "artifacts": [str(preflight_path), *(str(path) for path in result.artifacts),
                      *(str(p) for p in (result.stdout_path, result.stderr_path) if p.is_file())],
        "limitations": [*result.limitations, *post_issues],
    }
    return _record_stage(run_dir, config_path, record)


@_timed_stage
def run_extract_odb(config_path: Path, run_dir: Path) -> dict[str, object]:
    config_path = Path(config_path).resolve()
    run_dir = Path(run_dir).resolve()
    _require_validated_run(run_dir)
    blocked = _stage_guard(config_path, run_dir, "extract-odb", ("abaqus-analysis",))
    if blocked is not None:
        return blocked
    config = load_pipeline_config(config_path)
    odb_path = run_dir / "solver" / "analysis" / f"{config.abaqus.job_name}.odb"
    if config.abaqus.input_bundle is not None:
        submission_rel = config.abaqus.input_bundle.submission_dir.relative_to(config.abaqus.input_bundle.source_root)
        odb_path = odb_path.parent / submission_rel / odb_path.name
    output_dir = run_dir / "solver" / "extracted"
    if output_dir.exists():
        return _blocked_stage(config_path, run_dir, "extract-odb", ["extraction directory already exists; create a new run"])
    if not odb_path.is_file():
        return _record_stage(
            run_dir,
            config_path,
            {
                "stage": "extract-odb",
                "status": "blocked",
                "artifacts": [],
                "limitations": [f"real ODB is missing: {odb_path}"],
            },
        )
    request = ExtractionRequest(
        odb_path=odb_path,
        output_dir=output_dir,
        fields=config.abaqus.required_fields,
        position=config.abaqus.extraction_position,
        max_records=config.abaqus.extraction_max_records,
    )
    try:
        effective_command = _effective_abaqus_command(config)
        command = wrap_batch_command(build_abaqus_extraction_command(request, effective_command))
    except ValueError as exc:
        return _blocked_stage(config_path, run_dir, "extract-odb", [str(exc)])
    stdout_path = run_dir / "solver/extraction.stdout.txt"
    stderr_path = run_dir / "solver/extraction.stderr.txt"
    execution_dir = config.abaqus.ascii_temp_root or run_dir / "solver"
    fingerprint = capture_solver_fingerprint(effective_command, cwd=execution_dir,
                                             version_probe_args=config.abaqus.version_probe_args)
    try:
        completed = execute_process(
            command,
            cwd=execution_dir,
            capture_output=True,
            text=True,
            timeout=config.abaqus.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(_output_text(exc.stdout), encoding="utf-8")
        stderr_path.write_text(_output_text(exc.stderr), encoding="utf-8")
        return _record_stage(run_dir, config_path, {
            "stage": "extract-odb", "status": "failed", "command": list(command),
            "solver_fingerprint": fingerprint,
            "artifacts": [str(stdout_path), str(stderr_path)],
            "limitations": [f"Abaqus extraction timeout after {config.abaqus.timeout_seconds} seconds"],
        })
    except FileNotFoundError as exc:
        return _record_stage(
            run_dir,
            config_path,
            {
                "stage": "extract-odb",
                "status": "blocked",
                "command": list(command),
                "solver_fingerprint": fingerprint,
                "artifacts": [],
                "limitations": [f"Abaqus extraction command unavailable: {exc}"],
            },
        )
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    complete, missing = extraction_bundle_is_complete(output_dir)
    limitations = [f"missing extraction file: {name}" for name in missing]
    manifest = json.loads((run_dir / "reports/run_manifest.json").read_text(encoding="utf-8"))
    limitations.extend(binding_issues(run_dir, config_path, manifest))
    limitations.extend(verify_recorded_file(odb_path, manifest))
    if complete:
        metadata_path = output_dir / "metadata.json"
        extraction_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if extraction_metadata.get("odb_sha256") != sha256_file(odb_path):
            limitations.append("extracted ODB hash does not match the verified analysis artifact")
        if "missing_fields" not in extraction_metadata or extraction_metadata["missing_fields"]:
            limitations.append(f"required field evidence incomplete: {extraction_metadata.get('missing_fields')}")
        if extraction_metadata.get("errors") or extraction_metadata.get("complete") is False:
            limitations.append(f"extractor reported incomplete/error state: {extraction_metadata.get('errors', [])}")
        sample = load_sample_json(run_dir / "input/normalized_sample.json")
        extraction_metadata["sample_metadata"] = sample.metadata.model_dump(mode="json")
        extraction_metadata["odb_path"] = str(odb_path)
        extraction_metadata["field_units"] = dict(config.abaqus.field_units)
        metadata_path.write_text(
            json.dumps(extraction_metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            load_extraction_bundle(output_dir)
        except (ValueError, OSError) as exc:
            limitations.append(f"extraction data contract: {exc}")
    status = "completed" if completed.returncode == 0 and complete and not limitations else "failed"
    artifacts = [str(path) for path in output_dir.iterdir()] if output_dir.exists() else []
    artifacts.extend([str(stdout_path), str(stderr_path)])
    return _record_stage(
        run_dir,
        config_path,
        {
            "stage": "extract-odb",
            "status": status,
            "solver_fingerprint": fingerprint,
            "command": list(command),
            "return_code": completed.returncode,
            "artifacts": artifacts,
            "limitations": limitations,
        },
    )


@_timed_stage
def run_export(
    config_path: Path,
    run_dir: Path,
    format_name: str,
) -> dict[str, object]:
    config_path = Path(config_path).resolve()
    run_dir = Path(run_dir).resolve()
    _require_validated_run(run_dir)
    if format_name not in {"hdf5", "npz", "pyg"}:
        raise ValueError(f"unsupported export format: {format_name}")
    prerequisites = ("export-hdf5",) if format_name != "hdf5" else ()
    extracted_dir = run_dir / "solver/extracted"
    # A missing directory must not erase a recorded stage from the dependency
    # graph. Also reject an unregistered directory rather than importing it.
    extraction_expected = extracted_dir.exists() or any(
        record.get("stage") == "extract-odb" for record in _stage_records(run_dir)
    )
    if extraction_expected:
        prerequisites += ("extract-odb",)
    blocked = _stage_guard(config_path, run_dir, f"export-{format_name}", prerequisites)
    if blocked is not None:
        return blocked
    validation = json.loads((run_dir / "reports/validation.json").read_text(encoding="utf-8"))
    # Data validity is distinct from solver readiness: a valid curve-only
    # sample may be exported without a mesh/material/solver contract.
    if validation.get("passed") is not True:
        return _blocked_stage(config_path, run_dir, f"export-{format_name}",
                              ["data validation did not pass; formal export is blocked"])
    config = load_pipeline_config(config_path)
    if format_name not in config.export.formats:
        return _blocked_stage(config_path, run_dir, f"export-{format_name}",
                              [f"requested format {format_name!r} requires inclusion in export.formats"])
    if extraction_expected:
        manifest = json.loads((run_dir / "reports/run_manifest.json").read_text(encoding="utf-8"))
        issues = []
        for name in ("metadata.json", "frames.csv"):
            issues.extend(verify_recorded_file(extracted_dir / name, manifest))
        if issues:
            return _blocked_stage(config_path, run_dir, f"export-{format_name}", issues)
    if format_name in {"npz", "pyg"}:
        hdf5_path = run_dir / "dataset/sample.h5"
        digest = sha256_file(hdf5_path)
        output = run_dir / "dataset" / ("sample.npz" if format_name == "npz" else "sample.pt")
        try:
            writer = write_npz if format_name == "npz" else write_pyg
            writer(hdf5_path, output, digest)
        except (ValueError, RuntimeError) as exc:
            return _blocked_stage(config_path, run_dir, f"export-{format_name}", [str(exc)])
        return _record_stage(run_dir, config_path, {
            "stage": f"export-{format_name}", "status": "completed", "artifacts": [str(output)],
            "source_hdf5_sha256": digest, "limitations": [],
        })
    sample = load_sample_json(run_dir / "input/normalized_sample.json")
    complete, _ = extraction_bundle_is_complete(extracted_dir)
    if extraction_expected and not complete:
        return _blocked_stage(config_path, run_dir, "export-hdf5",
                              ["recorded extraction became incomplete before export"])
    if extraction_expected:
        if sample.tables.get("simulation_records"):
            return _blocked_stage(config_path, run_dir, "export-hdf5", [
                "simulation_records already contains another source; use separate samples or explicit source registration before merging"
            ])
        try:
            extracted = load_extraction_bundle(extracted_dir)
        except (ValueError, OSError) as exc:
            return _blocked_stage(config_path, run_dir, "export-hdf5", [f"extraction data contract: {exc}"])
        sample = SamplePackage(
            metadata=sample.metadata.model_copy(
                update={
                    "sources": (
                        *sample.metadata.sources,
                        *extracted.metadata.sources,
                    )
                }
            ),
            tables={**sample.tables, **extracted.tables},
            arrays={**sample.arrays, **extracted.arrays},
            assets=(*sample.assets, *extracted.assets),
            solver_inputs={
                **sample.solver_inputs,
                "extraction": extracted.solver_inputs["extraction"],
            },
        )
    report = validate_sample(sample, load_validation_policy(_default_policy_path()))
    validation_path = run_dir / "reports/export-hdf5_validation.json"
    qa_path = run_dir / "reports/export-hdf5_qa.md"
    write_validation_report(report, validation_path, qa_path)
    artifacts: list[str] = [str(validation_path), str(qa_path)]
    if not report.passed:
        return _record_stage(run_dir, config_path, {
            "stage": "export-hdf5", "status": "blocked", "artifacts": artifacts,
            "validation": report.to_dict(),
            "limitations": [f"{issue.code}: {issue.message}" for issue in report.errors],
        })
    if format_name == "hdf5":
        output = run_dir / "dataset" / "sample.h5"
        digest = write_hdf5(
            sample,
            output,
            json.loads((run_dir / "reports" / "run_manifest.json").read_text(encoding="utf-8")),
        )
        artifacts.append(str(output))
    else:
        raise ValueError(f"unsupported export format: {format_name}")
    return _record_stage(
        run_dir,
        config_path,
        {
            "stage": f"export-{format_name}",
            "status": "completed",
            "artifacts": artifacts,
            "source_hdf5_sha256": digest,
            "validation": report.to_dict(),
            "limitations": [],
        },
    )


def inspect_run(run_dir: Path) -> dict[str, object]:
    path = Path(run_dir) / "reports" / "run_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))
