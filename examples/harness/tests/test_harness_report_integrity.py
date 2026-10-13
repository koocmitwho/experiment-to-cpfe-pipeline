"""A historical accepted report must not survive current evidence failure as current truth."""
from test_harness_execution import req, setup, wait


def _completed_case(tmp_path):
    client, run = setup(tmp_path)
    status = wait(client, run)
    assert status['execution_status'] == 'completed', status
    report = client.call('reports.get', req(run_id=run['run_id']))
    assert report['ok'] and report['data']['overall_acceptance'] == 'accepted', report
    return client, run, status


def _corrupt_generated_candidate(client, run):
    candidates = list(client.root.glob(
        f"runs/{run['run_id']}/attempts/*-paramaterial_case/output/normalized/test_ID_055/sample.h5"))
    assert len(candidates) == 1
    # Fault injection touches generated output only, never original experiment CSVs.
    with candidates[0].open('r+b') as stream:
        stream.seek(1024)
        original = stream.read(1)
        assert len(original) == 1
        stream.seek(1024)
        stream.write(bytes([original[0] ^ 1]))


def test_reports_get_rejects_changed_evidence_after_completed_acceptance(tmp_path):
    client, run, _ = _completed_case(tmp_path)
    _corrupt_generated_candidate(client, run)
    report = client.call('reports.get', req(run_id=run['run_id']))
    assert report['ok'] is False, 'Current reports must authenticate the evidence they claim to accept.'
    assert report['error']['code'] == 'INTEGRITY_MISMATCH'


def test_new_evaluation_clears_current_report_and_failure_cannot_restore_old_acceptance(tmp_path):
    client, run, status = _completed_case(tmp_path)
    _corrupt_generated_candidate(client, run)
    started = client.call('evaluation.start', req(idempotency_key='reevaluate-corruption',
        run_id=run['run_id'], expected_state_version=status['state_version']))
    assert started['ok'], started
    pending_report = client.call('reports.get', req(run_id=run['run_id']))
    # Let the real worker settle even when the subsequent regression assertion fails.
    failed = wait(client, run)
    final_report = client.call('reports.get', req(run_id=run['run_id']))
    assert failed['execution_status'] == 'failed', failed
    assert len(failed['attempts']) == 2
    assert failed['attempts'][0]['execution_status'] == 'completed'
    assert failed['attempts'][1]['execution_status'] == 'failed'
    assert started['data']['acceptance_status'] == 'not_assessed', started
    assert pending_report['ok'], pending_report
    assert pending_report['data']['overall_acceptance'] == 'not_assessed', pending_report
    assert final_report['ok'], final_report
    assert final_report['data']['execution_status'] == 'failed', final_report
    assert final_report['data']['overall_acceptance'] == 'not_assessed', final_report
    assert list(client.root.glob(f"runs/{run['run_id']}/attempts/*-paramaterial_case/acceptance.json"))
