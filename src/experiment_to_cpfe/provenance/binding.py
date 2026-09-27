"""Content binding and integrity checks for declared inputs."""

import json
from pathlib import Path

from experiment_to_cpfe.config import PipelineConfig
from experiment_to_cpfe.provenance.hashing import sha256_file
from experiment_to_cpfe.solvers.abaqus.bundle import snapshot_input_bundle


def capture_inputs(config: PipelineConfig, config_path: Path, policy_path: Path) -> dict:
    paths = [config_path, policy_path, *(s.path for s in config.sources),
             *(a.path for a in config.assets)]
    paths.extend(p for p in (config.abaqus.template_path, config.abaqus.user_subroutine) if p is not None)
    paths.extend(source.path for imported in config.imports for source in imported.files.values())
    bundle = config.abaqus.input_bundle
    native_hashes = {}
    if bundle is not None:
        auxiliary = (*bundle.auxiliary_files, *((config.abaqus.user_subroutine,) if config.abaqus.user_subroutine else ()))
        snapshot = snapshot_input_bundle(bundle.entrypoint, source_root=bundle.source_root,
                    submission_dir=bundle.submission_dir, auxiliary_files=auxiliary,
                    max_files=bundle.max_files, max_total_bytes=bundle.max_total_bytes)
        native_hashes = snapshot.hashes
        paths.extend(snapshot.files)
    unique_paths = tuple(dict.fromkeys(paths))
    return {
        "version": "input-lock-1",
        "config_path": str(config_path.resolve()),
        "files": {str(p.resolve()): sha256_file(p) if p.is_file() else None for p in unique_paths},
        "native_bundle_files": native_hashes,
    }


def changed_inputs(binding: dict) -> list[str]:
    issues = []
    for name, expected in binding["files"].items():
        path = Path(name)
        try:
            observed = sha256_file(path) if path.is_file() else None
        except OSError:
            observed = None
        if observed != expected:
            issues.append(f"input integrity mismatch: {name}; expected={expected}, observed={observed}")
    return issues


def verify_recorded_file(path: Path, manifest: dict) -> list[str]:
    record = manifest.get("artifacts", {}).get(str(path))
    if not record or not path.is_file():
        return [f"input integrity evidence missing: {path}"]
    try:
        if sha256_file(path) == record.get("sha256"):
            return []
    except OSError:
        pass
    return [f"input integrity mismatch: {path}"]


def binding_issues(run_dir: Path, config_path: Path, manifest: dict) -> list[str]:
    lock_path = run_dir / "input/input_lock.json"
    issues = verify_recorded_file(lock_path, manifest)
    if issues:
        return issues + ["input binding unavailable or changed; create a new validated run"]
    try:
        binding = json.loads(lock_path.read_text(encoding="utf-8"))
        if binding.get("version") != "input-lock-1":
            return ["input integrity binding version is unsupported"]
        if str(config_path.resolve()) != binding["config_path"]:
            issues.append("input integrity mismatch: config location changed")
        issues.extend(changed_inputs(binding))
        for name in ("input/normalized_sample.json", "reports/validation.json",
                     "reports/solver_readiness.json", "reports/qa_report.md"):
            issues.extend(verify_recorded_file(run_dir / name, manifest))
    except (KeyError, TypeError, ValueError, OSError) as exc:
        issues.append(f"input integrity binding is unreadable: {exc}")
    return issues
