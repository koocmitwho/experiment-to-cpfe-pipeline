"""Fail-closed semantic checks for the v1 flat, static Abaqus contract.

The adapter compares explicit material, geometry, loading and output declarations
with the supplied input deck.
"""

from collections import Counter
from dataclasses import dataclass, field
import math
from numbers import Real

import numpy as np

from experiment_to_cpfe.schema.models import SamplePackage


@dataclass
class KeywordBlock:
    name: str
    options: dict[str, str]
    rows: list[list[str]] = field(default_factory=list)


def parse_keyword_blocks(text: str) -> list[KeywordBlock]:
    blocks: list[KeywordBlock] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        parts = [part.strip() for part in line.split(",")]
        if line.startswith("*"):
            options = {}
            for part in parts[1:]:
                if part:
                    key, _, value = part.partition("=")
                    options[key.strip().upper()] = value.strip().strip('"')
            blocks.append(KeywordBlock(parts[0].upper(), options))
        elif blocks:
            blocks[-1].rows.append(parts)
        else:
            raise ValueError("data before first INP keyword")
    return blocks


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, Real)):
        raise ValueError("expected a finite numeric value")
    number = float(value.replace("D", "E").replace("d", "e") if isinstance(value, str) else value)
    if not math.isfinite(number):
        raise ValueError("expected a finite numeric value")
    return number


def _label(value: object) -> int:
    number = _number(value)
    if number < 1 or not number.is_integer():
        raise ValueError("labels must be positive integers")
    return int(number)


def _flatten(block: KeywordBlock) -> list[str]:
    return [value for row in block.rows for value in row if value]


def inspect_mesh(blocks: list[KeywordBlock]) -> tuple[dict[int, tuple[float, ...]], dict[int, tuple[int, ...]], dict[str, set[int]], dict[str, set[int]], list[str]]:
    nodes: dict[int, tuple[float, ...]] = {}
    elements: dict[int, tuple[int, ...]] = {}
    nsets: dict[str, set[int]] = {}
    elsets: dict[str, set[int]] = {}
    errors: list[str] = []
    # This adapter's explicitly supported solid connectivities. Higher-order,
    # shell and assembly-scoped elements need their own checked profiles.
    sizes = {"C3D4": 4, "C3D8": 8, "C3D8R": 8, "C3D10": 10, "C3D20": 20, "C3D20R": 20}
    for block in blocks:
        if block.name not in {"*NODE", "*ELEMENT"}:
            continue
        target = nodes if block.name == "*NODE" else elements
        for row in block.rows:
            try:
                label = _label(row[0])
                if label in target:
                    raise ValueError(f"duplicate {block.name[1:].lower()} label {label}")
                if block.name == "*NODE":
                    coordinates = tuple(_number(value) for value in row[1:] if value)
                    if len(coordinates) != 3:
                        raise ValueError("node must have three explicit coordinates")
                    nodes[label] = coordinates
                    if "NSET" in block.options:
                        nsets.setdefault(block.options["NSET"].upper(), set()).add(label)
                else:
                    connectivity = tuple(_label(value) for value in row[1:] if value)
                    expected = sizes.get(block.options.get("TYPE", "").upper())
                    if expected is None:
                        raise ValueError("unsupported element type in v1 flat solid adapter")
                    if len(connectivity) != expected or len(set(connectivity)) != expected:
                        raise ValueError(f"invalid element {label} connectivity")
                    elements[label] = connectivity
                    if "ELSET" in block.options:
                        elsets.setdefault(block.options["ELSET"].upper(), set()).add(label)
            except (ValueError, TypeError, IndexError) as exc:
                errors.append(str(exc))
    if not nodes:
        errors.append("missing explicit mesh nodes")
    if not elements:
        errors.append("missing explicit mesh elements")
    for label, connectivity in elements.items():
        if not set(connectivity).issubset(nodes):
            errors.append(f"element {label} references unknown node labels")
    for block in blocks:
        if block.name not in {"*NSET", "*ELSET"}:
            continue
        key = block.name[1:]
        known = nodes if key == "NSET" else elements
        sets = nsets if key == "NSET" else elsets
        name = block.options.get(key, "").upper()
        try:
            if not name:
                raise ValueError(f"missing {key} name")
            labels = set()
            if "GENERATE" in block.options:
                for row in block.rows:
                    start, end, stride = (_label(value) for value in row)
                    if end < start or (end - start) % stride:
                        raise ValueError(f"invalid generated {key}")
                    if (end - start) // stride + 1 > len(known):
                        raise ValueError(f"generated {key} exceeds available labels")
                    labels.update(range(start, end + 1, stride))
            else:
                for value in _flatten(block):
                    if value.upper() in sets:
                        labels.update(sets[value.upper()])
                    else:
                        labels.add(_label(value))
            if not labels or not labels.issubset(known):
                raise ValueError(f"{key} {name} has missing or unknown labels")
            sets.setdefault(name, set()).update(labels)
        except (ValueError, TypeError) as exc:
            errors.append(str(exc))
    return nodes, elements, nsets, elsets, errors


