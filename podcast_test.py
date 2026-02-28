"""
podcast_test.py

Standalone test script for Delphinus podcast generation.
Fetches a paper by arxiv ID, generates a dialogue script with Claude,
and produces an MP3 using OpenAI TTS.

Usage:
    python podcast_test.py 2501.12345                              # full run
    python podcast_test.py 2501.12345 --script-only                # generate script, skip TTS
    python podcast_test.py 2501.12345 --from-script script.json    # skip Claude, reuse existing script

Requirements:
    pip install anthropic openai pymupdf python-dotenv
    ffmpeg installed on system PATH
"""

import os
import json
import urllib.request
import ssl
import tempfile
import argparse
import glob
from dotenv import load_dotenv

load_dotenv()


# ─── PDF Fetching ────────────────────────────────────────────────────────────

def fetch_pdf_text(arxiv_id: str) -> str:
    """Download PDF from arxiv and extract full text."""
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

        print(f"  Extracted {len(text):,} characters from PDF.")
        return text

    finally:
        os.unlink(tmp_path)


# ─── Script Generation ───────────────────────────────────────────────────────

SCRIPT_PROMPT = """You are writing a podcast script for a 10-minute episode about a quantum physics paper.

The podcast features two hosts — both experimental quantum physicists (think grad students or 
postdocs working on color centers or quantum hardware). They are peers, not teacher and student.

{role_block}

The conversation should feel like two experimentalists in a lab kitchen genuinely tearing into 
a paper — one has read it carefully, the other hasn't but is sharp enough to probe hard. 
They care about whether results are real, reproducible, and relevant to their own work.
Neither is explaining to a general audience; they're explaining to each other.

IMPORTANT RULES:
- Write for audio. No bullet points. No "as shown in Figure 2". No equations in LaTeX.
  Spell out everything verbally: "the T two star time" not "T2*", "nanometers" not "nm".
- Aim for ~1500 words total. This gives roughly 10 minutes at natural speaking pace.
- The skeptic should push back at least twice with substantive objections, not just 
  "interesting!" reactions. Make the expert actually defend the result.
- Cover: what the paper is doing, the key experimental result with real numbers, why it's 
  technically hard or novel, what it means for experimental quantum science (especially 
  color centers / solid-state qubits), and one honest open question or limitation.
- Do NOT pad with filler. Every exchange should move the conversation forward.
- Start in media res — jump straight into the paper. No intro, no "welcome to the show".

Format output as a JSON array:
[
  {{"speaker": "NICO", "text": "..."}},
  {{"speaker": "VENA", "text": "..."}},
  ...
]

Return only valid JSON. No markdown fences, no extra text.

Paper content:
{pdf_text}
"""

ROLE_BLOCK_NICO_EXPERT = """- NICO (expert this episode): Has read this paper closely. Enthusiastic, fast-talking, 
  makes lateral connections to other results. Gets genuinely excited when something is clever. 
  Slightly chaotic energy but technically sharp. Drives the explanation forward.
- VENA (skeptic this episode): Has not read this paper. Precise, dry, skeptical by default. 
  Demands justification before accepting a claim. Will point out if something sounds too good 
  or if a control is missing. Warms up only when the evidence actually convinces her."""

ROLE_BLOCK_VENA_EXPERT = """- VENA (expert this episode): Has read this paper closely. Precise and methodical in her 
  explanation. Presents results carefully, flags caveats upfront. Dry wit, doesn't oversell.
- NICO (skeptic this episode): Has not read this paper. Asks rapid-fire questions, makes 
  speculative leaps that Vena has to rein in. Pushes back when something sounds incremental 
  or when he thinks the community already knew this. Enthusiastic but demanding."""


def generate_script(pdf_text: str, title: str) -> list[dict]:
    """Generate a podcast dialogue script from paper text using Claude."""
    import anthropic
    import random

    client = anthropic.Anthropic()

    # Randomly assign expert/skeptic roles each run
    if random.random() < 0.5:
        role_block = ROLE_BLOCK_NICO_EXPERT
        expert = "NICO"
    else:
        role_block = ROLE_BLOCK_VENA_EXPERT
        expert = "VENA"

    print(f"  This episode: {expert} is the expert.")
    print("  Generating podcast script with Claude...")

    prompt = SCRIPT_PROMPT.format(pdf_text=pdf_text, role_block=role_block)

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    script = json.loads(raw)
    print(f"  Script generated: {len(script)} lines.")
    return script


# ─── TTS + Audio ─────────────────────────────────────────────────────────────

