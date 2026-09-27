"""Write stable SHA256SUMS.txt receipts for the regular files of a run."""

import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile


def _artifacts(root: Path) -> list[Path]:
    files = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        for name in (*names, *filenames):
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError(f"run artifacts require direct files and directories: {path}")
        for name in filenames:
            path = Path(directory) / name
            if path == root / "SHA256SUMS.txt":
                continue
            relative = path.relative_to(root).as_posix()
            if any(character in relative for character in ("\r", "\n", "\\")):
                raise ValueError(f"checksum filenames require single-line portable names: {path}")
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError(f"expected a regular artifact file: {path}")
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def hash_run_artifacts(run_dir: Path) -> tuple[Path, int]:
    """Read artifact bytes and atomically replace only the root checksum file.

    Paths are relative POSIX names sorted lexically. The checksum file excludes
    itself, making repeated receipts stable. Source size and modification time
    are checked around each read to detect files changing during hashing.
    """
    root = Path(run_dir)
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise ValueError(f"run directory must be an existing direct directory: {root}")
    root = root.resolve()
    files = _artifacts(root)
    lines = []
    for path in files:
        before = path.stat()
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError(f"artifact changed during hashing: {path}")
        lines.append(f"{digest}  {path.relative_to(root).as_posix()}\n")
    if _artifacts(root) != files:
        raise ValueError("run directory changed during hashing")
    output = root / "SHA256SUMS.txt"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         prefix=".checksums-", dir=root, delete=False) as stream:
            temporary = Path(stream.name)
            stream.writelines(lines)
        temporary.replace(output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return output, len(files)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        output, count = hash_run_artifacts(args.run_dir)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Wrote {output} ({count} artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
