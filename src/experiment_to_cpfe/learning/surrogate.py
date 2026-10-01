"""CPU MLP regression with case-group splits and validation-selected checkpoints."""

from pathlib import Path
import hashlib
import json
from numbers import Real
import time

import numpy as np

from experiment_to_cpfe.mechanics.tensile import regression_metrics
from experiment_to_cpfe.schema.validation import _unit_is_declared
from experiment_to_cpfe.learning.data_contract import read_training_bundle, validate_group_splits
from experiment_to_cpfe.provenance.hashing import sha256_file


def _network(torch, width, hidden):
    layers=[]
    for size in hidden:
        layers.extend([torch.nn.Linear(width,size),torch.nn.Tanh()])
        width=size
    layers.append(torch.nn.Linear(width,1))
    return torch.nn.Sequential(*layers).double()


def train_mlp(features, targets, groups, splits, *, output_dir, feature_names, feature_units,
              target_name, target_unit, epochs=2500, patience=500, seed=42, hidden=(32,32), learning_rate=.003,
              evaluation_mode='bundled_test', architecture='mlp', data_identity=None):
    """Fit a regression model, then evaluate its fixed best-validation checkpoint."""
    import torch
    x,y=np.asarray(features,float),np.asarray(targets,float)
    groups,splits=np.asarray(groups,str),np.asarray(splits,str)
    if x.ndim!=2 or y.shape!=(len(x),) or groups.shape!=y.shape or splits.shape!=y.shape or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('training requires aligned finite feature/target/group/split arrays')
    if (
        not isinstance(feature_names, (list, tuple, np.ndarray))
        or not isinstance(feature_units, (list, tuple, np.ndarray))
        or not all(_unit_is_declared(v) for v in [*feature_names, *feature_units, target_name, target_unit])
        or len(feature_names) != x.shape[1]
        or len(set(feature_names)) != len(feature_names)
        or len(feature_units) != x.shape[1]
    ):
        raise ValueError('training requires explicit feature names, units and target semantics')
    if evaluation_mode not in ('bundled_test', 'external_test'):
        raise ValueError('evaluation_mode must be bundled_test or external_test')
    if evaluation_mode == 'bundled_test' and set(splits) != {'train', 'validation', 'test'}:
        raise ValueError('scalar trainer requires train, validation and test splits; '
                         'use explicit external_test mode for train/validation-only training')
    if evaluation_mode == 'external_test' and set(splits) != {'train', 'validation'}:
        raise ValueError('external_test mode requires exactly train and validation; test responses must remain external')
    group_splits=validate_group_splits(groups,splits)
    if (
        type(epochs) is not int or epochs < 1
        or type(patience) is not int or patience < 1
        or architecture not in ('mlp', 'linear')
        or not isinstance(hidden, (list, tuple))
        or (architecture == 'mlp' and not hidden) or (architecture == 'linear' and hidden)
        or any(type(v) is not int or v < 1 for v in hidden)
        or isinstance(learning_rate, bool) or not isinstance(learning_rate, Real)
        or not np.isfinite(learning_rate) or learning_rate <= 0
        or type(seed) is not int or not -(2**63) <= seed < 2**64
    ):
        raise ValueError('positive training configuration required')
    masks={split:splits==split for split in ('train','validation','test') if split in set(splits)}
    output=Path(output_dir)
    output.mkdir(parents=True,exist_ok=False)
    mean=x[masks['train']].mean(axis=0)
    scale=x[masks['train']].std(axis=0)
    scale=np.where(scale>1e-12,scale,1.)
    ymean=float(y[masks['train']].mean())
    yscale=float(y[masks['train']].std())
    yscale=yscale if yscale>1e-12 else 1.
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    model=_network(torch,x.shape[1],hidden)
    tx=torch.tensor((x-mean)/scale,dtype=torch.float64)
    ty=torch.tensor((y-ymean)/yscale,dtype=torch.float64)[:,None]
    train=torch.tensor(masks['train']);validation=torch.tensor(masks['validation'])
    optimizer=torch.optim.Adam(model.parameters(),lr=learning_rate)
    if architecture == 'linear':
        # OLS is a reproducible baseline; neither validation nor external truth fits its coefficients.
        design = np.column_stack([tx[train].numpy(), np.ones(np.count_nonzero(masks['train']))])
        coefficients = np.linalg.lstsq(design, ty[train].numpy().ravel(), rcond=None)[0]
        with torch.no_grad():
            model[-1].weight.copy_(torch.tensor(coefficients[:-1][None, :]))
            model[-1].bias.copy_(torch.tensor(coefficients[-1:]))
    best_loss=float('inf');best_state=None;best_epoch=0;history=[]
    started=time.monotonic()
    for epoch in range(1,(1 if architecture == 'linear' else epochs)+1):
        model.train();optimizer.zero_grad()
        loss=torch.mean((model(tx[train])-ty[train])**2)
        if architecture == 'mlp':
            loss.backward();optimizer.step()
        model.eval()
        with torch.no_grad(): val_loss=float(torch.mean((model(tx[validation])-ty[validation])**2))
        history.append({'epoch':epoch,'train_mse_standardized':float(loss.detach()),'validation_mse_standardized':val_loss})
        if not np.isfinite([history[-1]['train_mse_standardized'],val_loss]).all():
            raise ValueError('training produced a nonfinite loss')
        if val_loss<best_loss-1e-10:
            best_loss=val_loss;best_epoch=epoch
            best_state={key:value.detach().clone() for key,value in model.state_dict().items()}
        if epoch-best_epoch>=patience: break
    model.load_state_dict(best_state)
    with torch.no_grad(): prediction=model(tx).numpy().ravel()*yscale+ymean
    checkpoint={'state_dict':best_state,'input_width':x.shape[1],'hidden':list(hidden),
                'architecture':architecture,'evaluation_mode':evaluation_mode,
                'x_mean':torch.tensor(mean),'x_scale':torch.tensor(scale),'y_mean':ymean,'y_scale':yscale,
                'feature_names':list(feature_names),'feature_units':list(feature_units),
                'target_name':target_name,'target_unit':target_unit,
                'training_identity':{'group_splits':group_splits,'data_identity':data_identity}}
    torch.save(checkpoint,output/'model.pt')
    metrics={split:regression_metrics(y[mask],prediction[mask]) for split,mask in masks.items()}
    baseline={split:regression_metrics(y[mask],np.full(np.count_nonzero(mask),ymean)) for split,mask in masks.items()}
    result={'model':'OLS' if architecture == 'linear' else 'MLP','architecture':architecture,
            'evaluation_mode':evaluation_mode,'hidden':list(hidden),'activation':'tanh' if hidden else 'identity','seed':seed,'device':'cpu','threads':1,
            'configuration':{'epochs':epochs,'patience':patience,'seed':seed,'hidden':list(hidden),
                             'learning_rate':learning_rate,'architecture':architecture,'evaluation_mode':evaluation_mode},
            'epochs_completed':epoch,'best_epoch':best_epoch,'checkpoint_selection':'validation MSE',
            'seconds':time.monotonic()-started,'metrics':metrics,'mean_baseline':baseline,'group_splits':group_splits,
            'feature_names':list(feature_names),'feature_units':list(feature_units),'target_name':target_name,'target_unit':target_unit,
            'normalization':{'fit_split':'train','x_mean':mean.tolist(),'x_scale':scale.tolist(),'y_mean':ymean,'y_scale':yscale},
            'history':history}
    (output/'training.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    np.savez_compressed(output/'predictions.npz',features=x,target=y,prediction=prediction,groups=groups,splits=splits)
    return result


def predict_mlp(checkpoint_path, features, *, feature_names=None, feature_units=None):
    import torch
    saved=torch.load(Path(checkpoint_path),map_location='cpu',weights_only=True)
    if feature_names is not None and list(feature_names) != saved['feature_names']:
        raise ValueError('prediction feature names/order disagree with checkpoint')
    if feature_units is not None and list(feature_units) != saved['feature_units']:
        raise ValueError('prediction feature units disagree with checkpoint')
    x=np.asarray(features,float)
    if x.ndim!=2 or x.shape[1]!=saved['input_width'] or not np.isfinite(x).all():
        raise ValueError('prediction features must be finite and match checkpoint width')
    model=_network(torch,saved['input_width'],saved['hidden'])
    model.load_state_dict(saved['state_dict']);model.eval()
    values=(torch.tensor(x,dtype=torch.float64)-saved['x_mean'])/saved['x_scale']
    with torch.no_grad(): return model(values).numpy().ravel()*saved['y_scale']+saved['y_mean']


def run_training(config_path, output_dir):
    """Run a configured numerical training bundle with dataset-relative input paths."""
    import yaml
    path=Path(config_path).resolve()
    config_bytes=path.read_bytes()
    try:
        config=yaml.safe_load(config_bytes.decode('utf-8'))
    except yaml.YAMLError as exc:
        raise ValueError(f'invalid training configuration: {exc}') from exc
    allowed={'dataset','dataset_sha256','feature_names','feature_units','target_name','target_unit','epochs','patience','seed','hidden','learning_rate','evaluation_mode','architecture'}
    required={'dataset','feature_names','feature_units','target_name','target_unit'}
    if not isinstance(config,dict) or set(config)-allowed or not required<=set(config):
        raise ValueError('scalar trainer accepts v1 target_name/target_unit declarations only; training config requires dataset and explicit feature/target declarations')
    if not isinstance(config['dataset'],str) or not config['dataset'].strip():
        raise ValueError('training dataset must be a nonblank path string')
    source=Path(config.pop('dataset'))
    if not source.is_absolute(): source=path.parent/source
    source=source.resolve()
    source_hash=sha256_file(source)
    expected_hash=config.pop('dataset_sha256',None)
    if expected_hash is not None and expected_hash!=source_hash:
        raise ValueError('training dataset file hash differs from configuration')
    with np.load(source,allow_pickle=False) as payload:
        if '__format_version__' in payload.files and payload['__format_version__'].item() == 'experiment-to-cpfe-training-2':
            raise ValueError('scalar trainer accepts v1 scalar bundles only; rebuild with version=1 and target')
        arrays,metadata=read_training_bundle(payload,config)
    if sha256_file(source)!=source_hash:
        raise ValueError('training dataset changed during reading')
    receipt={'path':str(source),'sha256':source_hash,'training_config_sha256':hashlib.sha256(config_bytes).hexdigest(),
             'metadata':metadata}
    try:
        result=train_mlp(**arrays,output_dir=output_dir,data_identity=receipt,**config)
    except ImportError as exc:
        raise ValueError('neural training requires the training extra') from exc
    result['dataset']={'path':str(source),'sha256':source_hash,'receipt':'dataset-receipt.json'}
    output=Path(output_dir)
    (output/'dataset-receipt.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    (output/'training.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    return {'status':'completed','model':str(Path(output_dir)/'model.pt'),'metrics':result['metrics']}
