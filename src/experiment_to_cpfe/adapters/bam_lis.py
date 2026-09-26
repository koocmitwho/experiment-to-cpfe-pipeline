"""Explicit BAM LIS tensile parsing and identity extraction.

This adapter keeps native measurements intact and records the declared selection
window. It never trains a model or asserts physical calibration.
"""
from types import SimpleNamespace

import numpy as np
from pydantic import Field

from experiment_to_cpfe.adapters.tabular import assemble_sample
from experiment_to_cpfe.config import SampleConfig, TabularSourceConfig
from experiment_to_cpfe.datasets.training_config import Contract, Declared, Split


class BamLISConfig(Contract):
    profile: str = 'bam_lis_tensile_v1'
    splits: dict[Declared, Split] = Field(default_factory=dict)
    identity_evidence: str = ''
    source_reference: str = ''
    license: str | None = None
    max_strain: float = Field(default=.008, gt=0, le=.008, allow_inf_nan=False)


def read_identity(path):
    lines = path.read_text(encoding='cp1252').splitlines()
    values = {}
    for prefix, key in [('Probenbezeichnung', 'specimen'), ('Projekt', 'batch')]:
        matches = [line.split('\t')[-1].strip() for line in lines if line.split('\t')[0].strip() == prefix]
        if len(matches) != 1 or not matches[0]:
            raise ValueError(f'{path.name}: missing or ambiguous native {prefix}')
        values[key] = matches[0]
    return values


def read_sample(path, identity, task, *, source_kind='measured'):
    specimen = identity['specimen']
    units = {'time': 's', 'strain': '1', 'stress': 'MPa'}
    source = TabularSourceConfig(path=path, table_name='measured_observations', source_kind=source_kind,
        modality='time_series', format='txt', delimiter='\t', encoding='cp1252',
        column_map={'time': '0', 'strain': '3', 'stress': '4'}, units=units,
        coordinate_frame=None, axis_order=('row',), native_layout='BAM LIS Daten block', license=task.license,
        block={'start_marker': '[Daten]', 'data_start_row': 3, 'decimal': ',',
               'numeric_fields': list(units), 'header_checks': [
                   {'row': 1, 'column': 0, 'value': 'Zeit'}, {'row': 2, 'column': 0, 'value': 'sec'},
                   {'row': 1, 'column': 3, 'value': 'Dehnung'}, {'row': 2, 'column': 3, 'value': '%'},
                   {'row': 1, 'column': 4, 'value': 'Spannung'}, {'row': 2, 'column': 4, 'value': 'MPa'}]},
        conversions={'strain': {'source_unit': '%', 'target_unit': '1', 'factor': .01,
                                 'reason': 'percent to dimensionless engineering strain'}})
    metadata = SampleConfig(sample_id=specimen, experiment_id=identity['batch'],
        microstructure_id='not-characterized', load_path_id='uniaxial-tensile', schema_version='1.0',
        coordinate={'name': 'tabular-observations', 'axes': ['row'], 'units': '1'},
        unit_system=units, tensor_order=['axial'],
        orientation={'representation': 'not_applicable', 'reason': 'scalar measured tensile curve regression'})
    sample = assemble_sample(SimpleNamespace(sources=[source], assets=[], imports=[], sample=metadata,
        solver_inputs={'dataset_split': task.splits[specimen], 'experimental_identity': identity,
                       'identity_evidence': task.identity_evidence, 'source_reference': task.source_reference}))
    rows = sample.tables['measured_observations']
    # Reject bad values anywhere, including outside the selected scientific window.
    values = np.asarray([[r[k] for k in units] for r in rows], float)
    if len(rows) < 2 or not np.isfinite(values).all():
        raise ValueError('all native numeric fields must be finite and contain at least two rows')
    origin_x, origin_y = rows[0]['strain'], rows[0]['stress']
    chosen = [0]
    for i in range(1, len(rows)):
        if rows[i]['strain'] > rows[chosen[-1]]['strain']:
            chosen.append(i)
            if rows[i]['strain'] - origin_x >= task.max_strain:
                break
    if rows[chosen[-1]]['strain'] - origin_x < task.max_strain:
        raise ValueError('native initial loading does not cover configured strain window')
    # Keep raw normalized table intact. Affine origins and source-row subset are
    # applied by the existing dataset selectors, preserving canonical hashes.
    selected = [i for i in chosen if rows[i]['strain'] - origin_x <= task.max_strain]
    sample.solver_inputs['processing'] = {'strain_origin': origin_x, 'stress_origin_MPa': origin_y,
        'selected_source_rows': [rows[i]['source_row'] for i in selected],
        'selected_normalized_rows': selected, 'max_strain': task.max_strain,
        'method': 'strictly increasing initial loading; preload subtraction; no interpolation'}
    return sample
