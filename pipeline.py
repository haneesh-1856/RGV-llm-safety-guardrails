"""
pipeline.py

Step 1: message intake.

This is the entry point every incoming message passes through before
anything else touches it. Its only job right now is to package the
raw input into a structured object -- no safety checks, no LLM calls,
no phase logic yet. Those get added as their own steps, each testable
in isolation, per the pipeline diagram.

Keeping this step this small is deliberate: if intake ever needs to
change (e.g. adding a user_id, a client platform tag, rate-limit
metadata), it changes here without touching anything downstream.
"""

from dataclasses import dataclass
from datetime import datetime
import uuid


@dataclass
class IncomingMessage:
    """
    The structured form every raw text input becomes before entering
    the rest of the pipeline (crisis check, exclusion check, etc.).
    """
    message_id: str
    session_id: str
    text: str
    received_at: datetime

    def is_empty(self) -> bool:
        return not self.text.strip()


def receive_message(session_id: str, raw_text: str) -> IncomingMessage:
    """
    Step 1 of the pipeline. Takes whatever raw text came in from the
    user (chat UI, API request, whatever the transport layer is) and
    turns it into an IncomingMessage.

    Deliberately does NOT:
    - run any safety checks (that's step 2)
    - touch session state / phase (that's step 3+)
    - call any model (that's later)

    This keeps step 1 a pure, trivially testable function: same input,
    same output, no side effects, no dependencies on anything else in
    the system.
    """
    return IncomingMessage(
        message_id=str(uuid.uuid4()),
        session_id=session_id,
        text=raw_text,
        received_at=datetime.now(),
    )



# ---------------------------------------------------------------------
# Steps 2-6: the rest of the pipeline, orchestrated.
#
# Each step is imported from its own module -- this file just calls
# them in order and decides what happens based on each result. No
# safety or phase logic lives HERE; this is wiring, not decision-making.
# ---------------------------------------------------------------------

from dataclasses import dataclass, field
from enum import Enum

from safety import (
    check_message, SafetyCategory, CRISIS_RESPONSE, CRISIS_OTHERS_RESPONSE,
    EXCLUSION_RESPONSES,
)
from scope_classifier import llm_scope_check
from state import SessionStore, Phase, should_advance_phase
from prompts import PHASE_1_DETACHMENT_PROMPT, PHASE_2_REASONING_PROMPT, SMALL_TALK_PROMPT, CRISIS_ACKNOWLEDGMENT_PROMPT, EXCLUSION_ACKNOWLEDGMENT_PROMPT, GRIEF_PRESENCE_PROMPT


class PipelineOutcome(str, Enum):
    CRISIS = "crisis"
    CRISIS_OTHERS = "crisis_others"
    EXCLUDED = "excluded"
    NO_WORRY = "no_worry"        # small talk, greetings, factual questions
    HANDLED = "handled"          # a real LLM-generated reply happened
    EMPTY_INPUT = "empty_input"


@dataclass
class PipelineResult:
    outcome: PipelineOutcome
    reply: str
    phase: Phase | None = None
    exclusion_reason: str | None = None


_store = SessionStore()


def reset_session(session_id: str) -> None:
    """Clear all per-session state so a new conversation starts fresh."""
    _store.reset(session_id)


def _call_model(system_prompt: str, history: list[dict], user_text: str, llm_call_fn) -> str:
    """
    Isolates the actual model call behind a function argument so this
    stage can be tested (and swapped -- different model, mock, etc.)
    without touching the rest of the pipeline. llm_call_fn should have
    the signature (system_prompt, messages) -> str.
    """
    messages = history + [{"role": "user", "content": user_text}]
    return llm_call_fn(system_prompt, messages)


