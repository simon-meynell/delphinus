import argparse
import json
import os
from datetime import datetime, timezone
from arxiv_fetcher import fetch_recent_papers
from analyzer import analyze_papers
from pdf_fetcher import summarize_top_papers
from email_formatter import format_email
from email_sender import send_digest

def parse_dt(s):
    """Parse an ISO datetime string into a UTC-aware datetime."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def save_last_fetch(path, end_utc):
    with open(path, "w") as f:
        json.dump({"last_fetch_utc": end_utc.isoformat()}, f)

def run():
    parser = argparse.ArgumentParser(description="Run the Delphinus arxiv digest.")
    parser.add_argument("--from", dest="from_dt", metavar="DATETIME",
                        help="Override fetch start (ISO format, e.g. 2026-03-20T14:00:00)")
    parser.add_argument("--to", dest="to_dt", metavar="DATETIME",
                        help="Override fetch end (ISO format)")
    parser.add_argument("--last-fetch-file", default="last_fetch.json", metavar="PATH",
                        help="Path to the last-fetch state file (default: last_fetch.json)")
    args = parser.parse_args()

    start_override = parse_dt(args.from_dt) if args.from_dt else None
    end_override   = parse_dt(args.to_dt)   if args.to_dt   else None
    manual_override = start_override is not None or end_override is not None

    print("=== Delphinus ===\n")

    podcast_enabled = os.getenv("PODCAST_ENABLED", "true").lower() == "true"
    if not podcast_enabled:
        print("Podcast generation disabled (PODCAST_ENABLED=false).\n")

    print("Fetching papers...")
    papers, start_utc, end_utc = fetch_recent_papers(
        start_utc=start_override,
        end_utc=end_override,
        last_fetch_path=args.last_fetch_file,
    )
    print(f"Found {len(papers)} papers.\n")

    if not papers:
        msg = f"No papers found in window {start_utc.isoformat()} → {end_utc.isoformat()}. Aborting."
        print(msg)
        with open("delphinus_log.txt", "a") as log:
            log.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")
        return

    print("Analyzing with Haiku...")
    analysis = analyze_papers(papers)

    must_see = analysis["must_see"]
    must_see_id = must_see["id"] if must_see else None
    print(f"\nMust-see: {must_see['title']}")
    print(f"Top 3 for deep dive: {analysis['top_3_ids']}\n")

    print("Fetching PDFs for top 3...")
    summaries = summarize_top_papers(
        analysis["top_3_ids"],
        papers,
        must_see_id=must_see_id,
        generate_podcast=podcast_enabled
    )

    # Pull podcast path out of must-see summary if it was generated
    podcast_path = None
    for s in summaries:
        if s["id"] == must_see_id and s.get("podcast_path"):
            podcast_path = s["podcast_path"]
            break

    print("\nFormatting email...")
    html = format_email(analysis, summaries, start_utc=start_utc, end_utc=end_utc)

    send_digest(html, podcast_path=podcast_path)

    # Only advance the state pointer on a normal (non-override) run
    if not manual_override:
        if papers:
            last_seen = max(
                datetime.strptime(p["submitted"], "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
                for p in papers
            )
        else:
            last_seen = end_utc
        save_last_fetch(args.last_fetch_file, last_seen)
        print(f"Updated {args.last_fetch_file} → {last_seen.isoformat()}")

    print("\nDone!")

if __name__ == "__main__":
    run()
