"""Run-directory creation and deterministic provenance manifests."""

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform

from experiment_to_cpfe import __version__

from experiment_to_cpfe.provenance.hashing import sha256_file


STAGE_DIRECTORIES = ("input", "solver", "dataset", "reports")


def source_fingerprint(package_root: Path) -> dict[str, object]:
    """Hash relative source/resource names and their bytes in stable order."""
    root = Path(package_root)
    files = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and (path.suffix in {".py", ".yaml"} or path.name == "py.typed")
        and "__pycache__" not in path.parts
    }
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(payload).hexdigest(), "files": files,
            "encoding": "sha256-of-sorted-relative-file-digests-json"}


def runtime_fingerprint() -> dict[str, object]:
    """Capture installed core dependencies and the package bytes executing a run."""
    return {
        "tool": {"name": "experiment-to-cpfe", "version": __version__},
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation()},
        "dependencies": {name: version(name) for name in ("numpy", "h5py", "pandas", "pydantic", "PyYAML")},
        "code": source_fingerprint(Path(__file__).resolve().parents[1]),
    }


def create_run_directory(root: Path, sample_id: str, run_id: str) -> Path:
    target = Path(root) / sample_id / run_id
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"run directory is non-empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    for name in STAGE_DIRECTORIES:
        (target / name).mkdir()
    return target


def build_run_manifest(
    run_dir: Path,
    config_path: Path,
    stage_records: list[dict[str, object]],
) -> dict[str, object]:
    artifacts: dict[str, dict[str, object]] = {}
    for stage in stage_records:
        for raw_path in stage.get("artifacts", []):
            path = Path(str(raw_path))
            if path.is_file():
                artifacts[str(path)] = {
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
    return {
        "schema_version": "0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(Path(run_dir)),
        "config_path": str(Path(config_path)),
        "config_sha256": sha256_file(config_path) if Path(config_path).is_file() else None,
        "runtime": runtime_fingerprint(),
        "stages": stage_records,
        "artifacts": artifacts,
        "limitations": [
            limitation
            for stage in stage_records
            for limitation in stage.get("limitations", [])
        ],
    }


def write_manifest(manifest: dict[str, object], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
