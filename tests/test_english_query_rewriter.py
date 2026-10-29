import pytest

from raggg.generation.llm_client import LLMCancelledError
from raggg.i18n import TEXTS
from raggg.retrieval.english_query_rewriter import EnglishQueryRewriter


BUILTIN_KEYS = (
    "quick_q1",
    "quick_q2",
    "quick_q3",
    "welcome_example_1",
    "welcome_example_2",
    "welcome_example_3",
)


def test_all_builtin_english_questions_append_paired_chinese_text():
    rewriter = EnglishQueryRewriter()

    for key in BUILTIN_KEYS:
        rewritten = rewriter.rewrite(TEXTS[key]["en"])
        assert rewritten.startswith(TEXTS[key]["en"]), key
        assert TEXTS[key]["zh"] in rewritten, key


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How do I set a lumped port?", "集总端口"),
        ("How does a PML absorbing boundary work?", "吸收边界"),
        ("How do I configure a plane wave excitation?", "平面波"),
        ("Why is material permittivity wrong?", "相对介电常数"),
        ("How do I fix an adaptive mesh failure?", "自适应网格"),
        ("How do I export an SNP Touchstone file?", "S 参数"),
        ("How do I export far field results?", "远场"),
        ("How do I run an XML parameter sweep?", "参数扫描"),
    ],
)
def test_offline_glossary_adds_domain_terms(question, expected):
    assert expected in EnglishQueryRewriter().rewrite(question)


def test_generic_error_does_not_invent_missing_material():
    rewritten = EnglishQueryRewriter().rewrite("How do I troubleshoot an error?")

    assert "材料缺失" not in rewritten


def test_short_acronym_does_not_match_inside_an_english_word():
    rewritten = EnglishQueryRewriter().rewrite("How do I inspect far field results?")

    assert "理想电导体" not in rewritten
    assert "远场" in rewritten


def test_valid_model_rewrite_is_appended_and_cached():
    calls = []

    def translate(prompt, should_cancel):
        calls.append(prompt)
        return "波导模式 截止频率"

    rewriter = EnglishQueryRewriter(translate)

    first = rewriter.rewrite("How do I calculate waveguide cutoff?")
    second = rewriter.rewrite("How do I calculate waveguide cutoff?")

    assert "波导模式 截止频率" in first
    assert second == first
    assert len(calls) == 1


@pytest.mark.parametrize(
    "candidate",
    ["", "english only", "```中文```", "中" * 501, None, ["中文"], 123],
)
def test_invalid_model_output_is_not_appended(candidate):
    question = "How do I calculate waveguide cutoff?"
    rewritten = EnglishQueryRewriter(
        lambda prompt, should_cancel: candidate
    ).rewrite(question)

    assert rewritten == question


def test_model_failure_keeps_offline_glossary():
    def fail(prompt, should_cancel):
        raise RuntimeError("offline")

    rewritten = EnglishQueryRewriter(fail).rewrite(
        "How do I set material permittivity?"
    )

    assert "相对介电常数" in rewritten


def test_chinese_and_mixed_queries_skip_model_rewriting():
    calls = []
    rewriter = EnglishQueryRewriter(
        lambda prompt, should_cancel: calls.append(prompt) or "不应调用"
    )

    chinese = rewriter.rewrite("波端口怎么设置？")
    mixed = rewriter.rewrite("S 参数怎么 export？")

    assert chinese == "波端口怎么设置？"
    assert mixed == "S 参数怎么 export？"
    assert calls == []


def test_cancellation_is_not_swallowed():
    def cancel(prompt, should_cancel):
        raise LLMCancelledError("cancelled")

    with pytest.raises(LLMCancelledError):
        EnglishQueryRewriter(cancel).rewrite("How do I calculate cutoff?")
