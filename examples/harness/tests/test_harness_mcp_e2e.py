"""Real stdio MCP acceptance with inspectable, exclusively local evidence.

The failure this catches is an adapter that advertises tools but changes core
request/response semantics, resubmits an already completed run, or conceals an
interruption caused by the Windows client's process-tree shutdown policy.
No language model, solver or remote service is used.

Run with the installed MCP extra and fixed-case dependencies::

    python -I -B test_harness_mcp_e2e.py --output-dir ABSOLUTE_NEW_DIRECTORY
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid


ROOT = Path(__file__).resolve().parents[3]
CASE = ROOT / "examples" / "paramaterial_tensile"
STOPPED = {"completed", "failed", "cancelled", "interrupted", "blocked", "paused", "waiting_human"}
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
EXPECTED_TOOLS = {
    "harness_capabilities_get", "harness_inputs_register", "harness_inputs_validate",
    "harness_task_plan", "harness_task_create", "harness_task_start",
    "harness_task_status", "harness_task_reconcile", "harness_task_control",
    "harness_events_list", "harness_artifacts_list", "harness_artifacts_read",
    "harness_evaluation_start", "harness_reports_get", "harness_handoffs_list",
    "harness_handoffs_submit", "harness_runs_list",
}


def save_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def source_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((CASE / "data").iterdir()) if path.is_file()}


def request(**fields):
    return dict(schema_version="harness.v1", request_id=uuid.uuid4().hex,
                workspace_id="local", **fields)


def cleanup_owned_run(workspace, run_id):
    """Cancel only this test's run through the same public business boundary."""
    if run_id is None or not (workspace / "workspace.json").exists():
        return dict(required=False, confirmed_stopped=True, calls=[])
    from experiment_to_cpfe.harness import HarnessClient
    client = HarnessClient(workspace)
    calls = []
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = client.call("task.status", request(run_id=run_id))
        calls.append(dict(tool="task.status", response=status))
        if not status["ok"]:
            break
        data = status["data"]
        if data["execution_status"] in TERMINAL:
            return dict(required=True, confirmed_stopped=True, status=data, calls=calls)
        cancelled = client.call("task.control", request(
            run_id=run_id, expected_state_version=data["state_version"],
            idempotency_key="mcp-e2e-cleanup-" + uuid.uuid4().hex,
            action="cancel", reason="Local MCP acceptance cleanup after failure or timeout."))
        calls.append(dict(tool="task.control", response=cancelled))
        if cancelled["ok"] and cancelled["data"]["execution_status"] in TERMINAL:
            return dict(required=True, confirmed_stopped=True, status=cancelled["data"], calls=calls)
        time.sleep(.1)
    return dict(required=True, confirmed_stopped=False, calls=calls)


