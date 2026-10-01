"""Native specimen partitions, adapted from the public v0.2.2 source checks.

The default is the entire root file. Narrower scopes require original table
identities and verified conversion lineage; they never establish physical
independence or reopen original/held-out files during inference or evaluation.
"""
from dataclasses import dataclass, field
from types import SimpleNamespace

from experiment_to_cpfe.assets.models import AssetRef
from experiment_to_cpfe.datasets.training_config import TableColumn, TargetSpecimen


def partitions_overlap(left, right):
    if left is None or right is None:
        return True
    # Changing the original identity column is not an independent partition.
    return (left.get('source_column') != right.get('source_column')
            or left['specimen'] == right['specimen']
            or bool({tuple(row) for row in left['records']} & {tuple(row) for row in right['records']}))


@dataclass
class TargetSourceIndex:
    by_digest: dict = field(default_factory=dict)
    by_uri: dict = field(default_factory=dict)

    def register(self, asset, split, sample_id, partition=None):
        digest = asset.sha256.lower() if asset.sha256 else None
        uri_records = self.by_uri.setdefault(asset.uri, {})
        candidates = ([record for records in uri_records.values() for record in records] if digest is None
                      else self.by_digest.get(digest, []) + uri_records.get(None, []))
        for previous_split, previous_sample, previous_partition in candidates:
            if previous_split != split and partitions_overlap(previous_partition, partition):
                raise ValueError(f'target source {asset.asset_id!r} reused across splits: '
                                 f'sample {previous_sample!r} ({previous_split}) and {sample_id!r} ({split})')
        record = (split, sample_id, partition)
        uri_records.setdefault(digest, []).append(record)
        if digest is not None:
            self.by_digest.setdefault(digest, []).append(record)


def _native_receipt(sample, asset, selector, declaration):
    metadata = asset.descriptive_metadata
    block = metadata.get('block')
    mapping = metadata.get('column_map', {})
    if (not isinstance(selector, TableColumn) or asset.parent_asset_id is not None
            or asset.format not in {'csv', 'txt', 'xlsx'} or not isinstance(block, dict)
            or metadata.get('table_name') != selector.table or declaration.column not in mapping):
        raise ValueError('target specimen column must be mapped from a native source block')
    if declaration.column in block.get('numeric_fields', ()) or declaration.column in metadata.get('conversions', {}):
        raise ValueError('specimen identity must retain its original text without numeric conversion')
    try:
        source_column = int(mapping[declaration.column])
    except (TypeError, ValueError) as exc:
        raise ValueError('specimen identity requires an original native column index') from exc
    if source_column < 0:
        raise ValueError('specimen identity requires an original native column index')
    receipts = [a for a in sample.assets if a.parent_asset_id == asset.asset_id
                and a.format == 'normalized-table-json' and a.conversion is not None
                and a.conversion.hash_scope == 'logical_payload' and a.conversion.source_hash_verified
                and a.conversion.source_sha256 == asset.sha256
                and a.conversion.original_format == asset.format
                and a.conversion.target_format == 'normalized-table-json'
                and a.sha256 == a.conversion.target_payload_sha256
                and a.descriptive_metadata.get('table_key') == selector.table
                and a.descriptive_metadata.get('row_source_asset_id') == asset.asset_id
                and a.descriptive_metadata.get('column_map') == mapping
                and a.descriptive_metadata.get('block') == block]
    if not asset.sha256 or not receipts:
        raise ValueError('target specimen scope requires a verified native table conversion receipt')
    return block, source_column


def _check_records(records, block):
    for record in records:
        if not isinstance(record, list) or len(record) != 2:
            raise ValueError('specimen partition requires original source row and worksheet')
        sheet, number = record
        if type(number) is not int or number < 1 or sheet != (block.get('sheet') or ''):
            raise ValueError('specimen partition requires original source row and worksheet')
        if not block.get('start_marker') and (number < block['data_start_row'] or
                (block.get('data_end_row') is not None and number >= block['data_end_row'])):
            raise ValueError('specimen source row is outside the recorded native block')
    if not records or len({tuple(record) for record in records}) != len(records):
        raise ValueError('specimen partition repeats or lacks original source records')


def _partition(sample, asset, selector, positions, declaration, group):
    block, source_column = _native_receipt(sample, asset, selector, declaration)
    records = []
    for position in positions:
        row = sample.tables[selector.table][position]
        if row.get(declaration.column) != group:
            raise ValueError('target specimen identity must equal the declared group in every selected row')
        records.append([row.get('source_sheet', ''), row.get('source_row')])
    _check_records(records, block)
    return dict(asset_id=asset.asset_id, specimen=group, records=records,
                evidence=declaration.evidence, column=declaration.column, source_column=source_column)


