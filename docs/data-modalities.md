# Data modalities and conversion rules

## Implementation scope

Asset registration records format, hash, evidence class and declared metadata.
The v0.2.1 interfaces below specify the parsing and conversion operations.

| Data or format | Available in version 0.2.1 | Input declarations and preparation |
|---|---|---|
| CSV, delimited TXT, JSON record arrays | Configured table ingestion | Explicit column map, delimiter where applicable, units and evidence class |
| Headered EBSD text | Generic text profile | Explicit column names, units and orientation convention |
| Native ANG/CTF text | Configured text profiles | ANG uses explicit zero-based column indices; CTF uses exact source headers; declare orientation and units |
| Vendor HDF5, h5ebsd, DREAM.3D | Layout inventory and explicit dataset-to-column mapping | Select aligned 1D components and declare physical meanings, units and coordinate conventions |
| OSC, CRC/CPR and other vendor binaries | Native asset references | Record the native file and use an instrument-specific numerical export for parsing |
| DIC/DVC point fields | CSV/TXT coordinate and component arrays | Explicit columns, units, frame and axes from the prepared field |
| Regular DIC/DVC grids and CT voxels | NPY, selected HDF5 dataset, nested JSON arrays, scalar ASCII VTI | Explicit spatial metadata, units and frame; VTI reads its own origin/spacing/extent |
| SEM, DIC and other images | Native image asset references | Record source images and connect prepared numerical fields with their processing records |
| Nodes, elements and grain assignments | Configured normalized tables and Abaqus input bundles | Supply prepared mesh connectivity, IDs and grain assignments |
| Grain graphs | Configured adjacency/feature/target TXT ingestion; `SamplePackage` arrays and NPZ/PyG export | Explicit row/ID mapping, directedness, self-loop/padding policy, units and target origins |
| Abaqus ODB field sequences | Abaqus-Python extraction followed by host loading | Completed recorded analysis, explicit requested fields/units/location and unchanged artifacts |
| DAMASK VTI/VTK/HDF5 and YAML, Neper/FEPX formats | Native asset references; generic scalar ASCII VTI and explicit HDF5 column mapping | Supply the source format, selected arrays and backend-specific meanings |
| XLSX, instrument blocks and multirow CSV | Explicit sheet/row/column blocks and affine unit conversion | Per-block evidence, header checks, evaluated values and original row locations |
| MAT5 numeric/struct/cell, HDF5 slices, multichannel NPY | Configured native numerical import | Explicit selectors and output meanings; MATLAB classes remain native references |
| Gmsh 2.2 ASCII with Neper orientations | Selected element type/dimension, IDs, CFG reference and explicit Rodrigues conversion | Supply the mesh, companion CFG and orientation convention |
| Self-describing JSON and configured BAM LIS | Experimental-file import and context records | Declare the profile, file hash, evidence scope, units and context basis |

## Tables and time series

The [native adapter guide](native-adapters.md) describes `pipeline adapt`, the
optional `imports` list and `sources[].block`. Partially understood files can be
decoded into drafts with explicit promotion requirements. XLSX blocks and MAT5
require the `native` extra.

CSV, delimited TXT, and JSON record arrays require an explicit target-to-source column map and units. Typical records include force, displacement, stress, strain, temperature, time, cycle, and control mode. Mechanical curves are calibration or validation evidence unless a user separately supplies a complete material model and parameters.

## EBSD and orientation maps

Text profiles map coordinate, phase, orientation and quality columns explicitly.
Set `modality: orientation_map`, `format: ang` or `ctf`, and provide an
`adapter_config` with `profile`, `column_map` and `orientation`. ANG maps string
representations of zero-based column indices to normalized target names. CTF
uses exact column names from its header. Generic CSV/TXT uses named columns.
Unrecognized layouts fail rather than trying another vendor convention.

```yaml
adapter_config:
  profile: ang
  column_map:
    euler_1: '0'
    euler_2: '1'
    euler_3: '2'
    x: '3'
    y: '4'
    quality: '5'
    phase_id: '7'
  orientation:
    representation: euler
    convention: explicit-source-convention
    angle_units: radian
    crystal_symmetry: explicit-source-symmetry
```

