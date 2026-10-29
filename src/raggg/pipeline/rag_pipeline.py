from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from raggg.config import Settings
from raggg.generation.llm_client import (
    LLMAuthError,
    LLMCancelledError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    OpenAICompatibleClient,
)
from raggg.generation.prompt_builder import (
    build_casual_prompt,
    build_english_repair_prompt,
    build_local_answer,
    build_local_casual_answer,
    build_prompt,
)
from raggg.i18n import get_language, get_text
from raggg.indexing.semantic_embeddings import create_embedding_model
from raggg.indexing.vector_store import VectorStore
from raggg.retrieval.english_query_rewriter import (
    EnglishQueryRewriter,
    is_english_technical_query,
)
from raggg.retrieval.retriever import Retriever, SearchResult
from raggg.text_language import HAN_RE, contains_han

ConversationHistory = list[tuple[str, str]]
MAX_RETRIEVAL_HISTORY_QUESTIONS = 3

HISTORY_RECALL_ACTIONS = (
    "回到",
    "恢复",
    "回溯",
    "返回",
    "复制",
    "复述",
    "重复",
    "原样",
    "再发",
    "重新发",
    "是什么",
    "go back",
    "repeat",
    "copy",
    "what was",
)
OPENING_HISTORY_REFERENCES = (
    "第一次",
    "第一轮",
    "最初",
    "一开始",
    "开头",
    "first turn",
    "first question",
    "first answer",
)

# 追问信号：指代词/承上启下的说法。命中才认为当前问题依赖上文（A5）
FOLLOWUP_HINTS = (
    "那",
    "这个",
    "这种",
    "这里",
    "这次",
    "这样",
    "那个",
    "那种",
    "那里",
    "上面",
    "刚才",
    "接着",
    "继续",
    "还有",
    "它",
)

CASUAL_HINTS = (
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "在吗",
    "姐妹",
    "谢谢",
    "感谢",
    "再见",
    "拜拜",
    "早安",
    "晚安",
    "哈哈",
    "笑死",
)
TECHNICAL_HINTS = (
    "waveda",
    "仿真",
    "端口",
    "网格",
    "边界",
    "材料",
    "求解",
    "模型",
    "s参数",
    "频率",
    "波导",
    "电磁",
    "热",
    "脚本",
    "报错",
    "错误",
    "导入",
    "导出",
    "设置",
    "pml",
    "pec",
    "pmc",
    "abc",
    "ibc",
    "sib",
    "sibc",
    "scbc",
    "rcld",
    "snp",
    "step",
    "iges",
    "gerber",
    "dxf",
)
QUESTION_HINTS = (
    "怎么",
    "如何",
    "为什么",
    "什么",
    "哪里",
    "多少",
    "是否",
    "能否",
    "可以",
    "请问",
    "?",
    "？",
)

@dataclass(frozen=True)
class RAGAnswer:
    question: str
    answer: str
    sources: list[SearchResult]
    warning: str | None = None
    cancelled: bool = False


class RAGPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = VectorStore.load(
            settings.data_dir / "index",
            embedding_model=create_embedding_model(settings.embedding_model),
        )
        self.retriever = Retriever(self.store)
        self.client = OpenAICompatibleClient(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
        )
        model_rewrite = None
        if self.client.is_configured:
            model_rewrite = lambda prompt, should_cancel: self.client.complete(
                prompt,
                timeout=20,
                should_cancel=should_cancel,
            )
        self.query_rewriter = EnglishQueryRewriter(model_rewrite)

    def ask(
        self,
        question: str,
        top_k: int = 8,
        conversation_history: ConversationHistory | None = None,
        on_chunk: Callable[[str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        additional_context: str | None = None,
    ) -> RAGAnswer:
        history = conversation_history or []
        recalled = self._recall_opening_turn(question, history)
        if recalled is not None:
            if on_chunk is not None:
                on_chunk(recalled)
            return RAGAnswer(question=question, answer=recalled, sources=[])

        normalized_additional_context = (
            additional_context.strip() if additional_context else ""
        )
        has_additional_context = bool(normalized_additional_context)
        answer_language = self._detect_answer_language(question)
        is_casual = (
            self._is_casual_message(question) and not has_additional_context
        )
        base_query = self._build_retrieval_query(question, history)
        try:
            retrieval_query = self.query_rewriter.rewrite(
                base_query,
                should_cancel=should_cancel,
            )
        except LLMCancelledError:
            return RAGAnswer(
                question=question,
                answer="",
                sources=[],
                cancelled=True,
            )
        sources = self.retriever.search(
            retrieval_query,
            top_k=top_k,
        )
        sources = self._filter_by_bm25_floor(
            sources, self.settings.retrieval_min_score
        )
        if is_casual and not sources:
            prompt = build_casual_prompt(
                question,
                conversation_history=history,
                language=answer_language,
            )
            fallback_answer = build_local_casual_answer(answer_language)
        elif not sources and not has_additional_context:
            # 专业问题无可靠命中时明说"没找到"，不让模型凭参数知识编造答案。
            answer = build_local_answer(
                question,
                sources,
                language=answer_language,
            )
            if on_chunk is not None:
                on_chunk(answer)
            return RAGAnswer(question=question, answer=answer, sources=sources)
        else:
            prompt = build_prompt(
                question,
                sources,
                conversation_history=history,
                language=answer_language,
                additional_context=normalized_additional_context or None,
            )
            fallback_answer = build_local_answer(
                question,
                sources,
                language=answer_language,
            )
        warning = None
        cancelled = False
        if self.client.is_configured:
            if on_chunk is not None:
                answer, warning = self._complete_streaming(
                    prompt,
                    question,
                    sources,
                    on_chunk,
                    should_cancel=should_cancel,
                    fallback_answer=fallback_answer,
                    language=answer_language,
                )
                cancelled = bool(should_cancel and should_cancel())
            else:
                try:
                    answer = self.client.complete(prompt, should_cancel=should_cancel)
                    answer = self._enforce_answer_language(
                        answer,
                        language=answer_language,
                        should_cancel=should_cancel,
                        fallback_answer=fallback_answer,
                    )
                except LLMCancelledError:
                    answer = ""
                    cancelled = True
                except Exception as exc:
                    answer = fallback_answer
                    warning = self._friendly_llm_warning(
                        exc,
                        language=answer_language,
                    )
        else:
            answer = fallback_answer
            if on_chunk is not None:
                on_chunk(answer)
        return RAGAnswer(
            question=question,
            answer=answer,
            sources=sources,
            warning=warning,
            cancelled=cancelled,
        )

    def _complete_streaming(
        self,
        prompt: str,
        question: str,
        sources: list[SearchResult],
        on_chunk: Callable[[str], None],
        should_cancel: Callable[[], bool] | None = None,
        fallback_answer: str | None = None,
        language: str | None = None,
    ) -> tuple[str, str | None]:
        parts: list[str] = []
        english_stream = language == "en"
        stream_is_safe = True
        try:
            for chunk in self.client.complete_stream(prompt, should_cancel=should_cancel):
                parts.append(chunk)
                if english_stream and stream_is_safe:
                    first_han = HAN_RE.search(chunk)
                    safe_prefix = (
                        chunk if first_han is None else chunk[: first_han.start()]
                    )
                    if safe_prefix:
                        on_chunk(safe_prefix)
                    if first_han is not None:
                        stream_is_safe = False
                elif not english_stream:
                    on_chunk(chunk)
                if should_cancel is not None and should_cancel():
                    raise LLMCancelledError("Generation cancelled.")
            if not parts:
                raise RuntimeError("The model returned an empty streaming response.")
            answer = self._enforce_answer_language(
                "".join(parts),
                language=language,
                should_cancel=should_cancel,
                fallback_answer=fallback_answer or "",
            )
            return answer, None
        except LLMCancelledError:
            return ("" if english_stream else "".join(parts)), None
        except RuntimeError as stream_error:
            if parts:
                answer = self._enforce_answer_language(
                    "".join(parts),
                    language=language,
                    should_cancel=should_cancel,
                    fallback_answer=fallback_answer or "",
                )
                return answer, self._friendly_llm_warning(
                    stream_error,
                    language=language,
                )

            try:
                answer = self.client.complete(prompt, should_cancel=should_cancel)
                answer = self._enforce_answer_language(
                    answer,
                    language=language,
                    should_cancel=should_cancel,
                    fallback_answer=fallback_answer or "",
                )
                on_chunk(answer)
                return answer, None
            except LLMCancelledError:
                return "".join(parts), None
            except Exception as fallback_error:
                answer = fallback_answer or build_local_answer(
                    question,
                    sources,
                    language=language,
                )
                on_chunk(answer)
                return answer, self._friendly_llm_warning(
                    fallback_error,
                    language=language,
                )

    def _enforce_answer_language(
        self,
        answer: str,
        language: str | None,
        should_cancel: Callable[[], bool] | None,
        fallback_answer: str,
    ) -> str:
        if language != "en" or not contains_han(answer):
            return answer
        try:
            repair_result = self.client.complete(
                build_english_repair_prompt(answer),
                timeout=20,
                should_cancel=should_cancel,
            )
        except LLMCancelledError:
            raise
        except Exception:
            return fallback_answer
        repaired = repair_result.strip() if isinstance(repair_result, str) else ""
        if repaired and not contains_han(repaired):
            return repaired
        return fallback_answer

    def cancel_active_request(self) -> None:
        self.client.cancel_active_request()

    @staticmethod
    def _recall_opening_turn(
        question: str,
        conversation_history: ConversationHistory,
    ) -> str | None:
        """Return an exact opening question/answer for explicit recall requests."""
        if not conversation_history:
            return None

        normalized = " ".join(question.casefold().strip().split())
        if not any(action in normalized for action in HISTORY_RECALL_ACTIONS):
            return None
        if not any(
            reference in normalized for reference in OPENING_HISTORY_REFERENCES
        ):
            return None

        opening_question, opening_answer = conversation_history[0]
        asks_for_question_text = (
            any(token in normalized for token in ("提问", "问题", "question"))
            and any(
                token in normalized
                for token in ("是什么", "复述", "复制", "原样", "what was", "repeat", "copy")
            )
            and not any(
                token in normalized
                for token in ("回答", "回复", "答案", "设定", "要求", "answer")
            )
            and not any(token in normalized for token in ("回到", "恢复", "go back"))
        )
        recalled = opening_question if asks_for_question_text else opening_answer
        recalled = recalled.strip()
        return recalled or None

    @staticmethod
    def _is_casual_message(question: str) -> bool:
        normalized = " ".join(question.casefold().strip().split())
        if not normalized:
            return False
        if normalized in {"hi", "hello", "hey", "hhh", "lol", "thanks", "thank you"}:
            return True
        if set(normalized) <= {"哈", "h", "a", " ", "~", "!", "！"}:
            return True
        if any(hint in normalized for hint in TECHNICAL_HINTS):
            return False
        if is_english_technical_query(normalized):
            return False
        if normalized.startswith("s") and normalized[1:].isdigit():
            return False
        if any(hint in normalized for hint in CASUAL_HINTS):
            return True
        return len(normalized) <= 12 and not any(
            hint in normalized for hint in QUESTION_HINTS
        )

    @staticmethod
    def _filter_by_bm25_floor(
        sources: list[SearchResult], min_score: float
    ) -> list[SearchResult]:
        """A6 分数门槛：按 BM25 原始分过滤不可靠命中。

        混合分/min-max 归一化分会被"每查询必有最优文档"的地板效应抬高，
        只有 BM25 原始分（稀有词 IDF 求和）能区分"真命中"和"词表完全不沾边"。
        阈值标定（2026-07，41+3 题）：in-scope 最低 34.8，out-of-scope 最高 33.5，
        默认取保守值 20——只拦最明显的无关问题，real 问题留足 40% 余量。
        """
        if min_score <= 0:
            return sources
        return [s for s in sources if s.bm25_raw >= min_score]

    @staticmethod
    def _build_retrieval_query(question: str, conversation_history: ConversationHistory) -> str:
        # 只有追问（指代上文或极短）才带最近几条问题一起检索；
        # 否则历史问题会污染检索向量，把新话题带偏（A5）
        if not conversation_history:
            return question
        stripped = question.strip()
        is_followup = len(stripped) <= 6 or any(
            hint in stripped for hint in FOLLOWUP_HINTS
        )
        if not is_followup:
            return question
        previous_questions: list[str] = []
        seen: set[str] = set()
        for previous, _answer in reversed(conversation_history):
            compact = " ".join(previous.split()).strip()
            if not compact or compact in seen:
                continue
            seen.add(compact)
            previous_questions.append(compact[:300])
            if len(previous_questions) >= MAX_RETRIEVAL_HISTORY_QUESTIONS:
                break
        previous_questions.reverse()
        return "\n".join([*previous_questions, question])

    @staticmethod
    def _detect_answer_language(question: str) -> str:
        if contains_han(question):
            return "zh"
        if re.search(r"[A-Za-z]", question):
            return "en"
        return get_language()

    @staticmethod
    def _friendly_llm_warning(
        error: Exception,
        language: str | None = None,
    ) -> str:
        if isinstance(error, LLMAuthError):
            return get_text("error_llm_auth", language)
        if isinstance(error, LLMRateLimitError):
            return get_text("error_llm_rate_limit", language)
        if isinstance(error, LLMServerError):
            return get_text("error_llm_server", language)
        if isinstance(error, LLMTimeoutError):
            return get_text("error_llm_timeout", language)
        if isinstance(error, LLMConnectionError):
            return get_text("error_llm_connection", language)
        return get_text("error_llm_unavailable", language)
