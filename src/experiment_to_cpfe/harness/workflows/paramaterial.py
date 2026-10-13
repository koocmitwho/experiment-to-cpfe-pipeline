"""Read-only registration of the reviewed, fixed Paramaterial v0.3.1 case.

The allowlist pins executable code and scientific inputs. A changed case needs a
new reviewed workflow version; tool callers cannot replace its truth or code.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import sys

import experiment_to_cpfe


WORKFLOW_ID = "paramaterial_tensile.v1"
IDS = ("test_ID_055", "test_ID_056", "test_ID_057")
ROWS = (614, 645, 630)
UNITS = {"Strain": "1", "Stress_MPa": "MPa"}
PROCESSING_SHA256 = "5c991eebb20968e77d93522c4be50d4fa9812de8bf0d430471d46fadbd4e6d22"
# Exact reviewed bytes at c6e2182783bea448007dc71422bfa296b3e8ea5c.
EXPECTED_FILES = {
    "workflow.py": "f6dc8b794c146f869dcbfaf722dd3dd5271935ab98fe4362ffaf2512bbf72adc",
    "verify_outputs.py": "6bc9032ba5f0e2c34fbc28560cc2231e95af0636d0a45af3e16c3e3961429b6f",
    "requirements.txt": "193e8b1df0ec7102edcb1714fc349aee6ce59b8f67e4d9ae00c182d0ed4b547d",
    "data/manifest.json": "d922aa8203f35e2392ce63d2c164122678feced0878f704bbbbb29086df98ff5",
    "data/reference_metrics.json": "3353997f8d61efc940c7c8ef36e328b7ef70116f12196523dce1849aeaf2767c",
    "data/test_ID_055.csv": "35ed1f7b1e0406bba3ba903087e186097d60229f4a533b07188515845fb162b5",
    "data/test_ID_056.csv": "4e381c1c478cb093788a5d7df9bf51d7d23a299b9fb2a7aa18351371f6ee24e1",
    "data/test_ID_057.csv": "ab08b8e87472facdbb842b1dd7ed3567b50089269dc33655023944b495da50bb",
}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("case JSON exceeds bound")
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def inspect_case(case_dir: Path) -> dict:
    """Validate fixed source bytes and report field-specific declaration issues."""
    root = Path(case_dir).resolve()
    issues, files = [], {}

    def issue(code, field, message):
        issues.append({"code": code, "field": field, "safe_message": message})

    for relative, expected in EXPECTED_FILES.items():
        path = root / relative
        try:
            if not path.resolve().is_relative_to(root) or path.is_symlink():
                issue("PATH_NOT_ALLOWED", relative, "Case files must remain inside the registered case.")
                continue
            if not path.is_file():
                issue("MISSING_INPUT", relative, "A required case file is missing.")
                continue
            if path.stat().st_size > 4 * 1024 * 1024:
                issue("INPUT_TOO_LARGE", relative, "The fixed-case input exceeds its size bound.")
                continue
            files[relative] = _sha(path)
            if files[relative] != expected:
                issue("SOURCE_HASH_MISMATCH", relative, "The file differs from the reviewed fixed case.")
        except OSError:
            issue("INPUT_UNREADABLE", relative, "A required case file could not be read.")

    if "data/manifest.json" in files:
        try:
            manifest = _json(root / "data/manifest.json")
            required = ("schema_version", "dataset", "examples_commit", "paramaterial", "specimens")
            for field in required:
                if field not in manifest:
                    issue("MISSING_METADATA", field, "Required source metadata is missing.")
            for section, fields in {"dataset": ("doi", "url", "license", "title", "contributors"),
                                    "paramaterial": ("version", "processing_sha256")}.items():
                nested = manifest.get(section)
                for field in fields:
                    if not isinstance(nested, dict) or not nested.get(field):
                        issue("MISSING_METADATA", f"{section}.{field}", "Required source metadata is missing.")
            entries = manifest.get("specimens", [])
            if not isinstance(entries, list) or len(entries) != 3:
                issue("SPECIMEN_IDENTITY_MISMATCH", "specimens", "Exactly three registered specimens are required.")
                entries = []
            for index, entry in enumerate(entries):
                prefix = f"specimens.{index}"
                required = ("sample_id", "filename", "sha256", "rows", "temperature_C", "lot",
                            "specimen_number", "original_filename", "upstream_url", "units", "screening")
                if not isinstance(entry, dict):
                    issue("MISSING_METADATA", prefix, "A specimen declaration must be an object.")
                    continue
                for field in required:
                    if field not in entry or entry[field] is None or entry[field] == "":
                        issue("MISSING_METADATA", f"{prefix}.{field}", "Required specimen metadata is missing.")
                if entry.get("sample_id") != IDS[index]:
                    issue("SPECIMEN_IDENTITY_MISMATCH", f"{prefix}.sample_id", "The specimen identity is not registered.")
                if entry.get("units") != UNITS:
                    issue("INVALID_UNITS", f"{prefix}.units", "Engineering strain must be 1 and engineering stress MPa.")
                if entry.get("rows") != ROWS[index]:
                    issue("ROW_COUNT_MISMATCH", f"{prefix}.rows", "The source row count differs from the fixed case.")
                for section, fields in {"screening": ("rejected", "source_url", "source_sha256"),
                                        "units": tuple(UNITS)}.items():
                    nested = entry.get(section)
                    for field in fields:
                        if (not isinstance(nested, dict) or field not in nested
                                or nested[field] is None or nested[field] == ""):
                            issue("MISSING_METADATA", f"{prefix}.{section}.{field}",
                                  "Required specimen source metadata is missing.")
        except (OSError, ValueError, TypeError, AttributeError):
            issue("INVALID_MANIFEST", "data/manifest.json", "The case manifest is malformed.")

    for sample_id, expected_rows in zip(IDS, ROWS):
        relative = f"data/{sample_id}.csv"
        if relative not in files:
            continue
        try:
            with (root / relative).open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames != list(UNITS):
                    raise ValueError("columns")
                rows = list(reader)
            if len(rows) != expected_rows:
                issue("ROW_COUNT_MISMATCH", relative, "The original row count is not preserved.")
            if any(not math.isfinite(float(row[field])) for row in rows for field in UNITS):
                raise ValueError("nonfinite")
        except (OSError, ValueError, TypeError, KeyError):
            issue("INVALID_CURVE", relative, "The curve must contain the declared finite numeric columns.")
    return {"valid": not issues, "issues": issues, "files": files, "workflow_id": WORKFLOW_ID,
            "specimen_ids": list(IDS), "total_rows": sum(ROWS)}


def environment_identity() -> dict:
    """Read installed distribution identity without importing Paramaterial or models."""
    dependencies = {}
    distribution_versions = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            distribution_versions[name.lower().replace("_", "-")] = distribution.version
    for name in ("experiment-to-cpfe", "paramaterial", "numpy", "pandas", "scipy", "matplotlib",
                 "seaborn", "h5py", "openpyxl", "pydantic", "PyYAML"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    processing_sha = None
    try:
        distribution = importlib.metadata.distribution("paramaterial")
        processing = Path(distribution.locate_file("paramaterial/processing.py"))
        processing_sha = _sha(processing)
    except (importlib.metadata.PackageNotFoundError, OSError):
        pass
    core_files = {}
    package_dir = None
    try:
        # Editable distributions may keep their metadata in site-packages while
        # the executed package lives in src/. Hash the resolved loaded package,
        # whose location does not depend on which metadata sys.path finds first.
        core = Path(experiment_to_cpfe.__file__).resolve().parent
        package_dir = str(core)
        for path in sorted(core.rglob("*")):
            if path.is_file() and path.suffix in (".py", ".yaml"):
                core_files[path.relative_to(core).as_posix()] = _sha(path)
    except (OSError, TypeError):
        pass
    return {"python_executable": str(Path(sys.executable).resolve()), "python_version": platform.python_version(),
            "python_sha256": _sha(Path(sys.executable).resolve()),
            "implementation": platform.python_implementation(), "platform": platform.platform(),
            "dependencies": dependencies, "processing_sha256": processing_sha,
            "package_dir": package_dir,
            "distribution_versions": dict(sorted(distribution_versions.items())),
            "core_sha256": hashlib.sha256(json.dumps(core_files, sort_keys=True).encode()).hexdigest(),
            "available": bool(core_files) and all(dependencies.values()) and processing_sha == PROCESSING_SHA256}


def case_command(case_dir: Path, output_dir: Path, python_executable: Path) -> list[str]:
    """Build a fixed argv vector; this function never launches a process."""
    case_dir, output_dir = Path(case_dir).resolve(), Path(output_dir).resolve()
    if not inspect_case(case_dir)["valid"]:
        raise ValueError("CASE_NOT_REGISTERED")
    if output_dir.is_relative_to(case_dir) or case_dir.is_relative_to(output_dir):
        raise ValueError("OUTPUT_OVERLAPS_INPUT")
    return [str(Path(python_executable).resolve()), "-I", "-X", "utf8", "-B",
            str(case_dir / "workflow.py"), "--run-dir", str(output_dir)]
