"""
i18n 国际化模块 — 中/英文切换
语言偏好保存到 config/.env (RAG_LANGUAGE=zh/en)
"""
from __future__ import annotations

import os
from pathlib import Path

from raggg.config import config_env_path

# ── 当前语言（模块级缓存） ──────────────────────────────────
_current_lang: str = "zh"

TEXTS: dict[str, dict[str, str]] = {
    # ── 窗口标题 ──────────────────────────────────
    "window_title": {
        "zh": "WavEDA Knowledge Workbench",
        "en": "WavEDA Knowledge Workbench",
    },
    "settings_title": {
        "zh": "设置",
        "en": "Settings",
    },

    # ── 侧边栏 ──────────────────────────────────
    "app_subtitle": {
        "zh": "WavEDA 仿真软件知识问答助手",
        "en": "WavEDA Simulation Knowledge Assistant",
    },
    "badge_waveda_first": {
        "zh": "WavEDA 优先",
        "en": "WavEDA First",
    },
    "sidebar_status": {
        "zh": "工作台状态",
        "en": "Workspace Status",
    },
    "card_knowledge_base": {
        "zh": "知识库",
        "en": "Knowledge Base",
    },
    "card_chunks": {
        "zh": "知识块",
        "en": "Chunks",
    },
    "card_model": {
        "zh": "模型",
        "en": "Model",
    },

    # ── 按钮 ──────────────────────────────────
    "btn_reload_index": {
        "zh": "重新载入索引",
        "en": "Reload Index",
    },
    "btn_rebuild_index": {
        "zh": "重建索引",
        "en": "Rebuild Index",
    },
    "btn_api_settings": {
        "zh": "设置",
        "en": "Settings",
    },
    "btn_favorites": {
        "zh": "收藏夹",
        "en": "Favorites",
    },
    "btn_script_gen": {
        "zh": "脚本生成器",
        "en": "Script Gen",
    },
    "script_gen_title": {
        "zh": "WavEDA 自动脚本生成器",
        "en": "WavEDA Script Generator",
    },
    "script_gen_desc": {
        "zh": "在本机生成便携 ZIP，再复制到异地电脑运行。异地路径只会写入配置，本机「检查配置」不会判断这些文件是否存在。",
        "en": "Generate a portable ZIP locally, then copy to the target machine. Remote paths are only written into config; local checks will not verify remote file existence.",
    },
    "script_gen_check": {"zh": "检查配置", "en": "Check Config"},
    "script_gen_preview": {"zh": "预览压缩包清单", "en": "Preview Manifest"},
    "script_gen_generate": {"zh": "生成压缩包", "en": "Generate ZIP"},
    "script_gen_path_group": {"zh": "路径配置", "en": "Paths"},
    "script_gen_zip_path": {"zh": "本地 ZIP 保存位置：", "en": "Local ZIP path:"},
    "script_gen_zip_placeholder": {"zh": "例：C:\\Users\\me\\Desktop\\waveda_sweep.zip", "en": "e.g. C:\\Users\\me\\Desktop\\waveda_sweep.zip"},
    "script_gen_exe_path": {"zh": "异地电脑 WavEDA.exe 路径：", "en": "Target WavEDA.exe path:"},
    "script_gen_exe_placeholder": {"zh": "例：D:\\Program Files\\WavEDA\\WavEDA.exe（异地电脑路径）", "en": "e.g. D:\\Program Files\\WavEDA\\WavEDA.exe (target machine)"},
    "script_gen_tsp_path": {"zh": "异地电脑外部 .tsp 路径：", "en": "External .tsp path (target):"},
    "script_gen_tsp_placeholder": {"zh": "例：E:\\projects\\antenna.tsp（外部工程，不会打进 ZIP）", "en": "e.g. E:\\projects\\antenna.tsp (external, not bundled)"},
    "script_gen_zip_note": {"zh": "ZIP 解压到异地电脑任意目录即可；输出会写到解压目录内部，因此无需填写目标工作目录。", "en": "Unzip anywhere on the target machine; output will be written inside the extracted folder."},
    "script_gen_browse": {"zh": "选择...", "en": "Browse..."},
    "script_gen_browse_local": {"zh": "浏览本机...", "en": "Browse..."},
    "script_gen_select_exe": {"zh": "WavEDA 可执行文件 (*.exe)", "en": "WavEDA executable (*.exe)"},
    "script_gen_select_tsp": {"zh": "WavEDA 工程文件 (*.tsp)", "en": "WavEDA project (*.tsp)"},
    "script_gen_sweep_group": {"zh": "扫参变量与循环策略", "en": "Sweep Variables & Strategy"},
    "script_gen_add_var": {"zh": "+ 添加第二个变量", "en": "+ Add second variable"},
    "script_gen_strategy_label": {"zh": "循环策略：", "en": "Strategy:"},
    "script_gen_strategy_auto": {"zh": "自动外部循环（按变量数量和输入格式生成）", "en": "Auto external loop (based on variable count & format)"},
    "script_gen_strategy_custom": {"zh": "自定义效果描述", "en": "Custom description"},
    "script_gen_strategy_builtin": {"zh": "工程内置参数扫描（暂未支持）", "en": "Built-in sweep (not yet supported)"},
    "script_gen_custom_label": {"zh": "效果描述：", "en": "Description:"},
    "script_gen_custom_placeholder": {"zh": "请输入下方列出的受支持语句之一。", "en": "Enter one of the supported descriptions listed below."},
    "script_gen_custom_hint": {"zh": "当前支持：", "en": "Supported: "},
    "script_gen_custom_suffix": {"zh": "。其他描述会被拒绝，不会按普通扫描静默运行。", "en": ". Other descriptions will be rejected."},
    "script_gen_var_name": {"zh": "变量：", "en": "Variable:"},
    "script_gen_var_name_ph": {"zh": "变量名，如 length", "en": "name, e.g. length"},
    "script_gen_var_start": {"zh": "起始：", "en": "Start:"},
    "script_gen_var_stop": {"zh": "终止：", "en": "Stop:"},
    "script_gen_var_step": {"zh": "步长：", "en": "Step:"},
    "script_gen_var_values_ph": {"zh": "或填写值列表：4.5, 5.0, 5.5", "en": "or value list: 4.5, 5.0, 5.5"},
    "script_gen_result_group": {"zh": "结果配置", "en": "Result Config"},
    "script_gen_port_name": {"zh": "Port S 参数结果节点：", "en": "Port S-param node:"},
    "script_gen_port_traces": {"zh": "Port 曲线：", "en": "Port traces:"},
    "script_gen_port_traces_ph": {"zh": "例如：S11 dB, S21 dB（英文逗号分隔）", "en": "e.g. S11 dB, S21 dB (comma separated)"},
    "script_gen_obs_check": {"zh": "导出 Observer", "en": "Export Observer"},
    "script_gen_obs_name_ph": {"zh": "Observer 结果节点名称", "en": "Observer result node name"},
    "script_gen_obs_label": {"zh": "可选 Observer：", "en": "Optional Observer:"},
    "script_gen_target_freq": {"zh": "目标频率：", "en": "Target frequency:"},
    "script_gen_data_unit": {"zh": "导出数据频率单位：", "en": "Export data frequency unit:"},
    "script_gen_data_unit_auto": {"zh": "自动（从 .tsp 读取）", "en": "Auto (from .tsp)"},
    "script_gen_ctrl_group": {"zh": "控制器与可靠性", "en": "Controller & Reliability"},
    "script_gen_controller": {"zh": "主控制器：", "en": "Controller:"},
    "script_gen_ctrl_matlab": {"zh": "MATLAB（只生成 .m 控制器）", "en": "MATLAB (.m controller only)"},
    "script_gen_ctrl_python": {"zh": "Python（只生成 .py 控制器）", "en": "Python (.py controller only)"},
    "script_gen_remesh": {"zh": "几何参数变化时删除旧网格", "en": "Delete old mesh when geometry changes"},
    "script_gen_remesh_label": {"zh": "强制重建网格：", "en": "Force remesh:"},
    "script_gen_timeout": {"zh": "单点超时：", "en": "Point timeout:"},
    "script_gen_attempts": {"zh": "最大尝试次数：", "en": "Max attempts:"},
    "script_gen_resume": {"zh": "允许按任务签名断点续跑", "en": "Allow resume by task signature"},
    "script_gen_resume_label": {"zh": "断点续跑：", "en": "Resume:"},
    "script_gen_select_file": {"zh": "选择本机文件", "en": "Select local file"},
    "script_gen_select_zip": {"zh": "选择本地 ZIP 保存位置", "en": "Save ZIP as"},
    "script_gen_err_number": {"zh": "必须是数字。", "en": "must be a number."},
    "script_gen_err_values": {"zh": "第 {idx} 个变量的值列表必须用逗号分隔数字。", "en": "Variable {idx}: value list must be comma-separated numbers."},
    "script_gen_err_start": {"zh": "第 {idx} 个变量的起始值", "en": "Variable {idx} start value"},
    "script_gen_err_stop": {"zh": "第 {idx} 个变量的终止值", "en": "Variable {idx} stop value"},
    "script_gen_err_step": {"zh": "第 {idx} 个变量的步长", "en": "Variable {idx} step value"},
    "script_gen_confirm_title": {"zh": "确认生成", "en": "Confirm Generation"},
    "script_gen_confirm_msg": {"zh": "将生成 ZIP 到：\n{path}\n\n总仿真点数：{points}\n\n确认生成？", "en": "Generate ZIP to:\n{path}\n\nTotal points: {points}\n\nProceed?"},
    "script_gen_done_title": {"zh": "生成完成", "en": "Generation Complete"},
    "script_gen_done_msg": {"zh": "已生成 ZIP：\n{path}\n\n包含控制器：{ctrl}\n仿真点数：{points}\n\n复制到异地电脑并解压后，直接运行主控制器即可。", "en": "ZIP generated:\n{path}\n\nController: {ctrl}\nPoints: {points}\n\nCopy and unzip on target machine, then run the controller."},
    "script_gen_err_title": {"zh": "生成失败", "en": "Generation Failed"},
    "script_gen_preview_title": {"zh": "压缩包预览", "en": "Package Preview"},
    "btn_ask": {
        "zh": "提问",
        "en": "Ask",
    },
    "btn_stop_generation": {
        "zh": "停止生成",
        "en": "Stop generating",
    },
    "btn_back_to_sources": {
        "zh": "← 返回来源列表",
        "en": "← Back to Sources",
    },
    "btn_delete": {
        "zh": "删除",
        "en": "Delete",
    },
    "btn_copy": {
        "zh": "复制",
        "en": "Copy",
    },
    "btn_copied": {
        "zh": "已复制!",
        "en": "Copied!",
    },
    "btn_fav": {
        "zh": "收藏",
        "en": "Save",
    },
    "btn_faved": {
        "zh": "已收藏",
        "en": "Saved",
    },
    "btn_fix": {
        "zh": "纠错",
        "en": "Fix",
    },
    "fix_dialog_title": {
        "zh": "纠正回答",
        "en": "Correct Answer",
    },
    "fix_dialog_desc": {
        "zh": "请描述回答中不准确的地方，AI 将修正并存入FAQ知识库：",
        "en": "Describe what is inaccurate. The AI will correct it and save to the FAQ knowledge base:",
    },
    "fix_placeholder": {
        "zh": "例如：S参数的导出步骤应该是...",
        "en": "E.g. The correct S-parameter export steps are...",
    },
    "fix_empty": {
        "zh": "请填写修正意见。",
        "en": "Please describe the correction.",
    },
    "fix_done": {
        "zh": "修正后的 FAQ 已存入：{file}",
        "en": "Corrected FAQ saved to: {file}",
    },

    # ── 快捷问题 ──────────────────────────────────
    "quick_questions_label": {
        "zh": "快捷问题",
        "en": "Quick Questions",
    },
    "quick_q1": {
        "zh": "波端口怎么设置？",
        "en": "How to set up a wave port?",
    },
    "quick_q2": {
        "zh": "PML 和吸收边界有什么关系？",
        "en": "What is the relationship between PML and absorbing boundary?",
    },
    "quick_q3": {
        "zh": "如何设置平面波激励？",
        "en": "How to configure plane wave excitation?",
    },
    "search_note": {
        "zh": "优先检索 WavEDA 帮助文档和团队教程，理论笔记作为补充。",
        "en": "Prioritizes WavEDA help docs and team tutorials, supplemented by theory notes.",
    },

    # ── 问答区 ──────────────────────────────────
    "section_qa": {
        "zh": "问答",
        "en": "Q&A",
    },
    "status_ready": {
        "zh": "就绪",
        "en": "Ready",
    },
    "status_loading_index": {
        "zh": "正在载入",
        "en": "Loading",
    },
    "status_building": {
        "zh": "正在重建知识库",
        "en": "Rebuilding knowledge base",
    },
    "status_searching": {
        "zh": "正在检索与生成",
        "en": "Searching & generating",
    },
    "status_stopping_generation": {
        "zh": "正在停止生成",
        "en": "Stopping generation",
    },
    "generation_stopped": {
        "zh": "已停止生成",
        "en": "Generation stopped",
    },
    "kb_not_built": {
        "zh": "未构建",
        "en": "Not built",
    },
    "kb_loaded": {
        "zh": "已载入",
        "en": "Loaded",
    },
    "model_local": {
        "zh": "本地片段",
        "en": "Local snippets",
    },
    "placeholder_input": {
        "zh": "慢慢说，我听着",
        "en": "Take your time, I am listening",
    },

    # ── 监听模块 ──────────────────────────────────
    "watch_label": {
        "zh": "监听",
        "en": "Watch",
    },
    "watch_starting": {
        "zh": "启动中",
        "en": "Starting",
    },
    "watch_active": {
        "zh": "监听中",
        "en": "Watching",
    },
    "watch_changed": {
        "zh": "检测到变化",
        "en": "Changes detected",
    },
    "watch_idle": {
        "zh": "等待空闲",
        "en": "Waiting idle",
    },
    "watch_rebuilding": {
        "zh": "自动重建",
        "en": "Rebuilding",
    },
    "watch_busy_msg": {
        "zh": "知识库变化，正在自动重建",
        "en": "Knowledge base changed, auto-rebuilding",
    },
    "watch_rebuild_error": {
        "zh": "自动重建失败",
        "en": "Auto-rebuild failed",
    },
    "watch_waiting_stable": {
        "zh": "检测到知识库变化，等待文件稳定",
        "en": "Knowledge base changes detected, waiting for files to stabilize",
    },

    # ── 导入模块 ──────────────────────────────────
    "import_button": {
        "zh": "导入资料入库",
        "en": "Import Documents",
    },
    "import_tooltip": {
        "zh": "导入资料入库",
        "en": "Import documents to knowledge base",
    },
    "import_dialog_title": {
        "zh": "选择要导入的资料",
        "en": "Select documents to import",
    },
    "import_busy_msg": {
        "zh": "正在导入资料并重建知识库",
        "en": "Importing documents and rebuilding knowledge base",
    },
    "import_failed": {
        "zh": "导入失败",
        "en": "Import failed",
    },
    "import_done": {
        "zh": "导入完成",
        "en": "Import complete",
    },
    "import_result": {
        "zh": "已导入: {name}\n知识块: {count}",
        "en": "Imported: {name}\nChunks: {count}",
    },

    # ── 侧边栏 ──────────────────────────────────
    "sidebar_toggle_tooltip": {
        "zh": "显示/隐藏侧边栏",
        "en": "Show/Hide Sidebar",
    },
    "sidebar_hide_tooltip": {
        "zh": "隐藏侧边栏",
        "en": "Hide Sidebar",
    },
    "section_data_status": {
        "zh": "资料与状态",
        "en": "Data &amp; Status",
    },

    # ── 来源面板 ──────────────────────────────────
    "section_sources": {
        "zh": "来源证据",
        "en": "Source Evidence",
    },
    "sources_subtitle": {
        "zh": "按相关性排序，帮助文档和团队教程优先",
        "en": "Sorted by relevance, help docs & team tutorials first",
    },
    "sources_empty": {
        "zh": "提出问题后，这里会显示可追溯的来源证据。",
        "en": "After asking a question, traceable source evidence will appear here.",
    },
    "sources_not_built": {
        "zh": "知识库尚未构建。",
        "en": "Knowledge base not yet built.",
    },
    "source_file_not_found": {
        "zh": "源文件未找到",
        "en": "Source file not found",
    },
    "source_viewer_title": {
        "zh": "源文档查看",
        "en": "Source Viewer",
    },
    "source_viewer_preview": {
        "zh": "预览",
        "en": "Preview",
    },
    "source_viewer_edit": {
        "zh": "编辑",
        "en": "Edit",
    },
    "source_viewer_save": {
        "zh": "保存",
        "en": "Save",
    },
    "source_viewer_path_label": {
        "zh": "关联路径：",
        "en": "File path:",
    },
    "source_viewer_no_path": {
        "zh": "未关联本地文件，仅支持预览",
        "en": "No local file is linked; preview only",
    },
    "source_viewer_no_path_warning": {
        "zh": "无法保存：未关联本地文件路径。",
        "en": "Cannot save because no local file path is linked.",
    },
    "source_viewer_save_failed": {
        "zh": "保存失败",
        "en": "Save failed",
    },
    "source_viewer_external_change_title": {
        "zh": "文件已在外部修改",
        "en": "File changed externally",
    },
    "source_viewer_external_change_message": {
        "zh": "该文件在打开后被其他程序修改。是否覆盖外部更改？",
        "en": "This file changed after it was opened. Overwrite the external changes?",
    },
    "source_viewer_unsaved_title": {
        "zh": "存在未保存的修改",
        "en": "Unsaved changes",
    },
    "source_viewer_unsaved_message": {
        "zh": "关闭前是否保存对源文档的修改？",
        "en": "Save the source-document changes before closing?",
    },
    "btn_close": {
        "zh": "关闭",
        "en": "Close",
    },
    "you_label": {
        "zh": "你",
        "en": "You",
    },

    # ── 来源标签 ──────────────────────────────────
    "badge_waveda_help": {
        "zh": "WavEDA 帮助",
        "en": "WavEDA Help",
    },
    "badge_team_tutorial": {
        "zh": "团队教程",
        "en": "Team Tutorial",
    },
    "badge_theory_notes": {
        "zh": "理论笔记",
        "en": "Theory Notes",
    },

    # ── 来源匹配度 ──────────────────────────────────
    "match_score": {
        "zh": "匹配度",
        "en": "Match",
    },

    # ── 图片/截图 ──────────────────────────────────
    "screenshot_label": {
        "zh": "操作截图",
        "en": "Screenshots",
    },

    # ── 启动页 ──────────────────────────────────
    "startup_brand_subtitle": {
        "zh": "WavEDA 仿真软件知识问答助手",
        "en": "WavEDA Simulation Knowledge Assistant",
    },
    "startup_chunks_label": {
        "zh": "知识块",
        "en": "Chunks",
    },
    "startup_strategy_label": {
        "zh": "检索策略",
        "en": "Strategy",
    },
    "startup_llm_label": {
        "zh": "大模型",
        "en": "LLM",
    },
    "startup_hint": {
        "zh": "在下方输入 WavEDA 相关问题开始",
        "en": "Enter a WavEDA question below to get started",
    },
    "welcome_title": {
        "zh": "您好！我是 WavEDA 仿真软件助手",
        "en": "Hello! I am your WavEDA simulation assistant",
    },
    "welcome_intro": {
        "zh": "我可以根据官方帮助、团队教程和错误案例，为您解答建模操作、仿真设置、错误排查和结果后处理等问题。",
        "en": "I can use the official help, team tutorials, and error cases to answer questions about modeling, simulation settings, troubleshooting, and result post-processing.",
    },
    "welcome_detail": {
        "zh": "请直接描述您正在做什么、卡在哪一步，或贴出具体报错。我会尽量给出简洁、可操作的步骤，并附上相关资料来源。",
        "en": "Describe what you are doing, where you are stuck, or provide the exact error. I will give concise, actionable steps with relevant sources.",
    },

    # 人格欢迎语 — 每个风格三句
    "welcome_title_mature": {
        "zh": "你好～我是你的仿真专属顾问，叫我姐姐就好。",
        "en": "Hello there～ I'm your simulation consultant. You can call me sis.",
    },
    "welcome_intro_mature": {
        "zh": "WavEDA 的事儿我门儿清。从建模到后处理，有什么搞不定的尽管说，我帮你把问题理清楚。",
        "en": "I know WavEDA inside out. From modeling to post-processing, just tell me what's giving you trouble and I'll sort it out.",
    },
    "welcome_detail_mature": {
        "zh": "别慌，说重点——你在做什么、卡在哪、报什么错。我会给你最干练的解决方案～",
        "en": "Don't panic — just tell me what you're doing, where you're stuck, and the error. I'll give you the cleanest solution～",
    },
    "welcome_title_sweet": {
        "zh": "嗨嗨～我是你的小助手呀！超开心见到你哦！",
        "en": "Hiiii～ I'm your little helper! So happy to see you!",
    },
    "welcome_intro_sweet": {
        "zh": "WavEDA 仿真软件的问题都可以问我呢！建模、仿真、报错排查我都能帮你看看哦～我会认真帮你找到答案的！",
        "en": "You can ask me anything about WavEDA! Modeling, simulation, troubleshooting — I'll help you figure it all out with lots of care!",
    },
    "welcome_detail_sweet": {
        "zh": "遇到什么困难啦？告诉我你在做什么、卡在哪里了，或者直接把报错发给我呀～我会给你最贴心的解答！",
        "en": "What troubles are you having? Tell me what you're doing, where you're stuck, or just send the error message～ I'll give you the sweetest answer!",
    },
    "welcome_title_dog": {
        "zh": "汪汪！主人好！我是你的仿真小助手金毛！",
        "en": "Woof woof! Hello master! I'm your Golden Retriever simulation assistant!",
    },
    "welcome_intro_dog": {
        "zh": "汪！不管建模、仿真还是报错，交给我来帮你找答案！官方文档、团队教程我全都翻遍了！",
        "en": "Woof! Modeling, simulation, or errors — leave it all to me! I've dug through every doc and tutorial for you!",
    },
    "welcome_detail_dog": {
        "zh": "主人遇到什么麻烦了？告诉我你在干啥、卡在哪、报什么错！我马上摇着尾巴帮你解决汪汪！！",
        "en": "What troubles you, master? Tell me what you're doing, where you're stuck, and the error! I'll solve it with my tail wagging WOOF!!",
    },
    "welcome_title_cat": {
        "zh": "喵。本喵是 WavEDA 助手。",
        "en": "Meow. I'm the WavEDA assistant cat.",
    },
    "welcome_intro_cat": {
        "zh": "建模、仿真、报错……本喵确实都懂。虽然懒得解释太多，但既然你问了，我就勉为其难帮你看看吧。",
        "en": "Modeling, simulation, errors... yes, I do know them all. I won't explain more than necessary, but since you asked... fine, I'll help. Meow.",
    },
    "welcome_detail_cat": {
        "zh": "说吧，什么事。最好说清楚点，不然本喵懒得猜。",
        "en": "Go on, tell me. Be clear about it — I don't guess.",
    },
    "welcome_title_workhorse": {
        "zh": "来嘞来嘞～俺是 WavEDA 助手老黄牛，有啥活儿尽管吩咐！",
        "en": "Here I come～ I'm old ox, your WavEDA helper. Give me any work you got!",
    },
    "welcome_intro_workhorse": {
        "zh": "建模、仿真、排错这些活儿俺都干过不少，官方文档俺也翻得烂熟。不懂的俺帮你看，难搞的俺埋头给你查。",
        "en": "Modeling, simulation, troubleshooting — I've done plenty of it all and know the docs by heart. If you don't know, I'll look it up. If it's tough, I'll dig for you.",
    },
    "welcome_detail_workhorse": {
        "zh": "你说说看——在做什么、卡哪了、报了啥错？别客气，俺慢慢给你捋清楚。",
        "en": "Tell me — what you're doing, where you're stuck, what error. Don't be shy, I'll sort it all out for you.",
    },
    "welcome_examples_title": {
        "zh": "例如，您可以这样问：",
        "en": "For example, you can ask:",
    },
    "welcome_example_1": {
        "zh": "波端口怎么设置，为什么预览方向要朝外？",
        "en": "How do I configure a wave port, and why should its preview direction point outward?",
    },
    "welcome_example_2": {
        "zh": "仿真提示材料未设置，应该怎么排查？",
        "en": "How should I troubleshoot a missing-material simulation error?",
    },
    "welcome_example_3": {
        "zh": "如何导出 S 参数，或者找到工程生成的 snp 文件？",
        "en": "How do I export S-parameters or find the generated SNP file?",
    },
    "welcome_click_hint": {
        "zh": "点击示例即可开始提问",
        "en": "Click an example to start",
    },

    # ── 错误/提示消息 ──────────────────────────────────
    "error_rebuild_title": {
        "zh": "重建失败",
        "en": "Rebuild Failed",
    },
    "error_no_kb_title": {
        "zh": "未载入知识库",
        "en": "Knowledge Base Not Loaded",
    },
    "error_no_kb_msg": {
        "zh": "请先重建或载入知识库。",
        "en": "Please rebuild or load the knowledge base first.",
    },
    "msg_generation_failed": {
        "zh": "生成失败：",
        "en": "Generation failed: ",
    },
    "msg_favorites_empty": {
        "zh": "还没有收藏任何问答。",
        "en": "No saved Q&A yet.",
    },
    "msg_api_saved": {
        "zh": "设置已更新，重启应用后生效。",
        "en": "Settings updated. Restart the app for changes to take effect.",
    },

    # ── 设置：人格 Tab ──────────────────────────────────
    "settings_personality_tab": {
        "zh": "人格",
        "en": "Personality",
    },
    "settings_personality_label": {
        "zh": "助手风格",
        "en": "Assistant Style",
    },
    "settings_personality_desc": {
        "zh": "选择 AI 助手的语气风格，重启应用后生效。",
        "en": "Choose your AI assistant's tone. Restart the app to take effect.",
    },
    "personality_normal": {
        "zh": "默认 — 专业简洁",
        "en": "Default — Professional & Concise",
    },
    "personality_mature": {
        "zh": "御姐风 — 成熟稳重",
        "en": "Mature — Elegant & Experienced",
    },
    "personality_sweet": {
        "zh": "甜妹风 — 活泼可爱",
        "en": "Sweet — Cheerful & Cute",
    },
    "personality_dog": {
        "zh": "小狗风 — 忠诚热情",
        "en": "Puppy — Loyal & Enthusiastic",
    },
    "personality_cat": {
        "zh": "小猫风 — 高冷傲娇",
        "en": "Kitty — Aloof & Tsundere",
    },
    "personality_workhorse": {
        "zh": "牛马风 — 任劳任怨",
        "en": "Workhorse — Humble & Hardworking",
    },

    # ── 设置：个性化 Tab ──────────────────────────────────
    "settings_personalization_tab": {
        "zh": "个性化",
        "en": "Personalization",
    },

    # ── 设置：主题 Tab ──────────────────────────────────
    "settings_theme_tab": {
        "zh": "主题",
        "en": "Theme",
    },
    "settings_theme_label": {
        "zh": "界面主题",
        "en": "Interface Theme",
    },
    "settings_theme_desc": {
        "zh": "切换主题后需要重启应用生效。",
        "en": "Restart the app after changing theme for it to take effect.",
    },
    "settings_theme_light": {
        "zh": "浅色",
        "en": "Light",
    },
    "settings_theme_dark": {
        "zh": "深色",
        "en": "Dark",
    },

    # ── 设置：API Tab ──────────────────────────────────
    "settings_api_tab": {
        "zh": "API 设置",
        "en": "API",
    },
    "settings_api_desc": {
        "zh": "选择大模型提供商，输入你的 API Key 即可。\nBase URL 和模型名称会自动填写。",
        "en": "Select your LLM provider and enter your API Key.\nBase URL and model name will be filled automatically.",
    },
    "settings_api_provider": {
        "zh": "大模型",
        "en": "Provider",
    },
    "settings_api_key": {
        "zh": "API Key",
        "en": "API Key",
    },
    "settings_edition_label": {
        "zh": "当前发行模式",
        "en": "Current edition",
    },
    "settings_edition_maintainer": {
        "zh": "知识库维护版",
        "en": "Knowledge Maintainer",
    },
    "settings_edition_user": {
        "zh": "用户版",
        "en": "User",
    },
    "kb_update_tab": {
        "zh": "知识库更新",
        "en": "Knowledge Update",
    },
    "kb_update_title": {
        "zh": "安装测试组发布的知识库",
        "en": "Install an official knowledge package",
    },
    "kb_update_desc": {
        "zh": "用户版不能编辑或重建知识库，只能安装经过完整性校验的 .wkb 更新包。",
        "en": "The user edition cannot edit or rebuild the knowledge base. It only installs validated .wkb packages.",
    },
    "kb_update_current": {
        "zh": "当前知识库版本",
        "en": "Current knowledge version",
    },
    "kb_update_install": {
        "zh": "选择并安装更新包",
        "en": "Select and install package",
    },
    "kb_update_backup_hint": {
        "zh": "安装前会自动备份当前知识库和索引，最多保留最近 3 个版本。",
        "en": "The current knowledge base and index are backed up before installation; the latest three backups are kept.",
    },
    "kb_update_select": {
        "zh": "选择知识库更新包",
        "en": "Select knowledge package",
    },
    "kb_update_invalid": {
        "zh": "更新包无效",
        "en": "Invalid package",
    },
    "kb_update_version": {
        "zh": "版本",
        "en": "Version",
    },
    "kb_update_files": {
        "zh": "文件数量",
        "en": "Files",
    },
    "kb_update_confirm": {
        "zh": "确认安装并替换当前知识库吗？",
        "en": "Install this package and replace the current knowledge base?",
    },
    "kb_update_failed": {
        "zh": "安装失败",
        "en": "Installation failed",
    },
    "kb_update_done": {
        "zh": "安装完成",
        "en": "Installation complete",
    },
    "kb_update_done_msg": {
        "zh": "知识库与索引已更新，新的问答将立即使用该版本。",
        "en": "The knowledge base and index have been updated. New questions will use this version immediately.",
    },

    # ── 设置：WavEDA 路径 Tab ─────────────────────────
    "settings_waveda_paths_tab": {
        "zh": "WavEDA 路径",
        "en": "WavEDA Paths",
    },
    "settings_waveda_paths_desc": {
        "zh": "只需选择本机 WavEDA 安装根目录。程序会自动查找帮助文档、说明配图和 Example 案例图片；未找到本机帮助目录时使用项目内置资料。",
        "en": "Select the local WavEDA install root. The app automatically finds help pages, help images, and Example images; bundled help is used when no local help folder is found.",
    },
    "settings_waveda_root": {
        "zh": "WavEDA 安装根目录",
        "en": "WavEDA install root",
    },
    "settings_waveda_help_root": {
        "zh": "帮助文档与配图目录",
        "en": "Help pages and images",
    },
    "settings_waveda_example_root": {
        "zh": "案例与案例图片目录",
        "en": "Examples and images",
    },
    "settings_waveda_auto_paths": {
        "zh": "自动识别帮助文档和案例目录（推荐）",
        "en": "Detect help and Example folders automatically (recommended)",
    },
    "settings_browse": {
        "zh": "浏览…",
        "en": "Browse…",
    },
    "settings_select_waveda_root": {
        "zh": "选择 WavEDA 安装根目录",
        "en": "Select the WavEDA install root",
    },
    "settings_select_folder": {
        "zh": "选择目录",
        "en": "Select folder",
    },
    "settings_waveda_paths_hint": {
        "zh": "示例：D:\\Program Files\\WavEDA。自动模式下，下方两个识别结果会置灰且无需填写；安装结构特殊时可取消自动识别后手动指定。保存并重启后生效。",
        "en": "Example: D:\\Program Files\\WavEDA. In automatic mode the two detected paths are read-only; disable automatic detection only for a non-standard install layout. Restart after saving.",
    },

    # ── 设置：语言 Tab ──────────────────────────────────
    "settings_lang_tab": {
        "zh": "语言",
        "en": "Language",
    },
    "settings_lang_label": {
        "zh": "界面语言",
        "en": "Interface Language",
    },
    "settings_lang_desc": {
        "zh": "切换语言后需要重启应用生效。",
        "en": "Restart the app after changing language for it to take effect.",
    },
    "settings_lang_zh": {
        "zh": "中文",
        "en": "Chinese",
    },
    "settings_lang_en": {
        "zh": "English",
        "en": "English",
    },

}

