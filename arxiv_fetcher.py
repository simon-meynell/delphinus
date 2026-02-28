import arxiv
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import pytz

load_dotenv()

DEFAULT_CATEGORIES = ["quant-ph", "cond-mat.mes-hall"]

def get_categories() -> list[str]:
    raw = os.getenv("ARXIV_CATEGORIES", "")
    if raw.strip():
        return [c.strip() for c in raw.split(",") if c.strip()]
    return DEFAULT_CATEGORIES

def get_submission_window():
    """
    Return (start_utc, end_utc) covering the submissions that correspond to
    the most recent arxiv announcement batch, based on arxiv's 2PM ET cutoff schedule.

    Mon       → Fri 2PM – Mon 2PM  (weekend bundle)
    Tue–Fri   → Previous day 2PM – today 2PM
    Sat       → Thu 2PM – Fri 2PM  (Friday's announcement, for catch-up)
    Sun       → Thu 2PM – Fri 2PM  (same)
    """
    ET = pytz.timezone("America/New_York")
    now_et = datetime.now(ET)
    cutoff_today = now_et.replace(hour=14, minute=0, second=0, microsecond=0)
    weekday = now_et.weekday()  # 0=Mon, 6=Sun

    if weekday == 0:    # Monday — grab everything since Friday 2PM
        days_back = 3
    elif weekday == 5:  # Saturday — grab Friday's batch (Thu 2PM → Fri 2PM)
        days_back = 2
    elif weekday == 6:  # Sunday — same as Saturday
        days_back = 3
    else:               # Tue–Fri — grab since yesterday 2PM
        days_back = 1

    start = cutoff_today - timedelta(days=days_back)
    end = cutoff_today  # exclude anything submitted after today's cutoff (tomorrow's batch)

    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)

def fetch_recent_papers(categories=None, max_per_category=100):
    """
    Fetch recent new submissions from arxiv for the given categories.
    Categories default to ARXIV_CATEGORIES in .env, or quant-ph + cond-mat.mes-hall if not set.
    Uses arxiv's 2PM ET submission cutoff schedule to determine the correct window.
    """
    if categories is None:
        categories = get_categories()

    start_utc, end_utc = get_submission_window()
    print(f"  Submission window: {start_utc.strftime('%a %Y-%m-%d %H:%M UTC')} → {end_utc.strftime('%a %Y-%m-%d %H:%M UTC')}")

    client = arxiv.Client()
    papers = []
    seen_ids = set()

    for category in categories:
        search = arxiv.Search(
            query=f"cat:{category}",
            max_results=max_per_category,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )

        for result in client.results(search):
            paper_id = result.entry_id.split("/")[-1]

            if paper_id in seen_ids:
                continue
            seen_ids.add(paper_id)

            submitted = result.published.replace(tzinfo=timezone.utc)

            if submitted > end_utc:
                continue  # submitted after today's cutoff — tomorrow's batch, skip

            if submitted < start_utc:
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
    papers = fetch_recent_papers()
    print(f"Found {len(papers)} papers today\n")
    for p in papers[:5]:
        print(f"- {p['title']}")
        print(f"  {p['first_author']} ... {p['last_author']}")
        print(f"  {p['id']}\n")