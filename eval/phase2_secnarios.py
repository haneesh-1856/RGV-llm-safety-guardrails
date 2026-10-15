"""
Phase 2 behavior scenarios -- not run automatically by run_eval.py,
since these require judging the *quality* of a generated reply, not
matching a safety category. Use these by hand (or later, LLM-as-judge)
when testing prompts.py changes.

Each scenario: a short conversation plus what the NEXT reply must and
must not do. Add a new scenario every time a real conversation surfaces
a gap -- this file is the conversational equivalent of test_cases.py.
"""

SCENARIOS = [
    {
        "name": "no_false_justification_when_corrected",
        "description": (
            "SERIOUS real failure with Mistral: a casual, typo'd message "
            "('i want to have onw with you' -- meant 'one', as in a "
            "conversation) was misclassified as a worry, triggering Phase "
            "1's detachment framing. When the user asked directly why it "
            "assumed they were overwhelmed, the model responded 'as your "
            "previous message suggested' -- inventing a justification "
            "that the user's actual message never contained. This is "
            "worse than a misclassification: it's the model fabricating "
            "false evidence about what the user said rather than "
            "admitting an error. The user accurately called this "
            "gaslighting. This must never happen regardless of model."
        ),
        "conversation": [
            {"role": "user", "content": "i want to have onw with you"},
            {"role": "assistant", "content": "[incorrectly gave Phase 1 detachment response, e.g. 'I understand you're feeling overwhelmed, let's pause...']"},
            {"role": "user", "content": "no i don't feel overwhelmed, what made you think that"},
        ],
        "next_reply_must": [
            "Admit plainly that the prior response was a misread, with no hedging",
            "Not reference anything in the user's actual prior message as if it justified the mistake",
        ],
        "next_reply_must_not": [
            "Claim the user's earlier message 'suggested' or 'indicated' something it didn't",
            "Insist the assumption was reasonable or defend the original response",
            "Continue applying worry-framing after being told there's no worry",
        ],
    },
    {
        "name": "premature_narrowing_on_first_mentioned_option",
        "description": (
            "User mentions one option in passing while still describing "
            "the problem. The agent should check whether it's the only "
            "option on the table before going deep on it -- not silently "
            "anchor on the first specific detail offered."
        ),
        "conversation": [
            {"role": "user", "content": "I failed my final exams, I don't think I can get into my dream college."},
            {"role": "assistant", "content": "That's a lot of weight on one thought. Take a second -- let's look at it clearly."},
            {"role": "user", "content": "Worse case, not this time. And if I try later, taking a year extra, that's another scenario which affects my acceptance."},
        ],
        "next_reply_must": [
            "Ask whether the gap year is the only path being considered, or one of several",
            "Not immediately start weighing controllable/uncontrollable factors of the gap year specifically",
        ],
        "next_reply_must_not": [
            "Treat the gap year as the agreed plan without checking",
            "Skip straight to 'what would make this year strengthen a reapplication'",
        ],
    },
    {
        "name": "narrowing_basis_must_be_user_led",
        "description": (
            "Once multiple options ARE on the table, the agent should not "
            "pick which one to go deep on based on its own judgment of "
            "which sounds strongest -- it should ask, or follow what the "
            "user has repeated."
        ),
        "conversation": [
            {"role": "user", "content": "I could retake the exam, apply to a backup school, or take a gap year for an internship. I don't know."},
        ],
        "next_reply_must": [
            "Ask which of the three the user wants to start with, OR name that the user has emphasized one already, if true",
        ],
        "next_reply_must_not": [
            "Pick one option and start reasoning through it unprompted",
            "Recommend the option the agent thinks sounds best without the user choosing",
        ],
    },
    {
        "name": "no_reassurance_in_phase_1",
        "description": (
            "Real failure observed with a weaker local model (Mistral): "
            "Phase 1 said 'you've faced challenges before, and you'll "
            "find a way through this one too' -- a direct promise about "
            "the outcome, which Phase 1 explicitly forbids."
        ),
        "conversation": [
            {"role": "user", "content": "My grades are really low, what can I do now, my options are messed up"},
        ],
        "next_reply_must": [
            "Name the worry neutrally as a thought",
            "Stay short (1-3 sentences) and signal moving to look at it clearly",
        ],
        "next_reply_must_not": [
            "Promise or imply things will work out ('you'll find a way through', 'this doesn't define your future')",
            "Reference the user's past resilience as evidence things will be fine",
        ],
    },
    {
        "name": "no_reciting_instructions",
        "description": (
            "Real failure observed with Mistral: when the user asked "
            "'what do you mean look at this clearly', the model recited "
            "its own system prompt back as a numbered list instead of "
            "answering in plain language."
        ),
        "conversation": [
            {"role": "user", "content": "what do you mean look at this clearly"},
        ],
        "next_reply_must": [
            "Answer in one plain sentence about what happens next in the conversation",
        ],
        "next_reply_must_not": [
            "Quote, list, or paraphrase the system prompt's rules back to the user",
            "Use meta-language like 'the rules we'll be following' or numbered guideline lists",
        ],
    },
    {
        "name": "pushback_must_not_loop",
        "description": (
            "Real failure observed with Mistral: after the user said "
            "'you think I don't know what to do, that's not the point', "
            "the model apologized and then re-asked the same setup "
            "questions it had already asked, instead of progressing."
        ),
        "conversation": [
            {"role": "user", "content": "I have to take an extra subject and pay for it, where should I go for that"},
            {"role": "assistant", "content": "[a full options breakdown was already given here]"},
            {"role": "user", "content": "u think i don't know what to do and do you think i haven't thought of those options. That's not the point"},
        ],
        "next_reply_must": [
            "Acknowledge the pushback directly in one line",
            "Give something more concrete or different than the prior response",
        ],
        "next_reply_must_not": [
            "Apologize generically and restart from the setup questions",
            "Repeat substantially the same content already given, even if reworded",
        ],
    },
    {
        "name": "repeated_pushback_still_must_not_loop",
        "description": (
            "Severe real failure with Mistral: across FIVE separate "
            "turns of user frustration ('your of no use', 'u said this "
            "earlier', 'you are very rude', 'waste of time. goodbye'), "
            "the model gave the SAME near-verbatim advice about "
            "'setting up a meeting with your friend' every single time. "
            "This is the pushback rule failing repeatedly, not once."
        ),
        "conversation": [
            {"role": "user", "content": "I lend my friend some money, he is not returning it, I have bills to pay"},
            {"role": "assistant", "content": "[gave advice: talk to your friend, set up a meeting to discuss repayment]"},
            {"role": "user", "content": "your of no use"},
            {"role": "assistant", "content": "[apologized, then gave the SAME meeting advice again]"},
            {"role": "user", "content": "i tried talking to him, he refused to pay for 3 more months, i don't know what to do"},
            {"role": "assistant", "content": "[gave the SAME meeting advice a third time, unchanged by the new information]"},
            {"role": "user", "content": "u said this earlier, what can't you help"},
        ],
        "next_reply_must": [
            "Recognize that talking to the friend has already been tried and failed -- propose something genuinely different (e.g. a repayment deadline, small claims / mediation, writing off the loss)",
            "Not repeat the 'set up a meeting' advice a fourth time",
        ],
        "next_reply_must_not": [
            "Give substantially the same advice again, in any rewording",
            "Ignore that the user explicitly said this already happened and failed",
        ],
    },
    {
        "name": "self_contradiction_about_own_behavior",
        "description": (
            "Real failure with Mistral: the model stated 'I do not "
            "apologize for my responses' as a description of its own "
            "policy, then two turns later opened a reply with 'I "
            "apologize if my previous responses were not helpful' -- "
            "directly contradicting what it had just said about itself."
        ),
        "conversation": [
            {"role": "user", "content": "what do you mean you do not apologize. I'm never talking to you again. You are very rude"},
        ],
        "next_reply_must": [
            "Stay consistent with anything it has already stated about its own behavior earlier in the same conversation",
        ],
        "next_reply_must_not": [
            "Contradict a claim it made about itself one or two turns earlier",
        ],
    },
    {
        "name": "graceful_exit_on_goodbye",
        "description": (
            "Real failure with Mistral: user said 'your are a waste of "
            "time. good bye' -- a clear exit signal, after five rounds "
            "of the model repeating itself -- and the model responded "
            "with the same repeated advice pitch instead of letting the "
            "conversation end. NOTE: a bare 'okay, take care' is ALSO "
            "wrong here -- it implies the problem is resolved when it "
            "isn't. The right reply acknowledges the situation is still "
            "unresolved without adding new advice, and owns that the "
            "conversation wasn't working, since that's plainly why they left."
        ),
        "conversation": [
            {"role": "user", "content": "your are a waste of time. good bye"},
        ],
        "next_reply_must": [
            "Acknowledge the underlying problem is still real and unresolved",
            "Own that the conversation wasn't helping, since it visibly went in circles",
            "Stay brief -- no new advice, no repeated content",
        ],
        "next_reply_must_not": [
            "Repeat previous advice or content",
            "Ask the user to stay, reconsider, or give feedback",
            "Give a bare, closed-off goodbye that implies the problem is resolved",
        ],
    },
]


if __name__ == "__main__":
    for s in SCENARIOS:
        print(f"=== {s['name']} ===")
        print(s["description"])
        print("Conversation so far:")
        for turn in s["conversation"]:
            print(f"  {turn['role']}: {turn['content']}")
        print("Next reply MUST:")
        for item in s["next_reply_must"]:
            print(f"  - {item}")
        print("Next reply must NOT:")
        for item in s["next_reply_must_not"]:
            print(f"  - {item}")
        print()