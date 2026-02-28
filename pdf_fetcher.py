import anthropic
import urllib.request
import ssl
import os
import tempfile
from dotenv import load_dotenv

load_dotenv()

def fetch_pdf_text(arxiv_id: str) -> str:
    """
    Downloads a PDF from arxiv and extracts the text content.
    Returns the extracted text as a string.
    """
    clean_id = arxiv_id.replace("v1", "").replace("v2", "").replace("v3", "")
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    
    print(f"  Downloading {pdf_url}...")
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; arxiv-agent/1.0)"}
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(pdf_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
            with open(tmp_path, "wb") as f:
                f.write(response.read())
        
        import fitz  # pymupdf
        doc = fitz.open(tmp_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        
        if len(text) > 15000:
            text = text[:15000] + "\n\n[... truncated ...]"
        
        return text
    
    finally:
        os.unlink(tmp_path)


def summarize_paper(arxiv_id: str, title: str, is_must_see: bool = False, generate_podcast: bool = True) -> dict:
    """
    Fetches a paper's PDF and generates a deep-dive summary using Claude.
    If is_must_see and generate_podcast is True, also generates a podcast episode.
    """
    client = anthropic.Anthropic()
    
    print(f"Summarizing: {title}")
    
    try:
        pdf_text = fetch_pdf_text(arxiv_id)
    except Exception as e:
        return {
            "id": arxiv_id,
            "title": title,
            "summary": f"Could not fetch PDF: {e}",
            "key_results": [],
            "methods": "N/A",
            "why_it_matters": "N/A",
            "caveats": "N/A",
            "podcast_path": None,
        }
    
    prompt = f"""You are summarizing a quantum physics paper for an expert researcher.
    
Paper title: {title}
Paper content:
{pdf_text}

Please provide a deep-dive summary with the following structure. Be specific and technical — 
the reader is a physicist who wants real details, not vague descriptions.

Return as JSON with this exact structure:
{{
  "id": "{arxiv_id}",
  "title": "{title}",
  "summary": "3-4 sentence overview of what the paper does and what they found",
  "key_results": [
    "Specific result 1 with numbers/metrics where available",
    "Specific result 2",
    "Specific result 3"
  ],
  "methods": "1-2 sentences on the experimental or theoretical approach",
  "why_it_matters": "1-2 sentences on the broader significance and what this opens up",
  "caveats": "Any important limitations or caveats worth noting"
}}

Return only valid JSON, no markdown formatting.
"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    raw = response.content[0].text.strip()
    
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    
    import json
    result = json.loads(raw)
    result["podcast_path"] = None

    # Generate podcast for must-see paper if enabled
    if is_must_see and generate_podcast:
        from podcast_generator import generate_podcast as generate_podcast_fn
        podcast_path = f"podcast_{arxiv_id.replace('/', '_')}.mp3"
        print(f"\n  Generating podcast for must-see paper...")
        result["podcast_path"] = generate_podcast_fn(pdf_text, arxiv_id, podcast_path)

    return result


def summarize_top_papers(top_ids: list[str], papers: list[dict], must_see_id: str = None, generate_podcast: bool = True) -> list[dict]:
    """
    Takes the top paper IDs from the analyzer and generates full summaries.
    Optionally generates a podcast for the must-see paper.
    """
    id_to_title = {p["id"]: p["title"] for p in papers}
    
    summaries = []
    for arxiv_id in top_ids:
        title = id_to_title.get(arxiv_id, "Unknown title")
        is_must_see = (arxiv_id == must_see_id)
        summary = summarize_paper(arxiv_id, title, is_must_see=is_must_see, generate_podcast=generate_podcast)
        summaries.append(summary)
        print(f"  Done.\n")
    
    return summaries


if __name__ == "__main__":
    from arxiv_fetcher import fetch_recent_papers
    from analyzer import analyze_papers
    import json
    
    print("Fetching papers...")
    papers = fetch_recent_papers()
    
    print(f"Analyzing {len(papers)} papers...")
    analysis = analyze_papers(papers)
    
    must_see_id = analysis["must_see"]["id"]
    print(f"\nTop 3 papers for deep dive: {analysis['top_3_ids']}")
    print(f"Must-see: {must_see_id}\n")
    
    summaries = summarize_top_papers(analysis["top_3_ids"], papers, must_see_id=must_see_id)
    
    for s in summaries:
        print(f"\n{'='*60}")
        print(f"TITLE: {s['title']}")
        print(f"\nSUMMARY: {s['summary']}")
        if s.get("podcast_path"):
            print(f"\nPODCAST: {s['podcast_path']}")