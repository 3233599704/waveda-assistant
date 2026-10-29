from __future__ import annotations

import re
from collections.abc import Callable

from raggg.generation.llm_client import LLMCancelledError
from raggg.i18n import TEXTS
from raggg.text_language import contains_han


CancellationCheck = Callable[[], bool]
ModelRewrite = Callable[[str, CancellationCheck | None], object]

BUILTIN_KEYS = (
    "quick_q1",
    "quick_q2",
    "quick_q3",
    "welcome_example_1",
    "welcome_example_2",
    "welcome_example_3",
)
BUILTIN_QUESTION_MAP = {
    " ".join(TEXTS[key]["en"].casefold().split()): TEXTS[key]["zh"]
    for key in BUILTIN_KEYS
}
DOMAIN_GLOSSARY = (
    (("wave port",), "波端口 设置 端口方向"),
    (("lumped port",), "集总端口 设置"),
    (("plane wave",), "平面波 激励 设置"),
    (("pml",), "PML 完美匹配层 吸收边界"),
    (("absorbing boundary",), "吸收边界 边界条件"),
    (("pec",), "PEC 理想电导体 边界"),
    (("pmc",), "PMC 理想磁导体 边界"),
    (("impedance boundary",), "阻抗边界 材料 电导率"),
    (
        ("missing material", "missing-material"),
        "材料缺失 材料赋值 仿真错误 求解失败 错误排查指南",
    ),
    (("permittivity",), "相对介电常数 材料"),
    (("permeability",), "相对磁导率 材料"),
    (("conductivity",), "电导率 材料"),
    (("loss tangent",), "损耗角正切 材料"),
    (("dispersion", "dispersive"), "色散材料 频率"),
    (("adaptive mesh",), "自适应网格 网格失败"),
    (("mesh", "meshing"), "网格 划分"),
    (("solver", "convergence"), "求解器 收敛 仿真"),
    (("license",), "license 许可 仿真失败"),
    (
        (
            "s-parameter",
            "s-parameters",
            "s parameter",
            "s parameters",
            "snp",
            "touchstone",
        ),
        "S 参数 导出 SNP Touchstone 文件",
    ),
    (("far field",), "远场 结果 导出"),
    (("near field",), "近场 场结果"),
    (("observer",), "接收器 Observer 结果"),
    (("snapshot",), "快照 结果"),
    (("domain",), "计算区域 Domain"),
    (("geometry",), "几何 建模"),
    (("parameter sweep", "sweep"), "参数扫描 扫参"),
    (("xml",), "XML 脚本 自动化"),
    (("matlab",), "MATLAB 脚本 自动化"),
    (("python",), "Python 脚本 自动化"),
)
LATIN_RE = re.compile(r"[A-Za-z]")


def build_rewrite_prompt(query: str) -> str:
    return (
        "Rewrite the following English WavEDA question as a concise Chinese "
        "retrieval query. Return only Chinese search text and necessary "
        "technical identifiers such as PML, S11, SNP, XML, MATLAB, filenames, "
        "or exact error strings. Do not answer the question. Do not explain, "
        "use Markdown, or invent software steps.\n\n"
        f"Question: {query}"
    )


def validate_model_rewrite(candidate: object) -> str:
    if not isinstance(candidate, str):
        return ""
    compact = " ".join(candidate.strip().split())
    if (
        not compact
        or len(compact) > 500
        or "```" in compact
        or not contains_han(compact)
    ):
        return ""
    return compact


def append_unique_lines(query: str, additions: list[str]) -> str:
    unique = []
    for addition in additions:
        compact = " ".join(addition.split())
        if not compact or compact in query or compact in unique:
            continue
        unique.append(compact)
    if not unique:
        return query
    return f"{query}\n{' '.join(unique)}"


def phrase_matches(trigger: str, normalized_query: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(trigger)}(?![a-z0-9])"
    return re.search(pattern, normalized_query) is not None


def is_english_technical_query(query: str) -> bool:
    if contains_han(query) or LATIN_RE.search(query) is None:
        return False
    normalized = " ".join(query.casefold().split())
    return any(
        phrase_matches(trigger, normalized)
        for triggers, _text in DOMAIN_GLOSSARY
        for trigger in triggers
    )


class EnglishQueryRewriter:
    def __init__(self, model_rewrite: ModelRewrite | None = None) -> None:
        self._model_rewrite = model_rewrite
        self._cache: dict[str, str] = {}

    def rewrite(
        self,
        query: str,
        should_cancel: CancellationCheck | None = None,
    ) -> str:
        if contains_han(query) or LATIN_RE.search(query) is None:
            return query

        normalized = " ".join(query.casefold().split())
        additions: list[str] = []
        exact = BUILTIN_QUESTION_MAP.get(normalized)
        if exact:
            additions.append(exact)

        for triggers, text in DOMAIN_GLOSSARY:
            if any(phrase_matches(trigger, normalized) for trigger in triggers):
                additions.append(text)

        if not exact and self._model_rewrite is not None:
            cached = self._cache.get(normalized)
            if cached is None:
                try:
                    candidate = self._model_rewrite(
                        build_rewrite_prompt(query),
                        should_cancel,
                    )
                except LLMCancelledError:
                    raise
                except Exception:
                    candidate = ""
                cached = validate_model_rewrite(candidate)
                if cached:
                    self._cache[normalized] = cached
            if cached:
                additions.append(cached)

        return append_unique_lines(query, additions)
