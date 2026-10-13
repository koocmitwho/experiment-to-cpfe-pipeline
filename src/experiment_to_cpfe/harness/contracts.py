"""Versioned request schemas and transport-independent errors."""
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class HarnessError(Exception):
    def __init__(self, code, message, *, retryable=False, field=None, action=None):
        self.code, self.message = code, message
        self.retryable, self.field, self.action = retryable, field, action
        super().__init__(message)

    def record(self):
        return dict(code=self.code, retryable=self.retryable,
                    retry_scope='same_request' if self.retryable else 'none',
                    field=self.field, safe_message=self.message,
                    required_action=self.action, evidence_ids=[], retry_after_seconds=None)


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Request(Strict):
    schema_version: Literal['harness.v1']
    request_id: str = Field(min_length=1, max_length=128)
    workspace_id: Literal['local']


class Budget(Strict):
    wall_seconds: float = Field(default=600, gt=0, le=86400)
    storage_bytes: int = Field(default=1073741824, gt=0)
    retries: int = Field(default=1, ge=0, le=10)
    cpu: Literal[1] = 1
    gpu: Literal[0] = 0
    model_calls: Literal[0] = 0


class Plan(Request):
    workflow_id: str
    budget: Budget = Field(default_factory=Budget)
    require_review: bool = False


class Create(Plan):
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_plan_digest: str | None = None
    replicate: bool = False


class Run(Request):
    run_id: str = Field(pattern=r'^run_[a-f0-9]{32}$')


class Mutation(Run):
    idempotency_key: str = Field(min_length=1, max_length=128)


class Start(Mutation):
    expected_state_version: int = Field(ge=1)


class Control(Start):
    action: Literal['pause', 'cancel', 'resume', 'retry']
    reason: str = Field(min_length=1, max_length=1024)
    stage: Literal['paramaterial_case', 'acceptance'] = 'paramaterial_case'
    attempt_id: str | None = None


class Page(Run):
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class RunsPage(Request):
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class ReadArtifact(Request):
    artifact_id: str = Field(pattern=r'^artifact_[a-f0-9]{32}$')
    view: Literal['summary', 'json', 'text', 'csv', 'hdf5'] = 'summary'
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)
    columns: list[str] | None = None
    dataset: str | None = None


class SubmitHandoff(Start):
    handoff_id: str
    attempt_id: str
    approval_id: str
    evidence_ids: list[str] = Field(min_length=1, max_length=30)


class RegisterInput(Request):
    idempotency_key: str = Field(min_length=1, max_length=128)
    relative_path: str
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


TOOLS = {
    'capabilities.get': (Request, False, 'Read registered workflow, environment and supported controls.'),
    'inputs.register': (RegisterInput, True, 'Register a file under the operator-approved case root; never modify it.'),
    'inputs.validate': (Request, False, 'Check the registered fixed case, units, metadata and content hashes without execution.'),
    'task.plan': (Plan, False, 'Read-only plan; no solver probes, output directories or worker creation.'),
    'task.create': (Create, True, 'Freeze a task and run; identical requests are deduplicated.'),
    'task.start': (Start, True, 'Queue a new attempt and return immediately. Does not mean accepted.'),
    'task.status': (Run, False, 'Read durable state and live process observation; does not resubmit work.'),
    'task.reconcile': (Mutation, True, 'Reconcile a stopped or missing worker; never repeat uncertain computation.'),
    'task.control': (Control, True, 'Request boundary pause, cancellation, resume or a new immutable retry attempt.'),
    'events.list': (Page, False, 'Read durable ordered events with cursor pagination.'),
    'artifacts.list': (Page, False, 'List sealed output references; incomplete attempt files are not accepted artifacts.'),
    'artifacts.read': (ReadArtifact, False, 'Read a bounded approved artifact view after integrity checks.'),
    'evaluation.start': (Start, True, 'Queue deterministic re-evaluation of verified frozen outputs; no threshold overrides.'),
    'reports.get': (Run, False, 'Read independent engineering, data, numerical and scientific conclusions.'),
    'handoffs.list': (Page, False, 'Read handoff requests at a quiescent stage boundary.'),
    'handoffs.submit': (SubmitHandoff, True, 'Submit operator-approved evidence for revalidation; no self-approval.'),
    'runs.list': (RunsPage, False, 'List registered runs newest first from durable state; no worker probe or evidence check.'),
}


