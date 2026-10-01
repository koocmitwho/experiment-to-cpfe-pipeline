# Public release checklist

Apply this checklist to the release candidate: tracked and non-ignored new
files, build archives and reachable Git history. Record the version, commands
and results in a dated verification report.

For `v0.1.0`, see [the release record](verification/2026-09-06-v0.1.0-release.md).
For `v0.2.0`, see [the data-foundation record](verification/2026-09-26-data-foundation.md)
and [the validation/CI repair record](verification/2026-09-27-validation-ci-hardening.md).
For `v0.2.1`, see [the release validation record](verification/2026-09-27-v0.2.1-release.md).
For `v0.2.2`, see [the solver fingerprint and release record](verification/2026-09-27-v0.2.2-release.md).

## Tests and packaging

- [ ] `python -m pytest -q -rs --strict-markers` passes in the offline environment.
  The skip gate accepts disabled Abaqus/wheel opt-ins and missing Torch imports
  in `EXP2CPFE_TEST_PROFILE=offline`; every other skip fails the session.
  Enable the wheel-installation and real-Abaqus tests for their respective checks.
- [ ] `python -m build` produces both sdist and wheel, and installing the wheel
  outside the source checkout finds the default policy and ODB extraction script.
- [ ] The synthetic multimodal validate/build/HDF5/NPZ/inspect flow completes in
  a new run directory. HDF5 round-trip preserves the declared arrays and metadata.
- [ ] Install CPU Torch and `.[dev,ml]`; use `EXP2CPFE_TEST_PROFILE=ml` and execute
  the real PyG serialization/readback test and full suite.
- [ ] Data-validation failures and incomplete/changed extraction evidence block
  formal export. Valid solver-incomplete experimental samples remain exportable.
- [ ] Check native INCLUDE dependencies through the CLI, including path
  confinement, input binding, staging and semantic solver readiness.
- [ ] For an authorized real-solver check, record datacheck, compile/link,
  analysis, ODB extraction and export. Record missing inputs or toolchain
  requirements when blocked. Report test-double results as offline tests.
- [ ] Resolve audit findings with regression coverage, or document their effect
  on the release's supported use cases.

## Files and sources

- [ ] Review `git ls-files --cached --others --exclude-standard`, including
  `docs/superpowers/` and dated verification documents, as a source-tree review.
- [ ] Review wheel/sdist members separately. `MANIFEST.in` keeps historical
  plans and historical dated verification Markdown as repository archives;
  `docs/verification/2026-09-30-public-usability.md` is the explicit current-release
  report exception in `MANIFEST.in`. Current guides,
  example assets, tests and scripts form the source distribution. Verify these
  exclusions and the attribution in `NOTICE` against the built archives.
- [ ] Keep raw experiments, ODB/CAE files, checkpoints, private material cards,
  run manifests, credentials and machine configuration in local storage.
  Check that candidates and build archives exclude them and local installation paths.
- [ ] Review reachable history for the same categories. Record historical
  findings and their disposition separately from working-tree changes.
- [ ] Review credential and path matches in context. Reports identify the file,
  line and category, with sensitive values redacted.
- [ ] Use small synthetic fixtures or inputs with confirmed redistribution
  rights. Keep source manifests in the repository and downloaded inputs locally.
- [ ] Record origin and redistribution rights for every included UMAT/VUMAT.
- [ ] Documentation distinguishes semantic parsing from native asset registration,
  implemented solver profiles from extension points, and toolchain checks from
  scientific CPFE validation.

## Publication

- [ ] Use the repository's configured author identity. Obtain the maintainer's
  details if configuration is missing.
- [ ] Verify the configured remote and repository visibility against the
  authorized destination. Push to that repository using a normal fast-forward update.
- [ ] Stage only the reviewed candidate, inspect the staged diff, commit and push
  after the tests and file review pass.
- [ ] Verify remote CI on the uploaded commit and report the commit and run link.
- [ ] Include Apache-2.0 `LICENSE`, project `NOTICE`, third-party attribution and
  SPDX package metadata, using the scope recorded in [licensing.md](licensing.md).
- [ ] Check package metadata with `python -m twine check --strict <dist-files>`.
- [ ] Publish a new annotated version tag and GitHub Release after all CI jobs
  pass, attaching the verified wheel and sdist and version-specific install links.
- [ ] Download the published attachments and verify their contents and installation.

Project code uses Apache-2.0. The listed public tensile materials use CC-BY-4.0.
