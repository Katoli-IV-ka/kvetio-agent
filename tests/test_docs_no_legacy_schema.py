from pathlib import Path


ACTIVE_DOCS = [
    Path("README.md"),
]
LEGACY = ["source_links", "analysis_notes", "analysis_note_signals", "signal_types"]


def test_active_docs_have_no_legacy_tables():
    for doc in ACTIVE_DOCS:
        text = doc.read_text(encoding="utf-8")
        for token in LEGACY:
            assert token not in text, f"{doc} still references {token}"