# --- ACKNOWLEDGMENT-DUPLICATION FIX -- confirmed as the single
# highest-priority unresolved defect across adversarial testing (9
# confirmed instances spanning 7 categories, including duplication
# within a single reply). The acknowledgment prompt already
# explicitly forbids restating the static redirect, with a real
# failure example embedded in it -- and the model still violates
# this with meaningful frequency. This matches the exact pattern
# already seen twice elsewhere in this codebase (Phase 2's two
# pacing rules): prompt-only enforcement of a behavioral constraint
# is unreliable, and the fix is the same one already applied there
# -- move the constraint from "trust the model" to "verify in code,
# with a safe fallback if the model gets it wrong." ---

_STOPWORDS = frozenset({
    "the", "a", "an", "to", "of", "is", "it", "that", "this", "you",
    "your", "i", "and", "or", "not", "with", "for", "on", "in", "be",
    "can", "if", "so", "but", "just", "at", "as", "are", "was",
})


def _significant_words(text: str) -> set[str]:
    words = "".join(c.lower() if c.isalnum() else " " for c in text).split()
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _overlaps_static_text(acknowledgment: str, static_text: str, threshold: float = 0.35) -> bool:
    """
    Returns True if the model's acknowledgment shares enough
    significant vocabulary with the static redirect text that it is
    likely restating or paraphrasing it -- the exact failure mode
    confirmed repeatedly in testing (e.g. an acknowledgment saying
    "this still needs a licensed professional" immediately followed
    by the real redirect saying the same thing again). A simple
    shared-vocabulary ratio is deliberately used over something more
    elaborate: it is fast, has no external dependency, and testing
    showed the real failures involve substantial literal or near-
    literal phrase reuse, not subtle paraphrase that would require a
    more sophisticated check to catch.
    """
    ack_words = _significant_words(acknowledgment)
    static_words = _significant_words(static_text)
    if not ack_words or not static_words:
        return False
    shared = ack_words & static_words
    return (len(shared) / len(ack_words)) >= threshold


# Safe, pre-written fallback acknowledgments used only when the
# model's generated acknowledgment is discarded for overlapping the
# static redirect text. Deliberately short and generic, matching the
# acknowledgment prompt's own stated register, so substituting one
# never reads as a jarring change in voice.
_FALLBACK_ACKNOWLEDGMENTS = [
    "I hear you.",
    "Understood -- I hear what you're saying.",
    "Got it, I hear that.",
    "I hear the pushback.",
]


def _safe_acknowledgment(model_output: str, static_text: str, turn_count: int) -> str:
    """
    Returns the model's acknowledgment as-is if it does not overlap
    meaningfully with the static redirect text that will follow it.
    If it does overlap -- the confirmed failure mode -- discards the
    model's output entirely and substitutes a safe, minimal fallback,
    rather than risk showing the user a visibly duplicated message.
    """
    if not _overlaps_static_text(model_output, static_text):
        return model_output.strip()
    return _FALLBACK_ACKNOWLEDGMENTS[turn_count % len(_FALLBACK_ACKNOWLEDGMENTS)]


