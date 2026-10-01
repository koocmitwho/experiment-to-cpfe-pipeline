"""Catch scalar/vector assumptions in the actual portable training-to-evaluation driver."""
import hashlib
import json
from pathlib import Path

import pytest

from test_external_case_workflow import driver

def test_complete_synthetic_dopamics_uses_v1_and_external_test_without_shape_assumptions(tmp_path):
    pytest.importorskip('torch')
    module=driver()
    source=tmp_path/'source';source.mkdir()
    fields=['stress_reported','force','time','traverse_strain','traverse_displacement',
            'lx500_extensometer','lx500_elongation','laser_strain_percent']
    units=['MPa','N','s','%','mm','mm','mm','%']
    manifest=dict(case='dopamics',doi='synthetic',license='Apache-2.0',purpose='Synthetic regression fixture',
        grouping_evidence='Original generated specimens',sources=[],records=[],
        training=dict(candidates=[dict(id='linear',architecture='linear',hidden=[]),dict(id='mlp',architecture='mlp',hidden=[2])],
                      seed=17,epochs=3,patience=3,learning_rate=.003))
    for k,role in enumerate(['train','train','train','validation','test']):
        name=f'specimen-{k}'
        path=source/(name+'.txt')
        path.write_text(''.join('\t'.join(map(str,[3*i+k,1,i,0,0,0,0,float(i)]))+'\n' for i in range(5)))
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        manifest['sources'].append(dict(path=path.name,sha256=digest))
        manifest['records'].append(dict(id=name,role=role,source=path.name,sha256=digest,output_name=path.name,
            reader=dict(format='txt',encoding='utf-8',delimiter='\t',start_row=1,fields=fields,units=units)))
    result=module.run_case(manifest,source,tmp_path/'run')
    assert result['status']=='completed' and result['new_process_readback']['max_abs_difference']==0
    assert result['ols_test_baseline']['count']==5
    training=json.loads((tmp_path/'run/models/linear/training.json').read_text())
    assert training['evaluation_mode']=='external_test' and set(training['metrics'])=={'train','validation'}
    assert (tmp_path/'run/inference/predictions.csv').exists()
    assert (tmp_path/'run/evaluation/evaluation.csv').exists()
