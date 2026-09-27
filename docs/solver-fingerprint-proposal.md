# Solver fingerprint design — confirmed 2026-09-27

This proposal addresses stage 3 of the 2026-09-27 second hardening request.
The maintainer approved explicit probe arguments on 2026-09-27. The interface
below is implemented and covered by synthetic Windows and Linux tests.

## Confirmed interface

Use optional `abaqus.version_probe_args`, for example `["information=release"]`
for an Abaqus launcher or `["--version"]` for an explicitly configured wrapper.
Append these arguments to the effective command parsed from configuration or
`EXP2CPFE_ABAQUS_COMMAND`. Use a three-second probe timeout and the existing
owned-process cleanup mechanism. The default empty setting records the command
file and its streamed digest, with a `not_configured` version-probe status.
The execution timeout is three seconds; owned-process cleanup follows the
runner's existing process-tree handling.

## Recorded identity

The initial `runtime.solver` snapshot records:

- effective command argv;
- executable/launcher resolution directory and resolved absolute file path;
- SHA-256 through the existing streaming `sha256_file` function;
- command-file kind, including an explicit batch-launcher classification;
- version string when the selected probe completes successfully;
- probe argv, timeout, return code/status and a reason for unavailable fields.

The recorded identity path resolves symlinks for hashing. Probe execution keeps
the selected launcher path so a Python virtual-environment symlink retains its
environment. The effective configured argv and actual probe argv are both stored.

For batch launchers the digest describes the resolved launcher file. This scope
is recorded explicitly. Windows probing uses the existing batch-command wrapper.
Missing commands, unreadable command files, invalid probe invocation, timeout
and nonzero/empty version output produce null fields and diagnostic reasons.
Fingerprint diagnostics leave the surrounding operation's status semantics intact.

## Stage identity and immutable history

Keep the initial runtime snapshot fixed. Capture a separate solver snapshot
before each datacheck, analysis and extraction invocation and attach it to that
stage's receipt. This makes a changed environment override or replaced command
file visible without replacing an earlier runtime fingerprint or artifact digest.
The addition makes solver changes visible in stage history while existing
execution and artifact checks determine stage status.

Keep manifest schema version 0.1 with additive fields. Existing readers and
callers retain their current interfaces through optional keyword arguments.

## Tests and implementation

Use synthetic command files and Python helpers for resolution, known digests,
environment argv, missing executables, unreadable files, successful/empty/failed
version output, bounded timeout, batch-launcher diagnostics, and preservation of
the initial runtime snapshot across stages. A successful validate run with an
absent solver and a POSIX symlink-environment regression cover graceful
diagnostics and launcher identity. These checks execute synthetic launchers.

Implementation locations: `provenance/manifest.py`,
`provenance/solver_fingerprint.py`, `config.py`, `pipeline.py`,
`solvers/abaqus/runner.py`, and `tests/unit/test_solver_fingerprint.py`.
