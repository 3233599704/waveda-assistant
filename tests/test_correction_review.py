from __future__ import annotations

from pathlib import Path

from raggg.desktop.correction_review import _remove_approved_entry, _write_approved_entry


def test_approved_correction_can_be_removed_without_touching_other_content(tmp_path: Path) -> None:
    faq = tmp_path / "knowledge_base" / "01_team_tutorials" / "02_常见问题FAQ.md"
    faq.parent.mkdir(parents=True)
    faq.write_text("# FAQ\n\nExisting answer.\n", encoding="utf-8")
    item = {"question": "How?"}

    _write_approved_entry(tmp_path, item, "Q: How?\nA: Like this.")

    assert item["correction_id"]
    assert _remove_approved_entry(tmp_path, item)
    assert faq.read_text(encoding="utf-8") == "# FAQ\n\nExisting answer.\n"


def test_legacy_history_without_marker_is_not_removed(tmp_path: Path) -> None:
    faq = tmp_path / "knowledge_base" / "01_team_tutorials" / "02_常见问题FAQ.md"
    faq.parent.mkdir(parents=True)
    faq.write_text("# FAQ\n", encoding="utf-8")

    assert not _remove_approved_entry(tmp_path, {"question": "legacy"})
    assert faq.read_text(encoding="utf-8") == "# FAQ\n"
