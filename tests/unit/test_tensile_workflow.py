"""Synthetic mechanics checks for a public-data-compatible tensile workflow."""

from pathlib import Path
import numpy as np
import pytest


def test_bilinear_calibration_recovers_known_plastic_parameters():
    from experiment_to_cpfe.mechanics.tensile import fit_bilinear, bilinear_stress
    strain = np.array([0., .005, .01, .02, .03, .04])
    stress = np.array([0., 5., 10., 15., 20., 25.])
    result = fit_bilinear(strain, stress, modulus=1000., yield_bounds=(5., 15.), hardening_bounds=(100., 3000.))
    assert result['yield_stress'] == pytest.approx(10, rel=1e-5)
    assert result['hardening_modulus'] == pytest.approx(1000, rel=1e-5)
    assert bilinear_stress(np.array([.005,.03]),1000,10,1000).tolist() == pytest.approx([5,20])


@pytest.mark.parametrize('strain,stress', [([0,.02,.01],[0,20,10]),([0,.01],[0,float('nan')])])
def test_calibration_reports_invalid_curve_order_and_values(strain,stress):
    from experiment_to_cpfe.mechanics.tensile import fit_bilinear
    with pytest.raises(ValueError):
        fit_bilinear(np.array(strain),np.array(stress),modulus=1000,yield_bounds=(1,20),hardening_bounds=(1,2000))


def test_generated_gauge_has_prescribed_area_length_and_valid_contract(tmp_path):
    from experiment_to_cpfe.mechanics.gauge import build_gauge_config
    from experiment_to_cpfe.adapters.tabular import assemble_sample
    from experiment_to_cpfe.config import PipelineConfig
    from experiment_to_cpfe.schema.validation import check_solver_readiness
    config = build_gauge_config(case_id='synthetic-gauge', area=4., length=10., modulus=1000.,
        poisson=.3,yield_stress=10.,hardening_modulus=1000.,max_strain=.04,strain_rate=.01,
        divisions=(2,2,2),units={'length':'mm','stress':'MPa','time':'s','force':'N'},
        abaqus_command=('abaqus',),template_path=Path('configs/templates/cpfe_template.inp').resolve(),
        work_dir=tmp_path,source_description='synthetic continuum definition')
    sample = assemble_sample(PipelineConfig.model_validate(config))
    assert sample.metadata.orientation.representation == 'not_applicable'
    assert check_solver_readiness(sample,'abaqus_cpfe').ready
    mesh=sample.solver_inputs['inp_replacements']['NODES']
    assert len(mesh.splitlines())==28  # 27 actual nodes + keyword
    assert len(sample.solver_inputs['material_region_mapping']['ALL'])==8
    assert config['solver_inputs']['gauge']['area']==4
    assert config['solver_inputs']['gauge']['top_nodes']==list(range(19,28))


def records():
    rows=[]
    for frame,displacement,force in [(0,0.,0.),(1,.2,20.)]:
        for node in [3,4]:
            for field,component,value,unit in [('U','U3',displacement,'mm'),('RF','RF3',force,'N')]:
                rows.append(dict(step='TENSION',frame=frame,frame_time=float(frame),instance='PART-1',position='nodal',
                                 node_label=node,field=field,component=component,value=value,unit=unit))
    return rows


def test_axial_reduction_sums_reactions_once_and_uses_original_geometry():
    from experiment_to_cpfe.mechanics.tensile import reduce_axial_records
    curve=reduce_axial_records(records(),step='TENSION',instance='PART-1',top_nodes=[3,4],axis=3,
                               area=4.,length=10.,force_unit='N',length_unit='mm')
    assert curve['force'].tolist()==[0,40]
    assert curve['strain'].tolist()==[0,.02]
    assert curve['stress'].tolist()==[0,10]


def test_axial_reduction_accepts_native_abaqus_nodal_enum():
    from experiment_to_cpfe.mechanics.tensile import reduce_axial_records
    rows=records()
    for row in rows: row['position']='NODAL'
    curve=reduce_axial_records(rows,step='TENSION',instance='PART-1',top_nodes=[3,4],axis=3,
                               area=4.,length=10.,force_unit='N',length_unit='mm')
    assert curve['stress'].tolist()==[0,10]


@pytest.mark.parametrize('change',['missing_node','duplicate','wrong_unit'])
def test_axial_reduction_requires_complete_unique_nodal_records(change):
    from experiment_to_cpfe.mechanics.tensile import reduce_axial_records
    rows=records()
    if change=='missing_node': rows.pop()
    if change=='duplicate': rows.append(rows[-1].copy())
    if change=='wrong_unit': rows[-1]['unit']='kN'
    with pytest.raises(ValueError):
        reduce_axial_records(rows,step='TENSION',instance='PART-1',top_nodes=[3,4],axis=3,
                             area=4.,length=10.,force_unit='N',length_unit='mm')


def test_error_metrics_keep_physical_units_and_zero_reference_scale():
    from experiment_to_cpfe.mechanics.tensile import regression_metrics
    result=regression_metrics(np.array([0.,2.]),np.array([0.,1.]))
    assert result['rmse']==pytest.approx(2**-.5)
    assert result['bias']==-.5
    assert result['nrmse']==pytest.approx(2**-.5/2)
    assert regression_metrics(np.zeros(2),np.ones(2))['nrmse'] is None


@pytest.mark.parametrize('reference,prediction,nrmse,r2', [
    ([2., 4.], [1., 3.], .25, 0.),
    ([0., 0.], [1., 1.], None, None),
    ([2., 2.], [1., 3.], .5, None),
    ([-2., -2.], [-1., -3.], .5, None),
])
def test_metric_normalization_and_constant_reference_contract(reference, prediction, nrmse, r2):
    from experiment_to_cpfe.mechanics.tensile import regression_metrics
    result = regression_metrics(reference, prediction)
    for key, expected in [('nrmse', nrmse), ('r2', r2)]:
        if expected is None:
            assert result[key] is None
        else:
            assert result[key] == pytest.approx(expected)
