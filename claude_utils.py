"""
Shared Claude model settings and call helpers.

Every Claude model name used by Delphinus lives here, so upgrading a model is a
one-line change.
"""

# ─── Models ───────────────────────────────────────────────────────────────────

# Haiku handles the high-volume, cheap steps: abstract triage, TOC parsing,
# quick chapter summaries.
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Sonnet handles the long-form writing: PDF deep-dives and podcast scripts.
SONNET_MODEL = "claude-sonnet-5-5"

# Sonnet 5.5 always thinks a little before answering, and thinking is billed as
# output tokens. "low" keeps it short, which is plenty for summaries and scripts.
# Raise to "medium" or "high" if script quality ever feels thin.
SONNET_EFFORT = "low"

# Thinking counts toward max_tokens, so leave headroom beyond the reply itself.
# You only pay for tokens actually generated, not for this ceiling.
SONNET_MAX_TOKENS = 16000


# ─── Helpers ──────────────────────────────────────────────────────────────────

def response_text(response) -> str:
    """
    Return the text of a Claude reply.

    Newer models can put a (possibly empty) thinking block before the text,
    so read blocks by type rather than taking content[0].
    """
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request (stop_reason: refusal)")
    return "".join(b.text for b in response.content if b.type == "text").strip()


def ask_sonnet(client, prompt: str) -> str:
    """Send a single-turn prompt to Sonnet and return the reply text."""
    response = client.beta.messages.create(
        model=SONNET_MODEL,
        max_tokens=SONNET_MAX_TOKENS,
        output_config={"effort": SONNET_EFFORT},
        # If Sonnet declines on safety grounds, the API retries on a fallback
        # model inside the same call instead of returning an empty refusal.
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
        messages=[{"role": "user", "content": prompt}],
    )
    return response_text(response)
