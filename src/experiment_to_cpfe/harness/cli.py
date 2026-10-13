"""Structured JSON adapter and explicitly separate operator commands."""
import argparse
import json
from pathlib import Path
import sys

from .contracts import HarnessError, tools


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid command arguments')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate request field')
        result[key] = value
    return result


def _request(source):
    if source == '-':
        text = sys.stdin.read(1024 * 1024 + 1)
    else:
        path = Path(source)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('request is too large')
        text = path.read_text(encoding='utf-8-sig')
    if len(text.encode('utf-8')) > 1024 * 1024:
        raise ValueError('request is too large')
    return json.loads(text, object_pairs_hook=_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite request')))


def main(argv=None):
    parser = Parser(prog='pipeline harness', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('tools')
    listing.add_argument('action', choices=['list'])
    listing.add_argument('--json', action='store_true')
    init = commands.add_parser('init', help='Operator-only: register a new local workspace.')
    init.add_argument('--workspace', required=True, type=Path)
    init.add_argument('--case-dir', required=True, type=Path)
    call = commands.add_parser('call')
    call.add_argument('tool')
    call.add_argument('--workspace', required=True, type=Path)
    call.add_argument('--request-json', required=True)
    approval = commands.add_parser('approve', help='Operator-only: approve exact registered handoff evidence.')
    approval.add_argument('--workspace', required=True, type=Path)
    approval.add_argument('--handoff-id', required=True)
    approval.add_argument('--evidence-id', required=True, action='append')
    approval.add_argument('--reviewer', required=True)
    approval.add_argument('--basis', required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == 'tools':
            result = tools()
        elif args.command == 'init':
            from .service import initialize_workspace
            result = initialize_workspace(args.workspace, args.case_dir)
        elif args.command == 'approve':
            from .service import approve_handoff
            result = approve_handoff(args.workspace, args.handoff_id, args.evidence_id,
                                     reviewer=args.reviewer, basis=args.basis)
        else:
            request = _request(args.request_json)
            from .service import HarnessClient
            result = HarnessClient(args.workspace).call(args.tool, request)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 1 if isinstance(result, dict) and result.get('ok') is False else 0
    except SystemExit as exc:
        return int(exc.code)
    except (ValueError, OSError, HarnessError):
        error = HarnessError('INVALID_REQUEST', 'Command or request is invalid; use the published schema and an initialized workspace.')
        print(json.dumps(dict(schema_version='harness.v1', request_id='', ok=False, data=None, error=error.record())))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
