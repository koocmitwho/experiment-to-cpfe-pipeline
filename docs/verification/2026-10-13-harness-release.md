# v0.4.0 harness release verification

Date: 2026-10-13 (Asia/Shanghai). This release adds the Windows local harness,
optional stdio MCP and Chinese browser UI to the public v0.3.1 baseline.
The fixed Paramaterial case, source curves and numerical tolerances are unchanged.
Distribution remains GitHub Release wheel and source archives; no PyPI release.

## Locally verified release candidate

| Check | Result | Command / method |
| --- | --- | --- |
| Existing offline suite | 804 passed, 22 skipped | `EXP2CPFE_TEST_PROFILE=offline`, `python -m pytest -q tests` |
| Windows harness, MCP, HTTP and UI contracts | 207 passed, 1 skipped | `python -m pytest -q examples/harness/tests` |
| Installed-wheel fixed case | 14 passed, 7 subtests passed | `python -m pytest -q examples/paramaterial_tensile/tests -o pythonpath=` |
| Installed-wheel legacy entry points | 1 passed | `tests/integration/test_installed_wheel.py` with `EXP2CPFE_WHEEL_DIR` |
| Installed-wheel MCP complete workflow | accepted | Real stdio subprocess, 17 tools, reconnect/replay and Python/CLI report comparison |
| Installed-wheel UI entry point and assets | passed | CLI help; HTTP 200 for HTML, JavaScript, CSS and SVG, each matching source bytes |
| Actual browser workflow | passed within the scope below | Chromium interaction against the local UI; independent core report readback |

Tests used Python 3.12.10 on Windows, MCP SDK 2.3.0 and the fixed case's pinned
numerical dependencies. The wheel was installed into a separate virtual
environment; imports were checked to originate from its `site-packages`.
Both environments passed `pip check`. Tests did not call a model or Abaqus.

The offline suite's skips cover optional Torch/PyG and disabled Abaqus/wheel
opt-ins; the wheel path was checked separately. The harness skip is ordinary
symlink creation without the required host permission; Windows junction escape
checks ran. Skips are not counted as successful validation.

The installed MCP case preserved all source-file hashes, returned three
specimens and 1,889 rows, accepted all nine numerical criteria, and kept one
attempt with zero additional computations on replay. Python, CLI and MCP
reports agreed. Its semantic digest is:

```text
dfc4369f0abe44f11e5acfa9d751f3231ef5148d4622fe986a935a248650eaa8
```

## Browser verification and limits

The actual browser was used to check an empty workspace, run input preflight,
generate a plan, create/start the fixed case, open completed status and layered
acceptance, display three curves and nine metrics, read the registered
`metrics.csv`, refresh and repeat creation. With unchanged frozen inputs,
environment and plan, repeat creation opened the existing completed task and
did not start another attempt. Browser console inspection recorded no warnings
or errors during this flow. The local test service was stopped after completion.

This is a scripted desktop-browser acceptance of the primary workflow, not an
exhaustive browser/platform matrix or human usability study. Active terminal
closure, all UI control races and real Codex/Claude model sessions were not
separately exercised through the browser. Lower-level tests cover task control,
recovery, approval, stale versions and transport errors. Keep the UI host open
until work finishes; detached background execution is not promised.

## Failed preparation checks retained locally

- Running the installed-case test in an editable development environment
  correctly failed its `site-packages` origin assertion despite completing the
  computation. The unchanged test passed in the separate wheel environment.
- An old generated v0.3.1 `egg-info` directory in the source tree conflicted with
  the installed v0.4.0 metadata. Twelve harness tests were rejected by environment
  identity checks. The generated metadata was moved to local evidence storage,
  not deleted; a focused identity check and the complete harness suite then
  passed without weakening checks or changing harness implementation.
- A browser task created before that metadata change remains separate from a
  task created afterward, as required by the frozen environment identity. A
  further identical request reused the latter task without computation.
- Initial Windows CI installed the wheel but inherited pytest's `pythonpath=src`
  setting for the parent process. Its workers used the installed wheel, so the
  package locations differed and environment checks rejected execution. The
  harness step now clears that source-path injection with `-o pythonpath=` and
  tests the installed package in both processes. No identity check or test was
  removed. Source development tests continue using the editable environment.
- One installed-wheel suite run encountered Windows `PermissionError` / WinError
  5 while atomically replacing `normalization.json.tmp`. The failed attempt and
  both receipt files were retained; no accepted result was published. The cause
  of the transient access denial remains unknown, as in an earlier local check.
  This is an unresolved host/filesystem limitation, not a claimed code fix.

The raw logs, workspaces, absolute-path receipts and screenshots remain in local
evidence storage. They are not included in source or package publication.

## Publication checks

The release process additionally checks wheel/sdist members, strict package
metadata, the source archive's reproducibility and matching artifact contents.
Remote CI results belong to their exact commit/tag; consult the version's
[GitHub Actions history](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/actions)
and [Release](https://github.com/koocmitwho/experiment-to-cpfe-pipeline/releases/tag/v0.4.0).
The release is published only after its remote CI succeeds. This local report
does not substitute for that remote result.

Only the reviewed public code, tests and guides are included. Local runs,
environments, model weights, solver files, machine configuration, historical
local acceptance notes and uncommitted planning notes are excluded.

## Scientific boundary

`scientific_claim_status` remains `not_established`. This verifies fixed-case
data processing, provenance, numerical consistency and software interfaces.
It does not establish material calibration, physical validity, prediction
accuracy, generalization, real model-agent usability, GPU or Abaqus execution.

[中文 UI 指南](../harness-ui.zh-CN.md) · [Harness 指南](../harness.zh-CN.md)
· [MCP 配置](../harness-mcp.zh-CN.md)
