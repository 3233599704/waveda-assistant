from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.config import load_settings
from raggg.pipeline.builder import build_knowledge_base


def main() -> int:
    report = build_knowledge_base(load_settings())
    print(f"documents={report.document_count}")
    print(f"waveda_documents={report.waveda_document_count}")
    print(f"obsidian_documents={report.obsidian_document_count}")
    print(f"chunks={report.chunk_count}")
    print(f"rebuilt_documents={report.rebuilt_document_count}")
    print(f"reused_documents={report.reused_document_count}")
    print(f"embedded_chunks={report.embedded_chunk_count}")
    print(f"data_dir={report.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
