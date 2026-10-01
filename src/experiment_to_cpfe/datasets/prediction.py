"""Named columns for independent prediction or truth, using canonical selectors."""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import Field, model_validator

from experiment_to_cpfe.datasets.package import _load_source
from experiment_to_cpfe.datasets.training_columns import select_column
from experiment_to_cpfe.datasets.training_config import Contract, Declared, Layout, Quantity, Split, TargetSpecimen
from experiment_to_cpfe.datasets.training_sources import collect_column_partitions
from experiment_to_cpfe.provenance.hashing import sha256_file


class SelectionInput(Contract):
    path: Declared
    sample_id: Declared
    layout: Declared
    group_id: Declared | None = None
    target_specimen: TargetSpecimen | None = None


class SelectionConfig(Contract):
    version: Literal[1]
    group_by: Literal['sample_id', 'experiment_id', 'explicit']
    grouping_evidence: Declared
    layouts: dict[Declared, Layout]
    inputs: list[SelectionInput] = Field(min_length=1)
    task_contract: dict | None = None

    @model_validator(mode='after')
    def selection_contract(self):
        from experiment_to_cpfe.datasets.task_contract import validate_task
        self.task_contract = validate_task(self.task_contract, getattr(self, 'features', None), getattr(self, 'targets', None))
        names = [q.name for q in self.quantities]
        if len(names) != len(set(names)):
            raise ValueError('quantity names must be unique')
        for name, layout in self.layouts.items():
            if set(layout.columns) != set(names):
                raise ValueError(f'layout {name!r} columns must match quantities exactly')
            target_selectors = [selector_identity(layout.columns[q.name]) for q in getattr(self, 'targets', [])]
            if any(selector_identity(layout.columns[q.name]) in target_selectors for q in getattr(self, 'features', [])):
                raise ValueError('target contamination: feature and target select the same source column')
            for q in self.quantities:
                column = layout.columns[q.name]
                if column.source_unit != q.unit and column.conversion is None:
                    raise ValueError(f'field {q.name!r}: unit change requires conversion')
        seen = set()
        for item in self.inputs:
            if item.sample_id in seen:
                raise ValueError(f'duplicate sample identity {item.sample_id!r}')
            seen.add(item.sample_id)
            if item.layout not in self.layouts:
                raise ValueError(f'unknown layout {item.layout!r}')
            if (self.group_by == 'explicit') != (item.group_id is not None):
                raise ValueError('group_id is required only for explicit grouping')
        return self


class InferenceConfig(SelectionConfig):
    checkpoint: Declared
    checkpoint_sha256: Declared | None = None
    features: list[Quantity] = Field(min_length=1)

    @property
    def quantities(self):
        return self.features


class EvaluationConfig(SelectionConfig):
    predictions: Declared
    predictions_sha256: Declared | None = None
    targets: list[Quantity] = Field(min_length=1)
    split: Split

    @property
    def quantities(self):
        return self.targets


@dataclass
class NamedSelection:
    values: np.ndarray
    sample_ids: np.ndarray
    row_ids: np.ndarray
    groups: np.ndarray
    sources: list[dict]
    task_assessment: dict | None = None


def selector_identity(selector):
    """Compare a selected field, independent of renaming or unit conversion."""
    if hasattr(selector, 'model_dump'):
        selector = selector.model_dump(mode='json')
    if selector['kind'] == 'table':
        return ('table', selector['table'], selector['column'], selector.get('where', {}))
    return ('array', selector['array'], selector.get('row_axis', 0), selector.get('component', []))


def select_named(config, *, base_dir, forbidden_names=(), forbidden_selectors=()):
    """Load only explicitly listed files; HDF5 integrity checks read each whole package.

    Put sealed responses in separate files. Selection is not an access-control
    boundary inside a mixed package, and field aliases cannot establish physics.
    """
    chunks, sources = [], []
    from experiment_to_cpfe.datasets.task_contract import assess_task, check_input_assets
    paths, hashes = set(), set()
    for item in config.inputs:
        path = (Path(base_dir) / item.path).resolve()
        try:
            digest = sha256_file(path)
            if path in paths or digest in hashes:
                raise ValueError('duplicate HDF5 file path or content')
            paths.add(path)
            hashes.add(digest)
            sample, provenance = _load_source(path, digest)
            if sample.metadata.sample_id != item.sample_id:
                raise ValueError('sample identity differs from configuration')
            group = item.group_id if config.group_by == 'explicit' else getattr(sample.metadata, config.group_by)
            layout = config.layouts[item.layout]
            selected = {}
            assets = {a.asset_id: a for a in sample.assets}
            for q in config.quantities:
                selector = layout.columns[q.name]
                identity = selector_identity(selector)
                if q.name in forbidden_names or identity in forbidden_selectors:
                    raise ValueError(f'target contamination in input field {q.name!r}')
                column = select_column(sample, selector)
                if q.name in {item.name for item in getattr(config, 'features', [])}:
                    check_input_assets(sample, column.asset_ids)
                selected[q.name] = column
            anchor = selected[config.quantities[0].name].ids
            rows = layout.rows
            stop = len(anchor) if rows.stop is None else rows.stop
            if stop > len(anchor) or rows.start >= stop:
                raise ValueError('row selection is empty or outside aligned rows')
            indices = rows.indices if rows.indices is not None else list(range(rows.start, stop, rows.step))
            if indices[-1] >= len(anchor):
                raise ValueError('row indices are outside aligned rows')
            identities = [anchor[i] for i in indices]
            vectors, records = [], {}
            for name, column in selected.items():
                if set(column.ids) != set(anchor):
                    raise ValueError(f'field {name!r}: identity alignment differs from first quantity')
                lookup = {key: i for i, key in enumerate(column.ids)}
                order = [lookup[key] for key in identities]
                vectors.append(column.values[order])
                records[name] = dict(selector=layout.columns[name].model_dump(mode='json'),
                    source_rows=[column.source_rows[i] for i in order], asset_ids=[column.asset_ids[i] for i in order],
                    physical_records=[dict(source_row=sample.tables[layout.columns[name].table][column.source_rows[i]].get('source_row'),
                        source_sheet=sample.tables[layout.columns[name].table][column.source_rows[i]].get('source_sheet',''))
                        for i in order] if layout.columns[name].kind == 'table' else [])
            target_names = [q.name for q in getattr(config, 'targets', [])]
            partitions = collect_column_partitions(sample, records, layout.columns,
                item.target_specimen, group, required=target_names)
            chunks.append((np.column_stack(vectors), np.asarray([item.sample_id] * len(indices)),
                           np.asarray(identities), np.asarray([group] * len(indices))))
            sources.append(dict(path=str(path), hdf5_sha256=digest, layout=item.layout, group=group,
                sample_metadata=sample.metadata.model_dump(mode='json'),
                assets=[a.model_dump(mode='json') for a in sample.assets], source_manifest=provenance,
                solver_inputs=sample.solver_inputs, row_ids=identities, columns=records,
                column_partitions=partitions,
                target_partitions=[scope for name in target_names for scope in partitions.get(name, [])]))
        except (ValueError, KeyError, TypeError, IndexError, OSError) as exc:
            raise ValueError(f'sample {item.sample_id!r} ({path}): {exc}') from exc
    arrays = [np.concatenate([c[i] for c in chunks]) for i in range(4)]
    assessment = assess_task(config.task_contract, getattr(config, 'features', None), getattr(config, 'targets', None), sources)
    return NamedSelection(*arrays, sources, assessment)
