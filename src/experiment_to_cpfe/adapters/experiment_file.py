"""Explicit self-describing JSON and BAM LIS file adapters. No instrument control."""
from pathlib import Path
from typing import Literal

from pydantic import Field,model_validator

from experiment_to_cpfe.adapters.tabular import assemble_sample
from experiment_to_cpfe.assets.models import AssetRef,DataLayer
from experiment_to_cpfe.config import SampleConfig
from experiment_to_cpfe.datasets.experiment_context import parse_experiment_context
from experiment_to_cpfe.datasets.hdf5 import write_hdf5,read_hdf5
from experiment_to_cpfe.datasets.normalization import validate_normalization_config
from experiment_to_cpfe.adapters.bam_lis import BamLISConfig,read_identity,read_sample
from experiment_to_cpfe.datasets.training_config import Contract,Declared
from experiment_to_cpfe.provenance.records import FileRef,artifact,bound_json,recorded_operation,write_record
from experiment_to_cpfe.pipeline import _default_policy_path
from experiment_to_cpfe.provenance.hashing import sha256_file
from experiment_to_cpfe.schema.models import SourceRef
from experiment_to_cpfe.schema.validation import validate_sample,load_validation_policy


class ScriptRef(FileRef):
    version: Declared
    purpose: Declared


class ExperimentFileConfig(Contract):
    version: Literal[1]
    purpose: Declared
    profile: Literal['self_describing_json_v1','bam_lis_context_v1']
    source: FileRef
    license: Declared
    evidence_scope: Literal['synthetic_mechanism_only','experimental']
    bam_task: FileRef | None = None
    scripts: list[ScriptRef] = Field(default_factory=list,max_length=32)

    @model_validator(mode='after')
    def profile_arguments(self):
        if (self.profile=='bam_lis_context_v1')!=(self.bam_task is not None):
            raise ValueError('bam_task is required only for explicit BAM profile')
        return self


def _json_sample(config,base,output):
    value,path=bound_json(config.source,base)
    if value.get('format')!='self-describing-experiment-1':raise ValueError('unsupported self-describing file format')
    sample_config=SampleConfig.model_validate(value['sample']);data=value['measurements']
    if not isinstance(data,dict) or set(data)!={'units','rows'} or not isinstance(data['rows'],list) or not data['rows']:
        raise ValueError('measurements need explicit units and nonempty rows')
    units=data['units']
    if not isinstance(units,dict) or not units or any(not isinstance(row,dict) or set(row)!=set(units) for row in data['rows']):
        raise ValueError('measurement row fields must match the declared unit keys')
    for key,unit in units.items():
        if key in sample_config.unit_system and unit!=sample_config.unit_system[key]:
            raise ValueError('measurement unit conflicts with sample unit declaration')
    context=parse_experiment_context(value.get('context',{}),sample_id=sample_config.sample_id,
        raw_metadata={k:v for k,v in value.items() if k!='measurements'})
    raw_rows=output/'measurement-rows.json';write_record(raw_rows,data['rows'])
    source_kind='measured' if config.evidence_scope=='experimental' else 'input'
    normalization=validate_normalization_config(dict(version=1,purpose=config.purpose,sample=sample_config.model_dump(mode='json'),
        sources=[dict(path=str(raw_rows),table_name='measured_observations',source_kind=source_kind,modality='time_series',
            format='json',delimiter=None,encoding='utf-8',column_map={key:key for key in units},units=units,
            coordinate_frame=sample_config.coordinate.name,axis_order=['row'],native_layout='explicit self-describing JSON measurement rows',license=config.license)]))
    sample=assemble_sample(normalization)
    original=AssetRef(asset_id='experiment-source',parent_asset_id=None,modality='time_series',format='self-describing-experiment-json',
        uri=str(path),source_kind=source_kind,layer='raw',units=units,coordinate_frame=sample_config.coordinate.name,
        axis_order=('row',),dtype='table',shape=(len(data['rows']),len(units)),native_layout='self-describing-experiment-1',
        sha256=config.source.sha256,license=config.license,lossy_transformations=(),descriptive_metadata={'experiment_context':context})
    # Preserve the original file as the root of the generated row-file lineage.
    sample.assets=(original,*(a.model_copy(update={'parent_asset_id':'experiment-source','layer':DataLayer.CURATED,
        'lossy_transformations':('measurement rows extracted; complete metadata preserved separately',)})
        if a.parent_asset_id is None else a for a in sample.assets))
    sample.metadata.sources=(*sample.metadata.sources,SourceRef(kind=source_kind,uri=str(path),sha256=config.source.sha256,role='original experimental file'))
    return sample,context


def _confirmed(value,evidence):
    return dict(status='confirmed',value=value,evidence=evidence)


