"""Known unresolved markers used by WavEDA automation templates."""

from __future__ import annotations

TEMPLATE_SENTINELS = frozenset(
    {
        "$EXPORT_COMMANDS",
        "$FIRST_VALUE",
        "$GEN_TIME",
        "$OBS_INIT",
        "$OBS_LOAD",
        "$OBS_PANEL",
        "$OBS_PLOT_OVERLAY",
        "$OBS_PLOT_SINGLE",
        "$OBS_PRINT",
        "$TSP_PATH",
        "$TSP_VAR_NAME",
        "$USER_CONFIG",
        "$USER_CONFIG_PY",
        "<PROJECT_FILE>",
        "{{RESULT_NAME}}",
        "<<<CONFIG_END>>>",
        "<<<CONFIG_START>>>",
        "<<<VARIABLE_NAME>>>",
        "${WAVEDA_EXE}",
    }
)


def find_template_sentinel(text: str | None) -> str | None:
    if not text:
        return None
    return next(
        (
            sentinel
            for sentinel in sorted(TEMPLATE_SENTINELS, key=len, reverse=True)
            if sentinel in text
        ),
        None,
    )
