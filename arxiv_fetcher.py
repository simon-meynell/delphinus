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

    arXiv rule: papers submitted by 2PM ET on day X are announced on day X+1.
    So "today's announcement" covers submissions from 2PM ET two days ago to 2PM ET yesterday.

    Mon       → Fri 2PM – Mon 2PM  (weekend bundle announced Monday)
    Tue–Fri   → 2 days ago 2PM – yesterday 2PM
    Sat/Sun   → Wed 2PM – Thu 2PM  (Friday's announcement; no weekend announcements)
    """
    ET = pytz.timezone("America/New_York")
    now_et = datetime.now(ET)
    cutoff_today = now_et.replace(hour=14, minute=0, second=0, microsecond=0)
    weekday = now_et.weekday()  # 0=Mon, 6=Sun

    if weekday == 0:         # Monday — announced papers submitted Fri 2PM – Mon 2PM
        start = cutoff_today - timedelta(days=3)
        end = cutoff_today
    elif weekday in (5, 6):  # Weekend — Friday's announcement: Wed 2PM → Thu 2PM
        last_friday = cutoff_today - timedelta(days=weekday - 4)
        start = last_friday - timedelta(days=2)  # Wednesday 2PM
        end = last_friday - timedelta(days=1)    # Thursday 2PM
    else:                    # Tue–Fri — announced papers submitted 2 days ago 2PM → yesterday 2PM
        start = cutoff_today - timedelta(days=2)
        end = cutoff_today - timedelta(days=1)

    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)

def fetch_recent_papers(categories=None):
    """
    Fetch recent new submissions from arxiv for the given categories.
    Categories default to ARXIV_CATEGORIES in .env, or quant-ph + cond-mat.mes-hall if not set.
    Uses arxiv's 2PM ET submission cutoff schedule to determine the correct window.
    """
    if categories is None:
        categories = get_categories()

    start_utc, end_utc = get_submission_window()
    print(f"  Submission window: {start_utc.strftime('%a %Y-%m-%d %H:%M UTC')} -> {end_utc.strftime('%a %Y-%m-%d %H:%M UTC')}")

    client = arxiv.Client(page_size=200, num_retries=3)
    papers = []
    seen_ids = set()

    for category in categories:
        search = arxiv.Search(
            query=f"cat:{category}",
            max_results=2000,
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
    papers = fetch_recent_papers()
    print(f"Found {len(papers)} papers today\n")
    for p in papers[:5]:
        print(f"- {p['title']}")
        print(f"  {p['first_author']} ... {p['last_author']}")
        print(f"  {p['id']}\n")