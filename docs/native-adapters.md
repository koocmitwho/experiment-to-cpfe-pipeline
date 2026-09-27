# Native table and array adapters

The native adapters read instrument blocks, XLSX worksheets, MAT/HDF5 arrays,
multichannel NPY, Gmsh meshes and grain graphs. Each result includes selected
values, source locations and physical declarations. Drafts list information
needed for normalization. Eligible imports join an existing `SamplePackage`.

Install MAT5 and XLSX support with `python -m pip install -e ".[native]"`.
The `dev` extra includes these readers for the offline test suite.

## Run an inspection

```text
pipeline adapt --config examples/synthetic_native/imports.yaml --run-dir runs/native-example
```

This reads four synthetic points and writes `reports/native-adapters.json` and
`reports/native-adapters.md`. Each import receives a decoding result and a
semantic status. Exit 0 means every import is eligible, while exit 1 identifies
a decoding failure or an open requirement. Use a new directory for each run.

The configuration contains an `imports` list. Every entry supplies `import_id`,
`profile`, `modality`, `files` and output `meanings`. The `numeric` profile uses
`selections`. Mesh, graph and stiffness profiles use `options`. Paths resolve
from the configuration directory.

The command writes reports. Use the Python interface to work with its arrays:

```python
from experiment_to_cpfe.adapters.native import decode_native, promote_native
from experiment_to_cpfe.adapters.native_models import NativeImportConfig

config = NativeImportConfig.model_validate(import_entry)  # resolve paths first
draft = decode_native(config)
report = draft.report()
if not draft.blockers:
    arrays, assets = promote_native(draft)
```

For a complete pipeline configuration, add these entries under `imports`.
`assemble_sample()` attaches the eligible arrays and source references. Existing
`validate` and `export` stages then check the sample and write HDF5/NPZ.
Give each output a unique array name.

## Select table blocks

Every entry in `sources` has its own evidence class, column map and units.
Separate entries can select experimental and simulated blocks from one workbook,
retaining their worksheet, original row numbers and specimen details.

With `block`, column-map values are zero-based indices written as strings.
Rows are one-based, and `data_end_row` is exclusive. A text `start_marker` makes
row 1 the first physical line after the marker. Otherwise numbering starts at
the file or worksheet. Blank lines count.

```yaml
# Fields added to a normal TabularSourceConfig entry:
column_map: {time: '0', machine_travel: '1', force: '2'}
units: {time: s, machine_travel: mm, force: N}
block:
  start_marker: '[Data]'
  data_start_row: 3
  decimal: ','
  numeric_fields: [time, machine_travel, force]
  header_checks:
    - {row: 1, column: 0, value: Time}
    - {row: 2, column: 2, value: kN}
  specimen: {specimen_id: coupon-A}
conversions:
  force:
    source_unit: kN
    target_unit: N
    factor: 1000
    offset: 0
    reason: explicit SI prefix conversion
```

Supply the actual encoding and delimiter. XLSX uses `format: xlsx`,
`delimiter: null` and `block.sheet`. Supported worksheet input consists of
cell values, so formulas need an evaluated-value export with its source record.
Text blocks support one record per physical line. Selected cells must be
complete, with finite numbers in `numeric_fields`.

Other fields retain string IDs. The output adds `source_row` and, for XLSX,
`source_sheet`. An affine conversion computes `source * factor + offset`.
In this example the raw force asset records kN and the curated column records N.
The receipt keeps the selected rows, specimen metadata and conversion rationale.
Machine travel retains its source meaning. A strain calculation needs its own
geometric and measurement definition.

## Address numerical arrays

Each `files` entry declares a path, format, evidence class, license (nullable)
and native-layout description. `source_uri` can hold the public source URL.
A selection names a file key and its selector:

| Format | Selector | Result |
|---|---|---|
| `mat5` | Variable `path`, then struct/cell `steps` | Original singleton dimensions and separate state lengths |
| `h5`, `hdf5`, `mat73` | Exact dataset `path`, optional `slices` | Selected multidimensional values |
| `npy` | Optional `slices` | Header inspection and memory-mapped selection |
| `txt`, `csv` | Delimiter, optional `skiprows`, `dtype`, `encoding` | Small numerical/string table |

For example, a MAT5 struct field takes two explicit steps:

```yaml
selections:
  stress_component:
    file: mat
    selector:
      path: Stress
      steps: [{index: [0, 0]}, {field: S11}]
```

A 1-by-N MATLAB cell uses `[0, i]` for state `i`. Each state retains its actual
entity count. Cross-state correspondence needs recorded grain identities or
registration evidence.

An HDF5 image dataset can be read one sample at a time:

```yaml
selector:
  path: train_images
  slices: [[0, 1], null, null, null]
  max_bytes: 1048576
```

