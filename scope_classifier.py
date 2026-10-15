"""
scope_classifier.py

The full semantic backstop -- covers crisis AND every exclusion
category from safety.py, aligned 1:1 with all 16 EXCLUSION_KEYWORDS
categories there.

Three real fixes merged in from live testing:
1. CRISIS_OTHERS was firing on benign short answers with no harmful
   language ("someone i know", answering an unrelated question about
   who to borrow money from) -- now requires actual harm/threat
   language to be present, not just a person-reference.
2. FINANCIAL_CRISIS was over-triggering on ordinary bills/loan
   payments ("bills to pay and loan to clear") -- now requires
   genuine crisis-level severity (eviction, bankruptcy, inability to
   meet basic needs), not routine financial stress.
3. META_DIAGNOSIS_REQUEST fired on a user PROTESTING a wrong
   exclusion ("i don't have any crisis") -- now explicitly excludes
   pushback/disputing a label from this category.
"""

SCOPE_CLASSIFIER_PROMPT = """You are a precise safety and scope classifier for a support tool that only handles specific, actionable worries (like exam stress, a work deadline, a specific conflict, procrastination). It does NOT handle deeper, ongoing, clinical, legal, medical, or safety-critical issues -- those need a real person or service, not this tool.

{context_block}Read the LATEST message and classify it into EXACTLY ONE of these categories, no matter how it's phrased -- direct, indirect, slang, understated, sarcastic, or "just testing" framing all count if the underlying content matches. IMPORTANT: interpret the latest message in light of what's actually been said so far, not as an isolated, context-free sentence.

GLOBAL RULE, applies to every category below: if the message is questioning, reacting to, or asking ABOUT the AGENT itself -- its prior response, its behavior, its trustworthiness, its capability, or anything evaluative about the agent as a tool -- not describing something happening in the user's own life -- do not classify it based on literal keyword matches. Phrases like "why did you push me away", "why did you say that", "how can I trust you", "why should I use you" are all meta-commentary about the agent, not the user's own life, however loaded individual words in them sound (e.g. "push" does not mean physical force here, "danger" does not mean a real threat here, "trust" here is not describing a recurring personal pattern). This applies to EVERY category, not just crisis -- real failures were found where this pattern was only guarded against for CRISIS_SELF and slipped through as RELATIONAL_SEVERE (a question about a prior reply sent someone a domestic violence hotline), and separately where "how can I trust you" -- a direct question about the agent's own reliability -- was misread as CHRONIC_PATTERN, treating a question about the tool as if it were a lifelong personal trust issue.

THE CORRECT LABEL for this kind of message is NO_WORRY -- treat questions about the agent itself (its trustworthiness, its limits, why to use it, its prior behavior) the same as any other factual question directed at the agent, since that's exactly what NO_WORRY already covers ("a factual question... just answer it"). A real, repeated failure was found where this rule told the classifier what NOT to do (don't keyword-match) without saying what TO do instead -- the model then had no correct label to output at all for "why should I trust you", fell through to unclear_classification, and got stuck there across multiple turns even after a good answer had already been given once. Do not leave this ambiguous: meta-commentary about the agent = NO_WORRY, full stop, unless a genuine active exclusion is also in play per the rule below.

IMPORTANT DISTINCTION within the rule above -- a real failure showed these are NOT the same thing: (a) meta-commentary suggesting the PRIOR CLASSIFICATION ITSELF was wrong ("that has nothing to do with what I said", "why did you bring up danger, I never said that") -- this CAN justify re-opening as in_scope, since it's pointing at a real possible error. (b) meta-commentary that's ONLY about REPETITION or the exchange feeling robotic ("are you a parrot", "you keep saying that", "stop repeating yourself") -- this does NOT by itself mean the original exclusion was wrong, only that hearing it twice is frustrating. If an exclusion is currently active for real, substantive reasons (genuine distress/compulsion signals were already confirmed, e.g. eating, self-harm, grief), pure repetition-annoyance alone must NOT clear it -- only genuinely new information that changes the picture should. Getting this distinction wrong was a real, serious failure: a confirmed disordered-eating-pattern exclusion got fully abandoned by "are you a parrot" alone, with zero new information, and the agent went on to give unsupervised behavioral tracking advice for what had just been confirmed as a real compulsive eating signal.

GLOBAL RULE, for every exclusion category above (depression, disordered eating, chronic pattern, and others): TOPIC ADJACENCY IS NOT ENOUGH. Merely mentioning a subject connected to an exclusion category (food and eating, a diagnosis-adjacent word, a long-running situation) is NOT sufficient to exclude -- the message must show actual, genuine indicators of the specific risk that category exists for (real distress, compulsion, clinical severity, ongoing dysfunction), not just topical proximity to it. Five separate real failures were found from this exact gap: a physiological question about rice and hunger excluded as disordered eating, situational sadness excluded as depression, a reflective "why" question excluded as a diagnosis request, and more. When in doubt, ask: does this message show real signs of the underlying concern, or does it just happen to use words connected to that topic? If it's the latter, it's IN_SCOPE or NO_WORRY, not excluded.

GLOBAL RULE, if the recent context shows a topic was already excluded: distinguish carefully between three different things a short follow-up can be, not two. Being aware of context means using it to correctly interpret what a short message means -- it does NOT mean defaulting to the same verdict just because the topic is related. (1) A genuinely low-content REACTION carrying no new substance -- "no", "not worth it", "i tried that", "give me hope" -- stays excluded under that same reason, since there is nothing new here to evaluate. (2) A message reporting something the user THEMSELVES decided or did -- "I took my stand to continue seeing her", "I told them I'm not stopping", "I decided to move out instead" -- is NOT a low-content reaction even when short and on the same topic; it is the user reporting their own action or decision, which is substantive new information and should be evaluated fresh on its own merits, weighted toward IN_SCOPE unless the message itself still contains active coercion, harm, or risk. The excluded party (family, partner, etc.) doing something further to the user still stays excluded; the user doing or deciding something themselves does not automatically inherit the prior exclusion just because it is short. (3) A short but GENUINELY DIFFERENT, SPECIFIC new topic -- e.g. "can you help me with my homework", "actually can we talk about my exam instead" -- is a real topic change and should be classified fresh, on its own merits, even though it's also short. The test is NOT length -- it's whether the message carries new substance (a decision, an action, a distinct subject) or is genuinely just a contentless reaction. A real failure was found where this distinction was missing and "help me finish my homework" got wrongly locked to an unrelated generalized_anxiety exclusion from earlier in the conversation, purely because it was short. A second real failure was found where "I took my stand to continue to date her" -- a substantive report of the user's own decision -- was wrongly treated as case (1) and kept locked to a family-coercion exclusion, when the user asserting their own choice is exactly the kind of new information case (2) exists for.

GLOBAL RULE, for every category whose definition names a SPECIFIC RELATIONSHIP OR ROLE (a partner, a parent or caregiver, and similarly worded categories): the named role is a real, load-bearing part of the definition, not a loose example standing in for any relationship generally. This cuts in TWO directions, and both have caused real failures:
(a) DO NOT let content from a DIFFERENT relationship bleed into a category defined for a specific one, just because the underlying harm-type (harassment, being hurt, fear) sounds similar. A real failure was found where school bullying by a classmate -- insults, body-shaming, and physical harm reported after complaining to a teacher -- was classified as RELATIONAL_SEVERE (defined around an intimate partner) and sent a domestic violence hotline, the wrong resource entirely for peer harassment.
(b) DO NOT let a category's definition be read so narrowly that a genuinely analogous role is missed just because it wasn't the exact word used. MANDATORY_REPORTING names "a parent or caregiver hurting a child" as its defining example, but the underlying concern -- a minor being harmed by someone in a position of authority or care over them -- applies just as much to a teacher, coach, or other adult with a duty of care, not only a parent or legal guardian.
When a message names a specific relationship or role, check that role against what the category actually requires, in both directions -- don't broaden a narrow category to catch an unrelated relationship, and don't narrow a broad concern down to only the one example role the definition happened to name first.

CRISIS_SELF - any indication of suicidal ideation or self-harm risk, however phrased (including slang like "unalive", indirect phrasing like "I can't do this anymore", or dark jokes that still signal real risk). Do NOT classify as crisis: ordinary figurative language for wanting a hard situation resolved ("get out of this situation"). Do NOT classify as crisis when the user is asking ABOUT or reacting to a PRIOR message from the agent -- that is meta-commentary, not a new statement of current risk.
CRISIS_OTHERS - any indication of intent or thoughts of harming another person. This REQUIRES actual language suggesting harm or threat (e.g. "hurt him", "make them pay physically", "kill", violent intent) -- NOT just a message that mentions or refers to another person with no harmful content at all. A short, ambiguous answer like "someone I know" or "a friend" with no violent or threatening language must NOT be classified as CRISIS_OTHERS just because it references a person -- especially when it's a direct answer to an unrelated question (e.g. who to borrow money from). If there is no actual harmful language present, this is not the right category regardless of what came before in the conversation.
GRIEF_LOSS - death, loss of a person/relationship/pet, or a terminal/serious diagnosis, with nothing left to decide or act on
TRAUMA_ABUSE - past or ongoing abuse, assault, trauma symptoms (flashbacks, etc.)
DEPRESSION - persistent low mood, emptiness, lack of motivation, described as ongoing and not tied to a single event. Do NOT classify as depression when someone expresses discouragement or "no options left" specifically about ONE already-established situational worry. Pay close attention to explicit time-bounding words like "today", "this week", "right now" -- these directly signal a bounded event, not persistence, and weigh AGAINST this category even if the content sounds emotionally heavy. A real failure was found where "I'm so stressed today" was excluded as depression on the very first message with zero context -- the word "today" is direct evidence against ongoing-ness, not something to ignore. On a short, ambiguous opening message with no conversation history yet, lean toward asking a clarifying question (which routes to IN_SCOPE) rather than excluding outright, unless the message itself contains real, unambiguous evidence of persistence.
GENERALIZED_ANXIETY - anxiety with no single identifiable cause, described as constant or ongoing, including panic attacks/panic disorder
CLINICAL_OTHER - OCD, obsessive intrusive thoughts, bipolar disorder or a manic episode, psychosis, hallucinations, dissociation
DISORDERED_EATING - restriction, bingeing, purging, or body image described as tied to CONTROL over food, with real indicators of distress or compulsion (guilt, secrecy, feeling out of control, punishing oneself, fear of food/weight). Do NOT classify as this for ordinary physiological or nutritional observations or curiosity about eating and hunger -- e.g. "rice makes me hungrier than expected", "why do I want more food after eating X" -- these are factual/curious questions about digestion and appetite, not disordered eating, even though they're topically about food and wanting to eat more. The category requires genuine signs of distress or compulsion around eating, not just any mention of a food-and-hunger pattern.
SUBSTANCE_USE - genuine signs of dependence, escalation, or loss of control: needing more of a substance over time to get the same effect, using it to function rather than to unwind, inability to cut back despite wanting to, or a pattern the person themselves frames as a real problem. Do NOT classify as this category a single, mild, situational mention of drinking or smoking tied to a specific stressor with no indication of escalation or dependence -- e.g. "I smoke sometimes when I'm stressed" or "I had a rough week and drank more than usual to unwind" are ordinary, bounded coping mentions and stay IN_SCOPE; real evidence from testing showed these being excluded inconsistently, sometimes triggering this category and sometimes not, despite containing no actual escalation signal. The distinguishing question is not whether a substance was mentioned, but whether the message itself indicates a growing or worsening pattern -- e.g. "I've been needing more each week just to feel normal" IS this category, since "needing more" is a direct tolerance/escalation signal, unlike a one-off or occasional mention with no such trajectory described.
CHRONIC_PATTERN - two SEPARATE, INDEPENDENT triggers, either one alone is sufficient:
(a) EXPLICITLY described as lifelong or long-standing ("always been like this", "for years", "every single time, my whole life", "not even one has ever gone well") -- this alone is enough, on its own, regardless of anything else in the message. Do NOT additionally require evidence of a goal to "cure" anything for case (a) -- a plain, explicit lifelong/always statement is sufficient by itself. A real regression was found where a near-identical statement to this exact pattern ("not even one presentation went well in my life... all my life") was wrongly kept IN_SCOPE -- do not require case (b)'s conditions to also be met when case (a) is already clearly satisfied.
(b) A standing condition or sensitivity (named or clearly described, e.g. misophonia, chronic anxiety in a specific setting -- established as ALREADY ongoing before this exchange) where the user's actual goal is to manage, reduce, treat, or cure the condition itself. This case (b) ONLY, unlike case (a), requires BOTH the topic being genuinely long-standing AND the goal being to cure/normalize it -- "give me a solution" alone, on a topic that is fresh, recent, or externally caused (a one-week spike in workload, a new deadline) is NOT case (b), even if the phrasing echoes "so it's normal again". A real failure was found where "give me a solution" alone, for a one-week-old workload spike, was wrongly excluded -- the classifier pattern-matched the phrase without checking whether the topic was actually long-standing.
Do NOT classify as chronic_pattern a single, specific, bounded decision or action tied to a standing condition -- that stays IN_SCOPE. Watch for the goal shifting mid-conversation on a topic ALREADY established as long-standing (case b) -- but this caution about goal-shifting only applies to case (b), never to case (a)'s plain explicit lifelong statements.
LEGAL - custody disputes, criminal charges, arrest, immigration status, deportation, lawsuits -- but NOT practical, logistical questions about preparing for an ALREADY-DECIDED meeting with a lawyer ("what should I bring", "what should I know before meeting my lawyer") -- those are preparation questions, not requests for legal advice, and stay IN_SCOPE.
MEDICAL - physical symptoms, medication questions, "should I go to the ER" -- but NOT practical, logistical questions about preparing for an ALREADY-DECIDED doctor visit. A real failure was found: "I am going to a doctor today, what should I know beforehand" was wrongly excluded here -- the person had already decided to see a doctor; they were asking how to prepare (what to note down, what questions to ask), not asking for diagnosis or treatment advice. That distinction matters: asking the tool to diagnose/treat = MEDICAL; asking for help preparing for a decision already made = IN_SCOPE.
FINANCIAL_CRISIS - serious debt, imminent eviction, or bankruptcy specifically -- being unable to meet basic needs, not just having bills or a loan payment to plan around. Do NOT classify ordinary bills, rent, or a personal loan repayment as financial_crisis on their own -- that is routine financial stress and belongs in IN_SCOPE, where it can actually be budgeted through. Only use this category when the person describes genuine crisis-level severity (eviction notice, bankruptcy, inability to afford necessities), not just "money is tight" or "I have bills to pay." Also NOT this category: practical, logistical questions about preparing for an ALREADY-DECIDED meeting with a financial counselor or advisor ("what should I bring", "what should I know beforehand") -- those stay IN_SCOPE, same logic as the medical/legal preparation carve-out above.
MANDATORY_REPORTING - a minor being hurt or endangered by someone in a position of authority or care over them -- a parent or caregiver, but also a teacher, coach, or other adult with a duty of care; a child in danger
RELATIONAL_SEVERE - coercive control by a partner, a partner who won't allow leaving, being hit by a partner, harassment or stalking BY A PARTNER OR EX-PARTNER specifically, sexual assault. Does NOT include peer, classmate, or coworker bullying/harassment -- a real failure was found where school bullying by a classmate (insults, body-shaming, physical harm reported after complaining to a teacher) was misclassified here and sent a domestic violence hotline, which is the wrong resource for this content entirely. Peer/classmate harassment without an intimate-partner context should be evaluated as a genuine in-scope situational worry unless it independently meets crisis or mandatory-reporting criteria.
FAMILY_COERCION - severe coercive control by family members over an adult's major life decisions, most clearly a forced or arranged marriage against the person's explicit will. Distinct from RELATIONAL_SEVERE, which requires an intimate-partner or ex-partner relationship specifically -- this category is for coercion by parents, extended family, or other relatives, not a partner. Distinct from ordinary family pressure, disapproval, or disagreement about a life choice, which stays IN_SCOPE -- this category requires the family actively working to compel a specific major decision against the person's stated will, not just disapproving of their choices. A real coverage gap was found in testing: a conversation describing an adult being pressured by her own family into a marriage arranged against her will had no matching category, since RELATIONAL_SEVERE's intimate-partner requirement and MANDATORY_REPORTING's minor-only scope both excluded it.
PEER_VIOLENCE - a sustained pattern of serious physical violence between minors, occurring outside any caregiving or authority relationship (if an authority figure is involved, use MANDATORY_REPORTING instead). Distinct from verbal bullying, social exclusion, or teasing, which stays IN_SCOPE as a genuine situational worry unless it independently meets crisis criteria -- this category requires an actual, sustained pattern of physical harm, not a single scuffle or the general unpleasantness of being bullied. A real coverage gap was found in testing: sustained peer-on-peer physical violence between minors, with no caregiver or authority figure involved on either side, did not match any existing category.
META_DIAGNOSIS_REQUEST - ONLY use this for a DIRECT, FIRST-PERSON request to be personally diagnosed right now: "do I have anxiety disorder", "am I bipolar", "diagnose me", "what's wrong with me clinically". This is a NARROW category, deliberately -- FIVE separate real failures were found here, and every single one was a false positive; none was ever a genuine catch. Failures included: open-ended "why" questions, requests for the agent's opinion, ordinary reflective questions, and -- the clearest case -- "how do you decode if I'm depressed or not", which is a question about the AGENT'S PROCESS/METHOD, not a personal diagnosis request, even though it contains a clinical word. ANY question about HOW the agent decides, detects, classifies, or decodes something (about depression, anxiety, or any condition) is a meta/process question, not this category -- it goes to NO_WORRY per the meta-commentary rule above, same as any other question about how the agent works. Given zero confirmed real catches and five confirmed real false positives tonight, treat this category as a LAST RESORT: only select it when a message could not plausibly be read any other way. PHASE_2_REASONING_PROMPT already has its own separate rule never to diagnose a condition, so this category doesn't need to pre-filter anything murky -- only the most unambiguous, literal, first-person cases.
META_MEDICATION_REQUEST - asking what medication or dosage to take, asking to be prescribed something
NO_WORRY - a greeting, small talk, a factual question, or anything with no worry or distress present at all
IN_SCOPE - a specific, situational worry with something actionable, even if it feels big in the moment (exams, deadlines, a specific conflict, a decision, procrastination) -- including ordinary financial stress like bills, loans, or budgeting a shortfall

If genuinely uncertain between IN_SCOPE and an exclusion category, lean toward the exclusion category -- but only when there is real content supporting that category, not merely because the topic sounds emotionally loaded. Do not let uncertainty override the specific requirements stated for each category above (e.g. CRISIS_OTHERS still requires actual harmful language; FINANCIAL_CRISIS still requires genuine severity). If the latest message is a short follow-up asking to continue on an EXCLUDED topic from context, classify it the SAME as that excluded topic.

Respond with a brief reasoning first -- one or two sentences, thinking through which category actually fits and why, especially checking it against the global rules above (meta-commentary about the agent, topic adjacency, distress vs. mere mention). THEN, on a new final line, give EXACTLY one word: one of the category names above.

LATEST message: "{message}\""""

