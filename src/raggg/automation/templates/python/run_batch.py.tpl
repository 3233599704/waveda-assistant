"""Portable WavEDA sweep controller.

Run without arguments for the safe automatic workflow:
check -> smoke -> endpoint -> run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
PROGRESS_FIELDS = (
    "task_signature",
    "runtime_signature",
    "point_id",
    "stage",
    "status",
    "attempts",
    "started_at",
    "finished_at",
    "message",
    "assignments_json",
    "result_files_json",
)
FREQUENCY_MULTIPLIERS = {
    "hz": 1.0,
    "khz": 1.0e3,
    "mhz": 1.0e6,
    "ghz": 1.0e9,
}
ENDPOINT_ABSOLUTE_TOLERANCE = 1.0e-9
ENDPOINT_RELATIVE_TOLERANCE = 1.0e-9
MAX_SWEEP_POINTS = 10_000
SAFE_POINT_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def load_config(package_dir=None):
    package = Path(package_dir).resolve() if package_dir else PACKAGE_DIR
    return json.loads(
        (package / "task_config.json").read_text(encoding="utf-8")
    )


def _task_signature(config):
    payload = json.loads(json.dumps(config, ensure_ascii=False))
    payload.pop("package_dir", None)
    payload.pop("task_signature", None)
    payload.pop("task_signature_payload", None)
    payload.pop("_resolved_data_frequency_unit", None)
    payload.pop("data_frequency_unit_resolved", None)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _project_fingerprint(project_file):
    project_path = Path(project_file)
    before = project_path.stat()
    digest = hashlib.sha256()
    with project_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    after = project_path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise RuntimeError(".tsp changed while its signature was calculated.")
    return {
        "size": after.st_size,
        "mtime_ns": after.st_mtime_ns,
        "sha256": digest.hexdigest(),
    }


def build_runtime_signature(config):
    payload = {
        "task_signature": config["task_signature"],
        "project": _project_fingerprint(config["target"]["project_file"]),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prepare_directories(package_dir=None):
    package = Path(package_dir).resolve() if package_dir else PACKAGE_DIR
    paths = {
        "package": package,
        "generated_xml": package / "generated_xml",
        "output": package / "output",
        "raw": package / "output" / "raw",
        "logs": package / "output" / "logs",
        "figures": package / "output" / "figures",
        "progress": package / "output" / "progress.csv",
    }
    for key in ("generated_xml", "output", "raw", "logs", "figures"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def _validate_point_id(point_id):
    text = str(point_id)
    if (
        not text
        or ".." in text
        or SAFE_POINT_ID.fullmatch(text) is None
    ):
        raise ValueError(
            "Unsafe point ID; only ASCII letters, digits, _, ., and - are allowed."
        )
    return text


def _confined_path(root, *parts):
    root_path = Path(root).resolve()
    candidate = root_path.joinpath(*map(str, parts)).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(
            f"Point-derived path escapes its package directory: {candidate}"
        ) from exc
    return candidate


def _confined_result_paths(result_paths, package_dir=None):
    raw_root = prepare_directories(package_dir)["raw"]
    confined = []
    for path in result_paths:
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(raw_root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Result path escapes package output/raw: {resolved}"
            ) from exc
        confined.append(resolved)
    return confined


def _variable_values(variable):
    if "values" in variable:
        return [float(value) for value in variable["values"]]
    start = float(variable["start"])
    stop = float(variable["stop"])
    step = float(variable["step"])
    values = []
    current = start
    tolerance = max(abs(step), 1.0) * 1.0e-10
    compare = (
        (lambda value: value <= stop + tolerance)
        if step > 0
        else (lambda value: value >= stop - tolerance)
    )
    while compare(current):
        values.append(current)
        current = start + step * len(values)
    return values


def _variable_value_count(variable):
    if "values" in variable:
        values = variable["values"]
        if not isinstance(values, list) or not values:
            raise ValueError("Sweep values must be a non-empty list.")
        return len(values)
    start = Decimal(str(variable["start"]))
    stop = Decimal(str(variable["stop"]))
    step = Decimal(str(variable["step"]))
    if step == 0:
        raise ValueError("Sweep step cannot be zero.")
    if (stop - start) * step < 0:
        raise ValueError("Sweep step direction does not reach the stop.")
    return int((stop - start) // step) + 1


def _estimate_sweep_point_count(config):
    total = 1
    for variable in config.get("sweep", {}).get("variables", []):
        total *= _variable_value_count(variable)
        if total > MAX_SWEEP_POINTS:
            raise ValueError(
                f"Sweep would create {total:,} points; "
                f"the hard limit is {MAX_SWEEP_POINTS:,}."
            )
    return total


def _number_text(value):
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return format(number, ".15g")


def _filename_token(value):
    text = _number_text(value)
    if text.startswith("-"):
        text = "m" + text[1:]
    return text.replace(".", "p").replace("+", "")


def _safe_name(name):
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(name)).strip("_")
    return cleaned or "var"


def _derived_planned_points(config):
    sweep = config["sweep"]
    variables = sweep["variables"]
    _estimate_sweep_point_count(config)
    value_sets = [_variable_values(variable) for variable in variables]
    points = []
    for index, combination in enumerate(itertools.product(*value_sets), start=1):
        assignments = [
            {"name": variable["name"], "value": value}
            for variable, value in zip(variables, combination)
        ]
        suffix = "_".join(
            f"{_safe_name(item['name'])}_{_filename_token(item['value'])}"
            for item in assignments
        )
        points.append(
            {
                "id": f"p{index:04d}_{suffix}",
                "assignments": assignments,
            }
        )
    return points


def _planned_points(config):
    supplied = config["sweep"].get("planned_points")
    if isinstance(supplied, dict):
        if supplied.get("mode") != "adaptive_coarse_to_fine":
            raise ValueError(
                f"Unsupported planned point mode: {supplied.get('mode')}"
            )
        points = supplied.get("stage1_points", [])
    elif supplied:
        points = supplied
    else:
        points = _derived_planned_points(config)
    if len(points) > MAX_SWEEP_POINTS:
        raise ValueError(
            f"Packaged plan has {len(points):,} points; "
            f"the hard limit is {MAX_SWEEP_POINTS:,}."
        )
    for point in points:
        _validate_point_id(point.get("id", ""))
    return points


def _expected_endpoint_ids(points):
    if not points:
        return []
    if len(points) == 1:
        return [points[0]["id"]]
    return [points[0]["id"], points[-1]["id"]]


def _initial_variable_value(variable):
    values = variable.get("values")
    if isinstance(values, list) and values:
        return values[0]
    return variable.get("start", 0)


def _validate_template_integrity(config, template_path):
    issues = []
    try:
        template_bytes = Path(template_path).read_bytes()
    except OSError as exc:
        return [f"template.xml cannot be read: {exc}"]
    expected_hash = (
        config.get("integrity", {}).get("template_xml_sha256", "")
    )
    actual_hash = hashlib.sha256(template_bytes).hexdigest()
    if not expected_hash or actual_hash.lower() != str(expected_hash).lower():
        issues.append("template.xml SHA-256 does not match task_config.json.")
    try:
        root = ET.fromstring(template_bytes)
    except ET.ParseError as exc:
        issues.append(f"template.xml cannot be parsed: {exc}")
        return issues

    loads = root.findall("./command[@cmdType='load'][@obj1='project']")
    if (
        len(loads) != 1
        or loads[0].get("file") != config.get("target", {}).get("project_file")
    ):
        issues.append("template.xml structure: project path does not match config.")

    modifications = root.findall("./command[@cmdType='modify'][@obj1='var']")
    expected_modifications = [
        (
            str(variable.get("name", "")).casefold(),
            _number_text(_initial_variable_value(variable)),
        )
        for variable in config.get("sweep", {}).get("variables", [])
    ]
    actual_modifications = [
        (command.get("name", "").casefold(), command.get("value", ""))
        for command in modifications
    ]
    if actual_modifications != expected_modifications:
        issues.append(
            "template.xml structure: variable command does not match config."
        )

    exports = root.findall("./command[@cmdType='export'][@obj1='result']")
    expected_exports = []
    for index, result in enumerate(config.get("results", []), start=1):
        result_type = str(result.get("type", "")).lower().replace(
            "observer", "obv"
        )
        expected_exports.append(
            (
                str(result.get("name", "")).casefold(),
                result_type,
                f"output/raw/result_{index:02d}_{result_type}.txt",
            )
        )
    actual_exports = [
        (
            command.get("name", "").casefold(),
            command.get("obj2", "").lower().replace("observer", "obv"),
            command.get("file", ""),
        )
        for command in exports
    ]
    if actual_exports != expected_exports:
        issues.append(
            "template.xml structure: result export does not match config."
        )

    mesh_deletes = root.findall("./command[@cmdType='delete'][@obj1='mesh']")
    expected_mesh_deletes = (
        1 if config.get("runtime", {}).get("force_remesh", True) else 0
    )
    if len(mesh_deletes) != expected_mesh_deletes:
        issues.append(
            "template.xml structure: remesh command does not match config."
        )
    if len(root.findall("./command[@cmdType='sim']")) != 1:
        issues.append(
            "template.xml structure: simulation command does not match config."
        )
    return issues


def _adaptive_plan(config):
    supplied = config.get("sweep", {}).get("planned_points")
    if (
        isinstance(supplied, dict)
        and supplied.get("mode") == "adaptive_coarse_to_fine"
    ):
        return supplied
    return None


def _assignment_key(assignments):
    return tuple(
        (str(item["name"]), round(float(item["value"]), 12))
        for item in assignments
    )


def _refined_values(coarse_values, best_value, refinement_factor):
    values = sorted({float(value) for value in coarse_values})
    best_index = min(
        range(len(values)),
        key=lambda index: abs(values[index] - float(best_value)),
    )
    refined = {float(best_value)}
    if best_index > 0:
        lower = values[best_index - 1]
        width = float(best_value) - lower
        refined.update(
            lower + width * offset / refinement_factor
            for offset in range(refinement_factor + 1)
        )
    if best_index + 1 < len(values):
        upper = values[best_index + 1]
        width = upper - float(best_value)
        refined.update(
            float(best_value) + width * offset / refinement_factor
            for offset in range(refinement_factor + 1)
        )
    return sorted(refined)


def build_adaptive_stage2_points(config, best_point):
    adaptive = _adaptive_plan(config)
    if adaptive is None:
        return []
    parameters = adaptive["stage2"]
    if parameters.get("neighborhood") != "adjacent_coarse_interval":
        raise ValueError("Unsupported adaptive neighborhood.")
    refinement_factor = int(parameters.get("refinement_factor", 0))
    if refinement_factor < 2:
        raise ValueError("Adaptive refinement_factor must be at least 2.")

    best_values = {
        str(item["name"]): float(item["value"])
        for item in best_point["assignments"]
    }
    variables = config["sweep"]["variables"]
    value_sets = [
        _refined_values(
            _variable_values(variable),
            best_values[str(variable["name"])],
            refinement_factor,
        )
        for variable in variables
    ]
    stage1_keys = {
        _assignment_key(point["assignments"])
        for point in adaptive.get("stage1_points", [])
    }
    points = []
    for combination in itertools.product(*value_sets):
        assignments = [
            {"name": variable["name"], "value": float(value)}
            for variable, value in zip(variables, combination)
        ]
        if (
            parameters.get("exclude_stage1_points", True)
            and _assignment_key(assignments) in stage1_keys
        ):
            continue
        suffix = "_".join(
            f"{_safe_name(item['name'])}_{_filename_token(item['value'])}"
            for item in assignments
        )
        points.append(
            {
                "id": f"a{len(points) + 1:04d}_{suffix}",
                "assignments": assignments,
            }
        )
    return points


def _select_smoke_point(config):
    points = _planned_points(config)
    if len(points) < 2:
        raise ValueError("Smoke test requires a non-baseline sweep point.")
    baseline = points[0]["assignments"]
    for point in points[1:]:
        if point["assignments"] != baseline:
            return point
    raise ValueError("Smoke test requires a non-baseline sweep point.")


def _local_tag(element):
    return str(element.tag).rsplit("}", 1)[-1].lower()


def _inspect_tsp(project_file):
    try:
        root = ET.parse(project_file).getroot()
    except (OSError, ET.ParseError, UnicodeError) as exc:
        return None, [f"Unable to parse WavEDA .tsp XML: {exc}"]
    if _local_tag(root) != "project":
        return None, ["Unrecognized WavEDA .tsp format: root is not project."]

    variable_containers = [
        element for element in root.iter() if _local_tag(element) == "variables"
    ]
    result_containers = {
        result_type: [
            element
            for element in root.iter()
            if _local_tag(element) == container_tag
        ]
        for result_type, container_tag in (
            ("port", "port-results"),
            ("obv", "obv-results"),
        )
    }
    if not variable_containers or not any(result_containers.values()):
        return None, [
            "Unrecognized WavEDA .tsp format: variables or result containers "
            "are missing."
        ]

    project_units = [
        element for element in root.iter() if _local_tag(element) == "project-unit"
    ]
    project_frequency_unit = None
    if project_units:
        project_frequency_unit = str(project_units[0].get("freq", "")).strip()

    variables = {}
    for container in variable_containers:
        for element in container:
            if _local_tag(element) != "var":
                continue
            name = str(element.get("name", "")).strip()
            expression = str(element.get("expression", "")).strip()
            try:
                numeric_expression = float(expression)
                is_expression = not math.isfinite(numeric_expression)
            except ValueError:
                is_expression = True
            if name:
                variables[name.casefold()] = {
                    "name": name,
                    "expression": expression,
                    "is_expression": is_expression,
                }

    results = {}
    for result_type, containers in result_containers.items():
        for container in containers:
            for element in container:
                name = str(element.get("name", "")).strip()
                if name:
                    results[(name.casefold(), result_type)] = {
                        "name": name,
                        "type": result_type,
                    }
    return {
        "variables": variables,
        "results": results,
        "data_frequency_unit": project_frequency_unit,
    }, []


def _frequency_multiplier(unit):
    normalized = str(unit or "").strip().lower()
    if normalized not in FREQUENCY_MULTIPLIERS:
        raise ValueError(
            f"Unsupported data frequency unit: {unit or '<missing>'}"
        )
    return FREQUENCY_MULTIPLIERS[normalized]


def resolve_data_frequency_unit(config, inspection=None):
    explicit = config.get("data_frequency_unit")
    if explicit is not None:
        candidate = str(explicit).strip()
    else:
        if inspection is None:
            inspection, issues = _inspect_tsp(
                config["target"]["project_file"]
            )
            if issues or inspection is None:
                raise ValueError(
                    "Data frequency unit cannot be read from .tsp."
                )
        candidate = str(inspection.get("data_frequency_unit") or "").strip()
    if not candidate:
        raise ValueError(
            "Data frequency unit is missing; set data_frequency_unit "
            "explicitly or add project-unit freq to the .tsp."
        )
    _frequency_multiplier(candidate)
    return candidate.lower()


def _has_port_results(config):
    return any(
        str(result.get("type", "")).lower() == "port"
        for result in config.get("results", [])
    )


def _configured_data_frequency_unit(config):
    if not _has_port_results(config):
        return None
    return config.get("_resolved_data_frequency_unit") or (
        resolve_data_frequency_unit(config)
    )


def preflight_check(config, package_dir=None):
    package = Path(package_dir).resolve() if package_dir else PACKAGE_DIR
    issues = []
    target = config.get("target", {})
    waveda_exe = Path(target.get("waveda_exe", ""))
    project_file = Path(target.get("project_file", ""))
    if not waveda_exe.is_file():
        issues.append(f"WavEDA executable does not exist: {waveda_exe}")
    if not project_file.is_file():
        issues.append(f"External .tsp project does not exist: {project_file}")
    else:
        inspection, inspection_issues = _inspect_tsp(project_file)
        issues.extend(inspection_issues)
        if inspection is not None:
            if _has_port_results(config):
                try:
                    resolve_data_frequency_unit(config, inspection)
                except ValueError as exc:
                    issues.append(str(exc))
            for variable in config.get("sweep", {}).get("variables", []):
                variable_name = str(variable.get("name", ""))
                discovered = inspection["variables"].get(
                    variable_name.casefold()
                )
                if discovered is None:
                    issues.append(
                        f"Sweep variable does not exist in .tsp: {variable_name}"
                    )
                elif discovered["is_expression"]:
                    issues.append(
                        f"Sweep variable is an expression and cannot be "
                        f"modified safely: {variable_name}"
                    )
            for result in config.get("results", []):
                result_name = str(result.get("name", ""))
                result_type = str(result.get("type", "")).lower()
                key = (result_name.casefold(), result_type)
                if key not in inspection["results"]:
                    same_name = any(
                        name == result_name.casefold()
                        for name, _found_type in inspection["results"]
                    )
                    if same_name:
                        issues.append(
                            f"Result node type does not match .tsp: "
                            f"{result_name} ({result_type})"
                        )
                    else:
                        issues.append(
                            f"Result node does not exist in .tsp: "
                            f"{result_name} ({result_type})"
                        )
    template_path = package / "template.xml"
    if not template_path.is_file():
        issues.append(f"XML template does not exist: {template_path}")
    else:
        issues.extend(_validate_template_integrity(config, template_path))
    if config.get("task_signature") != _task_signature(config):
        issues.append("Task signature does not match task_config.json.")
    try:
        supplied_points = _planned_points(config)
        derived_points = _derived_planned_points(config)
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(f"Invalid deterministic sweep plan: {exc}")
    else:
        if supplied_points != derived_points:
            issues.append(
                "Packaged planned_points do not match the deterministic sweep plan."
            )
        expected_endpoint_ids = _expected_endpoint_ids(derived_points)
        if config.get("sweep", {}).get("endpoint_ids") != expected_endpoint_ids:
            issues.append(
                "Packaged endpoint_ids do not match the deterministic sweep plan."
            )
        if config.get("sweep", {}).get("estimated_point_count") != len(
            derived_points
        ):
            issues.append(
                "Packaged estimated_point_count does not match the "
                "deterministic sweep plan."
            )
    variables = config.get("sweep", {}).get("variables", [])
    if len(variables) not in (1, 2):
        issues.append("Only one or two sweep variables are supported.")
    if config.get("sweep", {}).get("strategy") == "builtin_sweep":
        issues.append("Built-in WavEDA sweep is not supported.")
    try:
        paths = prepare_directories(package)
        probe = paths["output"] / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        issues.append(f"Package output directory is not writable: {exc}")
    return issues


def generate_point_xml(config, point, package_dir=None):
    paths = prepare_directories(package_dir)
    point_id = _validate_point_id(point.get("id", ""))
    template_path = paths["package"] / "template.xml"
    root = ET.fromstring(template_path.read_text(encoding="utf-8"))
    assignments = {
        item["name"].casefold(): item["value"]
        for item in point["assignments"]
    }
    matched = set()
    for command in root.findall("./command[@cmdType='modify']"):
        name = command.get("name", "")
        key = name.casefold()
        if key in assignments:
            command.set("value", _number_text(assignments[key]))
            matched.add(key)
    if matched != set(assignments):
        missing = sorted(set(assignments) - matched)
        raise ValueError(f"Variables are missing from template.xml: {missing}")

    point_raw = _confined_path(paths["raw"], point_id)
    point_raw.mkdir(parents=True, exist_ok=True)
    result_paths = []
    for index, command in enumerate(
        root.findall("./command[@cmdType='export']"), start=1
    ):
        result_type = command.get("obj2", "result").lower()
        result_path = (
            point_raw / f"result_{index:02d}_{result_type}.txt"
        ).resolve()
        command.set("file", str(result_path))
        result_paths.append(result_path)

    ET.indent(root, space="    ")
    xml_path = _confined_path(paths["generated_xml"], f"{point_id}.xml")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    xml_path.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n',
        encoding="utf-8",
    )
    return xml_path, result_paths


def _parse_numeric_rows(path):
    rows = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "%")):
            continue
        tokens = [token for token in re.split(r"[\s,;]+", line) if token]
        try:
            values = [float(token) for token in tokens]
        except ValueError:
            numeric_prefix = False
            try:
                float(tokens[0])
                numeric_prefix = True
            except (ValueError, IndexError):
                pass
            if numeric_prefix:
                raise ValueError(f"Malformed numeric row: {line}")
            continue
        if not values:
            raise ValueError(f"Numeric row is empty: {line}")
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"Numeric row contains NaN or Infinity: {line}")
        rows.append(values)
    return rows


def _target_frequency_hz(frequency):
    unit = str(frequency.get("unit", "")).lower()
    if unit not in FREQUENCY_MULTIPLIERS:
        raise ValueError(f"Unsupported frequency unit: {unit}")
    return float(frequency["target"]) * FREQUENCY_MULTIPLIERS[unit]


def parse_port_traces(rows, trace_count, data_frequency_unit):
    if trace_count < 1 or not rows:
        raise ValueError("Port result has no configured traces or data.")
    widths = {len(row) for row in rows}
    multiplier = _frequency_multiplier(data_frequency_unit)
    raw_traces = []
    if widths == {trace_count + 1}:
        for trace_index in range(trace_count):
            raw_traces.append(
                ([row[0] for row in rows], [row[trace_index + 1] for row in rows])
            )
    elif trace_count > 1 and widths == {trace_count * 2}:
        for trace_index in range(trace_count):
            raw_traces.append(
                (
                    [row[trace_index * 2] for row in rows],
                    [row[trace_index * 2 + 1] for row in rows],
                )
            )
    elif trace_count > 1 and widths == {2}:
        blocks = []
        current = []
        for row in rows:
            if current and row[0] <= current[-1][0]:
                blocks.append(current)
                current = []
            current.append(row)
        if current:
            blocks.append(current)
        if len(blocks) != trace_count:
            raise ValueError(
                "Stacked port result block count does not match traces."
            )
        raw_traces = [
            ([row[0] for row in block], [row[1] for row in block])
            for block in blocks
        ]
    else:
        raise ValueError(
            "Port result layout is not shared, paired, or stacked."
        )
    return [
        {
            "frequency_hz": [
                frequency_value * multiplier
                for frequency_value in frequencies
            ],
            "values": values,
        }
        for frequencies, values in raw_traces
    ]


def validate_result(
    path,
    started_at,
    result_spec=None,
    frequency=None,
    data_frequency_unit=None,
):
    result_path = Path(path)
    if not result_path.is_file():
        return False, "Result file was not created.", []
    try:
        if result_path.stat().st_mtime < float(started_at) - 1.0:
            return False, "Result file is older than this simulation.", []
        rows = _parse_numeric_rows(result_path)
    except (OSError, UnicodeError, ValueError) as exc:
        return False, str(exc), []
    if not rows:
        return False, "Result file contains no numeric data.", []
    result_type = str((result_spec or {}).get("type", "generic")).lower()
    if result_type == "port":
        try:
            traces = parse_port_traces(
                rows,
                len((result_spec or {}).get("traces", [])),
                data_frequency_unit,
            )
        except ValueError as exc:
            return False, str(exc), []
        if any(len(trace["frequency_hz"]) < 2 for trace in traces):
            return False, "Each port trace must contain at least two rows.", []
        for trace in traces:
            frequencies = trace["frequency_hz"]
            if any(
                later <= earlier
                for earlier, later in zip(frequencies, frequencies[1:])
            ):
                return False, "Port frequencies must be strictly increasing.", []
            if all(value == 0 for value in trace["values"]):
                return False, "Port trace data is entirely zero.", []
        if frequency is not None:
            try:
                target_hz = _target_frequency_hz(frequency)
            except (KeyError, TypeError, ValueError) as exc:
                return False, str(exc), []
            if any(
                not trace["frequency_hz"][0]
                <= target_hz
                <= trace["frequency_hz"][-1]
                for trace in traces
            ):
                return False, "Target frequency is outside port sweep range.", []
        return True, "ok", traces
    elif result_type not in {"obv", "observer", "generic"}:
        return False, f"Unsupported result type: {result_type}", []
    return True, "ok", rows


def _write_attempt_log(paths, point_id, attempt, completed):
    safe_point_id = _validate_point_id(point_id)
    log_path = _confined_path(
        paths["logs"], f"{safe_point_id}_attempt_{attempt}.log"
    )
    stdout = getattr(completed, "stdout", "") or ""
    stderr = getattr(completed, "stderr", "") or ""
    return_code = getattr(completed, "returncode", "timeout")
    log_path.write_text(
        f"return_code={return_code}\nstdout:\n{stdout}\nstderr:\n{stderr}\n",
        encoding="utf-8",
    )


def run_waveda(config, point, package_dir=None):
    paths = prepare_directories(package_dir)
    xml_path, result_paths = generate_point_xml(config, point, paths["package"])
    runtime = config["runtime"]
    max_attempts = int(runtime["max_attempts"])
    timeout_seconds = float(runtime["timeout_seconds"])
    first_started = None
    last_message = "Simulation did not run."
    for attempt in range(1, max_attempts + 1):
        result_paths = _confined_result_paths(
            result_paths, paths["package"]
        )
        for result_path in result_paths:
            if result_path.exists():
                result_path.unlink()
        started_at = time.time()
        if first_started is None:
            first_started = started_at
        try:
            completed = subprocess.run(
                [
                    config["target"]["waveda_exe"],
                    f"script={xml_path}",
                ],
                cwd=str(Path(config["target"]["waveda_exe"]).resolve().parent),
                timeout=timeout_seconds,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            completed = exc
            last_message = f"Simulation timed out after {timeout_seconds:g}s."
        except OSError as exc:
            completed = SimpleProcessError(str(exc))
            last_message = f"Unable to start WavEDA: {exc}"
        _write_attempt_log(paths, point["id"], attempt, completed)
        validations = [
            validate_result(
                result_path,
                started_at,
                result_spec,
                config.get("frequency"),
                _configured_data_frequency_unit(config),
            )
            for result_path, result_spec in zip(
                result_paths, config.get("results", [])
            )
        ]
        if validations and all(item[0] for item in validations):
            return {
                "success": True,
                "attempts": attempt,
                "started_at": first_started,
                "finished_at": time.time(),
                "message": "ok",
                "result_paths": [str(path) for path in result_paths],
            }
        if validations:
            last_message = "; ".join(
                message for valid, message, _rows in validations if not valid
            )
    return {
        "success": False,
        "attempts": max_attempts,
        "started_at": first_started or time.time(),
        "finished_at": time.time(),
        "message": last_message,
        "result_paths": [str(path) for path in result_paths],
    }


class SimpleProcessError:
    def __init__(self, message):
        self.returncode = "start-error"
        self.stdout = ""
        self.stderr = message


def save_progress(record, package_dir=None):
    paths = prepare_directories(package_dir)
    progress_path = paths["progress"]
    write_header = not progress_path.exists()
    with progress_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROGRESS_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({field: record.get(field, "") for field in PROGRESS_FIELDS})
    return progress_path


def _read_progress(package_dir=None):
    progress_path = prepare_directories(package_dir)["progress"]
    if not progress_path.is_file():
        return []
    with progress_path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _reusable_result_paths(
    config, point, package_dir=None, runtime_signature=None
):
    if not config["runtime"].get("resume", True):
        return None
    signature = config["task_signature"]
    current_runtime_signature = runtime_signature or build_runtime_signature(
        config
    )
    matching = [
        row
        for row in _read_progress(package_dir)
        if row.get("task_signature") == signature
        and row.get("runtime_signature") == current_runtime_signature
        and row.get("point_id") == point["id"]
        and row.get("status") == "completed"
    ]
    for row in reversed(matching):
        try:
            result_paths = json.loads(row["result_files_json"])
            started_at = float(row["started_at"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        try:
            result_paths = _confined_result_paths(result_paths, package_dir)
        except ValueError:
            continue
        if (
            result_paths
            and len(result_paths) == len(config.get("results", []))
            and all(
                validate_result(
                    path,
                    started_at,
                    result_spec,
                    config.get("frequency"),
                    _configured_data_frequency_unit(config),
                )[0]
                for path, result_spec in zip(
                    result_paths, config.get("results", [])
                )
            )
        ):
            return result_paths
    return None


def _record_result(
    config,
    point,
    stage,
    result,
    package_dir=None,
    runtime_signature=None,
):
    record = {
        "task_signature": config["task_signature"],
        "runtime_signature": runtime_signature
        or build_runtime_signature(config),
        "point_id": point["id"],
        "stage": stage,
        "status": "completed" if result["success"] else "failed",
        "attempts": result["attempts"],
        "started_at": format(float(result["started_at"]), ".6f"),
        "finished_at": format(float(result["finished_at"]), ".6f"),
        "message": result["message"],
        "assignments_json": json.dumps(
            point["assignments"], ensure_ascii=False, separators=(",", ":")
        ),
        "result_files_json": json.dumps(
            result["result_paths"], ensure_ascii=False, separators=(",", ":")
        ),
    }
    save_progress(record, package_dir)


def _session_result_paths(config, point, session_results):
    cached = session_results.get(point["id"])
    if not cached:
        return None
    result_paths = cached["result_paths"]
    started_at = cached["started_at"]
    try:
        result_paths = _confined_result_paths(result_paths)
    except ValueError:
        return None
    if len(result_paths) != len(config.get("results", [])):
        return None
    if all(
        validate_result(
            path,
            started_at,
            result_spec,
            config.get("frequency"),
            _configured_data_frequency_unit(config),
        )[0]
        for path, result_spec in zip(result_paths, config.get("results", []))
    ):
        return result_paths
    return None


def _execute_point(
    config,
    point,
    stage,
    package_dir=None,
    runtime_signature=None,
    session_results=None,
):
    session_results = session_results if session_results is not None else {}
    reusable = _session_result_paths(config, point, session_results)
    if reusable is not None:
        return True, reusable, True
    reusable = _reusable_result_paths(
        config, point, package_dir, runtime_signature
    )
    if reusable is not None:
        session_results[point["id"]] = {
            "result_paths": reusable,
            "started_at": min(
                Path(path).stat().st_mtime for path in reusable
            ),
        }
        return True, reusable, True
    result = run_waveda(config, point, package_dir)
    _record_result(
        config,
        point,
        stage,
        result,
        package_dir,
        runtime_signature,
    )
    if result["success"]:
        session_results[point["id"]] = {
            "result_paths": result["result_paths"],
            "started_at": result["started_at"],
        }
    return result["success"], result["result_paths"], False


def _smoke(
    config,
    package_dir=None,
    runtime_signature=None,
    session_results=None,
):
    point = _select_smoke_point(config)
    success, result_paths, _reused = _execute_point(
        config,
        point,
        "smoke",
        package_dir,
        runtime_signature,
        session_results,
    )
    return success, point, result_paths


def _run_points(
    config,
    points,
    stage,
    package_dir=None,
    runtime_signature=None,
    session_results=None,
):
    results = {}
    failed = []
    for point in points:
        success, result_paths, _reused = _execute_point(
            config,
            point,
            stage,
            package_dir,
            runtime_signature,
            session_results,
        )
        if success:
            results[point["id"]] = result_paths
        else:
            failed.append(point["id"])
    return {"results": results, "failed_points": failed}


def _select_adaptive_best_point(config, result_files):
    adaptive = _adaptive_plan(config)
    if adaptive is None:
        return None
    objective = adaptive["stage2"]["selection_metric"]
    if (
        objective.get("result_type") != "port"
        or objective.get("metric") != "target_frequency_value"
        or objective.get("goal") != "minimize"
    ):
        raise ValueError("Unsupported adaptive selection metric.")

    analysis = analyze_results(config, result_files)
    candidates = []
    for point in _planned_points(config):
        point_metrics = analysis["points"].get(point["id"], {})
        port_metrics = point_metrics.get("ports", {}).get(
            objective["result_name"], {}
        )
        trace_metrics = port_metrics.get("traces", {}).get(
            objective["trace"], {}
        )
        value = trace_metrics.get("nearest_value")
        if value is not None and math.isfinite(float(value)):
            candidates.append((float(value), point))
    if not candidates:
        raise ValueError(
            "Adaptive sweep could not find a valid Port metric in stage 1."
        )
    return min(candidates, key=lambda item: item[0])[1]


def _run(
    config,
    package_dir=None,
    runtime_signature=None,
    session_results=None,
):
    summary = _run_points(
        config,
        _planned_points(config),
        "run",
        package_dir,
        runtime_signature,
        session_results,
    )
    if _adaptive_plan(config) is None:
        return summary

    best_point = _select_adaptive_best_point(config, summary["results"])
    adaptive_points = build_adaptive_stage2_points(config, best_point)
    if not adaptive_points:
        raise ValueError("Adaptive stage 2 produced no new points.")
    adaptive_summary = _run_points(
        config,
        adaptive_points,
        "adaptive",
        package_dir,
        runtime_signature,
        session_results,
    )
    summary["results"].update(adaptive_summary["results"])
    summary["failed_points"].extend(adaptive_summary["failed_points"])
    return summary


def _result_matrix_payload(config, result_paths):
    if len(result_paths) != len(config.get("results", [])):
        return None
    matrices = []
    for path in result_paths:
        try:
            rows = _parse_numeric_rows(Path(path))
        except (OSError, UnicodeError, ValueError):
            return None
        if not rows:
            return None
        matrices.append(rows)
    return matrices


def result_matrices_differ(
    first,
    second,
    *,
    absolute_tolerance=ENDPOINT_ABSOLUTE_TOLERANCE,
    relative_tolerance=ENDPOINT_RELATIVE_TOLERANCE,
):
    if len(first) != len(second):
        return True
    for first_matrix, second_matrix in zip(first, second):
        if len(first_matrix) != len(second_matrix):
            return True
        for first_row, second_row in zip(first_matrix, second_matrix):
            if len(first_row) != len(second_row):
                return True
            if any(
                not math.isclose(
                    first_value,
                    second_value,
                    rel_tol=relative_tolerance,
                    abs_tol=absolute_tolerance,
                )
                for first_value, second_value in zip(first_row, second_row)
            ):
                return True
    return False


def _validate_endpoints(
    config,
    package_dir=None,
    runtime_signature=None,
    session_results=None,
):
    points = {point["id"]: point for point in _planned_points(config)}
    endpoint_ids = config.get("sweep", {}).get("endpoint_ids", [])
    if not endpoint_ids:
        return False, "Sweep plan has no endpoint_ids."
    endpoint_matrices = []
    for point_id in endpoint_ids:
        point = points.get(point_id)
        if point is None:
            return False, f"Endpoint is absent from sweep plan: {point_id}"
        success, result_paths, _reused = _execute_point(
            config,
            point,
            "endpoint",
            package_dir,
            runtime_signature,
            session_results,
        )
        if not success:
            return False, f"Endpoint simulation failed: {point_id}"
        matrices = _result_matrix_payload(config, result_paths)
        if matrices is None:
            return False, f"Endpoint has no valid result matrix: {point_id}"
        endpoint_matrices.append(matrices)
    if len(endpoint_matrices) >= 2 and not result_matrices_differ(
        endpoint_matrices[0],
        endpoint_matrices[-1],
    ):
        return False, "Endpoint result data has no material difference."
    return True, "ok"


def analyze_results(config, result_files):
    target_hz = _target_frequency_hz(config["frequency"])
    data_frequency_unit = _configured_data_frequency_unit(config)
    analysis = {
        "target_frequency_hz": target_hz,
        "nearest_frequency_hz": None,
        "nearest_value": None,
        "resonance_frequency_hz": None,
        "resonance_value": None,
        "points": {},
    }
    for point_id, paths in result_files.items():
        port_metrics = {}
        for result_index, result_spec in enumerate(config.get("results", [])):
            if str(result_spec.get("type", "")).lower() != "port":
                continue
            if result_index >= len(paths):
                continue
            try:
                rows = _parse_numeric_rows(Path(paths[result_index]))
                traces = parse_port_traces(
                    rows,
                    len(result_spec.get("traces", [])),
                    data_frequency_unit,
                )
            except (OSError, UnicodeError, ValueError):
                continue
            if not traces:
                continue
            trace_metrics = {}
            for trace_index, trace in enumerate(traces):
                pairs = list(
                    zip(trace["frequency_hz"], trace["values"])
                )
                nearest = min(
                    pairs, key=lambda pair: abs(pair[0] - target_hz)
                )
                resonance = min(pairs, key=lambda pair: pair[1])
                trace_name = str(result_spec["traces"][trace_index])
                trace_metrics[trace_name] = {
                    "nearest_frequency_hz": nearest[0],
                    "nearest_value": nearest[1],
                    "resonance_frequency_hz": resonance[0],
                    "resonance_value": resonance[1],
                }
            first_trace_name = str(result_spec["traces"][0])
            metrics = dict(trace_metrics[first_trace_name])
            metrics["traces"] = trace_metrics
            port_metrics[str(result_spec.get("name", ""))] = metrics
            if analysis["nearest_frequency_hz"] is None:
                analysis.update(trace_metrics[first_trace_name])
        if port_metrics:
            analysis["points"][point_id] = {"ports": port_metrics}
    return analysis


def build_report(config, run_summary, analysis, package_dir=None):
    paths = prepare_directories(package_dir)
    report = {
        "task_signature": config["task_signature"],
        "failed_points": run_summary.get("failed_points", []),
        "completed_point_count": len(run_summary.get("results", {})),
        "analysis": analysis,
    }
    report_path = paths["output"] / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report_path


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="Portable WavEDA sweep")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check-only", action="store_true")
    modes.add_argument("--smoke-only", action="store_true")
    modes.add_argument("--run-only", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    config = load_config()
    issues = preflight_check(config)
    if issues:
        for issue in issues:
            print(f"[check] {issue}")
        return 2
    config["_resolved_data_frequency_unit"] = (
        resolve_data_frequency_unit(config)
        if _has_port_results(config)
        else None
    )
    prepare_directories()
    runtime_signature = build_runtime_signature(config)
    session_results = {}
    if args.check_only:
        print("[check] passed")
        return 0
    if args.smoke_only:
        try:
            success, _point, _paths = _smoke(
                config,
                runtime_signature=runtime_signature,
                session_results=session_results,
            )
        except ValueError as exc:
            print(f"[smoke] {exc}")
            return 3
        return 0 if success else 3
    if not args.run_only:
        try:
            success, _point, _paths = _smoke(
                config,
                runtime_signature=runtime_signature,
                session_results=session_results,
            )
        except ValueError as exc:
            print(f"[smoke] {exc}")
            return 3
        if not success:
            return 3
    endpoint_ok, endpoint_message = _validate_endpoints(
        config,
        runtime_signature=runtime_signature,
        session_results=session_results,
    )
    if not endpoint_ok:
        print(f"[endpoint] {endpoint_message}")
        return 5
    try:
        run_summary = _run(
            config,
            runtime_signature=runtime_signature,
            session_results=session_results,
        )
    except ValueError as exc:
        print(f"[run] {exc}")
        return 6
    analysis = analyze_results(config, run_summary["results"])
    build_report(config, run_summary, analysis)
    return 0 if not run_summary["failed_points"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
