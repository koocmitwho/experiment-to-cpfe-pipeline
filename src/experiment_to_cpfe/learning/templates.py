"""Explicit inference/evaluation drafts; preserve strict declarations from a build config."""
import copy
import json
from pathlib import Path

import yaml

from experiment_to_cpfe.datasets.task_contract import validate_task
from experiment_to_cpfe.datasets.training_config import TrainingDatasetConfig

def bind_task(metadata, supplied, features, targets):
    original=(metadata or {}).get('config',{}).get('task_contract')
    declared=validate_task(supplied,features,targets)
    if original is not None:
        if declared != original:
            raise ValueError('strict training task_contract must be propagated unchanged')
    return declared

def make_template(kind, *, from_config):
    if kind not in ('infer-surrogate','evaluate-surrogate'):
        raise ValueError('supported template kinds: infer-surrogate, evaluate-surrogate')
    path=Path(from_config).resolve()
    build=TrainingDatasetConfig.model_validate(yaml.safe_load(path.read_text(encoding='utf-8')))
    if build.version != 1:
        raise ValueError('public scalar templates require a v1 scalar build configuration')
    scopes=[item.target_specimen.model_dump() if item.target_specimen else None for item in build.inputs]
    if any(scope != scopes[0] for scope in scopes):
        raise ValueError('partial or conflicting target_specimen declarations cannot be propagated')
    first=build.inputs[0]
    layout=build.layouts[first.layout]
    quantities=build.features if kind=='infer-surrogate' else build.target_quantities
    expected={q.name:layout.columns[q.name].model_dump(mode='json') for q in quantities}
    if any({q.name:build.layouts[item.layout].columns[q.name].model_dump(mode='json') for q in quantities} != expected
           for item in build.inputs):
        raise ValueError('conflicting layouts require an explicit inference/evaluation configuration')
    item=dict(path='REPLACE_WITH_HDF5_PATH',sample_id='REPLACE_WITH_SAMPLE_ID',layout=first.layout)
    if build.group_by=='explicit':item['group_id']='REPLACE_WITH_ORIGINAL_GROUP_ID'
    if scopes[0] is not None:item['target_specimen']=copy.deepcopy(scopes[0])
    config=dict(version=1,group_by=build.group_by,grouping_evidence=build.grouping_evidence,
        layouts={first.layout:dict(columns={q.name:layout.columns[q.name].model_dump(mode='json') for q in quantities},
            alignment_evidence=layout.alignment_evidence)},inputs=[item])
    if build.task_contract is not None:config['task_contract']=copy.deepcopy(build.task_contract)
    if kind=='infer-surrogate':
        config.update(checkpoint='REPLACE_WITH_FROZEN_CHECKPOINT',features=[q.model_dump() for q in quantities])
    else:
        config.update(predictions='REPLACE_WITH_PREDICTIONS_NPZ',targets=[q.model_dump() for q in quantities],split='test')
    return dict(kind=kind,config=config,required_edits=['paths','original sample/group identity'],
                source_config=str(path))

def write_template(output, template):
    path=Path(output)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(template['config'],stream,indent=2,ensure_ascii=False,allow_nan=False)
    return dict(status='completed',output=str(path),required_edits=template['required_edits'])
