# RGV Revision Plan: Changes After the JMIR AI Decision

**Status:** The manuscript *"RGV, a Bounded Large Language Model–Based Conversational Tool With Multilayer Safety Guardrails: System Design and Adversarial Safety Evaluation Study"* was not accepted by JMIR AI (October 2026).
**Purpose:** This document lists each problem raised in the decision letter, what we found when we checked the code and data, and what we will change before a new evaluation and resubmission.

---

## 1. Summary

| Question | Answer |
|---|---|
| Were the editor's concerns valid? | **Yes.** Checking the code and the transcripts confirmed every point. |
| Can the existing 100 transcripts be reused as evidence? | **No.** A state reset bug let state from earlier conversations leak into later ones. These transcripts are now treated as **pilot data** only. |
| What happens next? | Fix the code, build a scripted rerun harness, pre-register the protocol, and have independent blinded raters score the outputs. |
| Estimated time before raters start | About 1.5 to 2.5 weeks of part-time work. |

---

## 2. Editor's criticisms and our response

| # | Criticism in the decision letter | What we found | Change we will make |
|---|---|---|---|
| E1 | **Multi-turn test cases were not independent.** | Confirmed. In the evaluated web UI, the Start/End buttons cleared the message history but not the session state. In **38 of 41** (v1) and **39 of 41** (v2) worry conversations, the first worry turn was already in Phase 2, so Ground was skipped. Pacing counters, grief counters and exclusion context also carried over. | Every conversation gets a fresh `Session`, which an automated reset test checks and the per-turn logs confirm. The rerun calls `run_pipeline()` directly with a new `session_id` for each script, without the browser or its cookies. |
| E2 | **Ground and pacing conclusions are invalidated.** | Confirmed. The manuscript reported "Ground ran in only 3 of 50" and early usefulness check-ins as **design behaviour**. They were mostly **artifacts of the reset bug**. | These findings will be removed. The Ground and pacing behaviour will be measured again in the clean rerun. |
| E3 | **Self-evaluation bias.** | Confirmed. The same person wrote the test inputs, ran them and scored them. The version comparison was done with help from AI tools. | Use independent raters who don't know which version produced each output. Raters get a shuffled rater sheet with no version or route labels. Scenario scripts will be written partly by someone other than the developer. |
| E4 | **Scoring was changed post hoc.** | Confirmed. Three different denominators (133/133/134) were later normalised to 150, and a convergence denominator changed (78% → 92.9%). | Fix the rubric, the outcomes and the denominators in an OSF pre-registration **before** any run. The pre-registration will also set rules for handling errors and missing turns. |
| E5 | **The convergence metric was guaranteed to succeed.** | Confirmed. The tester knew the intended end point and steered the conversation toward it. | Drop this metric, or rate it from fixed scripts written by someone else, with raters who don't know the intended end point. |
| E6 | **Geographic variables were not in the protocol.** | Confirmed. Crisis and redirect resources are hard-coded for the US (988, 911, RAINN, SAMHSA). In 7 conversations set in India, 5 (v1) and 4 (v2) were given **only US numbers**. | State the target population and locale in the protocol. Then localise the resources to it (for example, Tele-MANAS and 112 for India, with the numbers checked before use), or limit the study to one country. Resource localisation becomes a pre-specified outcome. |

---

## 3. Code changes required

### 3.1 Blockers

- **State reset:** add `SessionStore.reset()`, `reset_session()` and a call to it from `/reset`. Add tests that show a new conversation starts with `phase == DETACHMENT`, all counters at 0 and `last_exclusion_reason is None`. Also test that two session IDs never share state.
- **Version control:** put all evaluation code in this repository, and tag the exact commit used for the rerun. The paper will cite that tag.

### 3.2 Safety defects

| # | Defect | Fix |
|---|---|---|
| S1 | The keyword crisis layer has false positives that skip the classifier. Examples: "wasn't around", "going to hurt my GPA", "Suicide Squad" and "can't go on a trip" all match as crisis. | Tighten or remove phrases that are too broad, or send keyword hits through the classifier for confirmation. Add these phrases as "must NOT be crisis" regression cases. |
| S2 | Crisis resources are US-only. | Localise them to match the locale in the protocol (see E6). |
| S3 | MANDATORY_REPORTING (child-abuse hotline) is given to adults. | Require an explicit minor for this category. Send adult exploitation to a separate route. |
| S4 | When the classifier's output can't be parsed, it silently becomes an exclusion (`unclear_classification`). | Log the raw classifier output, retry once, and report parse failures as a separate outcome. |
| S5 | API errors in the web path return HTTP 500, and the UI shows "(no reply)". | Catch errors, return a fixed safe message, and log the turn as `ERROR`. |
| S6 | Code comments still describe the removed crisis lock. | Rewrite the comments so they match current behaviour. |

