# First native adapter regression design

> Historical design/plan. Retained as a development archive; current operation is described in the v0.2.0 guides. Editorial update: 2026-09-27.

This design covers local ingestion of representative public tables, numerical
containers, voxel labels, meshes and grain graphs, followed by offline regression.

## Interfaces

1. Extend `TabularSourceConfig` with an optional block selector. CSV/TXT blocks
   use physical, one-based rows and zero-based column indices, explicit encoding,
   decimal mark and optional section marker. XLSX requires a named sheet and
   explicit rows/columns. Header assertions catch shifted blocks. Separate source
   configurations preserve evidence classes for mixed workbooks. Affine numeric
   conversions require both source/target units and a stated rationale. Original
   row, sheet and specimen metadata remain in conversion records.
2. Add a `NativeImportConfig` and `NativeDraft` outside the complete sample
   contract. Numerical selectors address MAT5 variables/struct fields/cells,
   HDF5 dataset slices, NPY arrays and delimited arrays. Selection and optional
   transpose/reshape are explicit. Class objects use upstream property exports,
   while state identity and quality values remain part of the source description.
3. Native readers also support a Gmsh 2.2 ASCII subset with explicit element
   type/tag filtering, and adjacency/feature/target text bundles. Raw IDs remain
   arrays; graph indices are separately mapped. Rodrigues conversion needs an
   explicit source convention and target direction. Companion CFG and loader
   evidence files remain recorded native dependencies.
4. Every output has a semantic declaration with axes, units, quantity and
   evidence class. Spatial, tensor, orientation, quality, entity, target and
   grouping declarations remain explicit. Missing declarations produce draft
   blockers. Drafts support inspection during metadata preparation.
   Promotion joins semantically complete arrays to the existing `SamplePackage`
   and its HDF5/NPZ conversion records.

## Alternatives considered

Dataset-specific scripts would duplicate conversions and hide reusable contracts.
Weakening SampleMetadata would change solver-facing compatibility. The selected
approach keeps partial ingestion separate and attaches checked arrays to the
existing contract using an optional `imports` list.

## Validation

Synthetic tests recreate layout problems: shifted
headers, decimal commas, mixed evidence, ragged cells, MATLAB objects, masked
nonfinite fields, component axes, Fortran ordering, missing units, label identity,
sparse IDs, mixed element dimensions, graph padding and self loops. New behavior
is implemented after a failing test. Real-file regression uses only existing
ignored evidence, preserves its receipts, and distinguishes structural decoding,
semantic conversion, complete sample conditions, readiness and physical checks.

Solver readiness uses the complete-sample contract. Physical validation requires
model/experiment comparisons with defined acceptance criteria. Public candidates
contain generic implementation and synthetic fixtures. Research data and machine
run records stay in local directories. This delivery consists of local edits.
