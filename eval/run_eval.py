"""
Run: python eval/run_eval.py   (from the project root)

Checks the safety layer against test_cases.py and reports pass/fail.
No API calls, no cost -- this only tests the deterministic keyword
layer, which is exactly the part that needs to be bulletproof before
anything touches the LLM.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safety import check_message
from eval.test_cases import TEST_CASES


def run():
    passed = 0
    failed = 0

    for message, expected_category, expected_reason in TEST_CASES:
        result = check_message(message)
        ok = result.category == expected_category and (
            expected_reason is None or result.reason == expected_reason
        )
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"[{status}] \"{message}\"")
        if not ok:
            print(f"        expected: {expected_category} / {expected_reason}")
            print(f"        got:      {result.category} / {result.reason}")

    print(f"\n{passed} passed, {failed} failed out of {len(TEST_CASES)}")


if __name__ == "__main__":
    run()