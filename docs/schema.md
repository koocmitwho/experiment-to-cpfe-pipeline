# Normalized schema

## Stable identifiers

Every sample declares `sample_id`, `experiment_id`, `microstructure_id`, `load_path_id`, and `schema_version`. Increment-level records carry `increment_id` when time or loading order matters.

## Evidence classes

- `measured`: directly observed experimental data.
- `inferred`: segmentation, interpolation, reconstruction, fitting, or another derived estimate.
- `input`: a deliberate solver or model input.
- `simulated`: output from a real solver or an explicitly identified synthetic generator.

Evidence class follows the source through representation changes. Converted measured EBSD remains measured, while a statistically reconstructed RVE is inferred.

## Asset contract

`AssetRef` records a stable asset ID, optional parent asset ID, modality, native
format and layout, URI, evidence class, data layer, units, coordinate frame,
axis order, dtype, shape, source hash, license and lossy transformations.
`descriptive_metadata` retains modality-specific descriptors such as voxel
origin/spacing, selected field columns and explicit orientation declarations.
`AssetManifest` rejects duplicate IDs, unresolved parents and parent cycles.

An optional `ConversionRecord` records source/target formats and integrity
receipts for files (`hash_scope: files`) or arrays (`hash_scope: logical_payload`).
`source_hash_verified=true` records local source-file agreement. ODB extraction
retains its own source asset and execution record.

Parsed external arrays retain their raw asset and add a `<raw-id>:normalized`
child in the curated layer. The child preserves evidence class, records selection
losses and points to its canonical array. Detailed array integrity metadata stays
with the conversion record.

Supported modalities are `table`, `time_series`, `orientation_map`, `image`, `voxel_grid`, `point_field`, `mesh`, `grain_graph`, and `field_sequence`. Data layers are `raw`, `curated`, `solver_input`, `solver_output`, and `derived_ml`.

## Spatial and tensor conventions

Coordinates declare a named frame, ordered axes and units. Orientations declare representation, convention, angle units where applicable and crystal symmetry. Tensor component order comes from the explicit input declaration.

A homogenized isotropic model can supply
`orientation: {representation: not_applicable, reason: ...}`. This represents
model applicability. Crystalline orientation data continue to use a resolved
Euler/quaternion/matrix convention. `material_region_mapping` assigns explicitly
named element sets for orientation-independent isotropic models, while
`microstructure_mapping` retains grain identity for crystalline models.

Field records carry units by field name. Stress, displacement and a state variable may have
different dimensions. State variables require individual declarations.
The field-location identity includes the step/frame, original field/component,
instance, position and available node/element/integration-point/section-point
labels. These fields jointly identify each record.

Each source/step/load-case/increment ID identifies one frame. Within that frame,
the complete field/location/component identity is unique. `frame_time` is
step-relative for TIME frames; `frame_value` follows the frame domain, and table
`time` uses its independently checked clock. Frame times are compared in frame
index order, and all records in a frame carry the same time.

`experiment_to_cpfe/_resources/field_contract.py` is the dependency-free shared
contract for the standalone Abaqus extractor, host numeric parsing and record
identity validation. Its version is recorded in extraction metadata. Native
string identifiers retain their spelling; missing inapplicable labels remain
empty and nonfinite numeric values are rejected.

`SamplePackage` holds metadata, reserved normalized tables, named NumPy arrays,
assets and explicit solver inputs. Reserved tables are `grains`,
`grain_boundaries`, `mesh_nodes`, `mesh_elements`, `load_history`,
`measured_observations` and `simulation_records`. Explicit selectors and row
identities define correspondence between tables.

`NativeDraft` is a separate ingestion result. It holds selected arrays and
unresolved semantic conditions without filling the complete sample's metadata.
`PipelineConfig.imports` promotes eligible drafts into ordinary arrays/assets.
Per-array meanings retain component axes, spatial descriptors, tensor/reference
conventions, quality and entity links, and target grouping. The
[native guide](native-adapters.md) describes these declarations.

## Canonical HDF5 groups

```text
/meta
/assets
/geometry
/mesh
/grains
/grain_boundaries
/load_history
/measured
/simulation
/macro_response
/derived
/provenance
/quality
```

The root attributes `container_format=experiment-to-cpfe` and
`container_version=1` identify the canonical format. The sample schema version
is a separate value under `/meta`. The reader rejects foreign or unsupported
container identifiers.

Table records are stored as JSON with numeric common columns additionally
available as datasets. Arrays live under `/derived/arrays`. Populated datasets
contain the selected payload; reserved groups provide the container structure.
Asset metadata and the source manifest retain references to original files.

Mapped table rows carry `source_asset_id` and `source_kind`. These reserved
fields bind every row to its raw source and its declared column units. Each
source also has a curated `normalized-table-json` child with a conversion
receipt, source hash and logical row-payload hash. Its source-selected row
subset is verified on HDF5 writing and reading; reordering, deleting or changing
rows requires a new conversion. The logical hash is not presented as a file
hash. Column selection and original text-format loss are recorded while the raw
file remains unchanged. Independent sources retain separate clocks and IDs.

ODB extraction rows bind to the simulated `odb-extraction-bundle` child asset,
which points to the original ODB. Its `units` map uses field names, and each
row's `unit` agrees with its field declaration. The export stage validates the
merged sample and registers its own JSON and Markdown validation reports.

Native blocks also retain physical source rows, worksheet and specimen metadata.
For explicit unit conversions, raw assets describe source units, curated assets
describe target units, and the source view records `normalized_units` for its
mapped output rows. Native mesh connectivity retains original node IDs; graph
edge indices instead address rows of `graph_node_ids`.

Numeric, Boolean, fixed-width byte and Unicode arrays, including scalars and
empty arrays, have explicit dtype/shape metadata. Unicode uses valid UTF-8 strings
and retains its original NumPy dtype descriptor on read. Normalize object,
structured and datetime arrays into these supported types before writing.

HDF5 is the normalized project container. Vendor files enter as native assets with
hashes and explicit layout descriptions. NPZ/PyG exports derive from a verified
canonical HDF5 file and record their loss of HDF5 storage layout, compression and
attributes outside the modeled sample contract.

## Training collection

`build-training-dataset` assembles selected columns from multiple canonical
packages, using v1 scalar targets or v2 ordered target lists.
The `experiment-to-cpfe-training-1` NPZ stores features, targets, groups,
splits, sample_ids and JSON-encoded row identities. Its metadata records ordered
quantity names/units, each sample's assets and sources, column selections,
conversions, source row indices and the collection configuration.

Exact row identities establish one-to-one alignment. Collection grouping uses
sample_id, experiment_id or an explicitly declared group_id. The builder and MLP
share the group/split contract. Training bundles also retain content receipts,
which the configured training entry checks before creating model outputs.
See the [training dataset guide](training-datasets.md) for the configuration.
