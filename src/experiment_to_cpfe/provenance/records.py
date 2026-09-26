"""Strict JSON references and atomic receipts for data import operations.

Extracted from the project's local study/recovery boundaries without training,
solver execution or orchestration dependencies.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from pydantic import Field

from experiment_to_cpfe.datasets.training_config import Contract, Declared
from experiment_to_cpfe.provenance.hashing import sha256_file


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError(f'duplicate JSON field: {key}')
        result[key] = value
    return result


def read_json(path: Path):
    deadline = time.monotonic() + 1
    while True:
        try:
            content = path.read_text(encoding='utf-8')
            break
        except PermissionError:
            if os.name != 'nt' or time.monotonic() >= deadline:
                raise
            time.sleep(.02)
    return json.loads(content, object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'nonfinite JSON: {value}')))


def _replace(temporary, path):
    # Windows readers/virus scanners can briefly hold a destination without
    # delete sharing. Keep the old complete file while retrying that condition.
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.05 * (attempt + 1))


def write_record(path, value):
    """Replace a run status only after its complete JSON has been written."""
    path = Path(path)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    _replace(temporary, path)


class FileRef(Contract):
    path: Declared
    sha256: Declared = Field(pattern=r'^[a-f0-9]{64}$')


def artifact(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=sha256_file(path))


def bound_json(reference, base):
    reference = FileRef.model_validate(reference)
    path = (Path(base) / reference.path).resolve()
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('bound JSON exceeds 32 MiB')
    before = sha256_file(path)
    if before != reference.sha256:
        raise ValueError(f'configuration hash mismatch: {path}')
    value = read_json(path)
    if sha256_file(path) != before:
        raise ValueError('configuration changed while reading')
    return value, path


def recorded_operation(config_path, output_dir, name, contract, operation):
    path, output = Path(config_path).resolve(), Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    report = dict(format='experiment-to-cpfe-'+name+'-1', stage=name, status='running',
        started_at=datetime.now(timezone.utc).isoformat(), config={'path': str(path)})
    receipt = output/(name+'.json')
    write_record(receipt, report)
    try:
        report['config'] = artifact(path)
        config = contract.model_validate(read_json(path))
        report['config']['resolved'] = config.model_dump(mode='json')
        report.update(operation(config,path.parent,output,report))
        if sha256_file(path) != report['config']['sha256']:
            raise ValueError('configuration changed during execution')
        report.update(status='completed', finished_at=datetime.now(timezone.utc).isoformat(),
            wall_seconds=time.perf_counter()-started)
        write_record(receipt,report)
    except (Exception,KeyboardInterrupt) as exc:
        report.update(status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',
            error=dict(type=type(exc).__name__,message=str(exc)),wall_seconds=time.perf_counter()-started)
        write_record(receipt,report)
        raise
    return report
