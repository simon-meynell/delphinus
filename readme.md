# Delphinus

An automated arxiv digest and standalone PDF podcast tool for researchers.

**Digest** — fetches all new papers from **quant-ph** and **cond-mat.mes-hall** since the last time it ran, analyzes them against your research interests using Claude, generates deep-dive summaries from PDFs, produces a ~10-minute podcast episode about the must-see paper, and sends a formatted HTML email with the audio attached.

**PDF podcast** — standalone script that takes any local PDF (paper, thesis, textbook) and generates a podcast episode of configurable length summarizing it.

---

## How to run

### Digest

```bash
python main.py
```

Each run fetches all papers submitted since the last successful run (capped at 7 days back). After sending, the timestamp of the most recently submitted paper is saved to `last_fetch.json` — that becomes the start of the next run's window. The email header shows the exact range covered: *Papers between 18:00 March 19 2026 and 14:32 March 25 2026*.

**Overriding the date range (testing / backfills):**
```bash
python main.py --from 2026-03-20T14:00:00 --to 2026-03-21T14:00:00
python main.py --from 2026-03-20T14:00:00          # custom start, end = now
python main.py --last-fetch-file my_state.json     # use a different state file
```
When `--from` or `--to` are used, `last_fetch.json` is **not** updated — the override is purely for that run.

**Windows — automated scheduling:**
Use Windows Task Scheduler to run on whatever cadence suits you (daily or a few times a week). Create a new task and set the action to run `python main.py` with the project folder as the working directory. Missed days are handled automatically — the next run will catch up on everything since the last successful one, up to 7 days back.

**Mac/Linux — automated scheduling:**
Use a cron job. Run `crontab -e` and add:
```
0 20 * * * cd /path/to/delphinus && python main.py
```

### PDF podcast

```bash
python pdf_podcast.py /path/to/document.pdf
python pdf_podcast.py /path/to/document.pdf --minutes 30
python pdf_podcast.py /path/to/document.pdf --presenter NICO
python pdf_podcast.py /path/to/document.pdf --script-only    # generate script JSON, skip TTS
python pdf_podcast.py /path/to/document.pdf --from-script doc_script.json  # skip LLM, go straight to TTS
python pdf_podcast.py   # uses PDF_PODCAST_PATH from .env
```

The PDF path is never committed to git — pass it as a CLI argument, or store it as `PDF_PODCAST_PATH` in `.env`.

---

## File overview

### Digest pipeline

#### `main.py`
The entry point. Orchestrates the full pipeline in order: fetch → analyze → summarize PDFs → generate podcast → format → send.

Accepts optional CLI flags to override the fetch window (`--from`, `--to`) and the state file path (`--last-fetch-file`). Exits early with a log entry if the arXiv API returns no papers for the window.

After a successful send, saves the submission date of the newest paper seen to `last_fetch.json` (not the clock time of the run). This means the next run always picks up exactly where the last one left off, with no risk of missing a paper that was submitted before the previous run but hadn't yet appeared in the API.

#### `arxiv_fetcher.py`
Fetches papers from the arXiv API for the configured categories, filtered to the time window determined by `last_fetch.json`.

The window start is read from `last_fetch.json` (the max submission date from the previous run). If no file exists, or the saved date is older than `MAX_LOOKBACK_DAYS` (7 days), the start falls back to 7 days ago. The end is always now (or a `--to` override). Pass `--from`/`--to` on the command line to override either end for testing or backfills.

The window is printed at runtime so you can verify what's being pulled. Returns a list of paper metadata including title, abstract, authors, submission date, and arxiv ID.

#### `analyzer.py`
Sends all paper abstracts to **Claude Haiku** for cost-efficient analysis. Returns a structured JSON response containing:
- `must_see` — the single most important paper of the day (if any truly stands out)
- `core_papers` — papers relevant to your research, rated 🐬 / 🐬🐬 / 🐬🐬🐬
- `foundations_papers` — quantum foundations papers of interest
- `top_3_ids` — the three papers selected for full PDF deep-dives
- `quirky_papers` — weird or delightful papers worth a glance

#### `pdf_fetcher.py`
Downloads the PDF for each of the top 3 papers and extracts the text. Sends the text to **Claude Sonnet** for a detailed summary including key results, methods, why it matters, and caveats. Falls back gracefully if a PDF can't be fetched. Also triggers podcast generation for the must-see paper.

#### `podcast_generator.py`
Generates a ~10-minute podcast episode about the must-see paper. Two stages:

1. **Script generation** — Sends the paper's full PDF text to **Claude Sonnet** to write a dialogue between two hosts, NICO and VENA, both playing experimental quantum physicists (think grad students or postdocs). Each episode randomly assigns one as the expert who has read the paper and the other as the sharp skeptic who hasn't. The script is written for audio: no LaTeX, no figure references, numbers and units spelled out verbally. Output is a JSON array of `{speaker, text}` turns.

