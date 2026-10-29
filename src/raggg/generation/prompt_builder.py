from __future__ import annotations

import re

from raggg.generation.personality import get_personality_prompt
from raggg.i18n import get_text, get_language
from raggg.retrieval.retriever import SearchResult
from raggg.text_language import contains_han


ConversationHistory = list[tuple[str, str]]
MAX_CONTEXT_TURNS = 20
MAX_CONTEXT_CHARS = 14_000
MAX_EARLY_MEMORY_CHARS = 2_400


def build_prompt(
    question: str,
    sources: list[SearchResult],
    conversation_history: ConversationHistory | None = None,
    language: str | None = None,
    additional_context: str | None = None,
) -> str:
    lang = language or get_language()
    colon = ":" if lang == "en" else "："
    snippets = []
    for index, result in enumerate(sources, start=1):
        chunk = result.chunk
        snippets.append(
            f"[{index}] {chunk.title} | {chunk.source_type} | {chunk.relative_path}\n"
            f"{chunk.content[:900]}"
        )
    joined = "\n\n".join(snippets)
    if joined.strip():
        context = (
            f"{get_text('prompt_context_label', lang)}{colon}\n{joined}\n\n"
            f"{get_text('prompt_context_instruction', lang)}"
        )
    else:
        context = get_text("prompt_no_context", lang)
    early_memory, history = _format_conversation_context(
        conversation_history or [],
        language=lang,
    )
    history_section = ""
    if early_memory:
        history_section += (
            f"{get_text('prompt_early_memory_label', lang)}{colon}\n"
            f"{early_memory}\n\n"
            f"{get_text('prompt_early_memory_instruction', lang)}\n\n"
        )
    if history:
        history_section += (
            f"{get_text('prompt_history_label', lang)}{colon}\n{history}\n\n"
            f"{get_text('prompt_history_instruction', lang)}\n\n"
        )
    attachment_section = ""
    if additional_context and additional_context.strip():
        attachment_section = (
            f"{get_text('prompt_attachment_context_label', lang)}{colon}\n"
            f"{additional_context.strip()}\n\n"
        )
    return (
        f"{get_personality_prompt(lang)}\n\n"
        f"{get_text('prompt_role', lang)}\n\n"
        f"{history_section}"
        f"{attachment_section}"
        f"{get_text('prompt_question_prefix', lang)}{colon}{question}\n\n"
        f"{context}\n\n"
        f"{get_text('prompt_final_instruction', lang)}\n\n"
        f"{get_text('prompt_citation_instruction', lang)}"
    )


def build_casual_prompt(
    question: str,
    conversation_history: ConversationHistory | None = None,
    language: str | None = None,
) -> str:
    lang = language or get_language()
    colon = ":" if lang == "en" else "："
    early_memory, history = _format_conversation_context(
        conversation_history or [],
        language=lang,
    )
    history_section = ""
    if early_memory:
        history_section += (
            f"{get_text('prompt_early_memory_label', lang)}{colon}\n"
            f"{early_memory}\n\n"
        )
    if history:
        history_section += (
            f"{get_text('prompt_history_label', lang)}{colon}\n{history}\n\n"
        )
    return (
        f"{get_personality_prompt(lang)}\n\n"
        f"{get_text('prompt_casual_role', lang)}\n\n"
        f"{history_section}"
        f"{get_text('prompt_question_prefix', lang)}{colon}{question}"
    )


def build_local_answer(
    question: str,
    sources: list[SearchResult],
    language: str | None = None,
) -> str:
    lang = language or get_language()
    if not sources:
        return get_text("local_answer_no_sources", lang)
    top = sources[:3]
    colon = ":" if lang == "en" else "："
    lines = [
        get_text("local_answer_title", lang),
        "",
        f"{get_text('local_answer_points', lang)}{colon}",
    ]
    for index, result in enumerate(top, start=1):
        chunk = result.chunk
        title = chunk.title
        snippet = _source_snippet(chunk.title, chunk.content)
        if lang == "en":
            if contains_han(title):
                title = f"Source {index}"
            if contains_han(snippet):
                snippet = "Relevant WavEDA documentation was found for this question."
        lines.append(f"- [{index}] {title}{colon}{snippet}")
    lines.append("")
    lines.append(f"{get_text('local_answer_sources', lang)}{colon}")
    for index, result in enumerate(top, start=1):
        chunk = result.chunk
        title = chunk.title
        relative_path = chunk.relative_path
        if lang == "en":
            if contains_han(title):
                title = f"Source {index}"
            if contains_han(relative_path):
                relative_path = "Knowledge base"
        lines.append(f"[{index}] {title} | {chunk.source_type} | {relative_path}")
    return "\n".join(lines)