async def exercise_mcp_routes(destination):
    destination = Path(destination)
    if not destination.is_absolute():
        raise ValueError("--output-dir must be an absolute path to a new directory")
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    calls = destination / "calls"
    calls.mkdir()
    workspace = destination / "workspace"
    before = source_hashes()
    save_new(destination / "source-hashes-before.json", before)
    run_id = None
    sequence = 0
    successful = False

    def command(label, argv, payload=None):
        nonlocal sequence
        sequence += 1
        process = subprocess.run(argv, cwd=destination,
            input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=120)
        record = dict(label=label, argv=[str(part) for part in argv], request=payload,
                      returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
        save_new(calls / f"{sequence:03d}-{label}.json", record)
        assert process.returncode == 0, record
        return process.stdout

    try:
        server_argv = [sys.executable, "-I", "-B", "-m", "experiment_to_cpfe.harness.mcp"]
        # This first real process also gives a clear RED before the adapter exists.
        command("mcp-entrypoint", [*server_argv, "--help"])
        from mcp import Client, StdioServerParameters
        from experiment_to_cpfe.harness import HarnessClient, initialize_workspace

        initialize_workspace(workspace, CASE)
        core = HarnessClient(workspace)
        core_catalog = {item["name"]: item for item in core.tools()}
        parameters = StdioServerParameters(command=sys.executable,
            args=[*server_argv[1:], "--workspace", str(workspace)], cwd=str(destination))

        async def call(client, tool, payload=None, *, expect_ok=True, **fields):
            nonlocal sequence
            payload = request(**fields) if payload is None else payload
            result = await client.call_tool("harness_" + tool.replace(".", "_"), payload)
            sequence += 1
            record = dict(tool=tool, request=payload, response=result.model_dump(mode="json", by_alias=True))
            save_new(calls / f"{sequence:03d}-{tool.replace('.', '-')}.json", record)
            assert len(result.content) == 1 and result.content[0].type == "text", record
            envelope = json.loads(result.content[0].text)
            assert result.structured_content == envelope, record
            assert result.is_error is (not envelope["ok"]), record
            assert envelope["schema_version"] == "harness.v1"
            assert envelope["request_id"] == payload["request_id"]
            assert envelope["ok"] is expect_ok, record
            return envelope["data"] if expect_ok else envelope

        async def pages(client, tool):
            items, cursor, page_count = [], 0, 0
            while True:
                page = await call(client, tool, run_id=run_id, cursor=cursor, limit=2)
                page_count += 1
                items.extend(page["items"])
                if page["next_cursor"] is None or not page["items"]:
                    return dict(items=items, next_cursor=None,
                                resume_cursor=page["next_cursor"], page_count=page_count)
                assert page["next_cursor"] > cursor, page
                cursor = page["next_cursor"]
                assert page_count < 200, "Pagination did not terminate"

        # Keep the server connected throughout execution: some Windows clients
        # terminate its entire process tree when their stdio transport closes.
        async with Client(parameters, read_timeout_seconds=30, cache=None) as client:
            discovered = await client.list_tools()
            assert discovered.next_cursor is None
            catalog = discovered.tools
            serialized = [item.model_dump(mode="json", by_alias=True) for item in catalog]
            save_new(destination / "mcp-discovery.json", serialized)
            assert {item.name for item in catalog} == EXPECTED_TOOLS
            for item in catalog:
                core_name = next(name for name in core_catalog
                                 if "harness_" + name.replace(".", "_") == item.name)
                assert item.input_schema == core_catalog[core_name]["input_schema"]
                # Older MCP peers require an object root; core envelopes already
                # are objects, so this declaration does not alter their contract.
                assert item.output_schema == dict(core_catalog[core_name]["output_schema"], type="object")
            capabilities = await call(client, "capabilities.get")
            validation = await call(client, "inputs.validate")
            assert validation["valid"] and validation["total_rows"] == 1889
            assert len(validation["specimen_ids"]) == 3
            invalid = request(run_id="not-a-registered-run")
            denied = await call(client, "task.status", payload=invalid, expect_ok=False)
            assert denied == core.call("task.status", invalid)
            assert denied["error"]["code"] == "INVALID_REQUEST"
            plan = await call(client, "task.plan", workflow_id="paramaterial_tensile.v1")
            assert plan["dry_run"] and plan["estimates"]["model_calls"] == 0
            create_request = request(workflow_id="paramaterial_tensile.v1",
                idempotency_key="mcp-e2e-create", expected_plan_digest=plan["plan_digest"])
            created = await call(client, "task.create", payload=create_request)
            run_id = created["run_id"]
            start_request = request(run_id=run_id, expected_state_version=created["state_version"],
                                    idempotency_key="mcp-e2e-start")
            started = await call(client, "task.start", payload=start_request)
            save_new(destination / "initial-session.json", dict(capabilities=capabilities,
                validation=validation, plan=plan, created=created, started=started))

            deadline = time.monotonic() + 120
            while True:
                status = await call(client, "task.status", run_id=run_id)
                if status["execution_status"] in STOPPED:
                    break
                if status.get("required_action") == "task.reconcile":
                    await call(client, "task.reconcile", run_id=run_id,
                               idempotency_key="mcp-e2e-reconcile-" + str(status["state_version"]))
                assert time.monotonic() < deadline, status
                await asyncio.sleep(.2)
            assert status["execution_status"] == "completed", status
            assert len(status["attempts"]) == 1
            report_request = request(run_id=run_id)
            report = await call(client, "reports.get", payload=report_request)
            artifacts = await pages(client, "artifacts.list")
            events = await pages(client, "events.list")
            assert artifacts["page_count"] > 1 and events["page_count"] > 1
            assert sum(item["kind"] == "execution_started" for item in events["items"]) == 1
            run_artifact = next(item for item in artifacts["items"] if item["relative_path"] == "run.json")
            run_evidence = (await call(client, "artifacts.read",
                artifact_id=run_artifact["artifact_id"], view="json"))["data"]
            assert run_evidence["cases_processed"] == 3 and run_evidence["total_rows"] == 1889
            save_new(destination / "completed-session.json", dict(status=status, report=report,
                artifacts=artifacts, events=events, run_evidence=run_evidence))

        # A new stdio process must reuse the exact completed run and attempt.
        async with Client(parameters, read_timeout_seconds=30, cache=None) as client:
            replay_created = await call(client, "task.create", payload=create_request)
            replay_started = await call(client, "task.start", payload=start_request)
            replay_status = await call(client, "task.status", run_id=run_id)
            replay_events = await pages(client, "events.list")
            replay_report = await call(client, "reports.get", payload=report_request)
            assert replay_created == created and replay_started == started
            assert replay_status["attempts"] == status["attempts"]
            assert replay_events == events and replay_report == report
            save_new(destination / "reconnected-replay.json", dict(created=replay_created,
                started=replay_started, status=replay_status, events=replay_events, report=replay_report))

        python_report = core.call("reports.get", report_request)
        cli_argv = [sys.executable, "-I", "-B", "-m", "experiment_to_cpfe.cli", "harness",
                    "call", "reports.get", "--workspace", str(workspace), "--request-json", "-"]
        cli_report = json.loads(command("cli-report", cli_argv, report_request))
        assert python_report == cli_report and python_report["ok"]
        assert python_report["data"] == report
        save_new(destination / "cross-client-report.json", dict(python=python_report, cli=cli_report,
                                                               mcp_data=report))
        assert report["execution_status"] == "completed"
        assert report["overall_acceptance"] == "accepted"
        assert report["scientific_claim_status"] == "not_established"
        assert len(report["criterion_results"]) == 9
        assert all(item["status"] == "met" for item in report["criterion_results"])
        hdf5 = [item for item in artifacts["items"] if item["relative_path"].endswith("sample.h5")]
        assert len(hdf5) == 3 and all(item["sha256"] and item["size_bytes"] > 0 for item in hdf5)
        after = source_hashes()
        save_new(destination / "source-hashes-after.json", after)
        assert before == after
        summary = dict(format="harness-mcp-stdio-acceptance-1",
            checked_at=datetime.now(timezone.utc).isoformat(), run_id=run_id,
            python_executable=sys.executable, transport="stdio", connections=2,
            mcp_sdk_version=importlib.metadata.version("mcp"),
            registered_tools=len(catalog), real_mcp_subprocesses=True,
            specimens=3, original_rows=1889, accepted_numeric_criteria=9,
            attempts=len(status["attempts"]), replay_computations=0,
            artifacts_pages=artifacts["page_count"], events_pages=events["page_count"],
            source_files_unchanged=True, cross_client_reports_equal=True,
            semantic_sha256=report["semantic_sha256"],
            package_code_sha256=capabilities["environment"]["package_code_sha256"],
            execution_status="completed", overall_acceptance="accepted",
            scientific_claim_status="not_established", real_model_agent_executed=False,
            model_calls=0, solver_executed=False, training_executed=False,
            scope="Scripted real MCP stdio client and shared public Python/CLI reports; "
                  "no Codex or Claude model session, solver, usability or scientific generalization acceptance.")
        save_new(destination / "summary.json", summary)
        successful = True
        return summary
    except BaseException as exc:
        save_new(destination / "failure.json", dict(type=type(exc).__name__, message=str(exc),
                                                    traceback=traceback.format_exc(), run_id=run_id))
        raise
    finally:
        if not successful:
            cleanup = cleanup_owned_run(workspace, run_id)
            save_new(destination / "cleanup.json", cleanup)
            if not cleanup["confirmed_stopped"]:
                raise RuntimeError(f"Owned worker cleanup was not confirmed; inspect {destination / 'cleanup.json'}")


def test_real_mcp_stdio_matches_core_and_reconnect_does_not_recompute(tmp_path):
    result = asyncio.run(exercise_mcp_routes(tmp_path / "mcp-evidence"))
    assert result["overall_acceptance"] == "accepted"


async def exercise_windows_transport_shutdown(destination):
    """An observed running attempt interrupted by SDK shutdown stays unaccepted.

    This characterizes the real Windows SDK Job Object boundary. The production
    core, original fixed case, and installed SDK are all unmodified.
    """
    assert sys.platform == "win32", "This acceptance case targets the Windows SDK process-tree policy"
    from mcp import Client, StdioServerParameters
    from experiment_to_cpfe.harness import initialize_workspace

    destination = Path(destination)
    if not destination.is_absolute():
        raise ValueError("--output-dir must be an absolute path to a new directory")
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    calls = destination / "calls"
    calls.mkdir()
    workspace = destination / "workspace"
    initialize_workspace(workspace, CASE)
    before = source_hashes()
    save_new(destination / "source-hashes-before.json", before)
    parameters = StdioServerParameters(command=sys.executable,
        args=["-I", "-B", "-m", "experiment_to_cpfe.harness.mcp", "--workspace", str(workspace)],
        cwd=str(destination))
    run_id, sequence = None, 0

    async def call(client, tool, payload=None, **fields):
        nonlocal sequence
        payload = request(**fields) if payload is None else payload
        result = await client.call_tool("harness_" + tool.replace(".", "_"), payload)
        sequence += 1
        save_new(calls / f"{sequence:03d}-{tool.replace('.', '-')}.json",
            dict(tool=tool, request=payload, response=result.model_dump(mode="json", by_alias=True)))
        envelope = json.loads(result.content[0].text)
        assert result.structured_content == envelope
        assert envelope["request_id"] == payload["request_id"]
        assert envelope["ok"] and not result.is_error, envelope
        return envelope["data"]

    try:
        async with Client(parameters, read_timeout_seconds=30, cache=None) as client:
            await client.list_tools()
            created = await call(client, "task.create", workflow_id="paramaterial_tensile.v1",
                                 idempotency_key="mcp-shutdown-create")
            run_id = created["run_id"]
            start_request = request(run_id=run_id, expected_state_version=created["state_version"],
                                    idempotency_key="mcp-shutdown-start")
            started = await call(client, "task.start", payload=start_request)
            deadline = time.monotonic() + 30
            while True:
                running = await call(client, "task.status", run_id=run_id)
                assert running["execution_status"] not in STOPPED, (
                    "The attempt must still be active when the transport closes", running)
                if running["execution_status"] == "running" and running.get("worker_observation") == "running":
                    break
                assert time.monotonic() < deadline, running
                await asyncio.sleep(.02)
            save_new(destination / "before-disconnect.json", running)

        async with Client(parameters, read_timeout_seconds=30, cache=None) as client:
            await client.list_tools()
            observed = await call(client, "task.status", run_id=run_id)
            assert observed["execution_status"] == "running", observed
            assert observed["worker_observation"] == "stopped", observed
            assert observed["required_action"] == "task.reconcile", observed
            reconciled = await call(client, "task.reconcile", run_id=run_id,
                                    idempotency_key="mcp-shutdown-reconcile")
            assert reconciled["execution_status"] == "interrupted", reconciled
            assert reconciled["reason_code"] == "CHECKPOINT_UNSUPPORTED", reconciled
            assert len(reconciled["attempts"]) == 1
            events = await call(client, "events.list", run_id=run_id, cursor=0, limit=500)
            assert sum(item["kind"] == "execution_started" for item in events["items"]) == 1
            assert any(item["kind"] == "worker_stopped_without_seal" for item in events["items"])
            report = await call(client, "reports.get", run_id=run_id)
            assert report["execution_status"] == "interrupted"
            assert report["overall_acceptance"] == "not_assessed"
            assert (await call(client, "artifacts.list", run_id=run_id))["items"] == []
            # Replaying the already successful start request must not allocate a
            # retry even though its recorded response predates the interruption.
            replay = await call(client, "task.start", payload=start_request)
            final_status = await call(client, "task.status", run_id=run_id)
            final_events = await call(client, "events.list", run_id=run_id, cursor=0, limit=500)
            assert replay == started
            assert final_status["execution_status"] == "interrupted"
            assert final_status["attempts"] == reconciled["attempts"]
            assert final_events == events
            save_new(destination / "after-reconnect.json", dict(observed=observed,
                reconciled=reconciled, report=report, replay=replay, status=final_status, events=final_events))
        after = source_hashes()
        save_new(destination / "source-hashes-after.json", after)
        assert before == after
        summary = dict(format="harness-mcp-windows-shutdown-1",
            checked_at=datetime.now(timezone.utc).isoformat(), run_id=run_id,
            mcp_sdk_version=importlib.metadata.version("mcp"),
            running_observed_before_disconnect=True, stopped_observed_after_disconnect=True,
            execution_status="interrupted", overall_acceptance="not_assessed", attempts=1,
            replay_computations=0, automatic_retries=0, source_files_unchanged=True,
            model_calls=0, solver_executed=False, fixture_injection=False,
            scope="Windows SDK stdio shutdown kills the server process tree; "
                  "reconciliation preserves the interrupted attempt without acceptance or automatic resubmission.")
        save_new(destination / "summary.json", summary)
        return summary
    except BaseException as exc:
        save_new(destination / "failure.json", dict(type=type(exc).__name__, message=str(exc),
                                                    traceback=traceback.format_exc(), run_id=run_id))
        raise
    finally:
        cleanup = cleanup_owned_run(workspace, run_id)
        save_new(destination / "cleanup.json", cleanup)
        if not cleanup["confirmed_stopped"]:
            raise RuntimeError(f"Owned worker cleanup was not confirmed; inspect {destination / 'cleanup.json'}")


def test_windows_mcp_shutdown_preserves_interruption_without_automatic_retry(tmp_path):
    result = asyncio.run(exercise_windows_transport_shutdown(tmp_path / "shutdown-evidence"))
    assert result["execution_status"] == "interrupted"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--scenario", choices=("complete", "windows-shutdown"), default="complete")
    arguments = parser.parse_args()
    exercise = exercise_mcp_routes if arguments.scenario == "complete" else exercise_windows_transport_shutdown
    print(json.dumps(asyncio.run(exercise(arguments.output_dir)), ensure_ascii=False, indent=2))
