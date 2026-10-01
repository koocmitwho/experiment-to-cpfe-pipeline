"""Frozen scalar workflow: raw/training sources and model are unnecessary at evaluation."""
import copy
import csv
import json

import numpy as np
import pytest

from training_fixtures import training_collection
from experiment_to_cpfe.datasets.hdf5 import write_hdf5
from experiment_to_cpfe.datasets.training import run_dataset_build

def save(path,value):
    path.write_text(json.dumps(value),encoding='utf-8')
    return path

@pytest.fixture(params=[False,True],ids=['legacy','strict'])
def frozen(tmp_path,make_sample,request):
    pytest.importorskip('torch')
    from experiment_to_cpfe.learning.surrogate import run_training
    config,samples = training_collection(tmp_path,make_sample)
    config['inputs'] = config['inputs'][:3]
    if request.param:
        from test_public_source_scopes import task
        declared=task()
        prototype=declared['inputs'].pop('x')
        declared['inputs']={q['name']:copy.deepcopy(prototype) for q in config['features']}
        observable=declared['targets'].pop('y');observable['unit']='Pa'
        declared['targets']={'stress':observable}
        config['task_contract']=declared
    run_dataset_build(save(tmp_path/'build.json',config),tmp_path/'dataset')
    training = json.loads((tmp_path/'dataset/training-config.json').read_text())
    training.update(dataset=str(tmp_path/'dataset/dataset.npz'),evaluation_mode='external_test',
        architecture='linear',hidden=[],epochs=1,patience=1)
    run_training(save(tmp_path/'train.json',training),tmp_path/'model')
    for fields,name in [({'eps','modulus'},'inputs'),({'load'},'truth')]:
        sample=copy.deepcopy(samples[3])
        keep=fields|{'increment_id','phase','source_asset_id','source_kind'}
        sample.tables['measured_observations']=[{k:v for k,v in row.items() if k in keep}
            for row in sample.tables['measured_observations']]
        write_hdf5(sample,tmp_path/f'{name}.h5')
    columns=config['layouts']['table']['columns']
    common=dict(version=1,group_by='sample_id',grouping_evidence='Original synthetic specimen identity')
    if config.get('task_contract') is not None:common['task_contract']=config['task_contract']
    inference=dict(common,checkpoint=str(tmp_path/'model/model.pt'),features=config['features'],
        layouts={'table':dict(columns={q['name']:columns[q['name']] for q in config['features']},alignment_evidence='record identity')},
        inputs=[dict(path=str(tmp_path/'inputs.h5'),sample_id='d',layout='table')])
    evaluation=dict(common,predictions=str(tmp_path/'infer/predictions.npz'),targets=[config['target']],split='test',
        layouts={'table':dict(columns={config['target']['name']:columns[config['target']['name']]},alignment_evidence='record identity')},
        inputs=[dict(path=str(tmp_path/'truth.h5'),sample_id='d',layout='table')])
    return inference,evaluation,config

def test_independent_prediction_then_identity_aligned_csv_evaluation(tmp_path,frozen):
    from experiment_to_cpfe.learning.inference import run_inference,run_evaluation
    infer,evaluate,_=frozen
    for name in 'abc':(tmp_path/f'{name}.h5').rename(tmp_path/f'{name}.sealed')
    (tmp_path/'truth.h5').rename(tmp_path/'truth.sealed')
    run_inference(save(tmp_path/'infer.json',infer),tmp_path/'infer')
    rows=list(csv.DictReader((tmp_path/'infer/predictions.csv').open(encoding='utf-8-sig')))
    assert len(rows)==5 and {r['sample_id'] for r in rows}=={'d'}
    assert {r['unit'] for r in rows}=={'Pa'}
    assert 'truth' not in rows[0]
    assert {'source_file','source_sha256','source_sheet','source_row','checkpoint_sha256','config_sha256'} <= rows[0].keys()
    (tmp_path/'truth.sealed').rename(tmp_path/'truth.h5')
    (tmp_path/'model/model.pt').rename(tmp_path/'model/model.sealed')
    run_evaluation(save(tmp_path/'evaluate.json',evaluate),tmp_path/'evaluated')
    report=json.loads((tmp_path/'evaluated/evaluation.json').read_text())
    assert report['training_overlap_check']=='verified'
    rows=list(csv.DictReader((tmp_path/'evaluated/evaluation.csv').open(encoding='utf-8-sig')))
    assert [float(r['truth']) for r in rows]==pytest.approx([0.,.425,.85,1.275,1.7])
    assert all(float(r['residual'])==pytest.approx(float(r['prediction'])-float(r['truth'])) for r in rows)
    assert (tmp_path/'evaluated/SUMMARY.md').is_file()
    delivery=json.loads((tmp_path/'evaluated/user-delivery.json').read_text())
    assert delivery['model_assessment']['status']=='not_assessed'

