"""
document_processor.py

Pure PDF structure extraction utilities for pdf_podcast.py.
No LLM calls — uses PyMuPDF only.
"""

import fitz  # PyMuPDF

# Characters above this threshold trigger sub-chunking for a chapter.
# ~100k chars ≈ 200 dense academic pages — well above any normal thesis chapter.
SUBCHUNK_THRESHOLD = 100_000


def get_pdf_metadata(pdf_path: str) -> dict:
    """
    Extract basic metadata from a PDF.

    Returns:
        total_pages: int
        toc: list of [level, title, page_0idx]   (0-indexed page numbers)
        first_pages_text: str  (first 20 pages, capped at 8000 chars for LLM use)
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    # PyMuPDF returns 1-based page numbers in the TOC; convert to 0-indexed.
    raw_toc = doc.get_toc()
    toc = [[level, title, max(0, page - 1)] for level, title, page in raw_toc]

    first_pages_text = ""
    for i in range(min(20, total_pages)):
        first_pages_text += doc[i].get_text()

    doc.close()

    return {
        "total_pages": total_pages,
        "toc": toc,
        "first_pages_text": first_pages_text[:8000],
    }


def extract_text(pdf_path: str, start_page: int = 0, end_page: int = None) -> str:
    """
    Extract text from a page range (0-indexed, end_page exclusive).
    If end_page is None, extracts to end of document.
    """
    doc = fitz.open(pdf_path)
    if end_page is None:
        end_page = len(doc)

    text = ""
    for i in range(start_page, min(end_page, len(doc))):
        text += doc[i].get_text()

    doc.close()
    return text


def chapters_from_toc(toc: list, total_pages: int) -> list:
    """
    Build a chapter list from level-1 TOC entries.

    All page numbers are 0-indexed, and end_page is exclusive
    (i.e. the first page of the next chapter, or total_pages for the last).

    Returns list of dicts: {title, start_page, end_page}
    Returns empty list if fewer than 2 top-level entries are found.
    """
    top_level = [(title, page) for level, title, page in toc if level == 1]

    if len(top_level) < 2:
        return []

    chapters = []
    for i, (title, start) in enumerate(top_level):
        end = top_level[i + 1][1] if i + 1 < len(top_level) else total_pages
        chapters.append({
            "title": title,
            "start_page": start,
            "end_page": end,
        })

    return chapters


def subchunk_chapter(pdf_path: str, chapter: dict, toc: list, total_pages: int) -> list:
    """
    Split a long chapter into sub-chunks.

    First attempts to use level-2 TOC entries within the chapter's page range.
    Falls back to splitting into thirds by page count.

    Returns list of {title, start_page, end_page} dicts.
    All page numbers are 0-indexed, end_page exclusive.
    """
    start = chapter["start_page"]
    end = chapter["end_page"]

    # Try level-2 TOC entries within this chapter's range
    sub_entries = [
        (title, page)
        for level, title, page in toc
        if level == 2 and start <= page < end
    ]

    if len(sub_entries) >= 2:
        chunks = []
        for i, (title, sub_start) in enumerate(sub_entries):
            sub_end = sub_entries[i + 1][1] if i + 1 < len(sub_entries) else end
            chunks.append({
                "title": f"{chapter['title']} — {title}",
                "start_page": sub_start,
                "end_page": sub_end,
            })
        return chunks

    # Fallback: thirds by page count
    chapter_pages = end - start
    third = max(1, chapter_pages // 3)

    return [
        {"title": f"{chapter['title']} (Part 1)", "start_page": start,           "end_page": start + third},
        {"title": f"{chapter['title']} (Part 2)", "start_page": start + third,   "end_page": start + 2 * third},
        {"title": f"{chapter['title']} (Part 3)", "start_page": start + 2 * third, "end_page": end},
    ]