2. **Audio rendering** — Converts the script to MP3 using **OpenAI TTS** (`tts-1`), with NICO mapped to the `echo` voice and VENA to `alloy`. Individual lines are rendered as separate audio clips and stitched together with short silence gaps using `ffmpeg`. The final MP3 is attached to the email.

Requires `ffmpeg` on your PATH and an `OPENAI_API_KEY` in your `.env`.

#### `email_formatter.py`
Builds the HTML email from the analysis and PDF summaries. Sections in order: Must-See paper, Deep Dives, Your Research, Quantum Foundations, Weird. Includes a header image of the Delphinus constellation and a dolphin rating legend in the footer.

#### `email_sender.py`
Sends the formatted HTML email via Gmail SMTP. Reads credentials from the `.env` file. Supports multiple recipients as a comma-separated list in `EMAIL_TO`. Attaches the podcast MP3 if one was generated.

#### `last_fetch.json`
State file written after each successful run. Contains a single key, `last_fetch_utc`, set to the submission date of the most recently seen paper. The next run reads this as its window start. You can edit it by hand to re-run a range, or delete it to fall back to a 7-day lookback. Not committed to git.

#### `interests.py`
Your personal configuration file. Edit this to tune what Delphinus pays attention to:
- `CORE_RESEARCH` — topics Claude scores and rates with dolphins
- `FOUNDATIONS_INTERESTS` — quantum foundations topics for a separate section
- `QUIRKY_INTERESTS` — what counts as weird and wonderful
- `IMPORTANT_GROUPS` — research groups whose papers get a badge if the PI is a listed author

---

### Standalone tools

#### `pdf_podcast.py`
Generates a podcast episode from any local PDF — paper, thesis, or textbook.

Short documents (< 30 pages or no chapter structure) get a single-pass script. Longer chaptered documents use a hierarchical pipeline:

1. **Structure detection** (Haiku) — reads the PDF's table of contents, classifies the document, and assigns each chapter a type (background, methods, core contribution, or conclusion)
2. **Chapter summaries** (Haiku, parallel) — fast 2–3 paragraph summary of every chapter
3. **Chapter scripts** (Sonnet, sequential) — each chapter gets a dialogue segment; crucially, every chapter sees the summaries of all other chapters so the hosts can make cross-references naturally. Earlier chapters use Haiku summaries of future chapters for context; later chapters use Sonnet-refined summaries of past ones
4. **Intro segment** (Sonnet, last) — generated after all chapter scripts so it can draw on the fully refined summaries to set up the episode
5. **Audio** — same OpenAI TTS + ffmpeg pipeline as the digest podcast

Podcast length is configurable via `--minutes`. Defaults to ~1 minute per 8 pages (15–60 min range). Core contribution chapters get ~2× the time of background or methods chapters. The presenter/questioner roles are randomly assigned each run (or forced with `--presenter`).

Also saves a `_script.json` alongside the MP3, so you can re-run just the TTS step with `--from-script` without repeating the LLM calls.

#### `document_processor.py`
Pure PDF utility functions used by `pdf_podcast.py`. No LLM calls.
- Metadata extraction (page count, table of contents)
- Page-range text extraction
- Sub-chunking of very long chapters using TOC structure or page-based splits

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

# Optional: default PDF for pdf_podcast.py (can also pass as a CLI argument)
# PDF_PODCAST_PATH=/path/to/your/document.pdf
```

Gmail requires an **App Password** (not your regular password). Enable it at myaccount.google.com/apppasswords — requires 2FA to be turned on.

Set `PODCAST_ENABLED=true` to turn on podcast generation for the digest (requires `OPENAI_API_KEY` and `ffmpeg`).

`ARXIV_CATEGORIES` is a comma-separated list of arxiv category identifiers. See [arxiv.org/category_taxonomy](https://arxiv.org/category_taxonomy) for the full list.

`ffmpeg` must be installed and on your PATH for podcast audio stitching.

---

## Dolphin rating guide

| Rating | Meaning |
|--------|---------|
| 🐬 | Tangential but interesting — worth a glance |
| 🐬🐬 | You should probably look at this one |
| 🐬🐬🐬 | YOWZA — you need to know about this paper |


---

## Approximate cost

**Digest**
~$0.10 per run for a typical day's batch (Haiku for abstract analysis, Sonnet for 3 PDF deep-dives). A weekly catch-up run with several days of papers costs more in Haiku tokens but the PDF deep-dives are still fixed at 3 papers.
~$0.15–0.25 additional per run with podcast enabled (Sonnet script + OpenAI TTS).

**PDF podcast (`pdf_podcast.py`)**
Varies with document length. Rough guide for a 10-chapter, 200-page thesis at 25 minutes:
- Haiku chapter summaries: ~$0.05
- Sonnet chapter scripts + intro: ~$1.50–2.50
- OpenAI TTS (~25 min audio): ~$0.70–1.00
- **Total: ~$2–4 per thesis**

Short papers are much cheaper — similar to a single digest run.