# OpenAI TTS voices — available: alloy, echo, fable, onyx, nova, shimmer
VOICES = {
    "NICO": "echo",   # Male
    "VENA": "nova",  # Female
}

def synthesize_line(client, text: str, voice_name: str) -> bytes:
    """Synthesize a single line of text to MP3 bytes using OpenAI TTS."""
    response = client.audio.speech.create(
        model="tts-1",       # tts-1 is faster/cheaper; tts-1-hd for higher quality
        voice=voice_name,
        input=text,
        response_format="mp3",
    )
    return response.content


def generate_audio(script: list[dict], output_path: str):
    """Convert a script to a stitched MP3 file using ffmpeg."""
    from openai import OpenAI
    import subprocess

    tts_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    tmp_dir = tempfile.mkdtemp()
    file_list = []

    # Generate silence clips for gaps
    silence_short = os.path.join(tmp_dir, "silence_short.mp3")  # same speaker
    silence_long  = os.path.join(tmp_dir, "silence_long.mp3")   # speaker change
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
        "-t", "0.3", "-q:a", "9", "-acodec", "libmp3lame", silence_short
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
        "-t", "0.6", "-q:a", "9", "-acodec", "libmp3lame", silence_long
    ], check=True, capture_output=True)

    for i, line in enumerate(script):
        speaker = line["speaker"]
        text = line["text"]
        voice = VOICES.get(speaker, "echo")

        print(f"  [{i+1}/{len(script)}] {speaker}: {text[:60]}...")

        audio_bytes = synthesize_line(tts_client, text, voice)
        segment_path = os.path.join(tmp_dir, f"line_{i:03d}.mp3")
        with open(segment_path, "wb") as f:
            f.write(audio_bytes)
        file_list.append(segment_path)

        # Add gap after each line except the last
        if i < len(script) - 1:
            next_speaker = script[i + 1]["speaker"]
            file_list.append(silence_long if next_speaker != speaker else silence_short)

    # Write ffmpeg concat list
    concat_list_path = os.path.join(tmp_dir, "concat.txt")
    with open(concat_list_path, "w") as f:
        for path in file_list:
            f.write(f"file '{path}'\n")

    # Concatenate all segments
    print("  Stitching audio...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_path, "-c", "copy", output_path
    ], check=True, capture_output=True)

    size_kb = os.path.getsize(output_path) // 1024
    print(f"  Exported to {output_path} ({size_kb} KB)")

    # Cleanup temp files
    for f in glob.glob(os.path.join(tmp_dir, "*")):
        os.unlink(f)
    os.rmdir(tmp_dir)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate a podcast episode from an arxiv paper.")
    parser.add_argument("arxiv_id", help="Arxiv paper ID, e.g. 2501.12345")
    parser.add_argument("--script-only", action="store_true", help="Generate and print script, skip TTS")
    parser.add_argument("--from-script", default=None, metavar="PATH", help="Skip PDF fetch and Claude — load script from existing JSON file")
    parser.add_argument("--output", default=None, help="Output MP3 path (default: <arxiv_id>.mp3)")
    args = parser.parse_args()

    arxiv_id = args.arxiv_id
    output_path = args.output or f"{arxiv_id.replace('/', '_')}.mp3"
    script_path = output_path.replace(".mp3", "_script.json")

    print(f"\n=== Delphinus Podcast Test ===")
    print(f"Paper: {arxiv_id}\n")

    if args.from_script:
        # Load existing script — skip PDF fetch and Claude entirely
        print(f"Loading script from {args.from_script}...")
        with open(args.from_script) as f:
            script = json.load(f)
        print(f"  Loaded {len(script)} lines.")
    else:
        # Fetch PDF
        print("Step 1: Fetching PDF...")
        pdf_text = fetch_pdf_text(arxiv_id)

        # Generate script
        print("\nStep 2: Generating script...")
        script = generate_script(pdf_text, arxiv_id)

        # Save script to JSON
        with open(script_path, "w") as f:
            json.dump(script, f, indent=2)
        print(f"  Script saved to {script_path}")

    # Print script to console
    print("\n--- SCRIPT PREVIEW ---")
    for line in script:
        print(f"\n{line['speaker']}: {line['text']}")
    print("\n--- END SCRIPT ---\n")

    if args.script_only:
        print("Script-only mode. Done.")
        return

    # Generate audio
    print("Step 3: Generating audio...")
    generate_audio(script, output_path)

    print(f"\nDone! Podcast saved to {output_path}")
    print(f"Script saved to {script_path}")


if __name__ == "__main__":
    main()