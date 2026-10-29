"""Backward-compatible imports for the modular automation generator.

New code should import these APIs from :mod:`raggg.automation`.
"""

from raggg.automation import (
    PackageBuildError,
    ScriptPackage,
    ValidationIssue,
    build_task_config,
    task_signature,
    validate_generation_config,
)

__all__ = [
    "PackageBuildError",
    "ScriptPackage",
    "ValidationIssue",
    "build_task_config",
    "task_signature",
    "validate_generation_config",
]
