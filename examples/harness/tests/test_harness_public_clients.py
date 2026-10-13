"""Public CLI and no-model client acceptance, with reusable local evidence output.

Only tool discovery, public JSON operations and the operator init command are
used. This is an automation-client test; no language model is invoked.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[3]
CASE = ROOT / "examples" / "paramaterial_tensile"
CLIENT = ROOT / "examples" / "harness" / "contract_client.py"
STOPPED = {"completed", "failed", "cancelled", "interrupted", "blocked", "paused", "waiting_human"}


def save_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((CASE / "data").iterdir()) if path.is_file()}


def exercise_public_routes(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    calls = destination / "cli-calls"
    calls.mkdir()
    workspace = destination / "workspace"
    before = source_hashes()
    save_new(destination / "source-hashes-before.json", before)
    sequence = 0

    def command(label, argv, request=None, *, timeout=120):
        nonlocal sequence
        sequence += 1
        started = time.monotonic()
        process = subprocess.Popen(argv, cwd=destination, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            stdout, stderr = process.communicate(
                json.dumps(request, ensure_ascii=False) if request is not None else None, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        record = {"label": label, "argv": [str(item) for item in argv], "request": request,
                  "caller_pid": process.pid, "returncode": process.returncode,
                  "elapsed_seconds": time.monotonic() - started,
                  "stdout": stdout, "stderr": stderr, "caller_process_exited": process.poll() is not None}
        save_new(calls / f"{sequence:03d}-{label}.json", record)
        assert process.returncode == 0, record
        value = json.loads(stdout)
        return value

    cli = [sys.executable, "-I", "-B", "-m", "experiment_to_cpfe.cli", "harness"]
    installation_script = (
        "import json,sys,importlib.metadata as m,experiment_to_cpfe as p; "
        "d=m.distribution('experiment-to-cpfe'); "
        "print(json.dumps(dict(version=d.version,package_file=p.__file__,python_executable=sys.executable,"
        "isolated=sys.flags.isolated,distribution_source=json.loads(d.read_text('direct_url.json') or 'null'))))")
    installation = command("installed-package", [sys.executable, "-I", "-B", "-c", installation_script])
    assert installation["isolated"] == 1 and installation["version"]
    assert Path(installation["python_executable"]).resolve() == Path(sys.executable).resolve()
    save_new(destination / "installation.json", installation)
    discovery = command("discovery", [*cli, "tools", "list", "--json"])
    names = {tool["name"] for tool in discovery}
    assert {"task.create", "task.start", "task.status", "artifacts.read", "reports.get"} <= names
    assert all(tool["input_schema"] and tool["output_schema"] for tool in discovery)
    save_new(destination / "tool-discovery.json", discovery)
    command("operator-init", [*cli, "init", "--workspace", str(workspace), "--case-dir", str(CASE)])

    def call(tool, **fields):
        assert tool in names
        request = {"schema_version": "harness.v1", "request_id": uuid.uuid4().hex,
                   "workspace_id": "local", **fields}
        result = command(tool.replace(".", "-"),
                         [*cli, "call", tool, "--workspace", str(workspace), "--request-json", "-"], request)
        assert result["ok"], result
        assert result["request_id"] == request["request_id"]
        return result["data"]

    def pages(tool, run_id):
        items, cursor = [], 0
        while True:
            page = call(tool, run_id=run_id, cursor=cursor, limit=100)
            items.extend(page["items"])
            # Events expose a live resume cursor, including an unchanged cursor
            # on an empty page; the terminal snapshot is complete at that point.
            if page["next_cursor"] is None or not page["items"]:
                return {"items": items, "next_cursor": None, "resume_cursor": page["next_cursor"]}
            assert page["next_cursor"] > cursor
            cursor = page["next_cursor"]

    capabilities = call("capabilities.get")
    validation = call("inputs.validate")
    assert validation["valid"] and validation["total_rows"] == 1889
    assert len(validation["specimen_ids"]) == 3
    plan = call("task.plan", workflow_id="paramaterial_tensile.v1")
    create_fields = dict(workflow_id="paramaterial_tensile.v1", idempotency_key="public-cli-create",
                         expected_plan_digest=plan["plan_digest"])
    created = call("task.create", **create_fields)
    # Each call is a separate, fully exited process. No long-lived CLI parent is retained.
    start_fields = dict(run_id=created["run_id"], expected_state_version=created["state_version"],
                        idempotency_key="public-cli-start")
    started = call("task.start", **start_fields)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = call("task.status", run_id=created["run_id"])
        if status["execution_status"] in STOPPED:
            break
        time.sleep(.2)
    assert status["execution_status"] == "completed", status
    report = call("reports.get", run_id=created["run_id"])
    artifacts = pages("artifacts.list", created["run_id"])
    events = pages("events.list", created["run_id"])
    assert len(status["attempts"]) == 1
    assert sum(item["kind"] == "execution_started" for item in events["items"]) == 1
    run_artifact = next(item for item in artifacts["items"] if item["relative_path"] == "run.json")
    run_evidence = call("artifacts.read", artifact_id=run_artifact["artifact_id"], view="json")["data"]
    assert run_evidence["cases_processed"] == 3 and run_evidence["total_rows"] == 1889
    cli_result = dict(client_kind="documented_cli_separate_processes", capabilities=capabilities,
                      validation=validation, plan=plan, created=created, started=started,
                      status=status, report=report, artifacts=artifacts, events=events, run_evidence=run_evidence)
    save_new(destination / "cli-result.json", cli_result)

    # Retry the same create and start requests via new CLI processes: retain the run and attempt.
    replay_created = call("task.create", **create_fields)
    replay_started = call("task.start", **start_fields)
    replay_status = call("task.status", run_id=created["run_id"])
    replay_events = pages("events.list", created["run_id"])
    assert replay_created["run_id"] == replay_started["run_id"] == created["run_id"]
    assert replay_status["attempts"] == status["attempts"]
    assert replay_events == events
    save_new(destination / "cli-replay.json", dict(created=replay_created, started=replay_started,
              status=replay_status, events=replay_events))

    client_argv = [sys.executable, "-I", "-B", str(CLIENT), "--workspace", str(workspace),
                   "--idempotency-key", "public-client-create", "--replicate"]
    automatic = command("automatic-client", client_argv, timeout=180)
    save_new(destination / "automatic-client.json", automatic)
    assert automatic["client_kind"] == "no_model_contract_client"
    assert automatic["run_id"] != created["run_id"]
    assert automatic["status"]["execution_status"] == "completed"
    assert len(automatic["status"]["attempts"]) == 1
    assert automatic["input_validation"]["total_rows"] == 1889
    assert len(automatic["input_validation"]["specimen_ids"]) == 3
    assert automatic["run_evidence"]["total_rows"] == 1889
    assert automatic["run_evidence"]["cases_processed"] == 3
    assert automatic["tool_calls"] and all(item["tool"] in names for item in automatic["tool_calls"])
    assert automatic["events"]["next_cursor"] is None
    assert automatic["artifacts"]["next_cursor"] is None
    assert sum(item["kind"] == "execution_started" for item in automatic["events"]["items"]) == 1
    automatic_replay = command("automatic-client-replay", client_argv, timeout=120)
    save_new(destination / "automatic-client-replay.json", automatic_replay)
    assert automatic_replay["run_id"] == automatic["run_id"]
    assert automatic_replay["status"]["attempts"] == automatic["status"]["attempts"]
    assert automatic_replay["events"] == automatic["events"]

    for result in (cli_result, automatic):
        accepted = result["report"]
        assert accepted["execution_status"] == "completed"
        assert accepted["overall_acceptance"] == "accepted"
        assert accepted["scientific_claim_status"] == "not_established"
        assert len(accepted["criterion_results"]) == 9
        assert all(item["status"] == "met" for item in accepted["criterion_results"])
        hdf5 = [item for item in result["artifacts"]["items"] if item["relative_path"].endswith("sample.h5")]
        assert len(hdf5) == 3 and all(item["sha256"] and item["size_bytes"] > 0 for item in hdf5)
    assert report["semantic_sha256"] == automatic["report"]["semantic_sha256"]
    after = source_hashes()
    save_new(destination / "source-hashes-after.json", after)
    assert before == after
    summary = dict(format="harness-public-client-acceptance-1", checked_at=datetime.now(timezone.utc).isoformat(),
        cli_run_id=created["run_id"], automatic_run_id=automatic["run_id"], independent_executions=2,
        specimens=3, original_rows=1889, accepted_numeric_criteria=9, source_files_unchanged=True,
        cli_replay_computations=0, automatic_replay_computations=0,
        semantic_sha256=report["semantic_sha256"], semantic_results_equal=True,
        package_code_sha256=capabilities["environment"]["package_code_sha256"],
        frozen_case_files=validation["files"], cli_attempts=len(status["attempts"]),
        automatic_attempts=len(automatic["status"]["attempts"]),
        execution_status="completed", overall_acceptance="accepted", scientific_claim_status="not_established",
        installation_mode="editable" if (installation["distribution_source"] or {}).get("dir_info", {}).get("editable") else "wheel_or_standard",
        real_model_agent_executed=False, model_calls=0, solver_executed=False, training_executed=False,
        scope="Real fixed-case computation through scripted documented CLI commands and a no-model public-tool client; no human usability study, real-model-agent or scientific generalization acceptance.")
    save_new(destination / "summary.json", summary)
    return summary


def test_public_cli_and_no_model_client_match_without_duplicate_computation(tmp_path):
    result = exercise_public_routes(tmp_path / "public-evidence")
    assert result["overall_acceptance"] == "accepted"


@pytest.mark.parametrize("execution,acceptance,exit_code", [
    ("completed", "accepted", 0), ("waiting_human", "accepted", 1),
    ("paused", "accepted", 1), ("failed", "accepted", 1), ("completed", "rejected", 1),
])
def test_client_exit_requires_completed_execution_and_acceptance(monkeypatch, tmp_path, execution, acceptance, exit_code):
    """Terminal-outcome fixtures isolate CLI exit policy from costly execution."""
    spec = importlib.util.spec_from_file_location("public_contract_client", CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outcome = dict(client_kind="no_model_contract_client", task_id="task_fixture", run_id="run_fixture",
                   status={"execution_status": execution}, report={"overall_acceptance": acceptance},
                   artifacts={"items": [], "next_cursor": None}, events={"items": [], "next_cursor": None})
    monkeypatch.setattr(module, "run", lambda *args, **kwargs: outcome)
    monkeypatch.setattr(sys, "argv", [str(CLIENT), "--workspace", str(tmp_path), "--idempotency-key", "terminal-fixture"])
    assert module.main() == exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(exercise_public_routes(arguments.evidence_dir), ensure_ascii=False, indent=2))