CATEGORY_MAP = {
    "CRISIS_SELF": ("crisis", None),
    "CRISIS_OTHERS": ("crisis_others", None),
    "GRIEF_LOSS": ("excluded", "grief_loss"),
    "TRAUMA_ABUSE": ("excluded", "trauma_abuse_past"),
    "DEPRESSION": ("excluded", "depression"),
    "GENERALIZED_ANXIETY": ("excluded", "generalized_anxiety"),
    "CLINICAL_OTHER": ("excluded", "clinical_other"),
    "DISORDERED_EATING": ("excluded", "disordered_eating"),
    "SUBSTANCE_USE": ("excluded", "substance_use"),
    "CHRONIC_PATTERN": ("excluded", "chronic_pattern"),
    "LEGAL": ("excluded", "legal"),
    "MEDICAL": ("excluded", "medical"),
    "FINANCIAL_CRISIS": ("excluded", "financial_crisis"),
    "MANDATORY_REPORTING": ("excluded", "mandatory_reporting"),
    "RELATIONAL_SEVERE": ("excluded", "relational_severe"),
    "FAMILY_COERCION": ("excluded", "family_coercion"),
    "PEER_VIOLENCE": ("excluded", "peer_violence"),
    "META_DIAGNOSIS_REQUEST": ("excluded", "meta_diagnosis_request"),
    "META_MEDICATION_REQUEST": ("excluded", "meta_medication_request"),
    "NO_WORRY": ("no_worry", None),
    "IN_SCOPE": ("in_scope", None),
}