Configure this fragment using the actual file's columns, angle units and conventions. Asset
units must cover mapped target columns, and frame/axis metadata must be declared.
Native files remain unchanged; conversion provenance retains the original hash.

`inspect_hdf5_layout` inventories dataset paths, shapes and dtypes under an
explicit layout name. Semantic parsing additionally requires `dataset_map`,
such as `{x: 'Group/X', u: {path: 'Group/U', component: 0}}`. Each selection must
produce a one-dimensional column with the same row count. Orientation maps
declare orientation conventions, units, phase definitions and crystal symmetry;
point fields also name coordinate and field columns. Vendor HDF5 selections are
converted into the project HDF5 contract.

## Images and DIC/DVC fields

Reference/deformed images remain image assets. Point-field ingestion loads
coordinate and displacement/strain components in configured order. Regular
arrays use the voxel adapter and require origin, spacing, axis order, units and
coordinate frame. Upstream interpolation, registration, smoothing and resampling
enter through their processed arrays and child-asset records.

## CT and voxel grids

NumPy, explicitly addressed HDF5 datasets, and tiny JSON synthetic fixtures preserve origin, spacing, axis order, dtype, shape, units, and frame. Future segmentation and voxel-to-mesh adapters must create new child assets and preserve raw scans.

The VTI adapter supports one full-extent ImageData Piece and a selected scalar
ASCII DataArray. Declare `array_name`, `association: PointData` or `CellData`,
spatial `units`, `value_units`, `coordinate_frame` and `axis_order: [z, y, x]`
under `adapter_config`. Asset units must separately describe spacing and the
selected value, for example `{spacing: mm, phase: '1'}`.

VTI origin, spacing and extent come from the file; conflicting configured values
are rejected. The adapter preserves native XYZ descriptors and records the
normalized ZYX sampling origin/spacing, using cell centers for CellData. PointData
allows singleton dimensions; CellData uses a full 3D grid. The explicit array selection follows the
[VTK XML format](https://docs.vtk.org/en/latest/vtk_file_formats/vtkxml_file_format.html)
and its structured-grid ordering, with physical meanings supplied by configuration.

## Meshes and microstructure mappings

Normalized mesh tables declare node and element IDs, connectivity, element type
and grain assignments. Native mesh files retain their original content and
hashes. Grain-to-element mappings reference existing grain IDs. Readiness checks
the declared material, mesh, loading and output contract against the input deck.

## Grain graphs and field sequences

Grain graphs use `graph_node_ids`, `graph_node_features`, `graph_edge_index` and
optional `graph_edge_features`. `solver_inputs.graph_contract` supplies
directedness and feature names/units. Undirected graphs must contain explicit
reverse edges. PyG exports contain a real `torch_geometric.data.Data` object and
an embedded portable NPZ payload for accompanying records and metadata. Explicit
graph arrays specify feature-to-node correspondence and target declarations.

ODB field sequences preserve step, frame, increment, time, instance, available
node/element/integration-point/section-point location labels, component, original
field name and field unit. NPZ and PyG exports retain the canonical HDF5 hash and
record the loss of HDF5 storage layout and unmodeled HDF5 attributes.

## Solver formats

Abaqus `.inp`, `.odb`, `.sta`, `.dat`, and `.msg` are distinct evidence artifacts.
Only the Abaqus backend currently executes and extracts solver results. DAMASK
`material.yaml`, `numerics.yaml`, VTI/VTK and HDF5 remain backend-specific assets.
Neper/FEPX `.tess`, `.tesr`, `.msh`, `.ori` and `.sim` may be referenced explicitly
without imposing Abaqus semantics.

The `gmsh22` native import additionally parses the documented Gmsh 2.2 ASCII
subset and Neper Rodrigues section. The CFG remains a companion native reference.
The ordinary scalar voxel adapter still requires one spatial descriptor per
axis; use a native numerical import for separate spatial/component axes.
