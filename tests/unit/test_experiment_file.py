import json

import pytest

from experiment_file_fixtures import save,ref


def declared(value):
    return dict(status='confirmed',value=value,evidence='explicit test file metadata')


def experiment_config(root):
    sample=dict(sample_id='specimen-a',experiment_id='campaign-a',microstructure_id='not-characterized',load_path_id='tensile',
        schema_version='0.1',coordinate=dict(name='table',axes=['row'],units='1'),unit_system={'strain':'1','stress':'MPa','time':'s'},
        tensor_order=['axial'],orientation=dict(representation='not_applicable',reason='scalar tensile file'))
    payload=dict(format='self-describing-experiment-1',sample=sample,
        context=dict(sample_id=declared('specimen-a'),batch_id=declared('batch-a'),protocol_summary=declared('prescribed ramp'),
            geometry=declared({'gauge_length':{'value':10.,'unit':'mm'}}),loading=declared('axial displacement'),
            measurement=declared('strain gauge and load cell'),acquired_at=declared('2026-09-17T10:30:00+08:00'),
            instrument_settings=declared({'sampling_rate':{'value':10,'unit':'Hz'}}),zeroing=declared('no zero shift'),
            preload=declared('none'),trimming=declared('all acquired rows retained'),vendor_magic=17),
        measurements=dict(units={'time':'s','strain':'1','stress':'MPa'},rows=[{'time':0.,'strain':0.,'stress':1.},
            {'time':.1,'strain':.01,'stress':10.}]),unknown_header={'channel_mode':'unmapped-code-42'})
    raw=save(root/'experiment.json',payload)
    script=root/'acquire.py';script.write_text("raise RuntimeError('must never execute')",encoding='utf-8')
    return save(root/'config.json',dict(version=1,purpose='synthetic self-describing fixture',profile='self_describing_json_v1',
        source=ref(raw),license='self-generated synthetic fixture',evidence_scope='synthetic_mechanism_only',
        scripts=[dict(ref(script),version='fixture-v1',purpose='declared acquisition script; hash only')]))


def test_context_and_unknown_fields_survive_hdf5_roundtrip_without_script_execution(tmp_path):
    from experiment_to_cpfe.adapters.experiment_file import run_experiment_file
    from experiment_to_cpfe.datasets.hdf5 import read_hdf5
    path=experiment_config(tmp_path);report=run_experiment_file(path,tmp_path/'run')
    sample=read_hdf5(tmp_path/'run/sample.h5')
    context=sample.solver_inputs['experiment_context']
    assert context['fields']['sample_id']['value']=='specimen-a'
    assert context['unmapped_fields']['vendor_magic']==17
    assert context['unmapped_semantics']=='unconfirmed'
    assert context['raw_metadata']['unknown_header']=={'channel_mode':'unmapped-code-42'}
    assert sample.tables['measured_observations'][1]['stress']==10.
    assert report['scripts'][0]['content_hash_verified'] is True
    assert report['scripts'][0]['executed'] is False
    assert report['scientific_readiness']=='not_established_by_file_import'
    original=next(a for a in sample.assets if a.asset_id=='experiment-source')
    assert original.sha256==json.loads(path.read_text())['source']['sha256']
    assert any(a.parent_asset_id=='experiment-source' for a in sample.assets)


@pytest.mark.parametrize('kind',['identity','unit','timestamp'])
def test_conflicting_or_invalid_confirmed_metadata_is_rejected(tmp_path,kind):
    from experiment_to_cpfe.adapters.experiment_file import run_experiment_file
    path=experiment_config(tmp_path);cfg=json.loads(path.read_text());raw=tmp_path/'experiment.json';data=json.loads(raw.read_text())
    if kind=='identity':data['context']['sample_id']=declared('different-specimen')
    elif kind=='unit':data['measurements']['units']['stress']='Pa'
    else:data['context']['acquired_at']=declared('2026-09-17 10:30:00')
    save(raw,data);cfg['source']=ref(raw);save(path,cfg)
    with pytest.raises(ValueError):run_experiment_file(path,tmp_path/'run')


def test_missing_experimental_settings_stay_unavailable(tmp_path):
    from experiment_to_cpfe.adapters.experiment_file import run_experiment_file
    path=experiment_config(tmp_path);cfg=json.loads(path.read_text());raw=tmp_path/'experiment.json';data=json.loads(raw.read_text())
    data['context']={'sample_id':declared('specimen-a')};save(raw,data);cfg['source']=ref(raw);save(path,cfg)
    result=run_experiment_file(path,tmp_path/'run')
    assert result['context_status']=='partial'
    assert 'geometry' in result['unavailable_fields']


def test_embedded_script_reference_is_preserved_but_never_followed(tmp_path):
    from experiment_to_cpfe.adapters.experiment_file import run_experiment_file
    path=experiment_config(tmp_path);cfg=json.loads(path.read_text());raw=tmp_path/'experiment.json';data=json.loads(raw.read_text())
    data['acquisition_script']={'path':'does-not-exist.py','version':'unknown'}
    save(raw,data);cfg['source']=ref(raw);save(path,cfg)
    result=run_experiment_file(path,tmp_path/'run')
    assert result['status']=='completed'