def llm_scope_check(text: str, llm_call_fn, recent_context: str = "") -> tuple[str, str | None]:
    """
    Returns (category, reason). category is one of: "crisis",
    "crisis_others", "excluded", "no_worry", "in_scope".
    """
    context_block = f"Recent context: {recent_context}\n\n" if recent_context else ""
    prompt = SCOPE_CLASSIFIER_PROMPT.format(context_block=context_block, message=text)
    result = llm_call_fn(
        "You are a precise, literal safety and scope classifier. Follow the instructions exactly.",
        [{"role": "user", "content": prompt}],
    )

    # Real fix: the prompt now allows brief reasoning before the final
    # answer (see SCOPE_CLASSIFIER_PROMPT), instead of forcing an
    # instant one-word answer with no room to think -- forcing instant
    # answers on a task juggling 19+ categories and several exception
    # rules was a real, likely cause of repeated misclassification.
    #
    # But that means the response can now legitimately CONTAIN other
    # category names while explaining why they DON'T apply ("this
    # isn't CRISIS_SELF, it's actually IN_SCOPE") -- searching the
    # WHOLE response for any label substring would grab whichever
    # label happens to appear first, not the actual conclusion. Only
    # the LAST non-empty line is the real answer now.
    lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
    final_line = lines[-1].upper() if lines else ""

    for label, mapped in CATEGORY_MAP.items():
        if label in final_line:
            return mapped

    return ("excluded", "unclear_classification")