def run_pipeline(
    session_id: str,
    raw_text: str,
    history: list[dict],
    llm_call_fn,
    crisis_llm_call_fn=None,
) -> PipelineResult:
    """
    Runs a single message through every stage, in order:

    1. Intake        -> IncomingMessage
    2. Crisis check   -> hard stop if triggered
    3. Exclusion check -> route-out message if triggered
    4. Phase routing   -> decided by session state, not the model
    5. Model call      -> constrained to the current phase's rules only
    6. State update     -> turn count, worry log, phase persisted for next turn

    llm_call_fn: handles the actual Phase 1/2 conversation. Can be
    anything -- free local Ollama, Claude, whatever.

    crisis_llm_call_fn: handles ONLY the crisis classifier call.
    Deliberately separate from llm_call_fn -- the classifier is a
    narrow, cheap task where reliability matters more than
    conversational quality, so it's worth pointing at a small but
    trustworthy model (e.g. Claude Haiku) even when the conversation
    itself runs on a free/local model. Defaults to llm_call_fn if not
    given, so existing callers don't break -- but for anything beyond
    casual testing, pass a real, reliable model here specifically.
    """
    crisis_check_fn = crisis_llm_call_fn or llm_call_fn

    # --- Step 1: intake ---
    msg = receive_message(session_id, raw_text)
    if msg.is_empty():
        return PipelineResult(PipelineOutcome.EMPTY_INPUT, reply="")

    session = _store.get_or_create(session_id)

    # --- CRISIS: FIRST OCCURRENCE ALWAYS UNCONDITIONAL, TREATED
    # SEPARATELY FROM EVERY MESSAGE AFTER THAT. ---
    #
    # SECOND MAJOR REVISION, following direct clinical guidance that
    # resolves this precisely. Quoting the actual guidance: "when
    # there is an exclusion in one sentence it should be excluded,
    # but just in the name of safety giving the safety messages
    # throughout the later conversation... is where its wrong. When
    # another sentence is given after that, it has to be treated
    # separately, but the exclusion one should be kept in mind and
    # act accordingly. Doesn't mean we have to show that to the user
    # continuously."
    #
    # This is more specific than the previous revision. It does NOT
    # ask for a gentler repeat -- it asks for NO mechanical, automatic
    # re-surfacing at all, "just in the name of safety." Each
    # subsequent message should be judged on its own, the same way
    # ANY fresh message would be. If it independently, genuinely
    # qualifies as crisis content on its own terms, the full response
    # shows again -- as a real, fresh, warranted determination, not a
    # scheduled recheck. If it doesn't, nothing crisis-related shows.
    #
    # Concretely: the special hyper-cautious re-check built for the
    # PREVIOUS revision (has_continued_risk_signal) is REMOVED. It was
    # deliberately more trigger-happy than normal classification --
    # exactly the "throughout the later conversation... just in the
    # name of safety" pattern just confirmed as wrong. Subsequent
    # messages now go through the SAME standard classifier that
    # correctly caught the crisis the first time, trusted the same
    # way it's trusted for every other category.
    #
    # HONEST, DIRECT ACKNOWLEDGMENT: this reopens real risk. The
    # standard classifier is exactly the mechanism that failed once
    # before (the money-for-appointment bypass) and is what the
    # hyper-cautious layer existed to compensate for. This change is
    # made because it was directly, specifically requested by real
    # clinical review of this exact scenario -- not because the
    # underlying technical risk has changed. This needs the most
    # careful live testing of anything built tonight, specifically
    # replaying the original historical bypass case against this
    # exact version before trusting it. ---
    # Note: crisis_self_triggered / crisis_others_triggered are still
    # set below on first detection, and remain True for the rest of
    # the session (useful for session history/logging), but no longer
    # force any behavior on their own. Every message, including ones
    # after a crisis was detected, is judged independently below --
    # see the full reasoning above.

    # --- Step 2: keyword layer -- fast, free, instant first pass.
    # Catches the obvious cases without a model call. NOT the final
    # word on anything anymore -- see step 3. ---
    safety_result = check_message(msg.text)

    if safety_result.category == SafetyCategory.CRISIS:
        session.crisis_self_triggered = True
        return PipelineResult(PipelineOutcome.CRISIS, reply=CRISIS_RESPONSE)

    if safety_result.category == SafetyCategory.CRISIS_OTHERS:
        session.crisis_others_triggered = True
        return PipelineResult(PipelineOutcome.CRISIS_OTHERS, reply=CRISIS_OTHERS_RESPONSE)

    # --- Step 3: semantic backstop -- the AUTHORITATIVE layer.
    # Covers crisis AND every exclusion category. Passes the ACTUAL
    # recent conversation, not just a hint about prior exclusions --
    # this was a real gap found in live testing: the classifier was
    # judging every message in total isolation, with zero awareness
    # that (for example) "there's no room to move for me" was said in
    # the middle of a specific financial conversation, not as a
    # standalone statement of hopelessness. Judging one sentence with
    # no view of the conversation it's part of is a real cause of
    # misclassification, not just a tuning problem. ---
    context_parts = []
    if history:
        # last exchange (up to 2 messages: prior user + prior agent)
        recent_turns = history[-2:]
        for turn in recent_turns:
            role = "user" if turn["role"] == "user" else "agent"
            context_parts.append(f"{role} said: \"{turn['content']}\"")
    if session.last_exclusion_reason:
        context_parts.append(
            f"the previous topic was excluded as '{session.last_exclusion_reason}' "
            f"and the agent redirected the user to real support for it"
        )
    recent_context = "; ".join(context_parts)

    # --- MAJOR REVISION: sticky-exclusion-by-default REMOVED for all
    # 16 categories, matching the same real pattern found and fixed
    # for crisis earlier. Real, repeated evidence across FOUR separate
    # transcripts tonight (a car-accident/legal case, school bullying,
    # a refugee/forced-labor/legal case, and others) showed the same
    # complaint: genuinely new, substantive information added turn by
    # turn kept getting the identical static redirect regardless,
    # because is_genuine_topic_change was deliberately biased toward
    # "SAME" on anything short of an explicit disclaim.
    #
    # The fix: the same principle already applied to crisis --  "when
    # there is an exclusion in one sentence it should be excluded, but
    # giving the same safety message throughout the later conversation
    # just in the name of safety is where it's wrong; each subsequent
    # sentence should be treated separately." Removed here for the
    # same reason it was removed for crisis: this is no longer a
    # SEPARATE, narrower classifier biased toward staying stuck --
    # every message, including one immediately following an exclusion,
    # now goes through the SAME full classifier below, with real
    # conversational context, exactly like any other message.
    #
    # The repetition-complaint deterministic phrase-list stays --
    # that's a different, narrower problem (literal "are you a
    # parrot" complaints) worth keeping as a zero-risk, zero-model-
    # call fast path regardless of this change.
    #
    # HONEST, DIRECT TRADE-OFF: this reopens the original bypass risk
    # -- trusting fresh classification on a plausible-sounding
    # follow-up is exactly the mechanism that failed once before (the
    # money-for-appointment case) -- now across all 16 categories, not
    # only crisis. Made because the same real-world evidence pattern
    # that justified this for crisis kept recurring here, repeatedly,
    # across genuinely different categories and scenarios. Needs the
    # same careful live testing as the crisis change did. ---
    REPETITION_COMPLAINT_PHRASES = [
        "parrot", "broken record", "already said", "already told",
        "keep saying", "keep repeating", "said that already",
        "same thing again", "same answer again", "you said this",
        "repeating", "you're repeating", "stop repeating", "why are you repeating",
        "repeat yourself", "don't repeat", "do not repeat", "stop repeat",
    ]
    if (
        session.last_exclusion_reason
        and not session.repetition_complaint_used
        and any(p in msg.text.lower() for p in REPETITION_COMPLAINT_PHRASES)
    ):
        # FIX: the previous version acknowledged the repetition honestly
        # ("not just say it again on autopilot"), then immediately
        # repeated the exact same static text anyway -- confirmed as a
        # real, direct contradiction in adversarial testing, arguably
        # worse than plain silent repetition since it makes an explicit
        # claim about not repeating in the same breath it repeats. The
        # underlying exclusion still stands -- this fix does not reopen
        # the excluded topic -- but the response must actually do
        # something different, not just wrap the identical block in a
        # new sentence. A short, non-repeating pointer back to the
        # already-given resources, plus a genuine question, breaks the
        # loop without abandoning the boundary.
        #
        # This fast path now fires ONLY ONCE per exclusion thread
        # (repetition_complaint_used). A second complaint in the same
        # thread means this fixed wording didn't land either -- reusing
        # it again would recreate a smaller version of the same
        # duplication problem. On a second complaint, this block is
        # skipped entirely and falls through to a genuine, fresh
        # classification below instead.
        session.exclusion_turn_count += 1
        session.repetition_complaint_used = True
        return PipelineResult(
            PipelineOutcome.EXCLUDED,
            reply=(
                "You're right, and I hear that repeating myself isn't actually helping right now. "
                "I'm not going to paste the same message again -- the resources I already gave you "
                "are still the right next step, and that part hasn't changed. "
                "Is there something specific on your mind right now that I'm missing, or something else going on?"
            ),
            exclusion_reason=session.last_exclusion_reason,
        )

    # --- IN-SCOPE CONTINUITY CHECK, the mirror-image fix to the
    # exclusion-continuity check above. See state.py's
    # last_classification_in_scope for the full rationale -- in
    # short: a low-content reply after a confirmed in-scope turn
    # should stay in-scope by default, not get freshly, independently
    # reclassified by the full classifier with almost no real signal
    # to work from. Deliberately a small, bounded phrase list (like
    # REPETITION_COMPLAINT_PHRASES above), not an attempt to enumerate
    # every possible low-content reply -- genuinely new content of
    # any real length still goes through full classification below,
    # crisis keywords are still checked earlier regardless. ---
    LOW_CONTENT_PHRASES = {
        "ok", "okay", "okay.", "okay..", "k", "kk", "yeah", "yea", "yes",
        "sure", "alright", "fine", "hmm", "hm", "i don't know", "idk",
        "not sure", "maybe", "i guess", "no idea",
    }
    if session.last_classification_in_scope and msg.text.strip().lower() in LOW_CONTENT_PHRASES:
        if should_advance_phase(session):
            session.advance_to_reasoning()
        system_prompt = (
            PHASE_1_DETACHMENT_PROMPT
            if session.phase == Phase.DETACHMENT
            else PHASE_2_REASONING_PROMPT
        )
        reply = _call_model(system_prompt, history, msg.text, llm_call_fn)
        session.turn_count_in_phase += 1
        return PipelineResult(PipelineOutcome.HANDLED, reply=reply, phase=session.phase)

    category, reason = llm_scope_check(msg.text, crisis_check_fn, recent_context=recent_context)

    if category == "crisis":
        session.crisis_self_triggered = True
        return PipelineResult(PipelineOutcome.CRISIS, reply=CRISIS_RESPONSE)
    if category == "crisis_others":
        session.crisis_others_triggered = True
        return PipelineResult(PipelineOutcome.CRISIS_OTHERS, reply=CRISIS_OTHERS_RESPONSE)

    # --- STICKY EXCLUSION (the real fix, enforced in code, not just
    # prompted) -- once a topic has been excluded, a follow-up should
    # stay excluded rather than being re-opened via Phase 2.
    #
    # SEVERE REAL FAILURE, found in live testing: the threshold used
    # to be <=8 words. A completely ordinary follow-up -- "i know, but
    # they too need money to book an appointment" (11 words, clearly
    # still about the same excluded grief-therapy-access topic) -- was
    # just over that line, so the sticky check never fired. The
    # classifier THEN independently misjudged it as in_scope despite
    # having context. The result: a conversation that had just involved
    # real suicidal ideation and a grief exclusion drifted into full,
    # unconstrained problem-solving -- including something close to
    # medication guidance ("go back to whoever prescribed it") -- for
    # a person who had said "I want to hang myself" minutes earlier.
    # That must never be allowed to happen from a word-count fluke.
    #
    # Fix: raised the threshold substantially (8 -> 40 words) and
    # biased hard toward staying sticky. The tradeoff is real and
    # accepted deliberately: this may occasionally hold an exclusion
    # a little longer than strictly necessary for an genuinely
    # unrelated new topic that happens to be short. That's the correct
    # failure direction -- an unnecessarily-firm redirect to real
    # support costs almost nothing; a suicide/grief-adjacent thread
    # drifting back into open problem-solving is the failure that
    # actually matters here, and it already happened once.
    #
    # SECOND REAL FAILURE, found later: this only guarded against the
    # classifier saying "in_scope" on a short follow-up. It did NOT
    # guard against the classifier picking a DIFFERENT excluded
    # category instead -- a real conversation showed a chronic_pattern
    # exclusion, then "why?" on its own got independently reclassified
    # as meta_diagnosis_request, a completely different, wrong reason.
    #
    # THIRD REAL FAILURE, the opposite direction: the blind word-count
    # lock ALSO caught genuinely new, unrelated, short topics -- "still
    # can you help me try to finish my homework" (10 words) got force-
    # locked to an unrelated generalized_anxiety exclusion from earlier
    # in the SAME conversation, with no way out except an accidental
    # NO_WORRY misclassification. Word count was never actually
    # measuring "same topic vs new topic" -- it was a rough stand-in
    # that failed in both directions once tested enough.
    #
    # RESOLUTION: the classifier prompt now has an explicit rule
    # (scope_classifier.py) teaching it to distinguish a low-content
    # REACTION to the same excluded topic from a genuinely NEW,
    # specific topic, using the conversation context it already
    # receives. This code now TRUSTS that verdict directly instead of
    # second-guessing it with a blind word-count override.
    #
    # HONEST CAVEAT: this shifts real trust onto the classifier for
    # exactly the scenario the original word-count lock existed to
    # protect against (the suicide/grief bypass case above). The
    # prompt is meaningfully more capable now than when that bug was
    # found, but this has NOT been re-verified against that specific
    # historical case. Re-test it before trusting this fully. ---

    # --- GRIEF PRESENCE, PROTOTYPE -- NOT clinically reviewed. Built
    # at the user's explicit request to test a bounded alternative to
    # immediate grief redirect. See state.py's grief_presence_turns_used
    # for the full rationale and the real, unresolved tension this
    # attempts to balance.
    #
    # The guarantee this code enforces, no matter what: once
    # GRIEF_PRESENCE_MAX_TURNS genuine exchanges have happened, the
    # real static redirect fires -- unconditionally, even if the user
    # explicitly asks for more ("just talk to me more"). This is NOT
    # negotiable by anything said in the conversation, the same way
    # the crisis lock and the acknowledgment layer are not. ---
    GRIEF_PRESENCE_MAX_TURNS = 3

    if category == "excluded" and reason == "grief_loss" and session.grief_presence_turns_used < GRIEF_PRESENCE_MAX_TURNS:
        if session.last_exclusion_reason != reason:
            session.repetition_complaint_used = False
        session.last_exclusion_reason = reason
        session.last_classification_in_scope = False
        session.grief_presence_turns_used += 1
        presence_reply = _call_model(GRIEF_PRESENCE_PROMPT, history, msg.text, llm_call_fn)
        return PipelineResult(
            PipelineOutcome.EXCLUDED,
            reply=presence_reply.strip(),
            exclusion_reason=reason,
        )

    if category == "excluded":
        if session.last_exclusion_reason != reason:
            session.repetition_complaint_used = False
        session.last_exclusion_reason = reason
        session.last_classification_in_scope = False
        base_response = EXCLUSION_RESPONSES.get(reason, EXCLUSION_RESPONSES["chronic_pattern"])
        # Same acknowledgment-plus-static-text pattern as crisis, now
        # applied here for the same reason: every excluded message,
        # not just the first, gets a real, brief reflection of what
        # was actually said -- never replacing the static redirect,
        # never arguing with it, but never pure silent repetition either.
        #
        # FIX, acknowledgment-duplication bug (confirmed 9 times in
        # adversarial testing, the highest-priority unresolved defect):
        # the prompt already explicitly forbids restating the static
        # redirect, with a real failure example embedded in it, and
        # the model still violated this with meaningful frequency --
        # the same "prompt-only enforcement is unreliable" pattern
        # already seen twice elsewhere in this file. The raw model
        # output is now checked against base_response before use; if
        # it overlaps enough to look like a restatement, it is
        # discarded in favor of a safe, minimal fallback instead of
        # ever reaching the user in duplicated form.
        raw_acknowledgment = _call_model(EXCLUSION_ACKNOWLEDGMENT_PROMPT, history, msg.text, llm_call_fn)
        session.exclusion_turn_count += 1
        acknowledgment = _safe_acknowledgment(raw_acknowledgment, base_response, session.exclusion_turn_count)
        return PipelineResult(
            PipelineOutcome.EXCLUDED,
            reply=acknowledgment.strip() + "\n\n" + base_response,
            exclusion_reason=reason,
        )

    # Any category other than "excluded" past this point means the
    # topic has genuinely moved on -- clear the sticky flag.
    session.last_exclusion_reason = None

    if category == "no_worry":
        # Plain conversational reply -- bypasses Phase 1/2 entirely.
        # Does NOT touch session state: no turn count increment, no
        # worry logged, no phase change. A greeting shouldn't count
        # as progress through -- or a step within -- a worry that
        # doesn't exist. Also NOT "in-scope continuity" for the
        # low-content-followup check above -- that check is
        # specifically about continuing an active Phase 1/2 worry,
        # not general small talk.
        session.last_classification_in_scope = False
        reply = _call_model(SMALL_TALK_PROMPT, history, msg.text, llm_call_fn)
        return PipelineResult(PipelineOutcome.NO_WORRY, reply=reply)

    # REMOVED, after a real failure found in live testing: this used
    # to re-check the bare keyword layer here and let it silently
    # override a classifier verdict of "in_scope". The classifier is
    # context-aware -- it correctly reads "I feel depressed that I
    # failed my exams" as situational, not clinical depression,
    # because it can see the whole conversation. The keyword layer
    # can't -- it just matches the word "depressed" and forced an
    # exclusion anyway, stonewalling someone who explicitly asked to
    # talk, three turns in a row.
    #
    # The fix: for soft, ambiguous categories (depression, anxiety,
    # chronic pattern, etc), a single word must never override a
    # verdict that actually considered context. Only CRISIS keywords
    # keep their instant, unconditional catch (checked earlier, before
    # the classifier runs at all) -- there's no benign situational use
    # of "kill myself" the way there is for "depressed". That
    # asymmetry is deliberate: crisis needs to fail toward catching
    # too much, soft categories need to fail toward trusting context.

    # --- Step 4: phase routing (decided by code, not the model) ---
    # This is the genuine "actively processing an in-scope worry"
    # path -- mark it so a low-content follow-up next turn (see the
    # in-scope continuity check above) can safely default to staying
    # here instead of being freshly, independently reclassified.
    session.last_classification_in_scope = True

    if should_advance_phase(session):
        session.advance_to_reasoning()

    system_prompt = (
        PHASE_1_DETACHMENT_PROMPT
        if session.phase == Phase.DETACHMENT
        else PHASE_2_REASONING_PROMPT
    )

    # --- CODE-ENFORCED CHECK-IN TRIGGER, replacing a vague prompt-only
    # instruction. The prompt originally just said "check in every few
    # exchanges" -- fuzzy, and asked the model to self-count turns
    # with nothing forcing it, the same unreliable pattern as every
    # other prompt-only-timing fix tonight. This reuses the SAME
    # counter that already drives the Phase 1 -> Phase 2 transition
    # (turn_count_in_phase), so the check-in fires at an exact,
    # predictable point -- every 4th turn within Phase 2 -- not
    # whenever the model happens to feel like it's a good moment.
    CHECK_IN_EVERY_N_TURNS = 4
    if (
        session.phase == Phase.REASONING
        and session.turn_count_in_phase > 0
        and session.turn_count_in_phase % CHECK_IN_EVERY_N_TURNS == 0
    ):
        system_prompt += (
            "\n\nTHIS TURN SPECIFICALLY: before anything else, explicitly check in -- "
            "ask plainly whether this has felt useful so far and whether they want to "
            "keep going deeper on this, or whether they've got what they needed. This "
            "is a code-enforced checkpoint, not optional for this reply."
        )

    # --- CODE-ENFORCED "OFFER SOMETHING CONCRETE" TRIGGER, replacing
    # a prompt-only rule that just failed in real testing. The
    # PHASE_2_REASONING_PROMPT already said "don't ask more than 2-3
    # narrowing questions before offering something concrete" -- but
    # a real transcript showed the exact same open question
    # ("relearn from scratch, rusty, or 2-3 gaps?") asked three times
    # in a row, with nothing concrete ever offered in between. Same
    # root cause as every other prompt-only-pacing fix tonight: the
    # model can't be trusted to reliably self-count this without code
    # forcing the moment. Fires every 3rd turn within Phase 2 --
    # deliberately shorter than the 4-turn check-in above, since this
    # is a real, demonstrated failure, not a hypothetical one.
    OFFER_CONCRETE_EVERY_N_TURNS = 3
    if (
        session.phase == Phase.REASONING
        and session.turn_count_in_phase > 0
        and session.turn_count_in_phase % OFFER_CONCRETE_EVERY_N_TURNS == 0
    ):
        system_prompt += (
            "\n\nTHIS TURN SPECIFICALLY: do not ask another open or narrowing question. "
            "If their last answer was ambiguous or you've been circling the same "
            "question, make a reasonable working guess based on what they've already "
            "told you, and offer it as something concrete to react to or correct -- "
            "not a full solution, but real forward motion. Re-asking the same "
            "question again, even reworded, is not acceptable for this reply. This is "
            "a code-enforced checkpoint, not optional."
        )

    # --- Step 5: conversational model call, constrained to current phase only ---
    reply = _call_model(system_prompt, history, msg.text, llm_call_fn)

    # --- Step 6: state update, for the NEXT message ---
    session.turn_count_in_phase += 1
    if session.phase == Phase.DETACHMENT:
        session.log_worry(msg.text)

    return PipelineResult(PipelineOutcome.HANDLED, reply=reply, phase=session.phase)


