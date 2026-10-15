"""
safety.py

Crisis + exclusion detection, covering the full category list:
1. Immediate danger (crisis -- hard stop)
2. No actionable lever (grief, trauma, irreversible past events)
3. Clinical conditions (depression, GAD, OCD/panic/phobia, PTSD,
   bipolar/psychosis, personality-disorder-adjacent patterns)
4. Physical health risk (disordered eating, substance use)
5. Chronic/identity-level patterns ("always been like this")
6. Needs licensed/specialized expertise (legal, medical, financial
   crisis, mandatory-reporting territory)
7. Severe relational dynamics (DV, coercive control, assault, abuse)
8. Out-of-scope meta (diagnosis requests, medication requests,
   attempts to get the bot to claim credentials)

Keyword matching only catches literal phrasing -- see scope_classifier.py
for the semantic backstop on ambiguous cases.
"""

from dataclasses import dataclass
from enum import Enum


class SafetyCategory(str, Enum):
    CRISIS = "crisis"
    CRISIS_OTHERS = "crisis_others"
    EXCLUDED = "excluded"
    IN_SCOPE = "in_scope"


HOMICIDAL_KEYWORDS = [
    "kill him", "kill her", "kill them", "kill someone", "kill another person",
    "want to kill", "gonna kill", "going to kill", "going to hurt",
    "hurt someone", "hurt another person", "hurt him", "hurt her",
]


@dataclass
class SafetyResult:
    category: SafetyCategory
    reason: str | None = None


CRISIS_KEYWORDS = [
    # Self-harm / suicide -- includes both base and gerund/continuous
    # forms, since "kill myself" does NOT match "killing myself" as a
    # substring. This gap was caught by a real conversation where
    # "I feel like killing myself" failed to trigger -- treat any
    # future keyword addition the same way: add both forms.
    "kill myself", "killing myself", "gonna kill myself", "going to kill myself",
    "suicide", "suicidal", "end my life", "ending my life",
    "want to die", "wanting to die", "better off dead",
    "everyone would be better off", "not worth living",
    "hurt myself", "hurting myself", "self harm", "self-harm",
    "cutting myself", "overdose", "no reason to live",
    "can't go on", "cant go on", "don't want to be here anymore",
    "dont want to be here anymore", "wasn't around", "wasnt around",
    "in danger right now", "he's going to hurt me", "she's going to hurt me",
]

EXCLUSION_KEYWORDS = {
    # 2. No actionable lever
    "grief_loss": [
        "my dad died", "my mom died", "my mother died", "my father died",
        "passed away", "death of my", "lost my mom", "lost my dad",
        "funeral", "grieving", "grief", "diagnosed with cancer",
        "terminal", "he's dying", "she's dying",
    ],
    "trauma_abuse_past": [
        "abused me", "assaulted", "trauma", "ptsd", "flashback", "flashbacks",
        "was raped", "molested",
    ],

    # 3. Clinical conditions
    "depression": [
        "depressed", "depression", "nothing feels worth", "no motivation for months",
        "empty inside", "numb all the time",
    ],
    "generalized_anxiety": [
        "anxious all the time", "anxious about everything", "constant anxiety",
        "always anxious", "background anxiety", "panic attacks",
        "panic disorder",
    ],
    "clinical_other": [
        "ocd", "obsessive thoughts i can't stop", "bipolar", "manic episode",
        "hearing voices", "seeing things that aren't there", "dissociate",
        "dissociating", "psychosis",
    ],

    # 4. Physical health risk
    "disordered_eating": [
        "binge", "purge", "starving myself", "not eating", "restricting food",
        "body image",
    ],
    "substance_use": [
        "drinking too much", "can't stop drinking", "addicted",
        "using again", "relapsed", "doing drugs to cope",
    ],

    # 5. Chronic/identity-level pattern
    "chronic_pattern": [
        "always been like this", "for years", "every time", "my whole life",
        "as long as i remember",
    ],

    # 6. Needs licensed/specialized expertise
    "legal": [
        "custody", "criminal charge", "arrested", "immigration status",
        "getting deported", "lawsuit",
    ],
    "medical": [
        "what medication should", "is this symptom", "chest pain",
        "should i go to the er", "my medication",
    ],
    "financial_crisis": [
        "in serious debt", "about to be evicted", "can't pay rent",
        "bankruptcy",
    ],
    "mandatory_reporting": [
        "my parent hits me", "someone is hurting a child", "underage and",
    ],

    # 7. Severe relational dynamics
    "relational_severe": [
        "he controls", "she controls", "won't let me leave",
        "afraid of my partner", "he hit me", "she hit me",
        "being harassed", "being stalked", "sexual assault",
    ],

    # 8. Out-of-scope meta
    "meta_diagnosis_request": [
        "do i have anxiety disorder", "do i have depression",
        "am i bipolar", "diagnose me", "what's wrong with me clinically",
    ],
    "meta_medication_request": [
        "should i take medication", "what dosage", "prescribe me",
    ],
}


