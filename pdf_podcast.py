"""
pdf_podcast.py

Generates a podcast episode from a local PDF — paper, thesis, or textbook.

Short documents (< 30 pages, or no chapter structure) get a single-pass script.
Chaptered documents get a hierarchical treatment:
  Phase 0 — structure detection   (Haiku)
  Phase 1 — chapter summaries     (Haiku, parallel)
  Phase 2 — chapter scripts       (Sonnet, sequential — each sees all other summaries)
  Phase 3 — intro script          (Sonnet, generated last with full context)
  Phase 4 — TTS + stitch          (OpenAI TTS + ffmpeg)

Usage:
    python pdf_podcast.py /path/to/document.pdf
    python pdf_podcast.py /path/to/document.pdf --minutes 30
    python pdf_podcast.py /path/to/document.pdf --presenter NICO
    python pdf_podcast.py /path/to/document.pdf --script-only
    python pdf_podcast.py /path/to/document.pdf --from-script doc_script.json
    python pdf_podcast.py   # uses PDF_PODCAST_PATH from .env

PDF path is never committed — pass as CLI arg or store in .env as PDF_PODCAST_PATH.
"""

import os
import json
import random
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from document_processor import (
    get_pdf_metadata,
    extract_text,
    chapters_from_toc,
    subchunk_chapter,
    SUBCHUNK_THRESHOLD,
)
from podcast_generator import generate_audio  # reuse existing TTS + ffmpeg pipeline

load_dotenv()

# ─── Models ───────────────────────────────────────────────────────────────────

HAIKU_MODEL  = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"

WORDS_PER_MINUTE = 130
INTRO_MINUTES    = 2.0

# Weight multipliers by chapter type when allocating podcast time
TYPE_WEIGHTS = {
    "background": 0.75,
    "methods":    0.75,
    "core":       1.5,
    "conclusion": 1.0,
}

# ─── Presenter / Questioner roles ─────────────────────────────────────────────

def make_role_block(presenter: str) -> str:
    """Return the character descriptions for the current episode's presenter/questioner."""
    questioner = "VENA" if presenter == "NICO" else "NICO"

    if presenter == "NICO":
        return (
            "- NICO (presenter): Has just read this section carefully and is explaining it.\n"
            "  Enthusiastic, makes lateral connections across the document. Gets excited about\n"
            "  clever or surprising ideas. Aims to make the material genuinely understandable.\n"
            f"- VENA (questioner): Hearing about this section for the first time.\n"
            "  Precise, asks probing questions, won't accept vague hand-waving.\n"
            "  Occasionally skeptical — pushes NICO to justify claims with evidence."
        )
    else:
        return (
            "- VENA (presenter): Has just read this section carefully and is explaining it.\n"
            "  Methodical and precise; flags caveats before delivering conclusions.\n"
            "  Dry wit; doesn't oversell. Builds explanations systematically.\n"
            f"- NICO (questioner): Hearing about this section for the first time.\n"
            "  Rapid-fire questions, speculative leaps that Vena sometimes has to rein in.\n"
            "  Pushes hard for the 'so what?' behind every claim."
        )


def choose_presenter(presenter_arg: str | None) -> str:
    """Return the presenter name: forced if specified, random otherwise."""
    if presenter_arg:
        return presenter_arg.upper()
    return random.choice(["NICO", "VENA"])


# ─── Phase 0: Structure Detection ─────────────────────────────────────────────

_STRUCTURE_PROMPT = """\
Analyze this document and return JSON describing its structure.

The document has {total_pages} pages.

Table of Contents (from PDF metadata):
{toc_str}

First pages text (up to 8000 characters):
{first_pages_text}

Return JSON with this exact structure:
{{
  "doc_type": "paper" or "chaptered",
  "title": "full document title",
  "topic_overview": "2-3 sentences describing the document's subject and significance",
  "chapter_types": [
    {{"index": 0, "chapter_type": "background"}},
    {{"index": 1, "chapter_type": "methods"}},
    ...
  ]
}}

Rules:
- doc_type "paper"    → fewer than 30 pages, OR no chapter structure in the TOC
- doc_type "chaptered" → 30+ pages with clear named chapters or sections

chapter_type values (assign one per TOC chapter, in order):
  "background"  — introduction, motivation, literature review, related work
  "methods"     — theory, methodology, experimental setup, technical framework
  "core"        — main results, contributions, findings, analysis, experiments
  "conclusion"  — conclusion, discussion, future work, summary

chapter_types must have one entry per level-1 TOC chapter listed above (by index, 0-based).
If doc_type is "paper", return an empty chapter_types list.

Return only valid JSON, no markdown fences."""


