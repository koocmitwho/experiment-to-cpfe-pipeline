# Validation, CI and documentation repair evidence — 2026-09-27

The local checkout started at `1dc679abe6a8c4d8857c88dba1e9badc476f73a2`
(`v0.2.0`) on Windows with Python 3.12.10. Changes remain in the worktree.
The existing untracked publication plan was retained. Version remains 0.2.0.

## Baseline reproduction

Commands used the repository's `.venv/Scripts/python.exe`:

```text
python -m pip install -e ".[dev]"
python -m pytest -q -rs
686 passed, 8 skipped in 55.83s

python -m pip install "torch==2.14.0+cpu" --index-url https://download.pytorch.org/whl/cpu
python -m pytest -q -rs
695 passed, 3 skipped in 45.71s

python -m pip install -e ".[ml]"
python -m pytest -q -rs
696 passed, 2 skipped in 39.89s
```

The supplied CPU baseline requires PyG as well as Torch. With Torch alone,
`test_pyg_is_real_data_with_portable_full_payload` skipped because
`torch_geometric.data` was absent. Installing torch-geometric 2.8.0.post1
reproduced the requested 696/2 count. Torch reports version 2.14.0+cpu and
`torch.version.cuda is None`.

## Red-to-green evidence

The initial extraction regressions ran against the unchanged implementation:

```text
python -m pytest -q --tb=short tests/unit/test_extraction_validation.py
23 failed, 7 passed in 2.19s
```

The decreasing-frame-time, NaN, reused-increment and invalid-source export
tests all observed the same incorrect result:

```text
assert result["status"] == "blocked"
E   AssertionError: assert 'completed' == 'blocked'
```

Missing required metadata reproduced raw `KeyError` for `odb_sha256`,
`odb_path` and `sample_metadata`. The implementation now produces named
`ValueError` diagnostics. This addresses malformed externally constructed
bundles; normal pipeline extraction already injects sample metadata.

The first focused extraction/export/validation regression command included:
`test_extraction_validation.py`, `test_extraction_provenance.py`,
`test_field_contract.py`, `test_export_gates.py`, `test_stage_integrity.py`,
`test_validation.py` and `test_training_dataset.py` under `tests/unit/`.

```text
167 passed in 9.89s
```

Review added three further cases for inconsistent increment IDs within one
frame and post-load string/Boolean field values:

```text
python -m pytest -q --tb=short tests/unit/test_extraction_validation.py -k "one_frame_retains or loaded_field_values"
3 failed, 30 deselected in 0.49s

python -m pytest -q tests/unit/test_extraction_validation.py
33 passed in 3.67s
```

Other red tests and subsequent focused checks:

| Check | Initial result | Subsequent evidence |
|---|---|---|
| CLI, export configuration, policy and fingerprints | 17 failed | Included in the 59-pass focused run and final full suites |
| Skip-gate child sessions | 8 failed, 3 passed | Included in the 59-pass focused run and final full suites |
| Standalone checksum script | 4 failed | Included in the 94-pass report/checksum run and final full suites |

One intermediate full run found a CLI capture assumption: the existing inspect
test accumulated the newly added validate summary. It now checks that summary
before preserving its original JSON assertions. A new fingerprint fixture was
also made byte-explicit for Windows line endings. Logs retain those intermediate
failures and the subsequent results.

## Contract decisions

- HDF5 export revalidates the merged SamplePackage and records JSON/Markdown
  validation artifacts plus the report in its stage. The original input
  validation receipt remains unchanged. NPZ/PyG consume verified canonical HDF5.
- `frame_time` is step-relative TIME-domain data. `frame_value` keeps its frame
  domain, and ordinary `time` is checked separately. Frame clocks are grouped by
  source/step/load path and ordered by frame index. A frame has one time and one
  increment ID; an increment ID maps to one frame within that group.
- Multiple fields/components/locations may share a frame. The existing full
  field-record identity remains the row uniqueness key.
- Extracted rows bind to a simulated extraction asset, including field-specific
  units. Clearing or contradicting that binding produces validation issues.
- Missing field-contract versions are accepted for extraction version 0.1.
  Current bundles require the explicit version. The existing fixture is unchanged.
- The loaded validation policy is shared by readiness, INP generation and
  solver preflight. Export enforces `export.formats`.
- Run manifests add tool, Python and core dependency versions and a package
  source/resource fingerprint while retaining schema version 0.1. Existing
  solver command receipts remain. This task did not invoke Abaqus for optional
  solver-version or binary-hash collection.

## Skip-gate demonstration and CI

An intentionally temporary test called `pytest.skip` with an unexpected reason:

