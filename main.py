import os
from arxiv_fetcher import fetch_recent_papers
from analyzer import analyze_papers
from pdf_fetcher import summarize_top_papers
from email_formatter import format_email
from email_sender import send_digest

def run():
    print("=== Delphinus ===\n")

    podcast_enabled = os.getenv("PODCAST_ENABLED", "true").lower() == "true"
    if not podcast_enabled:
        print("Podcast generation disabled (PODCAST_ENABLED=false).\n")

    print("Fetching papers...")
    papers = fetch_recent_papers()
    print(f"Found {len(papers)} papers.\n")

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
    html = format_email(analysis, summaries)

    send_digest(html, podcast_path=podcast_path)
    print("\nDone!")

if __name__ == "__main__":
    run()