"""
agent.py

The real model adapter + a manual CLI test loop. All orchestration
logic (safety checks, phase routing, state updates) now lives in
pipeline.py -- this file's only job is:
  1. provide a real llm_call_fn that calls the Claude API
  2. drive a simple terminal chat loop for manual testing

Requires: pip install anthropic
Set your API key: export ANTHROPIC_API_KEY=sk-...
"""

import os
import time
import anthropic

from pipeline import run_pipeline, PipelineOutcome

MODEL = "claude-sonnet-5"
SCOPE_CHECK_MODEL = "claude-haiku-4-5-20251001"  # small, fast, cheap -- but reliable, which is what this narrow task needs

# Current per-million-token rates (input, output). Sonnet 5 is at
# introductory pricing through Aug 31, 2026 -- update SONNET_RATES
# after that if you're still testing then. Cost is still tracked
# internally (real total printed at the end of the session) -- just
# not printed after every single turn anymore.
SONNET_RATES = (2.00, 10.00)
HAIKU_RATES = (1.00, 5.00)

_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def _create_with_retry(**kwargs):
    """
    Real failure found in live testing: anthropic.OverloadedError (HTTP
    529) crashed the entire CLI session on a single transient moment
    of Anthropic's API being at capacity -- not a bug in this code,
    just something that happens occasionally and needs to be retried,
    not treated as fatal. Same idea covers rate limits (429) and
    transient server errors (500/502/503).

    Retries a few times with a short, increasing wait between attempts.
    If it's still failing after that, it really is down -- the error
    surfaces normally rather than being swallowed silently.
    """
    max_attempts = 4
    for attempt in range(max_attempts):
        try:
            return _client.messages.create(**kwargs)
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            status = getattr(e, "status_code", None)
            transient = status in (429, 500, 502, 503, 529) or isinstance(e, anthropic.APIConnectionError)
            if not transient or attempt == max_attempts - 1:
                raise
            wait = 2 ** attempt  # 1, 2, 4 seconds
            print(f"  [Anthropic API temporarily unavailable ({status or 'connection error'}) -- retrying in {wait}s...]")
            time.sleep(wait)

_session_cost = {"total": 0.0, "calls": 0}


def _track_cost(usage, rates: tuple[float, float]):
    input_cost = (usage.input_tokens / 1_000_000) * rates[0]
    output_cost = (usage.output_tokens / 1_000_000) * rates[1]
    _session_cost["total"] += input_cost + output_cost
    _session_cost["calls"] += 1


def _extract_text(response, label: str = "") -> str:
    """
    Real bug found in live testing: response.content[0] is not always
    the text reply. Claude can include other block types in the content
    list (e.g. ThinkingBlock, for models with extended/interleaved
    thinking) -- when that happens, content[0] has no .text attribute
    and content[0].text crashes. This searches the content list for the
    actual text block instead of assuming it's always first.

    ALSO real, found in the same session: a completely empty reply can
    happen if the token budget runs out before any visible text is
    produced. If that happens now, it prints a loud, visible warning --
    this exact failure mode, happening silently inside the classifier,
    is what caused confusing "why is this so dumb" behavior earlier:
    an empty classifier response falls through to a default exclusion
    in scope_classifier.py, which looks like random bad judgment from
    the outside, when it's actually a truncation bug with no visible
    signal at all. Now it prints instead of failing silently.
    """
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    print(f"  [WARNING] {label or 'a model call'} returned no text -- likely hit its token limit before producing output.")
    return ""


def claude_llm_call(system_prompt: str, messages: list[dict]) -> str:
    """
    The real llm_call_fn passed into run_pipeline(). Matches the
    signature run_pipeline expects: (system_prompt, messages) -> str.
    Swappable for a different provider or a mock without touching
    pipeline.py at all.

    max_tokens history: 300 -> 1024 -> 2048. The second raise was
    another REAL bug found in live testing, not preemptive caution:
    a genuinely good, detailed comparison response (solo room vs.
    stranger roommates, two structured sections) got cut off mid-word
    at 1024 tokens -- "Stranger ro" -- and the user had to notice and
    prompt a continuation themselves. Phase 2's own rules (weigh
    options, give a real concrete draft) naturally produce longer
    replies than Phase 1 ever does, so this ceiling needs real
    headroom, not just enough for a short reply.
    """
    response = _create_with_retry(
        model=MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=messages,
    )
    _track_cost(response.usage, SONNET_RATES)
    return _extract_text(response, label="claude_llm_call (conversation)")


def claude_scope_check_call(system_prompt: str, messages: list[dict]) -> str:
    """
    Dedicated to the scope classifier only -- passed as
    crisis_llm_call_fn (parameter name kept for backward compatibility
    with pipeline.py), separate from claude_llm_call. Now covers
    crisis AND every exclusion category, not just crisis -- see
    scope_classifier.py. Still deliberately points at Haiku even when
    the main conversation uses Sonnet or a free/local model:
    classification is a narrow task where a small, reliable model is
    both cheaper and sufficient, and decoupling it means detection
    quality never depends on whichever backend runs the conversation.

    max_tokens raised from 20 to 200 -- this was the SAME bug as the
    one fixed in claude_llm_call (a too-small token limit truncating
    the response before any visible text, if the model does any
    internal reasoning first), just never applied here too. A silent
    empty result here falls through to "excluded / unclear_classification"
    in scope_classifier.py, which would look exactly like random,
    unexplainable over-exclusion from the outside -- a very plausible
    real cause of "why does this seem dumb" behavior, not a reasoning
    failure in the model itself.
    """
    response = _create_with_retry(
        model=SCOPE_CHECK_MODEL,
        max_tokens=300,  # raised from 200 -- the classifier now reasons briefly before its final answer instead of being forced into an instant one-word response (see scope_classifier.py), so it needs real room for that reasoning, not just a single word
        system=system_prompt,
        messages=messages,
    )
    _track_cost(response.usage, HAIKU_RATES)
    return _extract_text(response, label="claude_scope_check_call (classifier)")


# Kept as an alias so ollama_adapter.py's existing import of
# claude_crisis_check_call still works without changes.
claude_crisis_check_call = claude_scope_check_call


if __name__ == "__main__":
    session_id = "cli-session-1"
    history: list[dict] = []

    print("Therapy agent MVP -- real Claude backend. Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ")
        if user_input.strip().lower() == "quit":
            break

        result = run_pipeline(
            session_id=session_id,
            raw_text=user_input,
            history=history,
            llm_call_fn=claude_llm_call,
            crisis_llm_call_fn=claude_scope_check_call,
        )

        print(f"Agent: {result.reply}\n")

        if result.reply:
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": result.reply})

    print(f"\nSession ended. Total spent: ${_session_cost['total']:.4f} across {_session_cost['calls']} model calls.")