CASE_ERRORS = (
    'PATH_NOT_ALLOWED', 'MISSING_INPUT', 'INPUT_TOO_LARGE', 'SOURCE_HASH_MISMATCH',
    'INPUT_UNREADABLE', 'MISSING_METADATA', 'SPECIMEN_IDENTITY_MISMATCH',
    'INVALID_UNITS', 'ROW_COUNT_MISMATCH', 'INVALID_MANIFEST', 'INVALID_CURVE',
)
COMMON_ERRORS = ('INVALID_REQUEST', 'WORKSPACE_DENIED', 'UNSUPPORTED', 'FILE_UNAVAILABLE',
                 'INTEGRITY_MISMATCH', 'INTERNAL_RESPONSE_INVALID', 'STORE_UNAVAILABLE', 'INTERNAL_ERROR')
ERROR_CODES = (*COMMON_ERRORS, *CASE_ERRORS, 'NOT_FOUND', 'STATE_CONFLICT', 'PRECONDITION_FAILED',
               'BUDGET_EXCEEDED', 'IDEMPOTENCY_CONFLICT', 'PLAN_STALE', 'HASH_MISMATCH',
               'INPUT_CHANGED', 'ENVIRONMENT_CHANGED', 'POLICY_CHANGED', 'EXECUTION_UNCERTAIN',
               'RETRY_NOT_ALLOWED', 'EVIDENCE_STALE', 'APPROVAL_REQUIRED', 'COMPUTATION_FAILED',
               'EVIDENCE_INVALID')
ErrorCode = Literal[*ERROR_CODES]


class ErrorRecord(Strict):
    code: ErrorCode
    retryable: bool
    retry_scope: Literal['none', 'same_request', 'new_attempt', 'after_operator_action']
    field: str | None
    safe_message: str
    required_action: str | None
    evidence_ids: list[str]
    retry_after_seconds: float | None


class Response(Strict):
    schema_version: Literal['harness.v1'] = 'harness.v1'
    request_id: str
    ok: bool
    data: dict | None
    error: ErrorRecord | None


class Output(BaseModel):
    """Required stable fields with explicit, preserved forward-compatible evidence."""
    model_config = ConfigDict(extra='allow', strict=True, allow_inf_nan=False)


Hash = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
Nonblank = Annotated[str, Field(min_length=1)]
TaskId = Annotated[str, Field(pattern=r'^task_[a-f0-9]{32}$')]
RunId = Annotated[str, Field(pattern=r'^run_[a-f0-9]{32}$')]
AttemptId = Annotated[str, Field(pattern=r'^attempt_[a-f0-9]{32}$')]
ArtifactId = Annotated[str, Field(pattern=r'^artifact_[a-f0-9]{32}$')]
ExecutionState = Literal['ready', 'queued', 'waiting_resource', 'running', 'pause_requested',
    'paused', 'cancel_requested', 'reconciling', 'waiting_human', 'blocked', 'completed',
    'failed', 'cancelled', 'interrupted', 'unknown']
AcceptanceState = Literal['not_assessed', 'accepted', 'rejected', 'blocked', 'not_evaluated', 'criteria_met', 'failed_evidence']


class BudgetOutput(Output):
    wall_seconds: float = Field(gt=0)
    storage_bytes: int = Field(gt=0)
    retries: int = Field(ge=0)
    cpu: Literal[1]
    gpu: Literal[0]
    model_calls: Literal[0]


class EnvironmentOutput(Output):
    python_executable: Nonblank
    python_version: list[int] = Field(min_length=3, max_length=3)
    dependencies: dict[str, Any] = Field(description='Recorded distribution versions and code hashes; keys may expand.')
    package_code_sha256: Hash


class ControlsOutput(Output):
    pause: Nonblank
    cancel: Nonblank
    retry: Nonblank


class EnforcementOutput(Output):
    cpu: Nonblank
    storage: Nonblank
    wall_time: Nonblank
    gpu: Nonblank