def _mapping_errors(sample: SamplePackage, nodes: dict, elements: dict, elsets: dict) -> list[str]:
    errors: list[str] = []
    mapping = sample.solver_inputs.get("microstructure_mapping")
    grains = {str(row.get("grain_id")) for row in sample.tables.get("grains", [])}
    regions = sample.solver_inputs.get("material_region_mapping")
    if regions is not None:
        if mapping or sample.solver_inputs.get("material_model") not in {"isotropic_elastic", "isotropic_plastic"} or sample.solver_inputs.get("orientation_required") is not False:
            return ["material regions require an explicitly orientation-independent isotropic model"]
        if not isinstance(regions, dict) or not regions:
            return ["explicit material region mapping required"]
        for region, labels in regions.items():
            if not isinstance(labels, (list, tuple)) or str(region).upper() not in elsets or set(labels) != elsets[str(region).upper()]:
                return ["material region mapping differs from actual named element set"]
        mapping, grains = regions, set(regions)
    assigned: dict[int, str] = {}
    if not isinstance(mapping, dict) or not mapping:
        return ["explicit microstructure-to-mesh mapping required"]
    try:
        for grain, labels in mapping.items():
            if str(grain) not in grains:
                raise ValueError("microstructure mapping references unknown grain ID")
            if not isinstance(labels, (list, tuple)) or not labels:
                raise ValueError("microstructure mapping requires element label lists")
            for value in labels:
                label = _label(value)
                if label in assigned:
                    raise ValueError("microstructure mapping assigns an element more than once")
                assigned[label] = str(grain)
        if set(assigned) != set(elements):
            raise ValueError("microstructure mapping must cover exactly the actual mesh elements")
        rows = sample.tables.get("mesh_elements", [])
        if rows:
            table_labels = [_label(row["element_id"]) for row in rows]
            if len(table_labels) != len(set(table_labels)) or set(table_labels) != set(elements):
                raise ValueError("mesh element table IDs differ from actual INP")
            for row, label in zip(rows, table_labels):
                if "grain_id" in row and str(row["grain_id"]) != assigned.get(label):
                    raise ValueError("mesh table grain mapping differs from actual assignment")
                if "connectivity" in row and tuple(_label(x) for x in row["connectivity"]) != elements[label]:
                    raise ValueError("mesh table connectivity differs from actual INP")
        rows = sample.tables.get("mesh_nodes", [])
        if rows:
            table_nodes = {_label(row["node_id"]): tuple(_number(row[axis]) for axis in ("x", "y", "z")) for row in rows}
            if len(table_nodes) != len(rows) or table_nodes != nodes:
                raise ValueError("mesh node table differs from actual INP")
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    return errors


