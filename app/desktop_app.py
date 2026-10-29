from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("RAGGG_PORTABLE_ROOT", str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if importlib.util.find_spec("PySide6") is None and VENV_PYTHON.exists():
    current = Path(sys.executable).resolve()
    target = VENV_PYTHON.resolve()
    if current != target:
        os.execv(str(target), [str(target), *sys.argv])

from raggg.desktop.main_window import run_desktop_app


def _offer_desktop_shortcut() -> None:
    """第一次启动 EXE 时询问是否创建桌面快捷方式（用 Windows 原生弹窗，不依赖 PySide6）"""
    if not getattr(sys, "frozen", False):
        return

    shortcut_path = Path.home() / "Desktop" / "WavEDA 仿真助手.lnk"
    if shortcut_path.exists():
        return

    import ctypes
    reply = ctypes.windll.user32.MessageBoxW(
        0,
        "是否在桌面创建「WavEDA 仿真助手」快捷方式？\n\n以后双击桌面图标即可快速启动。",
        "创建快捷方式",
        4,  # 4 = Yes/No
    )
    if reply != 6:  # 6 = Yes
        return

    import subprocess
    exe_path = str(Path(sys.executable).resolve())
    work_dir = str(ROOT.resolve())
    lnk_path = str(shortcut_path.resolve())
    ps_cmd = (
        f"$s = (New-Object -COM WScript.Shell).CreateShortcut('{lnk_path}');"
        f"$s.TargetPath = '{exe_path}';"
        f"$s.WorkingDirectory = '{work_dir}';"
        f"$s.IconLocation = '{exe_path}';"
        f"$s.Description = 'WavEDA 仿真助手';"
        f"$s.Save()"
    )
    subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True)


def _check_env_config() -> None:
    """启动时检查 config/.env 是否存在，缺失则弹出修复指引"""
    import json
    env_path = ROOT / "config" / ".env"
    example_path = ROOT / "config" / ".env.example"

    # .env 存在且内容正常 → 通过
    if env_path.exists():
        try:
            content = env_path.read_text(encoding="utf-8")
            if content.strip():
                return  # 一切正常
        except Exception:
            pass  # 损坏了，继续走修复逻辑

    # ── 以下：.env 缺失或损坏 ──
    if getattr(sys, "frozen", False):
        # EXE 版用 Windows 弹窗
        import ctypes
        msg = (
            "配置文件 config\\.env 缺失或损坏。\n\n"
            "解决方法：\n"
            "1. 右键软件目录下的 config\\.env.example\n"
        )
        if example_path.exists():
            msg += "2. 复制它并重命名为 config\\.env\n"
            msg += "3. 打开 config\\.env，填入你的 API Key\n"
        else:
            msg += "2. 在 config\\ 文件夹里新建 .env 文件\n"
            msg += "3. 写入：\n"
            msg += "   RAG_LLM_BASE_URL=https://api.deepseek.com\n"
            msg += "   RAG_LLM_API_KEY=你的Key\n"
            msg += "   RAG_LLM_MODEL=deepseek-chat\n"
        msg += "\n不配 API Key 也可以使用本地检索模式。"
        ctypes.windll.user32.MessageBoxW(0, msg, "配置文件缺失", 0)
    else:
        # 开发版用控制台提示
        print("\n" + "=" * 50)
        print("  config\\.env 缺失或损坏")
        print("=" * 50)
        if example_path.exists():
            print(f"  请复制 {example_path} 为 {env_path}")
            print(f"  然后编辑 {env_path}，填入你的 API Key")
        else:
            print(f"  请在 {env_path} 中新建文件并写入：")
            print("    RAG_LLM_BASE_URL=https://api.deepseek.com")
            print("    RAG_LLM_API_KEY=你的Key")
            print("    RAG_LLM_MODEL=deepseek-chat")
        print("\n  不配 API Key 也可以使用本地检索模式。")
        print("=" * 50 + "\n")


if __name__ == "__main__":
    _offer_desktop_shortcut()
    _check_env_config()
    raise SystemExit(run_desktop_app())
