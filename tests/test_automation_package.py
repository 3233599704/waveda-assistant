from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.automation.package_builder import (
    README_NAME,
    PackageBuildError,
    ScriptPackage,
)
import raggg.automation.package_builder as package_builder
from raggg.automation.renderers.xml_renderer import render_template_xml
from raggg.automation.task_config import build_task_config, task_signature


def make_config(controller, *, project_file=r"E:\target projects\filter.tsp"):
    return build_task_config(
        package_dir=r"C:\local output\portable sweep",
        waveda_exe=r"D:\Program Files\WavEDA\WavEDA.exe",
        project_file=project_file,
        controller=controller,
        sweep_vars={"length": [9.0, 9.5, 10.0]},
        strategy="explicit_values",
        results=[
            {"name": "Port_S_data_1", "type": "port", "traces": ["S11 dB"]}
        ],
        target_freq=2.4567,
        frequency_unit="GHz",
    )


@pytest.mark.parametrize(
    ("controller", "controller_file"),
    [("matlab", "run_batch.m"), ("python", "run_batch.py")],
)
def test_generate_files_has_exact_language_specific_manifest(
    controller, controller_file
):
    files = ScriptPackage(make_config(controller)).generate_files()

    assert set(files) == {
        "README_运行说明.md",
        "task_config.json",
        "template.xml",
        controller_file,
    }
    assert not any(name.lower().endswith(".tsp") for name in files)
    unselected = "run_batch.py" if controller == "matlab" else "run_batch.m"
    assert unselected not in files


@pytest.mark.parametrize("controller", ["matlab", "python"])
def test_package_readme_describes_completed_controller_workflow(controller):
    files = ScriptPackage(make_config(controller)).generate_files()
    readme = files[README_NAME]

    assert "默认运行会自动执行 `check -> smoke -> endpoint -> run`" in readme
    assert "后续控制器任务" not in readme
    assert "入口骨架" not in readme
    assert "结果保存在压缩包解压目录内" in readme


def test_package_builder_has_no_obsolete_controller_scaffolds():
    assert not hasattr(package_builder, "_render_python_scaffold")
    assert not hasattr(package_builder, "_render_matlab_scaffold")


def test_generated_json_round_trips_without_local_package_path():
    config = make_config("python")
    files = ScriptPackage(config).generate_files()

    packaged_config = json.loads(files["task_config.json"])

    assert "package_dir" not in packaged_config
    assert packaged_config["target"] == config["target"]
    assert packaged_config["task_signature"] == task_signature(packaged_config)
    assert packaged_config["task_signature"] != task_signature(config)


def test_packaged_config_carries_signed_normalized_payload_for_matlab_check():
    config = make_config("matlab")
    files = ScriptPackage(config).generate_files()
    packaged_config = json.loads(files["task_config.json"])

    signed_payload = json.loads(packaged_config["task_signature_payload"])
    assert signed_payload["target"] == config["target"]
    assert signed_payload["sweep"]["planned_points"] == (
        packaged_config["sweep"]["planned_points"]
    )
    assert signed_payload["sweep"]["endpoint_ids"] == (
        packaged_config["sweep"]["endpoint_ids"]
    )
    assert "task_signature" not in signed_payload


def test_packaged_config_signs_template_xml_sha256():
    files = ScriptPackage(make_config("python")).generate_files()
    packaged_config = json.loads(files["task_config.json"])
    expected_hash = hashlib.sha256(
        files["template.xml"].encode("utf-8")
    ).hexdigest()

    assert packaged_config["integrity"]["template_xml_sha256"] == expected_hash
    signed_payload = json.loads(packaged_config["task_signature_payload"])
    assert signed_payload["integrity"]["template_xml_sha256"] == expected_hash


def test_generated_xml_is_parseable_and_matches_external_project_path():
    config = make_config("matlab")
    xml_text = ScriptPackage(config).generate_files()["template.xml"]

    root = ET.fromstring(xml_text)
    load = root.find("./command[@cmdType='load']")

    assert load is not None
    assert load.get("file") == config["target"]["project_file"]


def test_python_controller_is_compilable_before_package_is_returned():
    source = ScriptPackage(make_config("python")).generate_files()["run_batch.py"]

    compile(source, "run_batch.py", "exec")