def _bam_sample(config,base):
    path=(base/config.source.path).resolve()
    if sha256_file(path)!=config.source.sha256:raise ValueError('BAM source hash mismatch')
    value,_=bound_json(config.bam_task,base);task=BamLISConfig.model_validate(value)
    if task.profile!='bam_lis_tensile_v1' or task.license!=config.license or not task.identity_evidence.strip():
        raise ValueError('BAM profile, license and identity evidence must match the declared existing task')
    identity=read_identity(path)
    source_kind='measured' if config.evidence_scope=='experimental' else 'input'
    sample=read_sample(path,identity,task,source_kind=source_kind)
    text=path.read_text(encoding='cp1252');header=text.split('[Daten]',1)[0];raw={}
    for line in header.splitlines():
        parts=[part.strip() for part in line.split('\t')]
        if len(parts)>1 and parts[0]:raw.setdefault(parts[0],[]).append([p for p in parts[1:] if p])
    evidence='literal named BAM LIS header; complete original header retained'
    fields=dict(sample_id=_confirmed(identity['specimen'],'Probenbezeichnung'),
        batch_id=dict(status='unconfirmed',value={'native_project':identity['batch']},
            evidence='Projekt identifies the source project; physical material batch equivalence is not established'),
        protocol_summary=_confirmed(raw.get('Versuchsbezeichnung'),evidence),
        material_identity=_confirmed(raw.get('Werkstoff'),evidence),
        geometry=_confirmed({k:raw[k] for k in ('Probenform','Probenquerschnitt','Anfangsmesslänge') if k in raw},evidence),
        loading=_confirmed({k:raw[k] for k in ('Prüfgeschwindigkeit 1','Umschaltpunkt','Prüfgeschwindigkeit 2') if k in raw},evidence),
        acquired_at=dict(status='unconfirmed',value=raw.get('Versuchs-Datum'),evidence='native date only; time and timezone not supplied'),
        instrument_settings=_confirmed({k:raw[k] for k in ('Prüfmaschine','Prüftemperatur') if k in raw},evidence),
        preload=dict(status='unconfirmed',value={'first_observed_stress_MPa':sample.solver_inputs['processing']['stress_origin_MPa']},
            evidence='first measurement retained; instrument preload procedure is not inferred from this value'),
        zeroing=_confirmed({'downstream_origin_convention':sample.solver_inputs['processing']},
            'existing BAM selectors subtract first observation; stored raw normalized rows stay intact'),
        trimming=_confirmed({'max_strain':task.max_strain,'selected_source_rows':sample.solver_inputs['processing']['selected_source_rows']},
            'existing increasing initial-loading selector; raw data retained, no new trimming or interpolation'))
    fields={k:v for k,v in fields.items() if v.get('value') not in (None,{})}
    context=parse_experiment_context(fields,sample_id=identity['specimen'],raw_metadata={'bam_header':header,'header_fields':raw})
    return sample,context


def _run(config,base,output,report):
    source=(base/config.source.path).resolve()
    if sha256_file(source)!=config.source.sha256:raise ValueError('experiment source hash mismatch')
    scripts=[]
    for script in config.scripts:
        path=(base/script.path).resolve()
        if path.stat().st_size>32*1024*1024:raise ValueError('explicit acquisition script exceeds 32 MiB')
        actual=artifact(path)
        if actual['sha256']!=script.sha256:raise ValueError('acquisition script hash mismatch')
        scripts.append(dict(actual,version=script.version,purpose=script.purpose,content_hash_verified=True,
            version_status='declared_not_independently_verified',executed=False))
    sample,context=(_json_sample(config,base,output) if config.profile=='self_describing_json_v1' else _bam_sample(config,base))
    context['scripts']=scripts
    sample.solver_inputs['experiment_context']=context
    validation=validate_sample(sample,load_validation_policy(_default_policy_path()))
    if not validation.passed:raise ValueError('experimental file SamplePackage validation failed: '+str(validation.to_dict()))
    destination=output/'sample.h5';write_hdf5(sample,destination,{'adapter':config.profile,'context':context})
    readback=read_hdf5(destination)
    if readback.solver_inputs['experiment_context']!=context:raise ValueError('experimental context changed during HDF5 roundtrip')
    if sha256_file(source)!=config.source.sha256 or any(sha256_file(s['path'])!=s['sha256'] for s in scripts):
        raise ValueError('experiment source or acquisition script changed during import')
    unavailable=[k for k,v in context['fields'].items() if v['status']=='unavailable']
    unconfirmed=[k for k,v in context['fields'].items() if v['status']=='unconfirmed']
    write_record(output/'experiment-context.json',context)
    return dict(profile=config.profile,sources=[artifact(source)],scripts=scripts,
        sample_id=sample.metadata.sample_id,context_status='partial' if unavailable or unconfirmed or context['unmapped_fields'] else 'complete_declaration',
        unavailable_fields=unavailable,unconfirmed_fields=unconfirmed,unknown_fields=list(context['unmapped_fields']),
        artifacts={'sample.h5':artifact(destination),'experiment-context.json':artifact(output/'experiment-context.json')},
        evidence_scope=config.evidence_scope,scientific_readiness='not_established_by_file_import',
        validation=validation.to_dict(),instrument_control_performed=False)


def run_experiment_file(config_path,output_dir):
    return recorded_operation(config_path,output_dir,'experiment-file',ExperimentFileConfig,_run)