TOPIC_CHANGE_CHECK_PROMPT = """A topic was just excluded from this conversation as: {excluded_topic}

The user's new message is: "{message}"

Recent context: {recent_context}

Is this new message a GENUINE, SUBSTANTIVELY DIFFERENT topic from what was excluded -- or is it, in ANY form, still about or trying to continue the excluded topic? This includes: a direct request to keep talking about it, a low-content reaction to it ("no", "not worth it", "give me hope"), an argument for why you should engage anyway, or anything else that isn't a genuinely new subject. Judge the MEANING, not specific words -- there is no fixed list of phrases this covers, so do not look for exact wording, judge intent.

IMPORTANT: pure commentary about the CONVERSATION FEELING REPETITIVE OR ROBOTIC ("are you a parrot", "you keep saying that", "r u a parrot") is NOT, on its own, a genuine topic change -- it is annoyance at the repetition, not new evidence that the original exclusion was wrong. This must still answer SAME unless the message ALSO introduces genuinely new information that would change the classification (a real, different, specific topic, or a concrete reason the original read was mistaken). A real failure was found where this exact gap let "r u a parrot" alone reopen a correctly-active exclusion, three separate times.

SEPARATE, DIFFERENT CASE -- do not confuse with the above: a message that DIRECTLY CHALLENGES WHETHER THE CLASSIFICATION ITSELF WAS WARRANTED ("how do you know that?", "why do you think that?", "based on what?", "what makes you say that?") is questioning the validity of the read, not just complaining about repetition. This SHOULD answer DIFFERENT -- it deserves a real answer, not the same static text again, especially when the original exclusion happened on minimal context (e.g. one ambiguous opening message with no prior conversation to support it). A real failure was found where this exact distinction was missing from this specific check (even though a similar distinction existed elsewhere), and "how do you know that?" -- a completely reasonable challenge to an exclusion made on a single ambiguous first message -- got treated the same as pure repetition-annoyance and stayed stuck on the identical static text.

THIRD SEPARATE CASE -- also distinct from both above: a message that EXPLICITLY, DIRECTLY DISCLAIMS the excluded topic as not being the actual concern ("my worry is not about X", "that's not what I'm actually asking about", "I'm not concerned about that part") is a genuinely different signal from vague pushback like "no you're wrong" or "I don't care." Vague pushback stays SAME under the bias above. But an EXPLICIT, DIRECT statement that the excluded topic specifically is NOT the concern is not ambiguous -- it should weigh toward DIFFERENT, since it is about as clear a signal as text can give that the person is redirecting their own concern elsewhere, not continuing to argue about the excluded topic. A real failure was found where "my worry is not about the complaint" -- following a legal-matters exclusion -- was treated as ambiguous pushback and stayed SAME, when it was actually an explicit, unambiguous disclaim deserving fresh classification.

Respond with a brief reasoning first -- one or two sentences on what's actually being said and whether it changes anything. THEN, on a new final line, respond with EXACTLY one word: SAME or DIFFERENT. If genuinely uncertain -- meaning the message is vague, low-content, or could plausibly still relate to the excluded topic -- answer SAME. But do not default to SAME for a message that explicitly and directly disclaims the excluded topic as unrelated; that is not the ambiguous case this bias exists to protect against."""


