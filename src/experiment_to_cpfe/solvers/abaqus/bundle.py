"""Byte-preserving, confined staging of explicit Abaqus *INCLUDE bundles.

Paths in every include are relative to the submitted job's directory, NOT the
including file. This is a dependency/staging check, never a solver-readiness gate.
Other file-bearing keywords and abbreviated include syntax are rejected.
Auxiliary files (e.g. Fortran) are copied verbatim; their dependencies are not parsed.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re


@dataclass(frozen=True)
class StagedInputBundle:
    entrypoint: Path
    submission_dir: Path
    manifest_path: Path


@dataclass(frozen=True)
class InputBundleSnapshot:
    source_root: Path
    entrypoint: Path
    submission_dir: Path
    files: dict[Path, bytes]
    include_edges: list[dict[str, str]]

    @property
    def hashes(self) -> dict[str, str]:
        return {str(path): hashlib.sha256(data).hexdigest() for path, data in self.files.items()}

    def expanded_text(self) -> str:
        def expand(path: Path) -> str:
            text = self.files[path].decode("utf-8-sig")
            lines, pending = [], ""
            for line in text.splitlines():
                stripped = line.strip()
                if pending:
                    if not stripped or stripped.startswith("**"):
                        continue
                    pending += stripped
                elif stripped.upper().startswith("*INCLUDE") and not stripped.startswith("**"):
                    pending = stripped
                else:
                    lines.append(line)
                    continue
                if pending.endswith(","):
                    continue
                names = _include_names(pending.encode("utf-8"))
                for name in names:
                    lines.append(expand((self.submission_dir / name).resolve()))
                pending = ""
            return "\n".join(lines) + "\n"
        return expand(self.entrypoint)


def _checked_path(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"dependency outside source root: {path}")
    resolved = path.resolve(strict=True)
    for parent in (path, *path.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError(f"symbolic dependency is not supported: {path}")
        if parent == root:
            break
    return resolved


def _include_names(data: bytes) -> list[str]:
    names = []
    pending = ""
    for raw in data.decode("utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if not line.isascii():
            raise ValueError("Abaqus keyword/data lines must be ASCII")
        if pending:
            if line.startswith("*"):
                raise ValueError("unterminated keyword continuation")
            line = pending + line
        elif not line.startswith("*"):
            continue
        if line.endswith(","):
            pending = line
            continue
        pending = ""
        if line.count('"') % 2:
            raise ValueError("unbalanced keyword quotes")
        parts = re.split(r',(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)', line)
        keyword = "".join(parts[0].upper().split())
        parameters = []
        for part in parts[1:]:
            key, separator, value = part.partition("=")
            parameters.append(("".join(key.upper().split()), value.strip(), bool(separator)))
        if keyword != "*INCLUDE":
            if "*INCLUDE".startswith(keyword) or any(
                key and any(full.startswith(key) for full in ("INPUT", "FILE", "LIBRARY"))
                for key, _, _ in parameters
            ):
                raise ValueError(f"unsupported external dependency keyword: {keyword}")
            continue
        if len(parameters) != 1 or parameters[0][0] != "INPUT" or not parameters[0][2]:
            raise ValueError("INCLUDE requires exactly one explicit INPUT parameter")
        value = parameters[0][1]
        if value.startswith('"') and value.endswith('"') and value.count('"') == 2:
            value = value[1:-1]
        elif '"' in value:
            raise ValueError("unsupported include quoting")
        else:
            value = "".join(value.split())
        if not value:
            raise ValueError("empty INCLUDE filename")
        value = value.replace("\\", "/")
        if PureWindowsPath(value).drive or value.startswith("/") or ":" in value:
            raise ValueError("absolute or drive-qualified include paths are not portable")
        names.append(value)
    if pending:
        raise ValueError("unterminated keyword continuation")
    return names


def snapshot_input_bundle(
    entrypoint: Path,
    *,
    source_root: Path,
    submission_dir: Path,
    auxiliary_files: tuple[Path, ...] = (),
    max_files: int = 4096,
    max_total_bytes: int = 32 * 1024 * 1024,
) -> InputBundleSnapshot:
    """Read only the bounded transitive dependency graph into an immutable-byte snapshot."""
    root = Path(source_root).resolve(strict=True)
    if max_files < 1 or max_total_bytes < 1:
        raise ValueError("file limit and byte limit must be positive")
    submission = _checked_path(Path(submission_dir).absolute(), root)
    if not submission.is_dir():
        raise ValueError("submission directory must be a directory")
    entry = _checked_path(Path(entrypoint).absolute(), root)
    files: dict[Path, bytes] = {}
    active: set[Path] = set()
    edges: list[dict[str, str]] = []
    total_bytes = 0

    def snapshot(path: Path) -> bytes:
        nonlocal total_bytes
        if path in files:
            return files[path]
        if len(files) >= max_files:
            raise ValueError("bundle file limit exceeded")
        with path.open("rb") as stream:
            data = stream.read(max_total_bytes - total_bytes + 1)
        total_bytes += len(data)
        if total_bytes > max_total_bytes:
            raise ValueError("bundle byte limit exceeded")
        files[path] = data
        return data

    def visit(path: Path) -> None:
        path = _checked_path(path, root)
        if path in active:
            raise ValueError(f"include cycle: {path.relative_to(root)}")
        if path in files:
            return
        if len(active) >= 64:
            raise ValueError("include nesting exceeds supported depth 64")
        active.add(path)
        data = snapshot(path)
        # Keep the validated bytes in memory so staged content cannot diverge
        # from the hashed snapshot if a source changes between scan and copy.
        for name in _include_names(data):
            dependency = _checked_path(submission / name, root)
            edges.append({"from": path.relative_to(root).as_posix(), "to": dependency.relative_to(root).as_posix()})
            visit(dependency)
        active.remove(path)

    visit(entry)
    for auxiliary in auxiliary_files:
        path = _checked_path(Path(auxiliary).absolute(), root)
        snapshot(path)
    for path in files:
        if not path.relative_to(root).as_posix().isascii():
            raise ValueError("bundle filenames must be ASCII-only")
    manifest_relative = Path(".pipeline-bundle-manifest.json")
    if root / manifest_relative in files:
        raise ValueError("reserved staging manifest filename")
    return InputBundleSnapshot(root, entry, submission, files, edges)


def stage_input_bundle(entrypoint: Path, *, source_root: Path, submission_dir: Path,
                       destination: Path, license: str, auxiliary_files: tuple[Path, ...] = (),
                       max_files: int = 4096, max_total_bytes: int = 32 * 1024 * 1024,
                       expected_hashes: dict[str, str] | None = None) -> StagedInputBundle:
    root, target = Path(source_root).resolve(strict=True), Path(destination).resolve()
    if target == root or target.is_relative_to(root) or root.is_relative_to(target):
        raise ValueError("source and destination trees overlap")
    if target.exists():
        raise FileExistsError(target)
    if not str(target).isascii():
        raise ValueError("staging directory must be ASCII-only")
    if not license.strip():
        raise ValueError("explicit license identifier or unknown is required")
    snapshot = snapshot_input_bundle(entrypoint, source_root=root, submission_dir=submission_dir,
                                    auxiliary_files=auxiliary_files, max_files=max_files,
                                    max_total_bytes=max_total_bytes)
    if expected_hashes is not None and snapshot.hashes != expected_hashes:
        raise ValueError("input bundle integrity differs from the recorded snapshot")
    files, entry, submission, edges = snapshot.files, snapshot.entrypoint, snapshot.submission_dir, snapshot.include_edges
    manifest_relative = Path(".pipeline-bundle-manifest.json")

    target.mkdir(parents=True, exist_ok=False)
    (target / submission.relative_to(root)).mkdir(parents=True, exist_ok=True)
    assets = []
    for path, data in sorted(files.items()):
        relative = path.relative_to(root)
        staged = target / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        with staged.open("xb") as stream:
            stream.write(data)
        digest = hashlib.sha256(data).hexdigest()
        identity = hashlib.sha256((relative.as_posix() + "\0" + digest).encode()).hexdigest()
        raw_id = "raw-" + identity
        common = {
            "sha256": digest, "size_bytes": len(data), "source_kind": "input",
            "original_format": path.suffix.lstrip(".").lower(),
            "target_format": path.suffix.lstrip(".").lower(),
            "license": license, "lossy_transformations": [],
            "relative_path": relative.as_posix(),
        }
        assets.append({**common, "asset_id": raw_id, "parent_asset_id": None, "uri": str(path), "layer": "raw"})
        # Preserve the source layer when staging a native file.
        assets.append({**common, "asset_id": "staged-" + identity, "parent_asset_id": raw_id, "uri": str(staged), "layer": "raw"})
    manifest = target / manifest_relative
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump({
            "schema_version": "input-bundle-1", "operation": "byte_preserving_copy",
            "entrypoint": entry.relative_to(root).as_posix(),
            "submission_dir": submission.relative_to(root).as_posix(),
            "assets": assets, "include_edges": edges,
            "limitations": ["Solver readiness is checked by the consuming stage", "Auxiliary files are supplied explicitly"],
        }, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return StagedInputBundle(target / entry.relative_to(root), target / submission.relative_to(root), manifest)