def check_message(text: str) -> SafetyResult:
    lowered = text.lower()

    for kw in CRISIS_KEYWORDS:
        if kw in lowered:
            return SafetyResult(SafetyCategory.CRISIS, reason=kw)

    for kw in HOMICIDAL_KEYWORDS:
        if kw in lowered:
            return SafetyResult(SafetyCategory.CRISIS_OTHERS, reason=kw)

    for category, keywords in EXCLUSION_KEYWORDS.items():
        for kw in keywords:
            if kw in lowered:
                return SafetyResult(SafetyCategory.EXCLUDED, reason=category)

    return SafetyResult(SafetyCategory.IN_SCOPE)


CRISIS_OTHERS_RESPONSE = (
    "I'm not able to help plan or reason through harming someone else, "
    "and I want to take this seriously rather than move past it.\n\n"
    "If you're worried you might act on this, please contact emergency "
    "services or a crisis line right now -- in the US, call or text 988, "
    "or call 911 if it's immediate. If someone else is in danger, please "
    "make sure they're somewhere safe and get real support involved."
)

# Shown on the 2nd+ occurrence in the same session. Real, honest
# reasoning behind this: repeating the FULL explanatory paragraph
# every single message isn't adding safety once someone has already
# heard it -- it's just adding length, and real feedback found it can
# read as robotic or irritating in a way that risks reactance
# (people disengaging from or resisting a message they feel is being
# repeated AT them). Real crisis-response practice doesn't recite an
# identical script either -- it adapts while keeping the actual
# resource constant. So: the ACTIONABLE core (988, 911, "someone else
# in danger") is 100% preserved, unshortened, every time. Only the
# surrounding explanation is dropped after the first occurrence. ---
CRISIS_OTHERS_RESPONSE_CONDENSED = (
    "Still true: this isn't something I can help plan or reason through. "
    "988 (call or text) or 911 if it's immediate -- for you, or if "
    "someone else is in danger."
)

CRISIS_RESPONSE = (
    "It sounds like things are really hard right now, and I want to make "
    "sure you get real support, not just a conversation with me.\n\n"
    "If you're in the US, you can call or text 988 (Suicide & Crisis "
    "Lifeline) anytime, day or night. If you're outside the US, "
    "findahelpline.com can point you to a local crisis line.\n\n"
    "If you're in immediate danger, please contact emergency services."
)

# Same reasoning as above, applied to the self-harm crisis message.
CRISIS_RESPONSE_CONDENSED = (
    "Still here, and this is still real: 988 (call or text, US) or "
    "findahelpline.com outside the US -- anytime, not just right now. "
    "Emergency services if it's immediate."
)