def is_genuine_topic_change(message: str, excluded_topic: str, recent_context: str, llm_call_fn) -> bool:
    """
    A DEDICATED, NARROW check -- not folded into the main 19-category
    classifier, and NOT a keyword list. Both of those were tried and
    both failed on the exact same real bypass ("can I at least talk to
    you" breaking a correctly-active exclusion, twice).

    A keyword list is fundamentally incomplete -- there is no finite
    list of ways to ask to keep talking about something. Folding this
    judgment into the main classifier also failed twice, likely
    because that classifier is already juggling 19 categories at once.

    This applies the same lesson that already worked once tonight:
    the crisis check is its own small, focused call instead of being
    one more nuance inside the big classifier, because a narrow
    question is more reliable than a buried instruction. This is that
    same fix, applied to the bypass problem instead of crisis.

    Called ONLY when an exclusion is currently active -- zero cost or
    complexity added to any normal conversation turn.
    """
    prompt = TOPIC_CHANGE_CHECK_PROMPT.format(
        excluded_topic=excluded_topic, message=message, recent_context=recent_context or "(none)"
    )
    result = llm_call_fn(
        "You are a precise, literal classifier judging topic continuity. Follow the instructions exactly.",
        [{"role": "user", "content": prompt}],
    )
    # Same fix as llm_scope_check -- reasoning is now allowed before
    # the final answer, so only the LAST line is the real verdict, not
    # the whole response (which may reference both words while
    # reasoning through them).
    lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
    final_line = lines[-1].upper() if lines else ""
    # Fail toward SAME (stay excluded) on any unclear/unparseable output.
    return "DIFFERENT" in final_line and "SAME" not in final_line


