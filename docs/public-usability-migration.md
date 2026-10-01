# v0.3.0 public usability scope and license review

The candidate starts from public v0.2.2, commit
`cfdf90ea4144ca34cb0d5a4be1bb94f75e5ad5cb`, on
`candidate/public-usability-20260930`. Its authorized destination is
https://github.com/koocmitwho/experiment-to-cpfe-pipeline.
Publication status and fresh verification are recorded in
[the release audit](verification/2026-09-30-public-usability.md).

## Included capabilities

|Capability|v0.3.0 scope|
|---|---|
|Source partitions|Original specimen, column, sheet/row and conversion receipts; unverified roots remain whole-file|
|Strict task declarations|Preserve declared independence axes and reject conflicting or partial declarations|
|Scalar fitting|CPU OLS/MLP, train-only normalization/mean/OLS, validation-only selection|
|External testing|Explicit train/validation-only mode; default three-partition behavior retained|
|Prediction and evaluation|Frozen scalar checkpoints, separate input/truth packages, identity and overlap checks|
|Templates and reports|Two scalar config drafts, readable CSV and summaries, source/unit/model receipts|
|DOPAMICS|Fixed original 3/1/1 specimen roles, percent-strain conversion, separate test evaluation|
|FAIR Train|Original workbook channels and rows; intake only|
|PCL|All channels and preheating records; numerical packaging only|

V2 target lists remain numerical data contracts and are explicitly rejected by
the scalar trainer. No model-family expansion, recovery service or scientific
acceptance protocol is introduced. HDF5 integrity checks read the entire listed
package; sealed truth must be stored separately. Dataset identity checks do not
establish biological, batch or causal independence.

## Distribution and attribution

Project orchestration, generic modules and synthetic fixtures use Apache-2.0.
The source-derived fixed manifests retain CC BY 4.0 attribution and record hashes,
original metadata and native layouts. Official Zenodo records
[15343816](https://zenodo.org/records/15343816),
[19007867](https://zenodo.org/records/19007867) and
[10995304](https://zenodo.org/records/10995304) declare CC BY 4.0; their API license
fields were independently rechecked on 2026-10-01. See
[THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md) for creators and transformations.
No upstream scripts are executed or redistributed.

Raw measurements, trained weights, solver outputs, machine configuration and
private research material are excluded. Downloads and generated results stay in
user-selected local directories. The original local work-in-progress documents
were preserved in the pre-audit snapshot before preparing public-facing records.

## Scientific interpretation

The documented DOPAMICS test contains one specimen. Negative R² and the selected
MLP's MAE being worse than the training mean remain visible. No accuracy threshold
was prespecified; model validity is `not_assessed` and the example task remains
`legacy_unassessed`. Successful execution establishes software behavior only.