class CapabilitiesOutput(Output):
    workflows: list[str]
    backends: list[str]
    formats: list[str]
    environment: EnvironmentOutput
    unsupported: list[str]
    controls: ControlsOutput
    resource_enforcement: EnforcementOutput
    limits: BudgetOutput
    access_boundary: Nonblank


class IssueOutput(Output):
    code: Nonblank
    field: str | None
    safe_message: Nonblank


class InputValidationOutput(Output):
    valid: bool
    issues: list[IssueOutput]
    files: dict[str, Hash]
    workflow_id: Nonblank
    specimen_ids: list[str]
    total_rows: int = Field(ge=0)


class InputRegistrationOutput(Output):
    input_id: str = Field(pattern=r'^input_[a-f0-9]{32}$')
    sha256: Hash
    size_bytes: int = Field(ge=0)


class StagePlanOutput(Output):
    id: Nonblank
    depends_on: list[str]


class ResourceEstimateOutput(Output):
    cpu: int = Field(ge=0)
    gpu: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    wall_seconds: float | None = Field(ge=0)
    basis: Nonblank


class PlanOutput(Output):
    dry_run: Literal[True]
    plan_digest: Hash
    workflow_id: Nonblank
    stages: list[StagePlanOutput] = Field(min_length=1)
    budget: BudgetOutput
    confirmations: list[str]
    estimates: ResourceEstimateOutput


class AttemptOutput(Output):
    attempt_id: AttemptId
    number: int = Field(ge=1)
    stage: Literal['paramaterial_case', 'acceptance']
    execution_status: ExecutionState
    elapsed_seconds: float = Field(ge=0)
    reason_code: str | None


class ProgressOutput(Output):
    kind: Literal['stage']
    fraction: float | None = Field(ge=0, le=1)
    source: Nonblank


class StatusOutput(Output):
    task_id: TaskId
    run_id: RunId
    attempt_id: AttemptId | None
    execution_status: ExecutionState
    state_version: int = Field(ge=1)
    reason_code: str | None
    consumed_wall_seconds: float = Field(ge=0)
    budget: BudgetOutput
    attempts: list[AttemptOutput]
    progress: ProgressOutput
    acceptance_status: AcceptanceState
    worker_observation: Literal['running', 'stopped', 'unknown'] | None = None
    required_action: str | None = None
    deduplicated: bool | None = Field(default=None, description='task.create only: an equivalent frozen run was returned.')


class EventOutput(Output):
    seq: int = Field(ge=1)
    run_id: RunId
    attempt_id: AttemptId | None
    time: Nonblank
    kind: Nonblank
    data: dict[str, Any] = Field(description='Event-specific immutable evidence; keys depend on kind.')


class ArtifactMetadataOutput(Output):
    relative_path: Nonblank
    sha256: Hash
    size_bytes: int = Field(ge=0)
    media_type: Nonblank


class ArtifactOutput(ArtifactMetadataOutput):
    artifact_id: ArtifactId
    attempt_id: AttemptId
    acceptance_status: AcceptanceState
    datasets: list[str] | None = Field(default=None, description='Explicitly authorized HDF5 datasets, when available.')


class HandoffOutput(Output):
    handoff_id: Nonblank
    attempt_id: AttemptId
    state: Literal['pending', 'approved', 'revalidating', 'verified']
    binding: Hash
    required_evidence: Literal['registered_artifact_ids']
    quiesced: Literal[True]


Item = TypeVar('Item')


class PageOutput(Output, Generic[Item]):
    items: list[Item] = Field(max_length=500)
    next_cursor: int | None = Field(ge=0)


class RunSummaryOutput(Output):
    task_id: TaskId
    run_id: RunId
    workflow_id: Nonblank
    created_at: Nonblank
    execution_status: ExecutionState
    state_version: int = Field(ge=1)
    reason_code: str | None
    acceptance_status: AcceptanceState = Field(description='Recorded report state; evidence is not re-verified by listing.')
    attempt_count: int = Field(ge=0)
    current_attempt_id: AttemptId | None
    current_stage: Literal['paramaterial_case', 'acceptance'] | None
    review_required: bool


class RunsPageOutput(PageOutput[RunSummaryOutput]):
    total: int = Field(ge=0)


class SummaryView(ArtifactMetadataOutput):
    view: Literal['summary']


