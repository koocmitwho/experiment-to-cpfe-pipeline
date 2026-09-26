"""Material-neutral experimental context, with explicit uncertainty of meaning."""
from datetime import datetime
import json
from typing import Literal

from pydantic import model_validator

from experiment_to_cpfe.datasets.training_config import Contract,Declared


CONTEXT_FIELDS=('protocol_summary','sample_id','batch_id','material_identity','geometry','loading',
    'measurement','acquired_at','instrument_settings','preload','zeroing','trimming','acquisition_software',
    'hold_relaxation','loading_history','thermal_history','temperature','measurement_timing','preprocessing')


class FieldEvidence(Contract):
    status: Literal['confirmed','unconfirmed','unavailable','not_applicable']
    value: object = None
    evidence: Declared

    @model_validator(mode='after')
    def meaningful(self):
        if self.status in ('confirmed','unconfirmed') and self.value is None:
            raise ValueError('confirmed/unconfirmed context needs the declared value')
        if self.status=='unavailable' and self.value is not None:
            raise ValueError('unavailable context cannot carry an asserted value')
        json.dumps(self.value,allow_nan=False)
        return self


def parse_experiment_context(value,*,sample_id,raw_metadata=None):
    if not isinstance(value,dict):raise ValueError('experiment context must be an object')
    fields={}
    for name in CONTEXT_FIELDS:
        field=FieldEvidence.model_validate(value.get(name,dict(status='unavailable',evidence='not supplied in this file or explicit sidecar')))
        if name=='sample_id' and (field.status!='confirmed' or field.value!=sample_id):
            raise ValueError('confirmed experimental sample identity differs from sample metadata')
        if name=='acquired_at' and field.status=='confirmed':
            if not isinstance(field.value,str):raise ValueError('confirmed acquired_at must be an ISO timestamp')
            timestamp=datetime.fromisoformat(field.value)
            if timestamp.tzinfo is None:raise ValueError('confirmed timestamp requires an explicit timezone')
        fields[name]=field.model_dump(mode='json')
    return dict(version=1,fields=fields,unmapped_fields={k:v for k,v in value.items() if k not in CONTEXT_FIELDS},
        unmapped_semantics='unconfirmed',raw_metadata=raw_metadata or {},
        interpretation='confirmed denotes supplied evidence, not automatic physical validation')