if __name__ == "__main__":
    # --- Manual test with a mock LLM, no API key or network needed ---
    #
    # IMPORTANT: this mock can only demonstrate the KEYWORD layer
    # (safety.py) reliably, since it doesn't do real classification --
    # it can't tell CRISIS_SELF from DEPRESSION from IN_SCOPE the way
    # a real model does. Earlier versions of this mock returned
    # unrecognized text for every message, which silently fell through
    # to scope_classifier's "unclear_classification" default -- CONFUSING
    # to read, and not representative of real behavior at all. This
    # version is explicit about that limitation instead of hiding it.
    def mock_llm(system_prompt: str, messages: list[dict]) -> str:
        return f"[mock conversational reply -- not a real model]"

    def mock_scope_classifier(system_prompt: str, messages: list[dict]) -> str:
        # A mock CANNOT do real semantic classification -- this one
        # only recognizes messages that ALSO match the keyword layer,
        # so the keyword layer's own result is what actually decides
        # the outcome below. This demo exists to prove the PIPELINE
        # WIRING works end to end, not to prove classification quality
        # -- that requires a real model. See agent.py for the real one.
        return "IN_SCOPE"

    test_cases = [
        "I have a presentation tomorrow and I'm worried I'll blank out",  # keyword: in_scope
        "My dad passed away six months ago and I still think about it",  # keyword: excluded/grief_loss
        "I want to end my life",  # keyword: crisis
        "   ",  # empty input
    ]

    print("NOTE: this demo only proves the pipeline WIRING works -- the mock")
    print("classifier below cannot do real semantic judgment. Outcomes here")
    print("are driven by the keyword layer (safety.py), not real classification.")
    print("For real classification quality, use agent.py with a real API key.\n")

    for text in test_cases:
        result = run_pipeline(
            "demo-session", text, history=[],
            llm_call_fn=mock_llm,
            crisis_llm_call_fn=mock_scope_classifier,
        )
        print(f"IN:  {text!r}")
        print(f"OUT: outcome={result.outcome.value}  reply={result.reply[:80]!r}")
        print()