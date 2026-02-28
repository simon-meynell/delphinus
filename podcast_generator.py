import os
import json
import tempfile
import glob
import random
import anthropic
from dotenv import load_dotenv

load_dotenv()

# ─── Voices ──────────────────────────────────────────────────────────────────

VOICES = {
    "NICO": "echo",
    "VENA": "alloy",
}

# ─── Prompt ──────────────────────────────────────────────────────────────────

SCRIPT_PROMPT = """You are writing a podcast script for a 10-minute episode about a quantum physics paper.

The podcast features two hosts — both experimental quantum physicists (think grad students or 
postdocs working on color centers or quantum hardware). They are peers, not teacher and student.

{role_block}

The conversation should feel like two experimentalists in a lab kitchen genuinely tearing into 
a paper — one has read it carefully, the other hasn't but is sharp enough to probe hard. 
They care about whether results are real, reproducible, and relevant to their own work.
Neither is explaining to a general audience; they're explaining to each other.

IMPORTANT RULES:
- Begin with a hook that tells the listener why the paper is noteworthy, following this short hook, make sure to state the group and paper title.
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
- IMPORTANT: If something wouldn't be common knowledge for an experimentalist studying color centers then it needs some degree of explanation.
- Try to find examples of how it might relate to experiments for physicists studying color centers in a lab

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


# ─── Script Generation ───────────────────────────────────────────────────────

def generate_script(pdf_text: str) -> list[dict]:
    """Generate a podcast dialogue script from paper text using Claude."""
    client = anthropic.Anthropic()

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


# ─── Audio Generation ────────────────────────────────────────────────────────

def generate_audio(script: list[dict], output_path: str):
    """Convert a dialogue script to a stitched MP3 using OpenAI TTS + ffmpeg."""
    from openai import OpenAI
    import subprocess

    tts_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    tmp_dir = tempfile.mkdtemp()
    file_list = []

    # Generate silence clips
    silence_short = os.path.join(tmp_dir, "silence_short.mp3")
    silence_long  = os.path.join(tmp_dir, "silence_long.mp3")
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

        # Encode preview as ASCII to avoid cp1252 errors on Windows consoles
        preview = text[:60].encode("ascii", errors="replace").decode("ascii")
        print(f"  [{i+1}/{len(script)}] {speaker}: {preview}...")

        response = tts_client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            response_format="mp3",
        )
        segment_path = os.path.join(tmp_dir, f"line_{i:03d}.mp3")
        with open(segment_path, "wb") as f:
            f.write(response.content)
        file_list.append(segment_path)

        if i < len(script) - 1:
            next_speaker = script[i + 1]["speaker"]
            file_list.append(silence_long if next_speaker != speaker else silence_short)

    concat_list_path = os.path.join(tmp_dir, "concat.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for path in file_list:
            f.write(f"file '{path}'\n")

    print("  Stitching audio...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_path, "-c", "copy", output_path
    ], check=True, capture_output=True)

    size_kb = os.path.getsize(output_path) // 1024
    print(f"  Podcast saved to {output_path} ({size_kb} KB)")

    for f in glob.glob(os.path.join(tmp_dir, "*")):
        os.unlink(f)
    os.rmdir(tmp_dir)


# ─── Main Entry Point ────────────────────────────────────────────────────────

def generate_podcast(pdf_text: str, arxiv_id: str, output_path: str) -> str | None:
    """
    Full pipeline: generate script from PDF text, render to MP3.
    Returns the output path on success, None on failure.
    """
    try:
        script = generate_script(pdf_text)
        generate_audio(script, output_path)
        return output_path
    except Exception as e:
        print(f"  Podcast generation failed: {e}")
        return None