@pytest.mark.parametrize('mutation',['units','order','contamination'])
def test_inference_rejects_semantic_mismatch(tmp_path,frozen,mutation):
    from experiment_to_cpfe.learning.inference import run_inference
    config,_,_=frozen
    if mutation=='units':config['features'][0]['unit']='m'
    elif mutation=='order':config['features'].reverse()
    else:config['layouts']['table']['columns']['strain']=copy.deepcopy(frozen[2]['layouts']['table']['columns']['stress'])
    with pytest.raises(ValueError,match='unit|order|contamination|disagree'):
        run_inference(save(tmp_path/'invalid.json',config),tmp_path/'invalid')
    assert not (tmp_path/'invalid/predictions.csv').exists()

def test_template_keeps_strict_task_and_original_specimen_and_rejects_partial_scope(tmp_path):
    from experiment_to_cpfe.learning.templates import make_template
    from test_public_source_scopes import task
    selector=dict(kind='table',table='measured_observations',column='x',id_columns=['source_row'],source_unit='1')
    scope=dict(column='specimen',evidence='Original native ID')
    config=dict(version=1,features=[dict(name='x',unit='1')],target=dict(name='y',unit='1'),task_contract=task(),
        group_by='sample_id',grouping_evidence='Original specimen',layouts={'table':dict(columns={'x':selector,'y':dict(selector,column='y')},alignment_evidence='row')},
        inputs=[dict(path='a.h5',sample_id='a',layout='table',split='train',target_specimen=scope),
                dict(path='b.h5',sample_id='b',layout='table',split='validation',target_specimen=scope)])
    generated=make_template('infer-surrogate',from_config=save(tmp_path/'build.json',config))['config']
    assert generated['task_contract']==task()
    assert generated['inputs'][0]['target_specimen']==scope
    config['inputs'][1].pop('target_specimen')
    with pytest.raises(ValueError,match='partial|conflicting'):
        make_template('infer-surrogate',from_config=save(tmp_path/'partial.json',config))

def test_checkpoint_task_contract_rules_remain_explicit(tmp_path,frozen):
    from experiment_to_cpfe.learning.inference import run_inference
    config,_,_=frozen
    if 'task_contract' not in config:
        run_inference(save(tmp_path/'legacy.json',config),tmp_path/'legacy')
        report=json.loads((tmp_path/'legacy/inference.json').read_text())
        assert report['task_assessment']['status']=='legacy_unassessed'
        return
    config.pop('task_contract')
    with pytest.raises(ValueError,match='task_contract.*propagated'):
        run_inference(save(tmp_path/'dropped.json',config),tmp_path/'dropped')
    assert not (tmp_path/'dropped/predictions.csv').exists()

def test_evaluation_rejects_truth_with_a_different_original_row_identity(tmp_path,frozen):
    from experiment_to_cpfe.datasets.hdf5 import read_hdf5
    from experiment_to_cpfe.learning.inference import run_inference,run_evaluation
    infer,evaluate,_=frozen
    run_inference(save(tmp_path/'infer.json',infer),tmp_path/'infer')
    truth=read_hdf5(tmp_path/'truth.h5')
    for row in truth.tables['measured_observations']:
        if row['increment_id']=='r0':row['increment_id']='different-original-row'
    write_hdf5(truth,tmp_path/'changed-truth.h5')
    evaluate['inputs'][0]['path']=str(tmp_path/'changed-truth.h5')
    with pytest.raises(ValueError,match='identity alignment'):
        run_evaluation(save(tmp_path/'evaluate.json',evaluate),tmp_path/'invalid-evaluation')
    report=json.loads((tmp_path/'invalid-evaluation/evaluation.json').read_text())
    assert report['status']=='failed' and not (tmp_path/'invalid-evaluation/evaluation.csv').exists()
