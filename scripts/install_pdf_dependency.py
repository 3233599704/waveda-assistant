from __future__ import annotations

import importlib.util
import json
import sys
import urllib.request
import zipfile
from pathlib import Path


PYPI_JSON_URL = "https://pypi.org/pypi/pypdf/json"


def _site_packages_dir() -> Path:
    for item in sys.path:
        path = Path(item)
        if path.name == "site-packages":
            path.mkdir(parents=True, exist_ok=True)
            return path
    raise RuntimeError("Cannot locate site-packages on sys.path.")


def _download_wheel_url() -> str:
    with urllib.request.urlopen(PYPI_JSON_URL, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    version = payload["info"]["version"]
    for file_info in payload["releases"][version]:
        filename = file_info.get("filename", "")
        if filename.endswith("py3-none-any.whl"):
            return file_info["url"]
    raise RuntimeError(f"Cannot find a pure Python pypdf wheel for version {version}.")


def _safe_extract_wheel(wheel_path: Path, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    with zipfile.ZipFile(wheel_path) as archive:
        for member in archive.infolist():
            destination = (target_dir / member.filename).resolve()
            if not str(destination).startswith(str(target_root)):
                raise RuntimeError(f"Unsafe wheel member path: {member.filename}")
            archive.extract(member, target_dir)


def main() -> int:
    if importlib.util.find_spec("pypdf") is not None:
        print("pypdf already installed.")
        return 0

    target_dir = _site_packages_dir()
    wheel_url = _download_wheel_url()
    wheel_path = Path.cwd() / ".tmp" / Path(wheel_url).name
    wheel_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {wheel_url}")
    urllib.request.urlretrieve(wheel_url, wheel_path)
    _safe_extract_wheel(wheel_path, target_dir)
    if importlib.util.find_spec("pypdf") is None:
        raise RuntimeError("pypdf installation finished but import still fails.")
    print(f"Installed pypdf into {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
