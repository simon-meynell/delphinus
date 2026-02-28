import anthropic
import json
from dotenv import load_dotenv
from interests import CORE_RESEARCH, FOUNDATIONS_INTERESTS, QUIRKY_INTERESTS, IMPORTANT_GROUPS

load_dotenv()

def analyze_papers(papers: list[dict]) -> dict:
    client = anthropic.Anthropic()

    papers_text = ""
    for i, p in enumerate(papers):
        first = p.get("first_author", p["authors"][0] if p["authors"] else "Unknown")
        last = p.get("last_author", p["authors"][-1] if len(p["authors"]) > 1 else "")
        all_authors = ", ".join(p["authors"][:6])
        if len(p["authors"]) > 6:
            all_authors += " et al."

        papers_text += f"""
[{i+1}] {p["title"]}
First author: {first} | Last author: {last}
All authors: {all_authors}
ID: {p["id"]}
Abstract: {p["abstract"]}
---
"""

    prompt = f"""You are a research assistant helping a quantum physicist stay on top of the latest arxiv papers.

CORE RESEARCH INTERESTS:
{CORE_RESEARCH}

QUANTUM FOUNDATIONS INTERESTS:
{FOUNDATIONS_INTERESTS}

IMPORTANT GROUPS TO TRACK:
{IMPORTANT_GROUPS}

QUIRKY/UNUSUAL INTERESTS:
{QUIRKY_INTERESTS}

Today's papers:
{papers_text}

RULES:

GROUP MATCHING: Only assign a group affiliation if you are highly confident a known PI from the IMPORTANT GROUPS list is an actual listed author. Do NOT assign a group based on institution alone. If uncertain, leave group as empty string. Wrong is worse than blank.

DOLPHIN RATING SYSTEM for core_papers:
Rate each paper with 1, 2, or 3 dolphins based solely on relevance to CORE RESEARCH INTERESTS above.
Do not factor in foundations, quirky interest when scoring. If the work is from an IMPORTANT GROUP then it should be weighted highly.
- "🐬" = tangential but interesting, you might find it worth a glance
- "🐬🐬" = you should probably at least look at this one
- "🐬🐬🐬" = YOWZA — you need to know about this paper
Note: not every day has a 3-dolphin paper, and that's okay. Don't force it.

MUST-SEE SELECTION: Pick the must_see paper based solely on CORE RESEARCH INTERESTS. If it is from an IMPORTANT GROUP then this should add some weight.
Do not elevate a paper to must-see because it touches foundations,
or is quirky. It should be the paper most directly relevant to the researcher's core work.

Return a JSON object with this exact structure:

{{
  "must_see": {{
    "id": "<arxiv id of single most important paper today>",
    "title": "<title>",
    "first_author": "<first author name>",
    "last_author": "<last/senior author name>",
    "group": "<group name ONLY if PI is an actual author, else empty string>",
    "why": "<one punchy sentence: why is this THE paper of the day>"
  }},

  "core_papers": [
    {{
      "index": <paper number>,
      "id": "<arxiv id>",
      "title": "<title>",
      "first_author": "<first author>",
      "last_author": "<last/senior author>",
      "group": "<group name ONLY if PI is an actual author, else empty string>",
      "relevance": "<1-2 sentences on why this is relevant>",
      "dolphins": "<one of: 🐬 or 🐬🐬 or 🐬🐬🐬>"
    }}
  ],

  "foundations_papers": [
    {{
      "index": <paper number>,
      "id": "<arxiv id>",
      "title": "<title>",
      "first_author": "<first author>",
      "last_author": "<last/senior author>",
      "group": "<group name ONLY if PI is an actual author, else empty string>",
      "relevance": "<1-2 sentences on the foundations angle>"
    }}
  ],

  "top_3_ids": [<list of 3 arxiv ids for full PDF deep-dive, must_see should be first>],

  "quirky_papers": [
    {{
      "index": <paper number>,
      "id": "<arxiv id>",
      "title": "<title>",
      "first_author": "<first author>",
      "last_author": "<last/senior author>",
      "why_quirky": "<1-2 sentences on what makes this delightfully weird>"
    }}
  ]
}}

Return only valid JSON, no markdown formatting, no extra text.
"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=15000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


if __name__ == "__main__":
    from arxiv_fetcher import fetch_recent_papers

    print("Fetching papers...")
    papers = fetch_recent_papers()
    print(f"Found {len(papers)} papers. Analyzing with Haiku...")

    result = analyze_papers(papers)

    print("\n=== MUST SEE ===")
    ms = result["must_see"]
    print(f"{ms['title']}")
    print(f"  {ms['first_author']} ... {ms['last_author']}")
    print(f"  {ms['why']}")

    print(f"\n=== CORE PAPERS ({len(result['core_papers'])}) ===")
    for p in result["core_papers"]:
        group_tag = f" [{p['group']}]" if p['group'] else ""
        print(f"{p['dolphins']} {p['title']}{group_tag}")
        print(f"  {p['first_author']} ... {p['last_author']}")
        print(f"  {p['relevance']}")

    print(f"\n=== FOUNDATIONS ({len(result['foundations_papers'])}) ===")
    for p in result["foundations_papers"]:
        print(f"  {p['title']}")
        print(f"  {p['first_author']} ... {p['last_author']}")

    print(f"\n=== TOP 3 FOR DEEP DIVE ===")
    print(result["top_3_ids"])

    print(f"\n=== QUIRKY ===")
    for p in result["quirky_papers"]:
        print(f"  {p['title']}")
        print(f"  {p['why_quirky']}")