def detect_structure(metadata: dict, toc_chapters: list, client) -> dict:
    """
    Use Haiku to classify the document and assign chapter types.
    Merges Haiku's chapter_type classifications back onto the PyMuPDF chapter list.
    """
    toc = metadata["toc"]
    total_pages = metadata["total_pages"]

    toc_str = "\n".join(
        f"{'  ' * (level - 1)}{title} (page {page + 1})"
        for level, title, page in toc
    ) if toc else "(No table of contents found in PDF)"

    prompt = _STRUCTURE_PROMPT.format(
        total_pages=total_pages,
        toc_str=toc_str,
        first_pages_text=metadata["first_pages_text"],
    )

    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    # Merge chapter_type annotations onto the PyMuPDF-derived chapter list
    if result["doc_type"] == "chaptered" and toc_chapters:
        type_by_index = {
            entry["index"]: entry.get("chapter_type", "core")
            for entry in result.get("chapter_types", [])
        }
        for i, ch in enumerate(toc_chapters):
            ch["chapter_type"] = type_by_index.get(i, "core")
        result["chapters"] = toc_chapters
    elif result["doc_type"] == "paper":
        result["chapters"] = []

    return result


# ─── Phase 1: Haiku Chapter Summaries ─────────────────────────────────────────

_HAIKU_SUMMARY_PROMPT = """\
Summarize this section of "{doc_title}".

Section title: {chapter_title}

Section text:
{chapter_text}

Write a concise 2–3 paragraph summary covering:
- The main purpose or argument of this section
- Key concepts, methods, results, or ideas introduced
- How this section connects to the broader document

Plain prose only — no headers, no bullet points. Return only the summary text."""


def _haiku_summary(chapter_text: str, chapter_title: str, doc_title: str, client) -> str:
    prompt = _HAIKU_SUMMARY_PROMPT.format(
        doc_title=doc_title,
        chapter_title=chapter_title,
        chapter_text=chapter_text[:20_000],
    )
    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def generate_haiku_summaries(
    chapters: list, chapter_texts: list, doc_title: str, client
) -> list[str]:
    """Generate Haiku summaries for all chapters in parallel."""
    print("\nPhase 1: Generating chapter summaries (parallel)...")
    summaries = [None] * len(chapters)

    def _one(i):
        ch = chapters[i]
        print(f"  Summarising: {ch['title']}...")
        return i, _haiku_summary(chapter_texts[i], ch["title"], doc_title, client)

    with ThreadPoolExecutor(max_workers=5) as pool:
        for future in as_completed([pool.submit(_one, i) for i in range(len(chapters))]):
            i, s = future.result()
            summaries[i] = s

    print("  Done.")
    return summaries


# ─── Phase 2: Sonnet Chapter Segments ─────────────────────────────────────────

_CHAPTER_PROMPT = """\
Generate a podcast segment about "{chapter_title}" from "{doc_title}".

{role_block}

This podcast covers the document chapter by chapter. Both hosts have already discussed
the other chapters. The presenter has just read the current chapter carefully.

OTHER CHAPTERS (for cross-references):
{other_summaries}

{prev_transition_block}CURRENT CHAPTER TEXT:
{chapter_text}

Generate a dialogue of approximately {target_words} words.

Rules:
- The presenter explains; the questioner asks genuine, probing questions
- Reference other chapters naturally when relevant ("like you covered in Chapter 2...")
- Write for audio: spell out all equations, units, and abbreviations verbally
- No bullet points, no "see Figure X", no LaTeX notation
- {start_instruction}
- End when the key insight of this chapter has landed — no need for a formal close

Return JSON with exactly two keys:
{{
  "corrected_summary": "2–3 paragraph summary of this chapter (refined using cross-chapter context)",
  "script": [
    {{"speaker": "NICO", "text": "..."}},
    ...
  ]
}}

Return only valid JSON, no markdown fences."""


def _format_other_summaries(
    chapters: list, haiku_summaries: list, sonnet_summaries: dict, current_idx: int
) -> str:
    lines = []
    for i, ch in enumerate(chapters):
        if i == current_idx:
            continue
        summary = sonnet_summaries.get(i) or haiku_summaries[i]
        label = "refined" if i in sonnet_summaries else "quick"
        # Cap each summary at 400 chars to keep context manageable
        short = summary[:400].rstrip() + ("..." if len(summary) > 400 else "")
        lines.append(f"[Chapter {i + 1}: {ch['title']} ({label})]\n{short}")
    return "\n\n".join(lines)


