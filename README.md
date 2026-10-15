# RGV — LLM Safety Guardrails for a Worry-Support Agent

RGV is a conversational support agent for **specific, actionable worries** — exam stress, a work deadline, a conflict with someone, procrastination. It helps a person step back from a spiraling thought and then reason toward *their own* solution, rather than handing them one.

Most of this project is the safety layer around that conversation: detecting crisis, recognising when something is outside what a tool like this should handle (clinical, legal, medical, abuse, grief, …), and routing those cases to real resources instead of attempting to "fix" them.

> **This is not a therapy or crisis service.** It is a research/prototype project. If you are in crisis, call or text **988** (US) or find a local line at [findahelpline.com](https://findahelpline.com).

## How it works

Every message goes through a fixed pipeline (`pipeline.py`). Routing decisions are made by code and session state — not by the conversational model.

```
user message
   │
   ▼
1. Intake            receive_message() → IncomingMessage
2. Crisis check      keyword layer + LLM classifier  ──► crisis response (hard stop, session locked)
3. Scope check       keyword layer + LLM classifier  ──► exclusion response + appropriate resource
4. Phase routing     from session state (state.py)
5. Model call        system prompt for the current phase only (prompts.py)
6. State update      turn count, worry log, phase advance
```

**Two-layer safety detection**

- `safety.py` — deterministic keyword matching for crisis (self / others) and exclusion categories, plus the fixed crisis and exclusion response texts.
- `scope_classifier.py` — an LLM "semantic backstop" that classifies every message into one category (crisis, grief, trauma, depression, generalized anxiety, other clinical, disordered eating, substance use, chronic pattern, legal, medical, financial crisis, mandatory reporting, relational severe, family coercion, peer violence, in-scope, or no worry). The prompt includes rules learned from real misclassifications, such as topic adjacency not being enough to exclude, and meta-questions about the agent not counting as personal disclosures.

**Conversation phases** (`state.py`, `prompts.py`)

- **Phase 1 — Detachment:** a brief pause and acknowledgment, with no analysis, advice or reassurance about outcomes. Advances after 2 turns.
- **Phase 2 — Reasoning:** narrowing questions, structured reflections, and splitting what is controllable from what isn't, while the person lands on their own decision.
- Separate prompts handle small talk, crisis acknowledgment, exclusion acknowledgment, and grief presence.

**Session safeguards**: a crisis lock (once real crisis intent is stated, later turns can't slip back into open conversation), sticky exclusions, and checks that stop the model from repeating or paraphrasing the fixed safety text.

## Project layout

| Path | Purpose |
|---|---|
| `pipeline.py` | Orchestrates the six steps; `run_pipeline()` is the entry point |
| `safety.py` | Keyword-based crisis/exclusion detection and response texts |
| `scope_classifier.py` | LLM scope/safety classifier prompt and call |
| `crisis_classifier.py` | Standalone LLM crisis classifier |
| `state.py` | Session store, phases, phase-advance rule |
| `prompts.py` | System prompts (core rules + per-phase prompts) |
| `agent.py` | Claude adapter (Sonnet for conversation, Haiku for classification) and a CLI chat loop with cost tracking |
| `ollama_adapter.py` | Free, local alternative using Ollama for conversation turns |
| `web/` | Local Flask web UI (`app.py`, `templates/`) |
| `eval/` | Deterministic keyword-layer tests and scenario sets |
| `run_classification_test.py` | Runs a labelled CSV through the full pipeline and records responses |
| `classification_test_set.csv` / `classification_results.csv` | Test statements with ground-truth labels, and recorded results |
| `Test data/`, `Test data after fix/` | Transcripts of 50 manual test conversations, before and after fixes |

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt   # anthropic, requests, flask
```

Set your Anthropic API key (never commit it):

```bash
# macOS / Linux
export ANTHROPIC_API_KEY=your-key-here
# Windows PowerShell
$env:ANTHROPIC_API_KEY = "your-key-here"
```

## Running

**CLI chat (Claude):**

```bash
python agent.py
```

**Web UI (local only):**

```bash
python web/app.py
# open http://127.0.0.1:5000
```

**Local model via Ollama** — install [Ollama](https://ollama.com/download), run `ollama pull mistral`, then:

```bash
python ollama_adapter.py
```

The `USE_CLAUDE_FOR_SAFETY` flag in `ollama_adapter.py` controls whether safety classification uses Claude Haiku (recommended) or the local model. Testing showed local models missing crisis phrasing, so run fully local only for structural testing.

## Evaluation

```bash
# Deterministic keyword-layer tests, with no API calls and no cost
python eval/run_eval.py

# Full-pipeline run over a labelled statement set (makes API calls)
python run_classification_test.py classification_test_set.csv
```

`run_classification_test.py` deliberately doesn't auto-score. It records the full agent response for each statement plus a rough `auto_hint`, and leaves the `match` column for manual review, because correct handling sometimes goes through a different path than the one a statement was designed to test.

## Author

Built by **Haneesh Chowdary Sriram** — [LinkedIn](https://www.linkedin.com/in/haneesh-sriram/)
