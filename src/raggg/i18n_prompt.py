"""Prompt / LLM 翻译词条"""
from __future__ import annotations

TEXTS_PROMPT: dict[str, dict[str, str]] = {
    # ── Prompt 模板 ──────────────────────────────────
    "prompt_role": {
        "zh": "你是一个中文 RAG 助手，帮助用户解决 WavEDA 仿真软件的使用问题。",
        "en": "You are an English RAG assistant. Help users solve problems with WavEDA simulation software.",
    },
    "prompt_casual_role": {
        "zh": "用户正在寒暄、闲聊，或输入了含义较简略的内容。请自然、友好、简短地回应；对夸奖直接自然地接受，不要解释自己闻不到、看不到等能力限制。如果含义不清，询问用户想聊什么或需要什么帮助。不要使用表情符号，不要声称引用了资料，不要添加来源编号。",
        "en": "The user is greeting you, chatting casually, or sent an unclear short message. Reply naturally, warmly, and briefly. Accept compliments naturally without explaining sensory or other capability limitations. If the meaning is unclear, ask what they would like to discuss or need help with. Do not use emoji, claim to cite references, or add source numbers.",
    },
    "prompt_context_label": {
        "zh": "资料",
        "en": "Reference",
    },
    "prompt_attachment_context_label": {
        "zh": "用户提供的附件内容",
        "en": "User-provided attachment context",
    },
    "prompt_context_instruction": {
        "zh": "请优先使用资料中的内容回答，资料不足时用自己的知识补充。",
        "en": "Prioritize content from the references. Supplement with your own knowledge when references are insufficient.",
    },
    "prompt_history_label": {
        "zh": "最近对话",
        "en": "Recent conversation",
    },
    "prompt_early_memory_label": {
        "zh": "早期会话记忆",
        "en": "Earlier conversation memory",
    },
    "prompt_early_memory_instruction": {
        "zh": "这部分是较早对话的压缩记忆，用于保留用户目标、条件和已确认结论；若与当前问题或最新对话冲突，以最新内容为准。",
        "en": "This is compressed memory from earlier turns, retained for goals, constraints, and confirmed conclusions. If it conflicts with the current question or recent conversation, prefer the latest information.",
    },
    "prompt_history_instruction": {
        "zh": "如果当前问题使用了“这个、它、上一步、下一步、刚才”等指代，请结合最近对话理解用户真实意图；但事实依据仍以资料为准。",
        "en": "If the current question uses references such as this, it, previous step, next step, or just now, use the recent conversation to understand the intent; factual grounding should still come from the references.",
    },
    "prompt_history_user": {
        "zh": "用户",
        "en": "User",
    },
    "prompt_history_assistant": {
        "zh": "助手",
        "en": "Assistant",
    },
    "prompt_no_context": {
        "zh": "（知识库中暂无相关文档）\n\n请用自己的知识回答这个问题，给出简洁、可操作的建议。",
        "en": "(No relevant documents found in the knowledge base)\n\nPlease answer this question using your own knowledge. Give concise, actionable advice.",
    },
    "prompt_question_prefix": {
        "zh": "问题",
        "en": "Question",
    },
    "prompt_final_instruction": {
        "zh": "请给出简洁、可操作的回答，如果引用了资料请标注来源。",
        "en": (
            "Give concise, actionable answers. Cite sources when referencing "
            "materials. Write the entire final answer in English. Translate "
            "all Chinese source wording, interface labels, buttons, and menu "
            "names into English; do not copy any Chinese characters."
        ),
    },
    "prompt_citation_instruction": {
        "zh": (
            "引用规则：凡是由检索资料支持的事实，请在对应句末标注来源编号，如 [1]；"
            "多个来源连续写成 [1][2]。只能使用上方实际存在的编号，不得编造；"
            "没有资料支持的内容不要添加引用。"
        ),
        "en": (
            "Citation rules: Mark facts supported by retrieved references with "
            "the source number at the end of the sentence, for example [1]. "
            "Write multiple sources as [1][2]. Use only source numbers that "
            "actually appear above; never invent citations. Do not add a "
            "citation to unsupported content."
        ),
    },

    # ── 本地答案模板 ──────────────────────────────────
    "local_answer_title": {
        "zh": "根据当前知识库，先给出可确认的信息。",
        "en": "Based on the current knowledge base, here is what can be confirmed.",
    },
    "local_answer_points": {
        "zh": "要点",
        "en": "Key Points",
    },
    "local_answer_sources": {
        "zh": "引用来源",
        "en": "Sources",
    },
    "local_answer_no_sources": {
        "zh": "资料中没有足够依据回答这个问题。",
        "en": "Insufficient evidence in the knowledge base to answer this question.",
    },
    "local_casual_answer": {
        "zh": "你好！我是 WavEDA 仿真助手。想聊聊天，或者有建模、仿真设置和错误排查方面的问题，都可以直接告诉我。",
        "en": "Hello! I am the WavEDA simulation assistant. Feel free to chat or ask me about modeling, simulation settings, and troubleshooting.",
    },

    # ── LLM 错误 ──────────────────────────────────
    "error_llm_auth": {
        "zh": "API Key 无效或已过期，请打开设置检查并更新。已使用本地知识库回答。",
        "en": "Invalid or expired API Key. Please check your settings. Using local knowledge base.",
    },
    "error_llm_rate_limit": {
        "zh": "API 额度用尽或请求太频繁，请稍后重试或检查余额。已使用本地知识库回答。",
        "en": "API quota exhausted or rate limited. Please retry later or check your balance. Using local knowledge base.",
    },
    "error_llm_server": {
        "zh": "模型服务暂时不可用，请稍后重试。已使用本地知识库回答。",
        "en": "Model service temporarily unavailable. Please retry later. Using local knowledge base.",
    },
    "error_llm_timeout": {
        "zh": "请求超时（已自动重试），请检查网络或切换模型。已使用本地知识库回答。",
        "en": "Request timed out (auto-retried). Please check your network or switch models. Using local knowledge base.",
    },
    "error_llm_connection": {
        "zh": "网络连接失败，请检查网络或 API 地址。已使用本地知识库回答。",
        "en": "Network connection failed. Please check your network or API address. Using local knowledge base.",
    },
    "error_llm_unavailable": {
        "zh": "模型暂不可用，已使用本地知识库回答。",
        "en": "LLM temporarily unavailable. Using local knowledge base.",
    },

    # ── 收藏夹对话框 ──────────────────────────────────
    "favorites_title": {
        "zh": "收藏夹",
        "en": "Favorites",
    },
    "favorites_saved": {
        "zh": "已收藏",
        "en": "Saved",
    },
}
