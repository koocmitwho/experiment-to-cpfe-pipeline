"""Exercise real files and bounded artifact access, including unsafe containers."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess

import h5py
import numpy as np
import pytest


def api():
    return importlib.import_module('experiment_to_cpfe.harness.artifacts')


def record(path, root, **extra):
    return dict(relative_path=path.relative_to(root).as_posix(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                size_bytes=path.stat().st_size, media_type='application/octet-stream', **extra)


def test_atomic_json_replaces_complete_value_and_streaming_digest(tmp_path):
    path = tmp_path/'state.json'
    path.write_text('{"old": true}')
    api().atomic_json(path, {'message': '实验', 'status': 'completed'})
    assert json.loads(path.read_text(encoding='utf-8')) == {'message': '实验', 'status': 'completed'}
    assert api().digest_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()
    assert sorted(p.name for p in tmp_path.iterdir()) == ['state.json']


def test_atomic_json_failed_fsync_preserves_previous_record(tmp_path, monkeypatch):
    path = tmp_path/'state.json'
    path.write_bytes(b'{"old":true}')
    def fail(_):
        raise OSError('injected storage failure')
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(OSError):
        api().atomic_json(path, {'new': True})
    assert path.read_bytes() == b'{"old":true}'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['state.json']


def test_atomic_json_short_write_preserves_previous_record(tmp_path, monkeypatch):
    artifact_api = api()
    path = tmp_path/'state.json'
    path.write_bytes(b'{"old":true}')
    real_fdopen = os.fdopen
    class ShortWriter:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def write(self, payload): return self.stream.write(payload[:2])
        def __getattr__(self, name): return getattr(self.stream, name)
    monkeypatch.setattr(os, 'fdopen', lambda *a, **k: ShortWriter(real_fdopen(*a, **k)))
    with pytest.raises(OSError):
        artifact_api.atomic_json(path, {'new': True})
    assert path.read_bytes() == b'{"old":true}'


@pytest.mark.parametrize('value', [None, 1, {}, ['a'], '../outside.txt'])
def test_resolve_rejects_invalid_or_escaping_paths(tmp_path, value):
    with pytest.raises((ValueError, OSError)):
        api().resolve_within(tmp_path, value)


def test_resolve_handles_missing_target_without_escaping(tmp_path):
    target = tmp_path/'new'/'artifact.json'
    assert api().resolve_within(tmp_path, 'new/artifact.json', must_exist=False) == target
    with pytest.raises((ValueError, OSError)):
        api().resolve_within(tmp_path, 'missing.json')
    with pytest.raises(ValueError):
        api().resolve_within(tmp_path, tmp_path.parent/'outside', must_exist=False)


def test_inventory_rejects_link_and_does_not_follow_outside(tmp_path, record_property):
    artifact_api = api()
    root = tmp_path/'root'; root.mkdir()
    outside = tmp_path/'outside'; outside.mkdir()
    (outside/'secret.txt').write_text('must not read')
    try:
        (root/'linked').symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        record_property('symlink_not_exercised', type(exc).__name__)
        pytest.skip('ordinary symlink creation is unavailable; junction coverage is separate')
    record_property('symlink_exercised', True)
    with pytest.raises(ValueError):
        artifact_api.inventory(root)
    with pytest.raises(ValueError):
        artifact_api.resolve_within(root, root/'linked'/'secret.txt')


def test_inventory_rejects_windows_junction_escape(tmp_path, record_property):
    artifact_api = api()
    if os.name != 'nt':
        record_property('junction_not_applicable', True)
        return
    root = tmp_path/'root'; root.mkdir()
    outside = tmp_path/'outside'; outside.mkdir()
    (outside/'secret.txt').write_text('private')
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(root/'linked'), str(outside)],
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    with pytest.raises(ValueError):
        artifact_api.inventory(root)
    with pytest.raises(ValueError):
        artifact_api.resolve_within(root, root/'linked'/'secret.txt')


def test_inventory_has_relative_integrity_records_and_rejects_partial_files(tmp_path):
    (tmp_path/'nested').mkdir()
    (tmp_path/'nested'/'data.csv').write_bytes(b'x,y\n1,2\n')
    rows = api().inventory(tmp_path)
    assert rows == [dict(relative_path='nested/data.csv', sha256=hashlib.sha256(b'x,y\n1,2\n').hexdigest(),
                         size_bytes=8, media_type='text/csv')]
    (tmp_path/'pending.tmp').write_text('incomplete')
    with pytest.raises(ValueError):
        api().inventory(tmp_path)


def test_summary_does_not_expose_binary_contents(tmp_path):
    path = tmp_path/'model.odb'; path.write_bytes(b'\x00secret binary')
    summary = api().read_view(tmp_path, record(path, tmp_path))
    assert summary['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert summary['relative_path'] == 'model.odb'
    assert 'secret' not in json.dumps(summary)
    with pytest.raises(ValueError):
        api().read_view(tmp_path, record(path, tmp_path), view='text')


def test_json_list_and_object_views_are_structured_and_bounded(tmp_path):
    path = tmp_path/'report.json'; path.write_text(json.dumps([{'i': i} for i in range(10)]))
    page = api().read_view(tmp_path, record(path, tmp_path), view='json', offset=3, limit=2)
    assert page['items'] == [{'i': 3}, {'i': 4}]
    assert page['next_offset'] == 5
    path.write_text('{"status":"completed"}')
    assert api().read_view(tmp_path, record(path, tmp_path), view='json')['data'] == {'status': 'completed'}


def test_csv_and_text_pagination_preserve_columns_and_rows(tmp_path):
    path = tmp_path/'table.csv'; path.write_text('id,value,unused\na,1,x\nb,2,y\nc,3,z\n')
    page = api().read_view(tmp_path, record(path, tmp_path), view='csv', offset=1, limit=1, columns=['id','value'])
    assert page['items'] == [{'id': 'b', 'value': '2'}]
    assert page['next_offset'] == 2
    with pytest.raises(ValueError):
        api().read_view(tmp_path, record(path, tmp_path), view='csv', columns=['absent'])
    text = tmp_path/'log.txt'; text.write_text('first\nsecond\nthird\n')
    assert api().read_view(tmp_path, record(text, tmp_path), view='text', offset=1, limit=1)['items'] == ['second']


@pytest.mark.parametrize('kwargs', [{'limit':501}, {'limit':0}, {'limit':True}, {'offset':-1}, {'offset':1.5}, {'view':'raw'}, {'view':[]}])
def test_read_rejects_invalid_page_request(tmp_path, kwargs):
    path=tmp_path/'data.json'; path.write_text('[1]')
    with pytest.raises(ValueError):
        api().read_view(tmp_path, record(path,tmp_path), **kwargs)


def test_read_rejects_changed_artifact_and_oversized_response(tmp_path):
    path=tmp_path/'data.json'; path.write_text('[1]')
    bound=record(path,tmp_path); path.write_text('[2]')
    with pytest.raises(ValueError):
        api().read_view(tmp_path,bound,view='json')
    path.write_text(json.dumps({'huge':'a'*262144}))
    with pytest.raises(ValueError):
        api().read_view(tmp_path,record(path,tmp_path),view='json')
    path=tmp_path/'log.txt'; path.write_text('a'*262145)
    with pytest.raises(ValueError):
        api().read_view(tmp_path,record(path,tmp_path),view='text')


def test_read_checks_integrity_again_after_reading(tmp_path, monkeypatch):
    artifact_api=api()
    path=tmp_path/'data.json'; path.write_text('[1]')
    bound=record(path,tmp_path)
    actual=artifact_api.digest_file
    calls=[]
    def changing_digest(target):
        calls.append(target)
        if len(calls)==2: path.write_text('[2]')
        return actual(target)
    monkeypatch.setattr(artifact_api,'digest_file',changing_digest)
    with pytest.raises(ValueError):
        artifact_api.read_view(tmp_path,bound,view='json')


def test_hdf5_registered_numeric_slice_never_reads_entire_dataset(tmp_path):
    path=tmp_path/'fields.h5'
    with h5py.File(path,'w') as h5:
        data=h5.create_dataset('stress',shape=(10_000_000,2),dtype='f8',chunks=(10,2),fillvalue=7)
        data[4:6]=[[1,2],[3,4]]
    bound=record(path,tmp_path,datasets=['stress'])
    page=api().read_view(tmp_path,bound,view='hdf5',dataset='stress',offset=4,limit=2)
    assert page['items']==[[1.,2.],[3.,4.]]
    assert page['shape']==[10_000_000,2]
    assert page['next_offset']==6
    with pytest.raises(ValueError):
        api().read_view(tmp_path,record(path,tmp_path),view='hdf5',dataset='stress')


@pytest.mark.parametrize('kind',['external_link','soft_link','vds','external_storage','object','wide'])
def test_hdf5_rejects_unsafe_links_storage_and_unbounded_datasets(tmp_path,kind):
    path=tmp_path/'unsafe.h5'
    with h5py.File(path,'w') as h5:
        h5.create_dataset('safe',data=np.arange(3))
        if kind=='external_link': h5['unsafe']=h5py.ExternalLink(str(tmp_path/'outside.h5'),'data')
        elif kind=='soft_link': h5['unsafe']=h5py.SoftLink('/safe')
        elif kind=='vds':
            layout=h5py.VirtualLayout(shape=(3,),dtype='i8')
            layout[:]=h5py.VirtualSource(str(tmp_path/'outside.h5'),'data',shape=(3,))
            h5.create_virtual_dataset('unsafe',layout)
        elif kind=='external_storage': h5.create_dataset('unsafe',shape=(3,),dtype='i8',external=[('outside.bin',0,h5py.h5f.UNLIMITED)])
        elif kind=='object': h5.create_dataset('unsafe',data=['secret'],dtype=h5py.string_dtype())
        else: h5.create_dataset('unsafe',shape=(2,1_000_000),dtype='f8',chunks=True)
    target='safe' if kind in {'external_link','soft_link','vds','external_storage'} else 'unsafe'
    with pytest.raises(ValueError):
        api().read_view(tmp_path,record(path,tmp_path,datasets=[target]),view='hdf5',dataset=target,limit=2)


def test_hdf5_registered_names_cannot_escape_dataset_selection(tmp_path):
    path=tmp_path/'fields.h5'
    with h5py.File(path,'w') as h5: h5.create_dataset('stress',data=[1,2])
    with pytest.raises(ValueError):
        api().read_view(tmp_path,record(path,tmp_path,datasets=['stress']),view='hdf5',dataset='../outside')


def test_csv_oversized_quoted_multiline_record_is_rejected(tmp_path):
    path = tmp_path/'large.csv'
    path.write_text('id,text\n1,"' + ('a'*65536 + '\n')*5 + '"\n')
    with pytest.raises(ValueError):
        api().read_view(tmp_path,record(path,tmp_path),view='csv')


def test_json_ambiguous_keys_and_nonfinite_values_are_rejected(tmp_path):
    path = tmp_path/'ambiguous.json'
    for payload in ('{"threshold": 1, "threshold": 2}', '{"value":NaN}'):
        path.write_text(payload)
        with pytest.raises(ValueError):
            api().read_view(tmp_path,record(path,tmp_path),view='json')


def test_concurrent_atomic_writers_publish_whole_records(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    artifact_api=api()
    path=tmp_path/'state.json'
    def write(number):
        artifact_api.atomic_json(path, {'number':number,'payload':str(number)*10000})
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write,range(12)))
    actual=json.loads(path.read_text())
    assert actual['payload']==str(actual['number'])*10000
    assert list(tmp_path.iterdir())==[path]


def test_large_json_document_requires_a_bounded_export(tmp_path):
    path=tmp_path/'huge.json'
    path.write_text(json.dumps({'records':[0]*1_500_000}))
    with pytest.raises(ValueError):
        api().read_view(tmp_path,record(path,tmp_path),view='json',limit=1)


def test_hdf5_views_never_read_attributes(tmp_path,monkeypatch):
    path=tmp_path/'attributes.h5'
    with h5py.File(path,'w',track_order=True) as h5:
        h5.create_dataset('stress',data=[1.,2.,3.])
        h5.attrs['large_private_metadata']=np.arange(300_000,dtype='i8')
    def forbidden_attribute(*args,**kwargs):
        raise AssertionError('artifact views must not load HDF5 attributes')
    monkeypatch.setattr(h5py.AttributeManager,'__getitem__',forbidden_attribute)
    bound=record(path,tmp_path,datasets=['stress'])
    assert api().read_view(tmp_path,bound,view='hdf5',dataset='stress',limit=2)['items']==[1.,2.]
    assert 'large_private_metadata' not in json.dumps(api().read_view(tmp_path,bound))


def test_corrupt_hdf5_is_never_a_successful_view(tmp_path):
    path=tmp_path/'broken.h5'; path.write_bytes(b'not an HDF5 file')
    with pytest.raises((ValueError,OSError)):
        api().read_view(tmp_path,record(path,tmp_path,datasets=['stress']),view='hdf5',dataset='stress')
