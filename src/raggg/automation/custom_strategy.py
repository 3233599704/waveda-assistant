"""Controlled natural-language mappings for custom sweep strategies."""

from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_CUSTOM_DESCRIPTIONS = (
    "先粗扫再细扫",
    "coarse-to-fine",
    "只运行固定扫描",
    "fixed scan only",
)


class UnsupportedCustomStrategyError(ValueError):
    """Raised when custom text does not map to an executable strategy."""


@dataclass(frozen=True, slots=True)
class CustomStrategy:
    mode: str

    @property
    def is_adaptive(self) -> bool:
        return self.mode == "adaptive_coarse_to_fine"


def parse_custom_strategy(description: str) -> CustomStrategy:
    """Parse a deliberately small set of executable custom descriptions."""

    text = str(description).strip()
    if not text:
        raise UnsupportedCustomStrategyError("自定义策略描述不能为空。")

    normalized = text.casefold()
    exact_modes = {
        "先粗扫再细扫": "adaptive_coarse_to_fine",
        "coarse-to-fine": "adaptive_coarse_to_fine",
        "只运行固定扫描": "fixed_scan",
        "fixed scan only": "fixed_scan",
    }
    if normalized in exact_modes:
        return CustomStrategy(exact_modes[normalized])

    supported = "、".join(SUPPORTED_CUSTOM_DESCRIPTIONS)
    raise UnsupportedCustomStrategyError(
        f"不支持的自定义策略。当前支持：{supported}。"
    )
