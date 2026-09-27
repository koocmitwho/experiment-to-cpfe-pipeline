# Experiment-to-CPFE pipeline: original design

> Historical design dated 2026-09-02. Editorial update: 2026-09-27. This document records the original architecture and proposed milestones. Current commands and implemented profiles are in the [runbook](../../runbook.md) and [capability guide](../../limitations.md).

## Goal and architecture

Build a configurable experiment/simulation interchange pipeline. Structured
experimental, microstructure and loading records enter a versioned sample
contract; solver adapters prepare input, execute jobs and extract results;
exporters create portable datasets with provenance and quality reports.

```text
Experimental and microstructure data
  -> declared sample metadata and assets
  -> validation and solver input
  -> Abaqus execution and ODB extraction
  -> canonical HDF5 and derived NPZ/PyG
  -> provenance and quality reports
```

Formats, materials, solver commands and paths come from configuration.
Experimental observations supply model inputs, calibration evidence or
validation targets. Solved ODBs retain their execution records. Upstream image
processing and mesh generation connect through explicit assets and adapters.
Public examples use synthetic or redistributable inputs; research runs retain
their data, model inputs, outputs and authorization records locally.

## Sample contract

Stable identities are `sample_id`, `experiment_id`, `microstructure_id`,
`load_path_id` and `increment_id`. Metadata declares coordinates, units, tensor
order, orientation conventions, crystal symmetry, evidence kind, source URI,
source hash and schema version. Evidence kinds are `measured`, `inferred`,
`input` and `simulated`.

| Data family | Declarations envisaged in the original design |
|---|---|
| Geometry and mesh | Node IDs/coordinates, element connectivity/type, dimension, boundary markers and geometry origin |
| Microstructure | Grain/phase IDs, size and centroid measures, Euler/quaternion/matrix orientations, conventions and mesh correspondence |
| Grain boundaries | Adjacent grain IDs, length/area, normals, centroids, misorientation convention and boundary classes |
| Material and loading | Model/version, parameters and units, constitutive source, displacement/force/rate/temperature/time, boundaries and steps |
| Observations | Mechanical curves, DIC fields, EBSD measurements, instrument metadata, uncertainty and calibration/evaluation roles |
| Simulation | Frames/increments, field components, locations, derived responses, ODB and extractor provenance |

## Component responsibilities

Experiment adapters read a declared format and preserve physical meanings,
source data and conversion records. The initial table interface maps CSV/TXT/JSON
columns explicitly. Additional numerical, orientation and field adapters use
the same asset and sample contracts.

Validation checks required fields/types, unique identities, references, units,
coordinates, tensor order, orientation normalization, grain/mesh mapping,
increment order, finite values and group declarations. It emits JSON and human
reports with error, warning and information severities.

Solver input adapters consume validated declarations and an explicit template
or native deck. They record generated files and run static checks before solver
execution. The initial design envisaged mesh/material/orientation assignments,
boundaries, loading and output definitions, with a supplied constitutive source.

The runner uses an explicit ASCII execution directory and separate datacheck,
compile/link and analysis evidence. Records include command tokens, working
directory, input receipts, diagnostic files and completion/failure states.
Run size, CPU count, timeout and destination are configuration choices.

The Abaqus-side extractor opens ODBs through `odbAccess`, preserving requested
field names, frame/location labels and source records. Missing fields receive
explicit diagnostics. Host Python reads intermediate JSON/CSV and writes HDF5.

The HDF5 contract organizes metadata, assets, geometry, mesh, grains, boundaries,
loading, measured/simulated data, derived arrays, provenance and quality.
NPZ/PyG exports retain the canonical source hash and their conversion records.

## Runs and milestones

Each run has `input/`, `solver/`, `dataset/` and `reports/`. Its manifest records
configuration and input receipts, stage commands, artifacts, timestamps and
diagnostics. Each operation uses an explicit destination and preserves earlier
completed receipts.

The original milestones were package/CLI scaffolding; table and sample
contracts; Abaqus input preparation; one-sample solver execution; ODB-to-HDF5;
additional adapters and public examples; and controlled downstream collections.
These are the original planning categories. Dated verification records document
the resulting implementations.

## Validation strategy

Offline tests use synthetic fixtures for schema types, units, coordinate and
orientation declarations, ID mapping, template rendering, HDF5 readback,
provenance receipts and invalid-input diagnostics. Solver integration exercises
configured small inputs, datacheck, analysis, field extraction and response
readback. Evidence checks retain the origin of observations and simulated fields,
requested field availability, source grouping and scientific conventions.

Public source review covers reusable code, schema, templates, synthetic fixtures,
tests and documentation. Run records connect each stage to its declared inputs,
outputs and executable verification path.
