from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from raggg.config import Settings


PACKAGE_FORMAT = "waveda-knowledge-package"
PACKAGE_FORMAT_VERSION = 1
REQUIRED_INDEX_FILES = {"build_meta.json", "chunks.json", "vectors.npy"}
MAX_PACKAGE_FILES = 10_000
MAX_PACKAGE_FILE_BYTES = 128 * 1024 * 1024
MAX_PACKAGE_TOTAL_BYTES = 512 * 1024 * 1024


class KnowledgePackageError(RuntimeError):
    pass


@dataclass(frozen=True)
class KnowledgePackageInfo:
    version: str
    created_at: str
    release_notes: str
    file_count: int


def current_knowledge_version(settings: Settings) -> str:
    metadata = settings.data_dir / "index" / "knowledge_package.json"
    try:
        value = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    version = str(value.get("version", "")).strip()
    if version:
        return version

    bundled = settings.project_root / "config" / "version.txt"
    try:
        return bundled.read_text(encoding="utf-8").strip() or "内置版本"
    except OSError:
        return "内置版本"


def export_knowledge_package(
    settings: Settings,
    output_path: Path,
    version: str,
    release_notes: str = "",
) -> KnowledgePackageInfo:
    if not settings.can_manage_knowledge:
        raise PermissionError("用户版无权导出知识库更新包。")
    clean_version = version.strip()
    if not clean_version:
        raise KnowledgePackageError("知识库版本号不能为空。")

    source_files = _collect_source_files(settings)
    output_path = output_path.with_suffix(".wkb")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.unlink(missing_ok=True)

    checksums: dict[str, str] = {}
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source, archive_name in source_files:
                payload = source.read_bytes()
                checksums[archive_name] = hashlib.sha256(payload).hexdigest()
                archive.writestr(archive_name, payload)

            manifest = {
                "format": PACKAGE_FORMAT,
                "format_version": PACKAGE_FORMAT_VERSION,
                "version": clean_version,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "release_notes": release_notes.strip(),
                "file_count": len(checksums),
                "files": checksums,
            }
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
        temporary.replace(output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return _manifest_info(manifest)


def inspect_knowledge_package(package_path: Path) -> KnowledgePackageInfo:
    manifest, _ = _validated_package(package_path)
    return _manifest_info(manifest)


def install_knowledge_package(
    settings: Settings,
    package_path: Path,
) -> KnowledgePackageInfo:
    if settings.can_manage_knowledge:
        raise PermissionError("维护版请修改源知识库并重新构建，不应安装用户更新包。")

    manifest, payloads = _validated_package(package_path)
    info = _manifest_info(manifest)
    update_root = settings.project_root / ".kb_update"
    update_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="install-", dir=update_root) as temp_name:
        staging = Path(temp_name)
        for archive_name, payload in payloads.items():
            relative = PurePosixPath(archive_name).relative_to("payload")
            target = staging.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

        staged_knowledge = staging / "knowledge_base"
        staged_index = staging / "data" / "index"
        if not staged_knowledge.is_dir() or not staged_index.is_dir():
            raise KnowledgePackageError("更新包缺少知识库或索引目录。")

        metadata = {
            "version": info.version,
            "created_at": info.created_at,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "release_notes": info.release_notes,
        }
        (staged_index / "knowledge_package.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _replace_with_backup(settings, staged_knowledge, staged_index, info.version)

    _prune_backups(settings.project_root / "backups" / "knowledge_base", keep=3)
    return info


def _collect_source_files(settings: Settings) -> list[tuple[Path, str]]:
    if not settings.obsidian_vault_root.is_dir():
        raise KnowledgePackageError("知识库目录不存在。")
    index_root = settings.data_dir / "index"
    missing = sorted(name for name in REQUIRED_INDEX_FILES if not (index_root / name).is_file())
    if missing:
        raise KnowledgePackageError(f"索引不完整，请先重建：{', '.join(missing)}")

    files: list[tuple[Path, str]] = []
    for source in sorted(settings.obsidian_vault_root.rglob("*")):
        relative = source.relative_to(settings.obsidian_vault_root)
        if not source.is_file() or any(part.startswith(".") for part in relative.parts):
            continue
        files.append((source, f"payload/knowledge_base/{relative.as_posix()}"))
    for source in sorted(index_root.iterdir()):
        if source.is_file() and source.name != "knowledge_package.json":
            files.append((source, f"payload/data/index/{source.name}"))
    return files


def _validated_package(package_path: Path) -> tuple[dict, dict[str, bytes]]:
    try:
        archive = zipfile.ZipFile(package_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise KnowledgePackageError("无法读取知识库更新包。") from exc

    with archive:
        members = archive.infolist()
        if len(members) > MAX_PACKAGE_FILES + 1:  # payload files plus manifest.json
            raise KnowledgePackageError("更新包文件数量过多。")
        total_size = 0
        for member in members:
            if member.file_size > MAX_PACKAGE_FILE_BYTES:
                raise KnowledgePackageError(f"更新包中的单个文件过大：{member.filename}")
            total_size += member.file_size
            if total_size > MAX_PACKAGE_TOTAL_BYTES:
                raise KnowledgePackageError("更新包解压后的总体积过大。")

        names = archive.namelist()
        if "manifest.json" not in names:
            raise KnowledgePackageError("更新包缺少 manifest.json。")
        if len(names) != len(set(names)):
            raise KnowledgePackageError("更新包包含重复路径。")
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
            raise KnowledgePackageError("更新包清单损坏。") from exc

        if (
            manifest.get("format") != PACKAGE_FORMAT
            or manifest.get("format_version") != PACKAGE_FORMAT_VERSION
        ):
            raise KnowledgePackageError("不支持的知识库更新包格式。")
        checksums = manifest.get("files")
        if not isinstance(checksums, dict) or not checksums:
            raise KnowledgePackageError("更新包文件清单为空。")
        if manifest.get("file_count") != len(checksums):
            raise KnowledgePackageError("更新包文件数量与清单不一致。")
        if set(names) != {"manifest.json", *checksums}:
            raise KnowledgePackageError("更新包包含未登记文件或缺少登记文件。")

        payloads: dict[str, bytes] = {}
        for name, expected_hash in checksums.items():
            path = PurePosixPath(name)
            if (
                not name.startswith("payload/")
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in name
            ):
                raise KnowledgePackageError("更新包包含不安全路径。")
            payload = archive.read(name)
            if hashlib.sha256(payload).hexdigest() != expected_hash:
                raise KnowledgePackageError(f"文件完整性校验失败：{name}")
            payloads[name] = payload

    required = {f"payload/data/index/{name}" for name in REQUIRED_INDEX_FILES}
    if not required.issubset(payloads):
        raise KnowledgePackageError("更新包索引不完整。")
    if not any(name.startswith("payload/knowledge_base/") for name in payloads):
        raise KnowledgePackageError("更新包中没有知识库文档。")
    return manifest, payloads


def _replace_with_backup(
    settings: Settings,
    staged_knowledge: Path,
    staged_index: Path,
    version: str,
) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe_version = "".join(char if char.isalnum() or char in ".-_" else "_" for char in version)
    backup = settings.project_root / "backups" / "knowledge_base" / f"{timestamp}-{safe_version}"
    backup.mkdir(parents=True, exist_ok=False)
    knowledge_backup = backup / "knowledge_base"
    index_backup = backup / "data" / "index"
    index_backup.parent.mkdir(parents=True, exist_ok=True)

    current_knowledge = settings.obsidian_vault_root
    current_index = settings.data_dir / "index"
    moved_knowledge = False
    moved_index = False
    installed_knowledge = False
    installed_index = False
    try:
        if current_knowledge.exists():
            shutil.move(str(current_knowledge), str(knowledge_backup))
            moved_knowledge = True
        if current_index.exists():
            shutil.move(str(current_index), str(index_backup))
            moved_index = True
        current_knowledge.parent.mkdir(parents=True, exist_ok=True)
        current_index.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_knowledge), str(current_knowledge))
        installed_knowledge = True
        shutil.move(str(staged_index), str(current_index))
        installed_index = True
    except Exception:
        if installed_knowledge:
            shutil.rmtree(current_knowledge, ignore_errors=True)
        if installed_index:
            shutil.rmtree(current_index, ignore_errors=True)
        if moved_knowledge and knowledge_backup.exists():
            shutil.move(str(knowledge_backup), str(current_knowledge))
        if moved_index and index_backup.exists():
            current_index.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(index_backup), str(current_index))
        raise


def _prune_backups(root: Path, keep: int) -> None:
    if not root.is_dir():
        return
    backups = sorted((path for path in root.iterdir() if path.is_dir()), reverse=True)
    for old in backups[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def _manifest_info(manifest: dict) -> KnowledgePackageInfo:
    return KnowledgePackageInfo(
        version=str(manifest.get("version", "")),
        created_at=str(manifest.get("created_at", "")),
        release_notes=str(manifest.get("release_notes", "")),
        file_count=int(manifest.get("file_count", 0)),
    )
