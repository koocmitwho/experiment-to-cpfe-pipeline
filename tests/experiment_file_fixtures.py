"""Synthetic JSON and source reference helpers for experiment file tests."""
import json
from pathlib import Path

from experiment_to_cpfe.provenance.hashing import sha256_file


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def ref(path):
    return dict(path=str(Path(path).resolve()), sha256=sha256_file(path))