def collect_column_partitions(sample, records, selectors, declaration, group, *, required=()):
    """Verify each covered field separately; uncovered feature roots stay whole."""
    if declaration is None:
        return {}
    assets = {a.asset_id:a for a in sample.assets}
    result = {}
    for name, record in records.items():
        scopes = []
        for asset_id in dict.fromkeys(record['asset_ids']):
            asset, selector = assets[asset_id], selectors[name]
            compatible = (isinstance(selector, TableColumn)
                          and declaration.column in asset.descriptive_metadata.get('column_map', {}))
            if name not in required and not compatible:
                continue
            positions = [row for row, bound in zip(record['source_rows'], record['asset_ids'], strict=True) if bound == asset_id]
            scopes.append(_partition(sample, asset, selector, positions, declaration, group))
        if scopes:
            result[name] = scopes
    if not result:
        raise ValueError('target specimen column must be mapped from a selected native source block')
    return result


def register_target_sources(sample, asset_ids, split, group, index, partitions=()):
    assets = {a.asset_id:a for a in sample.assets}
    by_asset = {p['asset_id']:p for p in partitions}
    for asset_id in dict.fromkeys(asset_ids):
        asset = assets[asset_id]
        meaning = asset.descriptive_metadata.get('meaning', {})
        if meaning.get('role') == 'target' and (meaning.get('split') != split or meaning.get('group_id') != group):
            raise ValueError(f'target asset {asset_id!r} has conflicting declared group/split')
        partition = by_asset.get(asset_id)
        while asset.parent_asset_id is not None:
            asset = assets[asset.parent_asset_id]
        index.register(asset, split, sample.metadata.sample_id, partition)


def _recorded_partitions(source, name, sample):
    """Check frozen scope structure against bound assets without reading payloads."""
    partitions = source.get('column_partitions', {}).get(name, [])
    assets = {a.asset_id:a for a in sample.assets}
    record = source['columns'][name]
    selector = TableColumn.model_validate(record['selector']) if partitions else None
    seen = set()
    for scope in partitions:
        asset_id = scope['asset_id']
        if asset_id in seen or asset_id not in record['asset_ids'] or scope['specimen'] != source['group']:
            raise ValueError('recorded specimen partition conflicts with selected asset or group')
        seen.add(asset_id)
        declaration = TargetSpecimen(column=scope['column'], evidence=scope['evidence'])
        block, column = _native_receipt(sample, assets[asset_id], selector, declaration)
        if scope['source_column'] != column or len(scope['records']) != record['asset_ids'].count(asset_id):
            raise ValueError('recorded specimen partition differs from original column or selected row count')
        _check_records(scope['records'], block)
    return partitions


def source_record_sample(source):
    return SimpleNamespace(assets=[AssetRef.model_validate(a) for a in source['assets']],
                           metadata=SimpleNamespace(sample_id=source['sample_metadata']['sample_id']))


def register_recorded_targets(source, targets, split, index):
    sample = source_record_sample(source)
    for q in targets:
        name = q['name']
        register_target_sources(sample, source['columns'][name]['asset_ids'], split, source['group'], index,
                                _recorded_partitions(source, name, sample))


def selected_root_scopes(source):
    """A shared root is narrow only when every selected field has verified scope."""
    sample = source_record_sample(source)
    assets = {a.asset_id:a for a in sample.assets}
    roots = {}
    for name, record in source['columns'].items():
        partitions = {p['asset_id']:p for p in _recorded_partitions(source, name, sample)}
        for asset_id in dict.fromkeys(record['asset_ids']):
            root = assets[asset_id]
            while root.parent_asset_id is not None:
                root = assets[root.parent_asset_id]
            roots.setdefault(root.asset_id, (root, []))[1].append(partitions.get(asset_id))
    for asset, scopes in roots.values():
        if any(scope is None for scope in scopes):
            yield asset, None
            continue
        first = scopes[0]
        if any((scope['specimen'],scope['source_column']) != (first['specimen'],first['source_column']) for scope in scopes):
            raise ValueError('selected fields disagree on original specimen scope')
        yield asset, dict(first, records=[list(row) for row in sorted({tuple(row) for scope in scopes for row in scope['records']})])
