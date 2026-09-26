"""Explicit sample normalization, independent of solver-readiness requirements."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import json

from pydantic import BaseModel, ConfigDict, Field
import yaml

from experiment_to_cpfe.adapters.tabular import assemble_sample
from experiment_to_cpfe.adapters.native_models import NativeImportConfig
from experiment_to_cpfe.config import SampleConfig, TabularSourceConfig, ExternalAssetConfig
from experiment_to_cpfe.datasets.hdf5 import write_hdf5, read_hdf5
from experiment_to_cpfe.pipeline import _default_policy_path
from experiment_to_cpfe.provenance.hashing import sha256_file
from experiment_to_cpfe.schema.validation import validate_sample, load_validation_policy
from experiment_to_cpfe.diagnostics import DiagnosticError, diagnostic, diagnostics_for


class NormalizationConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    version: Literal[1]
    purpose: str = Field(min_length=1)
    sample: SampleConfig
    sources: tuple[TabularSourceConfig, ...] = ()
    assets: tuple[ExternalAssetConfig, ...] = ()
    imports: tuple[NativeImportConfig, ...] = ()
    solver_inputs: dict[str, object] = Field(default_factory=dict)


def validate_normalization_config(value):
    """Validate declarations without loading sample responses or solver state."""
    from experiment_to_cpfe.schema.validation import _unit_is_declared
    config = NormalizationConfig.model_validate(value)
    if not (config.sources or config.assets or config.imports):
        raise ValueError('normalization requires declared input sources/assets/imports')
    for i, source in enumerate(config.sources):
        for name in source.column_map:
            if not _unit_is_declared(source.units.get(name)):
                raise DiagnosticError([diagnostic(ValueError('explicit unit required for mapped field'),
                    field=f'sources.{i}.units.{name}')])
    return config


def run_normalization(config_path, output_dir):
    """Import and validate an explicit data package; keep a success/failure receipt."""
    config_path, output = Path(config_path).resolve(), Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'run directory is non-empty: {output}')
    output.mkdir(parents=True, exist_ok=True)
    receipt = dict(stage='normalize-sample', status='running', started_at=datetime.now(timezone.utc).isoformat(),
                   solver_readiness_assessed=False, configuration=str(config_path), artifacts={})
    def persist():
        temporary=output/'normalization.json.tmp'
        temporary.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(output/'normalization.json')
    persist()
    try:
        receipt['configuration_sha256'] = sha256_file(config_path)
        config = validate_normalization_config(yaml.safe_load(config_path.read_text(encoding='utf-8')))
        def resolve(item):
            return item.model_copy(update={'path': (config_path.parent / item.path).resolve()})
        config = config.model_copy(update=dict(sources=tuple(map(resolve, config.sources)),
            assets=tuple(map(resolve, config.assets)), imports=tuple(item.model_copy(update={
                'files': {key: resolve(value) for key, value in item.files.items()}}) for item in config.imports)))
        paths = [item.path for item in (*config.sources, *config.assets)]
        paths.extend(value.path for item in config.imports for value in item.files.values())
        if not paths:
            raise ValueError('normalization requires declared input sources/assets/imports')
        receipt['purpose'] = config.purpose
        receipt['inputs'] = [dict(path=str(p), sha256=sha256_file(p)) for p in dict.fromkeys(paths)]
        policy = _default_policy_path()
        receipt['policy'] = dict(path=str(policy), sha256=sha256_file(policy))
        sample = assemble_sample(config)
        validation = validate_sample(sample, load_validation_policy(policy))
        receipt['validation'] = validation.to_dict()
        if not validation.passed:
            raise ValueError('sample validation failed; inspect normalization.json')
        def check_integrity():
            if sha256_file(config_path) != receipt['configuration_sha256'] or any(
                    sha256_file(Path(item['path'])) != item['sha256'] for item in [*receipt['inputs'], receipt['policy']]):
                raise ValueError('configuration/input/policy integrity changed during normalization')
        check_integrity()
        destination = output / 'sample.h5'
        write_hdf5(sample, destination, {'purpose': config.purpose, 'solver_readiness_assessed': False})
        read_hdf5(destination)
        check_integrity()
        receipt['artifacts']['sample.h5'] = dict(sha256=sha256_file(destination), bytes=destination.stat().st_size)
        receipt['status'] = 'completed'
    except (Exception, KeyboardInterrupt) as exc:
        receipt.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                       error_type=type(exc).__name__, error=str(exc),
                       diagnostics=diagnostics_for(exc, file=config_path, stage='normalize-sample'))
    receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
    persist()
    return receipt
