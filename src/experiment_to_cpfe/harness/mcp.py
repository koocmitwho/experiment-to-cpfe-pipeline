"""Optional local stdio MCP transport over the existing public harness core."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys


def create_server(workspace):
    """Bind one initialized workspace; never expose operator init or approval."""
    import anyio
    from mcp.server import Server
    from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations

    from .service import HarnessClient

    core = HarnessClient(workspace)
    contracts = core.tools()
    names = {'harness_' + item['name'].replace('.', '_'): item['name'] for item in contracts}
    if len(names) != len(contracts):
        raise ValueError('MCP tool names must be unique')
    published = []
    for item in contracts:
        description = (item['description'] + '\nPreconditions: ' + ', '.join(item['preconditions'])
                       + '.\nSide effects: ' + (', '.join(item['side_effects']) or 'none') + '.')
        published.append(Tool(
            name='harness_' + item['name'].replace('.', '_'), description=description,
            input_schema=item['input_schema'], output_schema=dict(item['output_schema'], type='object'),
            annotations=ToolAnnotations(read_only_hint=item['read_only'],
                destructive_hint=not item['read_only'], idempotent_hint=item['idempotent'],
                open_world_hint=False),
            _meta={'experiment-to-cpfe/contract': {key: value for key, value in item.items()
                                                if key not in {'input_schema', 'output_schema'}}}))
    # HarnessClient reloads its policy per call. Keep each server's mutable client
    # serialized, and leave the async protocol loop free to handle ping/cancellation.
    lock = anyio.Lock()

    async def list_tools(ctx, params):
        return ListToolsResult(tools=published)

    async def call_tool(ctx, params):
        # A finite alias map prevents dotted names or operator APIs bypassing discovery.
        name = names.get(params.name, '__unregistered_mcp_tool__')
        async with lock:
            envelope = await anyio.to_thread.run_sync(core.call, name, params.arguments or {})
        return CallToolResult(
            content=[TextContent(type='text', text=json.dumps(envelope, ensure_ascii=False, allow_nan=False))],
            structured_content=envelope, is_error=not envelope['ok'])

    return Server('experiment-to-cpfe-harness', version='harness.v1',
        instructions=('Local Paramaterial harness. Use harness.v1 schemas and workspace_id=local. '
                      'Preserve idempotency keys when retrying the same request. '
                      'Read task status and reports; a successful tool call is not scientific acceptance. '
                      'Request cancellation is not task cancellation; use harness_task_control. '
                      'Keep this connection open while work runs: a host shutdown may terminate workers. '
                      'After reconnecting, inspect status and explicitly reconcile uncertain execution. '
                      'Initialization and approval require the separate operator CLI.'),
        on_list_tools=list_tools, on_call_tool=call_tool)


async def _serve(server):
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        # The SDK owns the protocol descriptors. Divert Python prints too, including
        # buffered dependency output, so interpreter shutdown cannot dirty stdout.
        with redirect_stdout(sys.stderr):
            await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True,
                        help='Existing operator-initialized harness workspace; no automatic init.')
    args = parser.parse_args(argv)
    try:
        # Optional imports stay out of the base CLI/Python import graph.
        with redirect_stdout(sys.stderr):
            import anyio
            import mcp  # noqa: F401
            from .contracts import HarnessError
            try:
                server = create_server(args.workspace)
            except (OSError, ValueError, HarnessError):
                print('MCP workspace unavailable. Initialize a new workspace with pipeline harness init '
                      'and pass its path to --workspace.', file=sys.stderr)
                return 2
    except ImportError:
        print('MCP dependencies are unavailable. Install this checkout with python -m pip install ".[mcp]" '
              'in the interpreter used to start this server.', file=sys.stderr)
        return 2
    try:
        anyio.run(_serve, server)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