def _material_errors(sample: SamplePackage, blocks: list[KeywordBlock], elements: dict, elsets: dict) -> list[str]:
    errors: list[str] = []
    materials = [b for b in blocks if b.name == "*MATERIAL"]
    sections = [b for b in blocks if b.name == "*SOLID SECTION"]
    model = sample.solver_inputs.get("material_model")
    parameters = sample.solver_inputs.get("material_parameters")
    try:
        if len(materials) != 1 or not materials[0].options.get("NAME"):
            raise ValueError("v1 requires one explicitly named material")
        material_name = materials[0].options["NAME"].upper()
        assigned = []
        for section in sections:
            if section.options.get("MATERIAL", "").upper() != material_name:
                raise ValueError("solid section references unknown material")
            labels = elsets.get(section.options.get("ELSET", "").upper())
            if not labels:
                raise ValueError("solid section references missing element set")
            assigned.extend(labels)
        if Counter(assigned) != Counter({label: 1 for label in elements}):
            raise ValueError("solid section material assignments must cover each element exactly once")
        if not isinstance(parameters, dict):
            raise ValueError("structured numeric material_parameters required")
        elastic = [b for b in blocks if b.name == "*ELASTIC"]
        user = [b for b in blocks if b.name == "*USER MATERIAL"]
        depvar = [b for b in blocks if b.name == "*DEPVAR"]
        if model in {"isotropic_elastic", "isotropic_plastic"}:
            expected = {"E", "nu", "plastic"} if model == "isotropic_plastic" else {"E", "nu"}
            if set(parameters) != expected:
                raise ValueError("isotropic material parameters differ from the declared profile")
            modulus, poisson = _number(parameters["E"]), _number(parameters["nu"])
            if modulus <= 0 or not -1 < poisson < 0.5:
                raise ValueError("invalid isotropic elastic parameters")
            if len(elastic) != 1 or user or depvar or elastic[0].options:
                raise ValueError("isotropic_elastic requires one plain *ELASTIC material definition")
            if [_number(value) for value in _flatten(elastic[0])] != [modulus, poisson]:
                raise ValueError("material parameters differ from actual *ELASTIC values")
            plastic = [b for b in blocks if b.name == "*PLASTIC"]
            if model == "isotropic_elastic" and plastic:
                raise ValueError("elastic profile contains an undeclared plastic material")
            if model == "isotropic_plastic":
                rows = parameters["plastic"]
                if not isinstance(rows, list) or len(rows) < 2 or any(not isinstance(r, (list, tuple)) or len(r) != 2 for r in rows):
                    raise ValueError("plastic table requires stress/plastic-strain pairs")
                table = [[_number(v) for v in row] for row in rows]
                if table[0][1] != 0 or any(s <= 0 or e < 0 for s, e in table) or any(b[1] <= a[1] or b[0] < a[0] for a, b in zip(table, table[1:])):
                    raise ValueError("plastic table requires positive nondecreasing stress and increasing strain starting at zero")
                if len(plastic) != 1 or plastic[0].options or [[_number(v) for v in row] for row in plastic[0].rows] != table:
                    raise ValueError("plastic parameters differ from actual *PLASTIC rows")
        elif model == "umat":
            if any(b.name == "*PLASTIC" for b in blocks):
                raise ValueError("UMAT material contract includes an incompatible built-in plastic table")
            constants = parameters.get("constants")
            units = parameters.get("constant_units")
            count = _label(parameters.get("depvar"))
            if not isinstance(constants, list) or not constants or not isinstance(units, list) or len(units) != len(constants):
                raise ValueError("UMAT requires numeric constants and an explicit unit for every constant")
            from experiment_to_cpfe.schema.validation import _unit_is_declared
            if not all(_unit_is_declared(unit) for unit in units):
                raise ValueError("UMAT constant units are unresolved")
            values = [_number(value) for value in constants]
            if len(user) != 1 or elastic or len(depvar) != 1:
                raise ValueError("UMAT requires one *USER MATERIAL and *DEPVAR")
            if _label(user[0].options.get("CONSTANTS")) != len(values) or [_number(value) for value in _flatten(user[0])] != values:
                raise ValueError("UMAT constants differ from actual *USER MATERIAL")
            if len(_flatten(depvar[0])) != 1 or _label(_flatten(depvar[0])[0]) != count:
                raise ValueError("UMAT state variable count differs from *DEPVAR")
        else:
            raise ValueError("unsupported material model; v1 adapters: isotropic_elastic, umat")
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        errors.append(str(exc))
    return errors