def generate_chapter_segment(
    chapter_text: str,
    chapter: dict,
    chapter_idx: int,
    chapters: list,
    haiku_summaries: list,
    sonnet_summaries: dict,
    doc_title: str,
    presenter: str,
    target_words: int,
    client,
) -> dict:
    """Generate dialogue script + corrected summary for one chapter."""

    is_first = chapter_idx == 0
    other_summaries = _format_other_summaries(
        chapters, haiku_summaries, sonnet_summaries, chapter_idx
    )

    if is_first:
        start_instruction = (
            "Begin naturally — the intro has already given the document overview"
        )
        prev_transition_block = ""
    else:
        prev_ch = chapters[chapter_idx - 1]
        prev_summary = (
            (sonnet_summaries.get(chapter_idx - 1) or haiku_summaries[chapter_idx - 1])[:300]
        )
        start_instruction = (
            f"Open with a brief natural transition from the previous chapter "
            f"({prev_ch['title']}) into this one"
        )
        prev_transition_block = (
            f"PREVIOUS CHAPTER ({prev_ch['title']}) — transition context:\n"
            f"{prev_summary}\n\n"
        )

    prompt = _CHAPTER_PROMPT.format(
        chapter_title=chapter["title"],
        doc_title=doc_title,
        role_block=make_role_block(presenter),
        other_summaries=other_summaries,
        prev_transition_block=prev_transition_block,
        chapter_text=chapter_text[:50_000],
        target_words=target_words,
        start_instruction=start_instruction,
    )

    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


# ─── Phase 3: Intro Segment ───────────────────────────────────────────────────

_INTRO_PROMPT = """\
Generate the INTRODUCTION segment of a podcast episode about "{doc_title}".

{role_block}

Topic overview: {topic_overview}

The podcast will then go chapter by chapter. The intro should:
- Open immediately with a compelling hook — why is this document worth the listener's time?
- Give a clear sense of the document's scope and central argument
- Briefly preview the main themes in order (so the listener knows what's coming)
- Aim for approximately {target_words} words

Chapter summaries (draw from these to build the overview):
{all_summaries}

Rules:
- Write for audio — no "welcome to the podcast" opener, hook first
- Both hosts share the presenting naturally (don't let one monologue)
- Build curiosity; don't give away all the punchlines

Return a JSON array:
[{{"speaker": "NICO", "text": "..."}}, ...]

Return only valid JSON, no markdown fences."""


def generate_intro_segment(
    chapters: list,
    haiku_summaries: list,
    sonnet_summaries: dict,
    doc_title: str,
    topic_overview: str,
    presenter: str,
    client,
) -> list:
    """Generate the intro segment using all corrected chapter summaries."""

    all_summaries = "\n\n".join(
        f"[{ch['title']}]\n{sonnet_summaries.get(i) or haiku_summaries[i]}"
        for i, ch in enumerate(chapters)
    )
    intro_words = int(INTRO_MINUTES * WORDS_PER_MINUTE)

    prompt = _INTRO_PROMPT.format(
        doc_title=doc_title,
        role_block=make_role_block(presenter),
        topic_overview=topic_overview,
        target_words=intro_words,
        all_summaries=all_summaries,
    )

    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


# ─── Paper (single-pass) path ─────────────────────────────────────────────────

_PAPER_PROMPT = """\
Generate a podcast episode about "{doc_title}".

{role_block}

Topic: {topic_overview}

One host explains the document to the other. The presenter has read it carefully;
the questioner is encountering it for the first time.

Rules:
- Aim for approximately {target_words} words total
- Write for audio: spell out equations, abbreviations, and units verbally
- No bullet points, no figure references, no LaTeX
- Open immediately with a hook — why is this document interesting or important?
- Cover: what it's about, the key ideas or findings, why it matters, one honest limitation

Document text:
{doc_text}

Return a JSON array:
[{{"speaker": "NICO", "text": "..."}}, ...]

Return only valid JSON, no markdown fences."""


def generate_paper_script(
    doc_text: str,
    doc_title: str,
    topic_overview: str,
    presenter: str,
    target_words: int,
    client,
) -> list:
    """Single-pass script generation for short papers."""
    prompt = _PAPER_PROMPT.format(
        doc_title=doc_title,
        role_block=make_role_block(presenter),
        topic_overview=topic_overview,
        target_words=target_words,
        doc_text=doc_text[:20_000],
    )

    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=5000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