def build_local_casual_answer(language: str | None = None) -> str:
    return get_text("local_casual_answer", language)


def build_english_repair_prompt(answer: str) -> str:
    return (
        "Rewrite the answer below entirely in English. Translate every Chinese "
        "word, menu label, button label, filename description, and explanatory "
        "phrase into natural English. Preserve Markdown structure, technical "
        "identifiers, file extensions, and citation markers such as [1][2]. "
        "Return only the corrected answer. The result must contain no Chinese "
        "characters.\n\n"
        f"Answer:\n{answer}"
    )


def _format_conversation_context(
    history: ConversationHistory,
    max_turns: int = MAX_CONTEXT_TURNS,
    max_chars: int = MAX_CONTEXT_CHARS,
    language: str | None = None,
) -> tuple[str, str]:
    """Return bounded early memory plus a contiguous recent-history suffix."""
    if not history or max_turns <= 0 or max_chars <= 0:
        return "", ""

    lang = language or get_language()
    selected: list[tuple[str, str]] = []
    used_chars = 0
    for question, answer in reversed(history[-max_turns:]):
        safe_question = _compact_text(question, 300)
        safe_answer = _compact_text(answer, 700)
        estimated = len(safe_question) + len(safe_answer) + 32
        if selected and used_chars + estimated > max_chars:
            break
        selected.append((safe_question, safe_answer))
        used_chars += estimated

    selected.reverse()
    recent_lines = _format_history_blocks(selected, language=lang)
    early_count = len(history) - len(selected)
    early_memory = _format_early_memory(history[:early_count], language=lang)
    return early_memory, recent_lines


def _format_conversation_history(
    history: ConversationHistory,
    max_turns: int = MAX_CONTEXT_TURNS,
    language: str | None = None,
) -> str:
    """Backward-compatible helper returning only the recent context section."""
    return _format_conversation_context(
        history,
        max_turns=max_turns,
        language=language,
    )[1]


def _format_history_blocks(
    history: ConversationHistory,
    language: str | None = None,
) -> str:
    lang = language or get_language()
    colon = ":" if lang == "en" else "："
    lines = []
    for index, (question, answer) in enumerate(history, start=1):
        if question:
            lines.append(
                f"[{index}] {get_text('prompt_history_user', lang)}"
                f"{colon}{question}"
            )
        if answer:
            lines.append(
                f"[{index}] {get_text('prompt_history_assistant', lang)}"
                f"{colon}{answer}"
            )
    return "\n".join(lines)


def _format_early_memory(
    history: ConversationHistory,
    language: str | None = None,
) -> str:
    if not history:
        return ""

    # Preserve the opening goal/constraints, then use the remaining budget for
    # the most recent conclusions immediately before the verbatim context.
    preferred_indices = list(range(min(3, len(history))))
    preferred_indices.extend(range(len(history) - 1, 2, -1))
    selected: dict[int, tuple[str, str]] = {}
    used_chars = 0
    for index in preferred_indices:
        if index in selected:
            continue
        question, answer = history[index]
        compact_pair = (
            _compact_text(question, 180),
            _compact_text(answer, 260),
        )
        estimated = len(compact_pair[0]) + len(compact_pair[1]) + 32
        if selected and used_chars + estimated > MAX_EARLY_MEMORY_CHARS:
            continue
        selected[index] = compact_pair
        used_chars += estimated

    ordered = [selected[index] for index in sorted(selected)]
    return _format_history_blocks(ordered, language=language)


def _compact_text(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip(" ，。；、,.") + "..."


def _source_snippet(title: str, content: str, limit: int = 180) -> str:
    snippet = re.sub(r"\s+", " ", content).strip()
    prefix_tokens = (title, "WavEDA")
    changed = True
    while changed:
        changed = False
        for token in prefix_tokens:
            trimmed = _strip_heading_token(snippet, token)
            if trimmed != snippet:
                snippet = trimmed
                changed = True
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit].rstrip(" ，。；、") + "..."


def _strip_heading_token(text: str, token: str) -> str:
    if not token or not text.startswith(token):
        return text
    rest = text[len(token) :]
    if rest and rest[0] not in " \t\r\n：:-|":
        return text
    return rest.strip(" ：:-|")