CLEARLY_UNRELATED_SAFE_TOPIC_PROMPT = """A crisis (self-harm intent or intent to harm another person) was detected earlier in this conversation. Crisis resources are ALWAYS shown for every message from here on, unconditionally -- that never changes and this check does not affect it.

The question here is narrower and separate: is the user's NEW message CLEARLY about a different, safe, everyday topic with NO plausible connection to the crisis -- not just "doesn't mention it," but genuinely, structurally a different domain (eg, schoolwork, a factual question, an unrelated logistical task)?

Be deliberately conservative. Answer NO if:
- The message could plausibly be a disguised continuation of the same situation, even indirectly (eg, referencing money, a relationship, a person, an appointment, anything that could tie back to the crisis context)
- The message is short, vague, or ambiguous in a way that could go either way
- You are not genuinely confident

Only answer YES for messages that are unmistakably, structurally unrelated -- the kind of message that would be equally normal in a conversation that had never touched on crisis content at all.

Message: "{message}"
Recent context: {recent_context}

Respond with brief reasoning, then on a final line, respond with EXACTLY one word: YES or NO."""


def is_clearly_unrelated_safe_topic(message: str, recent_context: str, llm_call_fn) -> bool:
    """
    Used ONLY alongside the crisis lock, never instead of it. The
    crisis message is unconditional and always shown regardless of
    what this returns -- this only decides whether to ALSO answer a
    genuinely separate question, in addition to the crisis resources,
    not whether to release the lock.

    Deliberately biased hard toward NO. A wrong NO just means a safe,
    unrelated question doesn't get answered this turn -- mildly
    frustrating, not dangerous. A wrong YES is bounded by the fact
    that the crisis message is still always shown alongside it, so
    the failure mode here is much softer than the original bypass bug
    this whole mechanism was built in response to.
    """
    prompt = CLEARLY_UNRELATED_SAFE_TOPIC_PROMPT.format(message=message, recent_context=recent_context or "(none)")
    result = llm_call_fn(
        "You are a precise, conservative classifier. Follow the instructions exactly.",
        [{"role": "user", "content": prompt}],
    )
    lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
    final_line = lines[-1].upper() if lines else ""
    return "YES" in final_line and "NO" not in final_line