### 3.3 Pacing and phase logic

| # | Defect | Fix |
|---|---|---|
| P1 | The check-in and offer-concrete prompts both fire on turns 12, 24, …, which gives the model conflicting instructions. | Make them mutually exclusive. |
| P2 | Moving from Phase 1 to Phase 2 depends only on the turn count (2 turns), and a new worry never returns the conversation to Phase 1. | Define a readiness or new-worry signal, or state in the protocol that the transition always happens after 2 turns. |
| P3 | The grief-presence cap counts turns per session, not per grief thread. | Reset the cap when the topic changes, or document that it applies per conversation. |
| P4 | Condensed crisis texts are defined but never used. | Use them or delete them. |

### 3.4 Reproducibility

| # | Gap | Fix |
|---|---|---|
| R1 | Classifier labels are not logged. | For every turn, write a JSONL line with the raw classifier output, label, route, phase, counters, model IDs, timestamp and git commit. |
| R2 | The model is set by an alias, and no temperature is set. | Pin exact model snapshot IDs, set the temperature, and record both in the protocol. |
| R3 | Dependencies are not pinned. | Pin `requirements.txt` and record the Python version. |
| R4 | The template file is named `Index.html` but the code loads `index.html`, which breaks on Linux and macOS. | Rename the file to `index.html`. |
| R5 | Dead safety code is shipped, including `crisis_classifier.py` and unused helpers in `scope_classifier.py`. | Delete it or move it to `archive/`. |
| R6 | The automated tests cover only the keyword layer. | Add the reset, isolation, phase and checkpoint tests, plus the keyword regression set. |

---

## 4. Psychologist's review: protocol decisions

The psychologist reviewer's remaining points are mostly **protocol decisions**, not bugs. They will be settled in the pre-registration:

- An operational definition of "bounded situational worry", and of the line between it and a clinically significant presentation.
- What counts as "ready" to move from **Ground to Reason**, and tests for problem-solving that starts too early.
- Using **controllability** carefully for problems that are structural or relational, such as bullying, discrimination, financial hardship or family power dynamics.
- A **no-action / uncertainty pathway** for situations that have no good solution.
- Tests for **reassurance loops**, where the same worry is presented again and again.
- **Longitudinal safety**: a conversation that starts benign and gradually becomes higher risk.
- Explicit rules for **ambiguous or borderline cases**, with **false positives and false negatives** both reported.
- **Cultural and intersectional** scenarios, and no assumptions about which supports are available to the user.
- Whether **minors** are in scope. If they are, the protocol needs explicit procedures for age-specific safety, consent/assent and escalation.
- **Informed consent** that covers being an AI, its limitations and how data are handled.
- Checks for **perceived authority or dependence**, and for appropriate challenge versus automatic agreement.
- A clear statement that the evaluation measures **conversational safety, not clinical efficacy**.

---

## 5. Behaviour issues not caused by the reset bug

The reset fix won't remove these. They will be fixed, or measured and reported honestly, in the rerun:

- Wrong redirect category for the relationship (peer bullying was sent to a domestic violence hotline).
- The "no direct solution" rule breaks under sustained pressure. It is enforced only in the prompt.
- Redirect text is sometimes duplicated within one reply.
- Some crisis routing was missed or delayed (for example, "I don't care what it takes").
- The classifier sometimes reads time-bounded distress as chronic ("lately" was labelled CHRONIC_PATTERN).
- Version 2 is more over-cautious and wordy (17–32% more words).
- Conversations 009 and 039, in which the developer discussed the project with the system, will be excluded by design.

---

## 6. New evaluation plan

1. **Freeze** one version (v2), apply the fixes above, and tag the commit.
2. **Pre-register** on OSF: the population and locale, the scenario list, the outcomes, the rubric with examples for each score, the denominators, the rules for errors and missing turns, and the agreement statistic.
3. **Run** the scripted harness: one fresh session per script, JSONL logs, and a blinded rater sheet export.
4. **Rate** the outputs with independent, blinded raters after a practice set that is not taken from the study data.
5. **Report** the results as an adversarial safety evaluation. The old transcripts will be described as pilot data used to design the new test set.

## 7. Readiness checklist

- [ ] Reset fix merged, with the reset and isolation tests passing
- [ ] Keyword false positives fixed (S1)
- [ ] Locale chosen and resources matched to it (S2, E6)
- [ ] Error handling and per-turn JSONL logging added (S4, S5, R1)
- [ ] Models pinned and temperature set (R2)
- [ ] Checkpoint conflict fixed (P1), and dead code removed (R5)
- [ ] Rerun harness tested on a dry run of 3–5 scripts
- [ ] Rubric with examples for each score, and a practice set
- [ ] Protocol pre-registered on OSF
- [ ] Ethics committee approval, or a documented exemption
