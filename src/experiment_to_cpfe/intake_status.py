"""Reviewed handoff checkpoints with explicit metadata and evidence bindings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat


CHECKPOINTS = {
    'raw_to_semantics': 'Raw files to explicit semantics',
    'semantics_to_sample_package': 'Semantics to SamplePackage',
    'sample_package_to_solver': 'SamplePackage to solver preparation',
    'solver_to_numerical_validation': 'Solver preparation to numerical validation',
    'simulation_training_to_experimental_evaluation': 'Simulation/training to experimental evaluation',
    'experimental_evaluation_to_applicability': 'Experimental evaluation to applicability',
}
STATUSES = ('ready', 'conditional', 'awaiting_information', 'not_applicable')
_SCOPES = ('synthetic_mechanism_only', 'simulation_only', 'experimental')
_MAX_FILE_BYTES = 1024 * 1024
_MAX_TOTAL_EVIDENCE_BYTES = 16 * 1024 * 1024
_METADATA_SUFFIXES = {'.json', '.txt', '.md', '.csv', '.tsv'}


def _fields(value, required, optional=(), *, where):
    if not isinstance(value, dict):
        raise ValueError(f'{where} must be an object')
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing or unknown:
        raise ValueError(f'{where}: missing fields {sorted(missing)}, unknown fields {sorted(unknown)}')


def _text(value, where):
    if not isinstance(value, str) or not value.strip() or '\x00' in value or len(value) > 4096:
        raise ValueError(f'{where} must be a nonempty string of at most 4096 characters')


def _text_list(value, where):
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError(f'{where} must be a list of at most 64 entries')
    for item in value:
        _text(item, where)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f'duplicate JSON field: {key}')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f'nonfinite JSON value: {value}')


def _read_metadata(path: Path, *, maximum=_MAX_FILE_BYTES):
    """Read a bounded regular file once, so size and hash describe the same bytes."""
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f'metadata must be a regular file: {path}')
        if info.st_size > maximum:
            raise ValueError(f'metadata exceeds byte limit {maximum}: {path}')
        with path.open('rb') as stream:
            payload = stream.read(maximum + 1)
        if len(payload) > maximum:
            raise ValueError(f'metadata exceeds byte limit {maximum}: {path}')
        payload.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise ValueError(f'metadata is missing or is not readable UTF-8: {path}') from exc
    return payload


def _review(item):
    _fields(item, ('id', 'status', 'reviewer', 'basis', 'conditions', 'blockers', 'evidence'),
            ('not_applicable_reason',), where='checkpoint')
    for field in ('id', 'status', 'reviewer', 'basis'):
        _text(item[field], f'checkpoint {field}')
    if item['id'] not in CHECKPOINTS:
        raise ValueError(f'unknown checkpoint id: {item["id"]}')
    if item['status'] not in STATUSES:
        raise ValueError(f'unknown checkpoint status: {item["status"]}')
    for field in ('conditions', 'blockers'):
        _text_list(item[field], f'checkpoint {field}')
    evidence = item['evidence']
    if not isinstance(evidence, list) or len(evidence) > 32:
        raise ValueError('checkpoint evidence must be a list of at most 32 explicit files')
    status = item['status']
    if status == 'ready' and (not evidence or item['conditions'] or item['blockers']):
        raise ValueError('ready requires evidence and no unresolved conditions or blockers')
    if status == 'conditional' and not item['conditions']:
        raise ValueError('conditional requires explicit conditions')
    if status == 'awaiting_information' and not item['blockers']:
        raise ValueError('awaiting_information requires blockers describing missing information')
    if status == 'not_applicable':
        _text(item.get('not_applicable_reason'), 'not_applicable_reason')
        if item['conditions'] or item['blockers']:
            raise ValueError('not_applicable cannot have unresolved conditions or blockers')
    elif 'not_applicable_reason' in item:
        raise ValueError('not_applicable_reason is only valid for not_applicable')


def _prepare(config_path):
    source = Path(config_path).absolute()
    raw = _read_metadata(source)
    try:
        config = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('intake config must be a finite JSON object') from exc
    _fields(config, ('version', 'handoff_id', 'purpose', 'evidence_scope', 'checkpoints'), where='intake config')
    if type(config['version']) is not int or config['version'] != 1:
        raise ValueError('intake version must be integer 1')
    for field in ('handoff_id', 'purpose', 'evidence_scope'):
        _text(config[field], field)
    if config['evidence_scope'] not in _SCOPES:
        raise ValueError('evidence_scope must explicitly identify synthetic, simulation or experimental evidence')
    items = config['checkpoints']
    if not isinstance(items, list) or not 1 <= len(items) <= len(CHECKPOINTS):
        raise ValueError('select between one and six checkpoints')
    seen = set()
    for item in items:
        _review(item)
        if item['id'] in seen:
            raise ValueError(f'duplicate checkpoint: {item["id"]}')
        seen.add(item['id'])

    total_bytes = 0
    for item in items:
        bindings = []
        for evidence in item['evidence']:
            _fields(evidence, ('path', 'sha256'), where='evidence')
            _text(evidence['path'], 'evidence path')
            sha = evidence['sha256']
            if not isinstance(sha, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', sha):
                raise ValueError('evidence SHA256 must contain exactly 64 hexadecimal characters')
            path = Path(evidence['path'])
            path = (source.parent / path).resolve() if not path.is_absolute() else path.resolve()
            if path.suffix.lower() not in _METADATA_SUFFIXES:
                raise ValueError('evidence must be a .json, .txt, .md, .csv or .tsv metadata file')
            payload = _read_metadata(path, maximum=min(_MAX_FILE_BYTES, _MAX_TOTAL_EVIDENCE_BYTES - total_bytes))
            actual = hashlib.sha256(payload).hexdigest()
            if actual != sha.lower():
                raise ValueError(f'evidence SHA256 mismatch: {path}')
            total_bytes += len(payload)
            bindings.append({'path': str(path), 'sha256': actual, 'size_bytes': len(payload)})
        item['evidence'] = bindings
    return config, {'path': str(source.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}


def validate_intake_status_config(config_path: str | Path) -> dict:
    """Validate a JSON config and its explicit evidence without producing output.

    The returned copy resolves evidence paths and includes their measured sizes.
    Configuration and evidence errors are reported as ValueError.
    """
    config, _ = _prepare(config_path)
    return config


def _report_text(report):
    lines = ['# Experimental handoff status', '', f'Handoff: {report["handoff_id"]}', '',
             f'Purpose: {report["purpose"]}', '', f'Declared evidence scope: {report["evidence_scope"]}', '',
             'Selected checkpoints retain their reviewer, basis, conditions and evidence receipts.', '',
             'File digests record the byte integrity of submitted evidence.', '',
             'Status counts: ' + ', '.join(f'{name}={count}' for name, count in report['status_counts'].items()), '']
    for item in report['checkpoints']:
        lines.extend([f'## {item["label"]}', '', f'Status: {item["status"]}', '',
                      f'Reviewer: {item["reviewer"]}', '', f'Basis: {item["basis"]}', '',
                      f'Evidence integrity: {item["evidence_integrity"]}', ''])
        if item.get('not_applicable_reason'):
            lines.extend([f'Applicability basis: {item["not_applicable_reason"]}', ''])
        for field, title in (('conditions', 'Condition'), ('blockers', 'Open requirement')):
            for text in item[field]:
                lines.extend([f'- {title}：{text}', ''])
        for evidence in item['evidence']:
            lines.extend([f'- Evidence: `{evidence["path"]}`; {evidence["size_bytes"]} bytes; '
                          f'SHA256 `{evidence["sha256"]}`', ''])
    lines.extend([f'Source configuration: `{report["source_config"]["path"]}`', '',
                  f'Source configuration SHA256: `{report["source_config"]["sha256"]}`', ''])
    return '\n'.join(lines)


def run_intake_status(config_path: str | Path, run_dir: str | Path) -> dict:
    """Create a handoff report preserving each selected checkpoint's status."""
    output = Path(run_dir).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError(f'intake output directory already exists: {output}')
    config, source = _prepare(config_path)
    items = [{**item, 'label': CHECKPOINTS[item['id']],
              'evidence_integrity': 'verified' if item['evidence'] else 'not_provided'}
             for item in config['checkpoints']]
    counts = {status: sum(item['status'] == status for item in items) for status in STATUSES}
    report = {**config, 'report_type': 'intake_status', 'processing_status': 'completed',
              'source_config': source, 'checkpoints': items,
              'selected_checkpoint_count': len(items), 'status_counts': counts,
              'all_selected_checkpoints_ready': counts['ready'] == len(items),
              'unselected_checkpoints_assessed': False,
              'scientific_validity': 'not_assessed', 'downstream_execution': 'not_started'}
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError(f'intake output directory already exists: {output}') from exc
    with (output / 'intake-status.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    with (output / 'REPORT.md').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(_report_text(report))
    return report