from raggg.i18n_kb import TEXTS_KB
from raggg.i18n_prompt import TEXTS_PROMPT
TEXTS.update(TEXTS_KB)
TEXTS.update(TEXTS_PROMPT)


def get_text(key: str, lang: str | None = None) -> str:
    """获取翻译文本"""
    if lang is None:
        lang = get_language()
    entry = TEXTS.get(key, {})
    return entry.get(lang, entry.get("zh", key))


def get_welcome_text(key: str) -> str:
    """获取人格感知的欢迎语，fallback 到默认"""
    try:
        from raggg.generation.personality import get_personality
        personality = get_personality()
    except Exception:
        personality = "normal"
    if personality != "normal":
        styled_key = f"{key}_{personality}"
        if styled_key in TEXTS:
            lang = get_language()
            entry = TEXTS[styled_key]
            return entry.get(lang, entry.get("zh", key))
    return get_text(key)


def get_language() -> str:
    """获取当前语言设置"""
    global _current_lang
    return _current_lang


def set_language(lang: str) -> None:
    """设置语言 (zh/en) 并持久化"""
    global _current_lang
    _current_lang = lang
    _save_language(lang)


def _language_env_path() -> Path:
    """config/.env 路径"""
    return config_env_path()


def _load_language() -> str:
    """从 config/.env 加载语言设置"""
    env_path = _language_env_path()
    if not env_path.exists():
        return "zh"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("RAG_LANGUAGE="):
            lang = line.split("=", 1)[1].strip().strip('"').strip("'")
            if lang in ("zh", "en"):
                return lang
    return "zh"


def _save_language(lang: str) -> None:
    """保存语言设置到 config/.env"""
    env_path = _language_env_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    found = False
    for line in lines:
        if line.startswith("RAG_LANGUAGE="):
            new_lines.append(f"RAG_LANGUAGE={lang}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"RAG_LANGUAGE={lang}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── 模块导入时自动加载语言 ──────────────────────────
_current_lang = _load_language()