def _loading_errors(sample: SamplePackage, blocks: list[KeywordBlock], nodes: dict, nsets: dict) -> list[str]:
    errors: list[str] = []
    try:
        declarations = sample.solver_inputs.get("boundary_conditions")
        if not isinstance(declarations, list) or not declarations or not all(isinstance(x, dict) for x in declarations):
            raise ValueError("boundary_conditions require structured target/DOF/value records")
        declared = []
        for row in declarations:
            declared.append((str(row["target"]).upper(), _label(row["first_dof"]), _label(row["last_dof"]), _number(row["value"])))
        actual = []
        restraints: dict[tuple[int, int], float] = {}
        step_open = False
        nonzero_load = False
        for block in blocks:
            if block.name == "*STEP":
                step_open = True
            elif block.name == "*END STEP":
                step_open = False
            if block.name != "*BOUNDARY":
                continue
            if block.options:
                raise ValueError("boundary options require an additional v1 adapter")
            for row in block.rows:
                if len(row) != 4:
                    raise ValueError("boundary row must explicitly declare target, first/last DOF and value")
                target, first, last, value = row[0].upper(), _label(row[1]), _label(row[2]), _number(row[3])
                if not 1 <= first <= last <= 3:
                    raise ValueError("boundary DOFs must be in 1..3 for v1 solid elements")
                if target not in nsets and _label(target) not in nodes:
                    raise ValueError("boundary target is not a node or node set")
                if value and not step_open:
                    raise ValueError("nonzero displacement loading must occur inside the analysis step")
                nonzero_load = nonzero_load or value != 0
                target_nodes = nsets[target] if target in nsets else {_label(target)}
                for node in target_nodes:
                    for dof in range(first, last + 1):
                        location = (node, dof)
                        if location in restraints:
                            raise ValueError("overlapping boundary conditions require explicit boundary-update semantics")
                        restraints[location] = value
                actual.append((target, first, last, value))
        if Counter(actual) != Counter(declared):
            raise ValueError("boundary conditions differ from actual *BOUNDARY records")
        if not nonzero_load:
            raise ValueError("explicit nonzero displacement loading required by v1 static profile")
        rigid_constraints = []
        for node, dof in restraints:
            x, y, z = nodes[node]
            rigid_constraints.append((
                (1, 0, 0, 0, z, -y),
                (0, 1, 0, -z, 0, x),
                (0, 0, 1, y, -x, 0),
            )[dof - 1])
        if np.linalg.matrix_rank(np.asarray(rigid_constraints)) < 6:
            raise ValueError("boundary conditions leave unconstrained rigid-body modes")
        steps = [b for b in blocks if b.name == "*STEP"]
        ends = [b for b in blocks if b.name == "*END STEP"]
        statics = [b for b in blocks if b.name == "*STATIC"]
        loads = sample.solver_inputs.get("load_steps")
        if len(steps) != 1 or len(ends) != 1 or len(statics) != 1 or not isinstance(loads, list) or len(loads) != 1 or not isinstance(loads[0], dict):
            raise ValueError("v1 loading requires one explicitly named static load step")
        load = loads[0]
        if str(load.get("name", "")).upper() != steps[0].options.get("NAME", "").upper() or not load.get("name") or load.get("procedure") != "static":
            raise ValueError("loading declaration differs from actual named static step")
        numbers = [_number(value) for value in _flatten(statics[0])]
        if len(numbers) not in (2, 4) or numbers[:2] != [_number(load["initial_increment"]), _number(load["time_period"])]:
            raise ValueError("loading time values differ from actual *STATIC record")
        if any(value <= 0 for value in numbers) or numbers[0] > numbers[1]:
            raise ValueError("static step time/increments must be positive and ordered")
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    return errors


def _initial_solution_values(blocks: list[KeywordBlock], count: int, elements: dict, elsets: dict) -> dict[int, tuple[float, ...]]:
    """Read explicit Abaqus TYPE=SOLUTION records with 7/8 value lines.

    The first line has one target plus up to seven values. Continuation lines
    have up to eight values. This adapter requires all DEPVAR values explicitly;
    Abaqus blank/default initialization is deliberately outside this contract.
    """
    initialized: dict[int, tuple[float, ...]] = {}
    for block in blocks:
        if block.name != "*INITIAL CONDITIONS":
            continue
        if block.options != {"TYPE": "SOLUTION"}:
            raise ValueError("only explicit *INITIAL CONDITIONS, TYPE=SOLUTION is supported")
        cursor = 0
        while cursor < len(block.rows):
            first = list(block.rows[cursor])
            cursor += 1
            if first and first[-1] == "":
                first.pop()
            if not first or len(first) != min(count, 7) + 1:
                raise ValueError("initial STATEV first line must explicitly supply target and up to seven values")
            target = first[0].upper()
            values = [_number(value) for value in first[1:]]
            while len(values) < count:
                if cursor >= len(block.rows):
                    raise ValueError("initial STATEV continuation is missing DEPVAR values")
                row = list(block.rows[cursor])
                cursor += 1
                if row and row[-1] == "":
                    row.pop()
                if len(row) != min(8, count - len(values)):
                    raise ValueError("initial STATEV continuation must explicitly supply up to eight remaining values")
                values.extend(_number(value) for value in row)
            labels = elsets[target] if target in elsets else {_label(target)}
            if not labels or not labels.issubset(elements):
                raise ValueError("initial STATEV target references unknown elements")
            for label in labels:
                if label in initialized:
                    raise ValueError("initial STATEV element assignment overlaps another target")
                initialized[label] = tuple(values)
    if set(initialized) != set(elements):
        raise ValueError("initial STATEV assignments must cover each mapped mesh element exactly once")
    return initialized


