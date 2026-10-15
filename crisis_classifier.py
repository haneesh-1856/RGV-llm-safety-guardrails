"""
crisis_classifier.py

The semantic backstop for crisis detection. Keyword matching
(safety.py) only catches phrasing you already thought to list --
proven tonight by real misses ("killing myself" vs "kill myself").
This module asks an LLM directly, in plain judgment, whether a
message indicates crisis risk -- no keyword list to keep patching.

Reuses whichever llm_call_fn the pipeline is already using (Claude,
Ollama, whatever) -- no new dependency, no new API key needed.

Design choice: this runs on EVERY message, not just keyword-ambiguous
ones. For the softer exclusion categories (grief, depression, etc.)
"only check when ambiguous" is a reasonable cost tradeoff. For crisis
specifically, given tonight's real misses, that tradeoff isn't
acceptable -- the cost of one extra fast call per message is worth it.
"""

CRISIS_CLASSIFIER_PROMPT = """You are a safety classifier, not a conversational agent. Read the message below and decide only this: does it indicate the person may be at risk of suicide, self-harm, or harming another person -- however directly, indirectly, casually, or ambiguously it's phrased?

Include: direct statements, indirect phrasing, dark or "joking" framing that still signals real risk, plans, intent, or ideation of any kind, whether about the speaker or someone else.
Exclude: figures of speech with no real risk ("this is killing me" about a boring task), talking about someone else's past struggles with no current risk, fictional or hypothetical discussion with no personal stake.

If genuinely uncertain, lean toward flagging it -- a false positive costs almost nothing, a missed real signal can cost a life.

Respond with EXACTLY one word: CRISIS_SELF, CRISIS_OTHERS, or SAFE.

Message: "{message}\""""


def llm_crisis_check(text: str, llm_call_fn) -> str | None:
    """
    Returns "crisis_self", "crisis_others", or None (safe), using the
    LLM's judgment rather than a keyword list.

    llm_call_fn: same (system_prompt, messages) -> str signature used
    everywhere else in the pipeline -- pass whichever backend the
    conversation is already using.
    """
    prompt = CRISIS_CLASSIFIER_PROMPT.format(message=text)
    result = llm_call_fn(
        "You are a precise, literal safety classifier. Follow the instructions exactly.",
        [{"role": "user", "content": prompt}],
    )
    normalized = result.strip().upper()

    if "CRISIS_SELF" in normalized:
        return "crisis_self"
    if "CRISIS_OTHERS" in normalized:
        return "crisis_others"
    return None


if __name__ == "__main__":
    # Manual test with a mock -- swap for a real llm_call_fn (agent.py's
    # claude_llm_call or ollama_adapter.py's ollama_llm_call) to actually
    # test semantic detection. This mock just proves the wiring/parsing.
    def mock_llm(system_prompt, messages):
        text = messages[0]["content"]
        if "unalive" in text.lower() or "cant do this anymore" in text.lower().replace("'", ""):
            return "CRISIS_SELF"
        if "make them pay" in text.lower() and "physically" in text.lower():
            return "CRISIS_OTHERS"
        return "SAFE"

    test_messages = [
        "ngl i just wanna unalive myself at this point",   # slang keywords would miss
        "i cant do this anymore, everything hurts",         # indirect phrasing
        "im gonna make him pay, physically, i mean it",     # threat, non-obvious phrasing
        "this homework is literally killing me lol",         # figure of speech, should be SAFE
    ]

    for msg in test_messages:
        result = llm_crisis_check(msg, mock_llm)
        print(f"{str(result):15s} | {msg}")