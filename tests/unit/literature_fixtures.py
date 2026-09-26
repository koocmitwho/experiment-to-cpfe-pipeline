"""Synthetic SamplePackages for data-contract tests."""
import json
from pathlib import Path

from experiment_to_cpfe.provenance.hashing import sha256_file


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def ref(path):
    return dict(path=str(Path(path).resolve()), sha256=sha256_file(path))


def collection(root, names, *, micro='known', loading='known', offsets=None, groups=None, contexts=None, feature_shift=0.):
    from experiment_to_cpfe.assets.models import AssetRef
    from experiment_to_cpfe.schema.models import SampleMetadata, SamplePackage
    from experiment_to_cpfe.datasets.hdf5 import write_hdf5
    root.mkdir(parents=True, exist_ok=True)
    inputs = []
    for i, name in enumerate(names):
        offset = offsets[i] if offsets is not None else i * .1
        rows = [dict(row_id=str(j), x=float(j)+feature_shift, y=2.*j+offset, source_asset_id='raw', source_kind='input') for j in range(4)]
        raw = save(root / (name+'.json'), {'sample_id':name,'rows':rows})
        meta = SampleMetadata(sample_id=name, experiment_id=groups[i] if groups else name,
            microstructure_id=micro[i] if isinstance(micro,list) else micro, load_path_id=loading, schema_version='0.1',
            coordinate=dict(name='scalar', axes=['row'], units='1'), unit_system={'force':'N'},
            tensor_order=['scalar'], orientation=dict(representation='not_applicable', reason='synthetic table'), sources=[])
        asset = AssetRef(asset_id='raw', parent_asset_id=None, modality='time_series', format='json', uri=raw.as_uri(),
            source_kind='input', layer='raw', units={'x':'1','y':'N'}, coordinate_frame='scalar', axis_order=('row',),
            dtype='float64', shape=(4,2), native_layout='synthetic named rows', sha256=sha256_file(raw),
            license='self-generated synthetic fixture', lossy_transformations=(), descriptive_metadata={'table_name':'measured_observations'})
        sample = SamplePackage(meta, {'measured_observations':rows}, {}, (asset,), contexts[i] if contexts else {})
        path = root/(name+'.h5'); write_hdf5(sample,path)
        inputs.append(dict(path=str(path),sample_id=name,layout='table'))
    return dict(version=1, features=[dict(name='x',unit='1')],targets=[dict(name='y',unit='N')],
        group_by='experiment_id', grouping_evidence='independent synthetic source groups',
        layouts={'table':dict(alignment_evidence='explicit row_id',columns={name:dict(kind='table',table='measured_observations',column=name,
            source_unit=unit,id_columns=['row_id']) for name,unit in [('x','1'),('y','N')]})},inputs=inputs)
