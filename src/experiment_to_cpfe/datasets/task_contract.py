"""Task-specific availability and observable semantics over existing SamplePackages.

These checks assess supplied declarations, never infer physical state from arrays.
"""
import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from experiment_to_cpfe.datasets.training_config import Contract, Declared, Finite
from experiment_to_cpfe.datasets.experiment_context import CONTEXT_FIELDS, FieldEvidence


class TimePoint(Contract):
    value: Finite
    unit: Declared
    reference: Declared


class TimeWindow(Contract):
    start: Finite
    stop: Finite
    unit: Declared
    reference: Declared

    @model_validator(mode='after')
    def ordered(self):
        if self.stop < self.start:
            raise ValueError('time window stop precedes start')
        return self


class InputAvailability(Contract):
    source: Declared
    role: Literal['predictor', 'label_only', 'target_derived', 'future_response']
    availability: Literal['confirmed', 'unconfirmed', 'unavailable']
    available_at: Finite | None = None
    evidence: Declared


class Observable(Contract):
    quantity: Declared
    unit: Declared
    entity: Declared
    spatial_support: Declared
    coordinate_frame: Declared
    component_convention: Declared
    time_window: TimeWindow
    basis: Declared

    def semantics(self):
        return self.model_dump(mode='json', exclude={'basis'})


class TaskContract(Contract):
    version: Literal[1]
    purpose: Declared
    data_kind: Literal['synthetic', 'simulation', 'experiment', 'mixed']
    prediction_time: TimePoint
    inputs: dict[Declared, InputAvailability] = Field(min_length=1)
    targets: dict[Declared, Observable] = Field(min_length=1)
    context_requirements: dict[Declared, list[Literal['confirmed', 'not_applicable']]]
    independence_axes: dict[Declared, Declared] = Field(min_length=1)

    @model_validator(mode='after')
    def usable_inputs(self):
        if set(self.inputs) & set(self.targets):
            raise ValueError('input and target names overlap')
        for name, item in self.inputs.items():
            if item.role != 'predictor':
                raise ValueError(f'input role for {name!r} is {item.role}, not a predictor')
            if item.availability == 'unavailable':
                raise ValueError(f'unavailable input {name!r}')
            if item.available_at is not None and item.available_at > self.prediction_time.value:
                raise ValueError(f'input {name!r} is only available after prediction time')
            if item.availability == 'confirmed' and item.available_at is None:
                raise ValueError(f'confirmed input {name!r} needs an available_at time')
        for name, states in self.context_requirements.items():
            if name not in CONTEXT_FIELDS or not states or len(set(states)) != len(states):
                raise ValueError(f'invalid task context requirement {name!r}')
        if any(not pointer.startswith('/') for pointer in self.independence_axes.values()):
            raise ValueError('independence axes require absolute JSON pointers')
        return self


def task_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def validate_task(value, features=None, targets=None):
    if value is None:
        return None
    task = TaskContract.model_validate(value)
    for supplied, declared, label in ((features, task.inputs, 'feature'), (targets, task.targets, 'target')):
        if supplied is not None:
            quantities = [q.model_dump() if hasattr(q, 'model_dump') else q for q in supplied]
            if {q['name'] for q in quantities} != set(declared):
                raise ValueError(f'task {label} names differ from selected quantities')
            if label == 'target' and any(q['unit'] != declared[q['name']].unit for q in quantities):
                raise ValueError('task target unit differs from selected target unit')
    return task.model_dump(mode='json')


def check_input_assets(sample, asset_ids):
    assets = {a.asset_id: a for a in sample.assets}
    for asset_id in set(asset_ids):
        asset = assets[asset_id]
        while True:
            if asset.descriptive_metadata.get('meaning', {}).get('role') in (
                    'target', 'label_only', 'target_derived', 'future_response'):
                raise ValueError(f'target asset or target-derived ancestor selected as input: {asset_id!r}')
            if asset.parent_asset_id is None:
                break
            asset = assets[asset.parent_asset_id]


