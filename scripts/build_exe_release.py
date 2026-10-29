from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "WavEDA_Assistant"
DIST_DIR = ROOT / "dist"
APP_DIR = DIST_DIR / APP_NAME
TEXT_SUFFIXES = {".md", ".txt", ".json", ".csv", ".html", ".htm"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp"}
ARCHIVE_ROOT = "WavEDA"
INVALID_API_KEYS = {
    "YOUR_API_KEY_HERE",
    "YOUR_API_KEY",
    "CHANGE_ME",
}


def _valid_api_key(value: str) -> bool:
    clean = value.strip()
    return bool(clean) and clean.upper() not in INVALID_API_KEYS


def _run(*args: str) -> None:
    print(">", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def _create_windows_icon() -> None:
    """Wrap the existing 96x96 PNG in a Windows ICO container."""
    source = ROOT / "wavEDA_docs" / "helpHtml" / "image" / "助手图标.png"
    target = ROOT / "build" / "waveda.ico"
    png = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 96, 96, 0, 0, 1, 32, len(png), 22)
    target.write_bytes(header + entry + png)


def _write_embedded_edition(edition: str) -> None:
    generated = ROOT / "build" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "raggg_build_edition.py").write_text(
        f"APP_EDITION = {edition!r}\n",
        encoding="utf-8",
    )


def _portable_text(text: str) -> str:
    local = _read_env(ROOT / "config" / ".env")
    configured_paths = (
        (local.get("WAVEDA_HELP_ROOT", ""), r"wavEDA_docs\helpHtml\helpHtml"),
        (local.get("WAVEDA_EXAMPLE_ROOT", ""), "Example"),
        (local.get("WAVEDA_ROOT", ""), "<WAVEDA_ROOT>"),
        (str(ROOT), "."),
    )
    replacements: list[tuple[str, str]] = []
    for source, replacement in configured_paths:
        clean = source.strip().rstrip("\\/")
        if not clean:
            continue
        if replacement != "." and not Path(clean).is_absolute():
            continue
        replacements.append((clean, replacement))
        replacements.append((clean.replace("\\", "/"), replacement.replace("\\", "/")))
    replacements.sort(key=lambda pair: len(pair[0]), reverse=True)
    for source, replacement in replacements:
        text = text.replace(source, replacement)
    return text


