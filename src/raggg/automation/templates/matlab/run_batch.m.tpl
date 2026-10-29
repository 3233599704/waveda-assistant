function exit_code = run_batch(mode)
%RUN_BATCH Portable WavEDA sweep controller.
% run_batch() performs check -> smoke -> endpoint -> run.
% run_batch("check"), run_batch("smoke"), and run_batch("run") are
% diagnostic entry points.

if nargin < 1
    mode = "auto";
end
mode = lower(string(mode));
package_dir = fileparts(mfilename('fullpath'));
config = load_config(package_dir);
paths = prepare_directories(package_dir);
issues = preflight_check(config, paths);
if ~isempty(issues)
    for issue_index = 1:numel(issues)
        fprintf(2, '[check] %s\n', issues(issue_index));
    end
    exit_code = 2;
    return;
end

if has_port_results(config)
    config.data_frequency_unit_resolved = ...
        resolve_data_frequency_unit(config);
else
    config.data_frequency_unit_resolved = "";
end
runtime_signature = build_runtime_signature(config);
session_results = containers.Map('KeyType', 'char', 'ValueType', 'any');
points = plan_points(config);
fprintf('=== WavEDA sweep: %d point(s) ===\n', numel(points));
switch mode
    case "auto"
        fprintf('[smoke] validating with non-baseline point ...\n');
        smoke_ok = run_smoke( ...
            config, paths, runtime_signature, session_results, points);
        if ~smoke_ok
            fprintf(2, '[smoke] FAILED — aborting\n');
            exit_code = 3;
            return;
        end
        fprintf('[smoke] passed\n');
        fprintf('[endpoint] checking sweep boundaries ...\n');
        [endpoint_ok, endpoint_message] = validate_endpoints( ...
            config, paths, runtime_signature, session_results, points);
        if ~endpoint_ok
            fprintf(2, '[endpoint] %s\n', endpoint_message);
            exit_code = 5;
            return;
        end
        fprintf('[endpoint] passed\n');
        fprintf('[run] starting batch sweep ...\n');
        summary = run_sweep( ...
            config, paths, runtime_signature, session_results, points);
        if isempty(summary.failed_points)
            fprintf('[run] %d/%d points completed successfully\n', ...
                numel(points), numel(points));
        else
            fprintf('[run] %d/%d points completed, %d failed\n', ...
                numel(points) - numel(summary.failed_points), ...
                numel(points), numel(summary.failed_points));
        end
    case "check"
        fprintf('[check] passed\n');
        exit_code = 0;
        return;
    case "smoke"
        smoke_ok = run_smoke( ...
            config, paths, runtime_signature, session_results);
        exit_code = double(~smoke_ok) * 3;
        return;
    case "run"
        [endpoint_ok, endpoint_message] = validate_endpoints( ...
            config, paths, runtime_signature, session_results);
        if ~endpoint_ok
            fprintf(2, '[endpoint] %s\n', endpoint_message);
            exit_code = 5;
            return;
        end
        summary = run_sweep( ...
            config, paths, runtime_signature, session_results);
    otherwise
        fprintf(2, 'Unknown mode: %s\n', mode);
        exit_code = 2;
        return;
end

analysis = analyze_results(config, summary.result_files);
build_report(config, summary, analysis, paths);
exit_code = double(~isempty(summary.failed_points)) * 4;
end


function config = load_config(package_dir)
config_path = fullfile(package_dir, 'task_config.json');
config = jsondecode(fileread(config_path));
end


function signature = build_runtime_signature(config)
if ~isfile(config.target.project_file)
    error('External .tsp project does not exist.');
end
project_sha256 = sha256_file(config.target.project_file);
signature = sprintf('%s|%s', ...
    string(config.task_signature), project_sha256);
end


function issues = preflight_check(config, paths)
issues = strings(0, 1);
if ~verify_task_signature(config)
    issues(end + 1) = "Task signature does not match task_config.json.";
end
issues = [issues; validate_plan_integrity(config)];
issues = [issues; validate_template_integrity(config, paths)];
if ~isfile(config.target.waveda_exe)
    issues(end + 1) = "WavEDA executable does not exist: " + ...
        string(config.target.waveda_exe);
end
if ~isfile(config.target.project_file)
    issues(end + 1) = "External .tsp project does not exist: " + ...
        string(config.target.project_file);
else
    try
        project_document = parse_tsp_xml(config.target.project_file);
        if has_port_results(config)
            try
                resolve_data_frequency_unit(config, project_document);
            catch unit_error
                issues(end + 1) = string(unit_error.message);
            end
        end
        project_root = project_document.getDocumentElement();
        variable_containers = ...
            project_document.getElementsByTagName('variables');
        port_results = collect_result_names(project_document, 'port-results');
        obv_results = collect_result_names(project_document, 'obv-results');
        if ~strcmpi(string(char(project_root.getTagName())), "project") || ...
                variable_containers.getLength() == 0 || ...
                (isempty(port_results) && isempty(obv_results))
            issues(end + 1) = ...
                "Unrecognized WavEDA .tsp XML structure.";
        else
            variable_nodes = project_document.getElementsByTagName('var');
            for configured_index = 1:numel(config.sweep.variables)
                configured_name = ...
                    string(config.sweep.variables(configured_index).name);
                found_variable = false;
                expression_variable = false;
                for variable_index = 0:variable_nodes.getLength() - 1
                    variable_node = variable_nodes.item(variable_index);
                    node_name = ...
                        string(char(variable_node.getAttribute('name')));
                    if strcmpi(node_name, configured_name)
                        found_variable = true;
                        expression_text = string(char( ...
                            variable_node.getAttribute('expression')));
                        expression_value = str2double(expression_text);
                        expression_variable = isnan(expression_value) || ...
                            ~isfinite(expression_value);
                    end
                end
                if ~found_variable
                    issues(end + 1) = ...
                        "Sweep variable is missing from .tsp: " + configured_name;
                elseif expression_variable
                    issues(end + 1) = ...
                        "Sweep variable is an expression: " + configured_name;
                end
            end
            for result_index = 1:numel(config.results)
                result_name = string(config.results(result_index).name);
                result_type = lower(string(config.results(result_index).type));
                if result_type == "port"
                    typed_names = port_results;
                    other_names = obv_results;
                else
                    typed_names = obv_results;
                    other_names = port_results;
                end
                if ~any(strcmpi(typed_names, result_name))
                    if any(strcmpi(other_names, result_name))
                        issues(end + 1) = ...
                            "Result node type does not match .tsp: " + result_name;
                    else
                        issues(end + 1) = ...
                            "Result node is missing from .tsp: " + result_name;
                    end
                end
            end
        end
    catch tsp_error
        issues(end + 1) = ...
            "Unable to parse WavEDA .tsp XML: " + string(tsp_error.message);
    end