@pytest.mark.parametrize(
    "placeholder",
    [
        "$TSP_PATH",
        "<PROJECT_FILE>",
        "{{RESULT_NAME}}",
        "<<<VARIABLE_NAME>>>",
        "${WAVEDA_EXE}",
    ],
)
def test_unresolved_controller_placeholder_blocks_generation(placeholder):
    package = ScriptPackage(
        make_config("python"),
        controller_renderer=lambda _config: f"print({placeholder!r})\n",
    )

    with pytest.raises(PackageBuildError, match="占位符"):
        package.generate_files()


def test_plain_matlab_dollar_text_is_not_treated_as_a_placeholder():
    controller = """function run_batch()
fprintf('Price is $5 and the note says $value.\\n');
end
"""
    files = ScriptPackage(
        make_config("matlab"),
        controller_renderer=lambda _config: controller,
    ).generate_files()

    assert files["run_batch.m"] == controller


@pytest.mark.parametrize(
    "project_file",
    [
        r"Y:\$PROJECTS\x.tsp",
        r"Y:\$TSP_PATH\x.tsp",
    ],
)
def test_dollar_named_remote_path_is_preserved_as_user_data(project_file):
    files = ScriptPackage(
        make_config("python", project_file=project_file)
    ).generate_files()

    packaged_config = json.loads(files["task_config.json"])
    assert packaged_config["target"]["project_file"] == project_file


def test_config_fragment_cannot_hide_a_real_template_sentinel():
    config = make_config("python")
    config["results"][0]["name"] = "TSP"
    package = ScriptPackage(
        config,
        controller_renderer=lambda _config: "print('$TSP_PATH')\n",
    )

    with pytest.raises(PackageBuildError, match="占位符"):
        package.generate_files()


def test_invalid_python_controller_blocks_generation():
    package = ScriptPackage(
        make_config("python"),
        controller_renderer=lambda _config: "def broken(:\n",
    )

    with pytest.raises(PackageBuildError, match="Python"):
        package.generate_files()


def test_malformed_generated_xml_blocks_generation(monkeypatch):
    config = make_config("matlab")
    monkeypatch.setattr(
        "raggg.automation.package_builder.render_template_xml",
        lambda _config: "<script><command></script>",
    )

    with pytest.raises(PackageBuildError, match="XML"):
        ScriptPackage(config).generate_files()


def test_unresolved_xml_variable_value_blocks_generation(monkeypatch):
    config = make_config("matlab")
    root = ET.fromstring(render_template_xml(config))
    modify = root.find("./command[@cmdType='modify']")
    assert modify is not None
    modify.set("value", "$FIRST_VALUE")
    unresolved_xml = ET.tostring(root, encoding="unicode")
    monkeypatch.setattr(
        "raggg.automation.package_builder.render_template_xml",
        lambda _config: unresolved_xml,
    )

    with pytest.raises(PackageBuildError, match="template.xml"):
        ScriptPackage(config).generate_files()


@pytest.mark.parametrize("text_location", ["root_text", "command_tail"])
def test_unresolved_xml_text_node_blocks_generation(monkeypatch, text_location):
    config = make_config("matlab")
    root = ET.fromstring(render_template_xml(config))
    if text_location == "root_text":
        root.text = "$EXPORT_COMMANDS"
    else:
        root[0].tail = "$EXPORT_COMMANDS"
    unresolved_xml = ET.tostring(root, encoding="unicode")
    monkeypatch.setattr(
        "raggg.automation.package_builder.render_template_xml",
        lambda _config: unresolved_xml,
    )

    with pytest.raises(PackageBuildError, match="template.xml"):
        ScriptPackage(config).generate_files()


def test_write_zip_contains_exact_generated_files(tmp_path):
    package = ScriptPackage(make_config("python"))
    expected_files = package.generate_files()
    destination = tmp_path / "waveda_sweep.zip"

    written = package.write_zip(destination)

    assert written == destination
    assert written.is_file()
    with zipfile.ZipFile(written) as archive:
        assert set(archive.namelist()) == set(expected_files)
        assert archive.read("task_config.json").decode("utf-8") == (
            expected_files["task_config.json"]
        )
