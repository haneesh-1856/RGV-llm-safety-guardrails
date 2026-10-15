"""
run_classification_test.py

Runs a large, ground-truthed set of statements through the REAL,
FULL pipeline (run_pipeline), recording the complete verbatim agent
response for each statement into classification_results.csv.

This calls the full pipeline, not just the isolated classifier --
so acknowledgment text, redirect selection, and every fix made to
the pipeline itself (not only the classifier) are exercised exactly
as a real user would experience them. Each statement gets a fresh,
isolated session, matching the original single-statement, no-prior-
context testing methodology -- session state never carries over
between statements, avoiding the cross-statement contamination bug
found during earlier manual testing.

No automated pass/fail verdict is computed. A plain string comparison
between the classifier's category and the expected label cannot
replicate real judgment calls -- several statements in the original
150-statement evaluation were correctly handled through a different
pathway than the one they were designed to test (e.g. a diagnostic
request correctly declined through ordinary conversation rather than
the formal exclusion category), and pure string matching would have
scored those as failures despite the actual behavior being right.
The "match" column is deliberately left blank for you to fill in
yourself after reading each full_agent_response -- the same way the
original, more careful evaluation was actually done. "auto_hint" is
included only as a rough, non-authoritative pointer to help you scan
faster; treat it as a hint to check, never as a verdict.

Usage:
    python run_classification_test.py classification_test_set.csv
"""

import csv
import sys
import os
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import run_pipeline, PipelineOutcome
from agent import claude_llm_call, claude_scope_check_call

# Maps the pipeline's outcome enum (plus exclusion_reason, when set)
# back to the ground-truth labels used in the test CSV.
OUTCOME_LABELS = {
    PipelineOutcome.CRISIS: "CRISIS_SELF",
    PipelineOutcome.CRISIS_OTHERS: "CRISIS_OTHERS",
    PipelineOutcome.NO_WORRY: "NO_WORRY",
    PipelineOutcome.HANDLED: "IN_SCOPE",
}


def normalize_result(outcome, exclusion_reason):
    if outcome == PipelineOutcome.EXCLUDED and exclusion_reason:
        return exclusion_reason.upper()
    return OUTCOME_LABELS.get(outcome, f"UNKNOWN({outcome})")


def run_test(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    results = []

    for i, row in enumerate(rows):
        expected = row["expected_category"]
        statement = row["statement"]
        level = row.get("level", "")
        confidence = row.get("ground_truth_confidence", "SOLID")

        print(f"[{i+1}/{len(rows)}] {row['id']} ({expected}, level {level}): {statement[:60]}...")

        # Fresh, unique session per statement -- no shared state,
        # no prior conversation, matching the original isolated
        # single-statement testing methodology exactly.
        session_id = f"classtest-{row['id']}-{uuid.uuid4().hex[:8]}"

        try:
            result = run_pipeline(
                session_id,
                statement,
                history=[],
                llm_call_fn=claude_llm_call,
                crisis_llm_call_fn=claude_scope_check_call,
            )
            actual = normalize_result(result.outcome, result.exclusion_reason)
            full_response = result.reply
        except Exception as e:
            actual = f"ERROR({e})"
            full_response = f"[ERROR during pipeline run: {e}]"

        # No automated pass/fail verdict is recorded here. A plain
        # string comparison (actual == expected) can't replicate real
        # judgment calls -- e.g. a statement correctly handled through
        # a different pathway than the one it was designed to test
        # still deserves a "Y", and pure string matching can't see
        # that. "auto_hint" is kept only as a rough, non-authoritative
        # pointer to help you scan faster; "match" is left blank for
        # you to fill in after actually reading full_agent_response,
        # the same way the original, more careful evaluation was done.
        auto_hint = "possible-match" if actual == expected else "check-this-one"

        results.append({
            "id": row["id"],
            "expected": expected,
            "actual": actual,
            "auto_hint": auto_hint,
            "match": "",  # fill in Y / N / AMBIGUOUS yourself after reading full_agent_response
            "level": level,
            "ground_truth_confidence": confidence,
            "statement": statement,
            "full_agent_response": full_response,
        })

        print(f"  -> {actual} [{auto_hint}]")
        time.sleep(0.5)

    # Write full results -- every row, including AMBIGUOUS ones, with
    # the complete verbatim agent response for each statement, so you
    # can read each one and fill in "match" yourself. auto_hint is a
    # rough pointer only, not a verdict -- do not treat it as scoring.
    with open("classification_results.csv", "w", newline="", encoding="utf-8") as f:
        fieldnames = ["id", "expected", "actual", "auto_hint", "match", "level", "ground_truth_confidence", "statement", "full_agent_response"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(results)

    print("\n" + "=" * 60)
    print(f"Ran {len(results)} statements through the full pipeline.")
    print("No automated accuracy score is computed -- 'match' is left")
    print("blank in classification_results.csv for you to fill in")
    print("yourself after reading each full_agent_response. 'auto_hint'")
    print("is a rough pointer only (whether the category name matched")
    print("exactly), not a real verdict -- some statements correctly")
    print("handled through a different pathway will show 'check-this-one'")
    print("even though the actual behavior was right.")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_classification_test.py classification_test_set.csv")
        sys.exit(1)
    run_test(sys.argv[1])