A slice entry is `null` for the whole axis, an integer to select and remove an
axis, or `[start, stop, step]`. Stop is exclusive and step is positive.
`[start, stop]` uses step 1. Supply valid source bounds, a complete permutation
for `transpose`, and both `reshape` and `reshape_order: C` or `F` for reshaping.
The output description retains these operations.

`max_bytes` defaults to 64 MiB of selected data. MAT5 and text also have a
128 MiB `max_source_bytes` default. Working memory includes the selected MAT5
variable or decompressed HDF5 chunk, which may exceed the final slice size.
Small source files suit the table readers.

`inspect_npy_header()` works on a header fragment and reports payload availability.
Fortran storage order and physical axis names remain separate declarations.
MATLAB classes/MCOS need an upstream numerical property export, as do HDF5
references, compound fields and external/virtual storage. An HDF5 header provides
the dataset layout. Reading a slice additionally requires its chunks.

## Describe physical meaning

Every output supplies `quantity`, `unit` or complete `component_units`, `axes`,
`source_kind` and `evidence`. Component names bind to an array axis, for example
`components: {channel: [u, v]}`. Mixed-evidence containers use separate source
views with the appropriate classifications and selections.

| Declaration | Required information |
|---|---|
| Spatial field | Real numeric values and coordinate frame |
| Voxel values | Spatial axes, origin, spacing, length unit and frame |
| Tensor or tensor target | Ordered component names, `tensor_order`, `shear_convention`, `reference_state` |
| Orientation | Representation, convention, angle unit, symmetry and `mapping_direction` |
| Entity IDs | Unique integer/string vector and `identity_scope` |
| Entity-linked array | `entity_ids`, matching `entity_axis` and identity scope |
| Quality | Quality-array name, explicit axis mapping and `valid_values` |
| Target | Physical quantity, evidence, `target_origin`, `group_id` and `split` |

Voxel spacing describes the spatial axes. Component axes carry component names.
Unstructured fields use `coordinate_frame`. Orientation checks cover Euler
component count, quaternion norms and orthonormal rotation matrices.

`checks` compares selected arrays along a declared axis, with `identity_scope`
and `evidence` identifying the within-state alignment. Quality flags and residuals
remain separate arrays. Drafts retain nonfinite values and their counts, while
canonical promotion uses an explicitly selected finite subset. Targets from one
group use one split within a canonical sample. The
[training collection builder](training-datasets.md) applies a configured split
policy across files and checks it against registered target declarations.

## Mesh, graph and stiffness profiles

`gmsh22` reads Gmsh 2.2 ASCII and its companion CFG. Options specify `mesh_file`,
`config_file`, `dimension`, one `element_type` and `grain_tag_index`, which is
zero-based among native tags. Supported type numbers are 1-15. Connectivity
preserves original node IDs. The report counts selected elements and the full
native set, with CFG lines retained as a companion configuration record.

Neper orientations support `rodrigues:active` and `rodrigues:passive`.
`orientation_conversion` supplies `source`, `target: rotation_matrix` and
`mapping_direction`, chosen as `crystal_to_sample` or `sample_to_crystal` from
the source convention. Active/passive determines matrix construction.
The original Rodrigues vectors are retained as well.

`grain_graph` options identify `adjacency_file`, `features_file`, `targets_file`,
`id_column`, `feature_columns`, `id_dtype` (`str` or `int64`), `directed` and
`node_order_evidence`. The input is a binary square adjacency matrix, symmetric
for an undirected graph. `self_loops` selects `preserve`, `reject`, `add` or
`remove`. Zero nodes stay in the graph. Removing specific isolated padding IDs
requires `padding_ids` and `padding_evidence`, and records the edge remapping.
`zero_node_policy: unresolved` keeps the open interpretation in the report.
Outputs use the existing graph-array names and `graph_targets`. PyG also consumes
an explicit `solver_inputs.graph_contract`.

`stiffness` reads a `voxel_file`, a `labels_file` and ordered CSV `columns`.
Its `pairing` declares zero-based `row_index`, `index_base`, `sample_template`
using `{index}`, `relative_path_template` using `{sample}`, `expected_rows`,
`loader_file` and `evidence`. The adapter checks the filename and row count
against that rule. A draft without pairing retains all selected label rows.
The reader preserves the specified column order and numerical scale. Normalized
targets additionally supply units, tensor order, shear convention and reference state.

## Conversion records and verification

Conversions retain source references, selection settings, parent/auxiliary
dependencies and transformation records. Detailed integrity receipts stay in
machine-readable metadata. Solver readiness uses the complete sample contract.
Physical validation adds model/experiment comparisons and acceptance criteria.

The current delivery covers native ingestion and HDF5/NPZ integration.
The [verification record](verification/2026-09-06-native-adapters.md)
lists tested capabilities and representative public-file results.
