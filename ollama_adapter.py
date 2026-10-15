"""
ollama_adapter.py

A free, fully local alternative to agent.py's Claude adapter for the
CONVERSATIONAL turns. Same signature as claude_llm_call() in agent.py
-- (system_prompt, messages) -> str -- so it drops straight into
run_pipeline() with zero changes to pipeline.py, safety.py, state.py,
or prompts.py.

IMPORTANT: given real crisis-detection misses found in testing with
Mistral, this file does NOT use the free local model for the crisis
classifier. It uses Claude Haiku instead (small, cheap, but
reliable), imported from agent.py, and passed as crisis_llm_call_fn.
This means: free conversation, paid-but-cheap safety detection. If
you truly want zero cost including crisis detection, you'd need to
pass ollama_llm_call as crisis_llm_call_fn too -- but I would not
recommend that given what testing has already shown.

SETUP (run on your own machine, not in a sandbox):
1. Install Ollama: https://ollama.com/download
2. Pull a model:      ollama pull llama3.3
   (or a smaller one if your machine is limited: ollama pull mistral)
3. Ollama runs a local server automatically after install, on
   http://localhost:11434 -- no API key, no account, no cost.
4. pip install requests

NO ANTHROPIC KEY YET? Set USE_CLAUDE_FOR_SAFETY = False below to run
fully free, no key required at all. Read the warning next to it
first -- this is meant as a "get something running today" option,
not the setup to trust for anything touching real crisis content.
Switch it back to True once you have a key (even a free trial one).
"""

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "mistral"  # swap for "mistral", "qwen2.5", etc. depending on what you pulled

# If True: crisis/exclusion detection uses Claude Haiku (reliable, tiny
# cost, requires ANTHROPIC_API_KEY). If False: uses the SAME free local
# model as the conversation -- meaning the classifier has the exact
# reliability problems already demonstrated in real testing tonight
# (missed crisis phrasing, self-contradiction, looping). Only set this
# False for early structural testing, never for anything real.
USE_CLAUDE_FOR_SAFETY = False


def ollama_llm_call(system_prompt: str, messages: list[dict]) -> str:
    """
    Matches the exact signature run_pipeline() expects, so it's a
    drop-in replacement for claude_llm_call from agent.py.
    """
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": False,
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["message"]["content"]


if __name__ == "__main__":
    from pipeline import run_pipeline, PipelineOutcome

    if USE_CLAUDE_FOR_SAFETY:
        from agent import claude_scope_check_call
        crisis_fn = claude_scope_check_call
        safety_note = "Claude Haiku for crisis/scope check"
    else:
        crisis_fn = ollama_llm_call
        safety_note = f"{MODEL} for crisis/scope check too -- LOWER RELIABILITY, testing only"

    session_id = "ollama-cli-session"
    history: list[dict] = []

    print(f"Therapy agent MVP -- local Ollama ({MODEL}) for conversation, {safety_note}. Type 'quit' to exit.\n")
    if not USE_CLAUDE_FOR_SAFETY:
        print("WARNING: running fully free mode. Crisis/exclusion detection is NOT reliable")
        print("in this mode -- do not use for anything beyond structural testing.\n")

    while True:
        user_input = input("You: ")
        if user_input.strip().lower() == "quit":
            break

        result = run_pipeline(
            session_id=session_id,
            raw_text=user_input,
            history=history,
            llm_call_fn=ollama_llm_call,
            crisis_llm_call_fn=crisis_fn,
        )

        print(f"Agent: {result.reply}\n")

        # See agent.py for why this changed from HANDLED-only to any
        # non-empty reply -- follow-up questions about a crisis/exclusion/
        # small-talk reply need the model to actually remember saying it.
        if result.reply:
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": result.reply})