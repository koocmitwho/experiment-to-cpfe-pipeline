"""Small synthetic regression exercises actual optimization and group isolation."""

import json
import numpy as np
import pytest

pytest.importorskip('torch')


def dataset():
    strain=np.linspace(0,1,31)
    x=np.vstack([np.column_stack([strain,np.full(len(strain),value)]) for value in (1.,2.,1.5,1.7)])
    y=x[:,0]*x[:,1]
    groups=np.repeat(['a','b','c','d'],31)
    splits=np.repeat(['train','train','validation','test'],31)
    return x,y,groups,splits


def test_mlp_learns_and_restores_best_validation_checkpoint(tmp_path):
    from experiment_to_cpfe.learning.surrogate import train_mlp, predict_mlp
    x,y,groups,splits=dataset()
    result=train_mlp(x,y,groups,splits,output_dir=tmp_path/'model',feature_names=['strain','modulus'],
        feature_units=['1','Pa'],target_name='stress',target_unit='Pa',epochs=800,patience=300,seed=17)
    assert result['metrics']['test']['nrmse'] < .05
    assert result['metrics']['test']['rmse'] < result['mean_baseline']['test']['rmse']
    assert result['normalization']['x_mean']==pytest.approx([.5,1.5])
    restored=predict_mlp(tmp_path/'model/model.pt',x[splits=='test'])
    assert np.allclose(restored,np.load(tmp_path/'model/predictions.npz')['prediction'][splits=='test'])
    metadata=json.loads((tmp_path/'model/training.json').read_text())
    assert metadata['group_splits']=={'a':'train','b':'train','c':'validation','d':'test'}
    assert metadata['target_unit']=='Pa'


def test_same_group_in_multiple_splits_is_rejected_before_outputs(tmp_path):
    from experiment_to_cpfe.learning.surrogate import train_mlp
    x,y,groups,splits=dataset()
    groups[splits=='test']='a'
    out=tmp_path/'invalid'
    with pytest.raises(ValueError,match='group'):
        train_mlp(x,y,groups,splits,output_dir=out,feature_names=['strain','modulus'],feature_units=['1','Pa'],
            target_name='stress',target_unit='Pa',epochs=1)
    assert not out.exists()


def test_scalar_trainer_rejects_missing_test_split_before_writing_a_partial_model(tmp_path):
    from experiment_to_cpfe.learning.surrogate import train_mlp
    x, y, groups, splits = dataset()
    keep = splits != 'test'
    out = tmp_path / 'unsupported-splits'
    with pytest.raises(ValueError, match='scalar trainer requires train, validation and test'):
        train_mlp(x[keep], y[keep], groups[keep], splits[keep], output_dir=out,
                  feature_names=['strain', 'modulus'], feature_units=['1', 'Pa'],
                  target_name='stress', target_unit='Pa', epochs=1)
    assert not out.exists()


def test_training_requires_explicit_features_and_finite_targets(tmp_path):
    from experiment_to_cpfe.learning.surrogate import train_mlp
    x,y,groups,splits=dataset();y[0]=np.nan
    with pytest.raises(ValueError):
        train_mlp(x,y,groups,splits,output_dir=tmp_path/'invalid',feature_names=['x'],feature_units=['unknown'],
                  target_name='stress',target_unit='Pa',epochs=1)


def test_training_cli_resolves_dataset_and_saves_outputs(tmp_path):
    from experiment_to_cpfe.cli import main
    x,y,groups,splits=dataset()
    np.savez_compressed(tmp_path/'data.npz',features=x,targets=y,groups=groups,splits=splits)
    config={'dataset':'data.npz','feature_names':['strain','modulus'],'feature_units':['1','Pa'],
            'target_name':'stress','target_unit':'Pa','epochs':2}
    (tmp_path/'train.json').write_text(json.dumps(config))
    output=tmp_path/'trained'
    assert main(['train-surrogate','--config',str(tmp_path/'train.json'),'--run-dir',str(output)])==0
    assert (output/'model.pt').is_file() and (output/'training.json').is_file()
    assert main(['train-surrogate','--config',str(tmp_path/'train.json'),'--run-dir',str(output)])==1