```text
python -m pytest -q -rs --strict-markers tests/test_ci_skip_probe_temporary.py
==================== Unexpected skips: test session failed ====================
tests/test_ci_skip_probe_temporary.py::test_intentional_ci_skip_probe: intentional unexpected skip to verify the CI gate
1 skipped in 0.02s
Exit code: 1
```

The temporary file was removed after the probe. Permanent child-session tests
cover call-time, decorator and collection-time skips, missing dependencies,
borrowed opt-in reasons and enabled solver checks. Allowed skips are the exact
disabled Abaqus/wheel opt-in tests and a missing Torch import in the offline
profile. CI retains the Ubuntu/Windows matrix, installed-wheel check and CPU
training job, and adds CPU ML/PyG execution. All pytest commands use `-rs` and
`--strict-markers`. Remote CI was not dispatched in this worktree-only task.

## Final verification

The offline environment is nested under the repository's `.venv/offline-verification/`
and contains `.[dev]`; the main `.venv` additionally contains CPU Torch/PyG.

```powershell
$env:EXP2CPFE_TEST_PROFILE = "offline"
.\.venv\offline-verification\Scripts\python.exe -m pytest -q -rs --strict-markers
# 751 passed, 8 skipped in 58.47s

$env:EXP2CPFE_TEST_PROFILE = "ml"
.\.venv\Scripts\python.exe -m pytest -q -rs --strict-markers
# 761 passed, 2 skipped in 59.53s

.\.venv\Scripts\python.exe -m build --outdir runs/maintenance-20260927/dist-final
# Successfully built experiment_to_cpfe-0.2.0.tar.gz and experiment_to_cpfe-0.2.0-py3-none-any.whl
.\.venv\Scripts\python.exe -m twine check --strict "runs/maintenance-20260927/dist-final/*"
# wheel: PASSED
# sdist: PASSED

$env:EXP2CPFE_WHEEL_DIR = "runs/maintenance-20260927/dist-final"
.\.venv\Scripts\python.exe -m pytest -q -rs --strict-markers tests/integration/test_installed_wheel.py tests/unit/test_derived_exports.py::test_pyg_is_real_data_with_portable_full_payload
# 2 passed in 9.30s
```

Both full profiles gained 65 passing cases. The offline skips are Torch-related
imports and the two disabled integration opt-ins; the ML full suite skips those
two opt-ins. Wheel verification was then explicitly enabled and passed.

The archive audit inspected 79 wheel members and 205 sdist files. Both contain
LICENSE, NOTICE and THIRD_PARTY_NOTICES.md, with zero matches for the retired
numeric owner identifier. Historical planning and dated verification Markdown
remain source-repository archives; current guides, example assets, tests and
scripts form the source distribution. The audit confirmed preservation of
18 historical documents, published changelog entries and every existing
assertion in the modified test files. `git diff --check` and `pip check` passed.

Ruff 0.16.9 was run for inventory:

```text
python -m ruff check src tests scripts examples --statistics --output-format json
Exit code: 1
Total findings: 294
```

The largest categories were I001 133, C408 81, TRY004 15, PLW1510 12,
RUF059 11, UP017 10 and F401 8. No Ruff configuration, CI lint gate or automatic
fix was introduced.

## Local evidence and remaining verification

Raw command output and audit JSON are in `runs/maintenance-20260927/`:
`baseline-*.log`, `phase1-red-cross-field.log`, `phase1-green.log`,
`phase5-red.log`, `phase4-red.log`, `phase4-5-green.log`,
`skip-probe-blocked.log`, `hash-script-red.log`, `report-and-hash-green.log`,
`field-review-red.log`, `field-review-green.log`, `full-*-final.log`,
`build-final.log`, `twine-final.log`, `wheel-and-pyg-final.log`,
`ruff-statistics-final.json` and `final-audit.json`.

This Windows run has no new Linux execution or real Abaqus execution evidence.
The twelve historical tensile cases were not rehashed; the supplied checksum
script was tested on synthetic directories. Their dated report now identifies
the local artifact location and checksum evidence needed for third-party review.
Retry behavior remains a [design proposal](../retry-design.md) for maintainer
approval. The original dated conclusions and released changelog entries are
preserved; current prose presents capabilities, inputs, operations and evidence.

## Publication follow-up — 2026-09-27

After review, the maintainer authorized publication. The repaired source is being
released as patch version 0.2.1 through the existing GitHub release channel.
The earlier version/worktree statements above describe the completed repair
checkpoint. Publication checks are recorded in the
[v0.2.1 release record](2026-09-27-v0.2.1-release.md).
