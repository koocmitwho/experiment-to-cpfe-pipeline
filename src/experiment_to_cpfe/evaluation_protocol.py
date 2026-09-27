"""Bounded identity/metric audit; never loads models, responses, or receipt links."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from experiment_to_cpfe.datasets.training_config import Contract, Declared, Finite, Split
from experiment_to_cpfe.learning.data_contract import validate_group_splits


class EvidenceFile(Contract):
    path: Declared
    sha256: Declared = Field(pattern=r'^[a-f0-9]{64}$')
    purpose: Declared


class Threshold(Contract):
    operator: Literal['le', 'lt', 'ge', 'gt']
    value: Finite
    unit: Declared


class SavedMetric(Contract):
    metric_id: Declared
    path: Declared
    sha256: Declared = Field(pattern=r'^[a-f0-9]{64}$')
    value_pointer: Declared
    unit_pointer: Declared
    unit: Declared
    split: Split
    threshold: Threshold | None = None


class ConditionEntry(Contract):
    case_id: Declared
    identity: dict[Declared, Declared] = Field(min_length=1)
    group_id: Declared
    split: Split
    axes: dict[Declared, Declared] = Field(default_factory=dict)
    records: list[Declared]

    @model_validator(mode='after')
    def unique_records(self):
        if len(self.records) != len(set(self.records)):
            raise ValueError('duplicate expanded records within one condition entry')
        return self


class EvaluationProtocolConfig(Contract):
    version: Literal[1]
    purpose: Declared
    claim: Declared
    population: Declared
    data_kind: Literal['synthetic', 'simulation', 'experiment', 'mixed']
    declaration_timing: Literal['retrospective', 'preregistered_claim']
    registration_evidence: EvidenceFile | None = None
    identity_definition: Declared
    group_definition: Declared
    record_unit: Declared
    holdout_axes: list[Declared]
    scope_limits: list[Declared] = Field(min_length=1)
    cases: list[ConditionEntry] = Field(min_length=1)
    metrics: list[SavedMetric] = Field(default_factory=list)
    sources: list[EvidenceFile] = Field(default_factory=list)

    @model_validator(mode='after')
    def explicit_declarations(self):
        if len(set(self.holdout_axes)) != len(self.holdout_axes):
            raise ValueError('duplicate holdout axis')
        if len({m.metric_id for m in self.metrics}) != len(self.metrics):
            raise ValueError('duplicate metric identity')
        if self.declaration_timing == 'preregistered_claim' and self.registration_evidence is None:
            raise ValueError('preregistered claim requires explicit registration evidence')
        if self.declaration_timing == 'retrospective' and self.registration_evidence is not None:
            raise ValueError('retrospective report cannot attach a preregistration claim')
        return self


def _read_json(path: Path, expected_hash: str | None = None):
    """Read one explicit regular JSON file, with a 32 MiB bound, without links."""
    path = path.resolve()
    if path.suffix.lower() != '.json' or not path.is_file():
        raise ValueError(f'an explicit JSON file is required: {path}')
    with path.open('rb') as stream:
        raw = stream.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError(f'JSON evidence exceeds 32 MiB bound: {path}')
    digest = hashlib.sha256(raw).hexdigest()
    if expected_hash is not None and digest != expected_hash:
        raise ValueError(f'evidence SHA256 mismatch: {path}')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result

    try:
        data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f'invalid JSON evidence: {path}') from exc
    return data, {'path': str(path), 'sha256': digest, 'bytes': len(raw)}


def _resolve(base: Path, path: str) -> Path:
    value = Path(path)
    return (value if value.is_absolute() else base / value).resolve()


def _pointer(document, pointer: str):
    if not pointer.startswith('/'):
        raise ValueError('metric value/unit position must be an absolute JSON pointer')
    current = document
    try:
        for raw in pointer[1:].split('/'):
            token = raw.replace('~1', '/').replace('~0', '~')
            if isinstance(current, list):
                if not token.isdigit() or (len(token) > 1 and token.startswith('0')):
                    raise ValueError('invalid JSON array index')
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                raise ValueError('JSON pointer traverses a scalar')
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f'metric JSON pointer not found: {pointer}') from exc
    return current


def _conditions(config: EvaluationProtocolConfig):
    conditions, names = {}, {}
    identity_keys = set(config.cases[0].identity)
    for entry in config.cases:
        if set(entry.identity) != identity_keys:
            raise ValueError('all conditions require the same declared identity key set')
        key = json.dumps(entry.identity, sort_keys=True, ensure_ascii=False)
        if entry.case_id in names:
            raise ValueError(f'duplicate or conflicting case name: {entry.case_id}')
        names[entry.case_id] = key
        previous = conditions.get(key)
        if previous is None:
            conditions[key] = {'identity': entry.identity, 'group_id': entry.group_id,
                               'split': entry.split, 'axes': entry.axes,
                               'aliases': [entry.case_id], 'records': set(entry.records)}
        else:
            if any(previous[k] != getattr(entry, k) for k in ('group_id', 'split', 'axes')):
                raise ValueError('same condition identity has conflicting group, split, or axes')
            previous['aliases'].append(entry.case_id)
            previous['records'].update(entry.records)
    if any(not item['records'] for item in conditions.values()):
        raise ValueError('each unique condition requires at least one expanded record')
    # Reuse the training contract for named groups and split leakage/minimum records.
    groups, splits = [], []
    for item in conditions.values():
        groups.extend([item['group_id']] * len(item['records']))
        splits.extend([item['split']] * len(item['records']))
    validate_group_splits(groups, splits)
    return list(conditions.values())


def _counts(conditions):
    return {'unique_conditions': len(conditions),
            'statistical_groups': len({item['group_id'] for item in conditions}),
            'expanded_records': sum(len(item['records']) for item in conditions)}


def _axes(config, conditions):
    result = {}
    for axis in config.holdout_axes:
        missing = [item['aliases'][0] for item in conditions if axis not in item['axes']]
        by_split = {split: sorted({item['axes'][axis] for item in conditions
                                  if item['split'] == split and axis in item['axes']})
                    for split in sorted({item['split'] for item in conditions})}
        train = set(by_split.get('train', []))
        evaluation = {v for split, values in by_split.items() if split != 'train' for v in values}
        overlap = sorted(train & evaluation)
        if missing:
            reason = 'axis values are missing for one or more unique conditions'
        elif len(train | evaluation) < 2:
            reason = 'axis has fewer than two distinct values'
        elif not train or not evaluation:
            reason = 'training or evaluation axis values are absent'
        elif overlap:
            reason = 'evaluation axis values overlap the training values'
        else:
            reason = 'declared evaluation axis values are disjoint from training values'
        supported = not missing and bool(train) and bool(evaluation) and not overlap
        result[axis] = {'status': 'metadata_supported' if supported else 'not_verified',
                        'reason': reason, 'values_by_split': by_split,
                        'missing_conditions': missing, 'train_evaluation_overlap': overlap}
    return result


def _inspect(config_path):
    config_path = Path(config_path).resolve()
    document, config_ref = _read_json(config_path)
    config = EvaluationProtocolConfig.model_validate(document)
    conditions = _conditions(config)
    inputs = {str(config_path): config_ref}
    cache = {}

    def read_bound(path, digest):
        resolved = _resolve(config_path.parent, path)
        key = str(resolved)
        if key not in cache:
            cache[key] = _read_json(resolved, digest)
        value, ref = cache[key]
        if ref['sha256'] != digest:
            raise ValueError('conflicting SHA256 declarations for one evidence file')
        inputs[key] = ref
        return value, ref

    sources = []
    for source in config.sources:
        _, ref = read_bound(source.path, source.sha256)
        sources.append({**ref, 'purpose': source.purpose})
    registration = None
    if config.registration_evidence is not None:
        source = config.registration_evidence
        _, ref = read_bound(source.path, source.sha256)
        registration = {**ref, 'purpose': source.purpose,
                        'timing_independently_verified': False}
    metric_evidence = []
    present_splits = {item['split'] for item in conditions}
    for metric in config.metrics:
        if metric.split not in present_splits:
            raise ValueError('metric refers to a split absent from the identity manifest')
        data, ref = read_bound(metric.path, metric.sha256)
        value = _pointer(data, metric.value_pointer)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('saved metric must be one finite numeric scalar, excluding bool')
        units = _pointer(data, metric.unit_pointer)
        units = units if isinstance(units, list) else [units]
        if not units or any(unit != metric.unit for unit in units):
            raise ValueError('metric unit disagrees with saved evidence')
        threshold_status = 'not_requested'
        if metric.threshold is not None:
            threshold = metric.threshold
            if threshold.unit != metric.unit:
                raise ValueError('threshold unit disagrees with metric unit')
            passed = {'le': value <= threshold.value, 'lt': value < threshold.value,
                      'ge': value >= threshold.value, 'gt': value > threshold.value}[threshold.operator]
            threshold_status = 'met' if passed else 'not_met'
        metric_evidence.append({**metric.model_dump(), **ref, 'value': value,
                                'threshold_status': threshold_status,
                                'split_binding': 'caller_declared; file hash and value verified'})
    axes = _axes(config, conditions)
    report = {
        'format': 'experiment-to-cpfe-evaluation-protocol-1',
        'purpose': config.purpose, 'claim': config.claim, 'population': config.population,
        'data_kind': config.data_kind, 'declaration_timing': config.declaration_timing,
        'registration_evidence': registration,
        'scientific_claim_status': 'not_established_by_metadata',
        'identity_definition': config.identity_definition, 'group_definition': config.group_definition,
        'statistical_independence_status': 'declared_grouping; physical independence not inferred',
        'counts': {'manifest_entries': len(config.cases), **_counts(conditions),
                   'record_unit': config.record_unit},
        'splits': {split: _counts([item for item in conditions if item['split'] == split])
                   for split in sorted(present_splits)},
        'holdout_axes': axes,
        'holdout_status': ('metadata_supported' if axes and all(
            item['status'] == 'metadata_supported' for item in axes.values()) else 'not_verified'),
        'metric_evidence': metric_evidence, 'source_evidence': sources,
        'source_config': config_ref, 'inputs_read': list(inputs.values()),
        'scope_limits': config.scope_limits,
        'boundary': 'This report checks explicitly supplied JSON configuration and evidence files. '
                    'It records declared condition/group counts, holdout metadata, saved metric '
                    'values and units, threshold comparisons and source-file integrity.',
    }
    return config, report


def validate_evaluation_protocol_config(config_path) -> EvaluationProtocolConfig:
    """Validate identity, split and explicit saved evidence without writing outputs."""
    return _inspect(config_path)[0]


def run_evaluation_protocol(config_path, run_dir) -> dict:
    """Audit explicit metadata and metrics into a new, exclusively created directory."""
    config, report = _inspect(config_path)
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    resolved_config = config.model_dump()
    for field in ('metrics', 'sources'):
        for item in resolved_config[field]:
            item['path'] = str(_resolve(Path(config_path).resolve().parent, item['path']))
    if resolved_config['registration_evidence'] is not None:
        item = resolved_config['registration_evidence']
        item['path'] = str(_resolve(Path(config_path).resolve().parent, item['path']))
    for filename, payload in [('config.json', resolved_config),
                              ('evaluation-protocol.json', report)]:
        with (run_dir / filename).open('x', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
    lines = ['# Evaluation protocol', '', f'Claim: {config.claim}',
             f'Population: {config.population}', f'Data: {config.data_kind}',
             f'Declaration: {config.declaration_timing}', '',
             'Assessment: declared identities, groups, holdouts and saved metric evidence.',
             f'Holdout metadata: **{report["holdout_status"]}**.', '',
             '| Scope | Unique conditions | Declared statistical groups | Expanded records |',
             '|---|---:|---:|---:|']
    for name, count in [('all', report['counts']), *report['splits'].items()]:
        lines.append(f'| {name} | {count["unique_conditions"]} | {count["statistical_groups"]} | '
                     f'{count["expanded_records"]} |')
    lines.extend(['', f'Record unit: {config.record_unit}',
                  f'Identity definition: {config.identity_definition}',
                  f'Group definition: {config.group_definition}', ''])
    for axis, item in report['holdout_axes'].items():
        lines.append(f'- {axis}: {item["status"]}; {item["reason"]}.')
    lines.extend(['', 'Saved numerical evidence:'])
    for metric in report['metric_evidence']:
        lines.append(f'- {metric["metric_id"]}: {metric["value"]} {metric["unit"]}; '
                     f'threshold {metric["threshold_status"]}; `{metric["value_pointer"]}`; '
                     f'SHA256 `{metric["sha256"]}`.')
    if not report['metric_evidence']:
        lines.append('- Metric evidence count: 0.')
    lines.extend(['', report['boundary'], '', 'Declared evaluation scope:'])
    lines.extend(f'- {value}' for value in config.scope_limits)
    lines.extend(['', 'Verified input files:'])
    lines.extend(f'- `{item["path"]}`; SHA256 `{item["sha256"]}`.' for item in report['inputs_read'])
    (run_dir / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return report
