"""Published output contracts reject incomplete evidence without running jobs."""
import copy
import hashlib
import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[3]
CASE = ROOT/'examples'/'paramaterial_tensile'


def contracts():
    return importlib.import_module('experiment_to_cpfe.harness.contracts')


def response(data=None, *, error=None):
    return dict(schema_version='harness.v1',request_id='contract-check',ok=error is None,data=data,error=error)


def request(**kwargs):
    return dict(schema_version='harness.v1',request_id='contract-check',workspace_id='local',**kwargs)


def validated(tool,value):
    module=contracts()
    assert hasattr(module,'validate_response'), 'tool-specific output validator is not implemented'
    return module.validate_response(tool,value)


def test_tool_discovery_has_distinct_required_data_schemas():
    published={item['name']:item for item in contracts().tools()}
    assert published['task.status']['output_schema'] != published['task.plan']['output_schema']
    assert 'plan_digest' in str(published['task.plan']['output_schema'])
    assert 'attempt_id' in str(published['task.status']['output_schema'])
    assert 'criterion_results' in str(published['reports.get']['output_schema'])
    assert 'relative_path' in str(published['artifacts.read']['output_schema'])
    assert 'dependencies' in str(published['capabilities.get']['output_schema'])


def test_real_readonly_and_allocation_responses_match_published_contracts(tmp_path):
    from experiment_to_cpfe.harness import HarnessClient,initialize_workspace
    initialize_workspace(tmp_path/'workspace',CASE)
    client=HarnessClient(tmp_path/'workspace')
    for tool,args in [('capabilities.get',{}),('inputs.validate',{}),
                      ('task.plan',{'workflow_id':'paramaterial_tensile.v1'}),
                      ('task.create',{'workflow_id':'paramaterial_tensile.v1','idempotency_key':'create'})]:
        result=client.call(tool,request(**args))
        assert result['ok'], result
        assert validated(tool,result)==result
    run_id=result['data']['run_id']
    for tool in ['task.status','reports.get','events.list','artifacts.list','handoffs.list']:
        result=client.call(tool,request(run_id=run_id))
        assert result['ok'], result
        assert validated(tool,result)==result
    source=CASE/'data/test_ID_055.csv'
    result=client.call('inputs.register',request(idempotency_key='register',relative_path='data/test_ID_055.csv',
                       expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    assert result['ok'],result
    assert validated('inputs.register',result)==result
    assert not list((tmp_path/'workspace'/'runs').iterdir())


@pytest.mark.parametrize('tool', ['capabilities.get','inputs.register','inputs.validate','task.plan','task.status',
                                  'task.create','task.start','task.reconcile','task.control','evaluation.start',
                                  'handoffs.submit','events.list','artifacts.list','handoffs.list','reports.get','artifacts.read','runs.list'])
def test_empty_success_data_is_never_a_valid_tool_result(tool):
    with pytest.raises(ValidationError):
        validated(tool,response({}))


def test_each_plan_field_is_required_and_nested_dependencies_are_typed():
    plan=dict(dry_run=True,plan_digest='a'*64,workflow_id='paramaterial_tensile.v1',
              stages=[{'id':'paramaterial_case','depends_on':[]}],
              budget=dict(wall_seconds=600.,storage_bytes=1073741824,retries=1,cpu=1,gpu=0,model_calls=0),
              confirmations=[],estimates=dict(cpu=1,gpu=0,model_calls=0,wall_seconds=None,basis='not_benchmarked'))
    assert validated('task.plan',response(plan))==response(plan)
    for field in plan:
        damaged=copy.deepcopy(plan); damaged.pop(field)
        with pytest.raises(ValidationError):
            validated('task.plan',response(damaged))
    plan['stages'][0]['depends_on']='guess'
    with pytest.raises(ValidationError):
        validated('task.plan',response(plan))


def test_completed_acceptance_requires_independent_layers_but_preserves_extensions():
    report=dict(format='experiment-to-cpfe-harness-acceptance-1',execution_status='completed',
                engineering_status='passed',data_status='passed',protocol_status='valid',
                numerical_checks={'status':'passed','absolute_tolerance':1e-7,'mesh_jacobian_solver_terminal':'not_applicable'},
                criterion_results=[{'criterion_id':'sample.UTS','value':1.,'reference':1.,'unit':'MPa',
                                    'absolute_tolerance':1e-7,'status':'met'}],
                scientific_claim_status='not_established',overall_acceptance='accepted',semantic_sha256='a'*64,
                issues=[],scope_limits=['Fixed-case arithmetic only.'],additional_verifier_evidence={'receipt':'kept'})
    assert validated('reports.get',response(report))==response(report)
    for field in ['engineering_status','data_status','numerical_checks','criterion_results','scientific_claim_status','protocol_status']:
        damaged=copy.deepcopy(report);damaged.pop(field)
        with pytest.raises(ValidationError):
            validated('reports.get',response(damaged))


@pytest.mark.parametrize('view',[
    {'view':'summary','relative_path':'sample.h5','sha256':'a'*64,'size_bytes':20,'media_type':'application/x-hdf5'},
    {'view':'json','data':{'state':'completed','future':{'value':1}}},
    {'view':'json','items':[{'sample':1}],'offset':0,'limit':2,'total':1,'next_offset':None},
    {'view':'text','items':['row'],'offset':0,'limit':2,'total':None,'next_offset':None},
    {'view':'csv','items':[{'id':'a'}],'columns':['id'],'offset':0,'limit':2,'total':None,'next_offset':None},
    {'view':'hdf5','items':[[1.,2.]],'dataset':'stress','shape':[1,2],'dtype':'float64',
     'offset':0,'limit':2,'total':1,'next_offset':None},
])
def test_artifact_view_variants_are_explicit_and_preserve_data(view):
    assert validated('artifacts.read',response(view))==response(view)
    missing=copy.deepcopy(view);missing.pop('view')
    with pytest.raises(ValidationError):
        validated('artifacts.read',response(missing))


def test_artifact_and_event_pages_require_item_identity_and_cursor():
    artifact=dict(artifact_id='artifact_'+'a'*32,attempt_id='attempt_'+'a'*32,
                  relative_path='a.json',sha256='b'*64,size_bytes=3,media_type='application/json',
                  acceptance_status='accepted',datasets=[])
    event=dict(seq=1,run_id='run_'+'a'*32,attempt_id=None,time='2026-10-08T00:00:00+00:00',
               kind='task_frozen',data={'fingerprint':'c'*64,'future_record':True})
    for tool,item in [('artifacts.list',artifact),('events.list',event)]:
        page=dict(items=[item],next_cursor=1)
        assert validated(tool,response(page))==response(page)
        damaged=copy.deepcopy(page)
        damaged['items'][0].pop('artifact_id' if tool=='artifacts.list' else 'seq')
        with pytest.raises(ValidationError):
            validated(tool,response(damaged))


def test_error_catalog_declares_actual_codes_and_never_guesses_from_message():
    published={item['name']:item for item in contracts().tools()}
    for tool,code in [('task.status','NOT_FOUND'),('task.create','PLAN_STALE'),('handoffs.submit','EVIDENCE_STALE'),
                      ('task.control','BUDGET_EXCEEDED'),('inputs.register','HASH_MISMATCH'),
                      ('task.create','MISSING_METADATA'),('task.start','ENVIRONMENT_CHANGED')]:
        assert code in published[tool]['errors']
        error=contracts().HarnessError(code,'This message deliberately contains unrelated words.').record()
        assert validated(tool,response(error=error))['error']['code']==code
    unknown=contracts().HarnessError('MADE_UP','hash').record()
    with pytest.raises(ValidationError):
        validated('task.status',response(error=unknown))


def test_envelope_never_claims_success_with_an_error_or_failure_without_an_error():
    error=contracts().HarnessError('NOT_FOUND','Registered run is absent.').record()
    broken=response(error=error);broken['ok']=True
    with pytest.raises(ValidationError):
        validated('task.status',broken)
    broken=response();broken['ok']=False
    with pytest.raises(ValidationError):
        validated('task.status',broken)


def test_handoff_records_require_binding_and_quiescence_evidence():
    item=dict(handoff_id='handoff_'+'a'*32,attempt_id='attempt_'+'a'*32,state='pending',
              binding='b'*64,required_evidence='registered_artifact_ids',quiesced=True)
    assert validated('handoffs.list',response(dict(items=[item],next_cursor=None)))['data']['items']==[item]
    item.pop('binding')
    with pytest.raises(ValidationError):
        validated('handoffs.list',response(dict(items=[item],next_cursor=None)))


def test_discovery_declares_preconditions_and_real_execution_side_effects():
    published={item['name']:item for item in contracts().tools()}
    assert all(item.get('preconditions') for item in published.values())
    for name in ('task.start','evaluation.start','handoffs.submit'):
        assert 'spawn_worker' in published[name]['side_effects']
        assert 'write_artifacts' in published[name]['side_effects']
    assert 'freeze_run_snapshot' in published['task.create']['side_effects']
    assert 'register_input_reference' in published['inputs.register']['side_effects']
    assert 'frozen_snapshot_matches' in published['task.start']['preconditions']
    assert all(item['side_effects']!=['persistent_state'] for item in published.values())
    assert all(item['side_effects']==[] for item in published.values() if item['read_only'])


def test_reconcile_discovery_discloses_conditional_dispatch_and_seal_publication():
    tool=next(item for item in contracts().tools() if item['name']=='task.reconcile')
    assert {'spawn_worker','register_artifact_references','publish_verified_report'}<=set(tool['side_effects'])
    conditions={entry['condition']:entry['side_effects'] for entry in tool['conditional_effects']}
    assert 'spawn_worker' in conditions['queued_without_execution_owner']
    assert 'register_artifact_references' in conditions['stopped_with_verified_seal']
    assert 'spawn_worker' not in conditions['worker_identity_uncertain']


def test_control_discovery_exposes_action_specific_states_and_obligations():
    tool=next(item for item in contracts().tools() if item['name']=='task.control')
    actions=tool['action_contracts']
    assert set(actions)=={'pause','cancel','resume','retry'}
    assert 'stage_boundary_only' in actions['pause']['limitations']
    assert 'terminate_owned_process_tree' in actions['cancel']['side_effects']
    assert 'termination_confirmed_before_cancelled' in actions['cancel']['postconditions']
    assert actions['resume']['applicable_run_states']==['paused']
    assert 'pending_human_review_cannot_be_bypassed' in actions['resume']['postconditions']
    assert {'exact_failed_attempt_and_stage','retry_and_wall_budget_available','frozen_snapshot_matches'}<=set(actions['retry']['preconditions'])
    assert 'allocate_new_attempt' in actions['retry']['side_effects']
    assert 'preserve_previous_attempt' in actions['retry']['postconditions']
