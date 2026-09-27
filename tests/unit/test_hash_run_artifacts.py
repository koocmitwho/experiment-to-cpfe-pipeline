"""Verify the standalone artifact-checksum command against known bytes."""

import hashlib
from pathlib import Path
import subprocess
import sys


SCRIPT = Path("scripts/hash_run_artifacts.py").resolve()


def execute(run):
    return subprocess.run([sys.executable, str(SCRIPT), str(run)],
                          capture_output=True, text=True, timeout=30)


def test_checksum_command_sorts_relative_names_and_hashes_all_regular_files(tmp_path):
    run = tmp_path / "run"
    (run / "nested").mkdir(parents=True)
    (run / "z file.txt").write_bytes(b"abc")
    (run / "nested/empty.bin").write_bytes(b"")
    (run / ".hidden").write_bytes(b"abc")
    result = execute(run)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (run / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines() == [
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad  .hidden",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  nested/empty.bin",
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad  z file.txt",
    ]


def test_checksum_repeated_run_is_stable_and_preserves_artifacts(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    source = run / "sample.h5"
    source.write_bytes(bytes(range(256)) * 5000)
    before = source.read_bytes(), source.stat().st_mtime_ns, source.stat().st_mode
    for _ in range(2):
        result = execute(run)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (source.read_bytes(), source.stat().st_mtime_ns, source.stat().st_mode) == before
        assert (run / "SHA256SUMS.txt").read_text() == f"{hashlib.sha256(before[0]).hexdigest()}  sample.h5\n"


def test_checksum_command_reports_a_missing_run_directory(tmp_path):
    run = tmp_path / "missing"
    result = execute(run)
    assert result.returncode == 1
    assert "directory" in result.stderr.lower()
    assert not run.exists()


def test_checksum_command_handles_an_empty_run_directory(tmp_path):
    result = execute(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "SHA256SUMS.txt").read_bytes() == b""