class SliceView(Output):
    items: list[Any] = Field(max_length=500)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    total: int | None = Field(ge=0)
    next_offset: int | None = Field(ge=0)


class JsonPageView(SliceView):
    view: Literal['json']


class JsonObjectView(Output):
    view: Literal['json']
    data: dict[str, Any] = Field(description='Small JSON artifact object; original fields are retained.')


class TextView(SliceView):
    view: Literal['text']
    items: list[str] = Field(max_length=500)


class CsvView(SliceView):
    view: Literal['csv']
    items: list[dict[str, str]] = Field(max_length=500)
    columns: list[str] = Field(min_length=1)


class Hdf5View(SliceView):
    view: Literal['hdf5']
    dataset: Nonblank
    shape: list[int]
    dtype: Nonblank


ArtifactViewOutput = SummaryView | JsonPageView | JsonObjectView | TextView | CsvView | Hdf5View


class CriterionOutput(Output):
    criterion_id: Nonblank
    value: float
    reference: float
    unit: Nonblank
    absolute_tolerance: float = Field(ge=0)
    status: Literal['met', 'not_met']


class NumericalOutput(Output):
    status: Literal['passed', 'failed', 'not_evaluated']
    absolute_tolerance: float = Field(ge=0)
    mesh_jacobian_solver_terminal: Literal['not_applicable']


class AcceptanceReportOutput(Output):
    format: Literal['experiment-to-cpfe-harness-acceptance-1']
    execution_status: ExecutionState
    engineering_status: Literal['passed', 'failed']
    data_status: Literal['passed', 'failed']
    numerical_checks: NumericalOutput
    protocol_status: Literal['valid', 'invalid']
    criterion_results: list[CriterionOutput]
    scientific_claim_status: Literal['not_established']
    overall_acceptance: Literal['accepted', 'rejected']
    semantic_sha256: Hash | None
    issues: list[IssueOutput]
    scope_limits: list[str] = Field(min_length=1)


class PendingReportOutput(Output):
    execution_status: ExecutionState
    overall_acceptance: Literal['not_assessed']


DATA_MODELS = {
    'capabilities.get': CapabilitiesOutput,
    'inputs.register': InputRegistrationOutput,
    'inputs.validate': InputValidationOutput,
    'task.plan': PlanOutput,
    **{name: StatusOutput for name in ('task.create', 'task.start', 'task.status', 'task.reconcile',
                                      'task.control', 'evaluation.start', 'handoffs.submit')},
    'events.list': PageOutput[EventOutput],
    'artifacts.list': PageOutput[ArtifactOutput],
    'artifacts.read': ArtifactViewOutput,
    'reports.get': AcceptanceReportOutput | PendingReportOutput,
    'handoffs.list': PageOutput[HandoffOutput],
    'runs.list': RunsPageOutput,
}


class SuccessfulResponse(Strict, Generic[Item]):
    schema_version: Literal['harness.v1']
    request_id: str
    ok: Literal[True]
    data: Item
    error: None


class FailedResponse(Strict):
    schema_version: Literal['harness.v1']
    request_id: str
    ok: Literal[False]
    data: None
    error: ErrorRecord


RESPONSE_ADAPTERS = {
    name: TypeAdapter(Annotated[SuccessfulResponse[data_model] | FailedResponse, Field(discriminator='ok')])
    for name, data_model in DATA_MODELS.items()
}


