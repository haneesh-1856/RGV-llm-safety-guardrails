"""
Session state: tracks which phase a conversation is in, and a light
history of what's been raised. In-memory dict for the MVP — swap for
a real database (Postgres, SQLite, whatever) once this leaves your
laptop.
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class Phase(str, Enum):
    DETACHMENT = "detachment"   # Phase 1
    REASONING = "reasoning"     # Phase 2


@dataclass
class WorryEntry:
    text: str
    logged_at: datetime
    resolved: bool = False


@dataclass
class Session:
    session_id: str
    phase: Phase = Phase.DETACHMENT
    turn_count_in_phase: int = 0
    worry_log: list[WorryEntry] = field(default_factory=list)
    last_exclusion_reason: str | None = None  # sticky -- see pipeline.py

    # --- CRISIS LOCK, added after the most severe finding of the
    # whole project: once someone states real crisis intent (self or
    # others), a short follow-up like "r u a parrot" broke the
    # boundary into full open-ended conversation TWICE in one short
    # test session -- and the resulting reply didn't even restate the
    # actual crisis number, just a vague reference to "a crisis line".
    #
    # Root cause: crisis detection had ZERO session memory. Every
    # other sticky protection built tonight only applies to the
    # "excluded" pathway; crisis relied entirely on the classifier
    # catching it fresh, every single message, with nothing checking
    # session history at all.
    #
    # Fix: once True, EVERY subsequent message in this session
    # returns the crisis response, unconditionally, no classifier
    # call needed. This is deliberately NOT subject to any "is this a
    # genuine topic change" judgment call, unlike the softer exclusion
    # categories -- the cost of staying locked too long is trivial
    # (someone sees crisis resources again); the cost of a wrong
    # "this is a new topic" call here is not. Never auto-releases
    # within a session. ---
    crisis_self_triggered: bool = False
    crisis_others_triggered: bool = False

    # --- GRIEF PRESENCE, PROTOTYPE -- NOT clinically reviewed or
    # approved. Built at the user's explicit request to prototype a
    # bounded alternative to immediate grief redirect, for evaluation
    # WITH a therapist before any real use, not as a production change.
    #
    # The concern this attempts to balance, stated honestly: unbounded
    # conversational engagement with unfixable grief is the same
    # pattern behind documented real-world harm from other AI systems
    # staying present through a crisis instead of redirecting. The
    # counter-argument, also real: the current redirect is closer to
    # "not me" than genuine comfort, which may itself be a failure of
    # care, not just an overcautious one.
    #
    # This field tracks how many genuine "presence" exchanges have
    # been used for the CURRENT grief thread, hard-capped in
    # pipeline.py at GRIEF_PRESENCE_MAX_TURNS. The redirect is
    # GUARANTEED once that cap is hit -- never optional, never
    # extendable by anything said in the conversation. ---
    grief_presence_turns_used: int = 0

    # --- Counter for the acknowledgment-duplication fix in
    # pipeline.py. Increments on every excluded turn (regardless of
    # category), used only to rotate the safe fallback acknowledgment
    # text when the model's own acknowledgment is discarded for
    # overlapping the static redirect -- so a sequence of fallback
    # turns doesn't itself become a new, visible repetition. Not
    # reused from turn_count_in_phase, which does not increment
    # during excluded turns and would otherwise always select the
    # same fallback. ---
    exclusion_turn_count: int = 0
    crisis_message_count: int = 0  # tracks occurrences THIS session, for condensed-vs-full text

    # --- Tracks whether the repetition-complaint fast path has
    # already fired once for the CURRENT exclusion thread. First
    # complaint gets the short, honest "I'm not going to repeat
    # myself" response. A SECOND complaint in the same thread means
    # that response itself didn't land or the user is still stuck --
    # repeating even the fixed wording a second time recreates a
    # smaller version of the same duplication problem. On a second
    # complaint, this forces a genuine fresh classification instead
    # of reusing the fallback text again. Reset whenever a new
    # exclusion begins (a genuinely different category, or the same
    # category re-triggering fresh after real content change). ---
    repetition_complaint_used: bool = False

    # --- IN-SCOPE CONTINUITY FLAG, the mirror-image gap to
    # last_exclusion_reason above. Found via a real transcript: "now
    # I'm feeling more depressed" (real content) correctly stayed
    # in-scope, but the VERY NEXT message -- "okay", carrying no
    # content at all -- got independently, freshly reclassified and
    # landed on EXCLUDED. Two adjacent turns, opposite outcomes, with
    # the second one decided by essentially nothing.
    #
    # Every continuity protection built tonight only guarded ONE
    # direction: "already excluded, stay excluded on a low-content
    # follow-up." Nothing protected the other direction: "already
    # in-scope, stay in-scope on a low-content follow-up." A message
    # with near-zero content carries near-zero evidence either way --
    # defaulting it to a fresh, full 19-category classification isn't
    # caution, it's noise dressed up as caution.
    #
    # Set True whenever a message is actually classified in_scope;
    # checked before the next message is classified at all -- if
    # True and the new message is low-content, skip reclassification
    # entirely and stay in the current phase. ---
    last_classification_in_scope: bool = False

    def advance_to_reasoning(self):
        self.phase = Phase.REASONING
        self.turn_count_in_phase = 0

    def reset_to_detachment(self):
        self.phase = Phase.DETACHMENT
        self.turn_count_in_phase = 0

    def log_worry(self, text: str):
        self.worry_log.append(WorryEntry(text=text, logged_at=datetime.now()))


class SessionStore:
    """In-memory store. One process only — fine for local dev/testing."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id=session_id)
        return self._sessions[session_id]

    def reset(self, session_id: str) -> None:
        # Drop all state for this session (phase, turn counters, last
        # redirect, crisis flags) so the next message starts fresh.
        self._sessions.pop(session_id, None)


# --- Phase transition logic ---------------------------------------
# This is the piece that used to live entirely inside the prompt.
# Moving it here means the transition is decided by code, not by
# hoping the model remembers to do it. Start simple: transition after
# N turns in detachment. Replace with a real signal (a lightweight
# sentiment/arousal classifier, or explicit user confirmation) once
# you have data on what actually indicates "ready to move on."

DETACHMENT_MAX_TURNS = 2


def should_advance_phase(session: Session) -> bool:
    return (
        session.phase == Phase.DETACHMENT
        and session.turn_count_in_phase >= DETACHMENT_MAX_TURNS
    )