"""
web/app.py

A local-only Flask web UI for the therapy agent -- open, no login, no
accounts. Runs ONLY on your machine; nothing here is exposed to the
internet. No data leaves your machine except the API calls to
Anthropic that agent.py already makes.

This does NOT duplicate any pipeline logic -- it's a thin wrapper
around the exact same run_pipeline() and claude_llm_call /
claude_scope_check_call functions used by agent.py and tested all
night. If those are correct, this is correct. Every fix tonight
(crisis lock, sticky exclusion, pacing, etc) applies here automatically.

SETUP:
  export ANTHROPIC_API_KEY=sk-...
  python app.py
  -> http://127.0.0.1:5000
"""

import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, render_template, session

from pipeline import run_pipeline, reset_session, PipelineOutcome
from agent import claude_llm_call, claude_scope_check_call

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "local-dev-only-not-secure")

# Per-session conversation history, keyed by a random session id stored
# in the browser cookie. In-memory only -- resets if the server restarts.
_histories: dict[str, list[dict]] = {}


@app.route("/")
def index():
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
        _histories[session["session_id"]] = []
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    session_id = session.get("session_id")
    if not session_id:
        return jsonify({"error": "no session"}), 400

    user_message = request.json.get("message", "")
    history = _histories.setdefault(session_id, [])

    result = run_pipeline(
        session_id=session_id,
        raw_text=user_message,
        history=history,
        llm_call_fn=claude_llm_call,
        crisis_llm_call_fn=claude_scope_check_call,
    )

    if result.reply:
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": result.reply})

    return jsonify({
        "reply": result.reply,
        "outcome": result.outcome.value,
        "phase": result.phase.value if result.phase else None,
    })


@app.route("/reset", methods=["POST"])
def reset():
    session_id = session.get("session_id")
    if session_id:
        _histories[session_id] = []
        # Also clear phase, counters, last redirect, and crisis flags;
        # previously these carried over into the next conversation.
        reset_session(session_id)
    return jsonify({"ok": True})


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("WARNING: ANTHROPIC_API_KEY is not set. Set it before running:")
        print("  export ANTHROPIC_API_KEY=sk-...")
    print("\nStarting local-only server at http://127.0.0.1:5000")
    print("This is NOT exposed to the internet -- only your own machine can reach it.\n")
    app.run(host="127.0.0.1", port=5000, debug=False)