def test_synthetic_import_keeps_input_provenance(tmp_path):
    from experiment_to_cpfe.adapters.experiment_file import run_experiment_file
    from experiment_to_cpfe.datasets.hdf5 import read_hdf5
    run_experiment_file(experiment_config(tmp_path), tmp_path / 'run')
    sample = read_hdf5(tmp_path / 'run/sample.h5')
    assert {asset.source_kind.value for asset in sample.assets} == {'input'}


@pytest.mark.parametrize('fault', ['source-hash', 'script-hash', 'duplicate-source-field', 'duplicate-config-field'])
def test_bad_source_bindings_and_ambiguous_json_leave_failure_receipt(tmp_path, fault):
    from experiment_to_cpfe.adapters.experiment_file import run_experiment_file
    path = experiment_config(tmp_path)
    cfg = json.loads(path.read_text())
    if fault == 'source-hash':
        (tmp_path / 'experiment.json').write_text('{}')
    elif fault == 'script-hash':
        (tmp_path / 'acquire.py').write_text('different content')
    elif fault == 'duplicate-source-field':
        raw = tmp_path / 'experiment.json'
        raw.write_text('{"format":"a","format":"b"}')
        cfg['source'] = ref(raw)
        save(path, cfg)
    else:
        path.write_text(path.read_text().replace('"version": 1', '"version": 1, "version": 1'))
    with pytest.raises(ValueError):
        run_experiment_file(path, tmp_path / 'run')
    report = json.loads((tmp_path / 'run/experiment-file.json').read_text())
    assert report['status'] == 'failed'
    assert not (tmp_path / 'run/sample.h5').exists()


def test_experiment_import_preserves_existing_output(tmp_path):
    from experiment_to_cpfe.adapters.experiment_file import run_experiment_file
    path = experiment_config(tmp_path)
    output = tmp_path / 'run'
    output.mkdir()
    (output / 'keep.txt').write_text('previous attempt')
    with pytest.raises(FileExistsError):
        run_experiment_file(path, output)
    assert [p.name for p in output.iterdir()] == ['keep.txt']


@pytest.mark.parametrize('scope,source_kind', [
    ('synthetic_mechanism_only', 'input'), ('experimental', 'measured')])
def test_bam_profile_imports_synthetic_native_rows_and_keeps_context(tmp_path, scope, source_kind):
    from experiment_to_cpfe.adapters.experiment_file import run_experiment_file
    from experiment_to_cpfe.datasets.hdf5 import read_hdf5
    raw = tmp_path / 'fixture.lis'
    raw.write_text('Probenbezeichnung\tfixture-a\nProjekt\tproject-a\n'
        '[Daten]\nZeit\tWeg\tKraft\tDehnung\tSpannung\nsec\tmm\tkN\t%\tMPa\n' +
        '\n'.join(f'{i}\t0\t0\t{i/10}\t{i*10}' for i in range(10)), encoding='cp1252')
    task = save(tmp_path / 'bam-task.json', dict(profile='bam_lis_tensile_v1', splits={'fixture-a':'train'},
        identity_evidence='synthetic fixture specimen declaration', license='synthetic fixture'))
    config = save(tmp_path / 'config.json', dict(version=1, purpose='BAM synthetic parser test',
        profile='bam_lis_context_v1', source=ref(raw), bam_task=ref(task), license='synthetic fixture',
        evidence_scope=scope))
    report = run_experiment_file(config, tmp_path / 'run')
    sample = read_hdf5(tmp_path / 'run/sample.h5')
    assert {asset.source_kind.value for asset in sample.assets} == {source_kind}
    assert {row['source_kind'] for row in sample.tables['measured_observations']} == {source_kind}
    assert {source.kind.value for source in sample.metadata.sources} == {source_kind}
    assert len(sample.tables['measured_observations']) == 10
    assert sample.tables['measured_observations'][8]['strain'] == pytest.approx(.008)
    assert sample.tables['measured_observations'][8]['stress'] == 80.
    assert sample.solver_inputs['processing']['selected_normalized_rows'] == list(range(9))
    context = sample.solver_inputs['experiment_context']
    assert context['fields']['batch_id']['status'] == 'unconfirmed'
    assert '[Daten]' not in context['raw_metadata']['bam_header']
    assert report['scientific_readiness'] == 'not_established_by_file_import'
    if scope == 'experimental':
        from experiment_to_cpfe.adapters.bam_lis import BamLISConfig, read_identity, read_sample
        # Direct users of the native profile retain its measured-data default.
        restored = read_sample(raw, read_identity(raw), BamLISConfig.model_validate(json.loads(task.read_text())))
        assert {asset.source_kind.value for asset in restored.assets} == {'measured'}
        assert {row['source_kind'] for row in restored.tables['measured_observations']} == {'measured'}
        assert {source.kind.value for source in restored.metadata.sources} == {'measured'}
