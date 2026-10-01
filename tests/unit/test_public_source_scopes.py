"""Catch fake conversion lineage and identity-column changes on shared native tables."""
import json

import pytest

from test_training_specimens import specimens
from experiment_to_cpfe.datasets.training import build_training_dataset
from experiment_to_cpfe.datasets.hdf5 import write_hdf5

def task():
    return dict(version=1,purpose='Synthetic retrospective regression',data_kind='synthetic',
        prediction_time=dict(value=0.,unit='s',reference='after observing input'),
        inputs={'x':dict(source='original channel',role='predictor',availability='confirmed',available_at=0.,evidence='synthetic input')},
        targets={'y':dict(quantity='synthetic response',unit='1',entity='original specimen',spatial_support='one specimen',
            coordinate_frame='sample',component_convention='scalar',time_window=dict(start=0.,stop=1.,unit='s',reference='observation'),basis='synthetic')},
        context_requirements={},independence_axes={'specimen':'/sample_metadata/sample_id'})

def test_strict_shared_source_accepts_verified_original_specimens(tmp_path,specimens):
    config,_ = specimens
    config['task_contract'] = task()
    result = build_training_dataset(config,base_dir=tmp_path)
    assert result.metadata['task_assessment']['status'] == 'declared_ready'
    assert result.metadata['sources'][2]['column_partitions']['x'][0]['source_column'] == 0

@pytest.mark.parametrize('mutation',['hash','mapping'])
def test_fake_conversion_receipt_cannot_authorize_cross_split_scope(tmp_path,specimens,mutation):
    config,samples = specimens
    sample = samples[0]
    raw,derived = sample.assets
    if mutation == 'hash':
        derived = derived.model_copy(update={'conversion':derived.conversion.model_copy(update={'source_sha256':'0'*64})})
    else:
        derived = derived.model_copy(update={'descriptive_metadata':{**derived.descriptive_metadata,'column_map':{'specimen':'2'}}})
    sample.assets = (raw,derived)
    write_hdf5(sample,tmp_path/'changed.h5')
    config['inputs'][0]['path'] = 'changed.h5'
    with pytest.raises(ValueError,match='conversion|receipt|source.*hash'):
        build_training_dataset(config,base_dir=tmp_path)

def test_different_identity_column_cannot_make_a_shared_root_independent(specimens):
    from experiment_to_cpfe.datasets.training_sources import TargetSourceIndex
    _,samples = specimens
    index = TargetSourceIndex()
    index.register(samples[0].assets[0],'train','a',dict(specimen='a',source_column=0,records=[['',2]]))
    with pytest.raises(ValueError,match='reused across splits'):
        index.register(samples[0].assets[0],'test','b',dict(specimen='b',source_column=1,records=[['',4]]))