end
if ~isfile(fullfile(paths.package_dir, 'template.xml'))
    issues(end + 1) = "template.xml is missing.";
end
variable_count = numel(config.sweep.variables);
if variable_count < 1 || variable_count > 2
    issues(end + 1) = "Only one or two sweep variables are supported.";
end
if strcmpi(string(config.sweep.strategy), "builtin_sweep")
    issues(end + 1) = "Built-in WavEDA sweep is not supported.";
end
try
    probe_path = fullfile(paths.output, '.write_probe');
    probe_id = fopen(probe_path, 'w');
    if probe_id < 0
        error('Cannot create output probe.');
    end
    fclose(probe_id);
    delete(probe_path);
catch probe_error
    issues(end + 1) = "Package output directory is not writable: " + ...
        string(probe_error.message);
end
end


function valid = verify_task_signature(config)
valid = false;
if ~isfield(config, 'task_signature') || ...
        ~isfield(config, 'task_signature_payload')
    return;
end
payload_text = char(config.task_signature_payload);
if ~strcmpi(sha256_text(payload_text), string(config.task_signature))
    return;
end
try
    jsondecode(config.task_signature_payload);
catch
    return;
end
valid = true;
end


function payload = normalized_task_payload(config)
payload = config;
top_level_runtime_fields = {
    'package_dir', 'task_signature', 'task_signature_payload', ...
    'data_frequency_unit_resolved'
};
for field_index = 1:numel(top_level_runtime_fields)
    field_name = top_level_runtime_fields{field_index};
    if isfield(payload, field_name)
        payload = rmfield(payload, field_name);
    end
end
end


function issues = validate_plan_integrity(config)
issues = strings(0, 1);
try
    rebuilt_points = rebuild_plan_points(config);
catch plan_error
    issues(end + 1) = "Invalid deterministic sweep plan: " + ...
        string(plan_error.message);
    return;
end
if isempty(rebuilt_points)
    expected_endpoint_ids = strings(0, 1);
elseif numel(rebuilt_points) == 1
    expected_endpoint_ids = string(rebuilt_points(1).id);
else
    expected_endpoint_ids = [
        string(rebuilt_points(1).id); string(rebuilt_points(end).id)
    ];
end
if ~isfield(config.sweep, 'endpoint_ids')
    actual_endpoint_ids = strings(0, 1);
else
    actual_endpoint_ids = string(config.sweep.endpoint_ids(:));
end
if ~isequal(actual_endpoint_ids, expected_endpoint_ids)
    issues(end + 1) = ...
        "Packaged endpoint_ids do not match the deterministic sweep plan.";
end
if ~isfield(config.sweep, 'estimated_point_count') || ...
        double(config.sweep.estimated_point_count) ~= numel(rebuilt_points)
    issues(end + 1) = ...
        "Packaged estimated_point_count does not match the deterministic sweep plan.";
end
end


function normalized = normalize_for_comparison(value)
if isstruct(value)
    normalized = orderfields(value);
    field_names = fieldnames(normalized);
    for element_index = 1:numel(normalized)
        for field_index = 1:numel(field_names)
            field_name = field_names{field_index};
            normalized(element_index).(field_name) = ...
                normalize_for_comparison( ...
                    normalized(element_index).(field_name));
        end
    end
elseif iscell(value)
    normalized = value;
    for element_index = 1:numel(normalized)
        normalized{element_index} = ...
            normalize_for_comparison(normalized{element_index});
    end
else
    normalized = value;
end
end


function document = parse_tsp_xml(tsp_path)
raw_text = fileread(tsp_path);
% WavEDA .tsp files may contain trailing content after the root element.
% Find the last XML closing tag and discard everything after it.
[close_starts, close_ends] = regexp(raw_text, '</[A-Za-z][\w.-]*\s*>');
if ~isempty(close_starts)
    raw_text = raw_text(1:close_ends(end));
end
raw_bytes = unicode2native(char(raw_text), 'UTF-8');
input_source = javaObject('org.xml.sax.InputSource', ...
    javaObject('java.io.ByteArrayInputStream', raw_bytes));
document = javax.xml.parsers.DocumentBuilderFactory.newInstance() ...
    .newDocumentBuilder().parse(input_source);
end


