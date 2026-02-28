# ✦ Delphinus

An automated daily arxiv digest delivered by email every evening. Fetches new papers from **quant-ph** and **cond-mat.mes-hall**, analyzes them against your research interests using Claude, generates deep-dive summaries from PDFs, produces a podcast episode about the must-see paper, and sends a formatted HTML email with the audio attached.

---

## How to run

```bash
python main.py
```

**Windows — automated scheduling:**
Use Windows Task Scheduler to run automatically at 8:00 PM Sunday–Friday. Create a new task, set the trigger to a weekly schedule on Sun–Fri at 8:00 PM, and set the action to run `python main.py` with the project folder as the working directory. Saturday and Sunday runs are also safe — the fetcher will return Friday's announcement batch as a catch-up digest.

**Mac/Linux — automated scheduling:**
Use a cron job. Run `crontab -e` and add:
```
0 20 * * 0-5 cd /path/to/delphinus && python main.py
```

---

## File overview

### `main.py`
The entry point. Orchestrates the full pipeline in order: fetch → analyze → summarize PDFs → generate podcast → format → send.

### `arxiv_fetcher.py`
Fetches recent papers from arxiv using the arxiv API. Uses arxiv's 2:00 PM Eastern submission cutoff schedule to determine the correct window of papers for each run:

- **Monday** — fetches submissions from Friday 2PM through Monday 2PM, capturing the full weekend bundle
- **Tuesday–Friday** — fetches submissions from the previous day 2PM through today 2PM
- **Saturday/Sunday** — fetches Friday's batch only (Thursday 2PM through Friday 2PM); weekend submissions are excluded as they haven't been announced yet

Papers submitted after today's cutoff are excluded, as they belong to tomorrow's announcement. The window is printed at runtime so you can verify what's being pulled. Returns a list of paper metadata including title, abstract, authors, and arxiv ID.

### `analyzer.py`
Sends all paper abstracts to **Claude Haiku** for cost-efficient analysis. Returns a structured JSON response containing:
- `must_see` — the single most important paper of the day (if any truly stands out)
- `core_papers` — papers relevant to your research, rated 🐬 / 🐬🐬 / 🐬🐬🐬
- `foundations_papers` — quantum foundations papers of interest
- `top_3_ids` — the three papers selected for full PDF deep-dives
- `quirky_papers` — weird or delightful papers worth a glance

### `pdf_fetcher.py`
Downloads the PDF for each of the top 3 papers and extracts the text. Sends the text to **Claude Sonnet** for a detailed summary including key results, methods, why it matters, and caveats. Falls back gracefully if a PDF can't be fetched. Also triggers podcast generation for the must-see paper.

### `podcast_generator.py`
Generates a ~10-minute podcast episode about the must-see paper. Two stages:

1. **Script generation** — Sends the paper's full PDF text to **Claude Sonnet** to write a dialogue between two hosts, NICO and VENA, both playing experimental quantum physicists (think grad students or postdocs). Each episode randomly assigns one as the expert who has read the paper and the other as the sharp skeptic who hasn't. The script is written for audio: no LaTeX, no figure references, numbers and units spelled out verbally. Output is a JSON array of `{speaker, text}` turns.

2. **Audio rendering** — Converts the script to MP3 using **OpenAI TTS** (`tts-1`), with NICO mapped to the `echo` voice and VENA to `alloy`. Individual lines are rendered as separate audio clips and stitched together with short silence gaps using `ffmpeg`. The final MP3 is attached to the email.

Requires `ffmpeg` to be installed and available on your PATH, and an `OPENAI_API_KEY` in your `.env`.

### `email_formatter.py`
Builds the HTML email from the analysis and PDF summaries. Sections in order: Must-See paper, Deep Dives, Your Research, Quantum Foundations, Weird. Includes a header image of the Delphinus constellation and a dolphin rating legend in the footer.

### `email_sender.py`
Sends the formatted HTML email via Gmail SMTP. Reads credentials from the `.env` file. Supports multiple recipients as a comma-separated list in `EMAIL_TO`. Attaches the podcast MP3 if one was generated.

### `interests.py`
Your personal configuration file. Edit this to tune what Delphinus pays attention to:
- `CORE_RESEARCH` — topics Claude scores and rates with dolphins
- `FOUNDATIONS_INTERESTS` — quantum foundations topics for a separate section
- `QUIRKY_INTERESTS` — what counts as weird and wonderful
- `IMPORTANT_GROUPS` — research groups whose papers get a badge if the PI is a listed author

---

## Configuration

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
EMAIL_ADDRESS=your_sending_address@gmail.com
EMAIL_APP_PASSWORD=your_gmail_app_password
EMAIL_TO=recipient1@gmail.com,recipient2@gmail.com
PODCAST_ENABLED=false
ARXIV_CATEGORIES=quant-ph,cond-mat.mes-hall
```

Gmail requires an **App Password** (not your regular password). Enable it at myaccount.google.com/apppasswords — requires 2FA to be turned on.

Set `PODCAST_ENABLED=true` to turn on podcast generation (requires `OPENAI_API_KEY` and `ffmpeg`).

`ARXIV_CATEGORIES` is a comma-separated list of arxiv category identifiers. See [arxiv.org/category_taxonomy](https://arxiv.org/category_taxonomy) for the full list.

`ffmpeg` must be installed and on your PATH for podcast audio stitching.

`pytz` must be installed for the submission window calculation: `pip install pytz`.

---

## Dolphin rating guide

| Rating | Meaning |
|--------|---------|
| 🐬 | Tangential but interesting — worth a glance |
| 🐬🐬 | You should probably look at this one |
| 🐬🐬🐬 | YOWZA — you need to know about this paper |

Not every day has a 🐬🐬🐬 paper, and that's okay.

---

## Approximate cost

~$0.10 USD per run for the digest (Haiku for abstract analysis, Sonnet for 3 PDF deep-dives).
~$0.15–0.25 USD per run for the podcast (Sonnet for script generation, OpenAI TTS for audio rendering — varies with paper length and script length).
~$6–10 USD/month for daily runs with podcast enabled.