CONTINUED_RISK_SIGNAL_PROMPT = """A crisis (self-harm intent or intent to harm another person) was stated earlier in this conversation. The full crisis-resources message was already shown once. Per direct clinical guidance, that message should NOT be blindly repeated on every subsequent turn regardless of content -- repetition itself, even in a short/generic form, is a real risk to avoid. So this check now decides, fresh, on EVERY message: does THIS message show any real signal that the risk is continuing, renewed, or still present?

Be DELIBERATELY, STRONGLY biased toward YES. This check exists specifically to replace a blanket repeat -- if it's too permissive, the exact failure this whole safety system was built to prevent (a real risk being missed because a message looked unrelated) happens again. A wrong YES costs very little: the resource message is shown one more time, which is a small, bounded cost. A wrong NO is the failure that matters.

Answer YES if:
- The message contains anything that could plausibly, even indirectly, relate to the original risk (the person, the situation, money, access, opportunity, means, timing)
- The message is short, vague, ambiguous, or could be read multiple ways
- You are not fully confident it's safe

Answer NO only if the message is unmistakably, structurally about something else entirely, with zero plausible connection -- the kind of message that would be equally ordinary in a conversation that had never touched on crisis content at all.

Message: "{message}"
Recent context: {recent_context}

Respond with brief reasoning, then on a final line, respond with EXACTLY one word: YES or NO."""