def _axis_value(source, pointer):
    from experiment_to_cpfe.evaluation_protocol import _pointer
    value = _pointer(source, pointer)
    # Resolve specimen/batch identities from confirmed context declarations.
    parent = _pointer(source, pointer.rsplit('/', 1)[0]) if pointer.count('/') > 1 else source
    if isinstance(parent, dict) and 'status' in parent and parent['status'] != 'confirmed':
        raise ValueError(f'independence axis has unconfirmed identity: {pointer}')
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError(f'independence axis requires a scalar identity: {pointer}')
    return str(value)


def assess_task(value, features, targets, sources):
    """Validate selected source lineage and return a declaration-only readiness report."""
    value = validate_task(value, features, targets)
    if value is None:
        return dict(status='legacy_unassessed', physical_validity='not_established')
    task = TaskContract.model_validate(value)
    owners, roots, gaps, identities = {}, {}, [], []
    for source in sources:
        group, role = source['group'], source.get('split', 'inference')
        sample_id = source['sample_metadata']['sample_id']
        axes = {}
        for axis, pointer in task.independence_axes.items():
            identity = _axis_value(source, pointer)
            axes[axis] = identity
            previous = owners.setdefault((axis, identity), (group, role))
            if previous != (group, role):
                raise ValueError(f'independence axis {axis!r} reused across groups or roles: {identity!r}')
        assets = {a['asset_id']: a for a in source['assets']}
        selected_roots = set()
        for column in source['columns'].values():
            for asset_id in set(column['asset_ids']):
                asset = assets[asset_id]
                while asset.get('parent_asset_id') is not None:
                    asset = assets[asset['parent_asset_id']]
                selected_roots.add(asset['asset_id'])
        root_tokens = set()
        for asset_id in selected_roots:
            asset = assets[asset_id]
            tokens = ['uri:' + asset['uri']]
            if asset.get('sha256'):
                tokens.append('sha256:' + asset['sha256'].lower())
            for token in tokens:
                previous = roots.setdefault(token, (group, role))
                if previous != (group, role):
                    raise ValueError('selected root source reused across independent groups or roles')
                root_tokens.add(token)
        context = source['solver_inputs'].get('experiment_context', {}).get('fields', {})
        preprocessing = context.get('preprocessing')
        if preprocessing is not None:
            field = FieldEvidence.model_validate(preprocessing)
            if field.value is not None:
                if not isinstance(field.value, list):
                    raise ValueError('preprocessing must list original operations with operation and basis')
                for operation in field.value:
                    if (not isinstance(operation, dict) or
                            any(not isinstance(operation.get(key), str) or not operation[key].strip()
                                for key in ('operation', 'basis'))):
                        raise ValueError('preprocessing operation and basis are required')
                    fit_role = operation.get('fit_role', 'unconfirmed')
                    if fit_role not in ('train', 'not_fitted', 'unconfirmed', 'unavailable'):
                        raise ValueError('fitted preprocessing must use train only')
                    if fit_role in ('unconfirmed', 'unavailable'):
                        gaps.append(dict(sample_id=sample_id, field='preprocessing.fit_role', status=fit_role,
                            evidence=operation['basis'], accepted_statuses=['train', 'not_fitted']))
        for name, acceptable in task.context_requirements.items():
            raw = context.get(name, dict(status='unavailable', evidence='not supplied'))
            field = FieldEvidence.model_validate(raw)
            if field.status not in acceptable:
                gaps.append(dict(sample_id=sample_id, field=name, status=field.status,
                    evidence=field.evidence, accepted_statuses=acceptable))
        identities.append(dict(sample_id=sample_id, group=group, role=role, axes=axes,
            selected_root_sources=sorted(root_tokens)))
    unknown = [name for name, item in task.inputs.items() if item.availability == 'unconfirmed']
    counts = {role: len({s['group'] for s in sources if s.get('split', 'inference') == role})
              for role in sorted({s.get('split', 'inference') for s in sources})}
    return dict(status='conditional' if unknown or gaps else 'declared_ready',
        contract_sha256=task_digest(value), unconfirmed_inputs=unknown, context_gaps=gaps,
        identities=identities, declared_group_counts=counts,
        small_group_roles=[role for role, count in counts.items() if count < 2],
        independent_group_interpretation='declared identities only; physical independence not established',
        physical_validity='not_established')