# ─── Length allocation ────────────────────────────────────────────────────────

def _auto_minutes(total_pages: int, doc_type: str) -> float:
    if doc_type == "paper":
        return 10.0
    # ~1 min per 8 pages, clamped to [15, 60]
    return max(15.0, min(60.0, total_pages / 8.0))


def _chapter_target_words(chapter: dict, all_chapters: list, total_minutes: float) -> int:
    available = total_minutes - INTRO_MINUTES
    total_pages = sum(c["end_page"] - c["start_page"] for c in all_chapters) or 1

    raw_weight  = (chapter["end_page"] - chapter["start_page"]) / total_pages
    type_weight = TYPE_WEIGHTS.get(chapter.get("chapter_type", "core"), 1.0)
    adjusted    = raw_weight * type_weight

    total_weight = sum(
        ((c["end_page"] - c["start_page"]) / total_pages)
        * TYPE_WEIGHTS.get(c.get("chapter_type", "core"), 1.0)
        for c in all_chapters
    ) or 1.0

    minutes = available * (adjusted / total_weight)
    minutes = max(2.0, min(8.0, minutes))
    return int(minutes * WORDS_PER_MINUTE)


# ─── Main pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    pdf_path: str,
    total_minutes: float | None,
    presenter_arg: str | None,
    client,
) -> list:
    """
    Full hierarchical pipeline. Returns the assembled flat script
    (list of {speaker, text} dicts) ready for TTS.
    """
    print(f"\nReading PDF: {pdf_path}")
    metadata    = get_pdf_metadata(pdf_path)
    total_pages = metadata["total_pages"]
    print(f"  {total_pages} pages, {len(metadata['toc'])} TOC entries")

    toc_chapters = chapters_from_toc(metadata["toc"], total_pages)

    # ── Phase 0: structure detection ──
    print("\nPhase 0: Detecting document structure...")
    structure    = detect_structure(metadata, toc_chapters, client)
    doc_type     = structure["doc_type"]
    doc_title    = structure["title"]
    topic_overview = structure["topic_overview"]
    chapters     = structure.get("chapters", [])

    print(f"  Type:  {doc_type}")
    print(f"  Title: {doc_title}")
    if doc_type == "chaptered":
        print(f"  Chapters ({len(chapters)}):")
        for ch in chapters:
            print(
                f"    [{ch.get('chapter_type', '?'):12s}] "
                f"{ch['title']} "
                f"(pp {ch['start_page'] + 1}–{ch['end_page']})"
            )

    presenter = choose_presenter(presenter_arg)
    questioner = "VENA" if presenter == "NICO" else "NICO"
    print(f"  Presenter: {presenter}   Questioner: {questioner}")

    if total_minutes is None:
        total_minutes = _auto_minutes(total_pages, doc_type)
    print(f"  Target:    {total_minutes:.0f} minutes")

    # ── Paper path: single-pass ──
    if doc_type == "paper":
        print("\nGenerating paper script (single pass)...")
        doc_text     = extract_text(pdf_path)
        target_words = int(total_minutes * WORDS_PER_MINUTE)
        script = generate_paper_script(
            doc_text, doc_title, topic_overview, presenter, target_words, client
        )
        print(f"  Script: {len(script)} lines")
        return script

    # ── Chaptered path ──

    # Extract chapter texts; sub-chunk if needed
    print("\nExtracting chapter text...")
    chapter_texts = []
    for ch in chapters:
        text = extract_text(pdf_path, ch["start_page"], ch["end_page"])
        if len(text) > SUBCHUNK_THRESHOLD:
            print(f"  Sub-chunking: {ch['title']} ({len(text):,} chars)")
            subchunks  = subchunk_chapter(pdf_path, ch, metadata["toc"], total_pages)
            sub_texts  = [
                extract_text(pdf_path, s["start_page"], s["end_page"])
                for s in subchunks
            ]
            # Summarise sub-sections with Haiku; use the summaries as effective text
            sub_summaries = []
            for s, st in zip(subchunks, sub_texts):
                ss = _haiku_summary(st, s["title"], doc_title, client)
                sub_summaries.append(f"[{s['title']}]\n{ss}")
            text = "\n\n".join(sub_summaries)
            ch["_subchunked"] = True
        chapter_texts.append(text)

    # Phase 1: Haiku summaries (parallel)
    haiku_summaries = generate_haiku_summaries(chapters, chapter_texts, doc_title, client)

    # Phase 2: Sequential Sonnet chapter segments
    print("\nPhase 2: Generating chapter segments (sequential)...")
    sonnet_summaries: dict[int, str]    = {}
    chapter_scripts:  dict[int, list]   = {}

    for i, chapter in enumerate(chapters):
        print(f"\n  Chapter {i + 1}/{len(chapters)}: {chapter['title']}")
        target_words = _chapter_target_words(chapter, chapters, total_minutes)
        print(f"    Target: {target_words} words (~{target_words // WORDS_PER_MINUTE:.1f} min)")

        result = generate_chapter_segment(
            chapter_text     = chapter_texts[i],
            chapter          = chapter,
            chapter_idx      = i,
            chapters         = chapters,
            haiku_summaries  = haiku_summaries,
            sonnet_summaries = sonnet_summaries,
            doc_title        = doc_title,
            presenter        = presenter,
            target_words     = target_words,
            client           = client,
        )
        sonnet_summaries[i] = result["corrected_summary"]
        chapter_scripts[i]  = result["script"]
        print(f"    Generated {len(result['script'])} lines")

    # Phase 3: Intro (last, so it uses all refined summaries)
    print("\nPhase 3: Generating intro segment...")
    intro_script = generate_intro_segment(
        chapters        = chapters,
        haiku_summaries = haiku_summaries,
        sonnet_summaries = sonnet_summaries,
        doc_title        = doc_title,
        topic_overview   = topic_overview,
        presenter        = presenter,
        client           = client,
    )
    print(f"  Intro: {len(intro_script)} lines")

    # Assemble: intro + chapters in order
    full_script = intro_script[:]
    for i in range(len(chapters)):
        full_script.extend(chapter_scripts[i])

    print(f"\n  Total script: {len(full_script)} lines")
    return full_script


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a podcast episode from a local PDF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pdf_path", nargs="?", default=None,
        help="Path to the PDF file (or set PDF_PODCAST_PATH in .env)",
    )
    parser.add_argument(
        "--minutes", type=float, default=None,
        help="Target podcast length in minutes (default: auto from page count)",
    )
    parser.add_argument(
        "--presenter", choices=["NICO", "VENA"], default=None,
        help="Force a specific presenter (default: random each run)",
    )
    parser.add_argument(
        "--script-only", action="store_true",
        help="Generate and save the script JSON, then stop (no TTS)",
    )
    parser.add_argument(
        "--from-script", default=None, metavar="PATH",
        help="Load an existing script JSON and go straight to TTS",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output MP3 path (default: <pdf_stem>_podcast.mp3)",
    )
    args = parser.parse_args()

    # Resolve PDF path: CLI arg > .env > error
    pdf_path = args.pdf_path or os.getenv("PDF_PODCAST_PATH")
    if not pdf_path and not args.from_script:
        parser.error(
            "Provide a PDF path as an argument or set PDF_PODCAST_PATH in your .env file."
        )

    # Resolve output paths
    if pdf_path:
        stem = Path(pdf_path).stem
    else:
        stem = Path(args.from_script).stem.replace("_script", "")

    output_path = args.output or f"{stem}_podcast.mp3"
    script_path = output_path.replace(".mp3", "_script.json")

    print("\n=== Delphinus PDF Podcast ===")
    if pdf_path:
        print(f"PDF:    {pdf_path}")
    print(f"Output: {output_path}")

    # ── Load or generate script ──
    if args.from_script:
        print(f"\nLoading script from {args.from_script}...")
        with open(args.from_script, encoding="utf-8") as f:
            script = json.load(f)
        print(f"  Loaded {len(script)} lines.")
    else:
        client = anthropic.Anthropic()
        script = run_pipeline(
            pdf_path      = pdf_path,
            total_minutes = args.minutes,
            presenter_arg = args.presenter,
            client        = client,
        )
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, indent=2, ensure_ascii=False)
        print(f"\nScript saved to {script_path}")

    # Print a short preview
    print("\n--- SCRIPT PREVIEW (first 5 lines) ---")
    for line in script[:5]:
        preview = line["text"][:100].encode("ascii", errors="replace").decode("ascii")
        print(f"{line['speaker']}: {preview}...")
    print("---\n")

    if args.script_only:
        print("Script-only mode — done.")
        return

    # ── TTS + stitch ──
    print("Generating audio...")
    generate_audio(script, output_path)
    print(f"\nDone!  Podcast: {output_path}")
    print(f"       Script:  {script_path}")


if __name__ == "__main__":
    main()
