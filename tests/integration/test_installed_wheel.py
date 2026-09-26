"""Opt-in local wheel installation test; never builds or downloads dependencies."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(not os.environ.get('EXP2CPFE_WHEEL_DIR'), reason='set EXP2CPFE_WHEEL_DIR after building the wheel')
def test_wheel_installation_outside_checkout(tmp_path, multimodal_sample_config):
    wheels=list(Path(os.environ['EXP2CPFE_WHEEL_DIR']).resolve().glob('*.whl'))
    assert len(wheels)==1, 'use a directory containing exactly one candidate wheel'
    target=tmp_path/'installed'
    installed=subprocess.run([sys.executable,'-m','pip','install','--no-deps','--no-compile',
                              '--disable-pip-version-check','--target',str(target),str(wheels[0])],
                             capture_output=True,text=True)
    assert installed.returncode==0,installed.stdout+installed.stderr
    code="""
import sys
from pathlib import Path
import subprocess
import runpy
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.path.insert(0,sys.argv[1])
import experiment_to_cpfe
assert Path(experiment_to_cpfe.__file__).is_relative_to(Path(sys.argv[1]))
from experiment_to_cpfe.cli import main
from experiment_to_cpfe.pipeline import _default_policy_path
assert _default_policy_path().is_relative_to(Path(sys.argv[1]))
assert main(['validate','--config',sys.argv[2],'--run-dir',sys.argv[3]])==0
from experiment_to_cpfe.solvers.abaqus.extraction import ExtractionRequest,build_abaqus_extraction_command
cmd=build_abaqus_extraction_command(ExtractionRequest(Path('none.odb'),Path('out'),('U',),'nodal'),('abaqus',))
script=Path(cmd[2])
assert script.is_relative_to(Path(sys.argv[1]))
r=subprocess.run([sys.executable,str(script),'--help'],capture_output=True,text=True)
assert r.returncode==0,r.stderr
prepare=runpy.run_path(sys.argv[4])['prepare']
prepare(Path('training-inputs'))
assert main(['build-training-dataset','--config','training-inputs/array/build.yaml','--run-dir','training-data'])==0
from experiment_to_cpfe.datasets.training import build_training_dataset
import inspect
assert Path(inspect.getfile(build_training_dataset)).is_relative_to(Path(sys.argv[1]))
runpy.run_path(sys.argv[5])['run'](Path('data-foundation'))
assert 'torch' not in sys.modules
for name, module in tuple(sys.modules.items()):
    if name.startswith('experiment_to_cpfe') and getattr(module, '__file__', None):
        assert Path(module.__file__).is_relative_to(Path(sys.argv[1])), name
print('Installed-wheel validate, extractor help, dataset build and data foundation workflow passed')
"""
    result=subprocess.run([sys.executable,'-I','-c',code,str(target),str(multimodal_sample_config),str(tmp_path/'run'),str(Path('examples/synthetic_training/prepare.py').resolve()),str(Path('examples/data_foundation/workflow.py').resolve())],
                          cwd=tmp_path,capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0,result.stdout+result.stderr
    assert 'data foundation workflow passed' in result.stdout
