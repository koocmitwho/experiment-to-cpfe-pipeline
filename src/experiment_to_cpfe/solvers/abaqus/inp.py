"""Template-driven Abaqus INP generation guarded by solver readiness."""

from dataclasses import dataclass
from pathlib import Path
import re

from experiment_to_cpfe.provenance.hashing import sha256_file
from experiment_to_cpfe.schema.models import SamplePackage
from experiment_to_cpfe.schema.validation import ValidationPolicy, check_deck_readiness, check_solver_readiness


KNOWN_MARKERS = frozenset(
    {
        "HEADING",
        "NODES",
        "ELEMENTS",
        "MATERIALS",
        "BOUNDARY_CONDITIONS",
        "OUTPUT_REQUESTS",
    }
)
MARKER_PATTERN = re.compile(r"\{\{([A-Z_]+)\}\}")


@dataclass(frozen=True)
class SolverInputRequest:
    template_path: Path
    output_path: Path
    replacements: dict[str, str]


@dataclass(frozen=True)
class InpBuildResult:
    output_path: Path
    sha256: str
    replacements: tuple[str, ...]


def build_inp(request: SolverInputRequest) -> InpBuildResult:
    output_path = Path(request.output_path)
    if output_path.exists():
        raise FileExistsError(output_path)
    rendered, markers = render_inp(request.template_path, request.replacements)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    return InpBuildResult(
        output_path=output_path,
        sha256=sha256_file(output_path),
        replacements=tuple(sorted(markers)),
    )


def render_inp(template_path: Path, replacements: dict[str, str]) -> tuple[str, set[str]]:
    """Render in memory for validation before creating the output file."""
    template = Path(template_path).read_text(encoding="utf-8")
    if "\x00" in template:
        raise ValueError("INP template contains a null byte")

    markers = set(MARKER_PATTERN.findall(template))
    unknown = markers - KNOWN_MARKERS
    if unknown:
        raise ValueError(f"unknown INP template markers: {sorted(unknown)}")
    missing = markers - set(replacements)
    if missing:
        raise ValueError(f"missing INP replacements: {sorted(missing)}")

    rendered = template
    for marker in markers:
        value = replacements[marker]
        if not value or "\x00" in value:
            raise ValueError(f"replacement {marker} is empty or invalid")
        rendered = rendered.replace(f"{{{{{marker}}}}}", value)
    if MARKER_PATTERN.search(rendered):
        raise ValueError("unresolved INP template marker")

    return rendered, markers


def build_solver_input(
    sample: SamplePackage,
    template_path: Path,
    output_path: Path,
    policy: ValidationPolicy | None = None,
) -> InpBuildResult:
    readiness = check_solver_readiness(sample, "abaqus_cpfe", policy)
    if not readiness.ready:
        raise ValueError("; ".join(readiness.missing))
    replacements = sample.solver_inputs.get("inp_replacements")
    if not isinstance(replacements, dict):
        raise ValueError("MISSING_SOLVER_INPUT: inp_replacements")
    if not all(isinstance(value, str) for value in replacements.values()):
        raise ValueError("INP replacements must be strings")
    rendered, markers = render_inp(template_path, replacements)
    readiness = check_deck_readiness(sample, rendered, policy)
    if not readiness.ready:
        raise ValueError("; ".join(readiness.missing))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    return InpBuildResult(output_path, sha256_file(output_path), tuple(sorted(markers)))
