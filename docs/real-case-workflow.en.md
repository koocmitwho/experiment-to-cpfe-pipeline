# Run a real intake, training, prediction and evaluation case

[中文](real-case-workflow.md)

This guide describes version 0.3.0. Version 0.2.2 does not contain these inference/evaluation commands.

Use the tagged source (`git clone --branch v0.3.0 https://github.com/koocmitwho/experiment-to-cpfe-pipeline.git`) or the source archive from the [v0.3.0 release](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/tag/v0.3.0). The wheel supplies the library and CLI; example scripts and fixed manifests are in the source archive. Publication status is in the [verification record](verification/2026-09-30-public-usability.md).

Use Python 3.12+, create a virtual environment, install CPU PyTorch from the [official selector](https://pytorch.org/get-started/locally/), then install the checked-out v0.3.0 source with `python -m pip install -e ".[training,native]"`. No GPU, PyG or Abaqus is needed. The original case record used Python 3.12.10 and an existing CPU environment without upgrading it. The release audit additionally verifies a fresh network-installed CPU environment.

Download only `2025-04-08_Mechanical_data_tensile_test_laser_ALES.zip` (621,757 bytes) from [Zenodo 15343816](https://zenodo.org/records/15343816). Keep it outside the repository, for example `../cpfe-data/dopamics`. Source SHA256: `210c2474278ad4c05aae85958e3e1eb4ef339b02ebed91d1b72a3b292042ad61`. Attribution and CC BY 4.0 terms are in [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md). No upstream scripts are executed.

```text
python -B examples/external_cases/workflow.py --case dopamics --source-root ../cpfe-data/dopamics --run-dir ../cpfe-results/dopamics-001
```

Always use a new output directory. The runner verifies ZIP/member hashes, native headers/units and specimen metadata before execution. Original specimen identities are matched to the original trial filename and metadata row, not inferred from renamed local files.

|Role|Specimens|Native trials|Rows|
|---|---|---|---:|
|Train|MC87_0370, MC87_1016, MC87_1044|1, 3, 4|424|
|Validation|MC87_1013|10|181|
|External test|MC87_1081|11|182|

Inputs are measured laser strain (percent × 0.01); targets are instrument-reported stress in MPa. No response-based filtering, zero correction or peak selection is applied. The 256-row per-specimen training/validation budget does not remove rows in this version. Normalization and OLS coefficients fit training rows only. A 16×16 tanh MLP (321 parameters), seed 17, learning rate 0.003, at most 300 epochs and patience 60 uses one CPU thread. Validation RMSE selects the model; OLS wins an exact tie. Runtime is seconds to minutes with roughly less than 1 GB of memory depending on startup and disk performance.

Start with `REPORT.md`. `inference/predictions.csv` contains sample/row/group identity, quantity/unit, original file/member/hash, source sheet/row and model/config hashes without truth. `evaluation/evaluation.csv` adds aligned truth, residual (prediction minus truth) and frozen training mean. Chinese `SUMMARY.md`, `baseline-comparison.csv`, `model-selection.json`, `configs/`, `commands/`, and before/after source hashes provide readable results and receipts. Text cells use reversible backslash escaping; numeric columns remain numeric.

For separate prediction, pass the saved checkpoint, input-only HDF5 and explicit configuration to `python -m experiment_to_cpfe.cli infer-surrogate --config infer.json --run-dir new-predictions`. Then pass the prediction NPZ and truth-only HDF5 to `evaluate-surrogate`. Evaluation does not reopen the model or training files. HDF5 integrity checking reads the complete listed package: keep sealed truth in a separate file.

`template-config --kind infer-surrogate --from-config build.json --output infer-draft.json` generates a draft. Fill paths and original identities explicitly. Consistent task/specimen declarations are preserved; partial or conflicting declarations are rejected. Strict checkpoint contracts must propagate unchanged.

This run selected MLP, best epoch 13, stopping after 73 epochs:

|Method|Test RMSE (MPa)|Test MAE (MPa)|R²|Bias (MPa)|
|---|---:|---:|---:|---:|
|Training mean 7.11323 MPa|2.245313|1.810683|-1.090530|1.621689|
|OLS|3.140684|2.839127|-3.090262|2.839127|
|Selected MLP|2.071353|1.923316|-0.779143|1.923316|

RMSE and MAE answer different error questions. Lower RMSE but higher MAE does not establish overall superiority. Negative R² means squared error exceeds the test-truth-mean variance reference, which is a statistic rather than a deployable training baseline. NRMSE divides RMSE by `max(abs(reference))` over the evaluated truth values. All-zero truth makes NRMSE undefined (JSON null); nonzero constant truth still has a defined NRMSE. Any constant truth makes R² undefined (JSON null). Different truth scales cannot be compared directly through NRMSE.

The test contains one specimen, not 182 independent specimens. Source grouping establishes declared identity/role consistency, not biological or batch independence. No scientific accuracy threshold was prespecified, so model status is `not_assessed`; task status remains `legacy_unassessed`. This is retrospective measured-strain-to-reported-stress regression on palm leaflets. Source audits read public test responses; it is not a new blind test or a crystal-plasticity/material validation.

FAIR Train remains workbook intake only because grade/batch/heat treatment/temperature/rate evidence is incomplete. PCL preserves all channels and preheating/equilibration/loading records for numerical packaging, without training. See the [external-case README](../examples/external_cases/README.md).

Bad hashes, headers, units, source overlap, identities or nonfinite data are rejected. Existing outputs are never overwritten; execution failures retain failed receipts. Use a new directory after correcting configuration. Default scalar training still requires train/validation/test. Explicit `evaluation_mode: external_test` requires exactly train/validation; v2 target-list bundles are rejected and must be rebuilt with a v1 scalar `target`.