_FROZEN_ERRORS = ('INPUT_CHANGED', 'ENVIRONMENT_CHANGED', 'POLICY_CHANGED')
TOOL_ERRORS = {
    'capabilities.get': (),
    'inputs.register': ('IDEMPOTENCY_CONFLICT', 'HASH_MISMATCH', 'INPUT_CHANGED'),
    'inputs.validate': (),
    'task.plan': (*CASE_ERRORS, 'BUDGET_EXCEEDED', 'PRECONDITION_FAILED'),
    'task.create': (*CASE_ERRORS, 'BUDGET_EXCEEDED', 'IDEMPOTENCY_CONFLICT', 'PLAN_STALE', 'PRECONDITION_FAILED'),
    'task.start': ('NOT_FOUND', 'IDEMPOTENCY_CONFLICT', 'STATE_CONFLICT', 'PRECONDITION_FAILED', *_FROZEN_ERRORS),
    'task.status': ('NOT_FOUND',),
    'task.reconcile': ('NOT_FOUND', 'IDEMPOTENCY_CONFLICT', 'EVIDENCE_INVALID'),
    'task.control': ('NOT_FOUND', 'IDEMPOTENCY_CONFLICT', 'STATE_CONFLICT', 'PRECONDITION_FAILED',
                     'EXECUTION_UNCERTAIN', 'RETRY_NOT_ALLOWED', 'BUDGET_EXCEEDED', *_FROZEN_ERRORS),
    'events.list': ('NOT_FOUND',),
    'artifacts.list': ('NOT_FOUND',),
    'artifacts.read': ('NOT_FOUND',),
    'evaluation.start': ('NOT_FOUND', 'IDEMPOTENCY_CONFLICT', 'STATE_CONFLICT', 'PRECONDITION_FAILED', *_FROZEN_ERRORS),
    'reports.get': ('NOT_FOUND',),
    'handoffs.list': ('NOT_FOUND',),
    'runs.list': (),
    'handoffs.submit': ('NOT_FOUND', 'IDEMPOTENCY_CONFLICT', 'STATE_CONFLICT', 'APPROVAL_REQUIRED',
                        'EVIDENCE_STALE', *_FROZEN_ERRORS),
}


def validate_response(tool: str, response: dict) -> dict:
    """Validate before publication; never infer result/error codes from prose.

    Raises Pydantic ValidationError for a malformed response. Service callers
    must map this producer defect to INTERNAL_RESPONSE_INVALID, not INVALID_REQUEST.
    Unknown tools can only publish the stable error envelope.
    """
    adapter = RESPONSE_ADAPTERS.get(tool)
    model = adapter.validate_python(response) if adapter is not None else FailedResponse.model_validate(response)
    return model.model_dump(mode='json', exclude_unset=True)


_PLAN_PRECONDITIONS = ('registered_workflow', 'fixed_case_inputs_valid',
                       'registered_dependencies_available', 'budget_within_operator_limits')
_EXECUTION_EFFECTS = ('allocate_new_attempt', 'spawn_worker', 'execute_registered_stage',
                      'write_artifacts', 'record_events', 'charge_run_budget')
