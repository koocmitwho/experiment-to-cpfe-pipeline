# Public usability audit and v0.3.0 release record

Audit date: 2026-10-01. Authorized repository:
https://github.com/koocmitwho/experiment-to-cpfe-pipeline.
Candidate branch: `candidate/public-usability-20260930`.
Baseline: `cfdf90ea4144ca34cb0d5a4be1bb94f75e5ad5cb` (v0.2.2).

Publication is pending the checks below. No tag or release has been created by
this audit at this stage. Original uncommitted public files were preserved in a
local pre-audit snapshot. No private integration, data or weights were accessed.

## Review and necessary corrections

Independent Standards and Spec reviews found the existing P2 NRMSE documentation
error and a P3 ambiguity about packaging this report. The bilingual guide now
states `RMSE / max(abs(reference))`. All-zero references make NRMSE null; nonzero
constant references retain a defined NRMSE; constant references make R² null.
Regression cases cover positive, negative, zero and nonconstant references.
The release checklist now names the current report as the explicit packaging
exception; other dated reports and plans remain repository archives.

Train-only normalization, training mean and OLS fitting, validation-only model
selection, fixed original specimen roles, frozen inference, evaluation alignment
and source/role isolation were reviewed against the public-usability plan.
No additional substantive static-review finding was confirmed.

## Version and publication process

0.3.0 is a minor version because this change adds public inference/evaluation,
scalar templates and explicit external-test training. Default v1 scalar
three-partition behavior remains, while v2 training stays explicitly unsupported.
Remote main and existing tags were checked: main remains the baseline and the
latest release is v0.2.2. No v0.3.0 exists at audit start.
The existing channel is GitHub Release with wheel, sdist and SHA256SUMS, after
pull-request/commit CI. No PyPI publication or new credentials are introduced.

## Evidence and boundaries

Fresh test, package, independent-install and remote-CI results will be appended
as each reaches a terminal state. Official source APIs independently declare
CC BY 4.0 for the three fixed manifests. A fresh download of the DOPAMICS ZIP
matches 621,757 bytes and SHA256
`210c2474278ad4c05aae85958e3e1eb4ef339b02ebed91d1b72a3b292042ad61`.

The earlier documented case has one external-test specimen, negative R² and
MLP MAE worse than the training mean. These are retained in the guides. They do
not establish scientific accuracy, material calibration, causal independence or
CPFE validity. No new expensive/private training is authorized or performed.
Historical Windows native-crash root cause remains unknown; successful bounded
CPU runs do not establish unrestricted long-term stability. Real Abaqus, GPU,
optional plotting and all possible dependency versions are outside this audit.

## Source, license and privacy review

252 public tracked/nonignored candidate files and all 11 reachable baseline
revisions were examined for protected payload names, credential formats and
machine paths. Current tree and built archives have no confirmed matches.
Historical revisions `e04277f` and `909fa2f` contain a plan sentence explicitly
forbidding three local paths in synthetic tests. This already-public instruction
contains no data or credentials; current source and packages omit those paths.
No history rewriting is performed. Public `tests/integration/` is the synthetic
integration test directory, not private integration material.

Wheel and sdist contain 83 and 227 files. Packaged source bytes, typed marker,
default policy, extractor script, license files and Apache-2.0 metadata match
the reviewed source. The sdist includes public examples/tests and this report;
plans, research and other dated reports are excluded. Fixed CC BY 4.0 manifests
have attribution and transformation statements. Neither archive contains raw
experiments, model checkpoints, solver outputs, secrets or machine paths.

Initial test attempts used a borrowed environment whose child processes loaded
an old public 0.1.0 editable checkout; those full-suite results are invalid for
this candidate. Sandbox process cleanup and archive-access limitations were
also observed. The timeout test passed at normal host permissions; 23 new
synthetic external-workflow tests passed. Final verification uses a new isolated
environment and byte-identical artifact copies without altering permissions.

## Fresh local release gates

Windows, Python 3.12.10; a new venv with system-site-packages disabled.
CPU Torch 2.8.0+cpu was downloaded from the official CPU index; the wheel and
its declared dev/training/ml/native dependencies installed through normal pip
and PyPI. NumPy 2.5.3, h5py 3.16.0, SciPy 1.18.1, pytest 9.1.1 and
PyG 2.8.0.post1 were used. Loaded project paths were in this new site-packages.

```text
EXP2CPFE_TEST_PROFILE=ml
EXP2CPFE_WHEEL_DIR=<byte-identical reviewed artifact directory>
python -m pytest -q -rs --strict-markers -p no:cacheprovider --basetemp <fresh temp>
831 passed, 1 skipped in 99.75s; exit 0
```

The sole skip is the disabled real-Abaqus opt-in. Wheel installation outside the
checkout and real CPU PyG serialization/readback were included. Cacheprovider
was disabled only to avoid sandbox-created cache ownership; no test or skip
gate was relaxed. Thread budgets were one, with CPU-only execution.

`python -m build --no-isolation` and `python -m twine check --strict dist/*`
passed. Normal isolated builds are additionally required by remote offline CI.
The source-distribution examples were copied without src/tests to a separate
folder and run outside the checkout against the newly installed wheel.
`pipeline --version` returned 0.3.0; the synthetic data-foundation example
completed its HDF5/dataset/protocol flow and rejection checks.

The independently downloaded DOPAMICS case completed with unchanged source
hashes and exact native-row/percent-conversion checks. Its new-process model
readback used installed site-packages and had max difference 0. Train/validation
contain 3/1 specimens and no test rows. Independently recomputed normalization,
validation-only selection and final metrics agree with saved receipts:

|Method|Test RMSE (MPa)|Test MAE (MPa)|R²|
|---|---:|---:|---:|
|Training mean|2.245313|1.810683|-1.090530|
|OLS|3.140684|2.839127|-3.090262|
|Selected MLP|2.071353|1.923316|-0.779143|

MLP best epoch is 13; NRMSE is 0.2571674970 under max-absolute-reference scaling.
The negative R², worse MAE versus the mean, single-specimen test and unassessed
scientific status remain explicit. Real FAIR/PCL inputs were not downloaded or
rerun in this audit; their public synthetic workflow tests were included.

Local gates are passed. Remote PR/main/tag CI and publication/download validation
remain pending at the release-candidate snapshot.