def _orientation_errors(sample: SamplePackage, blocks: list[KeywordBlock], elements: dict, elsets: dict) -> list[str]:
    """Verify user-declared orientation columns against explicit UMAT STATEV."""
    required = sample.solver_inputs.get("orientation_required", True) is not False
    initial = any(block.name == "*INITIAL CONDITIONS" for block in blocks)
    layout = sample.solver_inputs.get("orientation_state_variables")
    if sample.metadata.orientation.representation == "not_applicable" and (required or layout is not None):
        return ["required crystal orientation must have a resolved representation"]
    if not required and not initial and layout is None:
        return []
    try:
        if sample.solver_inputs.get("material_model") != "umat":
            raise ValueError("orientation STATEV initialization requires an explicit UMAT material contract")
        parameters = sample.solver_inputs.get("material_parameters")
        if not isinstance(parameters, dict):
            raise ValueError("orientation STATEV initialization requires explicit DEPVAR count")
        count = _label(parameters.get("depvar"))
        initialized = _initial_solution_values(blocks, count, elements, elsets)
        if not required and layout is None:
            return []
        if not isinstance(layout, dict) or set(layout) != {"columns", "indices"}:
            raise ValueError("orientation_state_variables requires explicit columns and indices")
        orientation = sample.metadata.orientation
        from experiment_to_cpfe.schema.validation import _unit_is_declared
        if not _unit_is_declared(orientation.convention) or not _unit_is_declared(orientation.crystal_symmetry):
            raise ValueError("orientation convention and crystal symmetry must be explicitly resolved")
        if orientation.representation == "euler" and orientation.angle_units not in {"degree", "radian"}:
            raise ValueError("Euler orientation requires explicit degree/radian units")
        if orientation.representation in {"quaternion", "rotation_matrix"} and orientation.angle_units is not None:
            raise ValueError("quaternion/matrix orientation values are dimensionless, not angles")
        size = {"euler": 3, "quaternion": 4, "rotation_matrix": 9}.get(orientation.representation)
        columns = layout["columns"]
        raw_indices = layout["indices"]
        if not isinstance(columns, list) or not isinstance(raw_indices, list) or len(columns) != size or len(raw_indices) != size:
            raise ValueError("orientation columns and STATEV indices must match representation size")
        if not all(isinstance(column, str) and column.strip() for column in columns) or len(set(columns)) != size:
            raise ValueError("orientation columns must be unique explicit column names")
        indices = [_label(index) for index in raw_indices]
        if len(set(indices)) != size or any(index > count for index in indices):
            raise ValueError("orientation STATEV indices must be unique and within DEPVAR")
        mapping = sample.solver_inputs.get("microstructure_mapping")
        if not isinstance(mapping, dict):
            raise ValueError("orientation initialization requires explicit grain-to-element mapping")
        grains = {str(row.get("grain_id")): row for row in sample.tables.get("grains", [])}
        for grain, labels in mapping.items():
            if str(grain) not in grains:
                raise ValueError("orientation mapping references unknown grain")
            row = grains[str(grain)]
            if any(column not in row for column in columns):
                raise ValueError("mapped grain lacks a declared orientation column")
            expected = tuple(_number(row[column]) for column in columns)
            if orientation.representation == "quaternion" and not math.isclose(math.hypot(*expected), 1.0, rel_tol=0, abs_tol=1e-6):
                raise ValueError("mapped grain quaternion is not normalized")
            if orientation.representation == "rotation_matrix":
                matrix = np.asarray(expected).reshape(3, 3)
                if not np.allclose(matrix @ matrix.T, np.eye(3), rtol=0, atol=1e-6) or not math.isclose(float(np.linalg.det(matrix)), 1.0, rel_tol=0, abs_tol=1e-6):
                    raise ValueError("mapped grain rotation matrix must be orthonormal and proper")
            for label in labels:
                state = initialized[_label(label)]
                if tuple(state[index - 1] for index in indices) != expected:
                    raise ValueError("initial STATEV orientation values differ from the mapped grain")
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return [str(exc)]
    return []


