from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from unittest.mock import patch

from raggg.config import Settings
from raggg.knowledge_package import (
    KnowledgePackageError,
    current_knowledge_version,
    export_knowledge_package,
    inspect_knowledge_package,
    install_knowledge_package,
)
from raggg.pipeline.builder import build_knowledge_base


def make_settings(root: Path, edition: str) -> Settings:
    return Settings(
        project_root=root,
        waveda_root=None,
        waveda_help_root=root / "wavEDA_docs" / "helpHtml" / "helpHtml",
        waveda_example_root=None,
        obsidian_vault_root=root / "knowledge_base",
        data_dir=root / "data",
        embedding_model="local-hashed-vectors",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="",
        llm_model="deepseek-chat",
        app_edition=edition,
    )


def write_package_sources(settings: Settings, marker: str = "new") -> None:
    settings.obsidian_vault_root.mkdir(parents=True, exist_ok=True)
    (settings.obsidian_vault_root / "guide.md").write_text(marker, encoding="utf-8")
    index = settings.data_dir / "index"
    index.mkdir(parents=True, exist_ok=True)
    (index / "build_meta.json").write_text('{"model":"test"}', encoding="utf-8")
    (index / "chunks.json").write_text(f'[{{"text":"{marker}"}}]', encoding="utf-8")
    (index / "vectors.npy").write_bytes(b"NUMPY-" + marker.encode())


def test_export_inspect_and_install_with_backup(tmp_path: Path) -> None:
    maintainer = make_settings(tmp_path, "maintainer")
    write_package_sources(maintainer)
    package = tmp_path / "knowledge-2.0.0.wkb"

    exported = export_knowledge_package(maintainer, package, "2.0.0", "reviewed")
    inspected = inspect_knowledge_package(package)

    assert exported.version == "2.0.0"
    assert inspected == exported

    (maintainer.obsidian_vault_root / "guide.md").write_text("old", encoding="utf-8")
    (maintainer.data_dir / "index" / "chunks.json").write_text("[]", encoding="utf-8")
    user = make_settings(tmp_path, "user")
    installed = install_knowledge_package(user, package)

    assert installed.version == "2.0.0"
    assert (user.obsidian_vault_root / "guide.md").read_text(encoding="utf-8") == "new"
    assert current_knowledge_version(user) == "2.0.0"
    backups = list((tmp_path / "backups" / "knowledge_base").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "knowledge_base" / "guide.md").read_text(encoding="utf-8") == "old"


def test_tampered_package_is_rejected(tmp_path: Path) -> None:
    maintainer = make_settings(tmp_path, "maintainer")
    write_package_sources(maintainer)
    package = tmp_path / "knowledge.wkb"
    export_knowledge_package(maintainer, package, "1.0.0")

    with zipfile.ZipFile(package, "r") as archive:
        members = [(item.filename, archive.read(item.filename)) for item in archive.infolist()]
    with zipfile.ZipFile(package, "w") as archive:
        for name, payload in members:
            if name == "payload/data/index/chunks.json":
                payload = b"tampered"
            archive.writestr(name, payload)

    with pytest.raises(KnowledgePackageError):
        inspect_knowledge_package(package)


def test_oversized_package_is_rejected_before_payload_is_loaded(tmp_path: Path) -> None:
    maintainer = make_settings(tmp_path, "maintainer")
    write_package_sources(maintainer)
    package = tmp_path / "knowledge.wkb"
    export_knowledge_package(maintainer, package, "1.0.0")

    with patch("raggg.knowledge_package.MAX_PACKAGE_TOTAL_BYTES", 1):
        with pytest.raises(KnowledgePackageError, match="总体积过大"):
            inspect_knowledge_package(package)


def test_edition_permissions_are_enforced_by_backend(tmp_path: Path) -> None:
    maintainer = make_settings(tmp_path, "maintainer")
    user = make_settings(tmp_path, "user")
    write_package_sources(maintainer)
    package = tmp_path / "knowledge.wkb"

    with pytest.raises(PermissionError):
        export_knowledge_package(user, package, "1.0.0")
    with pytest.raises(PermissionError):
        install_knowledge_package(maintainer, package)
    with pytest.raises(PermissionError):
        build_knowledge_base(user)


def test_settings_normalize_unknown_edition_to_maintainer(tmp_path: Path) -> None:
    user = Settings.from_env({"RAGGG_PORTABLE_ROOT": str(tmp_path), "RAG_APP_EDITION": "USER"})
    unknown = Settings.from_env({"RAGGG_PORTABLE_ROOT": str(tmp_path), "RAG_APP_EDITION": "other"})

    assert user.app_edition == "user"
    assert not user.can_manage_knowledge
    assert unknown.app_edition == "maintainer"
    assert unknown.can_manage_knowledge


def test_embedded_edition_overrides_editable_environment(tmp_path: Path) -> None:
    with patch("raggg.config.EMBEDDED_APP_EDITION", "user"):
        settings = Settings.from_env(
            {
                "RAGGG_PORTABLE_ROOT": str(tmp_path),
                "RAG_APP_EDITION": "maintainer",
            }
        )

    assert settings.app_edition == "user"
    assert not settings.can_manage_knowledge
