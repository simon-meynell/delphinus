import arxiv
import json
import os
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import pytz

load_dotenv()

DEFAULT_CATEGORIES = ["quant-ph", "cond-mat.mes-hall"]
MAX_LOOKBACK_DAYS = 7

def get_categories() -> list[str]:
    raw = os.getenv("ARXIV_CATEGORIES", "")
    if raw.strip():
        return [c.strip() for c in raw.split(",") if c.strip()]
    return DEFAULT_CATEGORIES

def get_window(last_fetch_path="last_fetch.json", start_override=None, end_override=None):
    """
    Return (start_utc, end_utc) for the fetch window.

    If start_override and end_override are provided, use them directly.
    Otherwise, read the last successful fetch timestamp from last_fetch_path.
    If no file exists or the saved timestamp is older than MAX_LOOKBACK_DAYS, fall back to
    (now - MAX_LOOKBACK_DAYS). end is always now.
    """
    now_utc = datetime.now(timezone.utc)

    if start_override is not None and end_override is not None:
        return start_override, end_override

    end_utc = end_override if end_override is not None else now_utc
    fallback_start = now_utc - timedelta(days=MAX_LOOKBACK_DAYS)

    if start_override is not None:
        return start_override, end_utc

    # Try to read saved last-fetch timestamp
    try:
        with open(last_fetch_path) as f:
            data = json.load(f)
        saved = datetime.fromisoformat(data["last_fetch_utc"])
        if saved.tzinfo is None:
            saved = saved.replace(tzinfo=timezone.utc)
        # Don't go back more than MAX_LOOKBACK_DAYS
        start_utc = max(saved, fallback_start)
    except (FileNotFoundError, KeyError, ValueError):
        start_utc = fallback_start

    return start_utc, end_utc

def fetch_recent_papers(categories=None, start_utc=None, end_utc=None,
                        last_fetch_path="last_fetch.json", max_retries=3, retry_delay=60):
    """
    Fetch new submissions from arxiv for the given categories.
    Categories default to ARXIV_CATEGORIES in .env, or quant-ph + cond-mat.mes-hall if not set.

    The time window is determined by last_fetch_path (the timestamp of the last successful run).
    Pass start_utc/end_utc directly to override the window (useful for testing or backfills).

    Returns (papers, start_utc, end_utc).
    Retries up to max_retries times on HTTP errors (e.g. 429 rate limit, 503 unavailable).
    """
    if categories is None:
        categories = get_categories()

    start_utc, end_utc = get_window(last_fetch_path, start_override=start_utc, end_override=end_utc)
    print(f"  Fetch window: {start_utc.strftime('%a %Y-%m-%d %H:%M UTC')} -> {end_utc.strftime('%a %Y-%m-%d %H:%M UTC')}")

    for attempt in range(max_retries):
        try:
            papers = _fetch(categories, start_utc, end_utc)
            return papers, start_utc, end_utc
        except arxiv.HTTPError as e:
            if attempt < max_retries - 1:
                print(f"  arXiv API error ({e}), retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
            else:
                raise

def _fetch(categories, start_utc, end_utc):
    """Inner fetch logic, separated so the retry wrapper stays clean."""
    # 500 is well above any realistic daily announcement volume (~150–250 for quant-ph)
    client = arxiv.Client(page_size=200, num_retries=3)
    papers = []
    seen_ids = set()

    for category in categories:
        search = arxiv.Search(
            query=f"cat:{category}",
            max_results=500,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )

        skipped = 0
        for result in client.results(search):
            paper_id = result.entry_id.split("/")[-1]

            if paper_id in seen_ids:
                continue
            seen_ids.add(paper_id)

            submitted = result.published.replace(tzinfo=timezone.utc)

            if submitted > end_utc:
                skipped += 1
                continue  # submitted after cutoff — not yet announced, skip

            if submitted < start_utc:
                print(f"  [{category}] Skipped {skipped} post-cutoff papers, found {len(papers)} in window.")
                break  # older than our window — stop iterating

            papers.append({
                "id": paper_id,
                "title": result.title,
                "abstract": result.summary,
                "authors": [a.name for a in result.authors],
                "first_author": result.authors[0].name if result.authors else "Unknown",
                "last_author": result.authors[-1].name if len(result.authors) > 1 else "",
                "url": result.entry_id,
                "categories": result.categories,
                "submitted": submitted.strftime("%Y-%m-%d %H:%M UTC"),
            })

    return papers


if __name__ == "__main__":
    papers, start, end = fetch_recent_papers()
    print(f"Found {len(papers)} papers\n")
    for p in papers[:5]:
        print(f"- {p['title']}")
        print(f"  {p['first_author']} ... {p['last_author']}")
        print(f"  {p['id']}\n")