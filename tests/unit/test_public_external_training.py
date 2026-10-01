"""Explicit scalar training boundaries, exercised through real CPU optimization."""
import json

import numpy as np
import pytest

pytest.importorskip('torch')

def data():
    x = np.array([[0.], [1.], [2.], [3.], [20.], [30.]])
    y = np.array([1., 3., 5., 7., 41., 61.])
    return x, y, np.array(['a']*4+['b']*2), np.array(['train']*4+['validation']*2)

def test_explicit_external_test_mode_fits_only_train_and_saves_frozen_identity(tmp_path):
    from experiment_to_cpfe.learning.surrogate import train_mlp, predict_mlp
    x, y, groups, splits = data()
    result = train_mlp(x, y, groups, splits, output_dir=tmp_path/'model',
        feature_names=['x'], feature_units=['1'], target_name='y', target_unit='MPa',
        evaluation_mode='external_test', architecture='linear', hidden=[], epochs=3, patience=3)
    assert set(result['metrics']) == {'train', 'validation'}
    assert result['normalization']['x_mean'] == [1.5]
    assert result['normalization']['y_mean'] == 4.
    assert result['evaluation_mode'] == 'external_test'
    assert predict_mlp(tmp_path/'model/model.pt', [[50.]]) == pytest.approx([101.])

def test_external_mode_rejects_a_bundled_test_response(tmp_path):
    from experiment_to_cpfe.learning.surrogate import train_mlp
    x, y, groups, splits = data()
    splits[-1] = 'test'
    groups[-1] = 'c'
    with pytest.raises(ValueError, match='external_test.*train.*validation'):
        train_mlp(x,y,groups,splits,output_dir=tmp_path/'model',feature_names=['x'],
            feature_units=['1'],target_name='y',target_unit='MPa',evaluation_mode='external_test',epochs=1)
    assert not (tmp_path/'model').exists()

def test_scalar_entry_rejects_vector_bundle_before_output(tmp_path):
    from experiment_to_cpfe.learning.surrogate import run_training
    from experiment_to_cpfe.learning.data_contract import VECTOR_TRAINING_FORMAT
    x, y, groups, splits = data()
    np.savez(tmp_path/'vector.npz',features=x,targets=y[:,None],groups=groups,splits=splits,
             __format_version__=np.asarray(VECTOR_TRAINING_FORMAT))
    config = dict(dataset='vector.npz',feature_names=['x'],feature_units=['1'],
                  target_name='y',target_unit='MPa',epochs=1)
    (tmp_path/'train.json').write_text(json.dumps(config))
    with pytest.raises(ValueError,match='scalar trainer.*v1'):
        run_training(tmp_path/'train.json',tmp_path/'model')
    assert not (tmp_path/'model').exists()
