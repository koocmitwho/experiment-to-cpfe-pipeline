"""Command-line interface for explicit pipeline stages."""

import argparse
import json
from pathlib import Path
import sys
from experiment_to_cpfe import __version__
from experiment_to_cpfe.errors import PipelineError

from experiment_to_cpfe.pipeline import (
    inspect_run,
    run_abaqus_stage,
    run_build_inp,
    run_export,
    run_extract_odb,
    run_validate,
    run_stage_input_bundle,
)

DATA_COMMANDS = {
    "normalize-sample": "Normalize declared data and units into canonical samples.",
    "import-experiment-file": "Preserve declared file context, original metadata and source hashes.",
    "check-evaluation-protocol": "Check declared identities, groups and saved metric evidence.",
    "check-intake-status": "Record reviewed handoff states and their supporting evidence.",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, description in DATA_COMMANDS.items():
        command = commands.add_parser(name, help=description, description=description)
        command.add_argument("--config", required=True, type=Path)
        command.add_argument("--run-dir", required=True, type=Path)
    for name in ("adapt", "build-training-dataset", "train-surrogate", "infer-surrogate", "evaluate-surrogate", "validate", "build-inp", "stage-input-bundle", "extract-odb"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True, type=Path)
        command.add_argument("--run-dir", required=True, type=Path)
    run = commands.add_parser("run-abaqus")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--run-dir", required=True, type=Path)
    run.add_argument("--stage", required=True, choices=("datacheck", "analysis"))
    export = commands.add_parser("export")
    export.add_argument("--config", required=True, type=Path)
    export.add_argument("--run-dir", required=True, type=Path)
    export.add_argument("--format", required=True, choices=("hdf5", "npz", "pyg"))
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--run-dir", required=True, type=Path)
    template=commands.add_parser('template-config',help='Draft scalar inference/evaluation config with preserved declarations.')
    template.add_argument('--kind',required=True,choices=('infer-surrogate','evaluate-surrogate'))
    template.add_argument('--from-config',required=True,type=Path)
    template.add_argument('--output',required=True,type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        if args.command == 'template-config':
            from experiment_to_cpfe.learning.templates import make_template,write_template
            result=write_template(args.output,make_template(args.kind,from_config=args.from_config))
            print(json.dumps(result,ensure_ascii=False))
            return 0
        elif args.command == 'infer-surrogate':
            from experiment_to_cpfe.learning.inference import run_inference
            result=run_inference(args.config,args.run_dir)
        elif args.command == 'evaluate-surrogate':
            from experiment_to_cpfe.learning.inference import run_evaluation
            result=run_evaluation(args.config,args.run_dir)
        elif args.command == "normalize-sample":
            from experiment_to_cpfe.datasets.normalization import run_normalization
            result = run_normalization(args.config, args.run_dir)
        elif args.command == "import-experiment-file":
            from experiment_to_cpfe.adapters.experiment_file import run_experiment_file
            result = run_experiment_file(args.config, args.run_dir)
        elif args.command == "check-evaluation-protocol":
            from experiment_to_cpfe.evaluation_protocol import run_evaluation_protocol
            result = run_evaluation_protocol(args.config, args.run_dir)
        elif args.command == "check-intake-status":
            from experiment_to_cpfe.intake_status import run_intake_status
            result = run_intake_status(args.config, args.run_dir)
        elif args.command == "build-training-dataset":
            from experiment_to_cpfe.datasets.training import run_dataset_build
            result = run_dataset_build(args.config, args.run_dir)
        elif args.command == "train-surrogate":
            from experiment_to_cpfe.learning.surrogate import run_training
            result = run_training(args.config, args.run_dir)
        elif args.command == "adapt":
            from experiment_to_cpfe.adapters.native_runner import run_native_adapt
            result = run_native_adapt(args.config, args.run_dir)
        elif args.command == "validate":
            result = run_validate(args.config, args.run_dir)
        elif args.command == "build-inp":
            result = run_build_inp(args.config, args.run_dir)
        elif args.command == "stage-input-bundle":
            result = run_stage_input_bundle(args.config, args.run_dir)
        elif args.command == "run-abaqus":
            result = run_abaqus_stage(args.config, args.run_dir, args.stage)
        elif args.command == "extract-odb":
            result = run_extract_odb(args.config, args.run_dir)
        elif args.command == "export":
            result = run_export(args.config, args.run_dir, args.format)
        else:
            print(json.dumps(inspect_run(args.run_dir), indent=2, sort_keys=True))
            return 0
    except (PipelineError, OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.command == "check-evaluation-protocol":
        # Exit status describes report generation, not scientific conclusions.
        # Unmet thresholds and holdouts are findings in a completed report;
        # malformed configuration or evidence takes the error path above.
        completed = True
    elif args.command == "check-intake-status":
        completed = result.get("processing_status") == "completed"
    else:
        completed = result.get("status") == "completed"
    if args.command in DATA_COMMANDS:
        print(json.dumps(result, ensure_ascii=False, indent=2),
              file=sys.stdout if completed else sys.stderr)
    else:
        status = result.get("status", "completed" if completed else "failed")
        detail = "; ".join(str(item) for item in result.get("limitations", ()))
        summary = f"{args.command}: {status}; run directory: {args.run_dir}"
        if detail:
            summary += f"; {detail}"
        print(summary, file=sys.stdout if completed else sys.stderr)
    return 0 if completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