TOOL_PRECONDITIONS = {
    'capabilities.get': (),
    'inputs.register': ('path_within_case_root', 'expected_input_hash_matches'),
    'inputs.validate': ('registered_case_root',),
    'task.plan': _PLAN_PRECONDITIONS,
    'task.create': (*_PLAN_PRECONDITIONS, 'supplied_plan_digest_matches'),
    'task.start': ('run_state_ready', 'expected_state_version_matches', 'frozen_snapshot_matches',
                   'verified_execution_platform'),
    'task.status': ('registered_run',),
    'task.reconcile': ('registered_run',),
    'task.control': ('registered_run', 'expected_state_version_matches', 'selected_action_preconditions'),
    'events.list': ('registered_run',),
    'artifacts.list': ('registered_run',),
    'artifacts.read': ('registered_artifact', 'authorized_artifact_path', 'artifact_hash_matches',
                       'bounded_view_supported', 'hdf5_dataset_registered_when_requested'),
    'evaluation.start': ('run_state_completed', 'expected_state_version_matches', 'frozen_snapshot_matches',
                         'frozen_candidate_integrity_verified_before_evaluation'),
    'reports.get': ('registered_run', 'current_report_evidence_verified_when_present'),
    'handoffs.list': ('registered_run',),
    'runs.list': (),
    'handoffs.submit': ('run_state_waiting_human', 'expected_state_version_matches', 'exact_handoff_attempt',
                        'operator_approval_matches', 'approved_evidence_ids_match', 'frozen_snapshot_matches'),
}
TOOL_SIDE_EFFECTS = {
    'inputs.register': ('register_input_reference', 'record_idempotency_result'),
    'task.create': ('allocate_task_and_run', 'freeze_run_snapshot', 'record_events', 'record_idempotency_result'),
    'task.start': _EXECUTION_EFFECTS,
    'task.reconcile': ('observe_process_identity', 'change_run_or_attempt_state', 'settle_observed_budget',
                       'register_artifact_references', 'publish_verified_report', 'spawn_worker',
                       'write_launch_logs', 'record_events'),
    'task.control': ('change_run_or_attempt_state', 'terminate_owned_process_tree', 'settle_observed_budget',
                     'allocate_new_attempt', 'spawn_worker', 'write_artifacts', 'open_human_handoff', 'record_events'),
    'evaluation.start': (*_EXECUTION_EFFECTS, 'clear_current_report', 'revalidate_frozen_candidate'),
    'handoffs.submit': (*_EXECUTION_EFFECTS, 'mark_handoff_revalidating', 'revalidate_approved_evidence'),
}
CONTROL_ACTION_CONTRACTS = {
    'pause': dict(applicable_run_states=['ready', 'queued', 'waiting_resource', 'running'],
        preconditions=['expected_state_version_matches'],
        side_effects=['request_stage_boundary_pause', 'record_events'],
        limitations=['stage_boundary_only', 'running_computation_continues_until_boundary'],
        postconditions=['do_not_claim_paused_until_quiescent_boundary']),
    'cancel': dict(applicable_run_states=['ready', 'queued', 'waiting_resource', 'running', 'pause_requested',
                                          'paused', 'cancel_requested', 'reconciling', 'waiting_human', 'blocked'],
        preconditions=['expected_state_version_matches', 'run_not_terminal'],
        side_effects=['terminate_owned_process_tree', 'settle_observed_budget', 'record_events'],
        limitations=['unconfirmed_stop_remains_cancel_requested', 'no_artifact_cleanup'],
        postconditions=['termination_confirmed_before_cancelled', 'preserve_previous_attempt']),
    'resume': dict(applicable_run_states=['paused'],
        preconditions=['expected_state_version_matches', 'frozen_snapshot_matches', 'previous_execution_stopped'],
        side_effects=['requeue_unexecuted_stage_or_allocate_acceptance', 'spawn_worker', 'write_artifacts',
                      'open_human_handoff_when_review_pending', 'record_events'],
        limitations=['stage_boundary_only', 'no_arbitrary_solver_checkpoint_restore'],
        postconditions=['pending_human_review_cannot_be_bypassed']),
    'retry': dict(applicable_run_states=['failed', 'interrupted', 'blocked'],
        preconditions=['expected_state_version_matches', 'exact_failed_attempt_and_stage',
                       'retry_and_wall_budget_available', 'frozen_snapshot_matches'],
        side_effects=['allocate_new_attempt', 'spawn_worker', 'write_artifacts', 'charge_run_budget', 'record_events'],
        limitations=['failed_or_interrupted_attempt_only', 'no_budget_increase'],
        postconditions=['preserve_previous_attempt']),
}
RECONCILE_CONDITIONS = [
    dict(condition='queued_without_execution_owner', side_effects=['spawn_worker', 'write_launch_logs'],
         guarantee='Worker must acquire the durable nonce before computation.'),
    dict(condition='stopped_with_verified_seal', side_effects=['register_artifact_references',
         'publish_verified_report', 'settle_observed_budget', 'record_events'],
         guarantee='Reuse the verified seal; do not rerun computation.'),
    dict(condition='stopped_without_verified_seal', side_effects=['mark_interrupted_or_blocked',
         'settle_observed_budget', 'record_events'], guarantee='No automatic scientific retry.'),
    dict(condition='worker_identity_uncertain', side_effects=['preserve_control_request_or_mark_reconciling',
         'record_events'], guarantee='Do not dispatch uncertain execution.'),
]


def tools():
    return [dict(name=name, description=description,
                 input_schema=model.model_json_schema(), output_schema=RESPONSE_ADAPTERS[name].json_schema(),
                 preconditions=['authorized_workspace', *TOOL_PRECONDITIONS[name]],
                 side_effects=list(TOOL_SIDE_EFFECTS.get(name, ())),
                 conditional_effects=RECONCILE_CONDITIONS if name == 'task.reconcile' else [],
                 action_contracts=CONTROL_ACTION_CONTRACTS if name == 'task.control' else {},
                 read_only=not writes, idempotent=True,
                 errors=list(dict.fromkeys((*COMMON_ERRORS, *TOOL_ERRORS[name]))))
            for name, (model, writes, description) in TOOLS.items()]