def _sanitize_release_text() -> None:
    roots = (APP_DIR / "knowledge_base", APP_DIR / "data", APP_DIR / "config")
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if path.suffix.lower() == ".json":
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue

                def sanitize_json(item):
                    if isinstance(item, str):
                        return _portable_text(item)
                    if isinstance(item, list):
                        return [sanitize_json(child) for child in item]
                    if isinstance(item, dict):
                        return {key: sanitize_json(child) for key, child in item.items()}
                    return item

                path.write_text(
                    json.dumps(sanitize_json(value), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            sanitized = _portable_text(text)
            if sanitized != text:
                path.write_text(sanitized, encoding="utf-8")


def _copy_release_files(edition: str) -> None:
    knowledge_ignore = (
        shutil.ignore_patterns(".source_files", ".imports")
        if edition == "user"
        else None
    )
    shutil.copytree(
        ROOT / "knowledge_base",
        APP_DIR / "knowledge_base",
        dirs_exist_ok=True,
        ignore=knowledge_ignore,
    )
    shutil.copytree(ROOT / "wavEDA_docs", APP_DIR / "wavEDA_docs", dirs_exist_ok=True)

    shutil.copytree(ROOT / "data" / "index", APP_DIR / "data" / "index", dirs_exist_ok=True)
    (APP_DIR / "data" / "favorites.json").write_text("[]\n", encoding="utf-8")
    # conversations.json is intentionally omitted; the app creates a clean session on first launch.
    (APP_DIR / "data" / "conversations.json").unlink(missing_ok=True)

    config_dir = APP_DIR / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "config" / ".env.example", config_dir / ".env.example")
    _write_release_env(config_dir / ".env", edition)
    shutil.copy2(ROOT / "config" / "version.txt", config_dir / "version.txt")
    shutil.copy2(ROOT / "README-EXE.md", APP_DIR / "使用说明.md")
    _sanitize_release_text()


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_release_env(target: Path, edition: str) -> None:
    local = _read_env(ROOT / "config" / ".env")
    api_key = local.get("RAG_LLM_API_KEY", "")
    if not _valid_api_key(api_key):
        raise RuntimeError(
            "The local API key is empty or a placeholder; refusing to create a preconfigured release."
        )
    release_values = {
        "RAG_APP_EDITION": edition,
        "RAG_LANGUAGE": local.get("RAG_LANGUAGE", "zh"),
        "RAG_THEME": local.get("RAG_THEME", "light"),
        "RAG_PERSONALITY": local.get("RAG_PERSONALITY", "normal"),
        "RAG_LLM_BASE_URL": local.get("RAG_LLM_BASE_URL", "https://api.deepseek.com"),
        "RAG_LLM_API_KEY": api_key,
        "RAG_LLM_MODEL": local.get("RAG_LLM_MODEL", "deepseek-chat"),
        "WAVEDA_ROOT": "",
        "WAVEDA_HELP_ROOT": "wavEDA_docs/helpHtml/helpHtml",
        "WAVEDA_EXAMPLE_ROOT": "",
    }
    target.write_text(
        "\n".join(f"{key}={value}" for key, value in release_values.items()) + "\n",
        encoding="utf-8",
    )


def _validate_release(edition: str) -> None:
    required = (
        APP_DIR / f"{APP_NAME}.exe",
        APP_DIR / "data" / "index" / "chunks.json",
        APP_DIR / "data" / "index" / "vectors.npy",
        APP_DIR / "knowledge_base",
        APP_DIR / "wavEDA_docs",
        APP_DIR / "config" / ".env.example",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Release is incomplete: {missing}")
    release_env = _read_env(APP_DIR / "config" / ".env")
    if not _valid_api_key(release_env.get("RAG_LLM_API_KEY", "")):
        raise RuntimeError("The release API key is missing or still a placeholder.")
    if release_env.get("RAG_APP_EDITION") != edition:
        raise RuntimeError("The release edition marker is missing or incorrect.")
    if release_env.get("WAVEDA_ROOT") or release_env.get("WAVEDA_EXAMPLE_ROOT"):
        raise RuntimeError("Personal WavEDA folders must be empty in the release.")
    if release_env.get("WAVEDA_HELP_ROOT") != "wavEDA_docs/helpHtml/helpHtml":
        raise RuntimeError("The release help folder must use the bundled relative path.")
    if (APP_DIR / "data" / "conversations.json").exists():
        raise RuntimeError("Private conversation history must not be included in a release.")

    chunks = json.loads((APP_DIR / "data" / "index" / "chunks.json").read_text(encoding="utf-8"))
    if not chunks:
        raise RuntimeError("The packaged knowledge index is empty.")

    local = _read_env(ROOT / "config" / ".env")
    private_paths = {
        str(ROOT),
        *(
            value.strip().rstrip("\\/")
            for key in ("WAVEDA_ROOT", "WAVEDA_HELP_ROOT", "WAVEDA_EXAMPLE_ROOT")
            if (value := local.get(key, "")).strip() and Path(value.strip()).is_absolute()
        ),
    }
    private_tokens = {
        token
        for path in private_paths
        for token in (path, path.replace("\\", "/"))
        if token
    }
    leaks: list[str] = []
    for root in (APP_DIR / "knowledge_base", APP_DIR / "data", APP_DIR / "config"):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if any(token in text for token in private_tokens):
                leaks.append(str(path.relative_to(APP_DIR)))
    if leaks:
        raise RuntimeError(f"Private local paths remain in release files: {leaks[:10]}")
    print(f"Validated {len(chunks)} packaged knowledge chunks; no private settings or paths found.")


def _make_zip(edition: str) -> Path:
    edition_label = "User" if edition == "user" else "Maintainer"
    archive_base = DIST_DIR / f"{APP_NAME}_{edition_label}_Windows_{date.today():%Y%m%d}"
    archive = archive_base.with_suffix(".zip")
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", allowZip64=True) as output:
        for path in sorted(APP_DIR.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(APP_DIR)
            archive_name = (Path(ARCHIVE_ROOT) / relative).as_posix()
            compression = zipfile.ZIP_STORED if path.suffix.lower() in IMAGE_SUFFIXES else zipfile.ZIP_DEFLATED
            output.write(path, archive_name, compress_type=compression, compresslevel=6)

    with zipfile.ZipFile(archive) as check:
        bad_member = check.testzip()
        if bad_member:
            raise RuntimeError(f"ZIP CRC validation failed: {bad_member}")
        longest = max((len(name) for name in check.namelist()), default=0)
        if longest > 200:
            raise RuntimeError(f"ZIP contains an extraction-unfriendly path ({longest} characters).")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a WavEDA Assistant release.")
    parser.add_argument(
        "--edition",
        choices=("user", "maintainer"),
        default="user",
        help="user disables knowledge maintenance; maintainer enables it",
    )
    args = parser.parse_args()
    _create_windows_icon()
    _write_embedded_edition(args.edition)
    _run(sys.executable, "-B", str(ROOT / "scripts" / "build_knowledge_base.py"))
    _run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(ROOT / "packaging" / "WavEDA_Assistant.spec"),
    )
    _copy_release_files(args.edition)
    _validate_release(args.edition)
    archive = _make_zip(args.edition)
    print(f"Release edition: {args.edition}")
    print(f"\nRelease folder: {APP_DIR}")
    print(f"Release archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