def solver_contract_errors(sample: SamplePackage, deck_text: str) -> tuple[str, ...]:
    try:
        blocks = parse_keyword_blocks(deck_text)
    except ValueError as exc:
        return (str(exc),)
    allowed = {"*HEADING", "*NODE", "*ELEMENT", "*NSET", "*ELSET", "*MATERIAL", "*ELASTIC", "*PLASTIC", "*USER MATERIAL", "*DEPVAR", "*SOLID SECTION", "*BOUNDARY", "*STEP", "*STATIC", "*OUTPUT", "*ELEMENT OUTPUT", "*NODE OUTPUT", "*END STEP", "*INITIAL CONDITIONS"}
    errors = [f"unsupported v1 keyword semantics: {name}" for name in sorted({b.name for b in blocks} - allowed)]
    options = {"*NODE": {"NSET"}, "*ELEMENT": {"TYPE", "ELSET"}, "*NSET": {"NSET", "GENERATE"}, "*ELSET": {"ELSET", "GENERATE"}, "*MATERIAL": {"NAME"}, "*USER MATERIAL": {"CONSTANTS", "UNSYMM"}, "*SOLID SECTION": {"ELSET", "MATERIAL"}, "*STEP": {"NAME", "NLGEOM", "INC"}, "*OUTPUT": {"FIELD", "FREQUENCY"}, "*INITIAL CONDITIONS": {"TYPE"}}
    for block in blocks:
        unknown = set(block.options) - options.get(block.name, set())
        if unknown:
            errors.append(f"unsupported options on {block.name}: {', '.join(sorted(unknown))}")
    opened = False
    step_seen = False
    field_request = False
    for block in blocks:
        if block.name == "*STEP":
            if opened:
                errors.append("nested analysis step")
            opened = True
            step_seen = True
        elif block.name == "*END STEP":
            if not opened:
                errors.append("unmatched end step")
            opened = False
        elif block.name in {"*STATIC", "*OUTPUT", "*ELEMENT OUTPUT", "*NODE OUTPUT"} and not opened:
            errors.append(f"{block.name} must occur inside the analysis step")
        elif block.name in {"*NODE", "*ELEMENT", "*MATERIAL", "*SOLID SECTION", "*ELASTIC", "*PLASTIC", "*USER MATERIAL", "*DEPVAR", "*INITIAL CONDITIONS"} and step_seen:
            errors.append(f"{block.name} must occur before the analysis step")
        if block.name == "*OUTPUT":
            field_request = "FIELD" in block.options
        if block.name in {"*ELEMENT OUTPUT", "*NODE OUTPUT"} and not field_request:
            errors.append("field variables require a preceding *OUTPUT, FIELD block")
    if opened:
        errors.append("missing *END STEP")
    nodes, elements, nsets, elsets, mesh_errors = inspect_mesh(blocks)
    errors.extend(mesh_errors)
    errors.extend(_mapping_errors(sample, nodes, elements, elsets))
    errors.extend(_material_errors(sample, blocks, elements, elsets))
    errors.extend(_loading_errors(sample, blocks, nodes, nsets))
    errors.extend(_orientation_errors(sample, blocks, elements, elsets))
    requested = sample.solver_inputs.get("output_variables")
    declared = {v.upper() for b in blocks if b.name in {"*ELEMENT OUTPUT", "*NODE OUTPUT"} for v in _flatten(b)}
    if not isinstance(requested, list) or not requested or not all(isinstance(value, str) for value in requested):
        errors.append("explicit output variable list required")
    elif not set(requested).issubset(declared):
        errors.append("output variables are absent from actual INP output requests")
    elif sample.solver_inputs.get("material_model") == "isotropic_elastic" and any(v == "PEEQ" or v.startswith("SDV") for v in requested):
        errors.append("isotropic_elastic cannot provide requested PEEQ/SDV evidence")
    if any(value not in {"S", "LE", "E", "U", "RF", "COORD", "SDV"} and not (value.startswith("SDV") and value[3:].isdigit()) for value in declared):
        errors.append("unsupported output variable in v1 extraction contract")
    for block in blocks:
        if block.name == "*ELEMENT OUTPUT" and any(value.upper() in {"U", "RF"} for value in _flatten(block)):
            errors.append("U/RF require *NODE OUTPUT")
        if block.name == "*NODE OUTPUT" and any(value.upper() not in {"U", "RF", "COORD"} for value in _flatten(block)):
            errors.append("element field requested as node output")
    if not any(b.name == "*OUTPUT" and "FIELD" in b.options for b in blocks):
        errors.append("explicit field output request required")
    return tuple(errors)