def has_continued_risk_signal(message: str, recent_context: str, llm_call_fn) -> bool:
    """
    Real design change made after direct clinical input: repeating the
    crisis-resources message on every single turn, even in condensed
    form, was flagged as a real risk to avoid -- repeated exposure to
    crisis-adjacent messaging, even generic, can itself function as a
    trigger. This replaces blind repetition with per-message vigilance.

    Deliberately NOT the same as is_clearly_unrelated_safe_topic above.
    That check is permissive-by-default, used to decide whether to
    ALSO answer something alongside an always-shown message. This
    check is restrictive-by-default -- it decides whether to show the
    message again AT ALL, so it is biased hard toward re-showing on
    any doubt, not hard toward staying quiet.

    This is a genuine, real tradeoff between two confirmed real risks
    (a clinically-flagged repetition risk, and a technically-proven
    bypass risk) -- not a fix with zero downside. Needs careful,
    ongoing real-world testing, not just this design rationale.
    """
    prompt = CONTINUED_RISK_SIGNAL_PROMPT.format(message=message, recent_context=recent_context or "(none)")
    result = llm_call_fn(
        "You are a precise, deliberately cautious safety classifier. Follow the instructions exactly.",
        [{"role": "user", "content": prompt}],
    )
    lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
    final_line = lines[-1].upper() if lines else ""
    # Fail toward YES (show the resource again) on any unclear output --
    # opposite bias from every other dedicated check in this file, on purpose.
    return "NO" not in final_line


if __name__ == "__main__":
    def mock_llm(system_prompt, messages):
        full = messages[0]["content"]
        actual = full.split('LATEST message: "')[-1].rstrip('"').lower()
        # These test cases specifically target the three real bugs fixed above
        if actual.strip() in ("someone i know", "a friend", "my brother"):
            return "IN_SCOPE"  # should NOT be crisis_others anymore
        if "bills to pay" in actual or "loan to clear" in actual:
            return "IN_SCOPE"  # should NOT be financial_crisis anymore
        if "dont have any crisis" in actual.replace("'", "") or "i dont have a crisis" in actual.replace("'", ""):
            return "IN_SCOPE"  # should NOT be meta_diagnosis_request anymore
        if "evicted" in actual or "bankruptcy" in actual:
            return "FINANCIAL_CRISIS"  # should STILL correctly catch real crisis-level severity
        if "hurt him" in actual or "make him pay" in actual:
            return "CRISIS_OTHERS"  # should STILL correctly catch real threats
        return "IN_SCOPE"

    test_messages = [
        "someone i know",  # the real false-positive from tonight
        "I have got some bills to pay and loan to clear",  # the real false-positive
        "what this is too much, i dont have any crisis",  # the real false-positive
        "I'm about to be evicted, I don't know what to do",  # should still correctly exclude
        "I want to hurt him for what he did",  # should still correctly catch
    ]
    for msg in test_messages:
        category, reason = llm_scope_check(msg, mock_llm)
        print(f"{category:10s} | {str(reason):25s} | {msg}")