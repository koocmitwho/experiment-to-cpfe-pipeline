"""Frozen tabular prediction and explicit identity-aligned evaluation."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import yaml

from experiment_to_cpfe.assets.registry import array_payload_sha256
from experiment_to_cpfe.datasets.prediction import InferenceConfig, EvaluationConfig, select_named, selector_identity
from experiment_to_cpfe.datasets.training_sources import TargetSourceIndex as _TargetSourceIndex, register_recorded_targets
from experiment_to_cpfe.learning.templates import bind_task
from experiment_to_cpfe.datasets.task_contract import assess_task
from experiment_to_cpfe.mechanics.tensile import regression_metrics
from experiment_to_cpfe.provenance.hashing import sha256_file
from experiment_to_cpfe.diagnostics import DiagnosticError, diagnostics_for


def write_record(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _declarations(saved):
    from experiment_to_cpfe.datasets.training_config import Quantity
    if saved.get('vector_output', False) or saved.get('architecture','mlp') not in ('mlp','linear'):
        raise ValueError('public inference supports scalar MLP/linear checkpoints only')
    features = [Quantity(name=n, unit=u).model_dump() for n, u in zip(saved['feature_names'], saved['feature_units'], strict=True)]
    vector = saved.get('vector_output', False)
    names = saved['target_names'] if vector else [saved['target_name']]
    units = saved['target_units'] if vector else [saved['target_unit']]
    targets = [Quantity(name=n, unit=u).model_dump() for n, u in zip(names, units, strict=True)]
    if (not features or len(features) != saved['input_width'] or not targets
            or len(targets) != saved.get('output_width', 1)
            or len({q['name'] for q in features + targets}) != len(features + targets)):
        raise ValueError('invalid or overlapping checkpoint feature/target declarations')
    for key, size in (('x_mean', len(features)), ('x_scale', len(features)), ('y_mean', len(targets)), ('y_scale', len(targets))):
        value = np.asarray(saved[key])
        if value.size != size or not np.isfinite(value).all() or (key.endswith('scale') and (value <= 0).any()):
            raise ValueError(f'invalid checkpoint normalization {key}')
    if saved.get('architecture', 'mlp') not in ('mlp', 'linear'):
        raise ValueError('unsupported checkpoint architecture')
    return features, targets


def _write_npz(path, arrays, metadata):
    metadata = dict(metadata, payload_hashes={k: array_payload_sha256(v) for k, v in arrays.items()})
    encoded = _json(metadata)
    with path.open('xb') as stream:
        np.savez_compressed(stream, **arrays, __metadata_json__=np.asarray(encoded),
                            __metadata_sha256__=np.asarray(hashlib.sha256(encoded.encode()).hexdigest()))
    # Verify actual exported bytes before declaring the run completed.
    with np.load(path, allow_pickle=False) as data:
        for key, expected in metadata['payload_hashes'].items():
            if array_payload_sha256(data[key]) != expected:
                raise ValueError(f'export readback mismatch: {key}')
    return dict(path=path.name, sha256=sha256_file(path), size_bytes=path.stat().st_size)


def _predict(config, base, output, receipt):
    import torch
    from experiment_to_cpfe.learning.surrogate import predict_mlp
    checkpoint = (base / config.checkpoint).resolve()
    digest = sha256_file(checkpoint)
    if config.checkpoint_sha256 is not None and config.checkpoint_sha256 != digest:
        raise ValueError('checkpoint hash differs from configuration')
    saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
    features, targets = _declarations(saved)
    if [q.model_dump() for q in config.features] != features:
        raise ValueError('feature order, names, units or width disagree with checkpoint')
    identity = saved.get('training_identity')
    metadata = ((identity or {}).get('data_identity') or {}).get('metadata')
    task = bind_task(metadata, config.task_contract, features, targets)
    forbidden = []
    if metadata is not None:
        if metadata['config']['group_by'] != config.group_by:
            raise ValueError('group_by differs from training provenance')
        for source in metadata['sources']:
            forbidden.extend(selector_identity(source['columns'][q['name']]['selector']) for q in targets)
    data = select_named(config, base_dir=base, forbidden_names=[q['name'] for q in targets], forbidden_selectors=forbidden)
    assessment = assess_task(task, features, targets, ((metadata or {}).get('sources', []) + data.sources))
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        prediction = np.asarray(predict_mlp(checkpoint, data.values, feature_names=[q['name'] for q in features],
                                           feature_units=[q['unit'] for q in features])).reshape(len(data.values), -1)
    finally:
        torch.set_num_threads(previous_threads)
    if prediction.shape != (len(data.values), len(targets)) or not np.isfinite(prediction).all():
        raise ValueError('prediction must be finite and match row/target dimensions')
    if sha256_file(checkpoint) != digest:
        raise ValueError('checkpoint changed during inference')
    model = dict(path=str(checkpoint), sha256=digest, architecture=saved.get('architecture', 'mlp'),
                 features=features, targets=targets, training_identity=identity,
                 normalization={key: np.asarray(saved[key]).tolist() for key in ('x_mean', 'x_scale', 'y_mean', 'y_scale')})
    metadata = dict(format='experiment-to-cpfe-prediction-1', model=model, features=features, targets=targets,
                    config=receipt['config'], sources=data.sources, group_by=config.group_by,
                    grouping_evidence=config.grouping_evidence, device='cpu', threads=1,
                    input_access='complete explicitly listed HDF5 packages', normalization_refitted=False)
    metadata.update(task_contract=task, task_assessment=assessment)
    arrays = dict(prediction=prediction, features=data.values, sample_ids=data.sample_ids,
                  row_ids=data.row_ids, groups=data.groups,
                  target_names=np.asarray([q['name'] for q in targets]), target_units=np.asarray([q['unit'] for q in targets]))
    artifact = _write_npz(output / 'predictions.npz', arrays, metadata)
    report = dict(config=receipt['config'], model=model, targets=targets, rows=len(prediction), sources=data.sources,
                task_contract=task, task_assessment=assessment,
                device='cpu', threads=1, normalization_refitted=False, artifacts={'predictions.npz': artifact})
    from experiment_to_cpfe.learning.user_reports import write_user_delivery
    report['artifacts'].update(write_user_delivery(output, arrays, report))
    return report


def read_predictions(path, expected_hash=None):
    """Check completion receipt and every payload; never reopen training or model files."""
    path = Path(path).resolve()
    digest = sha256_file(path)
    receipt = json.loads((path.parent / 'inference.json').read_text(encoding='utf-8'))
    if (receipt['status'] != 'completed' or receipt['artifacts'][path.name]['sha256'] != digest
            or (expected_hash is not None and digest != expected_hash)):
        raise ValueError('prediction artifact hash/completion receipt mismatch')
    with np.load(path, allow_pickle=False) as data:
        text = data['__metadata_json__'].item()
        if hashlib.sha256(text.encode()).hexdigest() != data['__metadata_sha256__'].item():
            raise ValueError('prediction metadata digest mismatch')
        metadata = json.loads(text)
        if metadata['format'] != 'experiment-to-cpfe-prediction-1':
            raise ValueError('unsupported prediction format')
        keys = {'prediction', 'features', 'sample_ids', 'row_ids', 'groups', 'target_names', 'target_units'}
        if set(metadata['payload_hashes']) != keys or set(data.files) != keys | {'__metadata_json__', '__metadata_sha256__'}:
            raise ValueError('prediction payload fields disagree with format')
        arrays = {k: data[k] for k in keys}
        for key, array in arrays.items():
            if array_payload_sha256(array) != metadata['payload_hashes'][key]:
                raise ValueError(f'prediction payload hash mismatch: {key}')
    n = len(arrays['prediction'])
    if (arrays['prediction'].shape != (n, len(metadata['targets'])) or not n
            or not np.isfinite(arrays['prediction']).all()
            or any(arrays[k].shape != (n,) for k in ('sample_ids', 'row_ids', 'groups'))
            or len(set(zip(arrays['sample_ids'], arrays['row_ids']))) != n):
        raise ValueError('invalid prediction shape or row identities')
    if sha256_file(path) != digest:
        raise ValueError('prediction artifact changed during reading')
    return arrays, metadata, digest


def _register_source(source, targets, split, index):
    declared = source['solver_inputs'].get('dataset_split')
    if declared is not None and declared != split:
        raise ValueError('target dataset_split conflicts with evaluation split')
    register_recorded_targets(source, targets, split, index)


def _evaluate(config, base, output, receipt):
    prediction_path = (base / config.predictions).resolve()
    arrays, metadata, digest = read_predictions(prediction_path, config.predictions_sha256)
    targets = [q.model_dump() for q in config.targets]
    if targets != metadata['targets']:
        raise ValueError('target order, names, units or width disagree with predictions')
    if config.group_by != metadata['group_by']:
        raise ValueError('group_by disagrees with inference')
    identity = metadata['model']['training_identity']
    training_metadata = ((identity or {}).get('data_identity') or {}).get('metadata')
    task = bind_task(training_metadata, config.task_contract, metadata['features'], targets)
    if task != metadata.get('task_contract'):
        raise ValueError('evaluation task contract disagrees with frozen predictions')
    truth = select_named(config, base_dir=base)
    truth_sources = [dict(s, split=config.split) for s in truth.sources]
    assessment = assess_task(task, metadata['features'], targets, ((training_metadata or {}).get('sources', []) + truth_sources))
    pkeys = list(zip(arrays['sample_ids'].tolist(), arrays['row_ids'].tolist()))
    tkeys = list(zip(truth.sample_ids.tolist(), truth.row_ids.tolist()))
    if set(pkeys) != set(tkeys) or len(tkeys) != len(set(tkeys)):
        raise ValueError('truth sample/row identity alignment differs from predictions')
    order = {key: i for i, key in enumerate(tkeys)}
    positions = [order[key] for key in pkeys]
    if not np.array_equal(arrays['groups'], truth.groups[positions]):
        raise ValueError('truth group identities disagree with predictions')
    predicted_sources = {s['sample_metadata']['sample_id']: s for s in metadata['sources']}
    for source in truth.sources:
        previous = predicted_sources[source['sample_metadata']['sample_id']]
        # Input and truth assets have distinct provenance by design. Compare
        # specimen/convention metadata, retaining both source lists separately.
        actual_identity = {k: v for k, v in source['sample_metadata'].items() if k != 'sources'}
        expected_identity = {k: v for k, v in previous['sample_metadata'].items() if k != 'sources'}
        if actual_identity != expected_identity:
            raise ValueError('truth sample metadata disagrees with inference identity/conventions')
    index = _TargetSourceIndex()
    identity = metadata['model']['training_identity']
    training_metadata = ((identity or {}).get('data_identity') or {}).get('metadata')
    check = 'unavailable_legacy_checkpoint' if identity is None else 'groups_only_no_training_source_identity'
    if identity is not None:
        for group in truth.groups:
            previous = identity['group_splits'].get(group)
            if previous is not None and previous != config.split:
                raise ValueError(f'training group {group!r} reused across splits')
    if training_metadata is not None:
        if config.group_by != training_metadata['config']['group_by']:
            raise ValueError('group_by differs from training provenance')
        for source in training_metadata['sources']:
            if source['sample_metadata']['sample_id'] in truth.sample_ids and source['split'] != config.split:
                raise ValueError('training sample identity reused across splits')
            _register_source(source, targets, source['split'], index)
        check = 'verified'
    for source in truth.sources:
        _register_source(source, targets, config.split, index)
    y = truth.values[positions]
    prediction = arrays['prediction']
    def metrics(mask):
        return {q['name']: regression_metrics(y[mask, i], prediction[mask, i]) for i, q in enumerate(targets)}
    report = dict(config=receipt['config'], predictions=dict(path=str(prediction_path), sha256=digest), model=metadata['model'],
        targets=targets, split=config.split, rows=len(y), sources=truth.sources, training_overlap_check=check,
        normalization_refitted=False, metrics=metrics(np.ones(len(y), dtype=bool)),
        by_sample={name: metrics(arrays['sample_ids'] == name) for name in sorted(set(arrays['sample_ids']))},
        by_group={name: metrics(arrays['groups'] == name) for name in sorted(set(arrays['groups']))})
    report.update(task_contract=task, task_assessment=assessment)
    artifact = _write_npz(output / 'evaluation.npz', dict(arrays, targets=y), dict(format='experiment-to-cpfe-evaluation-1',
        predictions=report['predictions'], config=receipt['config'], targets=targets, sources=truth.sources))
    report['artifacts'] = {'evaluation.npz': artifact}
    from experiment_to_cpfe.learning.user_reports import write_user_delivery
    report['artifacts'].update(write_user_delivery(output, dict(arrays, targets=y), report, evaluated=True))
    return report


def _run(config_path, output_dir, stage, contract, operation):
    path, output = Path(config_path).resolve(), Path(output_dir).resolve()
    # Refuse reuse before writing any status, including failed run directories.
    output.mkdir(parents=True, exist_ok=False)
    receipt = dict(status='running', stage=stage, started_at=datetime.now(timezone.utc).isoformat(), config={'path': str(path)})
    record = output / (stage + '.json')
    try:
        write_record(record, receipt)
        raw = path.read_bytes()
        receipt['config'].update(sha256=hashlib.sha256(raw).hexdigest())
        config = contract.model_validate(yaml.safe_load(raw.decode('utf-8')))
        receipt['config']['resolved'] = config.model_dump(mode='json')
        result = operation(config, path.parent, output, receipt)
        if sha256_file(path) != receipt['config']['sha256']:
            raise ValueError('configuration changed during execution')
        markdown = result.pop('_report_markdown', None)
        if markdown is not None:
            report_path = output/'REPORT.md'
            report_path.write_text(markdown, encoding='utf-8')
            result['artifacts']['REPORT.md'] = dict(path='REPORT.md', sha256=sha256_file(report_path), size_bytes=report_path.stat().st_size)
        receipt.update(result, status='completed', completed_at=datetime.now(timezone.utc).isoformat())
        write_record(record, receipt)
    except (Exception, KeyboardInterrupt) as exc:
        # Do not leave completed-looking metrics after prediction/export/report failure.
        failure = {k: receipt[k] for k in ('stage', 'started_at', 'config')}
        issues = diagnostics_for(exc, file=path, stage=stage)
        failure.update(status='failed', error={'type': type(exc).__name__, 'message': str(exc)}, diagnostics=issues)
        try:
            write_record(record, failure)
            (output/'SUMMARY.md').write_text(
                f'# 工程失败\n\n本次执行未完成，结果不能作为已完成输出使用。\n\n'
                f'原因见 `{record.name}` 的失败收据；修正配置后使用新的运行目录。\n', encoding='utf-8')
            if (output/'user-delivery.json').exists():
                write_record(output/'user-delivery.json', dict(status='failed', stage=stage,
                    reason=str(exc), receipt=record.name))
            if (output/'REPORT.md').exists():
                (output/'REPORT.md').write_text('# 工程失败\n\n本次执行未完成，详见 evaluation.json 或 inference.json 的失败收据。\n', encoding='utf-8')
        except OSError:
            pass  # The original error is still returned if the filesystem cannot write a receipt.
        raise DiagnosticError(issues) from exc
    return dict(status='completed', report=str(record), **{k: str(output / k) for k in receipt['artifacts']})


def run_inference(config_path, output_dir):
    return _run(config_path, output_dir, 'inference', InferenceConfig, _predict)


def run_evaluation(config_path, output_dir):
    return _run(config_path, output_dir, 'evaluation', EvaluationConfig, _evaluate)