function digest_hex = sha256_text(text)
digest = java.security.MessageDigest.getInstance('SHA-256');
digest.update(unicode2native(char(text), 'UTF-8'));
digest_bytes = typecast(digest.digest(), 'uint8');
digest_hex = lower(string(reshape(dec2hex(digest_bytes, 2).', 1, [])));
end


function digest_hex = sha256_file(file_path)
file_id = fopen(file_path, 'rb');
if file_id < 0
    error('Cannot read file for SHA-256: %s', string(file_path));
end
cleanup = onCleanup(@() fclose(file_id));
file_bytes = fread(file_id, Inf, '*uint8');
digest = java.security.MessageDigest.getInstance('SHA-256');
digest.update(file_bytes);
digest_bytes = typecast(digest.digest(), 'uint8');
digest_hex = lower(string(reshape(dec2hex(digest_bytes, 2).', 1, [])));
clear cleanup;
end


function issues = validate_template_integrity(config, paths)
issues = strings(0, 1);
template_path = fullfile(paths.package_dir, 'template.xml');
if ~isfile(template_path)
    issues(end + 1) = "template.xml is missing.";
    return;
end
if ~isfield(config, 'integrity') || ...
        ~isfield(config.integrity, 'template_xml_sha256') || ...
        ~strcmpi( ...
            sha256_file(template_path), ...
            string(config.integrity.template_xml_sha256))
    issues(end + 1) = ...
        "template.xml SHA-256 does not match task_config.json.";
end
try
    document = xmlread(template_path);
catch template_error
    issues(end + 1) = ...
        "template.xml cannot be parsed: " + string(template_error.message);
    return;
end
commands = document.getElementsByTagName('command');

load_count = 0;
project_load_count = count_commands(commands, "load", "project");
for command_index = 0:commands.getLength() - 1
    command = commands.item(command_index);
    if strcmp(char(command.getAttribute('cmdType')), 'load') && ...
            strcmp(char(command.getAttribute('obj1')), 'project') && ...
            strcmp(char(command.getAttribute('file')), ...
                char(config.target.project_file))
        load_count = load_count + 1;
    end
end
if load_count ~= 1 || project_load_count ~= 1
    issues(end + 1) = ...
        "template.xml structure: project path does not match config.";
end

variable_match_count = 0;
for variable_index = 1:numel(config.sweep.variables)
    variable = config.sweep.variables(variable_index);
    expected_name = string(variable.name);
    expected_value = number_text(variable_initial_value(variable));
    match_count = 0;
    for command_index = 0:commands.getLength() - 1
        command = commands.item(command_index);
        if strcmp(char(command.getAttribute('cmdType')), 'modify') && ...
                strcmp(char(command.getAttribute('obj1')), 'var') && ...
                strcmpi(string(char(command.getAttribute('name'))), ...
                    expected_name) && ...
                strcmp(char(command.getAttribute('value')), expected_value)
            match_count = match_count + 1;
        end
    end
    variable_match_count = variable_match_count + match_count;
end
modify_count = count_commands(commands, "modify", "var");
if variable_match_count ~= numel(config.sweep.variables) || ...
        modify_count ~= numel(config.sweep.variables)
    issues(end + 1) = ...
        "template.xml structure: variable command does not match config.";
end

result_match_count = 0;
for result_index = 1:numel(config.results)
    result_type = lower(string(config.results(result_index).type));
    if result_type == "observer"
        result_type = "obv";
    end
    expected_file = sprintf( ...
        'output/raw/result_%02d_%s.txt', result_index, result_type);
    match_count = 0;
    for command_index = 0:commands.getLength() - 1
        command = commands.item(command_index);
        if strcmp(char(command.getAttribute('cmdType')), 'export') && ...
                strcmp(char(command.getAttribute('obj1')), 'result') && ...
                strcmpi(string(char(command.getAttribute('name'))), ...
                    string(config.results(result_index).name)) && ...
                strcmpi(string(char(command.getAttribute('obj2'))), ...
                    result_type) && ...
                strcmp(char(command.getAttribute('file')), expected_file)
            match_count = match_count + 1;
        end
    end
    result_match_count = result_match_count + match_count;
end
export_count = count_commands(commands, "export", "result");
if result_match_count ~= numel(config.results) || ...
        export_count ~= numel(config.results)
    issues(end + 1) = ...
        "template.xml structure: result export does not match config.";
end

delete_count = count_commands(commands, "delete", "mesh");
expected_delete_count = double(logical(config.runtime.force_remesh));
if delete_count ~= expected_delete_count
    issues(end + 1) = ...
        "template.xml structure: remesh command does not match config.";
end
if count_commands(commands, "sim", "") ~= 1
    issues(end + 1) = ...
        "template.xml structure: simulation command does not match config.";
end
end


function count = count_commands(commands, command_type, object_type)
count = 0;
for command_index = 0:commands.getLength() - 1
    command = commands.item(command_index);
    if ~strcmp(char(command.getAttribute('cmdType')), char(command_type))
        continue;
    end
    if strlength(string(object_type)) > 0 && ...
            ~strcmp(char(command.getAttribute('obj1')), char(object_type))
        continue;
    end
    count = count + 1;
end
end


function value = variable_initial_value(variable)
if isfield(variable, 'values') && ~isempty(variable.values)
    value = variable.values(1);
elseif isfield(variable, 'start')
    value = variable.start;
else
    value = 0;
end
end


function names = collect_result_names(project_document, container_name)
names = strings(0, 1);
containers = project_document.getElementsByTagName(container_name);
for container_index = 0:containers.getLength() - 1
    children = containers.item(container_index).getChildNodes();
    for child_index = 0:children.getLength() - 1
        child = children.item(child_index);
        if child.getNodeType() == child.ELEMENT_NODE && ...
                child.hasAttribute('name')
            names(end + 1) = string(char(child.getAttribute('name')));
        end
    end
end
end


function unit = resolve_data_frequency_unit(config, project_document)
if isfield(config, 'data_frequency_unit')
    unit = lower(strtrim(string(config.data_frequency_unit)));
else
    if nargin < 2
        project_document = parse_tsp_xml(config.target.project_file);
    end
    unit_nodes = project_document.getElementsByTagName('project-unit');
    if unit_nodes.getLength() == 0
        error(['Data frequency unit is missing; set data_frequency_unit ' ...
            'or add project-unit freq to the .tsp.']);
    end
    unit = lower(strtrim(string(char( ...
        unit_nodes.item(0).getAttribute('freq')))));
end
if strlength(unit) == 0
    error(['Data frequency unit is missing; set data_frequency_unit ' ...
        'or add project-unit freq to the .tsp.']);
end
frequency_multiplier(unit);
end


function present = has_port_results(config)
present = false;
for result_index = 1:numel(config.results)
    if lower(string(config.results(result_index).type)) == "port"
        present = true;
        return;
    end
end
end


function multiplier = frequency_multiplier(unit)
switch lower(char(unit))
    case 'hz'
        multiplier = 1;
    case 'khz'
        multiplier = 1e3;
    case 'mhz'
        multiplier = 1e6;
    case 'ghz'
        multiplier = 1e9;
    otherwise
        error('Unsupported data frequency unit: %s', string(unit));
end
end


function paths = prepare_directories(package_dir)
paths.package_dir = package_dir;
paths.generated_xml = fullfile(package_dir, 'generated_xml');
paths.output = fullfile(package_dir, 'output');
paths.raw = fullfile(paths.output, 'raw');
paths.logs = fullfile(paths.output, 'logs');
paths.figures = fullfile(paths.output, 'figures');
paths.progress = fullfile(paths.output, 'progress.csv');
directory_list = {
    paths.generated_xml, paths.output, paths.raw, paths.logs, paths.figures
};
for directory_index = 1:numel(directory_list)
    if ~isfolder(directory_list{directory_index})
        mkdir(directory_list{directory_index});
    end
end
end


function points = plan_points(config)
points = packaged_plan_points(config);
for point_index = 1:numel(points)
    points(point_index).id = validate_point_id(points(point_index).id);
end
end


function points = packaged_plan_points(config)
if ~isfield(config.sweep, 'planned_points') || ...
        isempty(config.sweep.planned_points)
    points = rebuild_plan_points(config);
    return;
end
supplied = config.sweep.planned_points;
if isstruct(supplied) && isscalar(supplied) && isfield(supplied, 'mode')
    if string(supplied.mode) ~= "adaptive_coarse_to_fine"
        error("Unsupported planned point mode: %s", string(supplied.mode));
    end
    points = supplied.stage1_points;
else
    points = supplied;
end
end


function points = rebuild_plan_points(config)
variables = config.sweep.variables;
estimate_sweep_point_count(config);
value_sets = cell(1, numel(variables));
for variable_index = 1:numel(variables)
    variable = variables(variable_index);
    if isfield(variable, 'values')
        value_sets{variable_index} = double(variable.values(:)');
    else
        value_sets{variable_index} = ...
            double(variable.start):double(variable.step):double(variable.stop);
    end
end
points = struct('id', {}, 'assignments', {});
point_index = 0;
if numel(variables) == 1
    for first_index = 1:numel(value_sets{1})
        point_index = point_index + 1;
        assignments = struct( ...
            'name', string(variables(1).name), ...
            'value', value_sets{1}(first_index));
        points(point_index) = make_point(point_index, assignments);
    end
else
    for first_index = 1:numel(value_sets{1})
        for second_index = 1:numel(value_sets{2})
            point_index = point_index + 1;
            assignments(1) = struct( ...
                'name', string(variables(1).name), ...
                'value', value_sets{1}(first_index));
            assignments(2) = struct( ...
                'name', string(variables(2).name), ...
                'value', value_sets{2}(second_index));
            points(point_index) = make_point(point_index, assignments);
        end
    end
end
end


function point_count = estimate_sweep_point_count(config)
max_sweep_points = 10000;
point_count = 1;
variables = config.sweep.variables;
for variable_index = 1:numel(variables)
    variable = variables(variable_index);
    if isfield(variable, 'values')
        value_count = numel(variable.values);
    else
        start_value = double(variable.start);
        stop_value = double(variable.stop);
        step_value = double(variable.step);
        if step_value == 0 || ...
                (stop_value - start_value) * step_value < 0
            error('Sweep range step is invalid.');
        end
        value_count = floor( ...
            (stop_value - start_value) / step_value + 1e-12) + 1;
    end
    point_count = point_count * value_count;
    if point_count > max_sweep_points
        error('Sweep would create %d points; the hard limit is 10,000.', ...
            point_count);
    end
end
end


function point_id = validate_point_id(raw_point_id)
point_id = char(string(raw_point_id));
if isempty(point_id) || contains(point_id, '..') || ...
        isempty(regexp(point_id, '^[A-Za-z0-9_.-]+$', 'once'))
    error(['Unsafe point ID; only ASCII letters, digits, _, ., and - ' ...
        'are allowed.']);
end
end


function path = confined_path(root_path, relative_path)
candidate = fullfile(char(root_path), char(relative_path));
path = assert_confined_path(root_path, candidate);
end


function path = assert_confined_path(root_path, candidate_path)
root_canonical = char(java.io.File(char(root_path)).getCanonicalPath());
candidate_canonical = ...
    char(java.io.File(char(candidate_path)).getCanonicalPath());
separator = char(java.io.File.separator);
root_prefix = [root_canonical separator];
if ~strcmpi(candidate_canonical, root_canonical) && ...
        ~startsWith(lower(candidate_canonical), lower(root_prefix))
    error('Point-derived path escapes its package directory: %s', ...
        candidate_canonical);
end
path = candidate_canonical;
end


function point = make_point(point_index, assignments)
parts = strings(1, numel(assignments));
for assignment_index = 1:numel(assignments)
    parts(assignment_index) = safe_name(assignments(assignment_index).name) + ...
        "_" + filename_token(assignments(assignment_index).value);
end
point.id = sprintf('p%04d_%s', point_index, strjoin(parts, '_'));
point.assignments = assignments;
end


function name = safe_name(raw_name)
name = regexprep(string(raw_name), '[^A-Za-z0-9_]+', '_');
name = strip(name, '_');
if strlength(name) == 0
    name = "var";
end
end


function token = filename_token(value)
token = string(number_text(value));
if startsWith(token, "-")
    token = "m" + extractAfter(token, 1);
end
token = replace(token, ".", "p");
token = replace(token, "+", "");
end


function text = number_text(value)
if double(value) == fix(double(value))
    text = sprintf('%.0f', double(value));
else
    text = sprintf('%.15g', double(value));
end
end


function [xml_path, result_paths] = generate_point_xml(config, point, paths)
point.id = validate_point_id(point.id);
template_path = fullfile(paths.package_dir, 'template.xml');
document = xmlread(template_path);
commands = document.getElementsByTagName('command');
matched = false(1, numel(point.assignments));
point_raw = confined_path(paths.raw, point.id);
if ~isfolder(point_raw)
    mkdir(point_raw);
end
result_paths = {};
result_index = 0;
for command_index = 0:commands.getLength() - 1
    command = commands.item(command_index);
    command_type = string(char(command.getAttribute('cmdType')));
    object_type = string(char(command.getAttribute('obj1')));
    if strcmpi(command_type, "modify") && strcmpi(object_type, "var")
        command_name = string(char(command.getAttribute('name')));
        for assignment_index = 1:numel(point.assignments)
            if strcmpi(command_name, string(point.assignments(assignment_index).name))
                command.setAttribute( ...
                    'value', number_text(point.assignments(assignment_index).value));
                matched(assignment_index) = true;
            end
        end
    elseif strcmpi(command_type, "export") && strcmpi(object_type, "result")
        result_index = result_index + 1;
        result_type = string(char(command.getAttribute('obj2')));
        result_paths{result_index} = confined_path( ...
            point_raw, sprintf('result_%02d_%s.txt', result_index, result_type));
        command.setAttribute('file', result_paths{result_index});
    end
end
if ~all(matched)
    error('One or more configured variables are absent from template.xml.');
end
xml_path = confined_path(paths.generated_xml, char(point.id) + ".xml");
xmlwrite(xml_path, document);
end


function result = run_waveda(config, point, paths)
[xml_path, result_paths] = generate_point_xml(config, point, paths);
max_attempts = double(config.runtime.max_attempts);
timeout_seconds = double(config.runtime.timeout_seconds);
result.success = false;
result.attempts = max_attempts;
result.started_at = now;
result.finished_at = now;
result.message = "Simulation failed.";
result.result_paths = result_paths;
for attempt = 1:max_attempts
    if attempt > 1
        fprintf(' retry %d/%d', attempt, max_attempts);
    end
    for result_index = 1:numel(result_paths)
        result_paths{result_index} = assert_confined_path( ...
            paths.raw, result_paths{result_index});
        if isfile(result_paths{result_index})
            delete(result_paths{result_index});
        end
    end
    started_datenum = now;
    if attempt == 1
        result.started_at = started_datenum;
    end
    [return_code, stdout_text, stderr_text] = run_process_with_timeout( ...
        config.target.waveda_exe, xml_path, timeout_seconds);
    log_path = confined_path(paths.logs, ...
        sprintf('%s_attempt_%d.log', validate_point_id(point.id), attempt));
    log_id = fopen(log_path, 'w');
    fprintf(log_id, 'return_code=%d\nstdout:\n%s\nstderr:\n%s\n', ...
        return_code, stdout_text, stderr_text);
    fclose(log_id);
    valid = true;
    messages = strings(0, 1);
    for result_index = 1:numel(result_paths)
        [file_valid, message] = validate_result( ...
            result_paths{result_index}, started_datenum, ...
            config.results(result_index), config.frequency, ...
            config.data_frequency_unit_resolved);
        valid = valid && file_valid;
        if ~file_valid
            messages(end + 1) = message;
        end
    end
    if valid && ~isempty(result_paths)
        result.success = true;
        result.attempts = attempt;
        result.finished_at = now;
        result.message = "ok";
        return;
    end
    result.message = strjoin(messages, "; ");
end
result.finished_at = now;
end


function [return_code, stdout_text, stderr_text] = ...
        run_process_with_timeout(executable_path, xml_path, timeout_seconds)
[waveda_dir, waveda_name] = fileparts(char(executable_path));
bat_path = fullfile(tempdir, sprintf('waveda_run_%s.bat', ...
    char(java.util.UUID.randomUUID().toString())));
log_path = fullfile(tempdir, sprintf('waveda_log_%s.txt', ...
    char(java.util.UUID.randomUUID().toString())));
bat_id = fopen(bat_path, 'w');
fprintf(bat_id, '@echo off\r\n');
fprintf(bat_id, 'cd /d "%s"\r\n', waveda_dir);
fprintf(bat_id, '"%s" "script=%s" > "%s" 2>&1\r\n', ...
    executable_path, xml_path, log_path);
fprintf(bat_id, 'echo %%errorlevel%% > "%s.exit"\r\n', log_path);
fclose(bat_id);

log_exit_path = [log_path '.exit'];
if isfile(log_exit_path)
    delete(log_exit_path);
end
if isfile(log_path)
    delete(log_path);
end

started = tic;
[status, ~] = system(['"' bat_path '"']);
elapsed = toc(started);

return_code = -1;
stdout_text = '';
stderr_text = '';
if isfile(log_path)
    stdout_text = fileread(log_path);
end
if isfile(log_exit_path)
    try
        return_code = str2double(strtrim(fileread(log_exit_path)));
    catch
    end
end
if elapsed > timeout_seconds
    return_code = -1;
    stdout_text = sprintf('TIMEOUT after %.0f seconds', elapsed);
end
try delete(bat_path); catch; end
try delete(log_path); catch; end
try delete(log_exit_path); catch; end
end



function [valid, message, data] = validate_result( ...
        result_path, started_datenum, result_spec, frequency_config, ...
        data_frequency_unit)
valid = false;
message = "Result file was not created.";
data = [];
if ~isfile(result_path)
    return;
end
metadata = dir(result_path);
if metadata.datenum < started_datenum - 1 / 86400
    message = "Result file is older than this simulation.";
    return;
end
try
    data = readmatrix(result_path, 'FileType', 'text');
catch read_error
    message = "Cannot parse result file: " + string(read_error.message);
    return;
end
data = data(~all(isnan(data), 2), :);
if isempty(data) || ~all(isfinite(data(:)))
    data = [];
    message = "Result data must be non-empty, numeric, and finite.";
    return;
end
result_type = lower(string(result_spec.type));
if result_type == "port"
    if ischar(result_spec.traces) || isstring(result_spec.traces)
        trace_count = 1;
    else
        trace_count = numel(result_spec.traces);
    end
    if trace_count < 1 || size(data, 1) < 2
        data = [];
        message = "Port rows or columns do not satisfy traces.";
        return;
    end
    try
        traces = parse_port_traces( ...
            data, trace_count, data_frequency_unit);
    catch layout_error
        data = [];
        message = string(layout_error.message);
        return;
    end
    unit = lower(string(frequency_config.unit));
    multipliers = struct('hz', 1, 'khz', 1e3, 'mhz', 1e6, 'ghz', 1e9);
    target_hz = double(frequency_config.target) * multipliers.(char(unit));
    for trace_index = 1:numel(traces)
        trace = traces(trace_index);
        if numel(trace.frequency_hz) < 2 || ...
                ~all(diff(trace.frequency_hz) > 0)
            data = [];
            message = "Port frequencies must be strictly increasing.";
            return;
        end
        if all(trace.values == 0)
            data = [];
            message = "Port trace data is entirely zero.";
            return;
        end
        if target_hz < trace.frequency_hz(1) || ...
                target_hz > trace.frequency_hz(end)
            data = [];
            message = "Target frequency is outside port sweep range.";
            return;
        end
    end
elseif result_type == "obv"
    % Observer exports may use time, arc length, or another primary axis.
else
    data = [];
    message = "Unsupported result type: " + result_type;
    return;
end
valid = true;
message = "ok";
end


function traces = parse_port_traces(data, trace_count, data_frequency_unit)
multiplier = frequency_multiplier(data_frequency_unit);
column_count = size(data, 2);
traces = repmat( ...
    struct('frequency_hz', [], 'values', [], 'layout', ""), ...
    trace_count, 1);
if column_count == trace_count + 1
    layout = "shared";
    for trace_index = 1:trace_count
        traces(trace_index).frequency_hz = data(:, 1) * multiplier;
        traces(trace_index).values = data(:, trace_index + 1);
        traces(trace_index).layout = layout;
    end
elseif trace_count > 1 && column_count == trace_count * 2
    layout = "paired";
    for trace_index = 1:trace_count
        frequency_column = trace_index * 2 - 1;
        traces(trace_index).frequency_hz = ...
            data(:, frequency_column) * multiplier;
        traces(trace_index).values = data(:, frequency_column + 1);
        traces(trace_index).layout = layout;
    end
elseif trace_count > 1 && column_count == 2
    layout = "stacked";
    reset_rows = find(diff(data(:, 1)) <= 0);
    block_starts = [1; reset_rows + 1];
    block_ends = [reset_rows; size(data, 1)];
    if numel(block_starts) ~= trace_count
        error('Stacked port block count does not match traces.');
    end
    for trace_index = 1:trace_count
        block = block_starts(trace_index):block_ends(trace_index);
        traces(trace_index).frequency_hz = ...
            data(block, 1) * multiplier;
        traces(trace_index).values = data(block, 2);
        traces(trace_index).layout = layout;
    end
else
    error('Port layout is not shared, paired, or stacked.');
end
end


function progress_path = save_progress( ...
        config, point, stage, result, paths, runtime_signature)
progress_path = fullfile(paths.output, 'progress.csv');
task_signature = string(config.task_signature);
runtime_signature = string(runtime_signature);
point_id = string(point.id);
stage = string(stage);
if result.success
    status = "completed";
else
    status = "failed";
end
attempts = double(result.attempts);
started_at = double(result.started_at);
finished_at = double(result.finished_at);
message = string(result.message);
assignments_json = string(jsonencode(point.assignments));
result_files_json = string(jsonencode(result.result_paths));
row = table(task_signature, runtime_signature, point_id, stage, status, attempts, ...
    started_at, finished_at, message, assignments_json, result_files_json);
if isfile(progress_path)
    writetable(row, progress_path, 'WriteMode', 'append', ...
        'WriteVariableNames', false);
else
    writetable(row, progress_path);
end
end


function [reusable, result_paths] = reusable_result( ...
        config, point, paths, runtime_signature, session_results)
reusable = false;
result_paths = {};
session_key = char(point.id);
if isKey(session_results, session_key)
    cached = session_results(session_key);
    result_paths = cached.result_paths;
    all_valid = numel(result_paths) == numel(config.results);
    for result_index = 1:numel(result_paths)
        try
            result_paths{result_index} = assert_confined_path( ...
                paths.raw, result_paths{result_index});
        catch
            all_valid = false;
            break;
        end
        all_valid = all_valid && validate_result( ...
            result_paths{result_index}, cached.started_at, ...
            config.results(result_index), config.frequency, ...
            config.data_frequency_unit_resolved);
    end
    if all_valid
        reusable = true;
        return;
    end
end
if ~logical(config.runtime.resume) || ~isfile(paths.progress)
    return;
end
try
    progress = readtable(paths.progress, 'TextType', 'string');
catch
    return;
end
if ~ismember( ...
        "runtime_signature", string(progress.Properties.VariableNames))
    return;
end
matching = strcmp(progress.task_signature, string(config.task_signature)) & ...
    strcmp(progress.runtime_signature, string(runtime_signature)) & ...
    strcmp(progress.point_id, string(point.id)) & ...
    strcmp(progress.status, "completed");
indices = find(matching);
for reverse_index = numel(indices):-1:1
    row_index = indices(reverse_index);
    try
        result_paths = cellstr(jsondecode(progress.result_files_json(row_index)));
    catch
        result_paths = {};
        continue;
    end
    all_valid = numel(result_paths) == numel(config.results);
    for result_index = 1:numel(result_paths)
        try
            result_paths{result_index} = assert_confined_path( ...
                paths.raw, result_paths{result_index});
        catch
            all_valid = false;
            break;
        end
        all_valid = all_valid && validate_result( ...
            result_paths{result_index}, progress.started_at(row_index), ...
            config.results(result_index), config.frequency, ...
            config.data_frequency_unit_resolved);
    end
    if all_valid
        reusable = true;
        return;
    end
end
end


function smoke_ok = run_smoke( ...
        config, paths, runtime_signature, session_results, points)
smoke_ok = false;
try
if numel(points) < 2
    fprintf(2, '[smoke] A non-baseline point is required.\n');
    smoke_ok = false;
    return;
end
point = select_smoke_point(points);
if isempty(point)
    fprintf(2, '[smoke] No point differs from the baseline assignments.\n');
    smoke_ok = false;
    return;
end
[reusable, ~] = reusable_result( ...
    config, point, paths, runtime_signature, session_results);
if reusable
    smoke_ok = true;
    return;
end
result = run_waveda(config, point, paths);
save_progress(config, point, "smoke", result, paths, runtime_signature);
if result.success
    cached.result_paths = result.result_paths;
    cached.started_at = result.started_at;
    session_results(char(point.id)) = cached;
end
smoke_ok = result.success;
catch smoke_error
    fprintf(2, '[smoke] %s\n', string(smoke_error.message));
    smoke_ok = false;
end
end


function point = select_smoke_point(points)
point = struct([]);
baseline_assignments = jsonencode(points(1).assignments);
for candidate_index = 2:numel(points)
    candidate_assignments = ...
        jsonencode(points(candidate_index).assignments);
    if ~strcmp(candidate_assignments, baseline_assignments)
        point = points(candidate_index);
        return;
    end
end
end


function [endpoint_ok, message] = validate_endpoints( ...
        config, paths, runtime_signature, session_results, points)
endpoint_ok = false;
message = "";
endpoint_ids = string(config.sweep.endpoint_ids);
if isempty(endpoint_ids)
    message = "Sweep plan has no endpoint_ids.";
    return;
end
endpoint_matrices = cell(1, numel(endpoint_ids));
for endpoint_index = 1:numel(endpoint_ids)
    point_match = find( ...
        strcmpi(string({points.id}), endpoint_ids(endpoint_index)), 1);
    if isempty(point_match)
        message = "Endpoint is absent from sweep plan: " + ...
            endpoint_ids(endpoint_index);
        return;
    end
    point = points(point_match);
    try
        [reusable, result_paths] = reusable_result( ...
            config, point, paths, runtime_signature, session_results);
        if ~reusable
            result = run_waveda(config, point, paths);
            save_progress( ...
                config, point, "endpoint", result, paths, runtime_signature);
            if ~result.success
                message = "Endpoint simulation failed: " + string(point.id);
                return;
            end
            result_paths = result.result_paths;
            cached.result_paths = result.result_paths;
            cached.started_at = result.started_at;
            session_results(char(point.id)) = cached;
        end
        endpoint_matrices{endpoint_index} = ...
            load_result_matrices(config, result_paths);
        if isempty(endpoint_matrices{endpoint_index})
            message = "Endpoint has no valid result matrix: " + ...
                string(point.id);
            return;
        end
    catch endpoint_error
        message = "Endpoint exception: " + string(endpoint_error.message);
        return;
    end
end
absolute_tolerance = 1e-9;
relative_tolerance = 1e-9;
if numel(endpoint_matrices) >= 2 && ...
        ~result_matrices_differ( ...
            endpoint_matrices{1}, endpoint_matrices{end}, ...
            absolute_tolerance, relative_tolerance)
    message = "Endpoint result data has no material difference.";
    return;
end
endpoint_ok = true;
message = "ok";
end


function matrices = load_result_matrices(config, result_paths)
matrices = {};
if numel(result_paths) ~= numel(config.results)
    return;
end
for result_index = 1:numel(result_paths)
    data = readmatrix(result_paths{result_index}, 'FileType', 'text');
    data = data(~all(isnan(data), 2), :);
    if ~isempty(data) && all(isfinite(data(:)))
        matrices{end + 1} = data;
    else
        matrices = {};
        return;
    end
end
end


function different = result_matrices_differ( ...
        first_matrices, second_matrices, ...
        absolute_tolerance, relative_tolerance)
different = numel(first_matrices) ~= numel(second_matrices);
if different
    return;
end
for matrix_index = 1:numel(first_matrices)
    first_matrix = first_matrices{matrix_index};
    second_matrix = second_matrices{matrix_index};
    if ~isequal(size(first_matrix), size(second_matrix))
        different = true;
        return;
    end
    difference = abs(first_matrix - second_matrix);
    scale = max(abs(first_matrix), abs(second_matrix));
    if any(difference(:) > ...
            absolute_tolerance + relative_tolerance .* scale(:))
        different = true;
        return;
    end
end
different = false;
end


function summary = run_sweep( ...
        config, paths, runtime_signature, session_results, points)
summary.failed_points = strings(0, 1);
summary.result_files = struct();
for point_index = 1:numel(points)
    point = points(point_index);
    fprintf('  [%d/%d] %s ', point_index, numel(points), string(point.id));
    try
        [reusable, result_paths] = reusable_result( ...
            config, point, paths, runtime_signature, session_results);
        if reusable
            summary.result_files.(matlab.lang.makeValidName(point.id)) = ...
                result_paths;
            fprintf('(reused)\n');
            continue;
        end
        result = run_waveda(config, point, paths);
        save_progress(config, point, "run", result, paths, runtime_signature);
        if ~result.success
            summary.failed_points(end + 1) = string(point.id);
            fprintf('FAILED\n');
            continue;
        end
        summary.result_files.(matlab.lang.makeValidName(point.id)) = ...
            result.result_paths;
        cached.result_paths = result.result_paths;
        cached.started_at = result.started_at;
        session_results(char(point.id)) = cached;
        fprintf('OK\n');
    catch point_error
        result.success = false;
        result.attempts = 0;
        result.started_at = now;
        result.finished_at = now;
        result.message = "Point exception: " + string(point_error.message);
        result.result_paths = {};
        save_progress(config, point, "run", result, paths, runtime_signature);
        summary.failed_points(end + 1) = string(point.id);
        fprintf('ERROR: %s\n', string(point_error.message));
        continue;
    end
end
if has_adaptive_plan(config)
    analysis = analyze_results(config, summary.result_files);
    best_point = select_adaptive_best_point(config, analysis, points);
    adaptive_points = build_adaptive_stage2_points(config, best_point);
    if isempty(adaptive_points)
        error("Adaptive stage 2 produced no new points.");
    end
    for point_index = 1:numel(adaptive_points)
        point = adaptive_points(point_index);
        try
            [reusable, result_paths] = reusable_result( ...
                config, point, paths, runtime_signature, session_results);
            if reusable
                summary.result_files.( ...
                    matlab.lang.makeValidName(point.id)) = result_paths;
                continue;
            end
            result = run_waveda(config, point, paths);
            save_progress( ...
                config, point, "adaptive", result, paths, runtime_signature);
            if ~result.success
                summary.failed_points(end + 1) = string(point.id);
                continue;
            end
            summary.result_files.(matlab.lang.makeValidName(point.id)) = ...
                result.result_paths;
            cached.result_paths = result.result_paths;
            cached.started_at = result.started_at;
            session_results(char(point.id)) = cached;
        catch point_error
            result.success = false;
            result.attempts = 0;
            result.started_at = now;
            result.finished_at = now;
            result.message = ...
                "Adaptive point exception: " + string(point_error.message);
            result.result_paths = {};
            save_progress( ...
                config, point, "adaptive", result, paths, runtime_signature);
            summary.failed_points(end + 1) = string(point.id);
            continue;
        end
    end
end
end


function adaptive = has_adaptive_plan(config)
adaptive = isfield(config.sweep, 'planned_points') && ...
    isstruct(config.sweep.planned_points) && ...
    isscalar(config.sweep.planned_points) && ...
    isfield(config.sweep.planned_points, 'mode') && ...
    string(config.sweep.planned_points.mode) == ...
        "adaptive_coarse_to_fine";
end


function point = select_adaptive_best_point(config, analysis, points)
objective = config.sweep.planned_points.stage2.selection_metric;
if string(objective.result_type) ~= "port" || ...
        string(objective.metric) ~= "target_frequency_value" || ...
        string(objective.goal) ~= "minimize"
    error("Unsupported adaptive selection metric.");
end
port_name = matlab.lang.makeValidName(string(objective.result_name));
trace_name = matlab.lang.makeValidName(string(objective.trace));
best_value = inf;
point = struct([]);
for point_index = 1:numel(points)
    point_name = matlab.lang.makeValidName(string(points(point_index).id));
    if ~isfield(analysis.points, point_name)
        continue;
    end
    point_metrics = analysis.points.(point_name);
    if ~isfield(point_metrics.ports, port_name)
        continue;
    end
    port_metrics = point_metrics.ports.(port_name);
    if ~isfield(port_metrics.traces, trace_name)
        continue;
    end
    metric = port_metrics.traces.(trace_name).nearest_value;
    if isfinite(metric) && metric < best_value
        best_value = metric;
        point = points(point_index);
    end
end
if isempty(point)
    error("Adaptive sweep could not find a valid Port metric in stage 1.");
end
end


function points = build_adaptive_stage2_points(config, best_point)
parameters = config.sweep.planned_points.stage2;
if string(parameters.neighborhood) ~= "adjacent_coarse_interval"
    error("Unsupported adaptive neighborhood.");
end
refinement_factor = double(parameters.refinement_factor);
if refinement_factor < 2 || refinement_factor ~= fix(refinement_factor)
    error("Adaptive refinement_factor must be an integer of at least 2.");
end

variables = config.sweep.variables;
value_sets = cell(1, numel(variables));
for variable_index = 1:numel(variables)
    variable_name = string(variables(variable_index).name);
    assignment_index = find( ...
        strcmpi(string({best_point.assignments.name}), variable_name), 1);
    if isempty(assignment_index)
        error("Best point has no assignment for %s.", variable_name);
    end
    best_value = double(best_point.assignments(assignment_index).value);
    value_sets{variable_index} = refined_values( ...
        variable_values(variables(variable_index)), ...
        best_value, refinement_factor);
end

stage1_points = config.sweep.planned_points.stage1_points;
points = struct('id', {}, 'assignments', {});
if numel(variables) == 1
    for first_index = 1:numel(value_sets{1})
        assignments = struct( ...
            'name', string(variables(1).name), ...
            'value', value_sets{1}(first_index));
        if logical(parameters.exclude_stage1_points) && ...
                is_stage1_assignment(assignments, stage1_points)
            continue;
        end
        points(end + 1) = make_adaptive_point( ...
            numel(points) + 1, assignments);
    end
else
    for first_index = 1:numel(value_sets{1})
        for second_index = 1:numel(value_sets{2})
            assignments(1) = struct( ...
                'name', string(variables(1).name), ...
                'value', value_sets{1}(first_index));
            assignments(2) = struct( ...
                'name', string(variables(2).name), ...
                'value', value_sets{2}(second_index));
            if logical(parameters.exclude_stage1_points) && ...
                    is_stage1_assignment(assignments, stage1_points)
                continue;
            end
            points(end + 1) = make_adaptive_point( ...
                numel(points) + 1, assignments);
        end
    end
end
end


function values = variable_values(variable)
if isfield(variable, 'values')
    values = double(variable.values(:)');
else
    values = double(variable.start):double(variable.step):double(variable.stop);
end
end


function values = refined_values(coarse_values, best_value, factor)
coarse_values = unique(sort(double(coarse_values(:)')));
[~, best_index] = min(abs(coarse_values - double(best_value)));
values = double(best_value);
if best_index > 1
    values = [values, linspace( ...
        coarse_values(best_index - 1), double(best_value), factor + 1)];
end
if best_index < numel(coarse_values)
    values = [values, linspace( ...
        double(best_value), coarse_values(best_index + 1), factor + 1)];
end
values = unique(sort(values));
end


function matched = is_stage1_assignment(assignments, stage1_points)
candidate = jsonencode(assignments);
matched = false;
for point_index = 1:numel(stage1_points)
    if strcmp(candidate, jsonencode(stage1_points(point_index).assignments))
        matched = true;
        return;
    end
end
end


function point = make_adaptive_point(point_index, assignments)
point = make_point(point_index, assignments);
point.id = "a" + extractAfter(string(point.id), 1);
end


function analysis = analyze_results(config, result_files)
unit = lower(string(config.frequency.unit));
multipliers = struct('hz', 1, 'khz', 1e3, 'mhz', 1e6, 'ghz', 1e9);
target_hz = double(config.frequency.target) * multipliers.(char(unit));
analysis.target_frequency_hz = target_hz;
analysis.nearest_frequency_hz = [];
analysis.nearest_value = [];
analysis.resonance_frequency_hz = [];
analysis.resonance_value = [];
analysis.points = struct();
point_names = fieldnames(result_files);
for point_index = 1:numel(point_names)
    paths = result_files.(point_names{point_index});
    point_metrics.ports = struct();
    for result_index = 1:min(numel(paths), numel(config.results))
        result_type = lower(string(config.results(result_index).type));
        if result_type ~= "port"
            continue;
        end
        try
            data = readmatrix(paths{result_index}, 'FileType', 'text');
        catch
            continue;
        end
        data = data(~all(isnan(data), 2), :);
        if isempty(data) || size(data, 2) < 2 || ~all(isfinite(data(:)))
            continue;
        end
        trace_names = string(config.results(result_index).traces);
        try
            traces = parse_port_traces( ...
                data, numel(trace_names), ...
                config.data_frequency_unit_resolved);
        catch
            continue;
        end
        metrics.traces = struct();
        for trace_index = 1:numel(traces)
            trace = traces(trace_index);
            [~, nearest_index] = min( ...
                abs(trace.frequency_hz - target_hz));
            [resonance_value, resonance_index] = min(trace.values);
            trace_metric.nearest_frequency_hz = ...
                trace.frequency_hz(nearest_index);
            trace_metric.nearest_value = trace.values(nearest_index);
            trace_metric.resonance_frequency_hz = ...
                trace.frequency_hz(resonance_index);
            trace_metric.resonance_value = resonance_value;
            trace_name = matlab.lang.makeValidName(trace_names(trace_index));
            metrics.traces.(trace_name) = trace_metric;
            if trace_index == 1
                metrics.nearest_frequency_hz = ...
                    trace_metric.nearest_frequency_hz;
                metrics.nearest_value = trace_metric.nearest_value;
                metrics.resonance_frequency_hz = ...
                    trace_metric.resonance_frequency_hz;
                metrics.resonance_value = trace_metric.resonance_value;
            end
        end
        result_name = matlab.lang.makeValidName( ...
            config.results(result_index).name);
        point_metrics.ports.(result_name) = metrics;
        if isempty(analysis.nearest_frequency_hz)
            analysis.nearest_frequency_hz = metrics.nearest_frequency_hz;
            analysis.nearest_value = metrics.nearest_value;
            analysis.resonance_frequency_hz = ...
                metrics.resonance_frequency_hz;
            analysis.resonance_value = metrics.resonance_value;
        end
    end
    if ~isempty(fieldnames(point_metrics.ports))
        analysis.points.(point_names{point_index}) = point_metrics;
    end
end
end


function report_path = build_report(config, summary, analysis, paths)
report.task_signature = config.task_signature;
report.failed_points = summary.failed_points;
report.completed_point_count = numel(fieldnames(summary.result_files));
report.analysis = analysis;
report_path = fullfile(paths.output, 'report.json');
report_id = fopen(report_path, 'w');
fprintf(report_id, '%s\n', jsonencode(report, 'PrettyPrint', true));
fclose(report_id);
end