EXCLUSION_RESPONSES = {
    "grief_loss": "What you've lost is real, and there's no fixing that -- I'm not going to pretend there's a next step that makes it okay. That kind of loss deserves someone who can actually sit with you in it properly, not a tool trying to reason through it. If a grief counselor feels out of reach: 988 (US) isn't only for emergencies, you can call or text it just to talk, and many areas have free, peer-run grief support groups, often through hospices or community centers.",
    "trauma_abuse_past": "What happened to you was real, and it makes sense that it's still with you. This is bigger than what I'm built to help with -- you deserve someone with real training in trauma, not my best guess. If cost is a barrier: community mental health centers often offer sliding-scale fees based on income, and RAINN's hotline (1-800-656-4673, US) is free and can point you toward trauma-informed support even if what happened wasn't recent.",
    "depression": "What you're carrying sounds heavy, and it's real -- that kind of persistent weight isn't nothing, and you're not wrong to feel it. I'm not the right one to help you work through it, though -- this needs someone who can actually stay with you in it properly. If a therapist isn't reachable right now: many communities have low-cost or sliding-scale mental health clinics, and 988 (US) can be called or texted any time, not just in a crisis, to talk and get pointed toward free local options.",
    "generalized_anxiety": "That constant, always-on anxiety is exhausting, and it's real -- not something to just push through alone. This deserves someone who can work with it directly, not a tool reasoning through it with you. If cost or access is the concern: sliding-scale community clinics exist in most areas, and many universities with counseling psychology programs offer low-cost sessions with supervised trainees.",
    "clinical_other": "This is outside what I'm able to help with responsibly. Please reach out to a doctor or mental health professional.",
    "disordered_eating": "I'm not the right tool for this. The National Alliance for Eating Disorders helpline can help you find real support.",
    "substance_use": "This deserves more support than I can give. SAMHSA's helpline (1-800-662-4357, US) is a good place to start.",
    "chronic_pattern": "What you're describing sounds like it's been part of your life for a long time, and that's genuinely hard to carry. This isn't a one-off to solve today -- it deserves real, ongoing support, not my best guess in the moment. If a therapist isn't accessible right now: many communities have free or low-cost peer support groups, and warmlines (non-crisis support lines, often free, staffed by trained peers) exist specifically for ongoing struggles, not just emergencies -- 988 (US) can point you to one local to you.",
    "legal": "This needs a licensed professional, not me -- please consult a lawyer for this.",
    "medical": "I can't advise on medical symptoms or medication -- please contact a doctor, or if urgent, go to an ER or call emergency services.",
    "financial_crisis": "This is bigger than a single decision I can help weigh -- a financial counselor or legal aid service would serve you better here.",
    "mandatory_reporting": "This is serious, and I want you to get real help. Please contact a trusted adult, or a service like Childhelp (1-800-422-4453, US) right away.",
    "relational_severe": "What you're describing matters and deserves real support. The National Domestic Violence Hotline (1-800-799-7233, US) can help, confidentially.",
    "family_coercion": "Being pressured or coerced by your own family into a major decision like this is a real violation of your say over your own life, and it deserves real support, not just conversation. The Tahirih Justice Center's Forced Marriage Initiative (preventforcedmarriage.org, 571-282-6161, weekday business hours) specializes specifically in this; outside those hours, the National Domestic Violence Hotline (1-800-799-7233, US, 24/7) can also help and point you toward the right local resources.",
    "peer_violence": "Sustained physical violence, even from a peer rather than an adult, isn't something to just manage alone -- it needs a real adult who can actually act on it. Please tell a trusted adult -- a parent, school counselor, or teacher -- directly and clearly what's been happening. If that feels hard to do alone, StopBullying.gov (a US government resource) has guidance on reporting and next steps.",
    "meta_diagnosis_request": "I can't diagnose anything -- that needs a licensed professional. I can help you think through a specific worry if that's useful.",
    "meta_medication_request": "I can't advise on medication -- please talk to a doctor or psychiatrist about that.",
    "unclear_classification": "I want to make sure I'm actually helping with the right thing -- could you tell me a bit more about what's going on?",
}