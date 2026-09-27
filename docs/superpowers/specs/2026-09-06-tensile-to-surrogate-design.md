# Public tensile experiment to FE and neural surrogate

> Historical design/plan. Retained as a development archive; current operation is described in the v0.2.0 guides. Editorial update: 2026-09-27.

The complete case uses the KupferDigital CuSn8Ni2 tensile series. H_08 supplies
calibration data, H_16 supplies an experimental model check, and H_18 is the final
experimental holdout. The fixed public dataset is DOI 10.5281/zenodo.10820299.

## Physical model

The first case represents the uniform gauge response with a small-strain,
isotropic bilinear elastoplastic solid. Its equivalent square gauge has the
source initial area and 25 mm gauge length. The source describes cylindrical
specimens, so square-section geometry is an explicit gauge-response reduction.
Axial displacement follows the measured strain definition. The source's machine
travel remains an independent recorded quantity.

Use the initial loading interval up to 0.8% engineering strain, within the
documented 0.025%/s regime. Subtract each curve's first strain/stress pair as its
recorded preload origin. Freeze that rule before comparisons. The source H_08
elastic slope supplies E. Fit yield stress and positive linear plastic modulus
to H_08 by least squares on a fixed strain grid. Labels remain nominal axial
stress and engineering strain under the stated small-strain approximation.

Poisson ratio 0.30 is a numerical modeling assumption for lateral deformation.
Two sensitivity runs at 0.25/0.35 check its influence on the axial target. Compare
one-element and eight-element uniform gauges. Material domains are represented
as material regions. Orientation is explicitly inapplicable to this homogenized
isotropic model, distinct from an unresolved crystallographic declaration.

## Execution and learning

One CPU runs a fixed small collection of real Abaqus jobs, each with explicit
stage timeouts. Nine parameter cases vary E, yield stress and plastic modulus
within 10% of the calibration. Five cases train a two-hidden-layer MLP, two
select its checkpoint, and two form the simulation holdout. All frames from one
case retain that case's split. Input/output normalization uses training rows.

The network predicts nominal stress from axial strain and material parameters.
Its training targets come from nodal reactions in the verified canonical ODB
exports. Report FE-versus-analytical uniaxial response, neural-versus-FE error,
and calibrated FE/neural-versus-held-out experiment separately. The analytical
uniaxial relation is a numerical reference, and a train-mean predictor is a
learning baseline. Experimental errors are reported in MPa and normalized form.

## Software and artifacts

Extend the existing schema with a reasoned orientation-inapplicable declaration,
material-region mapping for isotropic solids, and a checked `isotropic_plastic`
profile using explicit *ELASTIC and *PLASTIC rows. Keep existing crystalline
contracts operational. Add generic calibration, gauge generation, axial ODB
reduction and tabular MLP training interfaces with small synthetic regression.

Public candidates contain reusable code, tests and configuration instructions.
The local case retains source files, calibrated parameters, generated INPs,
real ODBs, HDF5/NPZ packages, checkpoint, training history, evaluation tables and
figures. One case runner records the progress of every stage for continuation.
