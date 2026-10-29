from __future__ import annotations

from unittest.mock import patch

from scripts.build_exe_release import _portable_text, _valid_api_key


def test_release_rejects_empty_and_placeholder_api_keys() -> None:
    assert not _valid_api_key("")
    assert not _valid_api_key("YOUR_API_KEY_HERE")
    assert not _valid_api_key(" change_me ")
    assert _valid_api_key("test-real-looking-key")


def test_release_text_rewrites_known_private_waveda_paths() -> None:
    text = (
        r"Z:\Company\WavEDA\documentation\helpHtml\EM_Project\Boundary.html"
        "\n"
        r"Z:\Company\WavEDA\Example\EM\Antenna"
    )

    with patch(
        "scripts.build_exe_release._read_env",
        return_value={
            "WAVEDA_ROOT": r"Z:\Company\WavEDA",
            "WAVEDA_HELP_ROOT": r"Z:\Company\WavEDA\documentation\helpHtml",
            "WAVEDA_EXAMPLE_ROOT": r"Z:\Company\WavEDA\Example",
        },
    ):
        portable = _portable_text(text)

    assert "Z:\\Company" not in portable
    assert r"wavEDA_docs\helpHtml\helpHtml\EM_Project\Boundary.html" in portable
    assert r"Example\EM\Antenna" in portable
